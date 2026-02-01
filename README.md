# MedDoc Analyzer

**An intelligent medical document processing system powered by AI**

*Automate document classification, signature detection, and data extraction from medical PDFs*

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Documentation](#-documentation)

</div>

---

## 📋 Overview

**MedDoc Analyzer** is a comprehensive Flask-based web application designed to streamline medical document processing workflows. It leverages AWS Textract for OCR and form field detection, combined with OpenAI GPT models for intelligent document classification and information extraction.

The system processes batch PDF documents, automatically splits them into individual files, extracts structured data, detects signature fields, and classifies documents into predefined medical categories—all through an intuitive web interface.

## ✨ Features

### Core Capabilities

- 🔄 **Batch PDF Processing**: Automatically split multi-document PDFs into individual files using AI-powered boundary detection
- 📄 **Intelligent Text Extraction**: Extract text from PDFs using AWS Textract with OCR fallback support
- ✍️ **Signature Field Detection**: Automatically detect empty physician signature fields and associated date fields
- 🤖 **AI-Powered Classification**: Classify documents into 65+ medical document categories using GPT models
- 📊 **Structured Data Extraction**: Extract key information including:
  - Patient name and date of birth
  - Signer name and NPI (National Provider Identifier)
  - Document category and metadata
- 🎨 **Visual Annotation**: Generate annotated images highlighting signature and date field locations
- 📋 **Cover Sheet Detection**: Automatically identify and process fax cover sheets
- 💾 **Export Capabilities**: Export results to CSV for further analysis

### Technical Highlights

- **Dual AI Integration**: Combines AWS Textract for form analysis and OpenAI GPT for classification
- **Smart Document Splitting**: Uses LLM to intelligently identify document boundaries based on content
- **Coordinate Validation**: Visual validation of detected signature coordinates on PDF pages
- **Responsive Web Interface**: Modern, intuitive UI for batch processing and document review

## 🚀 Prerequisites

Before you begin, ensure you have the following:

- **Python 3.11+** installed on your system
- **AWS Account** with Textract service access
  - IAM user with `textract:AnalyzeDocument` permissions
  - AWS credentials configured
- **OpenAI API Key** for document classification
  - Account with access to GPT-4o or compatible models
- **Git** (optional, for cloning the repository)

## 📦 Installation

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd MedDoc-Analyzer
```

### Step 2: Set Up Virtual Environment

```bash
# Create virtual environment
python -m venv myenv

# Activate virtual environment
# On macOS/Linux:
source myenv/bin/activate

# On Windows:
myenv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Create a `.env` file in the root directory:

```bash
# Flask Configuration
FLASK_SECRET_KEY=your-secret-key-here-change-in-production

# OpenAI API Configuration
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-4o  # Optional, defaults to gpt-4o

# AWS Configuration (for Textract)
AWS_ACCESS_KEY_ID=your-aws-access-key-id
AWS_SECRET_ACCESS_KEY=your-aws-secret-access-key
AWS_DEFAULT_REGION=us-east-1
```

> ⚠️ **Important**: Never commit the `.env` file to version control. It's already included in `.gitignore`.

## Usage

### Running the Flask App

```bash
python flask_app.py
```

The application will be available at `http://localhost:5001`

### Command Line Usage

#### Process a single PDF:
```bash
python main.py path/to/document.pdf
```

#### Split a batch PDF:
```bash
python batch_split.py path/to/batch.pdf [output_directory]
```

## Project Structure

```
.
├── flask_app.py          # Main Flask application
├── main.py               # Core processing pipeline
├── batch_split.py        # Batch PDF splitting functionality
├── cover_page.py         # Cover page detection
├── validate_coordinates.py  # Signature coordinate validation
├── prompts.py            # GPT prompts for classification
├── templates/            # HTML templates
├── static/               # CSS and static files
├── uploads/             # Uploaded files (gitignored)
├── batch_output_docs/   # Split documents (gitignored)
├── EXTRACTED_DIR/       # Extracted text (gitignored)
├── OUTPUTS_DIR/         # CSV outputs (gitignored)
├── annotated_pages/     # Annotated images (gitignored)
└── signature data/      # Signature JSON data (gitignored)
```

## Environment Variables

- `FLASK_SECRET_KEY`: Secret key for Flask sessions (required)
- `OPENAI_API_KEY`: OpenAI API key (required)
- `OPENAI_MODEL`: OpenAI model to use (optional, defaults to gpt-4o)
- `AWS_ACCESS_KEY_ID`: AWS access key for Textract (required)
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for Textract (required)
- `AWS_DEFAULT_REGION`: AWS region (defaults to us-east-1)

## Security Notes

- Never commit `.env` files or sensitive data
- Change the default `FLASK_SECRET_KEY` in production
- Ensure AWS credentials have minimal required permissions
- Review and sanitize all uploaded documents before processing

