import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # AWS Configuration
    AWS_REGION: str = "eu-west-3"
    KB_INGESTION_QUEUE_URL: str
    S3_BUCKET_NAME: str
    DLQ_URL: Optional[str] = None

    # S3 Chunk Data
    S3_CHUNKS_PREFIX: str = "chunks_tender/"

    # Jena Configuration
    JENA_ENDPOINT: str = "http://fuseki:3030"
    JENA_DATASET: str = "tenders"
    JENA_USERNAME: str = "admin"
    JENA_PASSWORD: str

    # OpenRouter / Embedding Configuration
    OPENROUTER_API_KEY: str
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

    # Ontology Configuration
    ONTOLOGY_DIR: str = "/app/ontology"
    TENDER_STRUCTURE_FILE: str = "tender_structure.owl"
    SHACL_SHAPES_FILE: str = "shapes.ttl"
    ENRICHMENT_SHAPES_FILE: str = "shapes_enrichment.ttl"

    # Operational Flags
    VALIDATION_STRICT: bool = False
    BATCH_SIZE: int = 10

    # Vector Storage
    VECTOR_S3_BUCKET: str = "my-tender-vectors-bucket"
    VECTOR_S3_PREFIX: str = "index/tender-index/"

    # N-Triples Output
    NT_OUTPUT_DIR: str = "/tmp/nt_output"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
