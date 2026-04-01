import os
import logging
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from contextlib import contextmanager

Base = declarative_base()

class Tender(Base):
    __tablename__ = "tenders"
    id = Column(Integer, primary_key=True)
    reference = Column(String, unique=True, index=True)

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
