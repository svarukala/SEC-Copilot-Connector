"""Fail-closed frozen pilot loading; all Graph calls are mocked."""

import base64
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from sec_connector.config import AppConfig
from sec_connector.pilot_upload import (
    Journal, PilotGraphClient, PilotPlan, digest, execute, load_arm,
    pilot_lock, validate_plan, validate_token_identity,
)


@pytest.fixture
def plan(tmp_path):
    source = tmp_path / "source.htm"
    source.write_text("Synthetic source", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text('{"baseType":"microsoft.graph.externalItem","properties":[]}')
    url = "https://www.sec.gov/Archives/edgar/data/0000000123/000000012326000001/source.htm"
    item_id = "0000000123-000000012326000001-1-1"
    payload = {
        "id": item_id, "properties": {
            "CIK": "0000000123", "AccessionNumber": "0000000123-26-000001",
            "DocumentName": "source.htm", "Sequence": 1,
            "DocumentId": hashlib.sha256(url.encode()).hexdigest(), "Url": url,
            "Form": "DEF 14A", "DocumentType": "DEF 14A",
            "FilingDate": "2026-03-11T00:00:00Z", "ChunkOrdinal": 1,
        },
        "content": {"type": "text", "value": "Synthetic source"},
        "acl": [{"type": "everyone", "value": "everyone", "accessType": "grant"}],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"id": item_id, "payload": payload}]))
    return PilotPlan(
        tenant_id="tenant", source=source, schema_path=schema, schema_sha256=digest(schema),
        forbidden_connection="historical",
        scope={
            "cik": "0000000123", "accession": "0000000123-26-000001",
            "filename": "source.htm", "sequence": 1,
            "document_id": payload["properties"]["DocumentId"], "form": "DEF 14A",
            "filing_date": "2026-03-11T00:00:00Z", "source_sha256": digest(source),
        },
        baseline={"connection_id": "pilota", "manifest": manifest, "manifest_sha256": digest(manifest), "count": 1},
        candidate={"connection_id": "pilotb", "manifest": manifest, "manifest_sha256": digest(manifest), "count": 1},
    )


def test_validates_frozen_scope_without_auth(plan):
    assert len(validate_plan(plan)["baseline"]) == 1


@pytest.mark.parametrize("change", ["source", "schema", "manifest", "collision", "historical", "count"])
def test_plan_mismatch_rejected(plan, change):
    if change in {"source", "schema", "manifest"}:
        path = {"source": plan.source, "schema": plan.schema_path, "manifest": plan.baseline.manifest}[change]
        path.write_text("changed")
    elif change == "collision":
        plan.candidate.connection_id = plan.baseline.connection_id
    elif change == "historical":
        plan.candidate.connection_id = plan.forbidden_connection
    else:
        plan.candidate.count = 2
    with pytest.raises(ValueError):
        validate_plan(plan)


@pytest.mark.parametrize("field,value", [
    ("CIK", "0000000999"), ("AccessionNumber", "0000000123-26-000002"),
    ("DocumentName", "exhibit.htm"), ("Sequence", 2), ("DocumentId", "0" * 64),
    ("ChunkOrdinal", 2), ("Url", "https://example.invalid"), ("Form", "10-K"),
])
def test_manifest_scope_mismatch_even_with_updated_hash(plan, field, value):
    entries = json.loads(plan.baseline.manifest.read_bytes())
    entries[0]["payload"]["properties"][field] = value
    plan.baseline.manifest.write_text(json.dumps(entries))
    plan.baseline.manifest_sha256 = digest(plan.baseline.manifest)
    plan.candidate.manifest_sha256 = plan.baseline.manifest_sha256
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_acl_drift_rejected(plan):
    entries = json.loads(plan.baseline.manifest.read_bytes())
    entries[0]["payload"]["acl"] = []
    plan.baseline.manifest.write_text(json.dumps(entries))
    plan.baseline.manifest_sha256 = digest(plan.baseline.manifest)
    with pytest.raises(ValueError, match="ACL"):
        validate_plan(plan)


def token(**overrides):
    claims = {"tid": "tenant", "appid": "app", "aud": "https://graph.microsoft.com",
              "roles": ["ExternalConnection.ReadWrite.OwnedBy", "ExternalItem.ReadWrite.OwnedBy"]}
    claims.update(overrides)
    return "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"


