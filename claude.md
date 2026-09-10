# SEC Copilot Connector - Implementation Plan

## Overview
Python-based Microsoft Copilot Connector to import SEC EDGAR filings (10-K, 10-Q, DEF 14A, 8-K) for semantic indexing and LLM reasoning in Microsoft 365.

## Project Structure
```
SEC-Copilot-Connector\
├── pyproject.toml              # Dependencies and project config
├── config/
│   ├── config.yaml             # Main configuration
│   └── schema.json             # Graph connector schema
├── src/sec_connector/
│   ├── __init__.py
│   ├── __main__.py             # Entry point
│   ├── cli.py                  # Click-based CLI
│   ├── config.py               # Config loading
│   ├── models.py               # Pydantic data models
│   ├── sec_client.py           # SEC EDGAR API client
│   ├── parser.py               # SGML/HTML parsing & markdown conversion
│   ├── chunker.py              # Document chunking strategies
│   ├── graph_client.py         # Microsoft Graph API client
│   ├── state_manager.py        # SQLite-based state persistence
│   ├── pipeline.py             # Main orchestration
│   └── utils.py                # Retry, logging utilities
├── data/                       # Runtime data (gitignored)
│   ├── downloads/              # Cached SEC filings
│   ├── payloads/               # Saved upload payloads (--save-payloads)
│   ├── state.<destination>.db  # Tenant/connection-scoped processing state
│   └── logs/                   # Log files
└── tests/
```

## Key Components

### 1. SEC EDGAR Client (`sec_client.py`)
- Ticker-to-CIK mapping via `sec.gov/files/company_tickers.json`
- Fetch recent and historical submissions, including amendments and configured date bounds
- **Download raw filings to `data/downloads/{cik}/{accession}/`**
- Refresh source bytes by default; cache parsed payloads by source and configuration fingerprint
- Shared request/retry pacing (at most 10 req/sec per client)

### Processing Pipeline
```
1. DISCOVER  → Fetch filing metadata from SEC API
2. DOWNLOAD  → Save raw .txt/.htm files to data/downloads/ (cached)
3. PARSE     → Extract content from disk, convert to Markdown
4. CHUNK     → Split into LLM-friendly segments
5. UPLOAD    → Bounded individual PUTs for new/changed payloads
6. RECONCILE → Delete stale tracked items only after complete desired delivery
```
SQLite stores the discovered inventory, document outcomes, captured chunking/OCR
settings, and exact desired upload payloads. Resume retries unprepared documents
and replays prepared payloads without reparsing them.

Increment `pipeline.PROCESSING_VERSION` when parser, chunker, or payload
transformation semantics change. Completed filings then invalidate their parse
cache. Ordinary resume keeps already prepared payloads replayable. To rebuild
in-flight filings after an upgrade, stop the writer and use
`ingest -t TICKER --reprocess` with the intended date scope. This explicitly
replaces captured processing settings while preserving acknowledged and
potentially delivered old IDs for upload-before-delete reconciliation.

### 2. Document Parser (`parser.py`)
- Parse SGML structure (`<DOCUMENT>`, `<TEXT>`, headers)
- Extract metadata (company, form, date, accession number)
- Span-aware financial tables, hidden inline-XBRL removal, and literal-text preservation
- Collapse visual columns only when they share source cells across populated rows;
  independent equal financial values remain separate. Body colspans use
  `[merged with column N]` within the same row instead of repeating disclosures.
- Infer short period headers without promoting year-containing narrative rows.
- Filter by file type (.htm, .txt only)

### 3. Content Chunker (`chunker.py`)
- **Max item size**: 30 MiB (31,457,280 bytes), enforced on the serialized Graph request
- Page-based splitting (primary) using `<PAGE>` markers
- Section header splitting (secondary)
- Size-based fallback (3000-4000 chars target, well below the request ceiling)
- 200-char overlap for context continuity
- Validation: bounded UTF-8 splitting and final serialized-body validation

