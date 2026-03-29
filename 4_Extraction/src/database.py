import os
import logging
from typing import List, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

# Import shared models from database package
# Docker PYTHONPATH=/app is set in Dockerfile
from database.models import Tender, LotConstitution, Article, Base

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    @contextmanager
    def get_session(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def get_tender_id_by_reference(self, tender_ref: str) -> Optional[int]:
        """Lookup tender ID from reference."""
        with self.get_session() as session:
            tender = session.query(Tender).filter(Tender.reference == tender_ref).first()
            return tender.id if tender else None
