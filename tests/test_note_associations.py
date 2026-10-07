"""Source-local ownership controls; no issuer names or answers in runtime logic."""

import hashlib

import pytest

from sec_connector.chunker import _split_content, chunk_document
from sec_connector.config import ChunkingConfig
from sec_connector.models import ParsedDocument
from sec_connector.note_associations import collect_table_notes, linked_marker
from sec_connector.parser import html_to_markdown
from tests.test_evidence_coverage_gaps import process


def table(label="Product", marker="(a)", count=28):
    return ("<table><tr><th>Metric</th><th>2024</th></tr>"
            + "".join(f"<tr><td>{label} {i} {marker}</td><td>120</td></tr>" for i in range(count))
            + "</table>")


def note(marker="(a)", body="Net of obsolete inventory."):
    return f"<table><tr><td>{marker}</td><td>{body}</td></tr></table>"


@pytest.mark.parametrize("marker", ["*", "**", "***", "\u2020", "\u2021", "[*]", "(a)", "(1)"])
def test_source_note_layout_and_exact_symbols(tmp_path, marker):
    parsed, chunks, _ = process(tmp_path, table(marker=marker) + note(marker))
    assert any(parsed.table_notes.values())
    assert all("Net of obsolete inventory." in c.content for c in chunks if "| Product" in c.content)


def test_single_double_star_and_unmarked_rows_remain_distinct(tmp_path):
    source = (table("Single", "*") + note("*", "First adjustment.") + note("**", "Second adjustment.")
              + table("Double", "**") + note("*", "Not this table.") + note("**", "Different basis.")
              + table("Plain", "") + note("*", "Unrelated."))
    _, chunks, _ = process(tmp_path, source)
    for chunk in chunks:
        if "| Single" in chunk.content:
            assert "First adjustment." in chunk.content
            assert "Second adjustment." not in chunk.content
        if "| Double" in chunk.content:
            assert "Different basis." in chunk.content
            assert "Not this table." not in chunk.content
        if "| Plain" in chunk.content:
            assert "Unrelated." not in chunk.content


@pytest.mark.parametrize("cell", ["**Bold**", "*Italic*", "2 * 3", r"2 \* 3", "(1)", "(1,234)", "[-1]"])
def test_formatting_arithmetic_and_negative_numbers_are_not_references(cell):
    assert not linked_marker("*", cell)
    assert not linked_marker("**", cell)
    assert not linked_marker("(1)", cell)


@pytest.mark.parametrize("separator", [
    "<h2>Other disclosure</h2>",
    "<PAGE><h2>New section</h2>",
    "<PAGE><PAGE>",
    "<p>" + "Unrelated sentence. " * 60 + "</p>",
    table("Unrelated", ""),
])
def test_ownership_stops_at_unrelated_sections_tables_and_distance(tmp_path, separator):
    _, chunks, _ = process(tmp_path, table() + separator + note())
    assert all("Net of obsolete inventory." not in c.content for c in chunks if "| Product" in c.content)


def test_repeated_page_furniture_can_continue_only_its_own_section(tmp_path):
    footer = lambda n: f"<table><tr><td>Annual statement</td><td>{n}</td></tr></table>"
    heading = "<h2>Manufacturing</h2>"
    source = (heading + "<p>Introductory disclosure.</p>" + footer(1) + "<PAGE>"
              + heading + table() + footer(2) + "<PAGE>" + heading + note()
              + "<h2>New section</h2>" + table("Other") + note(body="Different qualification."))
    _, chunks, _ = process(tmp_path, source)
    relevant = [c for c in chunks if "| Product" in c.content]
    assert relevant and all("Net of obsolete inventory." in c.content for c in relevant)
    assert all(c.page_number == 2 and c.section_title == "Manufacturing" for c in relevant)
    assert all("Different qualification." not in c.content for c in relevant)
    assert all("Net of obsolete inventory." not in c.content for c in chunks if "| Other" in c.content)
    assert any(c.page_number == 3 and "Net of obsolete inventory." in c.content for c in chunks)


