"""Pydantic data models for SEC filings and Graph items."""

from datetime import datetime
from enum import Enum
from typing import Optional
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator


class FilingState(str, Enum):
    """State machine for filing processing."""
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    PARSED = "parsed"
    UPLOADED = "uploaded"
    COMPLETED = "completed"
    FAILED = "failed"
    SAMPLED = "sampled"
    RETIRING = "retiring"


class ChunkState(str, Enum):
    """State machine for chunk processing."""
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class FilingMetadata(BaseModel):
    """Metadata for a single SEC filing."""
    cik: str
    accession_number: str
    form: str
    filing_date: datetime
    company_name: str
    ticker: str
    primary_document: Optional[str] = None
    file_number: Optional[str] = None
    report_period_end: Optional[datetime] = None
    acceptance_datetime: Optional[datetime] = None

    @property
    def is_amendment(self) -> bool:
        return self.form.endswith("/A")

    @property
    def filing_url(self) -> str:
        return self.document_url(f"{self.accession_number}-index.html")

    def document_url(self, filename: str) -> str:
        return (
            f"https://www.sec.gov/Archives/edgar/data/{self.cik}/"
            f"{self.accession_no_dashes}/{quote(filename, safe='/')}"
        )

    @property
    def accession_formatted(self) -> str:
        """Return accession number formatted for URLs (with dashes)."""
        return self.accession_number

    @property
    def accession_no_dashes(self) -> str:
        """Return accession number without dashes for directory names."""
        return self.accession_number.replace("-", "")

    @property
    def sec_url(self) -> str:
        """Return the SEC EDGAR URL for this filing."""
        return self.document_url(self.primary_document) if self.primary_document else self.filing_url


class DocumentInfo(BaseModel):
    """Information about a document within a filing."""
    sequence: int
    filename: str
    document_type: str
    description: Optional[str] = None
    size: Optional[int] = None

    @field_validator("size", mode="before")
    @classmethod
    def parse_size(cls, v):
        """Convert empty strings to None for size field."""
        if v == "" or v is None:
            return None
        if isinstance(v, str):
            return int(v)
        return v


class ParsedDocument(BaseModel):
    """A parsed document ready for chunking."""
    filing: FilingMetadata
    document: DocumentInfo
    content: str
    content_type: str = "text/markdown"


class ContentChunk(BaseModel):
    """A chunk of content ready for upload to Graph."""
    chunk_id: str
    filing: FilingMetadata
    document: DocumentInfo
    page_number: int
    subchunk_number: Optional[int] = None
    chunk_ordinal: int = 1
    section_title: Optional[str] = None
    content: str
    title: str

    @property
    def graph_item_id(self) -> str:
        """Generate a unique ID for the Graph external item."""
        item_id = f"{self.filing.cik}-{self.filing.accession_no_dashes}-{self.document.sequence}-{self.page_number}"
        if self.subchunk_number is not None:
            item_id += f"-{self.subchunk_number}"
        return item_id


class GraphExternalItem(BaseModel):
    """External item for Microsoft Graph connector."""
    id: str
    properties: dict
    content: dict
    acl: list = Field(default_factory=lambda: [
        {
            "type": "everyone",
            "value": "everyone",
            "accessType": "grant"
        }
    ])


class FilingRecord(BaseModel):
    """Database record for a filing."""
    id: Optional[int] = None
    cik: str
    accession_number: str
    ticker: str
    company_name: str
    form: str
    filing_date: datetime
    primary_document: Optional[str] = None
    file_number: Optional[str] = None
    report_period_end: Optional[datetime] = None
    acceptance_datetime: Optional[datetime] = None
    inventory_complete: bool = False
    payloads_ready: bool = False
    sample_limit: Optional[int] = None
    processing_options: dict = Field(default_factory=dict)
    state: FilingState = FilingState.PENDING
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ChunkRecord(BaseModel):
    """Database record for a chunk."""
    id: Optional[int] = None
    filing_id: int
    chunk_id: str
    page_number: int
    sequence: int
    state: ChunkState = ChunkState.PENDING
    error_message: Optional[str] = None
    payload: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