@pytest.mark.parametrize("overrides", [
    {"tid": "wrong"}, {"appid": "wrong"}, {"aud": "wrong"}, {"roles": []},
])
def test_authenticated_identity_guard(overrides):
    validate_token_identity(token(), "tenant", "app")
    with pytest.raises(ValueError):
        validate_token_identity(token(**overrides), "tenant", "app")


@pytest.fixture
def client(plan):
    client = PilotGraphClient(AppConfig())
    client.config.azure.connection_id = "pilota"
    missing = aiohttp.ClientResponseError(SimpleNamespace(real_url="synthetic"), (), status=404)
    client.get_connection = AsyncMock(side_effect=[missing, {"id": "pilota"}])
    client.create_connection = AsyncMock(return_value={"id": "pilota"})
    client._schema_operation_url = "https://graph.microsoft.com/v1.0/external/connections/pilota/operations/op"
    client.register_schema = AsyncMock()
    client.wait_for_schema = AsyncMock(return_value=True)
    client.get_schema_status = AsyncMock(return_value=client.load_desired_schema(plan.schema_path))
    client.upload_payload = AsyncMock()
    client._request = AsyncMock(return_value=validate_plan(plan)["baseline"][0]["payload"])
    return client


async def test_acknowledgments_readback_and_resume(plan, client, tmp_path):
    entries = validate_plan(plan)["baseline"]
    journal = Journal(tmp_path / "journal.json", {"test": "binding"})
    await load_arm(client, entries, journal, plan.schema_path)
    restored = Journal(journal.path, {"test": "binding"})
    assert restored.data["result"]["acknowledged"] == restored.data["result"]["read_back"] == 1
    assert restored.data["result"]["search_readiness"] == "not established"
    client.get_connection = AsyncMock(return_value={"id": "pilota"})
    await load_arm(client, entries, restored, plan.schema_path)
    client.create_connection.assert_awaited_once()
    client.register_schema.assert_awaited_once()
    client.upload_payload.assert_awaited_once()
    with pytest.raises(ValueError, match="provenance mismatch"):
        Journal(journal.path, {"test": "changed"})


async def test_existing_connection_fails_without_adoption(plan, client, tmp_path):
    client.get_connection = AsyncMock(return_value={"id": "pilota"})
    with pytest.raises(RuntimeError, match="collision"):
        await load_arm(client, validate_plan(plan)["baseline"], Journal(tmp_path / "j.json", {}), plan.schema_path)
    client.create_connection.assert_not_awaited()
    client.upload_payload.assert_not_awaited()


@pytest.mark.parametrize("stage", ["create", "schema"])
async def test_unknown_mutation_is_not_repeated(plan, client, tmp_path, stage):
    journal = Journal(tmp_path / "j.json", {})
    journal.data["create_dispatched"] = True
    if stage == "schema":
        journal.data["created"] = True
        journal.data["schema_dispatched"] = True
        client.get_connection = AsyncMock(return_value={"id": "pilota"})
    journal.save()
    with pytest.raises(RuntimeError):
        await load_arm(client, validate_plan(plan)["baseline"], journal, plan.schema_path)
    client.create_connection.assert_not_awaited()
    client.register_schema.assert_not_awaited()
    client.upload_payload.assert_not_awaited()


async def test_upload_failure_never_acknowledged(plan, client, tmp_path):
    client.upload_payload.side_effect = TimeoutError()
    journal = Journal(tmp_path / "j.json", {})
    with pytest.raises(TimeoutError):
        await load_arm(client, validate_plan(plan)["baseline"], journal, plan.schema_path)
    assert journal.data["acknowledged"] == journal.data["read_back"] == {}


async def test_readback_mismatch_not_marked_complete(plan, client, tmp_path):
    wrong = deepcopy(validate_plan(plan)["baseline"][0]["payload"])
    wrong["content"]["value"] = "wrong"
    client._request.return_value = wrong
    journal = Journal(tmp_path / "j.json", {})
    with pytest.raises(RuntimeError, match="Persisted content"):
        await load_arm(client, validate_plan(plan)["baseline"], journal, plan.schema_path)
    assert len(journal.data["acknowledged"]) == 1
    assert journal.data["read_back"] == {}
    assert "result" not in journal.data


def test_pilot_lock_prevents_concurrent_writers(tmp_path):
    with pilot_lock(tmp_path):
        with pytest.raises(FileExistsError):
            with pilot_lock(tmp_path):
                pytest.fail("Must not acquire twice")
    assert not (tmp_path / "pilot.lock").exists()