def test_one_off_page_number_table_is_not_assumed_furniture(tmp_path):
    _, chunks, _ = process(
        tmp_path, table() + "<table><tr><td>Units</td><td>25</td></tr></table><PAGE>" + note(),
    )
    assert all("Net of obsolete inventory." not in c.content for c in chunks if "| Product" in c.content)


def test_footer_lookalike_away_from_page_end_remains_an_ownership_barrier(tmp_path):
    footer = lambda n: f"<table><tr><td>Statement</td><td>{n}</td></tr></table>"
    _, chunks, _ = process(
        tmp_path, footer(1) + "<PAGE>" + footer(2) + "<PAGE>" + table() + footer(3) + note(),
    )
    assert all("Net of obsolete inventory." not in c.content for c in chunks if "| Product" in c.content)


def test_duplicate_markers_and_identical_table_occurrences_fail_closed(tmp_path, caplog):
    _, chunks, _ = process(tmp_path, table() + note() + "<p>Additional narrative.</p>" + note(body="Conflicting."))
    assert "Duplicate table note markers" in caplog.text
    assert all("Net of obsolete inventory." not in c.content for c in chunks if "| Product" in c.content)
    parsed, chunks, _ = process(tmp_path, table() + note() + "<PAGE>" + table() + note(body="Different."))
    assert not any(parsed.table_notes.values())
    assert all("Net of obsolete inventory." not in c.content and "Different." not in c.content
               for c in chunks if "| Product" in c.content)


def test_short_marked_row_gets_cross_page_note_even_without_size_split(tmp_path):
    _, chunks, _ = process(tmp_path, table(count=1) + "<PAGE>" + note())
    relevant = [c for c in chunks if "| Product" in c.content]
    assert len(relevant) == 1 and relevant[0].page_number == 1
    assert "Net of obsolete inventory." in relevant[0].content


def test_scope_requires_unique_exact_marked_label_not_generic_nearby_prose(tmp_path):
    scope = "We supplied recycled products during 2024 to local manufacturers."
    source = ("<table><tr><td>&#8226;</td><td>" + scope + "</td></tr></table>"
              + "<table><tr><th>Activity</th><th>Amount</th></tr>"
              + "<tr><td>Recycled products(3)</td><td>12</td></tr></table><PAGE>"
              + note("(3)", "Excludes returns."))
    _, chunks, _ = process(tmp_path, source)
    assert all(scope in c.content and "Excludes returns." in c.content
               for c in chunks if "| Recycled products" in c.content)
    _, chunks, _ = process(tmp_path, source.replace("Recycled products(3)", "Other products(3)"))
    assert all(scope not in c.content for c in chunks if "| Other products" in c.content)


def test_sidecar_is_source_bound_serializable_and_absent_from_payloads(tmp_path):
    parsed, chunks, payloads = process(tmp_path, table() + "<PAGE>" + note())
    restored = ParsedDocument.model_validate_json(parsed.model_dump_json())
    assert restored.table_notes == parsed.table_notes
    assert all("table_notes" not in str(p) for p in payloads)
    original = html_to_markdown(table() + "<PAGE>" + note())
    assert original == parsed.content
    changed = original.replace("Product", "Changed")
    no_sidecar = _split_content(changed, 350, 800, 0, 10000)
    assert _split_content(changed, 350, 800, 0, 10000, table_notes=parsed.table_notes) == no_sidecar
    assert chunks == chunk_document(restored, ChunkingConfig(target_size=350, max_size=800, overlap=0))


def test_large_qualifier_remains_ordered_and_reports_budget_limit(tmp_path, caplog):
    _, chunks, _ = process(tmp_path, table() + "<PAGE><p>(a) " + "Long qualification. " * 80 + "END.</p>")
    assert "exceed row context budget" in caplog.text
    assert any("END." in c.content for c in chunks)


