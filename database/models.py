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
    
    # New Columns
    owner_name = Column(String(50))
    contact1 = Column(String(50))
    contact2 = Column(String(50))
    contact3 = Column(String(50))
    contact4 = Column(String(50))
    phone_1 = Column(String(50))
    phone_2 = Column(String(50))
    phone_3 = Column(String(50))
    email1 = Column(String(100))
    email2 = Column(String(100))
    email3 = Column(String(100))
    email4 = Column(String(100))
    poste1 = Column(String(100))
    poste2 = Column(String(100))
    poste3 = Column(String(100))
    poste4 = Column(String(100))
    is_client = Column(Boolean, default=False)
    is_agreements = Column(Integer)
    activity = Column(String(100))

    # Relationships
    agreements = relationship("Agreement", back_populates="contractor")
    won_results = relationship("Result", foreign_keys="[Result.winner_id]", back_populates="winner")
    # Add backref for Result winners if needed, or rely on Result.winner relationship definition


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
    
    # New Columns
    is_documents = Column(Boolean, default=False)
    is_results = Column(Boolean, default=False)
    nbr_of_lots = Column(Integer)
    s3_path = Column(String(250))
    s3_uri = Column(String(250))
    vector_path = Column(String(250))
    agrements_id = Column(Integer)
    
    # Foreign Keys
    buyer_id = Column(Integer, ForeignKey('buyers.id'))
    category_id = Column(Integer, ForeignKey('categories.id'))
    passation_mode_id = Column(Integer, ForeignKey('passation_modes.id'))
    lots_constitution_id = Column(Integer, ForeignKey('lots_constitution.id'))

    # Relationships
    buyer = relationship("Buyer", back_populates="tenders")
    category = relationship("Category", back_populates="tenders")
    passation_mode = relationship("PassationMode", back_populates="tenders")
    vector_store = relationship("TenderVectorStore", back_populates="tender", uselist=False, cascade="all, delete-orphan")
    agreements = relationship("Agreement", back_populates="tender", cascade="all, delete-orphan")
    lots = relationship("LotConstitution", foreign_keys=[lots_constitution_id], back_populates="tender_relation")
    
    # Note: 'lots' relationship above uses lots_constitution_id on Tender, which implies Tender belongs to LotConstitution?
    # Wait, the request says "Add relationship to LotConstitution (via lots_constitution_id)".
    # Usually LotConstitution belongs to Tender (one tender has many lots).
    # If Tender has lots_constitution_id, it means Tender -> 1 LotConstitution? 
    # But LotConstitution has wich_tender (FK to Tender). This seems circular or 1-to-1 if defined this way.
    # Typically LotConsitution has tender_id. The user request says "wich_tender: Integer, ForeignKey('tenders.id')" on LotConstitution.
    # And also "lots_constitution_id: Integer, ForeignKey('lots_constitution.id')" on Tender.
    # I will implement as requested but this smells like a potential circular dependency or a specific data modeling choice (e.g. main lot?).
    # For now I will add the column and relationship as requested.
    
    # Reverse relationship from LotConstitution using 'wich_tender'
    lot_details = relationship("LotConstitution", foreign_keys="[LotConstitution.wich_tender]", back_populates="tender_parent")


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


class Result(Base):
    """Result model: detailed outcome of a specific lot"""
    __tablename__ = 'results'

    id = Column(Integer, primary_key=True)
    lot_reference = Column(String(255))
    winner_id = Column(Integer, ForeignKey('contractors.id'))
    win_bid = Column(Numeric(15, 2))

    # Bidders 1-15
    bider1_id = Column(Integer, ForeignKey('contractors.id'))
    bid1 = Column(Numeric(15, 2))
    bider2_id = Column(Integer, ForeignKey('contractors.id'))
    bid2 = Column(Numeric(15, 2))
    bider3_id = Column(Integer, ForeignKey('contractors.id'))
    bid3 = Column(Numeric(15, 2))
    bider4_id = Column(Integer, ForeignKey('contractors.id'))
    bid4 = Column(Numeric(15, 2))
    bider5_id = Column(Integer, ForeignKey('contractors.id'))
    bid5 = Column(Numeric(15, 2))
    bider6_id = Column(Integer, ForeignKey('contractors.id'))
    bid6 = Column(Numeric(15, 2))
    bider7_id = Column(Integer, ForeignKey('contractors.id'))
    bid7 = Column(Numeric(15, 2))
    bider8_id = Column(Integer, ForeignKey('contractors.id'))
    bid8 = Column(Numeric(15, 2))
    bider9_id = Column(Integer, ForeignKey('contractors.id'))
    bid9 = Column(Numeric(15, 2))
    bider10_id = Column(Integer, ForeignKey('contractors.id'))
    bid10 = Column(Numeric(15, 2))
    bider11_id = Column(Integer, ForeignKey('contractors.id'))
    bid11 = Column(Numeric(15, 2))
    bider12_id = Column(Integer, ForeignKey('contractors.id'))
    bid12 = Column(Numeric(15, 2))
    bider13_id = Column(Integer, ForeignKey('contractors.id'))
    bid13 = Column(Numeric(15, 2))
    bider14_id = Column(Integer, ForeignKey('contractors.id'))
    bid14 = Column(Numeric(15, 2))
    bider15_id = Column(Integer, ForeignKey('contractors.id'))
    bid15 = Column(Numeric(15, 2))

    # Relationships
    winner = relationship("Contractor", foreign_keys=[winner_id], back_populates="won_results")
    
    # We can add relationships for bidders if needed, but it might clutter the model significantly
    # User asked: "Bidders (1 to 15): ... bider1 through bider15: relationships to Contractor."
    bider1 = relationship("Contractor", foreign_keys=[bider1_id])
    bider2 = relationship("Contractor", foreign_keys=[bider2_id])
    bider3 = relationship("Contractor", foreign_keys=[bider3_id])
    bider4 = relationship("Contractor", foreign_keys=[bider4_id])
    bider5 = relationship("Contractor", foreign_keys=[bider5_id])
    bider6 = relationship("Contractor", foreign_keys=[bider6_id])
    bider7 = relationship("Contractor", foreign_keys=[bider7_id])
    bider8 = relationship("Contractor", foreign_keys=[bider8_id])
    bider9 = relationship("Contractor", foreign_keys=[bider9_id])
    bider10 = relationship("Contractor", foreign_keys=[bider10_id])
    bider11 = relationship("Contractor", foreign_keys=[bider11_id])
    bider12 = relationship("Contractor", foreign_keys=[bider12_id])
    bider13 = relationship("Contractor", foreign_keys=[bider13_id])
    bider14 = relationship("Contractor", foreign_keys=[bider14_id])
    bider15 = relationship("Contractor", foreign_keys=[bider15_id])