> **FYI — Chunking Size Defaults**
>
> | Setting | Value | Purpose |
> |---------|-------|---------|
> | `target_size` | 4,000 chars | Ideal chunk size for splitting |
> | `max_size` | 8,000 chars | Upper limit before forced split |
> | `overlap` | 200 chars | Context overlap between chunks |
> | `max_item_bytes` | 31,457,280 (30 MiB) | Maximum serialized external-item request |
>
> Chunking priority: page markers → section headers → size-based fallback. All boundaries are size-checked; byte subchunks receive unique Graph IDs. JSON/metadata overhead is checked before sending.

### 4. State Manager (`state_manager.py`)
- Destination-bound SQLite manifests, delivered-item hashes, document cache, and durable run history
- Filing outcomes: pending/failed → parsed → completed (or sampled); document rows track downloads and parsing separately
- Resume capability: pick up from any failed state
- Prepared document payloads commit atomically; acknowledged uploads checkpoint individually

### 5. Graph Client (`graph_client.py`)
- MSAL authentication (client credentials flow)
- Connection and schema management
- Bounded individual PUTs (up to five concurrently), with exact serialized-request size checks
- Exponential backoff for 429 rate limits

### 6. CLI Interface (`cli.py`)
```bash
# Quick test mode (1-2 filings, 5 pages max)
sec-connector ingest -t AAPL --test

# Full ingestion
sec-connector ingest -t AAPL,MSFT,GOOG

# Save upload payloads as JSON to data/payloads/ (off by default)
sec-connector ingest -t AAPL --test --save-payloads
sec-connector ingest -t AAPL,MSFT,GOOG --save-payloads

# Resume interrupted processing
sec-connector resume

# Rebuild selected filings with upgraded parsing, including interrupted manifests
sec-connector ingest -t AAPL --reprocess

# Resume with payload saving
sec-connector resume --save-payloads

# Check status
sec-connector status
```

## Schema Properties (for Graph Connector)
| Property | Type | Searchable | Queryable | Purpose |
|----------|------|------------|-----------|---------|
| Title | String | ✓ | ✓ | "Company - Form - Date" |
| Company | String | ✓ | ✓ | Company name |
| Ticker | String | | ✓ | Refinable stock symbol |
| Form | String | | ✓ | Refinable form |
| FilingDate | DateTime | | ✓ | Filing date |
| Description | String | ✓ | | Document description |
| Url | String | | | SEC EDGAR link |
| CIK | String | | ✓ | SEC identifier |
| AccessionNumber | String | | | Unique filing ID |
| Sequence | Int64 | | | Doc sequence |
| Page | Int64 | | | Page/chunk number |
| IconUrl | String | | | iconUrl semantic label |
| FilingUrl | String | | | Filing index citation |
| DocumentName | String | ✓ | ✓ | fileName semantic label |
| FileExtension | String | | ✓ | fileExtension semantic label |
| DocumentType | String | | ✓ | Refinable primary/exhibit type |
| DocumentId | String | | ✓ | Stable document grouping ID |
| ChunkOrdinal | Int64 | | ✓ | Ordering within the document |
| SectionTitle | String | ✓ | ✓ | Genuine source heading |
| ReportPeriodEnd | DateTime | | ✓ | Fiscal reporting date |
| AcceptanceDateTime | DateTime | | ✓ | createdDateTime semantic label |
| IsAmendment | Boolean | | ✓ | Amendment flag |

The schema uses stable Graph v1.0. Requests include
`Prefer: include-unknown-enum-members` so `iconUrl` round-trips correctly.
The beta-only `isExactMatchRequired` property is deliberately not used.
Use a new connection for a populated schema change.

Full reruns refresh completed filings and skip unchanged PUTs. Samples never
delete full content. Whole-filing pruning is opt-in and requires an unlimited
historical inventory without date bounds; failures block pruning. Resume includes
failed deletions and partially retired filings.

