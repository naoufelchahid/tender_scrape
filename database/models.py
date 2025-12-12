"""
Database models for tender scraper using SQLAlchemy
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, JSON, ForeignKey, Numeric, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()


class Category(Base):
    """Category model"""
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    tenders = relationship("Tender", back_populates="category")


class PassationMode(Base):
    """Passation Mode model"""
    __tablename__ = 'passation_modes'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    tenders = relationship("Tender", back_populates="passation_mode")


class Buyer(Base):
    """Buyer model"""
    __tablename__ = 'buyers'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    initials = Column(String(10))
    type = Column(String(100))
    location = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    tenders = relationship("Tender", back_populates="buyer")


class Contractor(Base):
    """Contractor model"""
    __tablename__ = 'contractors'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    registration_number = Column(String(100), unique=True)
    email = Column(String(255))
    phone = Column(String(50))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    agreements = relationship("Agreement", back_populates="contractor")
    won_lots = relationship("LotConstitution", back_populates="winner_contractor")


class Tender(Base):
    """Tender model"""
    __tablename__ = 'tenders'
    
    id = Column(Integer, primary_key=True)
    reference = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(Text)
    publication_date = Column(DateTime)
    deadline = Column(DateTime)
    execution_location = Column(String(255))
    lot_count = Column(Integer)
    budget = Column(Numeric)
    status = Column(String(50))
    raw_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_scraped_at = Column(DateTime)
    
    # Foreign Keys
    buyer_id = Column(Integer, ForeignKey('buyers.id'))
    category_id = Column(Integer, ForeignKey('categories.id'))
    passation_mode_id = Column(Integer, ForeignKey('passation_modes.id'))
    
    # Relationships
    buyer = relationship("Buyer", back_populates="tenders")
    category = relationship("Category", back_populates="tenders")
    passation_mode = relationship("PassationMode", back_populates="tenders")
    documents = relationship("TenderDocument", back_populates="tender", cascade="all, delete-orphan")
    vector_store = relationship("TenderVectorStore", back_populates="tender", uselist=False, cascade="all, delete-orphan")
    agreements = relationship("Agreement", back_populates="tender", cascade="all, delete-orphan")
    lots = relationship("LotConstitution", back_populates="tender", cascade="all, delete-orphan")


class TenderDocument(Base):
    """Tender document model"""
    __tablename__ = 'tender_documents'
    
    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey('tenders.id'), nullable=False)
    document_name = Column(String(255))
    document_type = Column(String(50))
    document_size = Column(String(50))
    downloaded = Column(Boolean, default=False)
    s3_path = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    tender = relationship("Tender", back_populates="documents")


class TenderVectorStore(Base):
    """Tender Vector Store model"""
    __tablename__ = 'tenders_vector_stores'
    
    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey('tenders.id'), nullable=False)
    vector_data = Column(LargeBinary)
    embedding_model = Column(String(100))
    metadata_json = Column('metadata', JSON)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    tender = relationship("Tender", back_populates="vector_store")


class Agreement(Base):
    """Agreement model"""
    __tablename__ = 'agreements'
    
    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey('tenders.id'), nullable=False)
    contractor_id = Column(Integer, ForeignKey('contractors.id'))
    agreement_number = Column(String(100))
    amount = Column(Numeric(15, 2))
    signed_date = Column(DateTime)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    status = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    tender = relationship("Tender", back_populates="agreements")
    contractor = relationship("Contractor", back_populates="agreements")


class LotConstitution(Base):
    """Lot Constitution model"""
    __tablename__ = 'lots_constitution'
    
    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey('tenders.id'))
    lot_number = Column(String(50))
    description = Column(Text)
    amount = Column(Numeric(15, 2))
    status = Column(String(50))
    deadline = Column(DateTime)
    winner_contractor_id = Column(Integer, ForeignKey('contractors.id'))
    
    # Relationships
    tender = relationship("Tender", back_populates="lots")
    winner_contractor = relationship("Contractor", back_populates="won_lots")


class Database:
    """Database connection and session manager"""
    
    def __init__(self, database_url: str):
        """
        Initialize database connection
        
        Args:
            database_url: SQLAlchemy database URL
        """
        self.engine = create_engine(database_url, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def create_tables(self):
        """Create all tables"""
        Base.metadata.create_all(bind=self.engine)
    
    def get_session(self):
        """Get a new database session"""
        return self.SessionLocal()
    
    def drop_tables(self):
        """Drop all tables (use with caution!)"""
        Base.metadata.drop_all(bind=self.engine)
