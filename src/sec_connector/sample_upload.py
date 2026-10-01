"""Create-only frozen 25-document, five-bank pilot. No discovery or deletion."""

import argparse
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Literal

from pydantic import Field

from .config import AppConfig, AzureConfig, ChunkingConfig
from .graph_client import GraphClient
from .payloads import serialize_item
from .pipeline import PROCESSING_VERSION
from .pilot_upload import (
    Journal, PilotGraphClient, Scope, StrictModel, digest, ensure_absent, load_arm,
    pilot_lock, validate_token_identity,
)

BANKS = {"PNC": "0000713676", "WFC": "0000072971", "JPM": "0000019617",
         "BAC": "0000070858", "USB": "0000036104"}
PROTECTED = {"secedgar20260909v2", "secevidencepilot20260930a", "secevidencepilot20260930b"}
CODE_FILES = (
    "parser.py", "chunker.py", "models.py", "payloads.py", "graph_client.py",
    "pipeline.py", "config.py",
)


class SampleDocument(Scope):
    ticker: Literal["PNC", "WFC", "JPM", "BAC", "USB"]
    document_type: str
    source: Path
    payloads: Path
    payloads_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    count: int = Field(gt=0)


class SamplePlan(StrictModel):
    tenant_id: Literal["144b8c80-398d-405e-8055-fc9a9d5013f8"]
    connection_id: Literal["secevidencev820260930"]
    connection_name: str = Field(min_length=1, max_length=128)
    processing_version: Literal[8]
    code_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    code_sha256: dict[str, str]
    chunking: ChunkingConfig
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_path: Path
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    preflight: Path
    preflight_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    documents: list[SampleDocument] = Field(min_length=25, max_length=25)


def config_digest(config: ChunkingConfig) -> str:
    return hashlib.sha256(json.dumps(config.model_dump(), sort_keys=True).encode()).hexdigest()


def validate_sample(plan: SamplePlan) -> list[dict]:
    """Fail before authentication if any frozen scope or provenance is inconsistent."""
    if PROCESSING_VERSION != plan.processing_version:
        raise ValueError("Current processing version differs from frozen sample")
    if plan.connection_id.lower() in PROTECTED or not re.fullmatch(r"[A-Za-z0-9]{3,32}", plan.connection_id):
        raise ValueError("Invalid or protected destination")
    if set(plan.code_sha256) != set(CODE_FILES):
        raise ValueError("Incomplete processing-code provenance")
    for name in CODE_FILES:
        if digest(Path(__file__).parent / name) != plan.code_sha256[name]:
            raise ValueError("Processing-code hash mismatch")
    if config_digest(plan.chunking) != plan.config_sha256 or plan.chunking.max_size > 8000:
        raise ValueError("Processing configuration mismatch")
    if digest(plan.schema_path) != plan.schema_sha256:
        raise ValueError("Schema hash mismatch")
    GraphClient.load_desired_schema(plan.schema_path)
    if digest(plan.preflight) != plan.preflight_sha256:
        raise ValueError("Preflight hash mismatch")
    review = json.loads(plan.preflight.read_bytes())
    if (review.get("status") != "passed" or review.get("processing_version") != 8
            or review.get("code_sha256") != plan.code_sha256
            or review.get("config_sha256") != plan.config_sha256
            or review.get("schema_sha256") != plan.schema_sha256):
        raise ValueError("Preflight does not approve frozen processing provenance")
    if Counter(d.ticker for d in plan.documents) != Counter({ticker: 5 for ticker in BANKS}):
        raise ValueError("Sample requires exactly five documents for each approved ticker")
    if len({d.document_id for d in plan.documents}) != 25:
        raise ValueError("Duplicate document identity")
    if len({(d.ticker, d.source_sha256) for d in plan.documents}) != 25:
        raise ValueError("Duplicate source bytes within issuer")
    if len({(d.cik, d.accession, d.sequence) for d in plan.documents}) != 25:
        raise ValueError("Cross-document item-prefix collision")
    expected_review = [
        {"document_id": d.document_id, "source_sha256": d.source_sha256,
         "payloads_sha256": d.payloads_sha256, "count": d.count}
        for d in plan.documents
    ]
    if review.get("documents") != expected_review:
        raise ValueError("Preflight document allowlist mismatch")
    all_entries, all_ids = [], set()
    for d in plan.documents:
        if d.cik != BANKS[d.ticker] or digest(d.source) != d.source_sha256:
            raise ValueError("Source provenance or ticker/CIK mismatch")
        if digest(d.payloads) != d.payloads_sha256:
            raise ValueError("Frozen payload hash mismatch")
        url = f"https://www.sec.gov/Archives/edgar/data/{d.cik}/{d.accession.replace('-', '')}/{d.filename}"
        if hashlib.sha256(url.encode()).hexdigest() != d.document_id:
            raise ValueError("DocumentId does not match source URL")
        payloads = json.loads(d.payloads.read_bytes())
        if not isinstance(payloads, list) or len(payloads) != d.count:
            raise ValueError("Frozen document count mismatch")
        expected = {
            "CIK": d.cik, "Ticker": d.ticker, "AccessionNumber": d.accession,
            "DocumentName": d.filename, "Sequence": d.sequence, "DocumentId": d.document_id,
            "Url": url, "Form": d.form, "DocumentType": d.document_type, "FilingDate": d.filing_date,
        }
        prefix = f"{d.cik}-{d.accession.replace('-', '')}-{d.sequence}-"
        for ordinal, payload in enumerate(payloads, 1):
            item_id = payload["id"]
            props = payload["properties"]
            if (item_id in all_ids
                    or not re.fullmatch(re.escape(prefix) + r"[1-9]\d*(?:-[1-9]\d*)?", item_id)):
                raise ValueError("Duplicate or out-of-scope item ID")
            if any(props.get(k) != v for k, v in expected.items()) or props.get("ChunkOrdinal") != ordinal:
                raise ValueError("Payload escapes document scope or ordinal order")
            if d.form not in {"10-K", "10-Q", "10-K/A", "10-Q/A"} and "ReportPeriodEnd" in props:
                raise ValueError("Unsupported fiscal period for form")
            if payload["acl"] != [{"type": "everyone", "value": "everyone", "accessType": "grant"}]:
                raise ValueError("ACL differs from approved connector policy")
            content = payload["content"]
            if (content.get("type") != "text" or not isinstance(content.get("value"), str)
                    or not 0 < len(content["value"]) <= plan.chunking.max_size
                    or len(serialize_item(payload)) > plan.chunking.max_item_bytes):
                raise ValueError("Invalid or oversized frozen item")
            all_ids.add(item_id)
            all_entries.append({"id": item_id, "payload": payload})
    return all_entries