## Dependencies
- **click** + **rich**: CLI with progress bars
- **aiohttp**: Async HTTP client (5 concurrent downloads)
- **msal**: Microsoft authentication
- **beautifulsoup4** + **lxml**: HTML parsing
- **markdownify**: HTML to Markdown (including tables)
- **pydantic**: Data validation
- **tenacity**: Retry logic
- **pyyaml**: Configuration
- **aiosqlite**: Async SQLite for state

## Design Decisions
- **Async processing**: 5 concurrent downloads for faster ingestion
- **Tables**: Convert to Markdown format for LLM reasoning
- **Azure**: Operators must configure an app registration and admin-consented permissions (credentials supplied through environment variables)

## Test Mode (Quick Validation)
- `--test` flag limits: 1 ticker, 2 filings, 5 pages each
- Total: ~10 items uploaded for quick end-to-end validation
- Full processing mode removes all limits

## Robustness Features
1. **Retry Logic**: Exponential backoff (5 retries, 4-60s delays)
2. **Progress Logging**: Structured logs with timestamps
3. **Resume Capability**: SQLite state tracks every item
4. **Rate Limiting**: Respects SEC (10/s) and Graph (429) limits
5. **Error Isolation**: Failed items don't block batch processing

## Verification Steps
1. Run `sec-connector setup` to create Graph connection
2. Run `sec-connector ingest -t AAPL --test --save-payloads` for quick test with payload inspection
3. Review saved payloads in `data/payloads/{ticker}/{accession}/` to verify content before upload
4. Verify items in Microsoft 365 Admin → Search & Intelligence → Connectors
5. Test in Copilot: "What are Apple's recent SEC filings?"
6. Run full ingestion with desired tickers

## Configuration (config/config.yaml)
```yaml
sec:
  user_agent: ${SEC_USER_AGENT}
  rate_limit: 10

azure:
  tenant_id: ${AZURE_TENANT_ID}
  client_id: ${AZURE_CLIENT_ID}
  client_secret: ${AZURE_CLIENT_SECRET}
  connection_id: "sec-filings"

filings:
  forms: ["10-K", "10-Q", "8-K", "DEF 14A"]

chunking:
  target_size: 4000
  max_size: 8000
  overlap: 200

test_mode:
  max_filings: 2
  max_pages: 5
```

## Python vs PowerShell: Parsing & Semantic Indexing Comparison

This project is compared with an earlier PowerShell-based SEC connector that relied heavily on regex for HTML processing. The comparison concerns those specific implementations, not either language in general, and focuses on parsing quality, content format, and suitability for M365 Search semantic indexing.

### Where Python is genuinely better

#### 1. Table Handling (the biggest win)

SEC 10-K and 10-Q documents are 40-60% tabular financial data — balance sheets, income statements, cash flow statements. How tables are represented in the indexed content is the single most impactful difference.

| | PowerShell | Python |
|---|---|---|
| Tables | Left as **raw HTML tags** (`<table><tr><td>`) — table conversion code was written but is **commented out** | Converted to **Markdown tables** via `SECMarkdownConverter.convert_table()` with header detection and separator rows |
| What M365 Search sees | `<table><tr><td>Revenue</td><td>394,328</td></tr>` — opaque tag soup | `\| Revenue \| 394,328 \|` — structured, readable text |
| Semantic impact | Search indexes cell text but has **no structural understanding** of row/column relationships | Markdown tables preserve the **relational context** between labels and values |

When a user asks Copilot *"What was Apple's revenue?"*, the Python-produced content gives the search index `| Revenue | 394,328 |` on the same logical line, making the label-to-value association clear. The PowerShell version has these as separate `<td>` fragments buried in HTML noise.

#### 2. Content cleanliness

