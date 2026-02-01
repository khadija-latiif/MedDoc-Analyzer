import os
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF for PDF preview
from PIL import Image
import io
import base64

# Import existing functionality
from batch_split import extract_text_from_pdf, analyze_batch_with_llm, split_pdf_by_ranges
from main import process_single_pdf, EXTRACTED_DIR, SIGNATURE_DATA_DIR, ANNOTATED_PAGES_DIR, OUTPUTS_DIR
from cover_page import analyze_cover_page_with_llm

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'change-this-secret-key-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['BATCH_OUTPUT_FOLDER'] = 'batch_output_docs'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB max file size

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['BATCH_OUTPUT_FOLDER'], exist_ok=True)
os.makedirs(EXTRACTED_DIR, exist_ok=True)
os.makedirs(SIGNATURE_DATA_DIR, exist_ok=True)
os.makedirs(ANNOTATED_PAGES_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Store session data (in production, use Redis or database)
batch_sessions = {}


def get_pdf_thumbnail(pdf_path, page_num=0):
    """Generate base64 encoded thumbnail of PDF first page"""
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None

        page = doc[page_num]
        # Render at lower resolution for thumbnail
        pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        doc.close()

        return img_str
    except Exception as e:
        print(f"Error generating thumbnail: {e}")
        return None


@app.route('/')
def index():
    """Home page - batch upload"""
    return render_template('index.html')


@app.route('/upload_batch', methods=['POST'])
def upload_batch():
    """Handle batch PDF upload and splitting"""
    if 'batch_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['batch_file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are allowed'}), 400

    try:
        # Save uploaded file
        filename = secure_filename(file.filename)
        batch_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(batch_path)

        # Step 1: Extract text from batch PDF
        print(f"📖 Extracting text from {filename}...")
        pages = extract_text_from_pdf(batch_path)

        if not pages:
            return jsonify({'error': 'Failed to extract text from PDF'}), 500

        # Step 2: Analyze with LLM to find document boundaries
        print("🤖 Analyzing document boundaries with LLM...")
        llm_response = analyze_batch_with_llm(pages)

        if not llm_response or 'documents' not in llm_response:
            return jsonify({'error': 'Failed to identify document boundaries'}), 500

        # Step 3: Split PDF into individual documents
        print("✂️ Splitting PDF into individual documents...")
        split_files = split_pdf_by_ranges(
            batch_path,
            llm_response['documents'],
            app.config['BATCH_OUTPUT_FOLDER']
        )

        # Generate thumbnails and metadata for each split document
        split_docs_data = []
        for idx, pdf_path in enumerate(split_files):
            doc_name = os.path.basename(pdf_path)
            thumbnail = get_pdf_thumbnail(pdf_path)

            # Get page count
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            doc.close()

            # Check if this is a cover sheet
            doc_info = llm_response['documents'][idx]
            is_cover_sheet = doc_info.get('is_cover_sheet', False)

            # Set display name based on whether it's a cover sheet
            if is_cover_sheet:
                display_name = "Cover Sheet"
            else:
                display_name = doc_name

            split_docs_data.append({
                'id': idx + 1,
                'filename': doc_name,
                'display_name': display_name,
                'path': pdf_path,
                'thumbnail': thumbnail,
                'page_count': page_count,
                'page_range': f"{doc_info['start_page']}-{doc_info['end_page']}",
                'is_cover_sheet': is_cover_sheet
            })

        # Store session data
        session_id = filename.replace('.pdf', '')
        batch_sessions[session_id] = {
            'original_file': filename,
            'split_docs': split_docs_data,
            'batch_path': batch_path
        }

        return redirect(url_for('batch_results', session_id=session_id))

    except Exception as e:
        print(f"Error processing batch: {e}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500


@app.route('/batch_results/<session_id>')
def batch_results(session_id):
    """Display all split documents from batch"""
    if session_id not in batch_sessions:
        return "Session not found", 404

    session_data = batch_sessions[session_id]
    return render_template('batch_results.html',
                         session_id=session_id,
                         original_file=session_data['original_file'],
                         documents=session_data['split_docs'])


@app.route('/process_document/<session_id>/<int:doc_id>')
def process_document(session_id, doc_id):
    """Process individual document through main pipeline"""
    if session_id not in batch_sessions:
        return "Session not found", 404

    session_data = batch_sessions[session_id]

    # Find the document
    doc_info = None
    for doc in session_data['split_docs']:
        if doc['id'] == doc_id:
            doc_info = doc
            break

    if not doc_info:
        return "Document not found", 404

    try:
        # Clear previous annotated images to avoid showing old images
        if os.path.exists(ANNOTATED_PAGES_DIR):
            files_removed = 0
            for file in os.listdir(ANNOTATED_PAGES_DIR):
                file_path = os.path.join(ANNOTATED_PAGES_DIR, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    files_removed += 1
            if files_removed > 0:
                print(f"🧹 Cleared {files_removed} old annotated images")

        # Check if this is a cover sheet
        is_cover_sheet = doc_info.get('is_cover_sheet', False)

        # Process through main pipeline (for text extraction and annotation)
        print(f"\n🔄 Processing document {doc_info['filename']}...")
        result = process_single_pdf(doc_info['path'], original_filename=doc_info['filename'])

        # Get extracted text
        doc_name_no_ext = os.path.splitext(doc_info['filename'])[0]
        text_file = os.path.join(EXTRACTED_DIR, f"{doc_name_no_ext}.txt")
        extracted_text = ""
        if os.path.exists(text_file):
            with open(text_file, 'r', encoding='utf-8') as f:
                extracted_text = f.read()

        # If it's a cover sheet, analyze with cover page function
        cover_page_result = None
        if is_cover_sheet and extracted_text:
            print("Analyzing cover sheet...")
            cover_page_result = analyze_cover_page_with_llm(extracted_text)

        # Get signature data
        signature_file = os.path.join(SIGNATURE_DATA_DIR, f"{doc_name_no_ext}.json")
        signature_data = []
        if os.path.exists(signature_file):
            with open(signature_file, 'r') as f:
                signature_data = json.load(f)

        # Get annotated images
        annotated_images = []
        if os.path.exists(ANNOTATED_PAGES_DIR):
            for filename in sorted(os.listdir(ANNOTATED_PAGES_DIR)):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    annotated_images.append(filename)

        print(f"✅ Found {len(annotated_images)} annotated images for {doc_info['filename']}")

        return render_template('document_detail.html',
                             session_id=session_id,
                             doc_id=doc_id,
                             doc_info=doc_info,
                             result=result,
                             cover_page_result=cover_page_result,
                             extracted_text=extracted_text,
                             signature_data=signature_data,
                             annotated_images=annotated_images)

    except Exception as e:
        print(f"Error processing document: {e}")
        return f"Error processing document: {str(e)}", 500


@app.route('/annotated_image/<filename>')
def serve_annotated_image(filename):
    """Serve annotated images"""
    return send_from_directory(ANNOTATED_PAGES_DIR, filename)


@app.route('/pdf_preview/<session_id>/<int:doc_id>')
def pdf_preview(session_id, doc_id):
    """Generate PDF preview image"""
    if session_id not in batch_sessions:
        return "Session not found", 404

    session_data = batch_sessions[session_id]
    doc_info = None
    for doc in session_data['split_docs']:
        if doc['id'] == doc_id:
            doc_info = doc
            break

    if not doc_info:
        return "Document not found", 404

    thumbnail = get_pdf_thumbnail(doc_info['path'])
    if thumbnail:
        return jsonify({'thumbnail': thumbnail})
    else:
        return jsonify({'error': 'Could not generate preview'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)

