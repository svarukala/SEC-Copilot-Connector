"""Tests for document chunking."""

from datetime import datetime

import pytest

from sec_connector.chunker import (
    chunk_document,
    enforce_size_limit,
    split_by_pages,
    split_by_sections,
    split_by_size,
)
from sec_connector.config import ChunkingConfig
from sec_connector.models import DocumentInfo, FilingMetadata, ParsedDocument


@pytest.fixture
def sample_filing():
    """Create a sample filing for testing."""
    return FilingMetadata(
        cik="0000320193",
        accession_number="0000320193-23-000077",
        form="10-K",
        filing_date=datetime(2023, 11, 3),
        company_name="Apple Inc.",
        ticker="AAPL",
    )


@pytest.fixture
def sample_document():
    """Create a sample document for testing."""
    return DocumentInfo(
        sequence=1,
        filename="test.htm",
        document_type="10-K",
    )


@pytest.fixture
def chunking_config():
    """Create chunking config for testing."""
    return ChunkingConfig(
        target_size=1000,
        max_size=2000,
        overlap=100,
    )


def test_split_by_pages():
    """Test page-based splitting."""
    content = "Page 1 content\n\n---PAGE---\n\nPage 2 content\n\n---PAGE---\n\nPage 3 content"
    pages = split_by_pages(content)

    assert len(pages) == 3
    assert pages[0] == "Page 1 content"
    assert pages[1] == "Page 2 content"
    assert pages[2] == "Page 3 content"


def test_split_by_sections():
    """Test section header splitting."""
    content = "# Section 1\n\nContent 1\n\n## Section 2\n\nContent 2\n\n### Section 3\n\nContent 3"
    sections = split_by_sections(content)

    assert len(sections) == 3
    assert "Section 1" in sections[0]
    assert "Section 2" in sections[1]
    assert "Section 3" in sections[2]


def test_split_by_size():
    """Test size-based splitting."""
    content = "Word " * 500  # ~2500 chars
    chunks = split_by_size(content, target_size=500, max_size=1000, overlap=50)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000


def test_enforce_size_limit_small_content():
    """Test that small content is not split."""
    content = "Small content"
    result = enforce_size_limit(content, max_bytes=1000)

    assert len(result) == 1
    assert result[0] == content


def test_chunk_document(sample_filing, sample_document, chunking_config):
    """Test full document chunking."""
    content = "Page 1\n\n---PAGE---\n\nPage 2\n\n---PAGE---\n\nPage 3"

    parsed = ParsedDocument(
        filing=sample_filing,
        document=sample_document,
        content=content,
    )

    chunks = chunk_document(parsed, chunking_config)

    assert len(chunks) == 3
    assert all(c.filing == sample_filing for c in chunks)
    assert all(c.document == sample_document for c in chunks)


def test_chunk_document_no_markers(sample_filing, sample_document, chunking_config):
    """Test chunking without page markers falls back to size-based."""
    content = "Word " * 1000  # Long content without markers

    parsed = ParsedDocument(
        filing=sample_filing,
        document=sample_document,
        content=content,
    )

    chunks = chunk_document(parsed, chunking_config)

    assert len(chunks) > 1


def test_default_item_limit_is_30_mib():
    assert ChunkingConfig().max_item_bytes == 30 * 1024 * 1024


@pytest.mark.parametrize("content", ["x" * 1000, "\U0001f600" * 1000, "a" * 53 + "\u20ac" * 100])
def test_byte_limit_preserves_all_content(content):
    chunks = enforce_size_limit(content, 100)
    assert "".join(chunks) == content
    assert all(len(chunk.encode("utf-8")) <= 100 for chunk in chunks)


