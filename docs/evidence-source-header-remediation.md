# Offline source-structured financial headers (v8)

## Decision and scope

**Ready for promotion review and a separately approved bounded retest, not
unrestricted rollout.** The source-structure repair resolves the remaining 169
v7 period-context diagnostic pairs on the same 20 cached documents. All 79 newly
inferred header bands were inspected; no financial data row was found promoted
by the new annotations in this corpus. This is bounded evidence, not a universal
financial-accuracy guarantee or a new Copilot efficacy result.

Implementation revision: `30449d352bd584713e37a3aab5d0939d88cfc920`.
Comparison baseline: frozen v7 `4a06538491b9c005f74db8c45d4b9a49e43612cd`.
The [machine-readable matrix](evidence-source-header-results.json) pins exact
public document identities, source hashes, parameters, runner/receipt hashes,
reviewed band hashes and outcomes for all 20 documents.

This separately scoped repair follows the [v7 report](evidence-table-context-remediation.md).
Frozen live v5 and offline v6/v7 artifacts remain untouched. No network downloads,
tenant writes, connection/agent/skill changes, shared environment or original
cache/SQLite changes, merge, push or rollout were performed.

## Source adjudication

All 169 original diagnostic pairs were traced to **20 distinct source bands**,
with exact normalized label matches and raw HTML cell/span/style inspection.
None required promoting a first financial observation as schema. BAC vintage
years are origination categories, not newly inferred fiscal report periods.

| Source | Distinct bands | v7 missing pairs | v8 missing pairs | Raw evidence |
|---|---:|---:|---:|---|
| PNC 10-K 2026 | 2 | 8 | 0 | Spanned gains/losses groups, long rowspan qualifier, dated fair-value and transaction columns; `Assets` starts the body. |
| PNC 10-Q 2026 | 4 | 16 | 0 | Same rollforward geometry for quarterly/year-to-date comparisons, including acquisition column. |
| JPM 10-K 2026 | 4 | 49 | 0 | Three Level-3 rollforwards plus volume/rate/change analysis; stacked captions and rowspanned date/unit stubs. |
| JPM 10-Q 2024 | 4 | 44 | 0 | Three-/nine-month rollforwards with purchases, sales and settlements beneath the group band. |
| BAC 10-K 2026 | 3 | 26 | 0 | Country exposure/change bands and two credit-quality vintage bands, including blank source spacer rows. |
| BAC 10-Q 2025 | 3 | 26 | 0 | Corresponding country/vintage bands for September and comparative December dates. |
| Other 14 documents | 0 | 0 | 0 | No residual v7 target pairs. |

The private inventory preserves raw HTML table indexes, source hashes, source
rows/cells/attributes, exact matched labels and original pair counts. All 169
were adjudicated as real missing header/context co-locations; zero were dismissed
as false-positive requirements. They are not 169 independent financial answers.

## Minimal contract change

The parser carries `ParsedDocument.table_header_rows`, an out-of-band map from
the SHA-256 of an exact Markdown table to its leading header-row count. It does
**not change the Markdown format, cell conversion, column collapsing, source
text, headings or Graph schema/content annotations**. Retaining inline cell
styles through conversion supplies the structural evidence; existing heading
recognition still runs before style cleanup.

Native column headers are accepted unless row scope or inline-XBRL financial
facts contradict them. Otherwise a contiguous leading band needs spanned cells,
bottom/center alignment and a unit anchor. A dominant caption can have a separate
table-number cell. Centered multi-year vintage cells require a preceding group
and a unit stub on the same row. Domain numbers and long source captions are
not interpreted as financial values or rewritten. Monetary values, ordinary
numeric/date data and body stubs terminate inference; boldness alone never
authorizes it.

The existing source-origin grid still determines every rendered column. Source
header flags pass through the same empty-row/title removal and header flattening
as that grid, yielding an exact prefix of the unchanged table. The chunker repeats
that prefix verbatim rather than constructing a new interpretation of its cells.
Conflicting identical Markdown tables use the smaller source count; changed
table hashes cannot borrow annotations. Counts outside the matched table fail
explicitly. No sidecar keys/counts are serialized into Graph external items.

Repeated bands and existing marker-scoped notes consume the metadata-inclusive
character and request-byte budgets. Oversized bundles retain the existing
explicit warning and ordered-fragment fallback, not silent truncation. There
were no such warnings in this corpus. No context is inferred across a page or
section boundary; existing repeated source headers remain separate source rows.

Processing version is now **8**, not live v5 or frozen v7. Ordinary resume still
replays prepared payloads. A semantic rebuild requires separately approved
explicit reprocessing; this code does not upgrade live items on its own.

## Results and audit boundaries

| Measure | Frozen v7 | v8 |
|---|---:|---:|
| Items across 20 identical sources/configurations | 7,471 | 7,807 |
| Original period diagnostic misses / 3,441 | 169 | 0 |
| Explicit linked-note misses / 5,414 | 0 | 0 |
| Original broad adjacent-context misses / 7,462 | 1,018 | 778 |
| Full reviewed source-band misses / 2,058 | 1,400 | 0 |

The original period/broad diagnostics were not changed. The new source-band
audit separately checks the **entire reviewed prefix**, including long labels,
units, date/vintage columns and merged references, against every subsequent
source row. Its 79 reviewed bands include 59 additional bands beyond the 20
target bands, such as fair-value hierarchy, maturity, VaR and credit-exposure
column groups. All were inspected against captured source cells, not merely
accepted because an aggregate numeric-token score improved.

