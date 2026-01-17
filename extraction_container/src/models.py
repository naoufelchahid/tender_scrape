from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ProductItem(BaseModel):
    """Represents a single line item in a Bill of Quantities (Bordereau des Prix)."""
    designation: str = Field(..., description="Description or name of the product/service")
    unit: str = Field(..., description="Unit of measurement (e.g., m2, kg, u)")
    quantity: float = Field(..., description="Quantity required")
    estimated_price: Optional[float] = Field(None, description="Unit estimated price if available")
    lot_number: Optional[str] = Field(None, description="Reference to the Lot this product belongs to")

class ProductList(BaseModel):
    products: List[ProductItem]

class LotMetadata(BaseModel):
    """Represents a Lot within a Tender."""
    lot_number: str = Field(..., description="Lot number/identifier (e.g., '1', 'Lot 01')")
    lot_reference: Optional[str] = Field(None, description="Tender Ref + Lot Number (e.g. 'T123-1')")
    title: str = Field(..., description="Title or object of the lot")
    budget_lot: Optional[float] = Field(None, description="Estimated budget for this specific lot")

class TenderMetadata(BaseModel):
    """Extracted metadata for the overall Tender."""
    tender_reference: Optional[str] = Field(None, description="Reference of the tender")
    deadline: Optional[datetime] = Field(None, description="Submission deadline datetime")
    publication_date: Optional[datetime] = Field(None, description="Date of publication")
    location: Optional[str] = Field(None, description="Execution location (City/Region)")
    global_budget: Optional[float] = Field(None, description="Total estimated budget for the tender")
    nbre_lots: Optional[int] = Field(None, description="Total number of lots")
    buyer: Optional[str] = Field(None, description="Name of the public purchaser/buyer")
    buyer_address: Optional[str] = Field(None, description="Address of the buyer")
    buyer_phone: Optional[str] = Field(None, description="Phone number of the buyer")
    buyer_email: Optional[str] = Field(None, description="Email of the buyer")
    buyer_contact: Optional[str] = Field(None, description="Contact person name")
    passation_mode: Optional[str] = Field(None, description="Mode of passation (e.g., AO Ouvert)")
    type: Optional[str] = Field(None, description="Type/Domain of the tender (formerly category)")
    agrements: List[str] = Field(default_factory=list, description="List of required certifications (D-codes like 'D1', 'D2', etc.)")

class ExtractionOutput(BaseModel):
    """Container for the full extraction result."""
    tender_info: TenderMetadata
    lots: List[LotMetadata] = Field(default_factory=list)
    products: List[ProductItem] = Field(default_factory=list)

# ============================================================================
# Chunking Output Models (for LLM-based chunking with JSON output)
# ============================================================================

class ChunkMetadata(BaseModel):
    """Metadata for a single chunk."""
    type: str = Field(..., description="Chunk type: avis, specification, administrative, or products")
    lot: Optional[str] = Field(None, description="Lot number if applicable (e.g., '1', '2')")
    
    # Product-specific fields (only for type='products')
    designation: Optional[str] = Field(None, description="Product designation (for products only)")
    quantity: Optional[str | float | int] = Field(None, description="Quantity (for products only)")
    unit: Optional[str] = Field(None, description="Unit of measurement (for products only)")
    
    # Specification/Administrative fields
    article_id: Optional[str] = Field(None, description="Article identifier (e.g., 'Art_1', 'Art_2')")

class ChunkItem(BaseModel):
    """A single chunk with content and metadata."""
    content: str = Field(..., description="The actual text content of the chunk")
    metadata: ChunkMetadata = Field(..., description="Metadata describing this chunk")

class ChunkingOutput(BaseModel):
    """Complete output from LLM chunking operation."""
    chunks: List[ChunkItem] = Field(default_factory=list, description="List of all chunks")
