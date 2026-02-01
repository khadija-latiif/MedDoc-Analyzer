import fitz  # PyMuPDF
import json
from PIL import Image, ImageDraw, ImageFont
import os

def bbox_to_pixels(bbox, page_width, page_height):
    """Convert bounding boxes from normalized coordinates to pixels"""
    x0 = bbox['Left'] * page_width
    y0 = bbox['Top'] * page_height
    x1 = x0 + bbox['Width'] * page_width
    y1 = y0 + bbox['Height'] * page_height
    return x0, y0, x1, y1

def create_precise_bbox(bbox, page_width, page_height, padding=0):
    """Create a more precise bounding box with optional padding"""
    x0, y0, x1, y1 = bbox_to_pixels(bbox, page_width, page_height)
    # Add small padding to make the box more visible and precise
    return x0 - padding, y0 - padding, x1 + padding, y1 + padding

def split_signature_date_box(sig_bbox, page_width, page_height):
    """Split a single signature+date bounding box into two parts: left for signature, right for date"""
    x0, y0, x1, y1 = bbox_to_pixels(sig_bbox, page_width, page_height)

    # Calculate the split point (middle of the box)
    box_width = x1 - x0
    split_x = x0 + (box_width * 0.5)

    # Left half for signature (RED)
    sig_box = (x0, y0, split_x, y1)

    # Right half for date (BLUE)
    date_box = (split_x, y0, x1, y1)

    return sig_box, date_box

def validate_signature_coordinates(pdf_path, physician_signatures):
    """Validate Textract signature & date bounding boxes by drawing them on PDF pages"""

    # Step 1: Load the PDF
    print(f"Loading PDF: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return

    # Print page dimensions
    for page_num in range(len(doc)):
        page = doc[page_num]
        width, height = page.rect.width, page.rect.height

    # Step 2: Load the signature data
    try:
        with open(physician_signatures, "r") as f:
            signatures = json.load(f)
        print(f"Loaded {len(signatures)} entries")
    except Exception as e:
        print(f"Error loading signature data: {e}")
        return

    # Output directory for annotated images
    output_dir = "annotated_pages"
    os.makedirs(output_dir, exist_ok=True)

    # Step 3: Process each page
    for page_num in range(len(doc)):
        try:
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # high res
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img)

            # Filter signatures for this page - only process the selected signature
            page_signatures = [sig for sig in signatures if sig['page'] == page_num + 1]
            print(f"Found {len(page_signatures)} entries on page {page_num + 1}")

            # Only process the first (selected) signature field, not all detected ones
            if page_signatures:
                sig = page_signatures[0]  # Only process the selected signature
                # Physician signature bbox
                sig_bbox = sig.get("signature_bbox") or sig.get("signature_bbox_norm") or sig.get("bounding_box")
                # Nearest date bbox - access the correct nested structure
                nearest_date = sig.get("nearest_empty_date", {})
                date_bbox = nearest_date.get("bbox") if nearest_date else None

                if sig_bbox:
                    # Additional check: only highlight if this is truly an empty signature field
                    signature_label = sig.get("signature_label", "").lower()
                    print(f"  Processing signature field: '{signature_label}'")

                    page_width = page.rect.width * 2
                    page_height = page.rect.height * 2

                    # Check if we have separate signature and date fields (different bounding boxes)
                    if date_bbox and date_bbox != sig_bbox:
                        # Signature rectangle in RED
                        x0, y0, x1, y1 = create_precise_bbox(sig_bbox, page_width, page_height, padding=1)
                        draw.rectangle([x0, y0, x1, y1], outline="red", width=2)
                        label = sig.get("signature_label", "physician_signature")
                        draw.text((x0, max(0, y0 - 25)), f"Signature: {label}", fill="red", font=ImageFont.load_default())

                        # Date rectangle in BLUE
                        dx0, dy0, dx1, dy1 = create_precise_bbox(date_bbox, page_width, page_height, padding=1)
                        draw.rectangle([dx0, dy0, dx1, dy1], outline="blue", width=2)
                        dlabel = nearest_date.get("field_name", "date")
                        draw.text((dx0, max(0, dy0 - 25)), f"Date: {dlabel}", fill="blue", font=ImageFont.load_default())
                    else:
                        # We have 1 bounding box - split it into 2 parts (left=signature, right=date)
                        sig_box, date_box = split_signature_date_box(sig_bbox, page_width, page_height)

                        # Left half for signature (RED)
                        draw.rectangle(sig_box, outline="red", width=2)
                        label = sig.get("signature_label", "physician_signature")
                        draw.text((sig_box[0], max(0, sig_box[1] - 25)), f"Signature: {label}", fill="red", font=ImageFont.load_default())

                        # Right half for date (BLUE)
                        draw.rectangle(date_box, outline="blue", width=2)
                        draw.text((date_box[0], max(0, date_box[1] - 25)), f"Date: Date", fill="blue", font=ImageFont.load_default())

            # Save annotated image
            output_path = os.path.join(output_dir, f"annotated_page_{page_num+1}.png")
            img.save(output_path)
            print(f"Saved annotated page: {output_path}")

        except Exception as e:
            print(f"Error processing page {page_num + 1}: {e}")
            continue

    doc.close()

    print("\n Validation complete!")

# if __name__ == "__main__":

#     pdf_path = "New Testing Docs/fa301d80-12ff-49f8-bcf4-ea1ae2c95594.pdf"
#     signature_file = "signature data/fa301d80-12ff-49f8-bcf4-ea1ae2c95594.json"

#     if os.path.exists(pdf_path) and os.path.exists(signature_file):
#         validate_signature_coordinates(pdf_path, signature_file)
#     else:
#         print(f"PDF: {pdf_path} - {'exists' if os.path.exists(pdf_path) else 'missing'}")
