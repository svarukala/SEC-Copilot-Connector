# Broader offline evidence-packaging validation

## Recommendation

**Not ready for unrestricted promotion or broad reprocessing.** The refined
candidate is ready for code review and a separately approved, bounded retest.
No observed new table-structure or coverage regressions remain in this sample,
and introduced heading false positives were fixed. However, existing financial
table period/header and footnote-context gaps remain. These must be explicitly
accepted for a bounded trial or addressed in a separate scoped change before
claiming reliable independent-chunk financial interpretation.

This work made **no additional tenant writes, downloads, original database/cache
writes, shared environment changes, agent/skill changes, push, or main merge**.
Live pilot connections still contain their original frozen v4/v5 payloads.

## Revisions and corpus

| Role | Revision | Processing version |
|---|---|---|
| Pre-packaging baseline, including existing download normalization fixes | `6d34733b404631b2e6b25caa73a3ac910bf80aa7` | 4 |
| Original live-pilot candidate code | `4f12f9acb352b5e9b177ba85917338d125f29f0b` | 5 |
| Refined offline candidate | `ffb34ac3155a4af75a47a3171b15dc31701574d8` | 6 |

The change to v6 is deliberate: parser semantics changed after v5 was uploaded.
Reusing version 5 would incorrectly allow those completed parse caches to match.
The original v5 outcomes and user-reported evaluation remain historical evidence,
not results for v6.

The SQLite inventory was opened with `mode=ro` and `query_only=ON`. Exactly
20 available HTML documents were selected: six proxies, five annual primaries,
five quarterly primaries, three substantive earnings exhibits and one voting
results 8-K primary. All five requested issuers are represented. Selection favors
recent documents, with an older PNC proxy and 2023-2025 quarterlies for layout/year
variation. The PNC 2026 proxy is the positive control. No missing category was
filled by downloading or inventing a source.

The [machine-readable corpus matrix](evidence-corpus-results.json) contains each
exact accession, filename, sequence, source SHA-256, filing/document metadata,
selection reason, code revisions, dependency versions, parameters and outcomes.
Private manifests additionally retain absolute cached paths. Large HTML,
Markdown, payloads, source-cell observations and warnings remain private.

Both revisions used identical bytes and `target_size=4000`, `max_size=8000`,
`overlap=200`, `max_item_bytes=31457280`, with OCR disabled. Network connections
were blocked in the replay process. The baseline was extracted from its immutable
Git revision into a private directory; `PYTHONPATH` selected the intended source,
not the shared virtual environment's editable checkout.

The WFC and USB selected annual primary files incorporate annual-report material
by reference and are much smaller than the other annuals. They are not evidence
of full incorporated-report coverage; large quarterlies and earnings supplements
provide dense-table coverage for these issuers. The actual corpus does not test
PDF/OCR, amendments, missing assets, malformed-source recovery or full filing
inventories. It is a banking-only purposive sample, not random population coverage.

## Results matrix

Years below are filing years. The JSON matrix disambiguates every source and
financial reporting period. `Period gaps` and `Note/unit gaps` are heuristic
row-context checks remaining in v6; **none is newly introduced relative to v4**.

| Source | v4 items | v5 items | v6 items | Period gaps | Note/unit gaps |
|---|---:|---:|---:|---:|---:|
| PNC DEF 14A 2026 | 1,089 | 566 | 556 | 0 | 0 |
| WFC DEF 14A 2026 | 730 | 326 | 318 | 0 | 0 |
| JPM DEF 14A 2026 | 839 | 271 | 268 | 0 | 0 |
| BAC DEF 14A 2026 | 983 | 350 | 342 | 0 | 0 |
| USB DEF 14A 2026 | 719 | 404 | 404 | 0 | 0 |
| PNC DEF 14A 2022 | 500 | 349 | 344 | 0 | 0 |
| PNC 10-K 2026 | 581 | 625 | 623 | 53 | 174 |
| WFC 10-K 2026 | 90 | 62 | 60 | 0 | 0 |
| JPM 10-K 2026 | 1,701 | 905 | 884 | 126 | 453 |
| BAC 10-K 2026 | 1,003 | 770 | 765 | 216 | 0 |
| USB 10-K 2026 | 87 | 98 | 96 | 0 | 0 |
| PNC 10-Q 2026 | 413 | 378 | 374 | 60 | 164 |
| WFC 10-Q 2026 | 790 | 366 | 362 | 15 | 0 |
| JPM 10-Q 2024 | 854 | 585 | 580 | 109 | 534 |
| BAC 10-Q 2025 | 709 | 558 | 550 | 286 | 0 |
| USB 10-Q 2023 | 791 | 308 | 308 | 120 | 0 |
| PNC 8-K EX-99.2 2026 | 115 | 93 | 93 | 79 | 48 |
| JPM 8-K EX-99.1 2026 | 35 | 21 | 14 | 0 | 0 |
| USB 8-K EX-99.2 2026 | 82 | 21 | 21 | 0 | 0 |
| BAC voting-results 8-K 2026 | 24 | 20 | 20 | 0 | 0 |
| **Total** | **12,135** | **7,076** | **6,982** | **1,064** | **1,373** |

