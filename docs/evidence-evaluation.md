# Repeatable evidence evaluation, not an accuracy claim

This is an **offline, evaluator-only** extension to the existing corpus tools.
It changes no parser, chunker, processing version, Graph schema, synchronization,
agent instructions or installed skills. No source downloads, OCR engine calls,
database access, connector writes, deployed-agent evaluations, paid services or
telemetry were performed. Expected answers must never become agent knowledge,
runtime instructions, starter prompts or skill-package content.

The [public manifest](../samples/evaluation/pnc-evidence-v1.json) pins four cached
PNC HTML sources by accession, filename, SEC URL and SHA-256. It defines seven
questions, nine evidence groups and **34 exact, nonempty source-cell rows**.
Only factual rows and short locating phrases are included, not whole filings,
customer answers, worksheets, screenshots, operational identifiers or cache paths.
The [machine-readable receipt](evidence-evaluation-results.json) records the
actual offline run and code/dependency hashes. This is a purposive four-document
banking sample, not representative SEC coverage.

The runtime base is `53dd715b7a57ea8637528b54a9b1a12f53532d0f` (processing
version 8); the final receipt was captured at **2026-10-02 20:19:06 UTC**.
Those statements and the published receipt describe the original evaluator
addition, not the later runtime change. The
[processing-v9 follow-up](#processing-v9-note-association-follow-up) below records
the separate association fix; historical receipts and expected answers remain
unchanged.

## Supported-format and evidence matrix

Format acceptance, faithful extraction, self-contained chunks and successful
agent answers are different claims.

| Source surface | Implementation at this PR's base | Evidence and limits |
|---|---|---|
| HTML/text primary filings and selected exhibits | Implemented: HTML DOM/table conversion, SGML document extraction, plain-text parsing | Existing corpus plus the four pinned HTML sources here. Native multilevel headers, spans, independent equal values and signed amounts have synthetic regressions. Acceptance is not proof every layout is faithfully interpreted. |
| Amendments to 10-K, 10-Q, 8-K and DEF 14A | Discovery/metadata and distinct document identities implemented | New synthetic original/amended-value and fiscal-period controls; **no real amendment replay in this addition**. Never combine original and amended numbers silently. |
| Older layouts and non-bank financial disclosures | Generic HTML/text path, not issuer-specific | Existing historical banking sample retained; new synthetic manufacturing, legacy text pages and multilevel segment tables. **No new real non-bank source has been validated.** |
| Narrow rotated image headers inside HTML | Optional local Pillow/pytesseract/Tesseract path; disabled by default | HTML-only replay preserves placeholders/markers, not names. Independent visual references are source truth, **not OCR accuracy**. Real-engine work is separate; no image recovery is measured here. |
| General charts, arbitrary raster text, whole-page images | No general image-understanding pipeline | An adjacent chart does not mean a duplicate HTML table requires OCR. Check the DOM first. |
| PDF exhibits, including text PDFs | Not implemented as a PDF extraction pipeline | No PDF engine, PDF table-layout or PDF page-boundary claim. |
| Scanned/image-only PDFs | Not implemented | Requires separately designed page rendering/OCR/layout work and source-grounded evaluation. |
| Cross-page, symbol-only or narrative-separated notes | Not reliably bound to every marked chunk | Source text may survive while its association is missing. Three strict expected-failure regressions preserve these gaps. |
| Incorporated material absent from selected inventory | Not implicitly supplied | The prior WFC/USB incorporation-limited annuals remain incomplete-report examples, not full-report coverage. |

The [v6 corpus](evidence-corpus-validation.md),
[v7 context](evidence-table-context-remediation.md),
[v8 headers](evidence-source-header-remediation.md) and
[five-bank sample](evidence-v8-five-bank-sample.md) retain their original results.
In particular, the latter's 17 residual period diagnostics on two additional
documents are not erased by the earlier 20-document sample's zero target misses.
No broader supported-format statement supersedes these limits.

## Source-verified question coverage

Table indexes in the manifest are zero-based `BeautifulSoup(..., "lxml")`
`find_all("table")` indexes, pinned to exact bytes, not printed page numbers.
Printed pages below were checked in surrounding source footers; emitted `Page`
and chunk ordinals are not printed-page citations.

| Case | Verified evidence and required distinctions |
|---|---|
| Incentive above target | 2025 proxy table 376, printed p72: 2024 target $18.7m versus award $23.7m. Calculated difference/target is **26.7% above**, rounded to one decimal. Neither amount is total compensation or Summary Compensation Table pay. |
| Market capitalization | 2025 proxy table 398, p78: **PNC $76.4bn, as of December 31, 2024**. Independently ranked asset, revenue and market-cap columns have their own tickers. The leftmost company on that row is Fifth Third; assigning PNC's value to it is incorrect. |
| HR numeric performance | 2025 proxy table 370, p71: **nine financial rows plus four other key rows** with numeric 2024/2023 comparisons. The p66 framework also covers capital/risk/expense, growth, multihorizon TSR, strategy, risk, talent and succession. PSU ROE/EPS alone is incomplete. |
| HR year/selection control | 2024 proxy table 351 has ten financial rows plus four other key rows, comparing 2023/2022; 2025 compares 2024/2023. The older table includes an extra noncore-adjusted EPS row and a differently adjusted efficiency row. Preserve these basis differences. |
| Annual CAGR | Fiscal 2023 annual table 13, p36: **9.64%**, December 2018 to December 2023, total return including reinvested dividends. It is in an HTML table beneath a chart, not an OCR requirement. The same number elsewhere is a servicing-rights discount rate and is not interchangeable. |
| Age/period control | Fiscal 2023 annual table 11 says **61**; fiscal 2024 annual table 10 says **62**. Their accessions are from 2024 and 2025 respectively. Clarify an ambiguous “2024 annual filing” instead of silently swapping fiscal and filing years. |
| Charity interpretation | 2025 proxy table 128, p25: six markers, 13 image-only name headers. PNC made contributions to organizations linked to directors/family; this does **not** mean six directors personally donated. Footnote (3), across the page boundary, excludes matching gifts to personally supported charities. |

For charity names, the separate OCR workstream supplied an independent visual
reference made **before OCR**, with all 13 images and source-grid columns checked.
The immutable [published reference](https://github.com/svarukala/SEC-Copilot-Connector/blob/9695edf039de7321ad55f082c9aec243ed59262e/docs/maintenance.md)
identifies marked columns 2, 5, 6, 7, 8, 13 as Debra A. Cafaro, William S. Demchak,
Andrew T. Feldstein, Richard J. Harshman, Daniel R. Hesse and Bryan Salesky.
The manifest records these six reference image identities/hashes. This evaluator
checks their HTML asset ordering only; it **does not reread image bytes, run OCR,
or certify recovered marker-to-name relationships in payloads**. Names appearing
elsewhere in a document do not establish this mapping. An agent's honest
abstention when headers were not retrieved is incomplete, but preferable to
guessing from the evaluator's reference.

## Deterministic checks and reproduction

The runner is `python -m tests.evidence_evaluate`. Keep the manifest public and
all source maps, payload directories and actual agent receipts private.
Supply a JSON object mapping the four manifest source IDs to exact cached HTML
paths. It must contain exactly those IDs. The runner opens source files read-only
and blocks socket `connect`/`connect_ex` during evaluation. It performs no
discovery, asset download, authentication or state access.

Use the repository's existing Python dependencies; choose this checkout's `src`
explicitly rather than accidentally importing another editable checkout:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m tests.evidence_evaluate `
  --sources '<private source-map.json>' --output '<new private receipt.json>'
```

Four independent levels are reported:

1. **Source:** exact source SHA-256, ordered nonempty DOM cells at the pinned
   table index, source headers, context phrases, image count and referenced
   image order. A source mismatch produces a nonzero exit; the diagnostic
   receipt is retained. Printed pages and visual image readings remain reviewed
   provenance, not automatically reconstructed facts.
2. **Parsed:** exact row sequence after normalization of Markdown emphasis,
   escaped asterisks, empty visual columns and spacing before note markers.
   Numeric order, signs and literal note symbols must survive. Reversed years,
   wrong labels and document-wide bags of numbers do not pass. Charity's
   source-rowspan label is explicitly included in its expected rendered row.
3. **Local content probe:** the unchanged HTML converter and `_split_content`
   use 4000/8000/200 characters and 31,457,280 bytes with source header sidecars.
   This deliberately tests only content splitting: **no filing metadata prefix,
   full page/section orchestration, Graph body or ingestion manifest is produced**.
   Do not infer real item counts, page isolation or upload limits from these
   probe segments. Synthetic end-to-end tests use `parse_document`,
   `chunk_document` and Graph payload construction separately.
4. **Saved payloads (optional):** use `--corpus '<tests.corpus_replay output>'`.
   Each source-ID subdirectory must contain that runner's `result.json` and
   `payloads.json`. Source hash, payload-list hash and exact CIK/accession/
   filename/URL are checked before row/header/context availability. Missing or
   wrong inputs fail rather than become empty successful results. Generate
   replays with the existing corpus tool and an independently verified metadata
   manifest; **do not invent filing dates from filenames or cover-letter dates**.

Without `--corpus`, payload status is **`not_run`**, not failed or passed.
Even with payloads, this checks local saved evidence, not PUT acknowledgments,
GET readback, search visibility, retrieval or agent correctness. Hash matching
is provenance consistency, not proof of remote delivery.

All **34 selected source rows** pass the final source and parsed checks.
All have their requested header strings in at least one local probe segment.
The starred HR adjustment statement survives in parsed content but is not
co-located with any of the 13 table rows in the probe. This is a deliberately
broad row/context diagnostic: it is **not 13 independently adjudicated errors**;
the `*` adjustment qualifier applies to marked financial rows, not indiscriminately
to the four other key measures. Charity scope/exclusion context also survives
but the complete context bundle is not co-located with the marked row.
There are no real PNC payload or agent results in this receipt.

Source-expectation failures and initial row-normalization diagnostics were retained
privately under distinct filenames, not overwritten by the corrected run.
In particular, escaped `\*`, spacing before `(1)`, and separate source footnote
cells were evaluator matching issues, **not parser losses**. Source inspection
corrected the expectations before the final run.

## Answer rubric and repeatable run provenance

Run questions only after separate authorization for the chosen agent and
connection. Freeze source/payload manifests, instruction version/hash, installed
skill versions/hashes and prompts before collecting answers. Keep these equal
between packaging arms. Verify search visibility separately from item readback;
select **one exact connection**, not just its display name. Use fresh chats,
alternate/randomize arm order, and record actual model selection (including
`Auto` if that is the setting). Do not infer the backend model from answer style.
Keep each response verbatim with actual citations and exposed tool traces.

| Dimension | Full | Partial | Fail |
|---|---|---|---|
| Each required answer component | Correct value, unit, period, attribution and requested comparison/basis | Supported but incomplete, appropriately rounded, or explicit unresolved evidence gap | Wrong number/year/entity/basis, unsupported inference, invented name, or missing required answer without acknowledging the gap |
| Source grounding, graded separately | Every material component has a verified supporting citation/locator in the selected exact source | Only some components supported or precision/qualifier support incomplete | Wrong source, fabricated citation, or cited passage does not support the material claim |
| Unobserved grounding | Record `unobserved`, never promote to full | Overall cannot be full | Not evidence that ingestion failed |

The manifest's `required` entries are the per-question components. “Full” for
the broad HR question needs numeric prior-year comparisons and other key
measures, not just the names of selected metrics. Adjusted/non-GAAP bases and
reported efficiency-change conventions must be retained. A missing numeric
answer can have an honest evidence-gap explanation without becoming a full
answer. Missing retrieved context does not prove source or payload absence.

Copy [run-template.json](../samples/evaluation/run-template.json) into private
storage. Blank identifiers/response/time deliberately **fail validation**, so
the template cannot accidentally count as a run. Fill the exact prompt, native
conversation/response IDs, timezone-aware timestamp, actual model setting,
fresh-chat status, exact connection, instruction version/hash, payload-manifest
hash, index-visibility observation, skills and other-source observations.
Use `unobserved` (or `null` for chat freshness) rather than guessing. Empty
skills/other-source lists only mean verified absence when their corresponding
`*_observed` flag is true.

Human reviewers assign every component and source-grounding grade and record
their identity and adjudication notes. Each citation has this shape:

```json
{
  "source": "pnc-proxy-2025",
  "url": "https://www.sec.gov/Archives/edgar/data/0000713676/000119312525052937/d889589ddef14a.htm",
  "locator": "printed page 72, incentive compensation table",
  "verified": true,
  "components": ["target", "award", "calculation", "period-and-basis"]
}
```

`verified` is the reviewer's source adjudication, not an automatic URL check.
For present skills, record `name`, `version`, `sha256`; capture exact contents
privately. Exact URL checking permits a fragment but not a different filing.
No free-text keyword scorer or model judge assigns correctness.

```powershell
.\.venv\Scripts\python.exe -m tests.evidence_evaluate `
  --runs '<private manually-adjudicated-runs.json>' --output '<new private run-summary.json>'
```

The validator refuses duplicate native conversation/response identities even
under different record IDs. A copied worksheet row must instead use
`{"id":"copy-id","kind":"copy","original_id":"earlier-record-id"}`; it never counts
as another invocation. Preserve unquantified historical reports as
`historical_observation` records with `id`, `note` and `source_reference`, not
invented invocation records. Keep failures and original artifacts; output paths
are create-only. A new prompt or instruction variant is a new version/experiment,
not an overwritten failed trial.

Overall grading is conservative: any failed component/grounding gives `fail`;
all components and grounding must be full for `full`; otherwise `partial`.
`controlled` is separate from correctness and requires observed, fresh,
single-connection settings and verified index visibility. It is not an A/B
causality test or proof that skill activation occurred. Report case-level
counts and individual outcomes; **no broad accuracy percentages from this
small purposive sample**.

The historical instruction-only success, user-reported three candidate
successes and baseline failures with unknown count remain in the
[original pilot report](evidence-packaging-pilot.md). They were not converted
into newly observed runs here. No copied/private customer artifact was imported.

## Bounded next fixes and acceptance gates

| Gap | Concrete evidence | Separate next step |
|---|---|---|
| Symbol qualifiers | PNC HR `*`/`**` notes and synthetic marked manufacturing rows | Add conservative symbol-definition association with ambiguity/negative controls; retain markers and separate non-GAAP definitions. |
| Cross-page and narrative-separated definitions | Charity footnote (3) after p25; two synthetic boundary cases | Preserve source table/definition provenance before attempting bounded association. Do not blindly append the nearest similarly numbered note. |
| Image-header attribution | Six markers and 13 image headers; independent visual reference | OCR owner compares actual engine output and final grid attribution with the frozen reference, recording empty/misread outcomes. |
| Real amendment/non-bank coverage | Only synthetic new examples | Select a small, exact public-source allowlist with verified metadata and compliant acquisition before making real-world claims. |
| Difficult/indirect headers | Explicit multilevel non-bank header regression; existing v8 class-only/unanchored limitations remain | Add source-adjudicated positive/negative cases before expanding inference. |
| PDF/scanned input | No implemented parser or measured corpus | Separate design/approval and format-specific evaluation; not an extension of this PR. |

The three originally strict `xfail` cases in `test_evidence_coverage_gaps.py` represent
desired note co-location, not hidden passing behavior. Separate ordinary tests
require complete ordered row/note preservation. A future fix produces XPASS
and must explicitly update the gap test and report after proving the intended
association; do not remove the failure history.

## Processing-v9 note-association follow-up

The three original assertions first produced strict XPASS against the candidate;
only their `xfail` decorator was then removed. Their original row-preservation,
co-location, character-limit and serialized-request oracles are unchanged.
`test_note_associations.py` adds exact-marker, unrelated-table/section, repeated
marker/table, page ownership, short-row, byte-budget and oversized-note controls.

HTML parsing now captures a table-note sidecar from the **original rendered
source sequence before page/section splitting**, keyed by the exact table hash.
Original Markdown is not rewritten. Symbol definitions (`*`, `**`, `***`, dagger
and double dagger) stay distinct from emphasis, negative values and one another.
Paragraph definitions and two-cell note layouts can follow a short intervening
narrative or a single page boundary. Only repeated source page-prefix headings
and repeated, page-end footer structures can be crossed; a new heading or
independent table ends ownership. Identical table occurrences and duplicate
definitions are not disambiguated by proximity.

Search is bounded to 32 following blocks, 16,000 characters and 800 characters
of intervening narrative. Exhausted block/character scans are logged and not
bound. A short immediately preceding statement can accompany a marked row only
when it names that row's unique, exact multiword label; this is not a general
prose-understanding or long-distance coreference system. Other narrative is
retained in source order, not appended wholesale to every table chunk.
Definitions are repeated only in chunks with their marker (including marked
headers), with the table's original document URL and page ownership. Oversized
qualifiers stay in their original location with a warning rather than being
truncated, misattributed or allowed to exceed the chunk/request limits.

| Surface | v9 support / remaining limit |
|---|---|
| Symbol-only and short narrative-separated notes | Source-local paragraph/two-cell definitions, exact markers and ambiguity controls; the original synthetic gates pass. |
| Cross-page notes | One boundary with proven repeated furniture or no intervening heading/table; original note still exists on its source page. Arbitrary distant or differently headed references are not inferred. |
| PNC 2025 HR table 370 | All 13 ordered rows retained; only seven single-star financial rows require the adjustment definition, while double-star tangible book value retains its separate basis. Numeric notes remain distinct. |
| PNC 2025 charity table 128 | Five ordered relationship rows retained, including full note (3) exclusion and the adjacent source statement on the charitable-contribution row; not a claim of personal donations. |
| Image headers | The separate retained OCR receipt can be replayed, without engine calls: 26 consumed occurrences, 13 assets/headers and six charity marks checked against the earlier independent visual reference. HTML-only replay still has unnamed image placeholders. |
| Budgets, duplicate markers, long-distance/continued paragraphs | Conservative limits remain; no guarantee that every possible source layout becomes self-contained. No PDF, new issuer, live delivery, retrieval or agent-answer claim. |

`python -m tests.note_evidence_replay` is an opt-in, evaluator-only full-document
payload comparison. It reads the authorized copied PNC HTML and retained metadata
(March 12, 2025; source SHA-256
`a78e444a6885c182f38288900af321092d2323edfadc96a16e1b9f010cba5d00`).
`--frozen-ocr` additionally verifies the already-retained asset bytes/hashes and
ordered OCR receipt; it does not perform fresh recognition. It checks exact
rows, complete required qualifiers, header/marker geometry, original URLs,
unique IDs, deterministic output and actual serialized Graph request sizes.
The local content probe is reported separately from full page/section payloads.
All source/asset/receipt paths and generated payloads remain private.

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m tests.note_evidence_replay `
  --root '<authorized retained copied source directory>' `
  --metadata '<retained metadata summary.json>' `
  --output '<new private output directory>' --frozen-ocr
```

Run the same evaluator against the retained integration base
`b2c47ca0169ae359db6b7a7089b1f732729a44ed` and this candidate using separate
`PYTHONPATH` roots/output directories. Never overwrite the old evidence or
reinterpret content-probe misses as full-payload misses. In particular, the
baseline default full payloads already retained the HR starred definitions;
the symbol failure is exposed by the original local probe and bounded synthetic
chunks. The full-payload cross-page charity exclusion was absent.

The same final evaluator and frozen inputs produced these offline results
for both HTML-only and frozen-OCR runs:

| Measure | Retained v8 integration | v9 candidate |
|---|---:|---:|
| Exact selected rows retained once, in order | 18 | 18 |
| Rows with all applicable qualifiers in full payloads | 16 | 18 |
| Rows with all applicable qualifiers in local probe segments | 5 | 18 |
| Full-document payload count | 477 | 681 |
| Maximum content characters | 7,852 | 6,836 |
| Maximum serialized request bytes | 9,044 | 8,013 |

These are evidence availability counts, not answer-accuracy scores. Five
unmarked HR rows require no marker definition. The complete parsed-content
SHA-256 was identical before/after within each OCR mode, and lexical source
coverage passed. All 18 selected rows retained their original page and section
ownership, exact row occurrence and source headers. The frozen-OCR run also
matched all 13 ordered name headers and six marked names against the earlier
independent visual reference; no new OCR recognition or assets were acquired.

Processing v9 invalidates completed parse-cache generations, not SQLite format
4 or maintenance plan formats 1/2/3. Prepared payload replay, old-plan inspect
and source-free rollback retain exact old bytes/digests; forward drift needs the
original runtime. See [the version contract](maintenance.md#existing-plans-and-version-boundaries).
No automatic migration, live repackaging or sample-uploader retargeting is part
of this change.

Run the infrastructure and synthetic controls without a source cache:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_evaluate.py `
  tests\test_evidence_coverage_gaps.py tests\test_corpus_replay.py -q `
  --basetemp '<new isolated temporary directory>'
```