def test_long_second_paragraph_is_bounded():
    content = "short paragraph\n\n" + "word " * 1000
    chunks = split_by_size(content, 100, 200, overlap=0)
    assert "".join(chunks) == content
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_page_subchunks_have_distinct_stable_graph_ids(sample_filing, sample_document):
    parsed = ParsedDocument(
        filing=sample_filing, document=sample_document,
        content="x" * 1000 + "\n---PAGE---\n" + "y" * 1000,
    )
    config = ChunkingConfig(max_item_bytes=100)
    chunks = chunk_document(parsed, config)
    ids = [chunk.graph_item_id for chunk in chunks]
    assert len(ids) == len(set(ids))
    assert ids == [chunk.graph_item_id for chunk in chunk_document(parsed, config)]
    assert all(len(chunk.content.encode("utf-8")) <= 100 for chunk in chunks)


def test_large_pages_honor_character_limit(sample_filing, sample_document):
    parsed = ParsedDocument(
        filing=sample_filing, document=sample_document,
        content="x" * 20000 + "\n---PAGE---\nlast",
    )
    assert all(len(c.content) <= 8000 for c in chunk_document(parsed, ChunkingConfig()))


@pytest.mark.parametrize("values", [
    {"target_size": 0}, {"max_item_bytes": 30 * 1024 * 1024 + 1},
    {"target_size": 9000, "max_size": 8000}, {"overlap": 4000},
])
def test_invalid_chunk_settings_rejected(values):
    with pytest.raises(ValueError):
        ChunkingConfig(**values)


def test_ordinals_sections_and_report_context(sample_filing, sample_document):
    sample_filing.report_period_end = datetime(2025, 12, 31)
    content = (
        "## Financial position\n\n" + "Cash information. " * 500
        + "\n---PAGE---\nContinuation of the same section.\n\n"
        "## Liquidity\n\nAvailable funds."
    )
    parsed = ParsedDocument(filing=sample_filing, document=sample_document, content=content)
    chunks = chunk_document(parsed, ChunkingConfig())
    assert [chunk.chunk_ordinal for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk.section_title == "Financial position" for chunk in chunks[:-1])
    assert chunks[-1].section_title == "Liquidity"
    assert all("Report period: 2025-12-31" in chunk.content for chunk in chunks)
    assert all("Apple Inc. | 10-K" in chunk.content for chunk in chunks)
    assert all(len(chunk.content) <= 8000 for chunk in chunks)


def test_sections_without_page_markers_are_not_invented_pages(sample_filing, sample_document):
    parsed = ParsedDocument(
        filing=sample_filing, document=sample_document,
        content="## Assets\n\nCash.\n\n## Liabilities\n\nDebt.",
    )
    chunks = chunk_document(parsed, ChunkingConfig())
    assert [chunk.section_title for chunk in chunks] == ["Assets", "Liabilities"]
    assert all(chunk.page_number == 1 for chunk in chunks)
    assert all("Page" not in chunk.title for chunk in chunks)
    assert len({chunk.graph_item_id for chunk in chunks}) == 2


def test_tables_split_on_complete_rows_with_context():
    header = "| Metric | 2025 | 2024 |\n| --- | --- | --- |"
    rows = [f"| Synthetic revenue {index} (1) | {index + 100} | {index + 90} |" for index in range(30)]
    content = (
        "## Income statement\n\nAmounts in millions\n\n" + header + "\n"
        + "\n".join(rows) + "\n\n(1) Includes synthetic adjustments."
    )
    chunks = split_by_size(content, target_size=350, max_size=600, overlap=100)
    table_chunks = [chunk for chunk in chunks if header in chunk]
    assert len(table_chunks) > 1
    assert all("Amounts in millions" in chunk and "Income statement" in chunk for chunk in table_chunks)
    assert all("(1) Includes synthetic adjustments." in chunk for chunk in table_chunks)
    actual_rows = [line for chunk in table_chunks for line in chunk.splitlines() if line.startswith("| Synthetic")]
    assert actual_rows == rows
    assert all(len(chunk) <= 600 for chunk in chunks)


