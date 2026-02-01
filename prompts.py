# Document Categories - Organized by Type
# Structured format for better organization and maintenance

CATEGORIES = [
    # Medical Documentation & Records
    "Medical Photo Documentation",
    "Vital Signs Monitoring Record",
    "Medication Record",
    "Patient Condition Change Report",

    # Treatment Plans & Assessments
    "Treatment Plan Document",
    "Treatment Plan Update",
    "Clinical Service Assessment",
    "Service Episode Summary",
    "Service Eligibility Documentation",

    # Service Orders
    "Medical Service Order",
    "General Medical Service Order",
    "Interim Service Order",
    "Pharmaceutical Order",
    "Nutritional Service Order",
    "Medical Supplies Order",
    "Additional Service Request",

    # Therapy Services - Type A
    "Therapy Service Order - Type A",
    "Therapy Service Evaluation - Type A",
    "Therapy Service Certification - Type A",
    "Therapy Service Recertification - Type A",

    # Therapy Services - Type B
    "Therapy Service Order - Type B",
    "Therapy Service Evaluation - Type B",
    "Therapy Service Certification - Type B",
    "Therapy Service Recertification - Type B",

    # Therapy Services - Type C
    "Therapy Service Order - Type C",
    "Therapy Service Evaluation - Type C",
    "Therapy Service Certification - Type C",
    "Therapy Service Recertification - Type C",

    # Care Services - Type D
    "Care Service Order - Type D",
    "Care Service Certification - Type D",
    "Care Service Recertification - Type D",
    "Care Service Interim Order - Type D",

    # Care Services - Type E
    "Care Service Order - Type E",
    "Care Service Certification - Type E",
    "Care Service Recertification - Type E",
    "Care Service Interim Order - Type E",

    # Support Services
    "Support Services Evaluation",
    "Support Services Follow-up",

    # Provider Encounters
    "Primary Provider Encounter",
    "Provider Encounter Documentation",
    "Provider Encounter Documentation - Secondary",

    # Certifications & Authorizations
    "Service Authorization Form",
    "Financial Authorization Form",
    "Medical Necessity Documentation",
    "Medical Necessity Certificate",
    "Medical Equipment Necessity Certificate",
    "Dental Medical Clearance",
    "Terminal Condition Documentation",

    # Service Management
    "Service Agreement Document",
    "Service Resumption Documentation",
    "Service Discharge Order",
    "Service Duration Extension",

    # Recertifications
    "Standard Service Recertification",
    "Service Recertification Request",
    "Service Recertification - Alternative Format",

    # Certifications
    "Standard Service Certification",
    "Service Certification - Alternative Format",

    # Discharge Documentation
    "Discharge Documentation - Type A",
    "Discharge Documentation - Type B",
    "Discharge Documentation - Type C",
    "Discharge Documentation - Type D",
    "Discharge Documentation - Type E",
    "Discharge Documentation - Type F",
    "Discharge Documentation - Type G",

    # Communications
    "General Medical Communication"
]


def get_combined_prompt(document_text):
    categories_str = "\n".join(CATEGORIES)
    return f"""
    You are a medical document classification and extraction assistant.

    Your tasks:
    1. Read the provided document text.
    2. Classify the document into EXACTLY ONE of the following categories:
    {categories_str}
    3. Extract the following fields:
    - Patient Name
    - Patient DOB
    - Signer Name
    - NPI

    Rules:
    - "Signer Name" = the PHYSICIAN responsible for signing the order, even if the signature/date fields are blank.
      * Ignore other signatures such as nurses, therapists, or OTs.
      * Look for designations like "MD", "DO", "Physician", etc.
    - "NPI" = the National Provider Identifier. Look anywhere in the document where a numeric sequence follows "NPI", "NPI Number", or "NPI#" or "Qualifying Treating Physician's Billing Number".
      * Extract only digits (do not include extra text).
      * If multiple NPIs exist, choose the one associated with the PHYSICIAN.
    - Always return valid JSON only.
    - If a field is not found, use "NOT FOUND".
    - Category value must match one from the list exactly.

    Output format:
    {{
    "category": "...",
    "patient_name": "...",
    "patient_dob": "...",
    "signer_name": "...",
    "npi": "..."
    }}

    Document:
    {document_text}
        """


