"""Inspect one selected SEC document using the production transport/parser/payload code.

Usage: python test_filing.py <SEC-document-URL> [--output-dir data/test_output] [--ocr]
Requires SEC_USER_AGENT, but no Graph credentials. Never uploads anything.
"""

import argparse
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sec_connector.chunker import chunk_document
from sec_connector.config import load_config
from sec_connector.graph_client import GraphClient
from sec_connector.parser import parse_document
from sec_connector.payloads import serialize_item
from sec_connector.sec_client import SECClient


def parse_sec_url(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    match = re.fullmatch(r"/Archives/edgar/data/([0-9]+)/([0-9]{18})/([^/]+)", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "www.sec.gov" or not match:
        raise ValueError("Expected an HTTPS SEC Archives document URL")
    return match[1].zfill(10), match[2], SECClient._safe_filename(unquote(match[3]))


async def inspect_filing(url: str, output_dir: Path, ocr: bool) -> None:
    config = load_config()
    cik, accession, filename = parse_sec_url(url)
    async with SECClient(config) as sec:
        submissions = await sec._get_json(f"{config.sec.data_url}/submissions/CIK{cik}.json")
        tickers = submissions.get("tickers")
        if not tickers:
            raise ValueError("Issuer has no ticker; this connector selects filings by ticker")
        filings = await sec.get_filings(tickers[0])
        filing = next((item for item in filings if item.accession_no_dashes == accession), None)
        if filing is None:
            raise ValueError("Filing is outside the configured form/date/history selection")
        documents = await sec.get_filing_documents(filing)
        document = next((item for item in documents if item.filename == filename), None)
        if document is None:
            raise ValueError("Document is not a supported primary document or selected exhibit")
        path = await sec.download_document(filing, document, output_dir / "source", refresh=True)
    parsed = await asyncio.to_thread(parse_document, path, filing, document, ocr_images=ocr)
    if parsed is None:
        raise ValueError("Document did not produce usable content")
    chunks = chunk_document(parsed, config.chunking)
    graph = GraphClient(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "02_full_markdown.md").write_text(parsed.content, encoding="utf-8")
    payload_dir = output_dir / "chunks_json"
    payload_dir.mkdir(exist_ok=True)
    for chunk in chunks:
        payload = graph.build_payload(chunk)
        if len(serialize_item(payload)) > config.chunking.max_item_bytes:
            raise ValueError(f"Serialized Graph request exceeds configured ceiling: {chunk.graph_item_id}")
        (payload_dir / f"{chunk.graph_item_id}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    (output_dir / "00_summary.json").write_text(json.dumps({
        "source_url": filing.document_url(filename),
        "filing": filing.model_dump(mode="json"),
        "document": document.model_dump(mode="json"),
        "chunks": len(chunks),
        "chunking": config.chunking.model_dump(),
    }, indent=2), encoding="utf-8")
    print(f"Prepared {len(chunks)} production-format payloads in {payload_dir}; no uploads performed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--output-dir", type=Path, default=Path("data/test_output"))
    parser.add_argument("--ocr", action="store_true", help="OCR local assets; install the OCR extra and Tesseract")
    args = parser.parse_args()
    asyncio.run(inspect_filing(args.url, args.output_dir, args.ocr))


if __name__ == "__main__":
    main()
