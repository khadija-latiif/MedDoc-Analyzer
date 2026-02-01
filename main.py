import os
import boto3
import json
import fitz
import math
import csv
import io
import numpy as np
import re
from PIL import Image
from dotenv import load_dotenv
from openai import OpenAI
from prompts import get_combined_prompt
from validate_coordinates import validate_signature_coordinates

# Load environment variables
load_dotenv()

# ============
# Text Normalization
# ============
def normalize_text(text):
    """
    Normalize text by removing special characters, punctuation, and extra whitespace
    to better detect truly empty signature fields
    """
    if not text:
        return ""

    # Convert to lowercase
    text = text.lower().strip()

    # Remove common punctuation and special characters (keep only alphanumeric and spaces)
    text = re.sub(r'[^\w\s]', '', text)

    # Remove extra whitespace and normalize
    text = re.sub(r'\s+', ' ', text).strip()

    # Handle common OCR artifacts and empty indicators
    text = text.replace('_', '')  # Remove underscores that might be OCR artifacts
    text = text.replace('-', '')  # Remove hyphens
    text = text.replace('.', '')  # Remove periods
    text = text.replace('x', '')  # Remove x's that might be placeholders
    text = text.replace(' ', '')  # Remove all spaces after other processing

    return text

def is_signature_field_empty(value_text):
    """
    Check if a signature field is truly empty after normalization
    """
    if not value_text:
        return True

    # Normalize the text
    normalized = normalize_text(value_text)

    # Check if normalized text is empty or contains only common empty indicators
    empty_indicators = ['', 'n/a', 'na', 'none', 'blank', 'empty', 'null', 'void']

    # Check for patterns that indicate empty fields after normalization
    is_empty_after_normalization = (
        len(normalized) == 0 or  # Completely empty after removing special chars
        normalized in empty_indicators or  # Common empty indicators
        # Check for patterns like "x", "xx", "xxx" that might be placeholders
        (len(normalized) <= 3 and all(c == 'x' for c in normalized)) or
        # Check for very short strings that are likely artifacts
        (len(normalized) <= 2 and normalized.isalpha())
    )

    return is_empty_after_normalization

# ============
# Textract APIs
# ============
def call_textract_layout(image_bytes):
    client = boto3.client('textract', region_name="us-east-1")
    return client.analyze_document(
        Document={'Bytes': image_bytes},
        FeatureTypes=['LAYOUT']
    )

def call_textract_forms(image_bytes):
    client = boto3.client('textract', region_name="us-east-1")
    return client.analyze_document(
        Document={'Bytes': image_bytes},
        FeatureTypes=['FORMS']
    )

# ============
# Layout Utils
# ============
def get_line_blocks(textract_resp):
    lines = []
    for b in textract_resp.get('Blocks', []):
        if b.get('BlockType') == 'LINE':
            geom = b['Geometry']['BoundingBox']
            lines.append({
                'Text': b.get('Text', ''),
                'Box': (geom['Left'], geom['Top'], geom['Width'], geom['Height']),
                'Confidence': b.get('Confidence', 0)
            })
    return lines

def detect_empty_signature_slot(image, line_block,
                                extend_right=0.4, extend_down=0.2,
                                margin=0.01, blank_threshold=0.95):
    W, H = image.size
    l, t, w, h = line_block['Box']
    abs_l = int(l * W)
    abs_t = int(t * H)
    abs_w = int(w * W)
    abs_h = int(h * H)

    crop_left = abs_l + abs_w + int(margin * W)
    crop_top = max(abs_t - int(margin * H), 0)
    crop_w = min(int(W * extend_right), W - crop_left)
    crop_h = min(int(H * extend_down), H - crop_top)

    if crop_w <= 0 or crop_h <= 0:
        return None, 0.0

    region = image.crop((crop_left, crop_top, crop_left + crop_w, crop_top + crop_h))
    region_np = np.array(region.convert('L'))
    white_frac = np.mean(region_np / 255.0 > 0.99)

    if white_frac >= blank_threshold:
        slot_box = (crop_left / W, crop_top / H, crop_w / W, crop_h / H)
        return slot_box, white_frac
    else:
        return None, white_frac

