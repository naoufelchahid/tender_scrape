---
trigger: always_on
---


---

## 🔄 Complete Workflow (MANDATORY SEQUENCE)

### Phase 1: Scraping → PostgreSQL + S3
- Scrape tender data from MarchesPublics.gov.ma
- Store metadata in PostgreSQL Tender table
- Upload ZIP archives to S3

### Phase 2: Document Unzipping → S3 + SQS
- Lambda unzips documents to /final_doc_tender/{tender_ref}/
- Accept all file formats: **PDF, DOCX, XLSX, JPEG, PNG**
- Send message to **OCR_QUEUE** with tender_ref and S3 paths

### Phase 3: OCR Processing (DOCKER CONTAINER 1) → S3 Markdown
- Container polls **OCR_QUEUE**
- Download all files from /final_doc_tender/{tender_ref}/
- Process by file type:
  - **PDF**: OCR with layout preservation → Markdown
  - **DOCX**: Extract text, convert tables → Markdown
  - **XLSX**: Convert sheets to markdown tables
  - **JPEG/PNG**: OCR images → Markdown
- Upload markdown to /markdown_tender/{tender_ref}/
- Delete SQS message on success
- Send message to **EXTRACTION_QUEUE**

### Phase 4: Data Extraction (DOCKER CONTAINER 2) → PostgreSQL + S3 Chunks
- Container polls **EXTRACTION_QUEUE**
- Download markdown files from /markdown_tender/{tender_ref}/
- Analyze with document-type specific prompts:
  - **CPS**: Extract articles, chapters, legal clauses
  - **BDP**: Extract product specifications, quantities, tables
  - **RC**: Extract administrative requirements, criteria
- Update PostgreSQL (Tender, Article, Designation tables)
- Apply chunking strategy (document-type specific)
- Save chunks to /chunks_tender/{tender_ref}/
- Delete SQS message on success
- Send message to **VECTOR_QUEUE**

### Phase 5: Neptune Graph Creation (LAMBDA) → Neptune + Vector Store
- Lambda polls **VECTOR_QUEUE**
- Download chunks from /chunks_tender/{tender_ref}/
- Create Neptune vertices (lightweight chunk references)
- Create Neptune edges (document relationships)
- Vectorize chunks using Bedrock
- Store vectors in S3 Vector Store
- Delete SQS message on success

### Phase 6: Results Processing (LAMBDA) → PostgreSQL Result + Neptune
- Lambda triggered by S3 upload to tender_results/
- Process results files (PDF/DOCX/Images) → Markdown
- Extract structured data with specific prompting
- Update PostgreSQL Result table
- Update Neptune graph with AWARDS relationships

---

## 🔄 SQS Queue Strategy (CRITICAL)

### Queue Configuration:
1. **OCR_QUEUE**
   - Purpose: Trigger OCR container processing
   - Message format: `{"tender_ref": "REF123", "s3_paths": [...], "file_types": ["pdf", "docx", "xlsx", "jpeg", "png"]}`
   - Dead Letter Queue: OCR_DLQ (after 3 retries)
   - Visibility timeout: 900 seconds (15 minutes)

2. **EXTRACTION_QUEUE**
   - Purpose: Trigger data extraction container
   - Message format: `{"tender_ref": "REF123", "markdown_paths": [...]}`
   - Dead Letter Queue: EXTRACTION_DLQ (after 3 retries)
   - Visibility timeout: 1800 seconds (30 minutes)

3. **VECTOR_QUEUE**
   - Purpose: Trigger vectorization and graph creation
   - Message format: `{"tender_ref": "REF123", "chunk_paths": [...]}`
   - Dead Letter Queue: VECTOR_DLQ (after 3 retries)
   - Visibility timeout: 600 seconds (10 minutes)

### Queue Processing Rules:
- **ALWAYS** delete message only after successful processing
- **ALWAYS** send downstream queue message before deleting current message
- **NEVER** delete message on failure (let visibility timeout handle retry)
- **LOG** all queue operations (receive, process, delete, send)
- **HANDLE** dead letter queues with monitoring and alerts

---

## 🚫 CRITICAL CONSTRAINTS (MUST FOLLOW)

### Supported File Formats:
- **PDF**: Scanned or digital documents
- **DOCX**: Microsoft Word documents
- **XLSX**: Microsoft Excel spreadsheets
- **JPEG/PNG**: Image files (plans, diagrams, scanned documents)

### Storage Strategy:
- **S3**: Single source of truth for all files
  - `/final_doc_tender/{tender_ref}/` - Original files (PDF, DOCX, XLSX, JPEG, PNG)
  - `/markdown_tender/{tender_ref}/` - OCR markdown output
  - `/chunks_tender/{tender_ref}/` - Extracted chunks (JSON)
  - `/vector_store/` - Bedrock knowledge base vectors
