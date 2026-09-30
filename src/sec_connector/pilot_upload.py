"""Explicit, frozen-manifest pilot loading; never discovery, pruning, or deletion."""

import argparse
import asyncio
import base64
from contextlib import AsyncExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from .config import AppConfig, AzureConfig, GRAPH_MAX_ITEM_BYTES
from .graph_client import GRAPH_BASE_URL, GraphClient, HTTPResult
from .payloads import payload_hash, serialize_item


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(StrictModel):
    cik: str = Field(pattern=r"^\d{10}$")
    accession: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    filename: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.htm$")
    sequence: int = Field(gt=0)
    document_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    form: str
    filing_date: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Arm(StrictModel):
    connection_id: str = Field(pattern=r"^[A-Za-z0-9]{3,32}$")
    manifest: Path
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    count: int = Field(gt=0)


class PilotPlan(StrictModel):
    tenant_id: str
    source: Path
    schema_path: Path
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    forbidden_connection: str
    scope: Scope
    baseline: Arm
    candidate: Arm


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_plan(plan: PilotPlan) -> dict[str, list[dict]]:
    """Validate both complete manifests before authentication or any mutation."""
    if plan.baseline.connection_id == plan.candidate.connection_id:
        raise ValueError("Pilot arms must use distinct new destinations")
    if plan.forbidden_connection in {plan.baseline.connection_id, plan.candidate.connection_id}:
        raise ValueError("Historical destination is forbidden")
    if digest(plan.source) != plan.scope.source_sha256:
        raise ValueError("Source provenance hash mismatch")
    if digest(plan.schema_path) != plan.schema_sha256:
        raise ValueError("Schema hash mismatch")
    GraphClient.load_desired_schema(plan.schema_path)
    scope = plan.scope
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{scope.cik}/"
        f"{scope.accession.replace('-', '')}/{scope.filename}"
    )
    if hashlib.sha256(url.encode()).hexdigest() != scope.document_id:
        raise ValueError("DocumentId does not match the exact source URL")
    expected = {
        "CIK": scope.cik, "AccessionNumber": scope.accession,
        "DocumentName": scope.filename, "Sequence": scope.sequence,
        "DocumentId": scope.document_id, "Url": url, "Form": scope.form,
        "DocumentType": scope.form, "FilingDate": scope.filing_date,
    }
    prefix = f"{scope.cik}-{scope.accession.replace('-', '')}-{scope.sequence}-"
    result = {}
    for name in ("baseline", "candidate"):
        arm = getattr(plan, name)
        if digest(arm.manifest) != arm.manifest_sha256:
            raise ValueError(f"{name}: frozen manifest hash mismatch")
        entries = json.loads(arm.manifest.read_bytes())
        if not isinstance(entries, list) or len(entries) != arm.count:
            raise ValueError(f"{name}: unexpected item count")
        ids, ordinals = set(), []
        for entry in entries:
            item_id, payload = entry["id"], entry["payload"]
            if (not re.fullmatch(re.escape(prefix) + r"[1-9]\d*(?:-[1-9]\d*)?", item_id)
                    or payload["id"] != item_id or item_id in ids):
                raise ValueError(f"{name}: invalid or duplicate exact-document item ID")
            ids.add(item_id)
            props = payload["properties"]
            if any(props.get(key) != value for key, value in expected.items()):
                raise ValueError(f"{name}: item escapes approved document scope")
            if payload["acl"] != [{"type": "everyone", "value": "everyone", "accessType": "grant"}]:
                raise ValueError(f"{name}: ACL differs from frozen connector policy")
            if (payload["content"].get("type") != "text"
                    or not isinstance(payload["content"].get("value"), str)
                    or not payload["content"]["value"]
                    or len(payload["content"]["value"]) > 8000
                    or len(serialize_item(payload)) > GRAPH_MAX_ITEM_BYTES):
                raise ValueError(f"{name}: invalid or oversized request")
            ordinals.append(props.get("ChunkOrdinal"))
        if ordinals != list(range(1, arm.count + 1)):
            raise ValueError(f"{name}: incomplete or unordered chunk ordinals")
        result[name] = entries
    return result