# ============
# Forms Utils
# ============
def get_key_value_pairs(textract_resp):
    blocks = textract_resp.get("Blocks", [])
    id_map = {b["Id"]: b for b in blocks}
    kv_pairs = []

    for b in blocks:
        if b.get("BlockType") == "KEY_VALUE_SET" and "KEY" in b.get("EntityTypes", []):
            key_text, value_text, value_box = "", "", None

            if "Relationships" in b:
                for rel in b["Relationships"]:
                    if rel["Type"] == "CHILD":
                        for cid in rel["Ids"]:
                            child = id_map[cid]
                            if "Text" in child:
                                key_text += child["Text"] + " "
                    if rel["Type"] == "VALUE":
                        for vid in rel["Ids"]:
                            vb = id_map[vid]
                            if "Relationships" in vb:
                                for r in vb["Relationships"]:
                                    if r["Type"] == "CHILD":
                                        for cid in r["Ids"]:
                                            child = id_map[cid]
                                            if "Text" in child:
                                                value_text += child["Text"] + " "
                            value_box = vb["Geometry"]["BoundingBox"]

            kv_pairs.append({
                "key": key_text.strip().lower(),
                "value": value_text.strip(),
                "bbox": value_box
            })

    return kv_pairs

def calculate_distance(b1, b2):
    c1 = (b1["Left"] + b1["Width"] / 2, b1["Top"] + b1["Height"] / 2)
    c2 = (b2["Left"] + b2["Width"] / 2, b2["Top"] + b2["Height"] / 2)
    return math.dist(c1, c2)

def find_nearby_empty_date_fields(sig_box, kv_pairs, max_dist=0.8, y_tolerance=0.2):
    """Find nearby empty date fields by normalizing text and checking if empty"""
    results = {"nearest": None, "all_within": []}
    sig_bbox = {"Left": sig_box[0], "Top": sig_box[1], "Width": sig_box[2], "Height": sig_box[3]}

    nearest_dist, nearest_date = float("inf"), None

    for kv in kv_pairs:
        if kv["bbox"] is None:
            continue

        # Check if it's a pure date field (not a signature field that happens to contain "date")
        key_lower = kv["key"].lower()
        is_date_field = ("date" in key_lower and
                        "signed" not in key_lower and
                        "signature" not in key_lower and  # Exclude any signature fields
                        "nurse" not in key_lower and
                        "therapist" not in key_lower)

        if is_date_field:
            # Check if the field is truly empty
            field_value = kv.get("value", "")
            is_empty = (not field_value or
                       field_value == '' or
                       field_value in ['', ' ', 'n/a', 'na', 'none', 'blank', 'empty', '--'])

            if is_empty:
                dist = calculate_distance(sig_bbox, kv["bbox"])
                y_diff = abs(kv["bbox"]["Top"] - sig_bbox["Top"])

                if dist <= max_dist and y_diff <= y_tolerance:
                    candidate = {"field_name": kv["key"], "bbox": kv["bbox"], "distance": dist}
                    results["all_within"].append(candidate)
                    if dist < nearest_dist:
                        nearest_dist, nearest_date = dist, candidate

    results["nearest"] = nearest_date
    return results

