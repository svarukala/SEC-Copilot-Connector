"""Generic raw-grid oracles; no issuer names, table indexes or answer fixtures."""

from collections import Counter
from datetime import datetime
import hashlib
import json

import pytest

from sec_connector.chunker import _split_content, chunk_document
from sec_connector.config import AppConfig, ChunkingConfig
from sec_connector.graph_client import GraphClient
from sec_connector.marker_tables import GLYPHS, render
from sec_connector.models import DocumentInfo, FilingMetadata, ParsedDocument
from sec_connector.parser import html_to_markdown, parse_document
from sec_connector.payloads import serialize_item


def matrix(headers=("North", "South", "West"), rows=None, *, right=False, spacer=False):
    rows = rows if rows is not None else [("Survey", ["\u2022", "", "\u2022"]), ("Review", ["", "", ""])]
    def cells(values, tag):
        return ("<td></td>" if spacer else "").join(f"<{tag}>{v}</{tag}>" for v in values)
    fields = [*headers, "Activity"] if right else ["Activity", *headers]
    body = "".join("<tr>" + cells([*values, label] if right else [label, *values], "td") + "</tr>"
                   for label, values in rows)
    return "<table><tr>" + cells(fields, "th") + "</tr>" + body + "</table>"


def parse(source):
    markers, notes = {}, {}
    content = html_to_markdown(source, marker_tables=markers, table_notes=notes)
    return ParsedDocument(
        filing=FilingMetadata(cik="0000000001", accession_number="0000000001-25-000001",
                              form="DEF 14A", company_name="Synthetic", ticker="SYN",
                              filing_date=datetime(2025, 3, 12), report_period_end=datetime(2025, 5, 1)),
        document=DocumentInfo(sequence=2, filename="synthetic.htm", document_type="DEF 14A"),
        content=content, marker_tables=markers, table_notes=notes,
    )


def derived(parsed, config=None):
    return [c for c in chunk_document(parsed, config or ChunkingConfig())
            if "[Derived marker-table evidence;" in c.content]


