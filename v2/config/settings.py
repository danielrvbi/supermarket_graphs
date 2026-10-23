"""
Configuration settings for V2 pipeline.
Loads from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Mistral API
    MISTRAL_KEY: str = Field(default="", description="Mistral API key")
    MISTRAL_MODEL: str = Field(
        default="mistral-small-latest",
        description="Mistral model to use"
    )

    # Paths
    BASE_DIR: str = Field(default=".", description="Project base directory")
    RAW_RECEIPTS_DIR: str = Field(default="raw_receipts", description="Raw receipts directory")
    PROCESSED_DIR: str = Field(default="processed", description="Processed output directory")
    CHECKPOINTS_DIR: str = Field(default="v2/checkpoints", description="LangGraph checkpoints directory")
    TOKEN_USAGE_DB: str = Field(default="v2/checkpoints/token_usage.db", description="Token usage database path")

    # Pipeline settings
    CONFIDENCE_THRESHOLD_APPROVE: float = Field(default=0.95, description="Auto-approve threshold")
    CONFIDENCE_THRESHOLD_REVIEW: float = Field(default=0.70, description="Review queue threshold")

    # Validation tolerances
    ARITHMETIC_TOLERANCE: float = Field(default=0.02, description="Tolerance for qty × price = total")
    RECONCILIATION_TOLERANCE: float = Field(default=0.05, description="Tolerance for sum = receipt total")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Singleton instance
settings = Settings()