def test_mixed_prose_tables_and_small_pages_no_missing_rows(sample_filing, sample_document):
    header = "| Label | Year |\n| --- | --- |"
    rows = [f"| Unique row {index} | {index} |" for index in range(40)]
    content = (
        "Opening disclosure. " * 100 + "\n\n" + header + "\n" + "\n".join(rows)
        + "\n\nClosing disclosure.\n---PAGE---\nX\n---PAGE---\n## Final section\n\nDone."
    )
    parsed = ParsedDocument(filing=sample_filing, document=sample_document, content=content)
    config = ChunkingConfig(target_size=300, max_size=500, overlap=50)
    chunks = chunk_document(parsed, config)
    actual_rows = [
        line for chunk in chunks for line in chunk.content.splitlines() if line.startswith("| Unique")
    ]
    assert actual_rows == rows
    assert any("Closing disclosure." in chunk.content for chunk in chunks)
    assert any(chunk.content.endswith("X") for chunk in chunks)
    assert chunks[-1].section_title == "Final section"
    assert all(chunk.section_title is None for chunk in chunks[:-1])
    assert all(len(chunk.content) <= config.max_size for chunk in chunks)
    assert [chunk.chunk_ordinal for chunk in chunks] == list(range(1, len(chunks) + 1))


def test_oversized_unicode_row_has_lossless_bounded_fragments(sample_filing, sample_document, caplog):
    header = "| Metric | Value |\n| --- | --- |"
    row = "| Giant | " + "\U0001f600" * 300 + "END |"
    parsed = ParsedDocument(
        filing=sample_filing, document=sample_document, content=header + "\n" + row,
    )
    config = ChunkingConfig(target_size=100, max_size=150, overlap=0, max_item_bytes=128)
    chunks = chunk_document(parsed, config)
    assert all(len(chunk.content) <= 150 and len(chunk.content.encode("utf-8")) <= 128 for chunk in chunks)
    prefix = header + "\n[Table row fragment; concatenate in chunk order]\n"
    assert all(prefix in chunk.content for chunk in chunks)
    assert "".join(chunk.content.split(prefix, 1)[1] for chunk in chunks) == row
    assert "Indivisible table row" in caplog.text
    assert len({chunk.graph_item_id for chunk in chunks}) == len(chunks)


def test_byte_caps_also_preserve_complete_rows(sample_filing, sample_document):
    header = "| Label | Value |\n| --- | --- |"
    rows = [f"| Unicode {index} | {'€' * 10} |" for index in range(10)]
    parsed = ParsedDocument(
        filing=sample_filing, document=sample_document, content=header + "\n" + "\n".join(rows),
    )
    chunks = chunk_document(parsed, ChunkingConfig(max_item_bytes=150))
    assert all(header in chunk.content for chunk in chunks)
    assert [
        line for chunk in chunks for line in chunk.content.splitlines() if line.startswith("| Unicode")
    ] == rows
    assert all(len(chunk.content.encode("utf-8")) <= 150 for chunk in chunks)


@pytest.mark.parametrize("text", ["X" * 10000, "😀" * 10000], ids=["ascii", "unicode"])
def test_giant_tokens_terminate_without_content_loss(text):
    chunks = split_by_size(text, target_size=50, max_size=100, overlap=0)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_indivisible_header_fallback_preserves_every_character(sample_filing, sample_document, caplog):
    text = "| " + "€" * 100 + " |\n| --- |\n| complete data |"
    parsed = ParsedDocument(filing=sample_filing, document=sample_document, content=text)
    chunks = chunk_document(
        parsed, ChunkingConfig(target_size=1, max_size=1, overlap=0, max_item_bytes=4),
    )
    assert "".join(chunk.content for chunk in chunks) == text
    assert all(len(chunk.content.encode("utf-8")) <= 4 for chunk in chunks)
    assert "Table header/context exceeds" in caplog.text


def test_minimal_byte_limit_does_not_reserve_unusable_context(sample_filing, sample_document):
    sample_filing.company_name = "A"
    parsed = ParsedDocument(filing=sample_filing, document=sample_document, content="😀😀")
    chunks = chunk_document(parsed, ChunkingConfig(max_item_bytes=4))
    assert [chunk.content for chunk in chunks] == ["😀", "😀"]
