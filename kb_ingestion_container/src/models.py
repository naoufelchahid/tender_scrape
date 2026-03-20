from typing import List, Optional, Union, Any, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict

class AvisMetadata(BaseModel):
    """Metadata extracted from avis_fr or avis_ar."""
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["avis"] = "avis"
    objet: Optional[str] = Field(None, description="The object of the tender")
    mode_de_soumission: Optional[str] = Field(None, alias="mode de soumission")
    mode_de_passation: Optional[str] = Field(None, alias="mode de passation")
    qualifications: Optional[str] = None
    budget: Optional[Union[float, str]] = None
    location: Optional[str] = None
    deadline: Optional[str] = None
    caution: Optional[Union[float, str]] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    lot_number: str = "0"

    @field_validator('budget', 'caution', mode='before')
    @classmethod
    def parse_numeric(cls, v):
        if v == "" or v is None:
            return None
        if isinstance(v, str):
            clean = v.replace('\xa0', '').replace(' ', '').replace(',', '.').replace('DH', '').strip()
            try:
                return float(clean)
            except ValueError:
                return v
        return v

class SpecificationMetadata(BaseModel):
    """Metadata for specification chunks."""
    type: Literal["specification"] = "specification"
    title: Optional[str] = Field(None, description="Content of H3 header")
    chapter: Optional[str] = Field(None, description="Content of H2 header")

class AdministrativeMetadata(BaseModel):
    """Metadata for administrative chunks."""
    type: Literal["administrative"] = "administrative"
    title: Optional[str] = Field(None, description="Content of H3 header")
    chapter: Optional[str] = Field(None, description="Content of H2 header")

class ProductChunkMetadata(BaseModel):
    """Metadata for product chunks."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["product"] = "product"
    product_header: Optional[str] = Field(None, alias="product header")
    designation: Optional[str] = None
    quantity: Optional[Union[float, str]] = None
    unit: Optional[str] = None

    @field_validator('quantity', mode='before')
    @classmethod
    def parse_numeric(cls, v):
        if v == "" or v is None:
            return None
        if isinstance(v, str):
            try:
                return float(v.replace(',', '.'))
            except ValueError:
                return v
        return v

class ChunkItem(BaseModel):
    """Represents a single extracted segment and its associated metadata."""
    content: str = Field(..., description="The Verbatim text extracted from the document.")
    metadata: Union[
        AvisMetadata, 
        SpecificationMetadata, 
        AdministrativeMetadata, 
        ProductChunkMetadata, 
        dict
    ] = Field(None, description="Structured metadata for the specific section.")

    @field_validator('metadata', mode='before')
    @classmethod
    def fix_list_metadata(cls, v: Any) -> Any:
        if isinstance(v, list):
            return v[0] if len(v) > 0 else None
        return v

class ChunkingOutput(BaseModel):
    """The root object for the LLM response."""
    chunks: List[ChunkItem] = Field(default_factory=list)

class IngestionMessage(BaseModel):
    """Message received from SQS."""
    tender_ref: str
    tender_id: int
    avis_key: Optional[str] = None
    specification_key: Optional[str] = None
    administrative_key: Optional[str] = None
    product_key: Optional[str] = None