def validate_token_identity(token: str, tenant_id: str, client_id: str) -> None:
    """Check identity claims of the token obtained directly from MSAL; never log it."""
    segment = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    if (claims.get("tid", "").lower() != tenant_id.lower()
            or claims.get("appid", claims.get("azp", "")).lower() != client_id.lower()
            or claims.get("aud") not in {"https://graph.microsoft.com", "00000003-0000-0000-c000-000000000000"}):
        raise ValueError("Authenticated token identity does not match approved tenant/app/Graph")
    roles = set(claims.get("roles", []))
    for resource in ("ExternalConnection", "ExternalItem"):
        if not roles.intersection({f"{resource}.ReadWrite.OwnedBy", f"{resource}.ReadWrite.All"}):
            raise ValueError(f"Missing consented {resource} write permission")


class PilotGraphClient(GraphClient):
    """Do not retry or adopt create/schema mutations with uncertain acknowledgments."""

    async def _request_result(self, method, url, json_data=None, use_beta=False, body=None):
        if method not in {"GET", "PUT", "POST", "PATCH"}:
            raise ValueError("Pilot transport forbids deletion and unrequested mutations")
        if method not in {"POST", "PATCH"}:
            return await super()._request_result(method, url, json_data, use_beta, body)
        allowed = {
            ("POST", "/external/connections"),
            ("PATCH", f"/external/connections/{self.config.azure.connection_id}/schema"),
        }
        if (method, url) not in allowed or use_beta or body is not None or self._session is None:
            raise ValueError("Unexpected pilot mutation")
        token = await self._get_token()
        async with self._session.request(
            method, GRAPH_BASE_URL + url, json=json_data, allow_redirects=False,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Prefer": "include-unknown-enum-members"},
        ) as response:
            response.raise_for_status()
            if not 200 <= response.status < 300:
                raise RuntimeError("Unexpected pilot mutation response")
            raw = await response.read()
            return HTTPResult(
                response.status, {key.lower(): value for key, value in response.headers.items()},
                json.loads(raw) if raw else {},
            )

    async def create_connection(self):
        # Deliberately bypass the normal client's 409 adoption behavior.
        return await self._request("POST", "/external/connections", json_data={
            "id": self.config.azure.connection_id,
            "name": self.config.azure.connection_name,
            "description": "Isolated single-document SEC evidence packaging A/B pilot",
        })


class Journal:
    def __init__(self, path: Path, binding: dict):
        self.path = path
        self.data = json.loads(path.read_bytes()) if path.exists() else {
            "binding": binding, "created": False, "create_dispatched": False,
            "schema_dispatched": False, "schema_complete": False,
            "acknowledged": {}, "read_back": {},
        }
        if self.data["binding"] != binding:
            raise ValueError("Pilot journal identity/provenance mismatch")
        self.save()

    def save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)


@contextmanager
def pilot_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pilot.lock"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink()


async def ensure_absent(client: PilotGraphClient) -> None:
    try:
        await client.get_connection()
    except aiohttp.ClientResponseError as exc:
        if exc.status == 404:
            return
        raise
    raise RuntimeError("Connection collision: refusing to adopt existing destination")


