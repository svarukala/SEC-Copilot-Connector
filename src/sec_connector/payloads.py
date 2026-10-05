"""Canonical external-item serialization shared by transport and sync state."""

import hashlib
import json
from datetime import timezone
from pathlib import Path

from .models import ContentChunk, GraphExternalItem


def chunk_to_external_item(chunk: ContentChunk, icon_url: str) -> GraphExternalItem:
    """Build the exact request model without authentication or configuration I/O."""
    filing = chunk.filing
    filing_date = filing.filing_date
    if filing_date.tzinfo is None:
        filing_date = filing_date.replace(tzinfo=timezone.utc)

    properties = {
        "Title": f"{chunk.title} [{filing.ticker}] - {chunk.document.filename}",
        "Company": filing.company_name,
        "Ticker": filing.ticker,
        "Form": filing.form,
        "FilingDate": filing_date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "Description": chunk.document.description or f"{filing.form} filing for {filing.company_name}",
        "Url": filing.document_url(chunk.document.filename),
        "CIK": filing.cik,
        "AccessionNumber": filing.accession_number,
        "Sequence": chunk.document.sequence,
        "Page": chunk.page_number,
        "IconUrl": icon_url,
        "FilingUrl": filing.filing_url,
        "DocumentName": chunk.document.filename,
        "FileExtension": Path(chunk.document.filename).suffix.lstrip(".").lower(),
        "DocumentType": chunk.document.document_type,
        "DocumentId": hashlib.sha256(
            filing.document_url(chunk.document.filename).encode("utf-8")
        ).hexdigest(),
        "ChunkOrdinal": chunk.chunk_ordinal,
        "IsAmendment": filing.is_amendment,
    }
    if chunk.section_title:
        properties["SectionTitle"] = chunk.section_title
    if filing.fiscal_report_period_end:
        properties["ReportPeriodEnd"] = filing.fiscal_report_period_end.strftime("%Y-%m-%dT00:00:00Z")
    if filing.acceptance_datetime:
        if filing.acceptance_datetime.tzinfo is None:
            raise ValueError("SEC acceptance_datetime must include its source timezone")
        properties["AcceptanceDateTime"] = filing.acceptance_datetime.astimezone(
            timezone.utc
        ).isoformat().replace("+00:00", "Z")

    return GraphExternalItem(
        id=chunk.graph_item_id,
        properties=properties,
        content={"type": "text", "value": chunk.content},
    )


def serialize_item(payload: dict) -> bytes:
    return json.dumps(
        {key: value for key, value in payload.items() if key != "id"},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False,
    ).encode("utf-8")


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(serialize_item(payload)).hexdigest()
