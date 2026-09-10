"""Offline synthetic financial goldens, not reproductions of issuer filings."""

from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from sec_connector.chunker import chunk_document
from sec_connector.config import ChunkingConfig
from sec_connector.models import DocumentInfo, FilingMetadata, ParsedDocument
from sec_connector.parser import SECMarkdownConverter, html_to_markdown, parse_document


@pytest.fixture
def filing():
    return FilingMetadata(
        cik="0000000123", accession_number="0000000123-26-000001",
        company_name="Synthetic Example Co.", ticker="SYN", form="10-K",
        filing_date=datetime(2026, 2, 1),
    )


@pytest.fixture
def document():
    return DocumentInfo(sequence=1, filename="annual.htm", document_type="10-K")


def test_exact_cells_and_no_standalone_cell_pipes():
    html = "<table><tr><th>Metric</th><th>2025</th></tr><tr><td>Revenue</td><td>125</td></tr></table>"
    assert html_to_markdown(html) == "| Metric | 2025 |\n| --- | --- |\n| Revenue | 125 |"
    assert SECMarkdownConverter().convert("<td>Value</td>") == "Value"
    assert SECMarkdownConverter().convert("<th>Year</th>") == "Year"


def test_financial_spacer_rows_do_not_consume_chunk_budget():
    md = html_to_markdown(
        '<table><tr><th>Metric</th><th>2026</th></tr>'
        '<tr><td>&nbsp;</td><td></td></tr>'
        '<tr><td>Assets</td><td>616,034</td></tr>'
        '<tr><td></td><td></td></tr></table>'
    )
    assert md == "| Metric | 2026 |\n| --- | --- |\n| Assets | 616,034 |"


def test_visual_columns_collapse_even_with_independent_empty_spacer_cells():
    spacer = "<tr>" + "<td></td>" * 46 + "</tr>"
    md = html_to_markdown(
        '<table><tr><th>Exhibit</th><th colspan="45">Description</th></tr>'
        + spacer
        + '<tr><td>10.1</td><td colspan="45">Synthetic employment agreement.</td></tr>'
        + spacer + "</table>"
    )
    assert md == (
        "| Exhibit | Description |\n| --- | --- |\n"
        "| 10.1 | Synthetic employment agreement. |"
    )


def test_independent_equal_financial_columns_are_not_collapsed():
    md = html_to_markdown(
        '<table><tr><th>Metric</th><th>2026</th><th>2025</th></tr>'
        '<tr><td>Income</td><td>125</td><td>125</td></tr>'
        '<tr><td>Expense</td><td>10</td><td>10</td></tr></table>'
    )
    assert md == (
        "| Metric | 2026 | 2025 |\n| --- | --- | --- |\n"
        "| Income | 125 | 125 |\n| Expense | 10 | 10 |"
    )


def test_body_colspan_references_source_cell_without_repeating_text():
    md = html_to_markdown(
        '<table><tr><th>Metric</th><th>2026</th><th>2025</th></tr>'
        '<tr><td>Income</td><td>125</td><td>100</td></tr>'
        '<tr><td>Policy</td><td colspan="2">Same accounting policy.</td></tr></table>'
    )
    assert "| Income | 125 | 100 |" in md
    assert "| Policy | Same accounting policy. | [merged with column 2] |" in md
    assert md.count("Same accounting policy.") == 1


def test_merged_cell_preserves_literal_pipes_and_numeric_span_scope():
    md = html_to_markdown(
        '<table><tr><th>Metric</th><th>2026</th><th>2025</th></tr>'
        '<tr><td>Policy</td><td colspan="2">A | B</td></tr>'
        '<tr><td>Combined threshold</td><td colspan="2">125</td></tr></table>'
    )
    assert r"| Policy | A \| B | [merged with column 2] |" in md
    assert "| Combined threshold | 125 | [merged with column 2] |" in md


