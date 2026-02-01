import json
import pytesseract
import re
import os
from pathlib import Path
from dotenv import load_dotenv
from PyPDF2 import PdfReader, PdfWriter
from pdf2image import convert_from_path
from prompts import get_batch_split_prompt
from openai import OpenAI
from main import process_single_pdf

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def process_splitted_pdfs_local(split_dir):
    """
    Process split PDFs from a local folder.
    Saves outputs locally as usual (EXTRACTED_DIR, OUTPUTS_DIR, signature data).
    """
    split_dir = os.path.abspath(split_dir)
    if not os.path.exists(split_dir):
        print(f"❌ Folder does not exist: {split_dir}")
        return []

    pdf_files = [
        os.path.join(split_dir, f)
        for f in os.listdir(split_dir)
        if f.lower().endswith(".pdf")
    ]
    pdf_files.sort()  # optional, to keep them in order

    all_results = []

    for pdf_path in pdf_files:
        print(f"📄 Processing {pdf_path}...")
        result = process_single_pdf(pdf_path, original_filename=os.path.basename(pdf_path))
        all_results.append(result)

    print("🎉 All split documents processed locally!")
    return all_results


def extract_text_from_pdf(pdf_path):
    """Extract text per page from a PDF."""
    reader = PdfReader(pdf_path)
    texts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip() == "":
            print(f"⚠️ Page {i+1} had no text, running OCR...")
            images = convert_from_path(pdf_path, first_page=i+1, last_page=i+1)
            text = pytesseract.image_to_string(images[0])
        texts.append({"page": i + 1, "text": text})
        print(f"📄 Extracted text from page {i+1} ({len(text)} chars)")
    return texts


def split_pdf_by_ranges(pdf_path, ranges, output_dir):
    """Split the PDF into multiple sub-documents based on page ranges."""
    reader = PdfReader(pdf_path)
    Path(output_dir).mkdir(exist_ok=True)
    split_files = []

    for i, r in enumerate(ranges):
        writer = PdfWriter()
        for page_num in range(r["start_page"] - 1, r["end_page"]):
            writer.add_page(reader.pages[page_num])
        out_path = Path(output_dir) / f"doc_{i + 1}.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)
        split_files.append(str(out_path))
        print(f"✅ Saved: {out_path}")

    return split_files


def parse_llm_json(result):
    """Strip markdown code fences and parse JSON safely."""
    if not result:
        return None

    cleaned = re.sub(r"^```(?:json)?|```$", "", result.strip(), flags=re.MULTILINE)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        print("❌ JSON decode error. Cleaned LLM output:")
        print(cleaned)
        return None


def analyze_batch_with_llm(pages):
    """Call LLM to identify document boundaries."""
    try:
        truncated_pages = [{"page": p["page"], "text": p["text"]} for p in pages]
        prompt = get_batch_split_prompt(json.dumps(truncated_pages, indent=2))

        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        result = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )

        llm_output = result.choices[0].message.content
        parsed = parse_llm_json(llm_output)

        if parsed is None:
            print("❌ LLM output could not be parsed as JSON")
            print("Raw output from LLM (not parsed):")
            print(llm_output)
        return parsed

    except Exception as e:
        print(f"❌ Error analyzing batch: {e}")
        return None


def main():
    """Main function to split a batch PDF."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python batch_split.py <pdf_path> [output_dir]")
        print("Example: python batch_split.py batch.pdf batch_output_docs")
        return

    class Args:
        pdf_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else "batch_output_docs"

    args = Args()

    # Step 1 - extract text
    print("📖 Extracting text from PDF...")
    pages = extract_text_from_pdf(args.pdf_path)
    if not pages:
        print("❌ No text extracted")
        return
    print(f"✅ Extracted {len(pages)} pages")

    # Step 2 - analyze with LLM
    print("🤖 Calling LLM to identify document boundaries...")
    llm_response = analyze_batch_with_llm(pages)
    if not llm_response or "documents" not in llm_response:
        print("❌ Failed to analyze batch or invalid response")
        return

    print("✅ LLM Response:")
    print(json.dumps(llm_response, indent=2))

    # Step 3 - split PDF by identified ranges
    split_pdf_by_ranges(args.pdf_path, llm_response["documents"], args.output_dir)
    print("🎉 Batch split completed successfully!")

    # Optional: process extracted PDFs
    # process_splitted_pdfs_local(args.output_dir)


if __name__ == "__main__":
    main()