def get_batch_split_prompt(pages_json):
    return f"""
    You are an expert in medical document processing.

    The input is a batch PDF containing multiple sub-documents concatenated.

    Your task:
    1. Identify sub-documents, each with start_page and end_page.

    Special Rule — Cover Sheets:
    - If any page contains the phrase "cover sheet" (case insensitive), treat it as its own separate document.
    - Mark it with "is_cover_sheet": true in the output.
    - Cover sheets should always be single-page documents.

    **Rules for detecting sub-document boundaries:**

    1. **Patient Name Priority**
       - If a new patient name appears, start a new sub-document immediately.
       - Look for names such as "Mr. Saubhik Bhaumik", "Ms. Jane Doe", "Jane Smith", "Dorothy Adams", "Physician: John Doe", etc.
       - The same patient name may appear in multiple documents; do **not** merge documents with different headings unless it is an ADDENDUM.

    2. **Heading Detection**
       - Detect document types based on headings:
         - FAX COVER SHEET
         - HOME HEALTH CERTIFICATION AND PLAN OF CARE
         - ADDENDUM TO: PLAN OF TREATMENT
         - Supplemental Order
         - General Communication
       - **Important:**
         - ADDENDUM pages always belong to the immediately preceding sub-document. Merge ADDENDUM page(s) into the previous document's range.
         - **Any other heading change, even for the same patient, starts a new sub-document.**

    3. **Other Boundary Indicators**
       - Internal page numbering like "Page 1 of X" or "Page X of Y". A reset to "Page 1" may indicate a new document.
       - Document titles, section headers, or signature/date blocks at the bottom.
       - A cover sheet is always its own document.
       - Pages should remain contiguous, and independent documents should **never** be merged or duplicated.

    **Output Requirements**
    - Each sub-document may be one or multiple pages.
    - Merge ADDENDUM pages with the previous sub-document only.
    - Do not merge different headings for the same patient.
    - Do not repeat page numbers in multiple sub-documents.
    - Return JSON only, no extra text.
    - Output format:
    {{
      "documents": [
        {{"start_page": 1, "end_page": 2}},
        {{"start_page": 3, "end_page": 5}}
      ]
    }}

    Pages:
    {pages_json}
    """




def get_cover_page_prompt(document_text):
    return f"""
    You are a document intake assistant for medical fax transmissions.

    The input is the first page of a fax or email batch. Your tasks:
    1. Determine if this page appears to be a **Cover Page**.
       A cover page usually includes:
       - Sender or organization name
       - Recipient information (To:, Fax:, Phone:)
       - A date or subject line
       - A note or message (e.g., "Please see attached", "Urgent", "Patient documents enclosed")
       - It usually does NOT contain patient medical details or form fields.

    2. If it **is a cover page**, extract the following fields:
       - **is_cover_page**: true
       - **sending_organization**: The name of the sender or organization (e.g., "Home Health Provider", "Medical Organization")
       - **comments**: Any relevant free-text message, notes, or instructions included by the sender.

    3. If it **is NOT a cover page**, return:
       - **is_cover_page**: false
       - **sending_organization**: "N/A"
       - **comments**: "N/A"


    Output JSON format (valid JSON only):
    Example Output:
    {{
      "documents": [
        {{"start_page": 1, "end_page": 1, "is_cover_sheet": true}},
        {{"start_page": 2, "end_page": 3, "is_cover_sheet": false}},
        {{"start_page": 4, "end_page": 4, "is_cover_sheet": false}}
      ]
    }}

    Document Text:
    {document_text}
    """
