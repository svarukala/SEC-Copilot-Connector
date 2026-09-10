"""Configuration loading and validation."""

import os
import re
from datetime import date
from pathlib import Path
from importlib.resources import files
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings

GRAPH_MAX_ITEM_BYTES = 30 * 1024 * 1024


class SECConfig(BaseModel):
    """SEC API configuration."""
    user_agent: str = "SEC-Connector/1.0 (your-email@example.com)"
    rate_limit: int = Field(default=10, gt=0, le=10)
    base_url: str = "https://www.sec.gov"
    data_url: str = "https://data.sec.gov"


class AzureConfig(BaseModel):
    """Azure/Microsoft Graph configuration."""
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    connection_id: str = "pysecfilings"
    connection_name: str = "SEC EDGAR Filings"
    connection_description: str = "SEC EDGAR filings including 10-K, 10-Q, 8-K, and DEF 14A forms"
    icon_url: str = "https://www.sec.gov/favicon.ico"


class FilingsConfig(BaseModel):
    """Filing types to process."""
    forms: list[str] = Field(default_factory=lambda: ["10-K", "10-Q", "8-K", "DEF 14A"])
    include_history: bool = True
    include_amendments: bool = True
    include_exhibits: bool = True
    exhibit_types: list[str] = Field(default_factory=lambda: ["EX-99", "EX-10", "EX-21"])
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "FilingsConfig":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class ChunkingConfig(BaseModel):
    """Content chunking configuration."""
    target_size: int = Field(default=4000, gt=0)
    max_size: int = Field(default=8000, gt=0)
    overlap: int = Field(default=200, ge=0)
    max_item_bytes: int = Field(default=GRAPH_MAX_ITEM_BYTES, ge=4, le=GRAPH_MAX_ITEM_BYTES)

    @model_validator(mode="after")
    def validate_sizes(self) -> "ChunkingConfig":
        if self.target_size > self.max_size:
            raise ValueError("target_size must not exceed max_size")
        if self.overlap >= self.target_size:
            raise ValueError("overlap must be smaller than target_size")
        return self


class ProcessingConfig(BaseModel):
    """Processing configuration."""
    concurrent_downloads: int = Field(default=5, gt=0)
    batch_size: int = Field(default=20, gt=0)
    ocr_images: bool = False  # Local assets, Pillow, pytesseract, and Tesseract are required.


class SyncConfig(BaseModel):
    refresh_downloads: bool = True
    prune_missing_filings: bool = False


class TestModeConfig(BaseModel):
    """Test mode limits."""
    max_filings: int = Field(default=2, gt=0)
    max_pages: int = Field(default=5, gt=0)


class PathsConfig(BaseModel):
    """File paths configuration."""
    downloads: str = "data/downloads"
    payloads: str = "data/payloads"
    database: str = "data/state.db"
    logs: str = "data/logs"


class AppConfig(BaseSettings):
    """Main application configuration."""
    sec: SECConfig = Field(default_factory=SECConfig)
    azure: AzureConfig = Field(default_factory=AzureConfig)
    filings: FilingsConfig = Field(default_factory=FilingsConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    test_mode: TestModeConfig = Field(default_factory=TestModeConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    class Config:
        env_prefix = ""
        extra = "ignore"


def expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, value)
        for match in matches:
            env_value = os.environ.get(match, "")
            value = value.replace(f"${{{match}}}", env_value)
        return value
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML file with environment variable expansion."""
    if config_path is None:
        local = Path("config") / "config.yaml"
        packaged = files("sec_connector").joinpath("resources", "config.yaml")
        config_path = local if local.is_file() else packaged if packaged.is_file() else (
            Path(__file__).parent.parent.parent / "config" / "config.yaml"
        )
    with config_path.open(encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    config_data = expand_env_vars(config_data)

    return AppConfig(**config_data)


def ensure_directories(config: AppConfig) -> None:
    """Create required directories if they don't exist."""
    for path_attr in ["downloads", "payloads", "database", "logs"]:
        path = Path(getattr(config.paths, path_attr))
        if path_attr == "database":
            path = path.parent
        path.mkdir(parents=True, exist_ok=True)
