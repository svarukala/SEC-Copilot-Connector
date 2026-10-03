"""Aggregate sample guards and bounded resumability without network access."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sec_connector import sample_upload
from sec_connector.config import ChunkingConfig
from sec_connector.pilot_upload import Journal, SERVICE_METADATA_KEYS, digest, load_arm
from sec_connector.payloads import payload_hash
from sec_connector.sample_upload import (
    BANKS, CODE_FILES, SamplePlan, config_digest, execute_sample, validate_sample,
)


def save_review(plan):
    plan.preflight.write_text(json.dumps({
        "status": "passed", "processing_version": 8, "code_sha256": plan.code_sha256,
        "config_sha256": plan.config_sha256, "schema_sha256": plan.schema_sha256,
        "documents": [
            {"document_id": d.document_id, "source_sha256": d.source_sha256,
             "payloads_sha256": d.payloads_sha256, "count": d.count} for d in plan.documents
        ],
    }))
    plan.preflight_sha256 = digest(plan.preflight)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    # This uploader is permanently scoped to the historical v8 sample.
    monkeypatch.setattr(sample_upload, "PROCESSING_VERSION", 8)
    schema = tmp_path / "schema.json"
    schema.write_text('{"baseType":"microsoft.graph.externalItem","properties":[]}')
    config = ChunkingConfig()
    docs = []
    for ticker, cik in BANKS.items():
        for number in range(1, 6):
            accession = f"{cik}-26-{number:06}"
            filename = "source.htm"
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}"
            document_id = hashlib.sha256(url.encode()).hexdigest()
            item_id = f"{cik}-{accession.replace('-', '')}-1-1"
            source = tmp_path / f"{ticker}-{number}.htm"
            source.write_text(f"Synthetic {ticker} {number}")
            payloads = tmp_path / f"{ticker}-{number}.json"
            payloads.write_text(json.dumps([{
                "id": item_id, "properties": {
                    "CIK": cik, "Ticker": ticker, "AccessionNumber": accession,
                    "DocumentName": filename, "Sequence": 1, "DocumentId": document_id,
                    "Url": url, "Form": "8-K", "DocumentType": "EX-99.2",
                    "FilingDate": "2026-01-01T00:00:00Z", "ChunkOrdinal": 1,
                }, "content": {"type": "text", "value": source.read_text()},
                "acl": [{"type": "everyone", "value": "everyone", "accessType": "grant"}],
            }]))
            docs.append({
                "ticker": ticker, "cik": cik, "accession": accession, "filename": filename,
                "sequence": 1, "document_id": document_id, "form": "8-K",
                "document_type": "EX-99.2", "filing_date": "2026-01-01T00:00:00Z",
                "source": source, "source_sha256": digest(source), "payloads": payloads,
                "payloads_sha256": digest(payloads), "count": 1,
            })
    plan = SamplePlan(
        tenant_id="144b8c80-398d-405e-8055-fc9a9d5013f8",
        connection_id="secevidencev820260930", connection_name="Synthetic sample",
        processing_version=8, code_revision="0" * 40,
        code_sha256={name: digest(Path(sample_upload.__file__).parent / name) for name in CODE_FILES},
        chunking=config, config_sha256=config_digest(config),
        schema_path=schema, schema_sha256=digest(schema),
        preflight=tmp_path / "preflight.json", preflight_sha256="0" * 64,
        documents=docs,
    )
    save_review(plan)
    return plan


def test_sample_exact_count_and_exhibit_identity(sample):
    assert len(validate_sample(sample)) == 25


def test_v9_runtime_refuses_frozen_v8_sample_before_source_or_auth(sample, monkeypatch):
    from sec_connector.pipeline import PROCESSING_VERSION

    assert PROCESSING_VERSION == 9
    monkeypatch.setattr(sample_upload, "PROCESSING_VERSION", PROCESSING_VERSION)
    monkeypatch.setattr(sample_upload, "digest", lambda _: pytest.fail("source accessed"))
    with pytest.raises(ValueError, match="processing version differs"):
        validate_sample(sample)


@pytest.mark.parametrize("change", [
    "source", "payload", "schema", "code", "config", "review", "review_scope",
    "issuer_count", "document_duplicate", "bytes_duplicate", "prefix_collision",
])
def test_aggregate_provenance_and_collision_rejection(sample, change):
    if change == "source":
        sample.documents[0].source.write_text("different")
    elif change == "payload":
        sample.documents[0].payloads.write_text("[]")
    elif change == "schema":
        sample.schema_path.write_text("{}")
    elif change == "code":
        sample.code_sha256["parser.py"] = "0" * 64
    elif change == "config":
        sample.chunking.max_size = 7999
    elif change == "review":
        sample.preflight.write_text("{}")
    elif change == "review_scope":
        sample.documents[0].count = 2
    elif change == "issuer_count":
        sample.documents[0].ticker = "WFC"
    elif change == "document_duplicate":
        sample.documents[0].document_id = sample.documents[1].document_id
    elif change == "bytes_duplicate":
        sample.documents[0].source_sha256 = sample.documents[1].source_sha256
    else:
        sample.documents[0].accession = sample.documents[1].accession
    with pytest.raises(ValueError):
        validate_sample(sample)


@pytest.mark.parametrize("change", ["cross_document", "ordinal", "ticker", "acl", "period", "oversize"])
def test_rehashed_payload_still_cannot_escape_allowlist(sample, change):
    doc = sample.documents[0]
    payload = json.loads(doc.payloads.read_bytes())
    if change == "cross_document":
        payload = json.loads(sample.documents[1].payloads.read_bytes())
    elif change == "ordinal":
        payload[0]["properties"]["ChunkOrdinal"] = 2
    elif change == "ticker":
        payload[0]["properties"]["Ticker"] = "WFC"
    elif change == "acl":
        payload[0]["acl"] = []
    elif change == "period":
        payload[0]["properties"]["ReportPeriodEnd"] = "2026-04-01T00:00:00Z"
    else:
        payload[0]["content"]["value"] = "x" * 8001
    doc.payloads.write_text(json.dumps(payload))
    doc.payloads_sha256 = digest(doc.payloads)
    save_review(sample)
    with pytest.raises(ValueError):
        validate_sample(sample)


async def test_wrong_tenant_prevents_client_creation(sample, tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_TENANT_ID", "wrong")
    with pytest.raises(ValueError, match="Approved tenant"):
        await execute_sample(sample, tmp_path / "state", "approved")


async def test_batch_failure_checkpoints_other_inflight_items_before_resume(sample, tmp_path):
    entries = validate_sample(sample)
    journal = Journal(tmp_path / "j.json", {"approved": "sample"})
    journal.data.update(created=True, create_dispatched=True, schema_complete=True)
    schema = sample_upload.GraphClient.load_desired_schema(sample.schema_path)
    client = SimpleNamespace(
        config=SimpleNamespace(azure=SimpleNamespace(connection_id=sample.connection_id)),
        get_connection=AsyncMock(return_value={"id": sample.connection_id}),
        get_schema_status=AsyncMock(return_value=schema),
        schemas_compatible=sample_upload.GraphClient.schemas_compatible,
        load_desired_schema=sample_upload.GraphClient.load_desired_schema,
        create_connection=AsyncMock(), register_schema=AsyncMock(),
    )
    active, maximum, calls = 0, 0, []

    async def upload(item_id, payload):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        calls.append(item_id)
        await asyncio.sleep(0.001)
        active -= 1
        if item_id == entries[1]["id"]:
            raise TimeoutError("synthetic")

    client.upload_payload = upload
    payloads = {e["id"]: e["payload"] for e in entries}
    client._request = AsyncMock(side_effect=lambda method, path: payloads[path.rsplit("/", 1)[1]])
    with pytest.raises(TimeoutError):
        await load_arm(client, entries, journal, sample.schema_path, concurrency=5)
    assert maximum == 5 and active == 0 and len(calls) == 5
    restored = Journal(journal.path, {"approved": "sample"})
    assert len(restored.data["acknowledged"]) == 4 and not restored.data["read_back"]
    client.upload_payload = AsyncMock()
    await load_arm(client, entries, restored, sample.schema_path, concurrency=5)
    assert client.upload_payload.await_count == 21
    assert len(restored.data["read_back"]) == 25
    client.create_connection.assert_not_awaited()
    client.register_schema.assert_not_awaited()
    await load_arm(client, entries, restored, sample.schema_path, concurrency=5)
    assert client.upload_payload.await_count == 21
    assert client._request.await_count == 25


async def test_foreign_journal_items_rejected_before_mutation(sample, tmp_path):
    journal = Journal(tmp_path / "j.json", {})
    journal.data["acknowledged"]["foreign-item"] = "0" * 64
    with pytest.raises(ValueError, match="out-of-scope"):
        await load_arm(AsyncMock(), validate_sample(sample), journal, sample.schema_path)


async def test_exact_readback_rejects_added_property(sample, tmp_path):
    entries = validate_sample(sample)[:1]
    journal = Journal(tmp_path / "j.json", {})
    journal.data.update(created=True, schema_complete=True)
    client = sample_upload.SampleGraphClient(sample_upload.AppConfig())
    client.config.azure.connection_id = sample.connection_id
    client.get_connection = AsyncMock(return_value={"id": sample.connection_id})
    client.get_schema_status = AsyncMock(return_value=client.load_desired_schema(sample.schema_path))
    client.upload_payload = AsyncMock()
    actual = deepcopy(entries[0]["payload"])
    actual["properties"]["Unexpected"] = "not in frozen payload"
    client._request = AsyncMock(return_value=actual)
    with pytest.raises(RuntimeError, match="Persisted properties"):
        await load_arm(client, entries, journal, sample.schema_path)
    assert len(journal.data["acknowledged"]) == 1 and not journal.data["read_back"]


@pytest.mark.parametrize("change", [
    "none", "default_policy", "unknown", "missing_metadata", "invalid_uuid",
    "invalid_bool", "changed_submitted", "missing_submitted", "changed_content",
    "changed_acl", "declared_metadata",
])
async def test_service_metadata_is_separate_from_exact_submitted_readback(sample, tmp_path, change):
    entries = validate_sample(sample)[:1]
    journal = Journal(tmp_path / "j.json", {})
    journal.data.update(created=True, schema_complete=True)
    journal.data["acknowledged"] = {entries[0]["id"]: payload_hash(entries[0]["payload"])}
    if change == "declared_metadata":
        sample.schema_path.write_text(json.dumps({
            "baseType": "microsoft.graph.externalItem",
            "properties": [{"name": "ows_SiteID", "type": "string"}],
        }))
    client = sample_upload.SampleGraphClient(sample_upload.AppConfig())
    client.config.azure.connection_id = sample.connection_id
    client.get_connection = AsyncMock(return_value={"id": sample.connection_id})
    client.get_schema_status = AsyncMock(return_value=client.load_desired_schema(sample.schema_path))
    client.upload_payload = AsyncMock()
    client.create_connection = AsyncMock()
    client.register_schema = AsyncMock()
    actual = deepcopy(entries[0]["payload"])
    metadata = {
        key: True if key == "IsDGBasedSecurityEnabled" else "11111111-2222-3333-4444-555555555555"
        for key in SERVICE_METADATA_KEYS
    }
    actual["properties"].update(metadata)
    if change == "unknown":
        actual["properties"]["Unexpected"] = "not approved"
    elif change == "missing_metadata":
        del actual["properties"]["ows_WebId"]
    elif change == "invalid_uuid":
        actual["properties"]["ows_SiteID"] = "invalid"
    elif change == "invalid_bool":
        actual["properties"]["IsDGBasedSecurityEnabled"] = 1
    elif change == "changed_submitted":
        actual["properties"]["CIK"] = "wrong"
    elif change == "missing_submitted":
        del actual["properties"]["CIK"]
    elif change == "changed_content":
        actual["content"]["value"] += "changed"
    elif change == "changed_acl":
        actual["acl"] = []
    client._request = AsyncMock(return_value=actual)
    if change != "none":
        with pytest.raises(RuntimeError):
            await load_arm(
                client, entries, journal, sample.schema_path,
                allow_service_metadata=change != "default_policy",
            )
        assert not journal.data["read_back"] and not journal.data.get("service_metadata")
    else:
        await load_arm(client, entries, journal, sample.schema_path, allow_service_metadata=True)
        restored = Journal(journal.path, {})
        assert restored.data["read_back"] == restored.data["acknowledged"]
        assert restored.data["service_metadata"] == {entries[0]["id"]: metadata}
        await load_arm(client, entries, restored, sample.schema_path, allow_service_metadata=True)
        assert client._request.await_count == 1
        restored.data["service_metadata"]["foreign"] = metadata
        with pytest.raises(ValueError, match="without verified readback"):
            await load_arm(client, entries, restored, sample.schema_path, allow_service_metadata=True)
    client.upload_payload.assert_not_awaited()
    client.create_connection.assert_not_awaited()
    client.register_schema.assert_not_awaited()
