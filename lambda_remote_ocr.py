#!/usr/bin/env python3
"""
AWS Lambda Function: Remote OCR for Tender Result PDFs
Triggered by S3 uploads to results_lambda_ocr/ prefix
Processes PDFs using OpenRouter API and saves markdown output to S3
"""

import os
import json
import logging
import tempfile
import base64
from pathlib import Path
from typing import Optional, List
import boto3
from pdf2image import convert_from_path
from openai import OpenAI

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "nvidia/nemotron-nano-12b-v2-vl:free"

# Add /opt/bin to PATH for poppler binaries from Lambda layer
os.environ['PATH'] = f"/opt/bin:/opt/python/bin:{os.environ.get('PATH', '')}"

# Add /opt/lib to LD_LIBRARY_PATH for poppler shared libraries
os.environ['LD_LIBRARY_PATH'] = f"/opt/lib:/opt/python/lib:{os.environ.get('LD_LIBRARY_PATH', '')}"

# S3 client
s3_client = boto3.client('s3')


class RemoteOCR:
    """OCR processor using OpenRouter API"""
    
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OpenRouter API Key is required")
        
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        logger.info(f"Initialized RemoteOCR with model {MODEL_NAME}")

    def extract_from_pdf(self, pdf_path: str, prompt: str) -> str:
        """
        Extract text from PDF by converting to images and processing each page
        
        Args:
            pdf_path: Path to PDF file
            prompt: Prompt for the OCR model
            
        Returns:
            Combined markdown text from all pages
        """
        logger.info(f"Processing PDF: {pdf_path}")
        
        try:
            # Convert PDF to images
            images = convert_from_path(pdf_path)
            logger.info(f"Converted PDF to {len(images)} images")
            
            results = []
            
            # Process each page
            for i, image in enumerate(images):
                # Save image to temp file
                temp_image_path = f"/tmp/page_{i}.jpg"
                image.save(temp_image_path, 'JPEG')
                
                logger.info(f"Processing page {i+1}/{len(images)}...")
                page_text = self._extract_image(temp_image_path, prompt)
                results.append(f"--- Page {i+1} ---\n{page_text}")
                
                # Clean up temp image
                os.remove(temp_image_path)
            
            return "\n\n".join(results)
            
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            raise

    def _extract_image(self, image_path: str, prompt: str) -> str:
        """Extract text from a single image using OpenRouter API"""
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

            completion = self.client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://github.com/naoufelchahid/AO_scrape",
                    "X-Title": "AO Scrape Lambda",
                },
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
            )
            return completion.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error during image extraction: {e}")
            raise


def lambda_handler(event, context):
    """
    Lambda handler triggered by S3 upload events
    
    Args:
        event: S3 event notification
        context: Lambda context
        
    Returns:
        Response with status and details
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Validate API key
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")
        
        # Extract S3 bucket and key from event
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        
        logger.info(f"Processing file: s3://{bucket}/{key}")
        
        # Validate file is a PDF
        if not key.lower().endswith('.pdf'):
            logger.warning(f"Skipping non-PDF file: {key}")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Skipped non-PDF file'})
            }
        
        # Download PDF from S3 to /tmp
        pdf_path = f"/tmp/{Path(key).name}"
        logger.info(f"Downloading {key} to {pdf_path}")
        s3_client.download_file(bucket, key, pdf_path)
        
        # Define OCR prompt
        prompt = """Transcribe ALL data from this document into well-structured markdown format.

IMPORTANT INSTRUCTIONS:
1. Extract EVERY piece of information visible in the document
2. Preserve all tables in markdown table format
3. Clearly identify and label these sections:
   - Tender Reference/Number (Référence, Numéro AO, etc.)
   - Tender Object/Description (Objet)
   - Client/Organization (Maître d'ouvrage, Organisme)
   - All Bidders/Competitors (Concurrents, Soumissionnaires) with their:
     * Company name
     * Proposed amount (Montant proposé)
     * Status (admitted/excluded/disqualified)
   - Winner (Concurrent retenu, Attributaire) with:
     * Company name
     * Final amount (Montant)
   - Any excluded bidders with reasons
   - Dates (submission, opening, decision)

4. Use clear headers (##, ###) for different sections
5. For tables with bidders, use this format:
   | Company Name | Proposed Amount | Status | Notes |
   |--------------|----------------|--------|-------|
   
6. Highlight the winner clearly with a dedicated section
7. Include ALL monetary amounts with their currency
8. Preserve any official stamps, signatures mentions, or validation information

Output everything in French if the document is in French, or in the document's original language."""
        
        # Process PDF with OCR
        ocr = RemoteOCR(OPENROUTER_API_KEY)
        markdown_content = ocr.extract_from_pdf(pdf_path, prompt)
        
        # Generate output key in Results_markdown/ folder
        # Extract just the filename from the key (remove results_lambda_ocr/ prefix)
        filename = Path(key).name
        output_key = f"Results_markdown/{Path(filename).stem}.md"
        
        # Upload markdown to S3
        logger.info(f"Uploading markdown to s3://{bucket}/{output_key}")
        s3_client.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=markdown_content.encode('utf-8'),
            ContentType='text/markdown'
        )
        
        # Delete the PDF file from results_lambda_ocr/ to keep folder clean
        logger.info(f"Deleting PDF from s3://{bucket}/{key}")
        s3_client.delete_object(Bucket=bucket, Key=key)
        
        # Clean up temp files
        os.remove(pdf_path)
        
        logger.info(f"Successfully processed {key} -> {output_key} (PDF deleted)")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Success',
                'input_file': f's3://{bucket}/{key}',
                'output_file': f's3://{bucket}/{output_key}',
                'pages_processed': markdown_content.count('--- Page')
            })
        }
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Error',
                'error': str(e)
            })
        }
