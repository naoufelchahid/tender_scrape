from typing import List, Optional, Union, Any
from pydantic import BaseModel, Field, field_validator

# ============================================================================
# Chunking Output Models (for LLM-based chunking with JSON output)
# ============================================================================

class ChunkMetadata(BaseModel):
    """Metadata for a single chunk."""
    type: str = Field(..., description="Chunk type")
    lot: Optional[str] = Field(None, description="Lot number")
    
    # Common fields
    title: Optional[str] = Field(None, description="Short description")

    # Product-specific fields
    designation: Optional[str] = Field(None)
    # Allow string or float, and coerce empty strings to None
    quantity: Optional[Union[float, str]] = Field(None)
    unit: Optional[str] = Field(None)
    estimated_price: Optional[Union[float, str]] = Field(None)
    
    # Specification fields
    spec_type: Optional[str] = Field(None)
    article_id: Optional[str] = Field(None)

    # Administrative fields
    clause_type: Optional[str] = Field(None)

    # Avis fields
    budget: Optional[Union[float, str]] = Field(None)
    location: Optional[str] = Field(None)
    deadline: Optional[str] = Field(None)
    caution: Optional[Union[float, str]] = Field(None)
    lot_structure: Optional[str] = Field(None)

    @field_validator('quantity', 'estimated_price', 'budget', 'caution', mode='before')
    def parse_numeric(cls, v):
        if v == "" or v is None:
            return None
        if isinstance(v, str):
            # Remove spaces, commas, currrency symbols if typical noise
            clean = v.replace(' ', '').replace(',', '.').replace('DH', '').strip()
            try:
                return float(clean)
            except ValueError:
                return v # Return original string if fail, better than crash? 
                         # Actually, keep as Optional[Union[float, str]] allows string return.
        return v

class ChunkItem(BaseModel):
    """A single chunk with content and metadata."""
    content: str = Field(..., description="The actual text content")
    # Make metadata optional or provide default to avoid 'missing' error if LLM hallucinates structure
    metadata: Optional[ChunkMetadata] = Field(None)

class ChunkingOutput(BaseModel):
    """Complete output from LLM chunking operation."""
    # Allow relaxed list parsing
    chunks: List[ChunkItem] = Field(default_factory=list)