@pytest.mark.parametrize("right,spacer", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("glyph", sorted(GLYPHS))
def test_exact_raw_grid_mapping_and_blanks(right, spacer, glyph):
    headers = ["Assembly", "Safety", "Robotics"]
    raw = [("Team Indigo", [glyph, "", glyph]), ("Team Amber", ["", "", ""])]
    source = matrix(headers, raw, right=right, spacer=spacer)
    parsed = parse(source)
    rows = next(iter(parsed.marker_tables.values()))
    assert [r.labels for r in rows] == [[label] for label, _ in raw]
    for row, (_, values) in zip(rows, raw):
        assert [c.header for c in row.cells] == [[h] for h in headers]
        assert [c.marker for c in row.cells] == values
        assert [c.column for c in row.cells] == [
            (i + (0 if right else 1)) * (2 if spacer else 1) + 1 for i in range(3)
        ]
    assert parsed.content == html_to_markdown(source)
    assert "not false or no relationship" in derived(parsed)[0].content
    assert sum(c.content.count("blank; source cell:") for c in derived(parsed)) == 4


def test_reordering_and_renaming_axes_is_equivariant():
    original = [("Read", ["", "\u2713", ""]), ("Write", ["\u2713", "", "\u2713"])]
    for perm in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
        headers = ["Interface " + str(i) for i in perm]
        raw = [("Permission " + name, [values[i] for i in perm]) for name, values in reversed(original)]
        rows = next(iter(parse(matrix(headers, raw)).marker_tables.values()))
        assert [(r.labels[0], [(c.header[0], c.marker) for c in r.cells]) for r in rows] == [
            (label, list(zip(headers, values))) for label, values in raw
        ]


def test_hierarchical_axes_rowspans_multilevel_headers_and_blank_column():
    source = (
        "<table><tr><th rowspan='2'>Group</th><th rowspan='2'>Skill</th>"
        "<th colspan='2'>East</th><th colspan='2'>West</th></tr>"
        "<tr><th>Basic</th><th>Advanced</th><th>Basic</th><th>Advanced</th></tr>"
        "<tr><td rowspan='2'>Planning</td><td>Forecast</td><td>\u2022</td><td></td><td></td><td></td></tr>"
        "<tr><td>Budget</td><td></td><td>\u2022</td><td>\u2022</td><td></td></tr></table>"
    )
    parsed = parse(source)
    rows = next(iter(parsed.marker_tables.values()))
    assert [r.labels for r in rows] == [["Planning", "Forecast"], ["Planning", "Budget"]]
    assert rows[0].label_headers == [["Group"], ["Skill"]]
    assert [c.header for c in rows[0].cells] == [
        ["East", "Basic"], ["East", "Advanced"], ["West", "Basic"], ["West", "Advanced"],
    ]
    assert [r.row for r in rows] == [3, 4]
    assert all(row.cells[-1].marker == "" for row in rows)


@pytest.mark.parametrize("source", [
    matrix(("Same", "Same", "Other")),
    matrix(("", "Second", "Third")),
    matrix(rows=[("Same", ["\u2022", "", ""]), ("Same", ["", "\u2022", ""])]),
    matrix().replace("<td>Survey</td>", "<td></td>"),
    matrix().replace("<td>\u2022</td>", "<td>0</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>-</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>*</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>[*]</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>(1)</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>\u2713</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>\u2022*</td>", 1),
    matrix().replace("<td>\u2022</td>", "<td>X</td>", 1),
    matrix().replace("<td>\u2022</td>", "", 1),
    matrix().replace("<td>\u2022</td>", "<td rowspan='2'>\u2022</td>", 1),
    matrix().replace("<td>\u2022</td><td></td>", "<td colspan='2'>\u2022</td>", 1),
    matrix().replace("<td>Survey</td>", "<td colspan='wrong'>Survey</td>"),
    matrix().replace("<td>Survey</td>", "<td colspan='0'>Survey</td>"),
    matrix().replace("<td>Survey</td>", "<td>Survey | other</td>"),
    matrix().replace("<th>North</th>", "<th>&lt;region&gt;</th>"),
    matrix().replace("<th>North</th>", "<th><img alt='Region' src='offline.png'></th>"),
    matrix().replace("<td></td>", "<td><img alt='' src='offline.png'></td>", 1),
    matrix().replace("<table>", "<table role='presentation'>"),
    "<table><tr><td>" + matrix() + "</td></tr></table>",
    matrix(rows=[("Survey", ["", "", ""]), ("Review", ["", "", ""])]),
    "<table><tr><td>\u2022</td><td>First statement</td></tr>"
    "<tr><td>\u2022</td><td>Second statement</td></tr></table>",
])
def test_ambiguous_or_non_matrix_sources_are_not_expanded(source):
    parsed = parse(source)
    assert not parsed.marker_tables
    assert not derived(parsed)
    assert parsed.content == html_to_markdown(source)


def test_collapsed_spans_do_not_hide_ambiguous_cells():
    source = ("<table><tr><th>Activity</th><th colspan='2'>North</th><th>South</th></tr>"
              "<tr><td>Work</td><td colspan='2'>\u2022</td><td>\u2022</td></tr></table>")
    assert not parse(source).marker_tables


def test_header_span_cannot_become_body_row_group():
    source = (
        "<table><tr><th rowspan='3'>Group</th><th>Task</th><th>East</th><th>West</th></tr>"
        "<tr><td>First</td><td>\u2022</td><td></td></tr>"
        "<tr><td>Second</td><td></td><td>\u2022</td></tr></table>"
    )
    assert not parse(source).marker_tables


def test_repeated_tables_no_metadata_reuse_or_context_leak():
    parsed = parse("<h2>One</h2>" + matrix() + "<PAGE><h2>Two</h2>" + matrix())
    assert not parsed.marker_tables and not derived(parsed)


def test_mixed_semantic_middle_or_trailing_columns_not_reinterpreted_as_stubs():
    for values in (["\u2022", "Sometimes", "\u2022"], ["\u2022", "\u2022", "Sometimes"]):
        assert not parse(matrix(rows=[("Skill", values)])).marker_tables


def test_bounded_expansion_and_no_partial_evidence(caplog):
    assert not parse(matrix(tuple(f"Column {i}" for i in range(33)),
                            [("Row", ["\u2022"] * 33)])).marker_tables
    assert not parse(matrix(tuple(f"Column {i}" for i in range(17)),
                            [(f"Row {i}", ["\u2022"] * 17) for i in range(16)])).marker_tables
    parsed = parse(matrix())
    assert not derived(parsed, ChunkingConfig(target_size=100, max_size=200, overlap=0))
    assert "exceed chunk budget" in caplog.text
    assert not render(next(iter(parsed.marker_tables)), next(iter(parsed.marker_tables.values())),
                      "Context " * 10000, [], 8000, 32000)


def test_document_bound_and_table_expansion_byte_cap(caplog):
    parsed = parse("".join(matrix(rows=[(f"Work {i}", ["\u2022", "", ""])]) for i in range(40)))
    assert len(parsed.marker_tables) == 32
    large = "".join(
        matrix(tuple(f"Field {c}" for c in range(16)),
               [(f"Group {t} task {r}", ["\u2022"] * 16) for r in range(16)])
        for t in range(9)
    )
    bounded = parse(large)
    assert len(bounded.marker_tables) == 8
    assert sum(len(row.cells) for rows in bounded.marker_tables.values() for row in rows) == 2048
    parsed = parse(matrix(tuple("Field " + str(i) for i in range(16)),
                          [(f"Work {i}", ["\u2022"] * 16) for i in range(16)]))
    rows = next(iter(parsed.marker_tables.values()))
    for row in rows:
        row.labels[0] += "(a)"
    assert not render(next(iter(parsed.marker_tables)), rows, "",
                      [("(a)", "(a) " + "Long applicable qualification. " * 100)], 4200, 16000)
    assert "bounded table expansion" in caplog.text


def test_notes_scope_full_text_and_header_qualifiers_travel_with_each_association():
    source = ("<h2>Service coverage</h2><p>Recycled products were supplied only within this scope.</p>"
              + matrix(("Warehouse(a)", "Retail", "Online"), [
                  ("Recycled products(3)", ["\u2022", "", ""]),
                  ("Other supplies", ["", "\u2022", ""]),
              ])
              + "<PAGE><p>(3) " + "Full scope qualification. " * 10 + "END.</p>"
              "<p>(a) Warehouse basis only.</p><p>(z) Unrelated definition.</p>")
    parsed = parse(source)
    chunks = derived(parsed, ChunkingConfig(target_size=900, max_size=1200, overlap=0))
    assert chunks
    for chunk in chunks:
        assert chunk.page_number == 1 and chunk.section_title == "Service coverage"
        assert "Unrelated definition." not in chunk.content
        if 'Row path: ["Recycled products(3)"]' in chunk.content:
            assert "Full scope qualification. " * 10 + "END." in chunk.content
            assert "Recycled products were supplied only within this scope." in chunk.content
        else:
            assert "Full scope qualification." not in chunk.content
        if 'header path: ["Warehouse(a)"]' in chunk.content:
            assert "Warehouse basis only." in chunk.content
    entries = [line for c in chunks for line in c.content.splitlines() if line.startswith("Column ")]
    assert len(entries) == 6


def test_unresolved_or_ambiguous_notes_prevent_derived_claims(caplog):
    source = matrix(rows=[("Tools(a)", ["\u2022", "", ""])])
    for suffix in ("", "<p>(a) First basis.</p><p>(a) Conflicting basis.</p>"):
        assert not derived(parse(source + suffix))
    assert "unresolved source note" in caplog.text


def test_capture_serialization_hash_binding_and_exact_payload_attribution(tmp_path):
    source = "<h2>Facilities</h2>" + matrix(spacer=True)
    path = tmp_path / "synthetic.htm"
    path.write_text(source, encoding="utf-8")
    original = parse(source)
    parsed = parse_document(path, original.filing, original.document)
    assert parsed.marker_tables == original.marker_tables
    restored = ParsedDocument.model_validate_json(parsed.model_dump_json())
    config = ChunkingConfig(target_size=700, max_size=1000, overlap=0, max_item_bytes=4000)
    chunks = chunk_document(restored, config)
    assert chunks == chunk_document(parsed, config)
    original_rows = Counter(line for line in parsed.content.splitlines() if line.startswith("|"))
    emitted_rows = Counter(line for c in chunks for line in c.content.splitlines() if line.startswith("|"))
    assert all(emitted_rows[row] == count for row, count in original_rows.items() if "---" not in row)
    graph = GraphClient(AppConfig())
    payloads = [graph.build_payload(c) for c in chunks]
    assert len(set(p["id"] for p in payloads)) == len(payloads)
    for p in payloads:
        assert len(serialize_item(p)) <= config.max_item_bytes
        assert len(p["content"]["value"]) <= config.max_size
        assert p["properties"]["Page"] == 1
        assert p["properties"]["Sequence"] == 2
        assert p["properties"]["SectionTitle"] == "Facilities"
        assert p["properties"]["Url"] == parsed.filing.document_url("synthetic.htm")
        assert "ReportPeriodEnd" not in p["properties"]
        assert "marker_tables" not in json.dumps(p)
    changed = parsed.content.replace("Survey", "Different")
    assert _split_content(changed, 4000, 8000, 0, 32000, marker_tables=parsed.marker_tables) == [changed]
    assert all(len(key) == len(hashlib.sha256().hexdigest()) for key in parsed.marker_tables)


def test_utf8_association_budgets_never_fragment():
    parsed = parse(matrix(("R\u00e9gion", "\u6771", "\u897f")))
    key, rows = next(iter(parsed.marker_tables.items()))
    pieces = render(key, rows, "", [], 900, 790)
    assert pieces and all(len(p.encode("utf-8")) <= 790 for p in pieces)
    assert sum(p.count("Column ") for p in pieces) == 6
    assert all("Row path:" in p and "source table SHA256" in p for p in pieces)


def test_optional_module_is_in_diagnostics_and_maintenance_provenance():
    from pathlib import Path
    from sec_connector import diagnostics, maintenance, marker_tables

    path = Path(marker_tables.__file__)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    config = AppConfig()
    config.azure.tenant_id = "offline-synthetic"
    assert maintenance.provenance(config)["modules"]["marker_tables"] == expected
    schema = {"baseType": "microsoft.graph.externalItem",
              "properties": [{"name": "Title", "type": "string"}]}
    assert diagnostics.runtime_info(path.parent, schema)["code_sha256"]["marker_tables.py"] == expected
