"""Tests for data models."""

from datetime import datetime

import pytest

from sec_connector.models import (
    ChunkState,
    ContentChunk,
    DocumentInfo,
    FilingMetadata,
    FilingState,
)


def test_filing_metadata_accession_formatting():
    """Test accession number formatting methods."""
    filing = FilingMetadata(
        cik="0000320193",
        accession_number="0000320193-23-000077",
        form="10-K",
        filing_date=datetime(2023, 11, 3),
        company_name="Apple Inc.",
        ticker="AAPL",
    )

    assert filing.accession_formatted == "0000320193-23-000077"
    assert filing.accession_no_dashes == "000032019323000077"


def test_filing_metadata_sec_url():
    """Test SEC URL generation."""
    filing = FilingMetadata(
        cik="0000320193",
        accession_number="0000320193-23-000077",
        form="10-K",
        filing_date=datetime(2023, 11, 3),
        company_name="Apple Inc.",
        ticker="AAPL",
        primary_document="aapl-20230930.htm",
    )

    assert "0000320193" in filing.sec_url
    assert "000032019323000077" in filing.sec_url
    assert "aapl-20230930.htm" in filing.sec_url


def test_content_chunk_graph_item_id():
    """Test Graph item ID generation."""
    filing = FilingMetadata(
        cik="0000320193",
        accession_number="0000320193-23-000077",
        form="10-K",
        filing_date=datetime(2023, 11, 3),
        company_name="Apple Inc.",
        ticker="AAPL",
    )

    document = DocumentInfo(
        sequence=1,
        filename="test.htm",
        document_type="10-K",
    )

    chunk = ContentChunk(
        chunk_id="test-chunk",
        filing=filing,
        document=document,
        page_number=1,
        content="Test content",
        title="Test title",
    )

    item_id = chunk.graph_item_id
    assert "0000320193" in item_id
    assert "1" in item_id


def test_filing_state_transitions():
    """Test filing state enum values."""
    assert FilingState.PENDING.value == "pending"
    assert FilingState.DOWNLOADED.value == "downloaded"
    assert FilingState.PARSED.value == "parsed"
    assert FilingState.UPLOADED.value == "uploaded"
    assert FilingState.COMPLETED.value == "completed"
    assert FilingState.FAILED.value == "failed"


def test_chunk_state_values():
    """Test chunk state enum values."""
    assert ChunkState.PENDING.value == "pending"
    assert ChunkState.UPLOADED.value == "uploaded"
    assert ChunkState.FAILED.value == "failed"
