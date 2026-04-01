from typing import List, Optional, Union, Any, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict


class SpecificationMetadata(BaseModel):
    """Metadata for specification chunks."""
    type: Literal["specification"] = "specification"
    title: Optional[str] = Field(None, description="Content of H3 header (chunk identifier)")
    chapter: Optional[str] = Field(None, description="Content of H2 header")


class AdministrativeMetadata(BaseModel):
    """Metadata for administrative chunks."""
    type: Literal["administrative"] = "administrative"
    title: Optional[str] = Field(None, description="Content of H3 header (chunk identifier)")
    chapter: Optional[str] = Field(None, description="Content of H2 header")


class ProductChunkMetadata(BaseModel):
    """Metadata for product chunks — supports flat and nested product structures."""
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

    @classmethod
    def extract_nested_products(cls, metadata: dict) -> List["ProductChunkMetadata"]:
        """
        Handle nested product_1, product_2 structure inside a metadata dict.
        Returns a flat list of ProductChunkMetadata instances.
        """
        products = []
        # Check for nested product_N keys
        nested_keys = sorted([k for k in metadata if k.startswith("product_") and k[8:].isdigit()])
        if nested_keys:
            for key in nested_keys:
                entry = metadata[key]
                if isinstance(entry, dict):
                    entry.setdefault("type", "product")
                    try:
                        products.append(cls(**entry))
                    except Exception:
                        pass
        else:
            # Flat single product
            try:
                products.append(cls(**metadata))
            except Exception:
                pass
        return products


class ChunkItem(BaseModel):
    """Represents a single extracted segment and its associated metadata."""
    content: str = Field(..., description="The verbatim text extracted from the document.")
    metadata: Union[
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
