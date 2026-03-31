# Tender Scrape Pipeline

## Project Overview

This project is a multi-stage, event-driven data processing pipeline written in Python. Its primary purpose is to scrape public procurement tenders from a Moroccan portal, extract text from the documents via OCR, classify the logical structure of the documents, extract granular information using LLMs, and ingest the structured data into a Knowledge Graph (Apache Jena).

The architecture is heavily reliant on AWS infrastructure (S3 for object storage and SQS for event queueing between stages).

### Pipeline Stages

1.  **1_Update (Scraping):** Uses `Playwright` and `BeautifulSoup` to navigate the `marchespublics.gov.ma` portal, extract comprehensive metadata (reference, buyer, categories, deadlines, lots), bypass forms, and download ZIP files containing the raw tender documents. The raw files and JSON metadata are uploaded to S3.
2.  **2_Ocr (Text Extraction):** An SQS consumer that polls for new scraped documents. It utilizes `Docling` (and PyTorch/Transformers) to perform OCR and convert complex PDFs/documents into an intermediate Markdown format. It uploads the concatenated markdown back to S3.
3.  **3_Classification:** Another SQS consumer that takes the OCR'd markdown, splits it into logical documents, and leverages an LLM (via OpenRouter) to classify the sections (e.g., `avis_fr`, `administrative`, `specification`, `product`). It injects YAML frontmatter metadata and restructures the document hierarchy.
4.  **4_Extraction:** Polls the classification output, using LLMs and heuristics (`DocumentChunker`) to break the documents down into smaller, structured JSON chunks suited for vectorization and semantic mapping.
5.  **5_Ingestion (Knowledge Graph):** The final SQS consumer. It embeds the extracted chunks using an `EmbeddingClient`, generates an RDF graph using `JsonToRdfMapper`, validates the graph against SHACL shapes (`DataTester`), and ingests the final triples into an Apache Jena triplestore.

### Main Technologies
*   **Language:** Python 3.10+
*   **Web Scraping:** Playwright, BeautifulSoup4
*   **OCR & AI:** Docling, PyTorch, OpenRouter API (LLMs)
*   **Cloud & Infra:** AWS Boto3 (S3, SQS), Docker, Docker Compose
*   **Knowledge Graph:** Apache Jena, RDFLib, SPARQL

## Building and Running

The project is structured as a set of independent microservices (containers).

1.  **Environment Setup:** Each stage requires specific environment variables. A `.env` file should be configured with necessary credentials, including:
    *   `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`
    *   `OPENROUTER_API_KEY`
    *   Queue URLs for SQS (e.g., `EXTRACTION_QUEUE_URL`, `CLASSIFICATION_QUEUE_URL`)
    *   Jena configuration (`JENA_ENDPOINT`, `JENA_DATASET`)
2.  **Local Execution:** 
    *   Each directory contains its own `requirements.txt`. Create isolated virtual environments or install them globally depending on the stage you are working on.
    *   Run individual stages via their entry points (e.g., `python 1_Update/Db_updater.py`, `python 2_Ocr/main.py`).
3.  **Docker:** Most directories include a `Dockerfile` and some include `docker-compose.yml` (e.g., `2_Ocr`, `5_Ingestion`) for containerized deployment (intended for AWS ECS).

## Development Conventions

*   **Asynchronous I/O:** The codebase frequently uses `asyncio` for network-bound tasks like Playwright scraping and LLM API calls.
*   **Logging:** Python's standard `logging` module is heavily utilized across all services to track SQS polling, processing times, and failure states.
*   **Error Handling & DLQs:** SQS polling loops implement robust try-except blocks. Services are designed to either successfully process and delete a message or allow it to return to the queue (visibility timeout) or a Dead Letter Queue (DLQ).
*   **Intermediate Representation:** Markdown is treated as the source of truth between the OCR and Extraction stages.
*   **Data Validation:** The final ingestion stage uses Test-Driven Data (TDD) principles via SHACL shapes to ensure the RDF graph matches the ontology before inserting it into Jena.