def test_associated_qualifier_consumes_utf8_budget():
    source = html_to_markdown(table(count=20) + "<PAGE>" + note(body="Amounts in euros \u20ac\u20ac\u20ac."))
    associations = collect_table_notes(source)
    page = source.split("---PAGE---")[0]
    pieces = _split_content(page, 140, 250, 0, 230, table_notes=associations)
    assert all(len(p.encode()) <= 230 and len(p) <= 250 for p in pieces)
    assert all("Amounts in euros" in p for p in pieces if "| Product" in p)
    assert any(associations.values())
    assert all(len(key) == len(hashlib.sha256().hexdigest()) for key in associations)


def test_search_window_exhaustion_is_explicit_and_fails_closed(caplog):
    source = html_to_markdown(table() + note() + note("(z)", "Disclosure " * 2000))
    associations = collect_table_notes(source)
    assert not any(associations.values())
    assert "bounded source window" in caplog.text


def test_unspaced_alphabetic_definition_and_grouped_markers(tmp_path):
    _, chunks, _ = process(
        tmp_path, table(marker="(a, b)") + "<p>(a)First basis.</p><p>(b)Second basis.</p>",
    )
    assert all("First basis." in c.content and "Second basis." in c.content
               for c in chunks if "| Product" in c.content)


@pytest.mark.parametrize("caption", [
    "Amounts in euros; continuing operations only.",
    "Unaudited; excluding discontinued operations.",
    "Dollars per share, except ratios.",
])
@pytest.mark.parametrize("count", [2, 28])
def test_bound_notes_preserve_adjacent_financial_caption(tmp_path, caption, count):
    _, chunks, _ = process(tmp_path, f"<p>{caption}</p>" + table(count=count) + note())
    rows = [c for c in chunks if "| Product" in c.content]
    assert rows and all(caption in c.content for c in rows)
    assert all("Net of obsolete inventory." in c.content for c in rows)


@pytest.mark.parametrize("marker", ["*", "**", "***", "\u2020", "\u2021"])
@pytest.mark.parametrize("bracketed", [True, False])
def test_bracketed_and_bare_symbol_definitions_are_distinct(tmp_path, marker, bracketed):
    own, other = (f"[{marker}]", marker) if bracketed else (marker, f"[{marker}]")
    _, chunks, _ = process(
        tmp_path, table(marker=own, count=20)
        + note(other, "Other marker basis.") + note(own, "Applicable basis."),
    )
    rows = [c for c in chunks if "| Product" in c.content]
    assert rows and all("Applicable basis." in c.content for c in rows)
    assert all("Other marker basis." not in c.content for c in rows)


@pytest.mark.parametrize("first,second", [
    ("(a)", "(b)"), ("[a]", "[b]"), ("*", "**"), ("\u2020", "\u2021"), ("[*]", "*"),
])
def test_line_separated_definitions_do_not_transfer_other_basis(tmp_path, first, second):
    _, chunks, _ = process(
        tmp_path, table(marker=first, count=20)
        + f"<p>{first} Applicable basis.<br>{second} Other products only.</p>",
    )
    rows = [c for c in chunks if "| Product" in c.content]
    assert rows and all("Applicable basis." in c.content for c in rows)
    assert all("Other products only." not in c.content for c in rows)
    assert any("Other products only." in c.content for c in chunks)


def test_line_wrapped_note_keeps_continuation_and_rejects_duplicate_definitions(tmp_path, caplog):
    source = table(count=40) + "<p>(a) Applicable basis.<br>Excludes obsolete inventory.<br>(b) Other basis.</p>"
    _, chunks, _ = process(tmp_path, source)
    rows = [c for c in chunks if "| Product" in c.content]
    assert rows and all("Excludes obsolete inventory." in c.content for c in rows)
    assert all("Other basis." not in c.content for c in rows)
    _, chunks, _ = process(tmp_path, source.replace("(b)", "(a)"))
    assert "Duplicate table note markers" in caplog.text
    assert all("Applicable basis." not in c.content for c in chunks if "| Product" in c.content)
