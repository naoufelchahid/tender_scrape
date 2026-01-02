import os
import sys
# Ensure we can import from src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database import DatabaseManager
from database.models import Tender
from dotenv import load_dotenv

load_dotenv()

def seed_tender():
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("Error: DB_URL not set")
        return

    db = DatabaseManager(db_url)
    ref = "0002elfida_2025_DELPREMINJEUSPOPREALFMERSUL"
    
    with db.get_session() as session:
        # Check if exists
        tender = session.query(Tender).filter(Tender.reference == ref).first()
        if tender:
            print(f"Tender {ref} already exists with ID {tender.id}")
        else:
            print(f"Creating Tender {ref}...")
            tender = Tender(
                reference=ref,
                title="Test Tender for Extraction",
                execution_location="Test Location",
                status="in_progress"
            )
            session.add(tender)
            session.commit()
            print(f"Created Tender {ref} with ID {tender.id}")

if __name__ == "__main__":
    seed_tender()
