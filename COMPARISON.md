# Python vs PowerShell SEC Connector: Parsing & Semantic Indexing Comparison

This Python-based SEC connector replaces an earlier PowerShell-based connector (`Lumen-SEC`) that relied heavily on regex for HTML processing. Below is an honest comparison focused on parsing quality, content format, and suitability for M365 Search semantic indexing.

---

## Where Python is genuinely better

### 1. Table Handling (the biggest win)

SEC 10-K and 10-Q documents are 40-60% tabular financial data — balance sheets, income statements, cash flow statements. How tables are represented in the indexed content is the single most impactful difference.

| | PowerShell | Python |
|---|---|---|
| Tables | Left as **raw HTML tags** (`<table><tr><td>`) — table conversion code was written but is **commented out** | Converted to **Markdown tables** via `SECMarkdownConverter.convert_table()` with header detection and separator rows |
| What M365 Search sees | `<table><tr><td>Revenue</td><td>394,328</td></tr>` — opaque tag soup | `| Revenue | 394,328 |` — structured, readable text |
| Semantic impact | Search indexes cell text but has **no structural understanding** of row/column relationships | Markdown tables preserve the **relational context** between labels and values |

When a user asks Copilot *"What was Apple's revenue?"*, the Python-produced content gives the search index `| Revenue | 394,328 |` on the same logical line, making the label-to-value association clear. The PowerShell version has these as separate `<td>` fragments buried in HTML noise.

### 2. Content cleanliness

| | PowerShell | Python |
|---|---|---|
| Approach | 25+ hand-written regex replacements in sequence — strips attributes, converts tags one-by-one, then calls `HtmlDecode` | BeautifulSoup DOM parser + markdownify library — operates on the **parsed tree**, not raw text |
| Robustness | Regex-on-HTML is fragile; ordering matters; the `$emptyTagPattern` needs a **5-second timeout** to avoid catastrophic backtracking | DOM-based parsing handles malformed/nested HTML correctly by design |
| Residual HTML | Raw `<table>`, `<tr>`, `<td>` tags remain in final output (table conversion disabled) | **No HTML tags** in output — everything is Markdown or plain text |

Residual HTML tags hurt semantic search because the search engine must decide whether `<td>` is content or markup. Clean Markdown removes that ambiguity.

### 3. Chunk size enforcement

| | PowerShell | Python |
|---|---|---|
| Size validation | No explicit request-envelope validation in the earlier implementation | Bounded UTF-8 chunks plus final serialized-request validation against the configured 30 MiB ceiling |
| Chunk sizing | Splits only on page boundaries; pages can be arbitrarily large or small | Target ~4,000 chars with fallback splitting |
| Overlap | None — page boundaries are hard cuts | 200-char overlap ensures search queries hitting chunk boundaries still find relevant context |

Consistent chunk sizes produce more uniform relevance scoring. A 200 KB chunk competing with a 2 KB chunk creates scoring imbalances in search results.

### 4. State management and reliability

| | PowerShell | Python |
|---|---|---|
| Tracking | Flat `processed_ids.txt` file | SQLite with `filings` and `chunks` tables, state machine (PENDING -> DOWNLOADED -> PARSED -> UPLOADED -> COMPLETED) |
| Resume | Skips already-processed IDs | Resumes from exact failure point — if parsing succeeded but upload failed, re-uploads without re-downloading |

---

## Where PowerShell is better

### 1. Page boundary detection (PowerShell wins)

| | PowerShell | Python |
|---|---|---|
| Strategy | 6-tier detection: SGML `<PAGE>` markers, XBRL section breaks, **pattern-detected page numbers** (Arabic, Roman numeral, prefixed like F-1), horizontal rules, forward links | 3-tier: `---PAGE---` markers, Markdown section headers, size-based fallback |
| Page number intelligence | Validates **monotonically ascending** sequences, detects formats like `"Page 1"`, `"- 1 -"`, `"F-1"`, Roman numerals | No page number pattern detection |

Filings without `<PAGE>` tags but with visual page numbers get split more intelligently in PowerShell. However, for semantic search quality this advantage is marginal — whether a chunk boundary falls on a visual page break vs. a section header doesn't strongly affect retrieval relevance.

### 2. XBRL/XML fallback

PowerShell tries `<body>` extraction first, then falls back to XBRL content, then XML. Python handles only HTML and plain text. In practice most filings have an HTML body, so this matters for edge cases only.

### 3. Additional metadata fields

PowerShell indexes `Act`, `FileNumber`, `FilmNumber` which Python does not. These are niche but could help with specialized queries like *"Show me filings under Securities Act 34"*.

---

## Roughly equivalent

- **SGML document extraction**: Both parse `<DOCUMENT>`, `<SEQUENCE>`, `<FILENAME>` tags correctly
- **HTML entity handling**: Both effective (`[Net.WebUtility]::HtmlDecode` vs `clean_sec_text()` regex)
- **Heading/list/emphasis conversion**: Both produce `#`, `-`, `*text*`, `_text_` Markdown
- **Binary file handling**: PowerShell detects UUencoded/PDF; Python filters by extension — same result

---

## Net assessment

The Python project produces **meaningfully better content for M365 Search indexing** for two reasons:

1. **Financial tables are readable** — the single biggest deal for SEC filings. PowerShell passes raw HTML table tags through; Python produces structured Markdown tables.
2. **No residual HTML** — clean Markdown means every character in the indexed content is meaningful text, with no tag noise diluting the semantic signal.

The PowerShell project's smarter page-boundary detection is a genuine advantage, but it affects chunk boundaries rather than content quality — and chunk boundaries are a second-order concern compared to the content itself being properly formatted.
