from typing import List, Optional, Union, Any
from pydantic import BaseModel, Field, field_validator

class ChunkMetadata(BaseModel):
    """
    Detailed metadata extracted from tender documents. 
    Descriptions here act as instructions for the LLM.
    """
    type: str = Field(
        ..., 
        description="STRICT CATEGORY. Must be one of: 'specification' (technical requirements), 'administrative' (rules/clauses), 'product' (bill of quantities/pricing items), 'avis' (tender notice), 'form' (declarations). Default to 'other' if unsure."
    )
    
    # Common fields
    title: Optional[str] = Field(None, description="Concise header or summary of this section. (e.g., 'Article 5: Cautionnement').")

    # Product-specific fields
    designation: Optional[str] = Field(None, description="PRODUCT NAME. The exact, verbatim description of the line item. Do not paraphrase.")
    quantity: Optional[Union[float, str]] = Field(None, description="QUANTITY. Extract pure number if possible. If text is '12 mois', extract 12. If 'Forfait', leave null or use 1.")
    unit: Optional[str] = Field(None, description="UNIT. The unit of measurement (e.g., 'm²', 'kg', 'U', 'Ens', 'Forfait').")
    estimated_price: Optional[Union[float, str]] = Field(None, description="PRICE. The estimated UNIT price. If only total is available, explicitly note in title or designate as total.")
    
    # Specification fields
    spec_type: Optional[str] = Field(None, description="SPEC CATEGORY. Must be one of : 'product_spec', 'contractor_requirement', 'general_spec', 'administratif_spec', 'legal_normal'")
    # Administrative fields
    clause_type: Optional[str] = Field(None, description="CLAUSE CATEGORY.  Must be one of : 'general_clause', 'bidding_modalities', 'bid_eval_critera', 'contractor_eval_criterea', 'attribution_criterea'")

    # Avis / Administrative fields
    budget: Optional[Union[float, str]] = Field(None, description="TOTAL BUDGET. The overall estimated cost found in the Tender Notice (Avis).")
    location: Optional[str] = Field(None, description="LOCATION. City or Province of execution (e.g., 'Rabat', 'Casablanca').")
    deadline: Optional[str] = Field(None, description="DEADLINE. Submission deadline or date of opening of bids (formatted YYYY-MM-DD or 'X days').")
    caution: Optional[Union[float, str]] = Field(None, description="CAUTION. The provisional guarantee amount (number).")
    lot_number: Optional[str] = Field(None, description="LOT NUMBER. The specific Lot Number (e.g., '1', '2').")
    
    # Form fields
    form_type: Optional[str] = Field(None, description="FORM TYPE. Must be 'engagement' (Acte d'engagement) or 'declaration' (Déclaration sur l'honneur).")

    model_config = {"extra": "allow"}

    @field_validator('quantity', 'estimated_price', 'budget', 'caution', mode='before')
    @classmethod
    def parse_numeric(cls, v):
        if v == "" or v is None:
            return None
        if isinstance(v, str):
            # Handle non-breaking spaces (\xa0) and common Moroccan formatting
            clean = v.replace('\xa0', '').replace(' ', '').replace(',', '.').replace('DH', '').strip()
            try:
                # Attempt to convert to float, but fall back to string if it's descriptive (e.g., "A déterminer")
                return float(clean)
            except ValueError:
                return v 
        return v

class ChunkItem(BaseModel):
    """Represents a single extracted segment and its associated metadata."""
    content: str = Field(..., description="The Verbatim text extracted from the document.")
    metadata: Optional[ChunkMetadata] = Field(
        None, 
        description="Structured metadata. Must be a single object, not a list."
    )

    @field_validator('metadata', mode='before')
    @classmethod
    def fix_list_metadata(cls, v: Any) -> Any:
        """
        Fixes the error where LLMs return [ {metadata} ] instead of {metadata}.
        """
        if isinstance(v, list):
            return v[0] if len(v) > 0 else None
        return v

class ChunkingOutput(BaseModel):
    """The root object for the LLM response."""
    chunks: List[ChunkItem] = Field(
        default_factory=list, 
        description="A list of content chunks with their respective metadata."
    )
