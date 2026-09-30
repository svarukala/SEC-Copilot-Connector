"""Opt-in, offline cached-corpus replay; writes evidence only to a new output path.

Run this script with PYTHONPATH selecting the revision under test. The manifest
contains exact local source hashes, metadata and parameters; no discovery occurs.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import logging
from pathlib import Path
import re
import socket

from sec_connector import parser
from sec_connector.chunker import chunk_document
from sec_connector.config import AppConfig, ChunkingConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import DocumentInfo, FilingMetadata
from sec_connector.payloads import serialize_item


def tokens(text):
    return re.findall(r"\w+", text.replace("---PAGE---", ""))


def numbers(text):
    return re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?:%)?", text)


def subsequence(expected, actual):
    iterator = iter(actual)
    for position, token in enumerate(expected):
        if not any(value == token for value in iterator):
            return {"ok": False, "position": position, "token": token}
    return {"ok": True}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def replay(entry, output, config):
    source = Path(entry["path"])
    if sha(source.read_bytes()) != entry["sha256"]:
        raise ValueError("Frozen source hash mismatch")
    filing = FilingMetadata.model_validate(entry["filing"])
    document = DocumentInfo.model_validate(entry["document"])
    tables = []
    original = parser.SECMarkdownConverter.convert_table

    def capture(converter, el, text=None, *args, **kwargs):
        converted = original(converter, el, text, *args, **kwargs)
        if not el.find("table"):
            cells = [
                [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["th", "td"], recursive=False)]
                for row in el.find_all("tr")
            ]
            tables.append({
                "index": len(tables), "source_cells": cells,
                "has_spans": bool(el.select("[rowspan], [colspan]")),
                "has_explicit_headers": bool(el.find("th")),
                "has_footnotes": bool(el.find("sup")),
                "converted": converted.strip(),
            })
        return converted

    parser.SECMarkdownConverter.convert_table = capture
    try:
        parsed = parser.parse_document(source, filing, document, ocr_images=False)
    finally:
        parser.SECMarkdownConverter.convert_table = original
    if parsed is None:
        raise ValueError("Parsing returned no content")
    chunks = chunk_document(parsed, config)
    graph = GraphClient(AppConfig(chunking=config))
    payloads = [graph.build_payload(chunk) for chunk in chunks]
    second = [graph.build_payload(chunk) for chunk in chunk_document(parsed, config)]
    if payloads != second:
        raise AssertionError("Nondeterministic chunking/IDs/payloads")
    ids = [p["id"] for p in payloads]
    assert len(ids) == len(set(ids))
    assert all(len(chunk.content) <= config.max_size for chunk in chunks)
    assert all(len(serialize_item(p)) <= config.max_item_bytes for p in payloads)
    for p in payloads:
        props = p["properties"]
        assert props["CIK"] == filing.cik and props["AccessionNumber"] == filing.accession_number
        assert props["DocumentName"] == document.filename and props["Sequence"] == document.sequence
        assert props["DocumentId"] == sha(filing.document_url(document.filename).encode())
        assert props["Url"] == filing.document_url(document.filename)
        assert p["acl"] == [{"type": "everyone", "value": "everyone", "accessType": "grant"}]
    emitted = "\n".join(chunk.content for chunk in chunks)
    row_chunks = defaultdict(set)
    for index, chunk in enumerate(chunks):
        for line in chunk.content.splitlines():
            if line.startswith("|"):
                row_chunks[line].add(index)
    table_rows = []
    # Check exact relational rows plus their preceding flattened header, not
    # merely numeric bags. Oversized rows are reported, never silently excluded.
    for match in re.finditer(r"^\|[^\n]*(?:\n\|[^\n]*)*", parsed.content, re.MULTILINE):
        lines = match.group().splitlines()
        if len(lines) < 2 or not re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+\s*", lines[1]):
            continue
        header = "\n".join(lines[:2])
        for row in lines[2:]:
            containing = [chunks[index] for index in row_chunks[row]]
            table_rows.append({
                "row_sha256": sha(row.encode()), "chars": len(row),
                "row_preserved": bool(containing),
                "header_together": any(header in chunk.content for chunk in containing),
                "row": row if not containing or not any(header in c.content for c in containing) else None,
            })
    headings = re.findall(r"^#{1,3}\s+(.+)$", parsed.content, re.MULTILINE)
    mixing = []
    for chunk in chunks:
        actual = [
            re.sub(r"[*_]", "", h).strip()
            for h in re.findall(r"^#{1,3}\s+(.+)$", chunk.content, re.MULTILINE)
        ]
        if any(h != chunk.section_title for h in actual):
            mixing.append({"id": chunk.graph_item_id, "section": chunk.section_title, "headings": actual})
    result = {
        "id": entry["id"], "source_sha256": entry["sha256"],
        "source_bytes": source.stat().st_size, "parser_module": str(Path(parser.__file__).resolve()),
        "chunks": len(chunks), "max_chars": max(map(lambda c: len(c.content), chunks)),
        "max_request_bytes": max(map(lambda p: len(serialize_item(p)), payloads)),
        "lexical_tokens": len(tokens(parsed.content)), "numeric_tokens": len(numbers(parsed.content)),
        "emitted_lexical_coverage": subsequence(tokens(parsed.content), tokens(emitted)),
        "emitted_numeric_coverage": subsequence(numbers(parsed.content), numbers(emitted)),
        "table_count": len(tables), "relational_rows": len(table_rows),
        "rows_missing": sum(not r["row_preserved"] for r in table_rows),
        "rows_missing_header": sum(not r["header_together"] for r in table_rows),
        "row_failures": [r for r in table_rows if not r["row_preserved"] or not r["header_together"]],
        "headings": headings, "section_mixing": mixing,
        "report_period_values": sorted({p["properties"].get("ReportPeriodEnd", "") for p in payloads}),
        "report_period_prefix": any("Report period:" in c.content for c in chunks),
        "deterministic_payloads": True,
        "payload_sha256": sha(json.dumps(payloads, sort_keys=True).encode()),
    }
    output.mkdir()
    (output / "parsed.md").write_text(parsed.content, encoding="utf-8")
    for name, value in (("result", result), ("tables", tables), ("payloads", payloads)):
        (output / f"{name}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    return result


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--manifest", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    options = args.parse_args()
    manifest = json.loads(options.manifest.read_bytes())
    options.output.mkdir(exist_ok=False, parents=True)
    config = ChunkingConfig.model_validate(manifest["chunking"])

    def no_network(*args, **kwargs):
        raise AssertionError("Corpus replay must remain offline")

    socket.socket.connect = no_network
    logging.basicConfig(filename=options.output / "warnings.log", level=logging.WARNING)
    results = []
    for entry in manifest["documents"]:
        print(f"Replaying {entry['id']}", flush=True)
        try:
            result = replay(entry, options.output / entry["id"], config)
        except Exception as exc:
            result = {"id": entry["id"], "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        (options.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in (
            "id", "chunks", "rows_missing", "rows_missing_header", "emitted_lexical_coverage",
            "emitted_numeric_coverage", "error",
        ) if k in result}), flush=True)
    if any("error" in result for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
