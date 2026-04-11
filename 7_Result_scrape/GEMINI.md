# 7_Result_scrape: Results OCR Service

This service handles the **seventh stage** of the pipeline: processing result PV documents (PDFs) into structured markdown using OCR and text layer detection.

## Purpose

- **Poll** SQS `RESULTS_OCR_QUEUE` for new result documents.
- **Download** PV PDFs from S3.
- **Detect** if the PDF has a text layer or requires full OCR.
- **Convert** documents to a structured Markdown format optimized for result extraction.
- **Upload** the markdown to S3 and trigger the final ingestion stage.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | SQS consumer and main orchestration logic. |
| `ocr_service.py` | Core OCR and text extraction logic. |
| `text_layer_detector.py`| Heuristics to determine if OCR is needed. |
| `document_processor.py` | Post-processing of extracted text into structured markdown. |
| `data_extractor.py` | Preliminary regex-based extraction of key result fields. |
| `s3_poller.py` | Utility for polling S3 directly (alternative to SQS). |

## Workflow

1. **Trigger**: Receives a message with `tender_ref` and S3 path to a PV PDF.
2. **Download**: Fetches the PDF from `tender_results/{tender_ref}/pv.pdf`.
3. **Analyze**: `TextLayerDetector` checks if the PDF is searchable.
4. **Extract**: 
   - If searchable: Direct text extraction.
   - If image-based: Full OCR using Docling/Tesseract.
5. **Format**: Converts the output into Markdown, ensuring tables (winning bidders, amounts) are preserved.
6. **Persist**: Uploads markdown to `tender_results/{tender_ref}/pv.md`.
7. **Route**: Sends a message to `RESULTS_INGESTION_QUEUE`.

## Local Development

### Setup
```bash
cd 7_Result_scrape/results_ocr_container
pip install -r requirements.txt
```

### Commands
```bash
# Run the OCR service
python main.py
```

## Integration Notes

- **Input S3 Path**: `tender_results/{tender_ref}/pv.pdf`
- **Output S3 Path**: `tender_results/{tender_ref}/pv.md`
- **Downstream Dependency**: Triggers Stage 8 (`8_Result_Ingestion`).