- **Neptune**: References + relationships ONLY (no full content)
- **PostgreSQL**: Structured metadata ONLY (no documents or full text)
- **SQS**: Message passing ONLY (lightweight messages with S3 references)

### Chunking Rules:
- **CPS**: Hierarchical (Chapter → Article)
- **BDP**: Preserve tables (never split rows)
- **RC**: Semantic clauses
- **Results**: By lot (all bidders together)

### Database Rules:
- NO new tables without approval
- Use composite references (tender_ref + lot_num)
- Normalize contractor names before matching
- Update existing tables only

### Container Communication Rules:
- **NEVER** call next container directly
- **ALWAYS** use SQS queues for decoupling
- **NEVER** store processing state in containers (use SQS + S3)
- **ALWAYS** make containers stateless and idempotent

---

## 🐳 Container Architecture

### Container 1: OCR Service
**Purpose**: Convert all document types to structured Markdown
**Responsibilities**:
- Poll OCR_QUEUE for new tender documents
- Download files from S3 (all formats)
- Process by file type:
  - **PDF**: Tesseract/Textract OCR with layout preservation
  - **DOCX**: python-docx text extraction + table conversion
  - **XLSX**: openpyxl/pandas spreadsheet to markdown tables
  - **JPEG/PNG**: Tesseract/Textract OCR
- Generate structured Markdown with proper formatting
- Upload Markdown to S3
- Send completion message to EXTRACTION_QUEUE

**Technology Stack**:
- Base Image: python:3.11-slim
- OCR Engine: Tesseract / AWS Textract
- Document Processing: python-docx, openpyxl, pandas
- Dependencies: boto3, Pillow, pdf2image, pyyaml

**Environment Variables**:
- `OCR_QUEUE_URL`
- `EXTRACTION_QUEUE_URL`
- `S3_BUCKET_NAME`
- `AWS_REGION`

### Container 2: Data Extraction & Analysis Service
**Purpose**: Extract structured data from Markdown using LLM
**Responsibilities**:
- Poll EXTRACTION_QUEUE for processed markdown
- Download Markdown files from S3
- Analyze with document-type specific prompts
- Extract structured data (Pydantic validation)
- Update PostgreSQL database
- Apply document-type specific chunking
- Upload chunks to S3
- Send completion message to VECTOR_QUEUE

**Technology Stack**:
- Base Image: python:3.11-slim
- LLM Provider: AWS Bedrock (Claude/Nova)
- Dependencies: boto3, pydantic, sqlalchemy, psycopg2

**Environment Variables**:
- `EXTRACTION_QUEUE_URL`
- `VECTOR_QUEUE_URL`
- `S3_BUCKET_NAME`
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `AWS_REGION`
- `BEDROCK_MODEL_ID`

---

## 📋 Development Guidelines

**This architecture is the foundation of the entire system. ALL code generation must respect these rules.**

1. **Understand the full pipeline:** Scraping → Unzipping → OCR (Container 1) → Data Extraction (Container 2) → Vectorization → Results Processing

2. **Respect data integrity:**
   - Always use composite references in database
   - Normalize contractor names before matching
   - Maintain S3 path consistency
   - Never lose data between queue transitions
   - Handle all file formats correctly (PDF, DOCX, XLSX, JPEG, PNG)

3. **Follow container architecture:**
   - Each container polls its dedicated SQS queue
   - Containers are stateless and idempotent
   - Always delete SQS message only after successful processing
   - Send downstream queue message before deleting current message

4. **Preserve metadata:**
   - Every chunk needs `.metadata.json` for vector search
   - Include all required fields (tenderRef, buyerName, documentType, etc.)
   - Maintain consistent date formats
   - Track processing lineage (original_file → markdown → chunks)
   - Store original file format in metadata

5. **Handle errors gracefully:**
   - Log everything (CloudWatch for Lambda, container logs)
   - Retry on transient failures (use SQS visibility timeout)
   - Use Dead Letter Queues for persistent failures
   - Never corrupt database or S3 structure
   - Continue processing other items on individual failures
   - Handle unsupported file formats with clear error messages

6. **Test thoroughly:**
   - Test scrapers visually first (headless=False)
   - Verify database state after operations
   - Check S3 file organization
   - Monitor SQS queue metrics (messages in flight, DLQ depth)
   - Review CloudWatch logs for all components
   - Test each file format (PDF, DOCX, XLSX, JPEG, PNG)

7. **Code standards:**
   - Use type hints for function parameters and returns
   - Document all classes and functions with docstrings
   - Follow existing naming conventions:
     - Scripts: lowercase with underscores (e.g., `db_updater.py`)
     - Classes: PascalCase (e.g., `DatabaseUpdater`)
     - Functions: snake_case (e.g., `generate_initials()`)

This project is a **production system** processing real Moroccan tender data for business intelligence. Changes must be reliable, well-tested, and maintain data integrity at all times.