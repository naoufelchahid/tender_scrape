#!/usr/bin/env python3
"""
AWS Lambda Function: Extract Tender Results using Bedrock Nova Lite
Triggered by S3 uploads to Results_markdown/ prefix
Processes markdown files to extract structured tender result data and stores in database
"""

import os
import json
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = "amazon.nova-lite-v1:0"
MAX_RETRIES = 3

# AWS clients
s3_client = boto3.client('s3')
bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)


class BedrockExtractor:
    """Extracts structured data from tender result markdown using Bedrock Nova Lite"""
    
    def __init__(self):
        self.model_id = MODEL_ID
        logger.info(f"Initialized BedrockExtractor with model {self.model_id}")
    
    def _create_extraction_prompt(self) -> str:
        """Create the extraction prompt for Nova Lite"""
        return """You are an expert at extracting structured data from Moroccan tender result documents (PV - Procès Verbal).

Extract the following information from this tender result document:

1. LOT/TENDER REFERENCE: The reference number or code for this tender/lot (e.g., "AO N°01-2025", "LOT 1", etc.)
2. STATUS: Is this tender successful or "infructueux" (unsuccessful)?
3. BIDDERS: List ALL companies/contractors who submitted bids
4. BID AMOUNTS: The bid amount (in DH/Dirhams) for each bidder
5. WINNER: The name of the winning contractor (if successful)
6. WINNING AMOUNT: The final winning bid amount (if successful)

IMPORTANT INSTRUCTIONS:
- Extract company names EXACTLY as they appear, preserving capitalization
- Bid amounts should be numeric only (remove "DH", "DHS", commas, spaces)
- If a bidder has no amount listed, set their bid_amount to null
- If the tender is "infructueux" or unsuccessful, set is_successful to false
- Match bidders to their amounts carefully, even if they appear in different sections
- Handle OCR errors gracefully (e.g., slight spelling variations)
- Look for tables, lists, and text sections containing bidder information

Return ONLY valid JSON in this exact format (no markdown, no code blocks):
{
  "lot_reference": "string",
  "is_successful": true,
  "bidders": [
    {"name": "COMPANY NAME", "bid_amount": 123456.78},
    {"name": "ANOTHER COMPANY", "bid_amount": null}
  ],
  "winner_name": "WINNING COMPANY NAME",
  "winning_amount": 123456.78
}"""
    
    def extract_from_markdown(self, md_content: str) -> Optional[Dict[str, Any]]:
        """
        Extract tender result data from markdown content using Bedrock Nova Lite
        
        Args:
            md_content: Markdown content to process
            
        Returns:
            Extracted data as dictionary or None if extraction failed
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"Extraction attempt {attempt}/{MAX_RETRIES}")
                
                # Prepare conversation with document
                conversation = [
                    {
                        "role": "user",
                        "content": [
                            {"text": self._create_extraction_prompt()},
                            {
                                "document": {
                                    "format": "md",
                                    "name": "Tender Result Document",
                                    "source": {"bytes": md_content.encode('utf-8')},
                                }
                            },
                        ],
                    }
                ]
                
                # Call Bedrock Nova Lite
                response = bedrock_client.converse(
                    modelId=self.model_id,
                    messages=conversation,
                    inferenceConfig={"maxTokens": 2000, "temperature": 0.1},
                )
                
                # Extract response text
                response_text = response["output"]["message"]["content"][0]["text"]
                logger.info(f"Bedrock response: {response_text[:200]}...")
                
                # Parse JSON response
                json_data = self._extract_json_from_response(response_text)
                
                logger.info(f"✓ Successfully extracted data: {json_data.get('lot_reference')}")
                logger.info(f"  - Bidders: {len(json_data.get('bidders', []))}")
                logger.info(f"  - Winner: {json_data.get('winner_name')}")
                logger.info(f"  - Successful: {json_data.get('is_successful')}")
                
                return json_data
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error on attempt {attempt}: {e}")
                if attempt < MAX_RETRIES:
                    continue
                    
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt}: {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    continue
        
        logger.error(f"✗ Failed to extract data after {MAX_RETRIES} attempts")
        return None
    
    def _extract_json_from_response(self, response_text: str) -> dict:
        """Extract JSON from response, handling markdown code blocks"""
        text = response_text.strip()
        if text.startswith("```"):
            # Remove opening ```json or ```
            lines = text.split('\n')
            lines = lines[1:]  # Remove first line
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # Remove last line
            text = '\n'.join(lines)
        
        return json.loads(text)


class DatabaseManager:
    """Manages database operations for tender results"""
    
    # Legal suffixes to remove for matching (order matters - longest first)
    LEGAL_SUFFIXES = [
        'S.A.R.L.A.U',
        'S.A.R.L.AU',
        'S.A.R.L',
        'SARL AU',
        'SARL.AU',
        'SARL-AU',
        'SARL',
        'S.A.R.L',
        'S.A',
        'SA',
    ]
    
    def __init__(self):
        self.conn = None
    
    def normalize_contractor_name(self, name: str) -> str:
        """
        Normalize contractor name by removing legal suffixes
        
        Args:
            name: Original contractor name
            
        Returns:
            Normalized name without legal suffix
        """
        if not name:
            return ""
        
        # Convert to uppercase for matching and strip
        normalized = name.strip().upper()
        
        # Remove trailing period if present (e.g., "S.A.R.L." -> "S.A.R.L")
        if normalized.endswith('.'):
            normalized = normalized[:-1]
        
        # Remove legal suffixes (try longest first to avoid partial matches)
        for suffix in self.LEGAL_SUFFIXES:
            # Try with space before suffix
            if normalized.endswith(' ' + suffix):
                normalized = normalized[:-len(suffix)-1].strip()
                break
            # Try without space (e.g., "COMPANY-SARL")
            elif normalized.endswith('-' + suffix) or normalized.endswith(suffix):
                if normalized.endswith('-' + suffix):
                    normalized = normalized[:-len(suffix)-1].strip()
                else:
                    normalized = normalized[:-len(suffix)].strip()
                break
        
        return normalized
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(
                host=os.environ.get('DB_HOST', '').strip(),
                database=os.environ.get('DB_NAME'),
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASSWORD'),
                port=os.environ.get('DB_PORT', '5432')
            )
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def find_or_create_contractor(self, name: str) -> Optional[int]:
        """
        Find contractor by name or create new one
        Uses normalized name matching (removes legal suffixes for comparison)
        
        Args:
            name: Contractor name
            
        Returns:
            Contractor ID or None if operation failed
        """
        if not name or not name.strip():
            return None
        
        original_name = name.strip()
        normalized_name = self.normalize_contractor_name(original_name)
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # First, try to find by exact normalized match
                # We need to normalize all existing names and compare
                # This is done by creating a temporary normalized version in the query
                
                # Get all contractors and check normalized names
                cur.execute("SELECT id, name FROM contractors")
                all_contractors = cur.fetchall()
                
                # Find matching contractor by normalized name
                for contractor in all_contractors:
                    existing_normalized = self.normalize_contractor_name(contractor['name'])
                    if existing_normalized == normalized_name:
                        logger.info(f"Found existing contractor: '{original_name}' matched with '{contractor['name']}' (ID: {contractor['id']})")
                        return contractor['id']
                
                # No match found - create new contractor with original name
                cur.execute(
                    "INSERT INTO contractors (name, created_at, updated_at) VALUES (%s, NOW(), NOW()) RETURNING id",
                    (original_name,)
                )
                new_id = cur.fetchone()['id']
                self.conn.commit()
                logger.info(f"Created new contractor: {original_name} (normalized: {normalized_name}, ID: {new_id})")
                return new_id
                
        except Exception as e:
            logger.error(f"Error finding/creating contractor '{original_name}': {e}")
            self.conn.rollback()
            return None
    
    def insert_result(self, extracted_data: Dict[str, Any]) -> bool:
        """
        Insert result record into database
        
        Args:
            extracted_data: Extracted tender result data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            lot_reference = extracted_data.get('lot_reference')
            winner_name = extracted_data.get('winner_name')
            winning_amount = extracted_data.get('winning_amount')
            bidders = extracted_data.get('bidders', [])
            
            # Get winner ID
            winner_id = None
            if winner_name:
                winner_id = self.find_or_create_contractor(winner_name)
            
            # Prepare bidder data (max 15)
            bidder_ids = []
            bid_amounts = []
            
            for i, bidder in enumerate(bidders[:15]):  # Limit to 15 bidders
                bidder_name = bidder.get('name')
                bid_amount = bidder.get('bid_amount')
                
                bidder_id = self.find_or_create_contractor(bidder_name) if bidder_name else None
                bidder_ids.append(bidder_id)
                bid_amounts.append(bid_amount)
            
            # Pad to 15 entries
            while len(bidder_ids) < 15:
                bidder_ids.append(None)
                bid_amounts.append(None)
            
            # Log warning if more than 15 bidders
            if len(bidders) > 15:
                logger.warning(f"Tender {lot_reference} has {len(bidders)} bidders, only storing first 15")
            
            # Insert result
            with self.conn.cursor() as cur:
                sql = """
                    INSERT INTO results (
                        lot_reference, winner_id, win_bid,
                        bider1_id, bid1, bider2_id, bid2, bider3_id, bid3,
                        bider4_id, bid4, bider5_id, bid5, bider6_id, bid6,
                        bider7_id, bid7, bider8_id, bid8, bider9_id, bid9,
                        bider10_id, bid10, bider11_id, bid11, bider12_id, bid12,
                        bider13_id, bid13, bider14_id, bid14, bider15_id, bid15
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                """
                
                params = [lot_reference, winner_id, winning_amount]
                for i in range(15):
                    params.extend([bidder_ids[i], bid_amounts[i]])
                
                cur.execute(sql, params)
                self.conn.commit()
                
            logger.info(f"✓ Inserted result for lot: {lot_reference}")
            return True
            
        except Exception as e:
            logger.error(f"Error inserting result: {e}", exc_info=True)
            self.conn.rollback()
            return False
    
    def update_tender_is_results(self, reference: str) -> bool:
        """
        Update tender to set is_results = TRUE
        
        Args:
            reference: Tender reference
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.conn.cursor() as cur:
                sql = """
                    UPDATE tenders 
                    SET is_results = TRUE,
                        updated_at = NOW()
                    WHERE reference = %s
                    OR REPLACE(REPLACE(reference, '/', '_'), ' ', '_') = %s
                """
                
                cur.execute(sql, (reference, reference))
                self.conn.commit()
                
                if cur.rowcount > 0:
                    logger.info(f"✓ Updated tender {reference} is_results = TRUE")
                    return True
                else:
                    logger.warning(f"No tender found with reference: {reference}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error updating tender: {e}")
            self.conn.rollback()
            return False


def extract_tender_reference_from_filename(filename: str) -> Optional[str]:
    """
    Extract tender reference from markdown filename
    Assumes format: {reference}.md or result_{reference}.md
    
    Args:
        filename: Markdown filename
        
    Returns:
        Tender reference or None
    """
    # Remove extension
    name_no_ext = Path(filename).stem
    
    # Remove 'result_' prefix if present
    if name_no_ext.startswith('result_'):
        name_no_ext = name_no_ext[7:]
    
    return name_no_ext if name_no_ext else None


def lambda_handler(event, context):
    """
    Lambda handler triggered by S3 upload events to Results_markdown/
    
    Args:
        event: S3 event notification
        context: Lambda context
        
    Returns:
        Response with status and details
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    db_manager = None
    
    try:
        # Extract S3 bucket and key from event
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        
        logger.info(f"Processing file: s3://{bucket}/{key}")
        
        # Validate file is markdown
        if not key.lower().endswith('.md'):
            logger.warning(f"Skipping non-markdown file: {key}")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Skipped non-markdown file'})
            }
        
        # Download markdown from S3
        filename = Path(key).name
        md_path = f"/tmp/{filename}"
        logger.info(f"Downloading {key} to {md_path}")
        s3_client.download_file(bucket, key, md_path)
        
        # Read markdown content
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Extract data using Bedrock
        extractor = BedrockExtractor()
        extracted_data = extractor.extract_from_markdown(md_content)
        
        if not extracted_data:
            raise Exception("Failed to extract data from markdown")
        
        # Connect to database
        db_manager = DatabaseManager()
        db_manager.connect()
        
        # Insert result into database
        if not db_manager.insert_result(extracted_data):
            raise Exception("Failed to insert result into database")
        
        # Extract tender reference from filename or extracted data
        tender_ref = extract_tender_reference_from_filename(filename)
        if not tender_ref:
            tender_ref = extracted_data.get('lot_reference')
        
        # Update tender is_results flag
        if tender_ref:
            db_manager.update_tender_is_results(tender_ref)
        
            # Move markdown file to tender_doc_final/{tender_reference}/
            # Sanitize reference for folder name
            folder_name = tender_ref.replace('/', '_').replace(' ', '_')
            dest_key = f"tender_doc_final/{folder_name}/{filename}"
            
            logger.info(f"Copying {key} -> {dest_key}")
            s3_client.copy_object(
                Bucket=bucket,
                CopySource={'Bucket': bucket, 'Key': key},
                Key=dest_key
            )
        else:
            logger.warning("Could not determine tender reference, skipping file move")
        
        # Delete original markdown file from Results_markdown/
        logger.info(f"Deleting {key}")
        s3_client.delete_object(Bucket=bucket, Key=key)
        
        # Clean up temp file
        os.remove(md_path)
        
        logger.info(f"✓ Successfully processed {key}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Success',
                'lot_reference': extracted_data.get('lot_reference'),
                'bidders_count': len(extracted_data.get('bidders', [])),
                'winner': extracted_data.get('winner_name'),
                'moved_to': dest_key if tender_ref else None
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
    
    finally:
        if db_manager:
            db_manager.close()
