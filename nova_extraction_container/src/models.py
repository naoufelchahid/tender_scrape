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
    lot_number: str = Field(..., description="Lot number/identifier (e.g., '1', 'UNIQUE', '0' for single lot)")
    lot_reference: Optional[str] = Field(None, description="Tender Ref + Lot Number (e.g. 'T123_1' or 'T123_unique')")
    title: Optional[str] = Field(None, description="Title or object of the lot")
    budget_lot: Optional[float] = Field(None, description="Estimated budget for this specific lot")

class TenderMetadata(BaseModel):
    """Extracted metadata for the overall Tender."""
    tender_reference: Optional[str] = Field(None, description="Reference in format: XX_YYYY_ACRONYM_ORGANIZATION (e.g., 01_2026_DAMPS_MDT_DELM_DIRAPPMEDPROSAN)")
    location: Optional[str] = Field(None, description="Execution location (City/Region/Province)")
    global_budget: Optional[float] = Field(None, description="Total estimated budget (found in CPS or RC)")
    nbre_lots: Optional[int] = Field(None, description="Total number of lots")
    buyer: Optional[str] = Field(None, description="Full name of the public purchaser/buyer - MANDATORY")
    passation_mode: Optional[str] = Field(None, description="Mode of passation (e.g., 'Appel d'offres ouvert au rabais ou majoration')")
    type: Optional[str] = Field(None, description="Type/Domain of the tender (e.g., 'REHABILITATION DES LIEUX D'EXERCICE DE CULTE MUSULMAN')")
    agrements: List[str] = Field(default_factory=list, description="List of required certifications (D-codes like 'D1', 'D2', etc.)")

class ExtractionOutput(BaseModel):
    """Container for the full extraction result."""
    tender_info: TenderMetadata
    lots: List[LotMetadata] = Field(default_factory=list)
    products: List[ProductItem] = Field(default_factory=list)
