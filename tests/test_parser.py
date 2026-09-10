"""Tests for document parser."""

import pytest

from sec_connector.parser import (
    clean_sec_text,
    extract_sgml_documents,
    html_to_markdown,
)


def test_html_to_markdown_basic():
    """Test basic HTML to Markdown conversion."""
    html = "<h1>Title</h1><p>Paragraph text.</p>"
    md = html_to_markdown(html)

    assert "# Title" in md
    assert "Paragraph text." in md


def test_html_to_markdown_table():
    """Test table conversion to Markdown."""
    html = """
    <table>
        <tr><th>Header 1</th><th>Header 2</th></tr>
        <tr><td>Cell 1</td><td>Cell 2</td></tr>
    </table>
    """
    md = html_to_markdown(html)

    assert "Header 1" in md
    assert "Header 2" in md
    assert "Cell 1" in md
    assert "|" in md


def test_html_to_markdown_removes_scripts():
    """Test that scripts are removed."""
    html = "<p>Text</p><script>alert('bad')</script><p>More text</p>"
    md = html_to_markdown(html)

    assert "alert" not in md
    assert "Text" in md
    assert "More text" in md


def test_clean_sec_text_entities():
    """Test HTML entity cleaning."""
    text = "Test&nbsp;text&amp;more&lt;tag&gt;"
    cleaned = clean_sec_text(text)

    assert "Test text" in cleaned
    assert "&more<tag>" in cleaned


def test_clean_sec_text_page_markers():
    """Test page marker conversion."""
    text = "Page 1<PAGE>Page 2"
    cleaned = clean_sec_text(text)

    assert "---PAGE---" in cleaned


def test_extract_sgml_documents():
    """Test SGML document extraction."""
    sgml = """
    <DOCUMENT>
    <TYPE>10-K
    <SEQUENCE>1
    <FILENAME>form10k.htm
    <TEXT>
    Document content here.
    </TEXT>
    </DOCUMENT>
    <DOCUMENT>
    <TYPE>EX-99
    <SEQUENCE>2
    <FILENAME>exhibit.txt
    <TEXT>
    Exhibit content.
    </TEXT>
    </DOCUMENT>
    """

    docs = extract_sgml_documents(sgml)

    assert len(docs) == 2
    assert docs[0]["type"] == "10-K"
    assert docs[0]["sequence"] == "1"
    assert docs[0]["filename"] == "form10k.htm"
    assert "Document content" in docs[0]["text"]


def test_extract_sgml_documents_empty():
    """Test SGML extraction with no documents."""
    sgml = "No documents here"
    docs = extract_sgml_documents(sgml)

    assert len(docs) == 0