class SampleGraphClient(PilotGraphClient):
    async def create_connection(self):
        return await self._request("POST", "/external/connections", json_data={
            "id": self.config.azure.connection_id, "name": self.config.azure.connection_name,
            "description": "Isolated processing-version-8 SEC sample: exactly five cached documents per bank.",
        })


async def execute_sample(plan: SamplePlan, state_dir: Path, plan_sha256: str):
    entries = validate_sample(plan)
    tenant, app, secret = (os.environ.get(k, "") for k in (
        "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
    ))
    if tenant.lower() != plan.tenant_id or not app or not secret:
        raise ValueError("Approved tenant and populated app credentials required")
    with pilot_lock(state_dir):
        binding = {"tenant": tenant.lower(), "app": app, "connection": plan.connection_id,
                   "plan_sha256": plan_sha256, "schema_sha256": plan.schema_sha256,
                   "documents": [d.model_dump(mode="json") for d in plan.documents]}
        journal = Journal(state_dir / "sample.json", binding)
        config = AppConfig(azure=AzureConfig(
            tenant_id=tenant, client_id=app, client_secret=secret,
            connection_id=plan.connection_id, connection_name=plan.connection_name,
        ), chunking=plan.chunking)
        async with SampleGraphClient(config) as client:
            validate_token_identity(await client._get_token(), tenant, app)
            if not journal.data["created"]:
                if journal.data["create_dispatched"]:
                    raise RuntimeError("Unknown create acknowledgment; manual reconciliation required")
                await ensure_absent(client)
            await load_arm(
                client, entries, journal, plan.schema_path,
                concurrency=5, allow_service_metadata=True,
            )
        journal.data["documents"] = [
            {"ticker": d.ticker, "document_id": d.document_id, "count": d.count,
             "acknowledged": d.count, "read_back": d.count} for d in plan.documents
        ]
        journal.save()


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--plan", type=Path, required=True)
    args.add_argument("--plan-sha256", required=True)
    args.add_argument("--state-dir", type=Path)
    args.add_argument("--execute", action="store_true")
    options = args.parse_args()
    try:
        raw = options.plan.read_bytes()
        if hashlib.sha256(raw).hexdigest() != options.plan_sha256:
            raise ValueError("Approved plan hash mismatch")
        plan = SamplePlan.model_validate_json(raw)
        entries = validate_sample(plan)
        print(f"Validated exactly 25 documents / {len(entries)} items for {plan.connection_id}", flush=True)
        if options.execute:
            if options.state_dir is None:
                raise ValueError("Dedicated state directory required")
            asyncio.run(execute_sample(plan, options.state_dir, options.plan_sha256))
    except Exception as exc:
        # Never print remote error text or authentication material.
        print(f"Sample stopped: {type(exc).__name__}; HTTP status={getattr(exc, 'status', 'n/a')}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