async def test_wrong_tenant_blocks_before_auth(plan, tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_TENANT_ID", "wrong")
    with pytest.raises(ValueError, match="Approved tenant"):
        await execute(plan, tmp_path, validate_plan(plan))


async def test_transport_forbids_delete():
    with pytest.raises(ValueError, match="forbids deletion"):
        await PilotGraphClient(AppConfig())._request_result("DELETE", "/external/connections/history")


async def test_second_arm_collision_prevents_all_creates(plan, tmp_path, monkeypatch):
    from sec_connector import pilot_upload

    clients = []
    missing = aiohttp.ClientResponseError(SimpleNamespace(real_url="synthetic"), (), status=404)
    for response in (missing, {"id": "pilotb"}):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client._get_token.return_value = token()
        if isinstance(response, Exception):
            client.get_connection.side_effect = response
        else:
            client.get_connection.return_value = response
        clients.append(client)
    factory = iter(clients)
    monkeypatch.setattr(pilot_upload, "PilotGraphClient", lambda config: next(factory))
    for key, value in (("AZURE_TENANT_ID", "tenant"), ("AZURE_CLIENT_ID", "app"), ("AZURE_CLIENT_SECRET", "synthetic")):
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="collision"):
        await execute(plan, tmp_path, validate_plan(plan))
    for client in clients:
        client.create_connection.assert_not_awaited()
        client.register_schema.assert_not_awaited()
        client.upload_payload.assert_not_awaited()


async def test_create_409_is_never_adopted_or_retried():
    client = PilotGraphClient(AppConfig())
    client._request = AsyncMock(side_effect=aiohttp.ClientResponseError(
        SimpleNamespace(real_url="synthetic"), (), status=409,
    ))
    client.get_connection = AsyncMock()
    with pytest.raises(aiohttp.ClientResponseError):
        await client.create_connection()
    client._request.assert_awaited_once()
    client.get_connection.assert_not_awaited()


async def test_schema_timeout_resumes_recorded_operation(plan, client, tmp_path):
    journal = Journal(tmp_path / "j.json", {})
    entries = validate_plan(plan)["baseline"]
    client.wait_for_schema.return_value = False
    with pytest.raises(RuntimeError, match="Schema pending"):
        await load_arm(client, entries, journal, plan.schema_path)
    client.upload_payload.assert_not_awaited()
    client.wait_for_schema.return_value = True
    client.get_connection = AsyncMock(return_value={"id": "pilota"})
    await load_arm(client, entries, journal, plan.schema_path)
    client.register_schema.assert_awaited_once()


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_transport_does_not_retry_uncertain_non_idempotent_mutation(method):
    client = PilotGraphClient(AppConfig())
    client._get_token = AsyncMock(return_value="synthetic")
    client._session = SimpleNamespace(request=Mock(side_effect=TimeoutError()))
    path = "/external/connections"
    if method == "PATCH":
        path += f"/{client.config.azure.connection_id}/schema"
    with pytest.raises(TimeoutError):
        await client._request_result(method, path, json_data={})
    client._session.request.assert_called_once()


async def test_unknown_create_persisted_before_dispatch(plan, client, tmp_path):
    client.create_connection.side_effect = TimeoutError()
    journal = Journal(tmp_path / "j.json", {})
    entries = validate_plan(plan)["baseline"]
    with pytest.raises(TimeoutError):
        await load_arm(client, entries, journal, plan.schema_path)
    restored = Journal(journal.path, {})
    assert restored.data["create_dispatched"] and not restored.data["created"]
    with pytest.raises(RuntimeError, match="Unknown create"):
        await load_arm(client, entries, restored, plan.schema_path)
    client.create_connection.assert_awaited_once()


@pytest.mark.parametrize("change", ["id", "duplicate", "oversized", "content_type"])
def test_invalid_item_rejected_before_any_upload(plan, change):
    entries = json.loads(plan.baseline.manifest.read_bytes())
    if change == "id":
        entries[0]["id"] += "/escape"
    elif change == "duplicate":
        entries += deepcopy(entries)
        plan.baseline.count = 2
    elif change == "oversized":
        entries[0]["payload"]["content"]["value"] = "x" * 8001
    else:
        entries[0]["payload"]["content"]["type"] = "html"
    plan.baseline.manifest.write_text(json.dumps(entries))
    plan.baseline.manifest_sha256 = digest(plan.baseline.manifest)
    with pytest.raises(ValueError):
        validate_plan(plan)
