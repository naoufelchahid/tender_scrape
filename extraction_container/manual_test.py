import os
import json
import logging
import boto3
import time
from dotenv import load_dotenv

# Load env variables if .env exists
try:
    load_dotenv()
except:
    pass

from src.extraction import ExtractionService
from src.llm_chunker import LLMChunker
from main import handle_message

# Mocking SQS to avoid disrupting real queues
class MockSQS:
    def delete_message(self, QueueUrl, ReceiptHandle):
        print(f"[MOCK SQS] Deleting message from {QueueUrl}, handle: {ReceiptHandle}")
    
    def send_message(self, QueueUrl, MessageBody):
        print(f"[MOCK SQS] Sending message to {QueueUrl}:")
        print(f"Body: {MessageBody}")
    
    def get_queue_url(self, QueueName):
        return {"QueueUrl": f"https://sqs.mock.amazonaws.com/{QueueName}"}

def run_test():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    start_time = time.time()
    
    # Config
    AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-3')
    BEDROCK_MODEL = "openai/gpt-oss-20b" 
    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
    
    # Clients
    # Clients
    # MOCK S3 to save files locally for inspection
    from unittest.mock import MagicMock
    s3 = MagicMock()
    
    def mock_put_object(Bucket, Key, Body):
        output_path = os.path.join("test_output", Key)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(Body if isinstance(Body, str) else Body.decode('utf-8'))
        print(f"[MOCK S3] Saved {Key} to local file: {output_path}")

    def mock_get_object(Bucket, Key):
        # We need to return an object with a Body.read() method
        # This assumes we have the test file locally or we just mock return
        # But handle_message does s3.get_object. We need to mock that too or ensure files exist.
        # Actually checking earlier logs: "Downloading markdown: markdown_tender/..."
        # We need to simulate the markdown download.
        # Let's assume we read from a local file if exists or return dummy.
        pass
        
    s3.put_object.side_effect = mock_put_object
    
    # We also need get_object to work for the Markdown download
    # Let's verify if handle_message does get_object. Yes.
    class MockBody:
        def read(self):
            return b"""
# File: avis_01.txt
# AVIS D'APPEL D'OFFRES N 12/2025

Royaume du Maroc
Ministere de l'Equipement
Direction Provinciale de Tetouan

Objet: Travaux d'amenagement de la voirie.
Date limite: 2025-05-10
Budget: 1200000.00 DH

---

# File: rc_01.txt
# REGLEMENT DE CONSULTATION (RC)

## Article 1: Objet du reglement
Le present reglement a pour objet...

## Article 5: Justification des capacites
Les concurrents doivent fournir...
Agrements requis: D1, D2.

---

# File: cps_01.txt
# CAHIER DES PRESCRIPTIONS SPECIALES (CPS)

## Article 3: Consistance des travaux
Les travaux comprennent le terrassement...

## Article 10: Provenance des materiaux
Les materiaux proviennent de carriere agree...

---

# File: bdp_01.txt
# BORDEREAU DES PRIX - DETAIL ESTIMATIF

| N | Designation des ouvrages | U | Qte | Prix |
|---|---|---|---|---|
| 1 | Deblais en terrain meuble | m3 | 500 | |
| 2 | Remblais compactes | m3 | 300 | |
| 3 | Bethel blanc C25/30 | m3 | 100 | |

"""

    s3.get_object.return_value = {'Body': MockBody()}

    sqs = MockSQS()
    sqs = MockSQS()
    
    extractor = ExtractionService(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)
    chunker = LLMChunker(AWS_REGION, BEDROCK_MODEL, OPENROUTER_API_KEY)
    
    # Test Data
    tender_ref = "0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL"
    markdown_key = "markdown_tender/0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL/0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL_ocr.md"
    
    msg = {
        'ReceiptHandle': 'mock_handle_123',
        'Body': json.dumps({
            "tender_ref": tender_ref,
            "tender_id": 9999,
            "markdown_key": markdown_key
        })
    }
    
    print(f"--- STARTING TEST FOR {tender_ref} WITH MODEL {BEDROCK_MODEL} (Reasoning DISABLED) ---")
    handle_message(msg, sqs, s3, extractor, chunker)
    
    end_time = time.time()
    duration = end_time - start_time
    print(f"--- TEST COMPLETE IN {duration:.2f} SECONDS ({duration/60:.2f} MINUTES) ---")

if __name__ == "__main__":
    run_test()
