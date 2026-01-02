import os
import logging
from typing import List, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

# Import shared models (assumes structure is compatible)
# In Docker, we might need adjustments, but for now we rely on the file copy
# or shared volume. If running in dev, standard import works.
import sys
sys.path.append('/app')
sys.path.append('../') # Fallback for local dev

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

    def update_tender_metadata(self, tender_ref: str, metadata: 'TenderMetadata') -> Optional[int]:
        """DEPRECATED: Updates moved to downstream service."""
        logger.warning("Calling deprecated update_tender_metadata. No action taken.")
        return None

    def create_or_update_lots(self, tender_id: int, lots_data: List['LotMetadata']) -> List[int]:
        """DEPRECATED: Updates moved to downstream service."""
        logger.warning("Calling deprecated create_or_update_lots. No action taken.")
        return []

    def insert_products(self, tender_id: int, products: List['ProductItem']):
        """DEPRECATED: Updates moved to downstream service."""
        logger.warning("Calling deprecated insert_products. No action taken.")
        pass
