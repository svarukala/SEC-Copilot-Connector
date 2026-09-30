"""Source-preserving table qualifier repetition, without new parser inference."""

import re

import pytest

from sec_connector.chunker import _split_content, _table_header_count, _table_notes
from sec_connector.chunker import chunk_document
from sec_connector.config import ChunkingConfig
from sec_connector.models import DocumentInfo, FilingMetadata, ParsedDocument
from datetime import datetime
from tests.corpus_replay import subsequence, tokens
from tests.table_context_audit import data_row_counts, linked_notes


def split(text, maximum=700, byte_limit=10000):
    chunks = _split_content(text, maximum // 2, maximum, 0, byte_limit)
    assert all(len(c) <= maximum and len(c.encode()) <= byte_limit for c in chunks)
    assert subsequence(tokens(text), tokens("\n".join(chunks)))["ok"]
    return chunks


def test_period_body_rows_repeat_without_flattening_or_reordering_cells():
    head = "| Summary | | | | |\n| --- | --- | --- | --- | --- |"
    groups = "| | Quarter ended | [merged with column 2] | Six months ended | [merged with column 4] |"
    periods = "| Dollars in millions, except per share | 2025 | 2024 | 2025 | 2024 |"
    rows = [f"| Revenue {i} | 1,100 | 1,100 | 2,200 | 2,200 |" for i in range(30)]
    text = "\n".join([head, groups, periods, *rows])
    chunks = split(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert head + "\n" + groups + "\n" + periods in chunk
    assert [line for c in chunks for line in c.splitlines() if line.startswith("| Revenue")] == rows


@pytest.mark.parametrize("band", [
    ["| As of or for the year ended December 31, | | |",
     "| (in millions, except ratio data) | 2025 | 2024 |"],
    ["| | Due to Change in (1) | Net Change |", "| | Volume | Rate |",
     "| Dollars in millions | From 2024 to 2025 | From 2023 to 2024 |"],
    ["| In millions | Remainder of 2025 | Thereafter |"],
    ["| As of or for the period ended (in millions) | 3Q24 | 2Q24 |"],
    ["| December 31, 2025 In millions | 2025 | Revolving loans |"],
    ["| | Three months ended | Six months ended |", "| | June 30 | June 30 |",
     "| In millions | 2025 | 2024 |"],
    ["| Year ended December 31 In millions | 2025 | 2024 |"],
    ["| December 31, (in millions, except ratios) | 2025 | 2024 |"],
    ["| | Contractual rate in effect at December 31, 2025 | Issue date |",
     "| | 2025 | 2024 |"],
    ["| By remaining maturity at December 31, (in millions) | 2025 | 2024 |",
     "| By remaining maturity at December 31, (in millions) | Under 1 year | 1-5 years |"],
    ["| | Outstandings | Accruing Past Due 90 Days or More |",
     "| Dollars in millions | 2025 | 2024 |"],
    ["| Three Months Ended September 30 (Dollars in Millions) | 2025 | 2024 |"],
    ["| | Commercial Utilized (1) | Commercial Unfunded (2, 3, 4) |",
     "| Dollars in millions | 2025 | 2024 |"],
])
def test_source_backed_multilevel_header_bands(band):
    rows = ["| Summary | | |", "| --- | --- | --- |", *band, "| Revenue | 1,200 | 1,100 |"]
    assert _table_header_count(rows) == 2 + len(band)


def test_provisional_labels_without_later_period_or_units_are_not_headers():
    rows = ["| Summary | | |", "| --- | --- | --- |",
            "| | Some labels | Other labels |", "| Income | 1,200 | 1,100 |"]
    assert _table_header_count(rows) == 2


@pytest.mark.parametrize("row", [
    "| Revenue | 2025 | 2024 |",
    "| Acquired in 2025 | 1,234 | 1,234 |",
    "| December 31, 2025 | 100 | 200 |",
    "| Year | 2025 | 2024 |",  # Ambiguous date-as-data series, not a period header.
    "| | 1,234 | 1,234 |",
    "| 2025 | 2024 | 2023 |",
])
def test_first_data_row_is_not_promoted(row):
    assert _table_header_count(["| Metric | Value | Value |", "| --- | --- | --- |", row]) == 2


def test_units_schema_and_long_unit_stub_repeat_exactly():
    head = "| Shareholders' equity | | |\n| --- | --- | --- |"
    schema = "| In millions | Common stock | Retained earnings |"
    rows = [f"| Balance {i} (a) | 1,200 | 2,400 |" for i in range(40)]
    note = "(a) Excludes noncontrolling interests."
    text = "\n".join([head, schema, *rows]) + "\n\n" + note
    chunks = split(text)
    table_chunks = [c for c in chunks if head in c]
    assert all(schema in c and note in c for c in table_chunks)
    assert note in chunks[-1]


@pytest.mark.parametrize("marker", ["(a)", "(1)", "[b]", "[2]"])
def test_only_linked_notes_follow_qualifying_rows(marker):
    head = "| Metric | 2025 |\n| --- | --- |"
    rows = [f"| Marked {i} {marker} | 1,234 |" for i in range(20)]
    rows += [f"| Unmarked {i} | 2,345 |" for i in range(20)]
    note = marker + " Net of allowances."
    text = head + "\n" + "\n".join(rows) + "\n\n" + note + "\n\n(z) Unrelated note."
    chunks = split(text)
    for chunk in chunks:
        if "| Marked" in chunk:
            assert note in chunk
            assert chunk.index(note) > chunk.index("| Marked")
        if "| Unmarked" in chunk and "| Marked" not in chunk:
            assert note not in chunk
        if head in chunk:
            assert "(z) Unrelated note." not in chunk
    assert "(z) Unrelated note." in chunks[-1]


def test_negative_values_and_bold_prose_do_not_link_notes():
    table = "| Net loss | 2025 |\n| --- | --- |\n| Income | (1) |"
    assert _table_notes("(1) Unrelated number.", table) == []
    assert _table_notes("**Other information**", table + "\n| **Bold** | 2 |") == []
    assert _table_notes("(1) A definition.", "| Gain (1,234) | 1,000 |") == []


def test_grouped_source_note_markers_keep_each_definition():
    head = "| Metric | 2025 |\n| --- | --- |"
    rows = "\n".join(f"| Marked {i} (1, 2, 3) | 1,234 |" for i in range(40))
    notes = "(1) First qualification.\n\n(2) Second qualification.\n\n(3) Third qualification."
    chunks = split(head + "\n" + rows + "\n\n" + notes)
    assert all(notes in c for c in chunks if "| Marked" in c)


@pytest.mark.parametrize("marker", ["(1)", "[1]"])
def test_numeric_marker_in_header_applies_to_every_row(marker):
    head = f"| Metric | 2025 {marker} |\n| --- | --- |"
    rows = [f"| Balance {i} | 1,234 |" for i in range(30)]
    note = marker + " Revised measurement basis."
    chunks = split(head + "\n" + "\n".join(rows) + "\n\n" + note)
    assert all(note in c for c in chunks if "| Balance" in c)


def test_long_qualifier_is_not_truncated_or_silently_lost(caplog):
    head = "| Metric | 2025 |\n| --- | --- |"
    rows = [f"| Balance {i} (a) | 1,234 |" for i in range(20)]
    note = "(a) " + "Exception to the measurement basis. " * 30 + "END."
    chunks = split(head + "\n" + "\n".join(rows) + "\n\n" + note, maximum=450)
    assert "Linked table notes (a) exceed" in caplog.text
    assert "END." in chunks[-1]
    assert all(row in "\n".join(chunks) for row in rows)


def test_repeated_qualifiers_consume_byte_and_character_budget():
    head = "| Metric | 2025 |\n| --- | --- |"
    rows = [f"| Balance {i} (a) | " + "\u20ac" * 15 + " |" for i in range(30)]
    text = head + "\n" + "\n".join(rows) + "\n\n(a) Units in euros."
    chunks = split(text, maximum=500, byte_limit=280)
    assert all("(a) Units in euros." in c for c in chunks if "| Balance" in c)


def test_adjacent_note_after_unrelated_prose_is_not_assumed_linked():
    assert _table_notes("Different discussion.\n\n(a) Other definition.", "| Balance (a) |") == []


def test_duplicate_note_definitions_are_not_assumed_unambiguous(caplog):
    assert _table_notes("(a) Definition one.\n\n(a) Definition two.", "| Balance (a) |") == []
    assert "Duplicate table note markers" in caplog.text


def test_preceding_table_note_is_not_rebound_to_next_table():
    head = "| Metric | 2025 |\n| --- | --- |"
    first = head + "\n| Old (a) | 1,000 |"
    second = head + "\n" + "\n".join(f"| New {i} (a) | 2,000 |" for i in range(40))
    text = first + "\n\n(a) Applies to old table.\n\n" + second
    chunks = split(text)
    assert all("Applies to old table" not in c for c in chunks if "| New " in c)


def test_source_header_rows_are_not_repeated_as_data_observations():
    # Exact original data ordering is stronger than subsequence coverage when
    # context is repeated: omission cannot be hidden by a repeated year/header.
    head = "| Summary | | |\n| --- | --- | --- |"
    years = "| In millions | 2025 | 2024 |"
    rows = [f"| Balance {i} | 2,025 | 2,024 |" for i in range(30)]
    chunks = split(head + "\n" + years + "\n" + "\n".join(rows))
    data = [line for c in chunks for line in c.splitlines() if re.match(r"\| Balance \d", line)]
    assert data == rows


def test_context_does_not_cross_page_or_section_boundaries():
    head = "| Metric | 2025 |\n| --- | --- |"
    rows = "\n".join(f"| Balance {i} (a) | 1,234 |" for i in range(40))
    content = (
        "## First\n\n" + head + "\n" + rows + "\n---PAGE---\n"
        "(a) Ambiguous next-page definition.\n\n## Next\n\n" + head + "\n" + rows
    )
    parsed = ParsedDocument(
        filing=FilingMetadata(cik="0000000001", ticker="SYN", accession_number="0000000001-26-000001",
                              form="10-K", filing_date=datetime(2026, 1, 1), company_name="Synthetic"),
        document=DocumentInfo(sequence=1, filename="annual.htm", document_type="10-K"),
        content=content,
    )
    chunks = chunk_document(parsed, ChunkingConfig(target_size=300, max_size=600, overlap=0))
    assert all("Ambiguous next-page" not in c.content for c in chunks if c.page_number == 1)
    assert all("Ambiguous next-page" not in c.content for c in chunks if c.section_title == "Next")


def test_occurrence_audit_rejects_loss_even_when_row_text_exists_elsewhere():
    head = "| Metric | 2025 |\n| --- | --- |"
    row = "| Same label | 1,234 |"
    source = head + "\n" + row + "\n" + row
    payloads = [{"content": {"value": head + "\n" + row}}]
    assert data_row_counts(source, payloads)["missing_occurrences"] == {row: 1}


def test_audit_allows_only_leading_context_repetition():
    head = "| Summary | |\n| --- | --- |"
    period = "| In millions | 2025 |"
    a, b = "| Alpha | 1,200 |", "| Beta | 2,400 |"
    source = "\n".join([head, period, a, b])
    payloads = [{"content": {"value": "\n".join([head, period, row])}} for row in (a, b)]
    result = data_row_counts(source, payloads)
    assert not result["missing_occurrences"] and not result["unexplained_extra_occurrences"]
    payloads[-1]["content"]["value"] += "\n" + b
    assert data_row_counts(source, payloads)["unexplained_extra_occurrences"] == {b: 1}


def test_linked_audit_distinguishes_unmarked_rows_and_missing_notes():
    head = "| Metric | 2025 |\n| --- | --- |"
    source = head + "\n| Marked (a) | 1,000 |\n| Unmarked | 2,000 |\n\n(a) Relevant."
    result = linked_notes(source, [{"content": {"value": head + "\n| Marked (a) | 1,000 |"}}])
    assert len(result) == 1 and set(result.values()) == {False}
