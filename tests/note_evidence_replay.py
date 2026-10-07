"""Opt-in exact-source note release gate; expected evidence stays evaluator-only."""

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

from bs4 import BeautifulSoup

from sec_connector import chunker, parser, pipeline
from sec_connector.config import AppConfig, ChunkingConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import DocumentInfo, FilingMetadata
from sec_connector.payloads import serialize_item
from tests.corpus_replay import sha, subsequence, tokens
from tests.evidence_evaluate import MANIFEST, offline, row_text


def replay(root, metadata, *, frozen_ocr=False):
    manifest = json.loads(MANIFEST.read_bytes())
    source = next(s for s in manifest["sources"] if s["id"] == "pnc-proxy-2025")
    path = root / source["filename"]
    raw = path.read_bytes()
    assert sha(raw) == source["sha256"]
    entry = next(e for e in json.loads(metadata.read_bytes()) if e["source_sha256"] == source["sha256"])
    filing = FilingMetadata.model_validate(entry["filing"])
    assert filing.filing_date.isoformat() == "2025-03-12T00:00:00"
    assert filing.document_url(path.name) == source["url"]
    document = DocumentInfo(sequence=1, filename=path.name, document_type=filing.form)
    bundle_path = root / "full-document-ocr-bundle.json"
    bundle = json.loads(bundle_path.read_bytes()) if frozen_ocr else None
    entries = iter(bundle["assets"]) if bundle else iter([])
    consumed = []

    def resolve(src, resolved):
        assert Path(src).name == src
        captured = next(entries)
        assert captured["src"] == src
        assert resolved == (root / src).resolve() == Path(captured["path"]).resolve()
        assert sha(resolved.read_bytes()) == captured["sha256"]
        assert sha(base64.b64decode(captured["bytes"], validate=True)) == captured["sha256"]
        consumed.append(src)
        return captured["text"]

    with offline(), patch.object(subprocess, "run", side_effect=AssertionError("No fresh OCR engine calls")):
        parsed = parser.parse_document(
            path, filing, document, ocr_images=frozen_ocr,
            ocr_resolver=resolve if frozen_ocr else None,
        )
        assert parsed is not None
        assert next(entries, None) is None
        config = ChunkingConfig()
        chunks = chunker.chunk_document(parsed, config)
        extra = {"table_notes": parsed.table_notes} if hasattr(parsed, "table_notes") else {}
        probe = chunker._split_content(
            parsed.content, 4000, 8000, 200, 31457280, parsed.table_header_rows, **extra,
        )
        graph = GraphClient(AppConfig())
        payloads = [graph.build_payload(c) for c in chunks]
        assert payloads == [graph.build_payload(c) for c in chunker.chunk_document(parsed, config)]
    assert len({p["id"] for p in payloads}) == len(payloads)
    assert all(len(p["content"]["value"]) <= config.max_size for p in payloads)
    assert all(len(serialize_item(p)) <= config.max_item_bytes for p in payloads)
    assert all(p["properties"]["Url"] == source["url"] for p in payloads)
    assert all("ReportPeriodEnd" not in p["properties"] for p in payloads)
    tables = BeautifulSoup(raw, "lxml").find_all("table")
    # Exact original table geometries, not bags of tokens or names elsewhere.
    rendered = {}
    for index in (128, 370):
        fragment = str(tables[index])
        if frozen_ocr and index == 128:
            assets = {e["src"]: e for e in bundle["assets"]}
            rendered[index] = parser.html_to_markdown(
                fragment, local_image_dir=root,
                ocr_resolver=lambda src, _: assets[src]["text"],
            )
        else:
            rendered[index] = parser.html_to_markdown(fragment)
    if frozen_ocr:
        reference = json.loads((root / "visual-reference.json").read_bytes())
        assert reference["source_sha256"] == sha(raw)
        names = [c.strip() for c in rendered[128].splitlines()[0].strip("|").split("|") if c.strip()]
        assert names == reference["names_in_image_order"]
        charity = next(row for row in rendered[128].splitlines() if "Charitable Contributions(3)" in row)
        columns = [c.strip() for c in charity.strip("|").split("|")][4::2]
        marked = [i for i, value in enumerate(columns, 1) if value]
        assert marked == reference["charity_marked_director_ordinals"]
        assert [names[i - 1] for i in marked] == reference["charity_marked_names"]
    note_text = {128: {}, 370: {}}
    for owner, indexes in ((128, (129, 130, 132, 133)), (370, (371, 372, 373, 374))):
        for index in indexes:
            values = [cell.get_text(" ", strip=True) for cell in tables[index].find_all("td")]
            values = [v for v in values if v]
            assert len(values) == 2
            note_text[owner][values[0]] = row_text(" ".join(values))
    scope = row_text(tables[127].get_text()).lstrip("\u25fe ").strip()
    emitted_lines = Counter(line for c in chunks for line in c.content.splitlines() if line.startswith("|"))
    results = []
    for index, text in rendered.items():
        for row in text.splitlines()[2:]:
            if index == 370 and ("performance metrics |" in row):
                continue
            relevant = [c for c in chunks if row in c.content.splitlines()]
            # Single star and double star are separate definitions, never substrings.
            plain = row.replace("\\*", "*")
            markers = re.findall(r"(?<!\*)\*{1,2}(?!\*)|\([1-4]\)", plain)
            required = [note_text[index][m] for m in markers if m in note_text[index]]
            if index == 128 and "(3)" in plain:
                required.append(scope)
            probe_matches = [p for p in probe if row in p.splitlines()]
            results.append({
                "table": index, "row": row, "occurrences": emitted_lines[row],
                "required_notes": required,
                "co_located": bool(relevant) and all(
                    all(n in row_text(c.content) for n in required) for c in relevant
                ),
                "source_header_preserved": bool(relevant) and all(text.splitlines()[0] in c.content for c in relevant),
                "probe_co_located": bool(probe_matches) and all(
                    all(n in row_text(p) for n in required) for p in probe_matches
                ),
                "pages": [c.page_number for c in relevant],
                "sections": [c.section_title for c in relevant],
                "ids": [c.graph_item_id for c in relevant],
            })
    assert all(r["occurrences"] == 1 for r in results)
    assert len([r for r in results if r["table"] == 370]) == 13
    assert len([r for r in results if r["table"] == 128]) == 5
    assert all(r["source_header_preserved"] for r in results)
    emitted = "\n".join(c.content for c in chunks)
    receipt = {
        "kind": "offline_source_note_association", "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sha(raw), "source_date": filing.filing_date.isoformat(),
        "processing_version": pipeline.PROCESSING_VERSION,
        "ocr": "frozen-receipt replay, not fresh OCR" if frozen_ocr else "disabled",
        "ocr_bundle_sha256": sha(bundle_path.read_bytes()) if bundle else None,
        "ocr_occurrences": len(consumed), "ocr_unique_assets": len(set(consumed)),
        "dependencies": {name: version(name) for name in ("beautifulsoup4", "lxml", "markdownify", "pydantic")},
        "code_sha256": {p.name: sha(p.read_bytes()) for p in Path(parser.__file__).parent.glob("*.py")},
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "manifest_sha256": sha(MANIFEST.read_bytes()),
        "parsed_sha256": sha(parsed.content.encode()),
        "payload_sha256": sha(json.dumps(payloads, sort_keys=True).encode()),
        "chunks": len(chunks), "max_chars": max(len(c.content) for c in chunks),
        "max_request_bytes": max(len(serialize_item(p)) for p in payloads),
        "lexical_coverage": subsequence(tokens(parsed.content), tokens(emitted)),
        "rows": results, "all_required_associations": all(r["co_located"] for r in results),
        "all_required_probe_associations": all(r["probe_co_located"] for r in results),
        "remote_delivery_search_agent_evaluation": "not_run",
    }
    return receipt, payloads


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", required=True, type=Path, help="Read-only retained copied HTML/assets/receipts")
    cli.add_argument("--metadata", required=True, type=Path, help="Read-only retained metadata summary")
    cli.add_argument("--output", required=True, type=Path, help="New private output directory")
    cli.add_argument("--frozen-ocr", action="store_true")
    args = cli.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists; preserve original evidence")
    receipt, payloads = replay(args.root, args.metadata, frozen_ocr=args.frozen_ocr)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("receipt.json", receipt), ("payloads.json", payloads)):
        with (args.output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: receipt[k] for k in (
        "processing_version", "ocr", "chunks", "max_chars", "max_request_bytes", "all_required_associations",
    )}))


if __name__ == "__main__":
    main()
