#!/usr/bin/env python3
"""Check if a tender reference exists in the database with fuzzy matching."""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def check_tender(search_ref):
    """Search for tender by reference with fuzzy matching."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        return
    
    engine = create_engine(db_url)
    
    # Try different matching strategies
    queries = [
        # Exact match
        f"SELECT reference, title, status, s3_path FROM tenders WHERE reference = '{search_ref}' LIMIT 1",
        # Case-insensitive
        f"SELECT reference, title, status, s3_path FROM tenders WHERE LOWER(reference) = LOWER('{search_ref}') LIMIT 1",
        # Partial match with underscores
        f"SELECT reference, title, status, s3_path FROM tenders WHERE reference ILIKE '%{search_ref.replace('_', '%')}%' LIMIT 5",
        # Just the tender number/year portion
        f"SELECT reference, title, status, s3_path FROM tenders WHERE reference ILIKE '%13_2025%' AND reference ILIKE '%COMRUR%' LIMIT 5"
    ]
    
    with engine.connect() as conn:
        for i, query in enumerate(queries, 1):
            print(f"\n{'='*80}")
            print(f"Strategy {i}: {query[:100]}...")
            print(f"{'='*80}")
            
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            if rows:
                print(f"Found {len(rows)} match(es):")
                for row in rows:
                    print(f"  Reference: {row[0]}")
                    print(f"  Title: {row[1][:80]}..." if len(str(row[1])) > 80 else f"  Title: {row[1]}")
                    print(f"  Status: {row[2]}")
                    print(f"  S3 Path: {row[3]}")
                    print()
                if i <= 2:  # If found with exact/case-insensitive match, stop
                    break
            else:
                print("  No matches found")

if __name__ == "__main__":
    search_ref = sys.argv[1] if len(sys.argv) > 1 else "13_2025_COMRURS_AISBENSLI"
    print(f"Searching for tender: {search_ref}\n")
    check_tender(search_ref)