All 20 sources retain the same **1,660,777 ordered lexical tokens** and
**223,297 ordered numeric tokens** from baseline parsing. Every parsed token
survives in order in candidate output, permitting repeated prefixes/overlap and
ignoring page markers. This is a relative preservation check, not an independent
proof that the baseline parser extracted every visible HTML fact correctly.

All **5,259 leaf-table conversion observations** were paired on identical source
cell arrays (nested wrappers can cause repeated conversion observations).
**523** changed only into the intended bullet lists. Every other table conversion
was identical, including cell order, merged-cell references and rendered headers.
All **29,802 candidate Markdown data rows** occurred intact with their rendered
Markdown header in at least one emitted chunk. No oversized-row fragmentation
was needed in this sample.

Every document passed context-inclusive character limits, serialized request
limits, unique IDs, deterministic repeated chunking/payload generation, exact
document identity/URL/ACL checks, and recognized-heading section consistency.
Maximums were **7,998 characters** and **10,003 serialized request bytes**.
All ten annual/quarterly documents retained their stored fiscal report date;
all proxies/current-report documents omitted the fiscal property/prefix without
substituting a guessed compensation year. Download normalization code was unchanged.

## Structural review: what token equality alone would miss

Source cell arrays and rendered rows were inspected for representative real
tables, not just totals of numbers:

| Source and private table observation | Source relationship checked | Finding |
|---|---|---|
| PNC 10-K, table 13 | Net interest income aligns with 2025/2024/2023, dollars-in-millions/per-share units; independent repeated values remain separate. | Row/column mapping unchanged. Header labels repeat over visual currency/spacer columns, preserving their original scope. |
| JPM 10-K, table 64 | Selected income statement values, annual periods, unit caption and lettered footnote markers. | Table conversion unchanged, but true period row is in the body rather than the repeated Markdown header. Later chunks can lack it. |
| WFC 10-Q, table 8 | Quarter-ended versus six-month periods, separate percent-change columns, and note markers. | Source row/cell alignment unchanged; some true period labels remain body rows. A rendered-header-only check would incorrectly certify all context. |
| BAC 10-K, table 43 | 2025/2024 income statement, source colspans and unit label. | Actual values stay under their year groups; merged references remain local. Other long tables still have pre-existing period gaps. |
| USB 10-Q 2023, table 35 | Three-month versus nine-month groups, 2023/2022, percentage columns, negative values and lettered markers. | Multi-level groups and row order unchanged. Source visual parentheses/currency columns remain separate; no new normalization was introduced. |
| USB earnings supplement, table 3 | Five quarterly columns, millions/per-share units and `(a)` markers. | Full-width title and repeated date/unit headers remain intact. |

An additional audit checked short adjacent units and linked footnotes: **1,373
of 7,462** row/context pairs were not co-located, versus **4,314** misses in the
baseline. The true-period-row audit found **1,064 of 3,441** missing row/period
co-locations, versus **1,234** baseline misses. No pair that passed in the
baseline newly failed in v6. These are diagnostic heuristics, not independent
financial-accuracy scores; a zero for a document does not certify every
semantic relationship.

The misses include existing lettered-note handling and period/unit labels left
as data rows after title-like first rows. For example, JPM's selected metrics
can repeat a `Selected metrics` header without repeating the 2025/2024/2023 body
row; PNC changes-in-equity rows do not consistently carry the adjacent `(a)`
note. Values are not lost, but independent retrieval may omit their qualifiers.
These pre-existing issues were documented rather than expanded into an unrelated
financial-header rewrite in this task.

## Introduced heading regressions and correction

The v5 nested-CSS inference mistakenly promoted several fully bold prose blocks:
a PNC wrapped cross-reference beginning "For more information", a BAC cybersecurity
sentence ending in a comma, a WFC resolution introduction ending in a colon,
salutations/date labels, and JPM cover-page numeric label/value disclosures.
The resulting `SectionTitle` could propagate into unrelated following content.

v6 conservatively excludes those shapes for **new inferred CSS headings**:
sentence/list-introduction punctuation, date-only blocks, terminal numeric
label/value disclosures, and a bold block followed by a lowercase bold
continuation. Explicit source headings and established bold-heading behavior
remain unchanged. Synthetic fixtures cover these shapes, real headings, financial
headlines containing amounts, and section propagation. A two-page synthetic
financial fixture verifies multi-level date headers, units, equal independent
values, colspans, and attached notes.