# ============
# Pipeline Directories
# ============
EXTRACTED_DIR = "EXTRACTED_DIR"
SIGNATURE_DATA_DIR = "signature data"
OUTPUTS_DIR = "OUTPUTS_DIR"
ANNOTATED_PAGES_DIR = "annotated_pages"

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ============
# Unified Textract Extraction
# ============
def extract_with_textract(pdf_file_path):
    """Extract text and signature data using improved Textract pipeline"""
    doc = fitz.open(pdf_file_path)

    all_text = []         # for full PDF text
    paired_results = []   # signature + nearest empty date

    for page_idx in range(doc.page_count):
        print(f"  Processing page {page_idx + 1}...")

        # Convert page to image
        page = doc[page_idx]
        img_bytes = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
        image = Image.open(io.BytesIO(img_bytes))

        # Layout analysis
        layout_resp = call_textract_layout(img_bytes)
        lines = get_line_blocks(layout_resp)
        for line in lines:
            all_text.append(f"Page {page_idx+1}: {line['Text']}")

        # Forms analysis to get actual empty signature fields from Textract
        forms_resp = call_textract_forms(img_bytes)
        kv_pairs = get_key_value_pairs(forms_resp)

        # Find the actual empty signature field detected by Forms API
        # Prioritize physician signature over other signature types
        signature_field = None
        physician_signature_field = None
        other_signature_field = None

        for kv in kv_pairs:
            key_lower = kv['key'].lower()
            value_text = kv.get('value', '').strip().lower()

            # Only look for physician-related signature fields, exclude nurse signatures
            is_signature_field = (
                # Broad signature patterns but exclude nurse/therapist signatures
                (key_lower.endswith('signature') and 'nurse' not in key_lower and 'therapist' not in key_lower) or
                (key_lower.endswith('signature:') and 'nurse' not in key_lower and 'therapist' not in key_lower) or
                ('signature' in key_lower and 'nurse' not in key_lower and 'therapist' not in key_lower) or
                # Specific physician signature patterns
                key_lower == 'physician signature' or
                key_lower == 'physician signature:' or
                key_lower == 'physician\'s signature:' or
                key_lower == 'attending physician\'s signature' or
                key_lower == 'attending physician\'s signature and date signed' or
                key_lower == 'signature of physician:' or
                key_lower == 'md signature' or
                key_lower == 'md signature:' or
                key_lower == 'md\'s signature:' or
                key_lower == 'practitioner signature:' or
                key_lower == 'practitioner\'s signature:' or
                # MD/Physician designations
                (key_lower == 'md' or key_lower == 'md:') or
                key_lower == 'physician' or
                key_lower == 'physician:' or
                # Certification fields (usually physician-signed)
                'certification' in key_lower or
                # Generic signature fields (but exclude nurse/therapist)
                (key_lower.startswith('sign') and 'field' in key_lower and 'nurse' not in key_lower and 'therapist' not in key_lower) or
                (key_lower.startswith('sign') and 'line' in key_lower and 'nurse' not in key_lower and 'therapist' not in key_lower)
            )

            # Check if the field is truly empty (no text, or only whitespace, or common empty indicators)
            is_empty = (not value_text or
                       value_text == '' or
                       value_text in ['', ' ', 'n/a', 'na', 'none', 'blank', 'empty', '--'])

            # Only process if it's a signature field AND truly empty
            if is_signature_field and is_empty:
                print(f"Found empty signature field: '{kv['key']}' with value: '{kv.get('value', '')}'")

                # Prioritize physician signature
                if 'physician' in key_lower:
                    physician_signature_field = kv
                else:
                    # Store other signature fields as fallback
                    if not other_signature_field:
                        other_signature_field = kv
            elif is_signature_field and not is_empty:
                print(f"Skipping filled signature field: '{kv['key']}' with value: '{kv.get('value', '')}'")

        # Use physician signature if found, otherwise use other signature
        signature_field = physician_signature_field or other_signature_field

        if signature_field:
            # Use the actual bounding box from Forms API
            sig_bbox = signature_field['bbox']
            slot_box = (sig_bbox['Left'], sig_bbox['Top'], sig_bbox['Width'], sig_bbox['Height'])

            # Check if signature field already contains date (combined signature+date field)
            signature_label_lower = signature_field['key'].lower()
            is_combined_signature_date = ('date' in signature_label_lower and 'signature' in signature_label_lower)

            # Only find separate date fields if this is not a combined signature+date field
            if is_combined_signature_date:
                print(f"Signature field already contains date: '{signature_field['key']}'")
                date_matches = {"nearest": None, "all_within": []}
            else:
                # Find nearby date fields
                date_matches = find_nearby_empty_date_fields(slot_box, kv_pairs)

            paired_results.append({
                "page": page_idx + 1,
                "signature_label": signature_field['key'],
                "signature_bbox": {
                    "Left": slot_box[0],
                    "Top": slot_box[1],
                    "Width": slot_box[2],
                    "Height": slot_box[3]
                },
                "nearest_empty_date": date_matches["nearest"],
                "all_nearby_empty_dates": date_matches["all_within"]
            })

    doc.close()
    return all_text, paired_results

