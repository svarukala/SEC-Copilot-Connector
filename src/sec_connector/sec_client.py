"""SEC EDGAR API client for fetching filing metadata and documents."""

import asyncio
import re
import tempfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup

from .config import AppConfig
from .models import DocumentInfo, FilingMetadata
from .utils import RateLimiter, get_logger

logger = get_logger("sec_client")


class SECClient:
    """Client for interacting with SEC EDGAR API."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.rate_limiter = RateLimiter(config.sec.rate_limit)
        self._ticker_to_cik: dict[str, str] = {}
        self._cik_to_company: dict[str, str] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def headers(self) -> dict:
        """Return request headers with User-Agent."""
        return {
            "User-Agent": self.config.sec.user_agent,
            "Accept": "application/json",
        }

    async def __aenter__(self) -> "SECClient":
        """Create aiohttp session."""
        self._session = aiohttp.ClientSession(
            headers=self.headers, timeout=aiohttp.ClientTimeout(total=120, connect=30)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close aiohttp session."""
        if self._session:
            await self._session.close()

    async def _get(self, url: str) -> bytes:
        """Pace every network attempt, retrying only transient failures."""
        user_agent = self.config.sec.user_agent.strip()
        if (
            not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", user_agent)
            or "example.com" in user_agent.lower()
            or "your-email" in user_agent.lower()
            or "${" in user_agent
            or "\r" in user_agent
            or "\n" in user_agent
        ):
            raise ValueError("Set SEC_USER_AGENT to an identifying User-Agent with a real contact email")
        if not self._session:
            raise RuntimeError("Client not initialized. Use async with context manager.")

        for attempt in range(5):
            await self.rate_limiter.acquire()
            retry_after = None
            try:
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=120, connect=30)
                ) as response:
                    retry_after = response.headers.get("Retry-After")
                    response.raise_for_status()
                    return await response.read()
            except aiohttp.ClientResponseError as exc:
                if exc.status != 429 and not 500 <= exc.status <= 599:
                    raise
                if attempt == 4:
                    raise
            except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, asyncio.TimeoutError):
                if attempt == 4:
                    raise

            delay = min(60.0, 4.0 * 2 ** attempt)
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(retry_after)
                        if retry_at.tzinfo is None:
                            retry_at = retry_at.replace(tzinfo=timezone.utc)
                        delay = max(delay, (retry_at - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        pass
            logger.warning("Transient SEC request failure; retrying in %.1fs", delay)
            await asyncio.sleep(delay)
        raise RuntimeError("SEC request attempts exhausted")

    async def _get_json(self, url: str) -> dict:
        """Make a rate-limited GET request and return JSON."""
        data = await self._get(url)
        import json
        return json.loads(data)

    async def load_ticker_mapping(self) -> None:
        """Load ticker to CIK mapping from SEC."""
        url = f"{self.config.sec.base_url}/files/company_tickers.json"
        logger.info(f"Loading ticker mapping from {url}")

        data = await self._get_json(url)

        for entry in data.values():
            ticker = entry["ticker"].upper()
            cik = str(entry["cik_str"]).zfill(10)
            company = entry["title"]
            self._ticker_to_cik[ticker] = cik
            self._cik_to_company[cik] = company

        logger.info(f"Loaded {len(self._ticker_to_cik)} ticker mappings")

    def get_cik(self, ticker: str) -> Optional[str]:
        """Get CIK for a ticker symbol."""
        return self._ticker_to_cik.get(ticker.upper())

    def get_company_name(self, cik: str) -> str:
        """Get company name for a CIK."""
        return self._cik_to_company.get(cik, "Unknown Company")

    async def get_filings(
        self,
        ticker: str,
        forms: Optional[list[str]] = None,
        max_filings: Optional[int] = None,
    ) -> list[FilingMetadata]:
        """Get filing metadata for a ticker.

        Args:
            ticker: Stock ticker symbol
            forms: List of form types to filter (e.g., ["10-K", "10-Q"])
            max_filings: Maximum number of filings to return

        Returns:
            List of FilingMetadata objects
        """
        if max_filings is not None:
            if max_filings < 0:
                raise ValueError("max_filings must not be negative")
            if max_filings == 0:
                return []
        if not self._ticker_to_cik:
            await self.load_ticker_mapping()

        cik = self.get_cik(ticker)
        if not cik:
            logger.error(f"Unknown ticker: {ticker}")
            return []

        url = f"{self.config.sec.data_url}/submissions/CIK{cik}.json"
        logger.info(f"Fetching submissions for {ticker} (CIK: {cik})")

        data = await self._get_json(url)
        company_name = data.get("name", self.get_company_name(cik))

        inventory = data.get("filings")
        if not isinstance(inventory, dict) or not isinstance(inventory.get("recent"), dict):
            raise ValueError("Malformed SEC submissions: missing filings.recent")
        batches = [inventory["recent"]]
        if self.config.filings.include_history:
            references = inventory.get("files", [])
            if not isinstance(references, list):
                raise ValueError("Malformed SEC historical filing references")
            seen_references = set()
            for reference in references:
                if not isinstance(reference, dict):
                    raise ValueError("Malformed SEC historical filing reference")
                name = self._safe_filename(reference.get("name", ""))
                if not name.lower().endswith(".json"):
                    raise ValueError("Historical filing reference must be JSON")
                if name not in seen_references:
                    batches.append(await self._get_json(
                        f"{self.config.sec.data_url}/submissions/{quote(name)}"
                    ))
                    seen_references.add(name)

        selected_forms = {
            form.strip().upper().removesuffix("/A")
            for form in (self.config.filings.forms if forms is None else forms)
        }
        filings_by_id = {}
        required = ("accessionNumber", "form", "filingDate", "primaryDocument")
        optional = ("reportDate", "acceptanceDateTime", "fileNumber")
        for batch in batches:
            if not isinstance(batch, dict):
                raise ValueError("Malformed SEC filing arrays")
            if any(not isinstance(batch.get(key), list) for key in required):
                raise ValueError("Malformed SEC filing arrays: required columns missing")
            count = len(batch["accessionNumber"])
            if any(len(batch[key]) != count for key in required) or any(
                key in batch and (not isinstance(batch[key], list) or len(batch[key]) != count)
                for key in optional
            ):
                raise ValueError("Malformed SEC filing arrays: column lengths differ")
            for i in range(count):
                accession, form, date_str, primary_doc = (batch[key][i] for key in required)
                if not all(isinstance(value, str) and value.strip()
                           for value in (accession, form, date_str)):
                    raise ValueError("Malformed SEC filing row")
                form = form.strip().upper()
                filing_date = datetime.strptime(date_str, "%Y-%m-%d")
                if form.removesuffix("/A") not in selected_forms:
                    continue
                if form.endswith("/A") and not self.config.filings.include_amendments:
                    continue
                if self.config.filings.start_date and filing_date.date() < self.config.filings.start_date:
                    continue
                if self.config.filings.end_date and filing_date.date() > self.config.filings.end_date:
                    continue
                report = batch["reportDate"][i] if "reportDate" in batch else None
                accepted = batch["acceptanceDateTime"][i] if "acceptanceDateTime" in batch else None
                acceptance = datetime.fromisoformat(accepted.replace("Z", "+00:00")) if accepted else None
                if acceptance is not None and acceptance.tzinfo is None:
                    acceptance = acceptance.replace(tzinfo=ZoneInfo("America/New_York"))
                filing = FilingMetadata(
                    cik=cik, accession_number=accession, form=form,
                    filing_date=filing_date, company_name=company_name,
                    ticker=ticker.upper(), primary_document=primary_doc,
                    file_number=(batch["fileNumber"][i] or None) if "fileNumber" in batch else None,
                    report_period_end=datetime.strptime(report, "%Y-%m-%d") if report else None,
                    acceptance_datetime=acceptance,
                )
                filings_by_id.setdefault((cik, accession.replace("-", "")), filing)
        filings = sorted(
            filings_by_id.values(),
            key=lambda filing: (filing.filing_date, filing.accession_no_dashes),
            reverse=True,
        )
        if max_filings is not None:
            filings = filings[:max_filings]

        logger.info(f"Found {len(filings)} filings for {ticker}")
        return filings

    async def get_filing_documents(
        self, filing: FilingMetadata
    ) -> list[DocumentInfo]:
        """Get list of documents in a filing.

        Args:
            filing: Filing metadata

        Returns:
            List of DocumentInfo objects for processable documents
        """
        self._validate_filing_path(filing)
        primary = self._safe_filename(filing.primary_document or "")
        url = self._archive_url(filing, f"{filing.accession_number}-index.html")
        soup = BeautifulSoup(await self._get(url), "lxml")
        table = soup.find("table", summary=re.compile(r"^Document Format Files$", re.I))
        if table is None:
            raise ValueError("SEC filing detail has no Document Format Files table")
        documents = {}
        sequences = {}
        primary_found = False
        for row in table.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            if len(cells) < 5:
                raise ValueError("Malformed SEC document table row")
            sequence, description, document_cell, doc_type, size = cells[:5]
            doc_type = doc_type.get_text(" ", strip=True).upper()
            is_exhibit = self.config.filings.include_exhibits and any(
                doc_type == allowed.upper() or doc_type.startswith(allowed.upper() + ".")
                for allowed in self.config.filings.exhibit_types
            )
            if doc_type != filing.form.upper() and not is_exhibit:
                continue
            link = document_cell.find("a", href=True)
            if link is None:
                continue
            filename = self._document_link_filename(filing, url, link["href"])
            is_primary = filename == primary and doc_type == filing.form.upper()
            if not is_primary and not is_exhibit:
                continue
            if filename.lower() in {
                f"{filing.accession_number}.txt", f"{filing.accession_no_dashes}.txt"
            }:
                logger.warning("Excluded complete-submission aggregate %s", filename)
                continue
            if not filename.lower().endswith((".htm", ".html", ".txt")):
                logger.warning("Excluded unsupported binary document %s (%s)", filename, doc_type)
                if is_primary:
                    raise ValueError(f"Unsupported primary document: {filename}")
                continue
            sequence_text = sequence.get_text(strip=True)
            if not sequence_text.isdigit() or int(sequence_text) <= 0:
                raise ValueError(f"Invalid document sequence for {filename}")
            size_text = size.get_text(strip=True).replace(",", "")
            doc = DocumentInfo(
                sequence=int(sequence_text), filename=filename, document_type=doc_type,
                description=description.get_text(" ", strip=True),
                size=int(size_text) if size_text else None,
            )
            if filename in documents:
                if documents[filename] != doc:
                    raise ValueError(f"Conflicting document metadata for {filename}")
                continue
            if doc.sequence in sequences:
                raise ValueError(f"Duplicate SEC document sequence {doc.sequence}")
            documents[filename] = doc
            sequences[doc.sequence] = filename
            primary_found |= is_primary
        if not primary_found:
            raise ValueError(f"Expected primary document missing from SEC detail: {primary}")
        return sorted(documents.values(), key=lambda doc: (doc.filename != primary, doc.sequence))

    @staticmethod
    def _safe_filename(filename: str) -> str:
        if (
            not isinstance(filename, str) or not filename or filename in {".", ".."}
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)
            or filename != filename.strip() or filename.endswith(".")
            or unquote(filename) != filename
            or filename.split(".")[0].upper() in {
                "CON", "PRN", "AUX", "NUL",
                *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
            }
        ):
            raise ValueError(f"Unsafe SEC filename: {filename!r}")
        return filename

    @staticmethod
    def _validate_filing_path(filing: FilingMetadata) -> None:
        if not re.fullmatch(r"[0-9]+", filing.cik) or not re.fullmatch(
            r"[0-9]+(?:-[0-9]+)*", filing.accession_number
        ):
            raise ValueError("Unsafe SEC filing cache path")

    def _archive_url(self, filing: FilingMetadata, filename: str) -> str:
        return (
            f"{self.config.sec.base_url}/Archives/edgar/data/"
            f"{filing.cik}/{filing.accession_no_dashes}/{quote(filename)}"
        )

    def _document_link_filename(self, filing: FilingMetadata, index_url: str, href: str) -> str:
        parsed = urlsplit(urljoin(index_url, href))
        if parsed.netloc != urlsplit(self.config.sec.base_url).netloc:
            raise ValueError("SEC document link points outside the configured SEC host")
        if "doc" in parse_qs(parsed.query):
            parsed = urlsplit(parse_qs(parsed.query)["doc"][0])
            if parsed.netloc:
                raise ValueError("Unsafe SEC inline viewer document link")
        path = unquote(parsed.path)
        match = re.fullmatch(r"/Archives/edgar/data/([0-9]+)/([0-9]+)/([^/]+)", path)
        if not match or int(match[1]) != int(filing.cik) or match[2] != filing.accession_no_dashes:
            raise ValueError("SEC document link points outside this filing")
        return self._safe_filename(match[3])

    async def download_document(
        self,
        filing: FilingMetadata,
        document: DocumentInfo,
        download_dir: Path,
        refresh: bool = False,
    ) -> Path:
        """Download a document to local storage.

        Args:
            filing: Filing metadata
            document: Document info
            download_dir: Base download directory

        Returns:
            Path to downloaded file
        """
        self._validate_filing_path(filing)
        self._safe_filename(document.filename)
        root = download_dir.resolve()
        filing_dir = root / filing.cik / filing.accession_no_dashes
        file_path = filing_dir / document.filename
        if not file_path.resolve().is_relative_to(root):
            raise ValueError("SEC document cache path escapes download directory")
        filing_dir.mkdir(parents=True, exist_ok=True)

        if not refresh and file_path.exists() and file_path.stat().st_size > 0 and (
            document.size is None or file_path.stat().st_size == document.size
        ):
            logger.debug(f"Document already downloaded: {file_path}")
            return file_path

        url = self._archive_url(filing, document.filename)

        logger.debug(f"Downloading {url}")
        content = await self._get(url)

        if not content:
            raise ValueError(f"Downloaded document is empty: {document.filename}")
        if document.size is not None and len(content) != document.size:
            raise ValueError(f"Downloaded size does not match the inventory: {document.filename}")
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=filing_dir, suffix=".part", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
            temporary_path.replace(file_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        logger.info(f"Downloaded {document.filename} ({len(content)} bytes)")

        return file_path

    async def download_filing(
        self,
        filing: FilingMetadata,
        download_dir: Path,
        max_documents: Optional[int] = None,
    ) -> list[tuple[DocumentInfo, Path]]:
        """Download all documents for a filing.

        Args:
            filing: Filing metadata
            download_dir: Base download directory
            max_documents: Maximum documents to download

        Returns:
            List of (DocumentInfo, Path) tuples
        """
        documents = await self.get_filing_documents(filing)

        if max_documents is not None:
            if max_documents <= 0:
                raise ValueError("max_documents must be positive")
            documents = documents[:max_documents]

        if not documents:
            raise ValueError(f"No processable documents found for {filing.accession_number}")
        semaphore = asyncio.Semaphore(self.config.processing.concurrent_downloads)

        async def download(doc):
            async with semaphore:
                return doc, await self.download_document(filing, doc, download_dir)

        tasks = [asyncio.create_task(download(doc)) for doc in documents]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