async def load_arm(client: PilotGraphClient, entries: list[dict], journal: Journal, schema_path: Path):
    data = journal.data
    if not data["created"]:
        if data["create_dispatched"]:
            raise RuntimeError("Unknown create acknowledgment; manual reconciliation required")
        await ensure_absent(client)
        data["create_dispatched"] = True
        journal.save()
        response = await client.create_connection()
        if response.get("id") != client.config.azure.connection_id:
            raise RuntimeError("Create acknowledgment identity mismatch")
        data["created"] = True
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        journal.save()
    remote = await client.get_connection()
    if remote.get("id") != client.config.azure.connection_id:
        raise RuntimeError("Connection readback identity mismatch")
    if not data["schema_complete"]:
        if not data["schema_dispatched"]:
            data["schema_dispatched"] = True
            journal.save()
            await client.register_schema(schema_path)
            data["schema_operation"] = client._schema_operation_url
            journal.save()
        operation = data.get("schema_operation")
        expected = f"{GRAPH_BASE_URL}/external/connections/{client.config.azure.connection_id}/operations/"
        if not operation or not operation.startswith(expected):
            raise RuntimeError("Missing or unexpected schema operation; do not resubmit PATCH")
        client._schema_operation_url = operation
        if not await client.wait_for_schema():
            raise RuntimeError("Schema pending: resume same journal without another PATCH")
        if not client.schemas_compatible(await client.get_schema_status(), client.load_desired_schema(schema_path)):
            raise RuntimeError("Persisted schema does not match the frozen schema")
        data["schema_complete"] = True
        journal.save()
    if not client.schemas_compatible(await client.get_schema_status(), client.load_desired_schema(schema_path)):
        raise RuntimeError("Schema changed since provisioning")
    for entry in entries:
        item_id, payload = entry["id"], entry["payload"]
        expected_hash = payload_hash(payload)
        if item_id in data["acknowledged"]:
            if data["acknowledged"][item_id] != expected_hash:
                raise ValueError("Acknowledged payload hash mismatch")
            continue
        await client.upload_payload(item_id, payload)
        data["acknowledged"][item_id] = expected_hash
        journal.save()
        if len(data["acknowledged"]) % 100 == 0:
            print(f"{client.config.azure.connection_id}: {len(data['acknowledged'])}/{len(entries)} PUTs acknowledged", flush=True)
    for entry in entries:
        item_id, payload = entry["id"], entry["payload"]
        if data["read_back"].get(item_id) == payload_hash(payload):
            continue
        actual = await client._request("GET", f"/external/connections/{client.config.azure.connection_id}/items/{item_id}")
        # Graph may add OData annotations; compare only every submitted field.
        for field in ("properties", "content"):
            if any(actual.get(field, {}).get(key) != value for key, value in payload[field].items()):
                raise RuntimeError(f"Persisted {field} differs for {item_id}")
        acl_keys = ("type", "value", "accessType")
        if [tuple(acl.get(key) for key in acl_keys) for acl in actual.get("acl", [])] != [
            tuple(acl.get(key) for key in acl_keys) for acl in payload["acl"]
        ]:
            raise RuntimeError(f"Persisted ACL differs for {item_id}")
        data["read_back"][item_id] = payload_hash(payload)
        journal.save()
    if set(data["acknowledged"]) != {e["id"] for e in entries} or set(data["read_back"]) != set(data["acknowledged"]):
        raise RuntimeError("Pilot acknowledgment/readback count mismatch")
    data["result"] = {"acknowledged": len(entries), "read_back": len(entries),
                      "search_readiness": "not established", "copilot_efficacy": "not evaluated"}
    journal.save()
    print(f"{client.config.azure.connection_id}: {json.dumps(data['result'])}", flush=True)


async def execute(plan: PilotPlan, state_dir: Path, entries: dict[str, list[dict]]):
    tenant = os.environ.get("AZURE_TENANT_ID", "")
    app = os.environ.get("AZURE_CLIENT_ID", "")
    secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    if tenant.lower() != plan.tenant_id.lower() or not app or not secret:
        raise ValueError("Approved tenant and populated app credentials required")
    with pilot_lock(state_dir):
        async with AsyncExitStack() as stack:
            prepared = []
            for name in ("baseline", "candidate"):
                arm = getattr(plan, name)
                binding = {
                    "tenant": tenant.lower(), "app": app, "connection": arm.connection_id,
                    "manifest_sha256": arm.manifest_sha256, "schema_sha256": plan.schema_sha256,
                    "scope": plan.scope.model_dump(), "count": arm.count,
                }
                journal = Journal(state_dir / f"{name}.json", binding)
                config = AppConfig(azure=AzureConfig(
                    tenant_id=tenant, client_id=app, client_secret=secret,
                    connection_id=arm.connection_id, connection_name=f"SEC evidence pilot {name}",
                ))
                client = await stack.enter_async_context(PilotGraphClient(config))
                validate_token_identity(await client._get_token(), tenant, app)
                if not journal.data["created"]:
                    if journal.data["create_dispatched"]:
                        raise RuntimeError("Unknown create acknowledgment; manual reconciliation required")
                    await ensure_absent(client)
                prepared.append((name, client, journal))
            for name, client, journal in prepared:
                await load_arm(client, entries[name], journal, plan.schema_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--execute", action="store_true", help="Create/load approved new pilot destinations")
    args = parser.parse_args()
    try:
        plan = PilotPlan.model_validate_json(args.plan.read_bytes())
        entries = validate_plan(plan)
        print("Frozen scope/provenance validated: " + ", ".join(f"{k}={len(v)}" for k, v in entries.items()), flush=True)
        if args.execute:
            if args.state_dir is None:
                raise ValueError("--execute requires a dedicated --state-dir")
            asyncio.run(execute(plan, args.state_dir, entries))
    except Exception as exc:
        # Do not expose token-bearing URLs or authentication error descriptions.
        print(f"Pilot stopped: {type(exc).__name__}; HTTP status={getattr(exc, 'status', 'n/a')}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