def test_narrative_years_are_not_promoted_to_headers():
    md = html_to_markdown(
        '<table><tr><th>Standard</th><th>Effective date</th><th>Description</th></tr>'
        '<tr><td>ASU 2026-03</td><td>January 1, 2027</td>'
        '<td>Recognition requirements issued in 2026 apply to these arrangements.</td></tr>'
        '<tr><td>ASU 2025-01</td><td>January 1, 2026</td>'
        '<td>Disclosure requirements issued in 2025.</td></tr></table>'
    )
    assert md.splitlines()[0] == "| Standard | Effective date | Description |"
    assert md.splitlines()[2].startswith("| ASU 2026-03 | January 1, 2027 |")
    assert md.splitlines()[3].startswith("| ASU 2025-01 | January 1, 2026 |")


def test_year_in_first_data_row_is_not_a_period_heading():
    md = html_to_markdown(
        "<table><tr><td>ASU 2026-03</td><td>Effective in 2027.</td></tr>"
        "<tr><td>ASU 2025-01</td><td>Effective in 2026.</td></tr></table>"
    )
    assert md.startswith("|  |  |\n| --- | --- |\n| ASU 2026-03 | Effective in 2027. |")


def test_long_first_narrative_row_stays_in_body():
    description = "A synthetic disclosure applicable in 2026. " * 10
    md = html_to_markdown(
        f"<table><tr><td>Policy</td><td>{description}</td></tr>"
        "<tr><td>Effective year</td><td>2027</td></tr></table>"
    )
    assert md.startswith("|  |  |\n| --- | --- |\n| Policy | ")
    assert description.strip() in md.splitlines()[2]


@pytest.mark.parametrize("period", [
    "June 30, 2026", "Three months ended June 30, 2026", "Q2 2026", "Fiscal 2026",
])
def test_short_period_headers_remain_recognized(period):
    md = html_to_markdown(
        f"<table><tr><td>Metric</td><td>{period}</td></tr>"
        "<tr><td>Assets</td><td>616,034</td></tr></table>"
    )
    assert md.startswith(f"| Metric | {period} |\n| --- | --- |\n| Assets | 616,034 |")


def test_maturity_headers_with_numbers_remain_headers():
    md = html_to_markdown(
        "<table><tr><td>Obligation</td><td>Less than 1 year</td><td>1 to 3 years</td></tr>"
        "<tr><td>Debt</td><td>100</td><td>200</td></tr></table>"
    )
    assert md.startswith(
        "| Obligation | Less than 1 year | 1 to 3 years |\n| --- | --- | --- |"
    )


def test_merged_disclosure_stays_with_headers_in_one_chunk(filing, document, caplog):
    disclosure = "Synthetic compensation policy applies to each named officer. " * 40
    md = html_to_markdown(
        "<table><tr><th>Category</th><th>Salary</th><th>Bonus</th><th>Equity</th></tr>"
        f'<tr><td>Policy</td><td colspan="3">{disclosure}</td></tr>'
        "<tr><td>Officer A</td><td>100</td><td>100</td><td>200</td></tr></table>"
    )
    chunks = chunk_document(
        ParsedDocument(filing=filing, document=document, content=md), ChunkingConfig(),
    )
    assert len(chunks) == 1
    assert disclosure.strip() in chunks[0].content
    assert chunks[0].content.count(disclosure.strip()) == 1
    assert "| Officer A | 100 | 100 | 200 |" in chunks[0].content
    assert "| Category | Salary | Bonus | Equity |" in chunks[0].content
    assert "exceeds chunk budget" not in caplog.text


def test_inline_xbrl_xml_declaration_does_not_change_html_content():
    source = '<html><body><p>Shareholders&#8217; equity</p></body></html>'
    assert html_to_markdown("<?xml version='1.0' encoding='ASCII'?>\n" + source) == html_to_markdown(source)