The concrete false headings were absent in final replay; the PNC pay-ratio
heading/disclosure stayed coherent. Recognized Markdown headings never mixed
across emitted sections. This does not certify every inferred heading by human
review or rule out stale context after **unrecognized** source headings, which
is an existing heuristic limitation.

## Live pilot compatibility and staged proposal

The refined PNC document has **556 items**, versus the frozen live candidate's
566. It has 554 shared IDs, two new IDs and 12 stale IDs; only seven entire
payloads are unchanged, largely because ordinals and section metadata shift.
The pay-ratio item keeps the same ID and identical 2,477-character content, but
its ordinal changes from 429 to 422. **Neither live connection was updated.**
The user's three successful candidate attempts remain observations of frozen
v5, not a runtime acceptance test of v6.

1. Review the exact v6 commits and this report. Do not promote frozen v5 merely
   because the live proxy answer succeeded; its newly observed false headings
   are now known. Decide explicitly whether existing table-context gaps are
   acceptable for a limited trial or need a separate fix first.
2. Obtain separate approval for a bounded v6 destination/retest and exact
   accession/document allowlist. Preserve v4/v5 evidence and keep agent
   instructions/skills fixed. The current pilot loader is create-only with no
   deletion; it is not an authorized replacement/reconciliation tool.
3. Before any separately approved staged reprocessing, stop the destination
   writer, back up its state and acknowledged/potentially delivered manifests,
   pin code/schema/settings, and record exact old/desired IDs and hashes.
   Complete the **whole approved filing's** intended document inventory, or use
   a reviewed exact-document replacement implementation. Ticker/date scope is
   not an exact-document allowlist.
4. Upgrade v5 caches/manifests explicitly to **v6**. Ordinary resume replays
   captured prepared payloads; it must not be assumed to rebuild them. Keep
   acknowledged and potentially delivered old IDs while rebuilding desired
   payloads. Avoid broad `--reprocess`, date-only scope and global pruning.
5. Acknowledge **every desired upload** before deleting only approved scoped
   stale IDs. Any preparation/upload/inventory failure blocks stale deletion.
   Checkpoint each acknowledgment; retain failed deletions for recovery. Never
   erase state or prune an entire filing merely to clean up shifted chunk IDs.
6. Verify item readback and independent search readiness, then repeat controlled
   proxy/financial/period/neighbor queries. Stop on regressions before widening
   the batch. No stage described here has been executed.

Rollback is not just restoring SQLite or a Git revision: overlapping Graph IDs
may already hold new content. Restoring a prior destination requires replaying
the complete backed-up old payload set and acknowledging it before removing
new-only IDs within the same approved scope. Preserve receipts and coordinate
writers; do not roll state backward while leaving remote content forward.
Index propagation makes replacement non-atomic, so freeze evaluation during
changes. Retaining isolated v4/v5 connections is safer for comparison.

## Reproduction and artifacts

`tests.corpus_replay` accepts the private frozen manifest and a **new** output
directory; `tests.corpus_compare` reads two saved runs. They never discover,
download or upload content. From this repository, use the existing Python
environment without reinstalling it:

```powershell
$env:PYTHONPATH = '<absolute source directory of revision under test>'
python -m tests.corpus_replay --manifest '<private manifest-v6-final.json>' --output '<new private output>'
python -m tests.corpus_compare --baseline '<private baseline output>' --candidate '<new private output>' --output '<new comparison.json>'
```

Private artifact group `corpus-v1` keeps immutable `baseline`, original
`candidate` (v5), intermediate `candidate-v6`, and final `candidate-v6-final`
directories distinct. `manifest-v6-final.json`, `comparison-v6-refined.json`
and `promotion-summary.json` identify final evidence. Each document has parsed
Markdown, payloads, source-cell/table observations and machine-readable results.
No raw corpus or local source paths are committed.

Set `SEC_CORPUS_EVIDENCE` to that private artifact group to enable the frozen
receipt/source-hash audit in `tests/test_corpus_replay.py`. Set the existing
`SEC_EVIDENCE_PILOT_SOURCE` and `SEC_EVIDENCE_PILOT_BASELINE` variables to enable
the positive-control source replay. Use an isolated pytest `--basetemp`.

Final verification: **357 tests passed**, with both optional cached-source audits
enabled and no skips. The only warning was the existing Pydantic class-based
configuration deprecation. Final source hashes still matched the frozen manifest;
the replay/comparison script hashes matched the published provenance.