There are no new period, explicit-linked-note or unit-label gaps. There are
**seven new broad-diagnostic misses**: five JPM rows no longer incidentally share
an unreferenced U.S. GSE `(a)` note, and two PNC servicing-rights rows no longer
share an unreferenced NAV `(a)` note. None carries that marker. All explicitly
marked associations remain present; the broad metric's 247 resolved and seven
new misses are retained, not reclassified away to improve its score.

All original Markdown and **5,259 source-cell/table conversion observations**
are exactly unchanged from v7. Ordered coverage preserves **1,660,777 lexical
and 223,297 numeric tokens**. All **29,802 rendered data rows** retain their
existing column/header relationships and occurrence counts. A stricter repetition
audit permits extra rows only from existing text-recognized prefixes or the
separately reviewed structural prefixes; no unexplained data repetition remains.
Independent equal values and signed values remain in their original columns.

The occurrence-level audit checks **1,936 uniquely attributable emitted row
occurrences**, with zero missing bands. **192 source-row checks** have identical
text in multiple tables, such as `Assets` or `Refreshed FICO score`: their global
multiplicity and source-band co-location are checked, but they are not claimed
as uniquely attributed per-copy checks. Ambiguous duplicates remain explicitly
listed in the private receipt rather than being counted as individual proof.

Maximum output remains **7,998 characters including metadata**, and maximum
serialized request **10,003 bytes**, within the existing 8,000-character and
30 MiB ceilings. All document identity/ACL, fiscal metadata, ordered coverage,
deterministic ID/payload and section-heading checks pass. No proxy compensation
year was invented. The matrix's `filing` fields preserve frozen **input discovery
metadata**, including proxy meeting dates; they are not emitted Graph properties.
Proxy `ReportPeriodEnd` remains absent in the actual payloads.

**420 tests passed**, including all opt-in cached-source/historical/current
receipt checks, with no skips. The only warning is the existing Pydantic
class-based configuration deprecation. Source-derived minimized tests cover
rowspan/colspan bands, Level-3 labels, long captions, year/vintage groups, negative
and equal financial amounts, bold totals, date-as-data, row scope, XBRL facts,
unrelated tables, page/section boundaries, stale/conflicting hashes, explicit
oversize fallback, serialization and audit-negative controls.

## Limits and live/reprocessing implications

This does not solve indirect/class-only CSS layouts, unanchored ambiguous
headers, cross-page or narrative-separated notes, duplicate note definitions,
symbol-only references or arbitrary oversized context bundles. Legacy
text-only parser flattening is deliberately unchanged: a synthetic `Total /
2025` row can still be folded into a header by that older heuristic, although
the new structural inference rejects it. That pre-existing ambiguity is not
evidence of a newly inferred v8 header or justification for a broader parser
rewrite under this authorization. The corpus still excludes PDF/OCR,
amendments, uncached incorporated reports and non-bank issuers.

All **556 PNC proxy payloads are identical to v7**. Against frozen live v5:
566 -> 556 items, 554 shared IDs, two new IDs, 12 stale IDs, and seven identical
whole payloads. The known-good pay-ratio content remains unchanged; v8 adds no
further PNC payload delta beyond v6/v7. Historical user-reported success applies
to live v5 only. A future v8 retest still requires the previously proposed
v6-equivalent PNC replacement; neither live connection was updated.

The [staged upload-before-delete plan](evidence-corpus-validation.md#live-pilot-compatibility-and-staged-proposal)
now targets version 8: pin revision and exact destination/document scope, freeze
desired payloads and old acknowledged/potential IDs, acknowledge every desired
upload before any separately approved scoped stale deletion, and preserve
recovery/rollback artifacts. Mixed versions are not an evaluation window;
restoring SQLite alone cannot roll back Graph. No global prune or broad
reprocessing is approved here. Keep exact agent instructions and skill
presence/version fixed across any separately approved A/B evaluation.

## Reproduction

Private `corpus-v1` contains `manifest-v8-final.json`, `candidate-v8-final`,
`comparison-v8-final.json`, `linked-audit-v8-final.json`,
`complex-header-source-inventory-all.json`, `reviewed-source-bands-v8.json`,
`structure-audit-v8-reviewed.json` and `source-header-summary-v8-final.json`.
Exploratory artifacts and the initial structure audit remain separate, not
substituted for final evidence. Raw corpus, payloads and logs are not committed.
The frozen replay runner is from `30449d3`, with its recorded hash over the
Windows CRLF checkout bytes rather than Git's LF blob; a later
compatibility-only guard lets the current runner also load pre-v7 source without
the newer header helper. The current runner reproduces the frozen PNC payload
hash. The structural audit has its own recorded runner hash.

Use the shared dependency environment with this revision's `src` explicitly
selected via `PYTHONPATH`, an isolated pytest `--basetemp`, and new output paths:

```powershell
python -m tests.corpus_replay --manifest '<manifest-v8-final.json>' --output '<new output>'
python -m tests.corpus_compare --baseline '<candidate-v7-review2>' --candidate '<new output>' --output '<new comparison.json>'
python -m tests.table_context_audit --baseline '<candidate-v7-review2>' --candidate '<new output>' --output '<new linked-audit.json>'
python -m tests.source_header_audit --baseline '<candidate-v7-review2>' --candidate '<new output>' --review '<reviewed-source-bands-v8.json>' --output '<new structure-audit.json>'
```

Enable `SEC_SOURCE_HEADER_EVIDENCE` for v8 receipts/source hashes, alongside
`SEC_CORPUS_EVIDENCE`, `SEC_TABLE_CONTEXT_EVIDENCE`,
`SEC_EVIDENCE_PILOT_SOURCE` and `SEC_EVIDENCE_PILOT_BASELINE` for retained
historical evidence. A different corpus needs its own source review; the
reviewed-band file is not a generic automatic approval mechanism.