class Article(Base):
    """Article model: line items in BOQ"""
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True)
    designation = Column(Text)
    quantity = Column(Numeric(15, 2))
    price = Column(Numeric(15, 2))
    unity = Column(String(50))
    
    # Foreign Key
    lot_id = Column(Integer, ForeignKey('lots_constitution.id'))
    
    # Relationship
    lot = relationship("LotConstitution", back_populates="articles")


class Designation(Base):
    """Designation model: reference table for items"""
    __tablename__ = 'designations'

    id = Column(Integer, primary_key=True)
    intitule = Column(String(255))
    description = Column(Text)
    nature = Column(String(100))
    avg_price = Column(Numeric(15, 2))


class LotConstitution(Base):
    """Lot Constitution model"""
    __tablename__ = 'lots_constitution'
    
    id = Column(Integer, primary_key=True)
    
    # New Columns replacing old ones
    lot_reference = Column(String(250))
    title = Column(String(250))
    budget = Column(Numeric(15, 2))
    bord_prix_link = Column(String(250))
    
    # Foreign Keys
    wich_tender = Column(Integer, ForeignKey('tenders.id'))
    # articles_id removed (Article now points to Lot)
    results_id = Column(Integer, ForeignKey('results.id'))
    
    # We also keep winner_contractor_id if it's still needed by Contractor relationship?
    # The user instruction said "Remove all old columns ... except id" but Contractor model has "won_lots = relationship(..., back_populates='winner_contractor')"
    # which implies LotConstitution should have a relationship back.
    # However, the user also created a `Result` model which has `winner_id`.
    # It's possible `LotConstitution` links to `Result` which links to `Contractor` (winner).
    # But for now, to avoid breaking Contractor relationship immediately without specific instruction to remove it from Contractor,
    # I will comment out the old winner_contractor_id and relationship on LotConstitution side if strictly following "Remove all old columns".
    # BUT, the user said "bider1_id ... bider15_id: Integer, ForeignKey('contractors.id')" in Result.
    # And LotConstitution has `results_id`.
    # So the winner is likely tracked in Result now.
    # I will adapt Contractor.won_lots to potentially break or point to Result?
    # Actually, the user instruction didn't say to remove `won_lots` from Contractor.
    # But it did say "Remove all old columns ... except id" for LotConstitution.
    # This implies `winner_contractor_id` is gone.
    # I will remove `winner_contractor_id` from LotConstitution.
    # This WILL break `Contractor.won_lots`. I should probably remove `won_lots` from Contractor too or comment it out / update it.
    # I'll comment out the back_populates in Contractor for now to be safe, or just remove the relationship side in LotConstitution.
    # I will assume `Contractor.won_lots` is deprecated by `Result.winner`.
    
    # Relationships
    tender_parent = relationship("Tender", foreign_keys=[wich_tender], back_populates="lot_details")
    tender_relation = relationship("Tender", foreign_keys="[Tender.lots_constitution_id]", back_populates="lots")
    articles = relationship("Article", back_populates="lot", cascade="all, delete-orphan")
    results = relationship("Result")
    
    # Legacy support note: The Contractor model expects 'won_lots'. Since we removed the column, we must update Contractor too or it will error on mapper initialization.
    # I will disable 'won_lots' on Contractor in the earlier class definition to avoid mapper errors.


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
