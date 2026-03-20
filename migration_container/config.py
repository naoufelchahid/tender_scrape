"""
Configuration for the SQL → Neptune migration container.
Reads settings from environment variables (lazily on first access).

DATABASE_URL is REQUIRED at runtime but NOT at import time,
so test modules can import without it set.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


class MigrationSettings:
    """
    Lazy configuration object.  Reads each env-var on first property access
    so that `from migration_container.config import settings` never fails
    when env vars are absent (e.g., in unit tests).
    """

    # ---- required at runtime ----
    @property
    def DATABASE_URL(self) -> str:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise EnvironmentError(
                "DATABASE_URL environment variable is required"
            )
        return url

    # ---- Neptune ----
    @property
    def NEPTUNE_ENDPOINT(self) -> str:
        return os.environ.get("NEPTUNE_ENDPOINT", "localhost")

    @property
    def NEPTUNE_PORT(self) -> int:
        return int(os.environ.get("NEPTUNE_PORT", "8182"))

    @property
    def AWS_REGION(self) -> str:
        return os.environ.get("AWS_REGION", "eu-west-1")

    @property
    def NEPTUNE_USE_IAM(self) -> bool:
        return os.environ.get("NEPTUNE_USE_IAM", "true").lower() == "true"

    # ---- migration behaviour ----
    @property
    def BATCH_SIZE(self) -> int:
        return int(os.environ.get("BATCH_SIZE", "100"))

    @property
    def DRY_RUN(self) -> bool:
        return os.environ.get("DRY_RUN", "false").lower() == "true"

    @property
    def LOG_LEVEL(self) -> str:
        return os.environ.get("LOG_LEVEL", "INFO")


# Singleton — modules import this object directly
settings = MigrationSettings()
