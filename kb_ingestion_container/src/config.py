import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # AWS Configuration
    AWS_REGION: str = "eu-west-3"
    KB_INGESTION_QUEUE_URL: str
    S3_BUCKET_NAME: str
    DLQ_URL: Optional[str] = None

    # Neptune Configuration
    NEPTUNE_ENDPOINT: str
    NEPTUNE_PORT: int = 8182
    NEPTUNE_REAL_HOST: str = ""
    NEPTUNE_USE_IAM: bool = True

    # OpenRouter / Embedding Configuration
    OPENROUTER_API_KEY: str
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

    # Ontology Configuration
    ONTOLOGY_DIR: str = "/app/ontology"
    TENDER_STRUCTURE_FILE: str = "tender_structure.ttl"
    SHACL_SHAPES_FILE: str = "shapes.ttl"

    # Operational Flags
    VALIDATION_STRICT: bool = False
    BATCH_SIZE: int = 10

    # Vector Storage
    VECTOR_S3_PREFIX: str = "vector_store/"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