# ============
# GPT Classification
# ============
def classify_and_extract(document_text: str) -> dict:
    """Classify and extract fields in one GPT call"""
    prompt = get_combined_prompt(document_text)

    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict medical document classifier and parser."},
            {"role": "user", "content": prompt}
        ],
    )

    # print("Raw GPT Response:", response.choices[0].message.content.strip())

    try:
        data = json.loads(response.choices[0].message.content.strip())
    except json.JSONDecodeError:
        data = {
            "category": "ERROR",
            "patient_name": "ERROR",
            "patient_dob": "ERROR",
            "signer_name": "ERROR",
            "signer_npi": "ERROR"
        }
    return data

# ============
# Save to CSV
# ============
def save_to_csv(doc_id: str, result: dict, output_dir: str):
    """Save classification and details into a CSV file"""
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "document_results.csv")
    file_exists = os.path.isfile(output_file)

    with open(output_file, mode="a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=["doc_id", "category", "patient_name", "patient_dob", "signer_name", "signer_npi"]
        )

        if not file_exists:
            writer.writeheader()

        row = {
            "doc_id": doc_id,
            "category": result.get("category", ""),
            "patient_name": result.get("patient_name", ""),
            "patient_dob": result.get("patient_dob", ""),
            "signer_name": result.get("signer_name", ""),
            "signer_npi": result.get("signer_npi", "")
        }
        writer.writerow(row)

    # print(f" Results saved to {output_file}")

# ============
# Main Orchestrator
# ============
def process_single_pdf(pdf_path: str, original_filename: str = None):
    """
    Process a single PDF through the complete pipeline.
    """
    pdf_filename = original_filename or os.path.basename(pdf_path)
    doc_id = os.path.splitext(pdf_filename)[0]

    print(f"\nProcessing: {pdf_filename}")

    # Step 1: Extract Text + Signature Data
    print("Step 1: Extracting text and signature data...")
    all_text, paired_results = extract_with_textract(pdf_path)

    # Save extracted text
    os.makedirs(EXTRACTED_DIR, exist_ok=True)
    text_file = os.path.join(EXTRACTED_DIR, f"{doc_id}.txt")
    with open(text_file, "w", encoding="utf-8") as f:
        f.write("\n".join(all_text))
    # print(f"Text saved to {text_file}")

    # Save signature data
    os.makedirs(SIGNATURE_DATA_DIR, exist_ok=True)
    signature_file = os.path.join(SIGNATURE_DATA_DIR, f"{doc_id}.json")
    with open(signature_file, "w") as f:
        json.dump(paired_results, f, indent=2)
    # print(f"Signature data saved to {signature_file}")

    # Step 2: Classify Document
    print("Step 2: Classifying document...")
    result = classify_and_extract("\n".join(all_text))
    save_to_csv(doc_id, result, OUTPUTS_DIR)
    print(f"Classified as: {result.get('category', '')}")

    # Step 3: Validate Coordinates
    print("Step 3: Validating coordinates...")
    validate_signature_coordinates(pdf_path, signature_file)
    print(f"Annotated images saved to {ANNOTATED_PAGES_DIR}")

    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python main.py <pdf_file_path>")
        print("Example: python main.py path/to/document.pdf")
        sys.exit(1)

    pdf_file = sys.argv[1]
    if not os.path.exists(pdf_file):
        print(f"Error: File not found: {pdf_file}")
        sys.exit(1)

    result = process_single_pdf(pdf_file)
    print("Final result:", result)
