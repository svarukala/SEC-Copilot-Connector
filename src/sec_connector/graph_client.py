"""Microsoft Graph API client for Copilot connector operations."""

import asyncio
import json
import hashlib
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from importlib.resources import files
from typing import Optional
from urllib.parse import urljoin, urlsplit

import aiohttp
from msal import ConfidentialClientApplication

from .config import GRAPH_MAX_ITEM_BYTES, AppConfig
from .models import ContentChunk, GraphExternalItem
from .payloads import serialize_item
from .utils import get_logger

logger = get_logger("graph_client")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_BETA_URL = "https://graph.microsoft.com/beta"


@dataclass(frozen=True)
class HTTPResult:
    """Response metadata needed for asynchronous Graph operations."""

    status: int
    headers: dict[str, str]
    data: dict


class GraphClient:
    """Client for Microsoft Graph API operations."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._token: Optional[str] = None
        self._token_expires: float = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._schema_operation_url: Optional[str] = None

        self._msal_app: Optional[ConfidentialClientApplication] = None
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "GraphClient":
        """Create aiohttp session."""
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close aiohttp session."""
        if self._session:
            await self._session.close()

    async def _get_token(self) -> str:
        """Get or refresh access token."""
        async with self._token_lock:
            return await self._refresh_token()

    async def _refresh_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        def acquire():
            if self._msal_app is None:
                self._msal_app = ConfidentialClientApplication(
                    client_id=self.config.azure.client_id,
                    client_credential=self.config.azure.client_secret,
                    authority=f"https://login.microsoftonline.com/{self.config.azure.tenant_id}",
                )
            return self._msal_app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

        result = await asyncio.to_thread(acquire)

        if "access_token" in result:
            self._token = result["access_token"]
            self._token_expires = time.time() + result.get("expires_in", 3600)
            return self._token
        else:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Failed to acquire token: {error}")

    async def _request(
        self,
        method: str,
        url: str,
        json_data: Optional[dict] = None,
        use_beta: bool = False,
        body: Optional[bytes] = None,
    ) -> dict:
        """Make an authenticated request, preserving the dict-returning API."""
        result = await self._request_result(method, url, json_data, use_beta, body)
        return result.data

    @staticmethod
    def _retry_delay(headers: dict, fallback: float) -> float:
        value = headers.get("retry-after")
        if value is None:
            return fallback
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return fallback

    async def _request_result(
        self,
        method: str,
        url: str,
        json_data: Optional[dict] = None,
        use_beta: bool = False,
        body: Optional[bytes] = None,
    ) -> HTTPResult:
        """Retry only transient failures, retaining headers and empty responses."""
        if not self._session:
            raise RuntimeError("Client not initialized. Use async with context manager.")
        if json_data is not None and body is not None:
            raise ValueError("Specify either json_data or body, not both")

        token = await self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "include-unknown-enum-members",
        }

        base = GRAPH_BETA_URL if use_beta else GRAPH_BASE_URL
        full_url = url if urlsplit(url).scheme or url.startswith("//") else f"{base}{url}"
        if (urlsplit(full_url).scheme, urlsplit(full_url).netloc) != (
            "https", urlsplit(GRAPH_BASE_URL).netloc
        ):
            raise ValueError("Graph operation URL must use the Microsoft Graph HTTPS origin")
        request_data = {"data": body} if body is not None else {"json": json_data}
        for attempt in range(5):
            delay = min(4 * 2**attempt, 60)
            try:
                async with self._session.request(
                    method, full_url, headers=headers, allow_redirects=False, **request_data
                ) as response:
                    response_headers = {key.lower(): value for key, value in response.headers.items()}
                    if response.status == 429 or 500 <= response.status < 600:
                        if attempt == 4:
                            response.raise_for_status()
                        delay = self._retry_delay(response_headers, delay)
                    else:
                        try:
                            response.raise_for_status()
                        except aiohttp.ClientResponseError as exc:
                            details = (await response.read()).decode("utf-8", errors="replace")
                            if details:
                                exc.message = f"{exc.message}: {details[:4000]}"
                            raise
                        if 300 <= response.status < 400:
                            raise RuntimeError("Unexpected redirect from Microsoft Graph")
                        raw = await response.read()
                        data = json.loads(raw) if raw else {}
                        if not isinstance(data, dict):
                            raise ValueError("Expected a Graph JSON object response")
                        return HTTPResult(response.status, response_headers, data)
            except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, asyncio.TimeoutError):
                if attempt == 4:
                    raise
            logger.warning(f"Transient Graph request failure; retrying in {delay}s")
            await asyncio.sleep(delay)
        raise RuntimeError("Graph request retry limit exceeded")

    async def create_connection(self) -> dict:
        """Create an external connection for the connector."""
        connection_id = self.config.azure.connection_id

        connection_data = {
            "id": connection_id,
            "name": self.config.azure.connection_name,
            "description": self.config.azure.connection_description,
        }

        logger.info(f"Creating connection: {connection_id}")

        try:
            result = await self._request(
                "POST",
                "/external/connections",
                json_data=connection_data,
            )
            logger.info(f"Connection created: {connection_id}")
            return result
        except aiohttp.ClientResponseError as e:
            if e.status == 409:
                logger.info(f"Connection already exists: {connection_id}")
                return await self.get_connection()
            raise

    async def get_connection(self) -> dict:
        """Get the external connection."""
        connection_id = self.config.azure.connection_id
        return await self._request("GET", f"/external/connections/{connection_id}")

    async def delete_connection(self) -> None:
        """Delete the external connection."""
        connection_id = self.config.azure.connection_id
        logger.info(f"Deleting connection: {connection_id}")
        await self._request("DELETE", f"/external/connections/{connection_id}")
        logger.info(f"Connection deleted: {connection_id}")

    @staticmethod
    def load_desired_schema(schema_path: Optional[Path] = None) -> dict:
        """Load the local schema used to verify and provision the connection."""
        if schema_path is None:
            packaged = files("sec_connector").joinpath("resources", "schema.json")
            schema_path = packaged if packaged.is_file() else (
                Path(__file__).parent.parent.parent / "config" / "schema.json"
            )
        with schema_path.open(encoding="utf-8") as f:
            schema = json.load(f)
        if any("isExactMatchRequired" in prop for prop in schema.get("properties", [])):
            raise ValueError("isExactMatchRequired is beta-only; this connector provisions a v1.0 schema")
        return schema

    @staticmethod
    def schemas_compatible(remote: dict, desired: dict) -> bool:
        """Compare desired definitions, ignoring order and Graph metadata.

        Additional remote properties are harmless; every desired property must
        have the requested type, capabilities, labels and aliases.
        """
        if remote.get("baseType", "").lower() != desired.get("baseType", "").lower():
            return False
        remote_properties = {prop["name"]: prop for prop in remote.get("properties", [])}
        flags = ("isSearchable", "isQueryable", "isRetrievable", "isRefinable", "isExactMatchRequired")
        for prop in desired.get("properties", []):
            actual = remote_properties.get(prop["name"])
            if actual is None or actual.get("type", "").lower() != prop.get("type", "").lower():
                return False
            if any(actual.get(flag, False) != prop.get(flag, False) for flag in flags):
                return False
            if any(set(actual.get(key) or []) != set(prop.get(key) or []) for key in ("labels", "aliases")):
                return False
        return True

    load_schema = load_desired_schema
    schema_matches = schemas_compatible

    async def register_schema(self, schema_path: Optional[Path] = None) -> dict:
        """Submit the v1.0 schema PATCH and retain its operation Location."""
        connection_id = self.config.azure.connection_id
        schema = self.load_desired_schema(schema_path)
        logger.info(f"Registering schema for connection: {connection_id}")
        self._schema_operation_url = None
        path = f"/external/connections/{connection_id}/schema"
        result = await self._request_result("PATCH", path, json_data=schema)
        location = result.headers.get("location")
        if result.status == 202 and not location:
            raise RuntimeError("Schema registration returned 202 without an operation Location")
        if location:
            self._schema_operation_url = urljoin(f"{GRAPH_BASE_URL}{path}", location)
        logger.info("Schema registration initiated (may take 5-15 minutes)")
        return result.data

    async def get_schema_status(self) -> dict:
        """Get the actual remote schema definition (not operation status)."""
        connection_id = self.config.azure.connection_id
        return await self._request(
            "GET",
            f"/external/connections/{connection_id}/schema",
        )

    async def wait_for_schema(self, timeout: float = 900) -> bool:
        """Poll the retained operation until completed, failed or deadline.

        Failure raises with Graph's error details; expiration returns False.
        Schema properties alone never establish operation completion.
        """
        if not self._schema_operation_url:
            raise RuntimeError("No schema operation Location; call register_schema first")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = await asyncio.wait_for(
                    self._request_result("GET", self._schema_operation_url),
                    timeout=max(0, deadline - time.monotonic()),
                )
            except asyncio.TimeoutError:
                break
            state = result.data.get("status", "").lower()
            if state == "completed":
                return True
            if state == "failed":
                raise RuntimeError(f"Schema registration failed: {result.data.get('error', result.data)}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(self._retry_delay(result.headers, 10), remaining))
        logger.error("Schema registration timeout")
        return False

    def _chunk_to_external_item(self, chunk: ContentChunk) -> GraphExternalItem:
        """Convert a ContentChunk to a GraphExternalItem."""
        filing = chunk.filing
        filing_date = filing.filing_date
        if filing_date.tzinfo is None:
            filing_date = filing_date.replace(tzinfo=timezone.utc)

        properties = {
            "Title": f"{chunk.title} [{filing.ticker}] - {chunk.document.filename}",
            "Company": filing.company_name,
            "Ticker": filing.ticker,
            "Form": filing.form,
            "FilingDate": filing_date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "Description": chunk.document.description or f"{filing.form} filing for {filing.company_name}",
            "Url": filing.document_url(chunk.document.filename),
            "CIK": filing.cik,
            "AccessionNumber": filing.accession_number,
            "Sequence": chunk.document.sequence,
            "Page": chunk.page_number,
            "IconUrl": self.config.azure.icon_url,
            "FilingUrl": filing.filing_url,
            "DocumentName": chunk.document.filename,
            "FileExtension": Path(chunk.document.filename).suffix.lstrip(".").lower(),
            "DocumentType": chunk.document.document_type,
            "DocumentId": hashlib.sha256(
                filing.document_url(chunk.document.filename).encode("utf-8")
            ).hexdigest(),
            "ChunkOrdinal": chunk.chunk_ordinal,
            "IsAmendment": filing.is_amendment,
        }
        if chunk.section_title:
            properties["SectionTitle"] = chunk.section_title
        if filing.report_period_end:
            properties["ReportPeriodEnd"] = filing.report_period_end.strftime("%Y-%m-%dT00:00:00Z")
        if filing.acceptance_datetime:
            if filing.acceptance_datetime.tzinfo is None:
                raise ValueError("SEC acceptance_datetime must include its source timezone")
            properties["AcceptanceDateTime"] = filing.acceptance_datetime.astimezone(
                timezone.utc
            ).isoformat().replace("+00:00", "Z")

        content = {
            "type": "text",
            "value": chunk.content,
        }

        return GraphExternalItem(
            id=chunk.graph_item_id,
            properties=properties,
            content=content,
        )

    def build_payload(self, chunk: ContentChunk, icon_url: Optional[str] = None) -> dict:
        """Build the Graph API payload dict for a chunk.

        Args:
            chunk: Content chunk

        Returns:
            Payload dict matching what gets sent to Graph API
        """
        item = self._chunk_to_external_item(chunk)
        if icon_url is not None:
            item.properties["IconUrl"] = icon_url
        return {
            "id": item.id,
            "properties": item.properties,
            "content": item.content,
            "acl": item.acl,
        }

    async def upload_item(self, chunk: ContentChunk) -> dict:
        """Upload a single external item.

        Args:
            chunk: Content chunk to upload

        Returns:
            Upload result
        """
        return await self.upload_payload(chunk.graph_item_id, self.build_payload(chunk))

    async def upload_payload(self, item_id: str, payload: dict) -> dict:
        """Replay a saved item using exactly the bytes checked against limits."""
        connection_id = self.config.azure.connection_id
        body = serialize_item(payload)
        limit = min(self.config.chunking.max_item_bytes, GRAPH_MAX_ITEM_BYTES)
        if len(body) > limit:
            raise ValueError(
                f"External item {item_id} request body is {len(body)} bytes; limit is {limit} bytes"
            )
        result = await self._request(
            "PUT",
            f"/external/connections/{connection_id}/items/{item_id}",
            body=body,
        )
        logger.debug(f"Uploaded item: {item_id}")
        return result

    async def upload_items_batch(
        self,
        chunks: list[ContentChunk],
    ) -> tuple[list[str], list[str]]:
        """Upload multiple items.

        These are bounded individual PUT requests, not a Graph JSON batch.

        Args:
            chunks: List of content chunks to upload

        Returns:
            Tuple of (successful_ids, failed_ids)
        """
        successful = []
        failed = []

        semaphore = asyncio.Semaphore(5)

        async def upload_one(chunk: ContentChunk) -> bool:
            async with semaphore:
                try:
                    await self.upload_item(chunk)
                    return True
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
                    logger.error(f"Failed to upload {chunk.chunk_id}: {e}")
                    return False

        tasks = [upload_one(chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks)

        for chunk, success in zip(chunks, results):
            if success:
                successful.append(chunk.chunk_id)
            else:
                failed.append(chunk.chunk_id)

        logger.info(f"Batch upload: {len(successful)} succeeded, {len(failed)} failed")
        return successful, failed

    async def delete_item(self, item_id: str) -> None:
        """Delete an external item."""
        connection_id = self.config.azure.connection_id
        await self._request(
            "DELETE",
            f"/external/connections/{connection_id}/items/{item_id}",
        )
        logger.debug(f"Deleted item: {item_id}")

    async def get_connection_quota(self) -> dict:
        """Get connection quota information."""
        connection_id = self.config.azure.connection_id
        return await self._request(
            "GET",
            f"/external/connections/{connection_id}/quota",
        )