def test_multilevel_headers_spans_units_and_footnotes():
    html = """
    <table><caption>Consolidated synthetic results</caption>
      <tr><td colspan="5">Amounts in millions, except per-share data</td></tr>
      <tr><th rowspan="2">Metric</th><th colspan="2">2025</th><th colspan="2">2024</th></tr>
      <tr><th>Domestic</th><th>Foreign</th><th>Domestic</th><th>Foreign</th></tr>
      <tr><td rowspan="2">Income (1)</td><td>$125</td><td>$24</td><td>$110</td><td>$19</td></tr>
      <tr><td>125.5</td><td>(4.2)</td><td>100.1</td><td>3.5%</td></tr>
    </table><p>(1) Includes synthetic adjustments.</p>"""
    md = html_to_markdown(html)
    assert md == (
        "Consolidated synthetic results\n\nAmounts in millions, except per-share data\n\n"
        "| Metric | 2025 / Domestic | 2025 / Foreign | 2024 / Domestic | 2024 / Foreign |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Income (1) | $125 | $24 | $110 | $19 |\n"
        "| Income (1) | 125.5 | (4.2) | 100.1 | 3.5% |\n\n"
        "(1) Includes synthetic adjustments."
    )


def test_td_year_headers_and_first_data_row_not_consumed_as_header():
    md = html_to_markdown("""
    <table><tr><td></td><td>2025</td><td>2024</td></tr>
    <tr><td>Cash</td><td>12</td><td>9</td></tr></table>
    <table><tr><td>Loans</td><td>123</td></tr><tr><td>Deposits</td><td>120</td></tr></table>""")
    assert "|  | 2025 | 2024 |\n| --- | --- | --- |\n| Cash | 12 | 9 |" in md
    assert "|  |  |\n| --- | --- |\n| Loans | 123 |\n| Deposits | 120 |" in md


def test_superscript_footnotes_stay_attached_to_their_cells():
    md = html_to_markdown(
        "<table><tr><th>Metric</th><th>2025</th></tr>"
        "<tr><td>Income<sup>1</sup></td><td>125<sup>(2)</sup></td></tr></table>"
        "<p><sup>1</sup> Includes adjustments.</p><p><sup>(2)</sup> Estimated.</p>"
    )
    assert "| Income[1] | 125(2) |" in md
    assert "[1] Includes adjustments." in md and "(2) Estimated." in md


def test_identical_values_are_not_mistaken_for_a_full_width_title():
    assert "| 0 | 0 |\n| 1 | 2 |" in html_to_markdown(
        "<table><tr><td>0</td><td>0</td></tr><tr><td>1</td><td>2</td></tr></table>"
    )


def test_nested_layout_preserves_inner_table_once():
    md = html_to_markdown("""
    <table><tr><td><p>Financial overview</p><table>
    <tr><th>Metric</th><th>2025</th></tr><tr><td>Cash</td><td>125</td></tr>
    </table></td><td>Additional note</td></tr></table>""")
    assert md.count("Cash") == md.count("125") == md.count("Additional note") == 1
    assert "| Metric | 2025 |\n| --- | --- |\n| Cash | 125 |" in md
    assert "\\|" not in md


def test_hidden_css_and_ix_headers_removed_visible_facts_retained():
    md = html_to_markdown("""
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><head><style>
    .concealed, #secrets { display: none !important; }
    .invisible { visibility: hidden; }
    </style></head><body><h2>Visible totals</h2>
    <div class="concealed">HIDDEN_CLASS</div><p id="secrets">HIDDEN_ID</p>
    <div class="invisible">HIDDEN_VISIBILITY</div>
    <span style="DISPLAY: none">HIDDEN_STYLE</span><p hidden>HIDDEN_ATTR</p>
    <p aria-hidden="true">HIDDEN_ARIA</p>
    <ix:header><ix:hidden><ix:nonfraction>HIDDEN_IX</ix:nonfraction></ix:hidden></ix:header>
    <p>Cash <ix:nonfraction name="cash" unitRef="usd">125</ix:nonfraction></p>
    <p><ix:nonnumeric>VISIBLE_FACT</ix:nonnumeric></p></body></html>""")
    assert "HIDDEN" not in md
    assert "Cash 125" in md
    assert r"VISIBLE\_FACT" in md