| | PowerShell | Python |
|---|---|---|
| Approach | 25+ hand-written regex replacements in sequence — strips attributes, converts tags one-by-one, then calls `HtmlDecode` | BeautifulSoup DOM parser + markdownify library — operates on the **parsed tree**, not raw text |
| Robustness | Regex-on-HTML is fragile; ordering matters; the `$emptyTagPattern` needs a **5-second timeout** to avoid catastrophic backtracking | DOM-based parsing handles malformed/nested HTML correctly by design |
| Residual HTML | Raw `<table>`, `<tr>`, `<td>` tags remain in final output (table conversion disabled) | **No HTML tags** in output — everything is Markdown or plain text |

Residual HTML tags hurt semantic search because the search engine must decide whether `<td>` is content or markup. Clean Markdown removes that ambiguity.

#### 3. Chunk size enforcement

| | PowerShell | Python |
|---|---|---|
| Size validation | No explicit request-envelope validation in the earlier implementation | Bounded UTF-8 chunks plus final serialized-request validation against the configured 30 MiB ceiling |
| Chunk sizing | Splits only on page boundaries; pages can be arbitrarily large or small | Target ~4,000 chars with fallback splitting |
| Overlap | None — page boundaries are hard cuts | 200-char overlap ensures search queries hitting chunk boundaries still find relevant context |

Consistent chunk sizes produce more uniform relevance scoring. A 200 KB chunk competing with a 2 KB chunk creates scoring imbalances in search results.

#### 4. State management and reliability

| | PowerShell | Python |
|---|---|---|
| Tracking | Flat `processed_ids.txt` file | SQLite with `filings` and `chunks` tables, state machine (PENDING -> DOWNLOADED -> PARSED -> UPLOADED -> COMPLETED) |
| Resume | Skips already-processed IDs | Resumes from exact failure point — if parsing succeeded but upload failed, re-uploads without re-downloading |

### Where PowerShell is better

#### 1. Page boundary detection (PowerShell wins)

| | PowerShell | Python |
|---|---|---|
| Strategy | 6-tier detection: SGML `<PAGE>` markers, XBRL section breaks, **pattern-detected page numbers** (Arabic, Roman numeral, prefixed like F-1), horizontal rules, forward links | 3-tier: `---PAGE---` markers, Markdown section headers, size-based fallback |
| Page number intelligence | Validates **monotonically ascending** sequences, detects formats like `"Page 1"`, `"- 1 -"`, `"F-1"`, Roman numerals | No page number pattern detection |

Filings without `<PAGE>` tags but with visual page numbers get split more intelligently in PowerShell. However, for semantic search quality this advantage is marginal — whether a chunk boundary falls on a visual page break vs. a section header doesn't strongly affect retrieval relevance.

#### 2. XBRL/XML fallback

PowerShell tries `<body>` extraction first, then falls back to XBRL content, then XML. Python handles only HTML and plain text. In practice most filings have an HTML body, so this matters for edge cases only.

#### 3. Additional metadata fields

PowerShell indexes `Act`, `FileNumber`, `FilmNumber` which Python does not. These are niche but could help with specialized queries like *"Show me filings under Securities Act 34"*.

### Roughly equivalent

- **SGML document extraction**: Both parse `<DOCUMENT>`, `<SEQUENCE>`, `<FILENAME>` tags correctly
- **HTML entity handling**: Both effective (`[Net.WebUtility]::HtmlDecode` vs `clean_sec_text()` regex)
- **Heading/list/emphasis conversion**: Both produce `#`, `-`, `*text*`, `_text_` Markdown
- **Binary file handling**: PowerShell detects UUencoded/PDF; Python filters by extension — same result

### Net assessment

The Python project produces **meaningfully better content for M365 Search indexing** for two reasons:

1. **Financial tables are readable** — the single biggest deal for SEC filings. PowerShell passes raw HTML table tags through; Python produces structured Markdown tables.
2. **No residual HTML** — clean Markdown means every character in the indexed content is meaningful text, with no tag noise diluting the semantic signal.

The PowerShell project's smarter page-boundary detection is a genuine advantage, but it affects chunk boundaries rather than content quality — and chunk boundaries are a second-order concern compared to the content itself being properly formatted.
