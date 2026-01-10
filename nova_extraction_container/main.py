"""
Main orchestration module for Nova Extraction Container.
Polls SQS queue, processes tender documents with multimodal extraction, and uploads results.
"""
import os
import re
import time
import shutil
from typing import List, Dict, Any
from datetime import datetime

from config import Config
from logger import logger, log_processing_start, log_processing_complete, log_processing_error, log_extraction_result
from s3_utils import S3Client
from sqs_utils import SQSClient
from src import DocumentClassifier, NovaExtractor, ExtractionOutput, IntegrityChecker, IntegrityCheckError
from src.models import ProductItem
from src.llm_chunker import LLMChunker
from src.cleaning import DocumentCleaners


def sanitize_for_s3_metadata(text: str) -> str:
    """Remove non-ASCII characters from text for S3 metadata compatibility."""
    if not text:
        return text
    # Remove any non-ASCII characters
    return ''.join(char for char in text if ord(char) < 128)


class NovaExtractionService:
    """Main service class for Nova-based extraction."""
    
    def __init__(self):
        """Initialize service."""
        self.s3_client = S3Client()
        self.sqs_client = SQSClient()
        self.classifier = DocumentClassifier()
        self.extractor = NovaExtractor()
        self.chunker = LLMChunker(
            Config.AWS_REGION,
            Config.PRIMARY_MODEL,
            Config.GROQ_API_KEY
        )
        logger.info("Nova Extraction Service initialized")
    
    def run(self):
        """Main service loop."""
        logger.info("Starting Nova Extraction service main loop")
        
        while True:
            try:
                # Poll SQS for messages
                message = self.sqs_client.receive_message()
                
                if not message:
                    time.sleep(5)
                    continue
                
                try:
                    logger.info(f"📨 Processing message: {message['message_id']}")
                    
                    # Parse message body
                    body = message['body']
                    tender_ref = body.get('tender_ref')
                    tender_id = body.get('tender_id', tender_ref)
                    
                    if not tender_ref:
                        logger.error("No tender_ref in message")
                        self.sqs_client.delete_message(message['receipt_handle'])
                        continue
                    
                    # Process tender
                    success = self._process_tender(tender_ref, tender_id)
                    
                    if success:
                        # Delete message from queue
                        self.sqs_client.delete_message(message['receipt_handle'])
                        logger.info("✅ Message processed and deleted successfully")
                    else:
                        logger.error("❌ Message processing failed permanently.")
                        # Send to DLQ
                        if Config.OCR_DLQ_URL:
                            logger.info(f"🚚 Moving message {message['message_id']} to DLQ")
                            try:
                                self.sqs_client.send_message(body, Config.OCR_DLQ_URL)
                                self.sqs_client.delete_message(message['receipt_handle'])
                                logger.info("✅ Message moved to DLQ and deleted from source queue")
                            except Exception as dlq_err:
                                logger.error(f"Failed to move message to DLQ: {dlq_err}")
                        else:
                            logger.warning("OCR_DLQ_URL not set - message will be retried by SQS (visibility timeout)")
                
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    continue
            
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(10)
    
    def _parse_float(self, value: Any) -> float:
        """Parse float from string handling various formats (1 234,56)."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        
        # String processing
        s = str(value).strip()
        # Remove spaces/thousand separators
        s = s.replace(" ", "").replace("\u00a0", "") # Handle non-breaking space
        # Replace comma with dot
        s = s.replace(",", ".")
        
        try:
            return float(s)
        except ValueError:
            return 0.0


    def _process_tender(self, tender_ref: str, tender_id: str) -> bool:
        """Process a single tender."""
        start_time = time.time()
        temp_dir = None
        
        try:
            
            # 1. Download files from S3
            s3_prefix = f"{Config.S3_SOURCE_PREFIX}{tender_ref}/"
            temp_dir = f"temp/{tender_ref}"
            os.makedirs(temp_dir, exist_ok=True)
            
            # List and download supported files
            all_files = self.s3_client.list_tender_files(tender_ref)
            logger.info(f"Found {len(all_files)} files in {s3_prefix}")
            
            # Filter for supported file types
            supported_extensions = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.png', '.jpg', '.jpeg']
            supported_files = [f for f in all_files if any(f.lower().endswith(ext) for ext in supported_extensions)]
            
            logger.info(f"Found {len(supported_files)} supported files for {tender_ref} (PDF, Word, Excel, Images)")
            
            if not supported_files:
                logger.error(f"No supported files downloaded for {tender_ref}")
                return False
            
            local_paths = self.s3_client.download_files(supported_files, temp_dir)
            
            log_processing_start(tender_ref, len(local_paths))
            
            # 2. Classify and process each document
            all_extractions = []
            files_processed = 0
            files_skipped = 0
            
            for pdf_path in local_paths:
                filename = os.path.basename(pdf_path)
                
                # Classify document
                doc_type, should_process = self.classifier.classify(pdf_path)
                
                if not should_process:
                    logger.info(f"⏭️  Skipping {filename} (type: {doc_type})")
                    files_skipped += 1
                    continue
                
                # Extract data
                logger.info(f"🔄 Processing {filename} (type: {doc_type})")
                try:
                    extraction = self.extractor.extract_tender_data(pdf_path, doc_type, tender_ref)
                    if extraction:
                        all_extractions.append(extraction)
                        files_processed += 1
                        logger.info(f"✅ Completed {filename}")
                    else:
                        logger.warning(f"⚠️  No data extracted from {filename}")
                except Exception as e:
                    logger.error(f"❌ Error processing {filename}: {e}", exc_info=True)
                    continue
            
            # 3. Aggregate results
            if not all_extractions:
                logger.warning("No data extracted from any document")
                # Create empty result
                aggregated = ExtractionOutput(
                    tender_info={},
                    lots=[],
                    products=[]
                )
            else:
                aggregated = self._aggregate_extractions(all_extractions, tender_ref)
            
            # Log results
            log_extraction_result(
                tender_ref,
                len(aggregated.tender_info.model_dump(exclude_none=True)),
                len(aggregated.lots),
                len(aggregated.products)
            )
            
            # 4. Integrity check
            logger.info("Performing integrity checks...")
            meta_valid = IntegrityChecker.check_metadata(aggregated)
            
            if not meta_valid:
                logger.error(f"Integrity check FAILED for {tender_ref}")
                # Don't fail completely, just log warning
                logger.warning("Proceeding with potentially incomplete data")
            
            # 5. Create chunks using extracted text from document processor
            logger.info("Creating document chunks...")
            try:
                from src.cleaning import LogicalDocument
                from src.document_processor import DocumentProcessor
                
                processor = DocumentProcessor()
                docs = []
                
                for local_path in local_paths:
                    filename = os.path.basename(local_path)
                    try:
                        # Use document processor to extract text (same as extraction does)
                        text, images = processor.process_file(local_path)
                        
                        if text:  # Only create chunks from text content
                            # Classify document type
                            doc_type = DocumentCleaners.classify_document(filename, text)
                            
                            docs.append(LogicalDocument(
                                original_filename=filename,
                                content=text,
                                doc_type=doc_type
                            ))
                        else:
                            logger.warning(f"No text extracted from {filename}, skipping for chunking")
                    except Exception as e:
                        logger.warning(f"Could not process {filename} for chunking: {e}")
                        continue
                
                if docs:
                    chunks = self.chunker.chunk_all_documents(
                        docs,
                        tender_id,
                        tender_ref,
                        aggregated.lots
                    )
                    logger.info(f"Generated {len(chunks)} chunks")
                else:
                    logger.warning("No documents available for chunking")
                    chunks = []
            except Exception as e:
                logger.error(f"Chunking failed: {e}", exc_info=True)
                chunks = []

            if not aggregated.products and chunks:
                logger.info("Backfilling products from chunks...")
                backfilled_count = 0
                for chunk in chunks:
                    meta = chunk.get('metadata', {})
                    if meta.get('type') == 'products':
                        try:
                            # Create ProductItem from chunk metadata
                            item = ProductItem(
                                designation=meta.get('designation', 'Unknown'),
                                unit=meta.get('unit', 'u'),
                                quantity=self._parse_float(meta.get('quantity', 0)),
                                estimated_price=self._parse_float(meta.get('estimated_price')) if meta.get('estimated_price') else None,
                                lot_number=meta.get('lot', meta.get('lot_reference'))
                            )
                            aggregated.products.append(item)
                            backfilled_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to create product from chunk {chunk.get('id')}: {e}")
                
                if backfilled_count > 0:
                    logger.info(f"Successfully backfilled {backfilled_count} products from chunks")

            # 6. Upload to S3 - NEW FOLDER STRUCTURE
            # Metadata goes to /tenders_metadata/{tender_ref}.json
            metadata_key = f"tenders_metadata/{tender_ref}.json"
            
            if not self.s3_client.upload_json(
                aggregated.model_dump(mode='json'),
                metadata_key,
                {'tender_ref': sanitize_for_s3_metadata(tender_ref), 'processed_date': datetime.utcnow().isoformat()}
            ):
                logger.error(f"Failed to upload metadata for {tender_ref}")
                return False
            
            # Upload chunks to /chunks_tender/{tender_ref}/chunks.json
            if chunks:
                chunks_key = f"chunks_tender/{tender_ref}/chunks.json"
                if not self.s3_client.upload_json(
                    chunks,
                    chunks_key,
                    {'tender_ref': sanitize_for_s3_metadata(tender_ref), 'chunk_count': str(len(chunks))}
                ):
                    logger.error(f"Failed to upload chunks for {tender_ref}")
                    # Don't fail completely, metadata is more important
            else:
                logger.warning(f"No chunks generated for {tender_ref}")
            
            # 7. Send completion messages to separate queues
            processing_time = time.time() - start_time
            
            # Message 1: Metadata -> DB_FILLER_QUEUE
            metadata_message = {
                'tender_ref': tender_ref,
                'tender_id': tender_id,
                'status': 'completed',
                'metadata_path': metadata_key,
                'files_processed': files_processed,
                'files_skipped': files_skipped,
                'processing_time': processing_time
            }
            
            self.sqs_client.send_message(
                metadata_message,
                Config.DB_FILLER_QUEUE_URL
            )
            logger.info(f"Sent metadata notification to DB_FILLER_QUEUE for {tender_ref}")
            
            # Message 2: Chunks -> VECTOR_QUEUE (if chunks exist)
            if chunks:
                chunks_message = {
                    'tender_ref': tender_ref,
                    'tender_id': tender_id,
                    'status': 'completed',
                    'chunks_path': f"chunks_tender/{tender_ref}/chunks.json",
                    'chunk_count': len(chunks),
                    'processing_time': processing_time
                }
                
                self.sqs_client.send_message(
                    chunks_message,
                    Config.VECTOR_QUEUE_URL
                )
                logger.info(f"Sent chunks notification to VECTOR_QUEUE for {tender_ref}")
            else:
                logger.warning("No chunks generated, skipping VECTOR_QUEUE notification")
            
            # Cleanup
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temp files for {tender_ref}")
            
            log_processing_complete(tender_ref, processing_time, files_processed, files_skipped)
            return True
        
        except Exception as e:
            log_processing_error(tender_ref, str(e))
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return False
    
    def _aggregate_extractions(self, extractions: List[ExtractionOutput], tender_ref: str) -> ExtractionOutput:
        """Aggregate multiple extraction outputs into one with deduplication."""
        # Start with first extraction
        aggregated = extractions[0]
        
        # Track seen lots by normalized number
        # Key: simplified lot number (e.g. "1", "2")
        seen_lots = {}
        
        # Initialize with first extraction's lots
        for lot in aggregated.lots:
            lot_num = lot.lot_number.lower().replace("lot", "").strip()
            seen_lots[lot_num] = lot
        
        # Merge data from other extractions
        for extraction in extractions[1:]:
            # Merge tender_info (prefer non-null values)
            for key, value in extraction.tender_info.model_dump().items():
                if value is not None:
                    current = getattr(aggregated.tender_info, key)
                    if current is None:
                        setattr(aggregated.tender_info, key, value)
            
            # Merge lots (Smart Deduplication)
            for lot in extraction.lots:
                lot_num = lot.lot_number.lower().replace("lot", "").strip()
                if lot_num in seen_lots:
                    # Lot already exists - verify if new one is better
                    existing = seen_lots[lot_num]
                    # If existing has no title but new one does, update it
                    if not existing.title and lot.title:
                        existing.title = lot.title
                    # If existing has no budget but new one does, update it
                    if not existing.budget_lot and lot.budget_lot:
                        existing.budget_lot = lot.budget_lot
                else:
                    # New lot
                    seen_lots[lot_num] = lot
                    aggregated.lots.append(lot)
            
            # Merge products
            aggregated.products.extend(extraction.products)
        
        # Ensure tender_reference is set
        if not aggregated.tender_info.tender_reference:
            aggregated.tender_info.tender_reference = tender_ref
        
        return aggregated


def main():
    """Entry point."""
    logger.info("=" * 80)
    logger.info("Nova Extraction Service Starting")
    logger.info("=" * 80)
    
    # Print configuration
    print("=" * 50)
    print("Nova Extraction Container Configuration")
    print("=" * 50)
    print(f"AWS Region: {Config.AWS_REGION}")
    print(f"S3 Bucket: {Config.S3_BUCKET_NAME}")
    print(f"S3 Prefix: {Config.S3_SOURCE_PREFIX}")
    print(f"OCR Queue: {Config.OCR_QUEUE_URL[:50]}...")
    print(f"Primary Model: {Config.PRIMARY_MODEL}")
    print(f"Fallback 1: {Config.FALLBACK_MODEL_1}")
    print(f"Fallback 2: {Config.FALLBACK_MODEL_2}")
    print(f"Max Workers: {Config.MAX_WORKERS}")
    print(f"Chunk Size: {Config.CHUNK_SIZE_PAGES} pages")
    print(f"OpenRouter Key: {'*' * 20}")
    print("=" * 50)
    
    service = NovaExtractionService()
    service.run()


if __name__ == "__main__":
    main()