def test_escaped_angle_brackets_page_markers_and_item_headings(tmp_path, filing, document):
    path = tmp_path / "annual.htm"
    path.write_text(
        "<p><b>Item 1A. Risk Factors</b></p><p>Literal &lt;RISK&gt; and &#60;TAG&#62;.</p>"
        "<PAGE><div style='page-break-after:always'>Other text</div><p>Final page</p>",
        encoding="utf-8",
    )
    parsed = parse_document(path, filing, document)
    assert "<RISK>" in parsed.content and "<TAG>" in parsed.content
    assert "## **Item 1A. Risk Factors**" in parsed.content
    assert parsed.content.count("---PAGE---") == 2


def _sgml(filename="annual.htm", sequence=1, kind="10-K", text="Selected synthetic content"):
    return (
        f"<DOCUMENT>\n<TYPE>{kind}\n<SEQUENCE>{sequence}\n<FILENAME>{filename}\n"
        f"<TEXT>{text}</TEXT>\n</DOCUMENT>\n"
    )


def test_aggregate_selects_only_exact_document(tmp_path, filing, document):
    path = tmp_path / "aggregate.txt"
    path.write_text(
        _sgml(text="<p>Selected synthetic &lt;RISK&gt; content.</p>")
        + _sgml("exhibit.htm", 2, "EX-99", "<p>DO_NOT_INCLUDE</p>"),
        encoding="utf-8",
    )
    parsed = parse_document(path, filing, document)
    assert parsed.content == "Selected synthetic <RISK> content."
    assert "DO_NOT_INCLUDE" not in parsed.content


@pytest.mark.parametrize("content", [
    _sgml("other.htm"), _sgml(sequence=2), _sgml(kind="10-Q"),
    _sgml() + _sgml(), "<DOCUMENT><TYPE>10-K",
])
def test_aggregate_missing_or_ambiguous_match_fails(tmp_path, filing, document, content):
    path = tmp_path / "aggregate.txt"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one match"):
        parse_document(path, filing, document)


@pytest.mark.parametrize("src", ["absent.jpg", "https://example.invalid/header.jpg", "../escape.jpg", ""])
def test_requested_ocr_rejects_unavailable_or_remote_assets(tmp_path, filing, document, src):
    path = tmp_path / "annual.htm"
    path.write_text(
        f'<p>Text</p><img src="{src}" style="width:0.14in;height:0.90in">',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="local image"):
        parse_document(path, filing, document, ocr_images=True)
    assert "[rotated text]" in parse_document(path, filing, document, ocr_images=False).content


def test_remote_ocr_entry_point_rejected():
    with pytest.raises(ValueError, match="Remote OCR"):
        html_to_markdown("<p>Content</p>", base_url="https://example.invalid/")


@pytest.mark.parametrize("label", ["Synthetic Director", "2025"])
def test_local_ocr_uses_only_predownloaded_asset(tmp_path, filing, document, monkeypatch, label):
    path = tmp_path / "annual.htm"
    path.write_text('<img src="header.jpg" width="12" height="90">', encoding="utf-8")
    (tmp_path / "header.jpg").write_bytes(b"synthetic image placeholder")
    opened = []

    class Image:
        size = (90, 120)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rotate(self, *args, **kwargs):
            return self

    def image_open(asset):
        opened.append(Path(asset))
        return Image()

    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=SimpleNamespace(open=image_open)))
    monkeypatch.setitem(
        sys.modules, "pytesseract",
        SimpleNamespace(image_to_string=lambda image, config: label),
    )
    assert parse_document(path, filing, document, ocr_images=True).content == label
    assert opened == [tmp_path / "header.jpg"]


def test_requested_ocr_missing_dependencies_fails(tmp_path, monkeypatch):
    (tmp_path / "header.jpg").write_bytes(b"synthetic")
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(RuntimeError, match="Pillow, pytesseract"):
        html_to_markdown(
            '<img src="header.jpg" width="12" height="90">', local_image_dir=tmp_path,
        )
