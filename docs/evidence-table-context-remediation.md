# Offline financial-table context remediation (v7)

## Decision

**The bounded repair is ready for review, not unrestricted rollout.** It fixes
common source-backed period/header/unit bands and explicit linked notes without
changing the parser's cells, flattening new relationships, or guessing fiscal
periods. Complex financial header exclusions remain; accepting those exclusions
for a bounded retest or expanding source-structure-aware header handling requires
a parent/user scope decision. No live retest or rollout was performed.

This follows the [v6 corpus assessment](evidence-corpus-validation.md).
The exact same 20 cached sources and parameters were used, without downloads,
original SQLite/cache writes, shared-environment edits, tenant writes,
agent/skill changes, main merge or push. The original v4/v5/v6 evidence is intact.
The [machine-readable v7 matrix](evidence-table-context-results.json) records
public source identities/hashes, pinned code and runner hashes, limits and
per-document outcomes. Raw source, row examples, payloads and logs remain private.

The final replay pins code revision `4a06538` (with preceding scoped commits
`8e5c500`, `f28b02c`, `f468424`) against frozen v6 `ffb34ac`.

## Implementation and safety controls

Processing version is **7**, separate from frozen offline v6 and live v5.
Prepared manifests still replay their captured payloads on ordinary resume;
rebuilding with these semantics requires separately approved explicit
reprocessing. This is not an implicit upgrade of existing live items.

The change is in table splitting, not HTML parsing. It preserves original
Markdown rows and column positions, including merged-cell references, currency
columns, equal independent values, units and per-share exceptions. A contiguous
leading band of source rows is repeated only when anchored by explicit
year/quarter or unit/schema evidence. Empty-stub grouping rows can precede that
anchor. Monetary values, narrative/data stubs, date-as-data rows and unanchored
label bands stop inference. Existing nested styled-heading and proxy packaging
logic is unchanged.

Contiguous following note definitions are associated by explicit parenthesized
or bracketed letter/numeric markers, including comma-separated reference groups.
A header reference applies to its table segments; a data-row reference carries
its definition with that row's segment. Notes are appended after rows, and their
original occurrence remains in source order. Standalone negative numeric values,
unrelated notes, duplicate definitions and preceding-table notes are not rebound
as evidence. No note/header association is inferred across a source page or
section boundary.

Every repeated header, caption and note consumes the existing character and
UTF-8 budget after metadata reservation. When even an intact row plus its
qualifiers cannot fit, the code logs the missing co-location explicitly and
retains the original note in adjacent prose; it never truncates the note.
Oversized rows/headers retain the existing logged, ordered-fragment fallback.
Synthetic controls exercise both failures. Such chunks require adjacent-context
retrieval; bounded output is not a claim of self-contained evidence in that case.

## Evidence and interpretation

| Check | Frozen v6 | Reviewed v7 |
|---|---:|---:|
| Items across the same 20 documents | 6,982 | 7,471 |
| Missing period-row co-locations, out of 3,441 checks | 1,064 | 169 |
| Missing explicit linked-note co-locations, out of 5,414 checks | 1,888 | 0 |
| Original broad adjacent-context misses, out of 7,462 checks | 1,373 | 1,018 |
| New period / explicit linked-note / unit-label misses | N/A | 0 / 0 / 0 |

Thus 895 measured period gaps and all 1,888 measured explicitly linked-note
gaps were resolved. The repeated context increases output size: that is an
intentional tradeoff, not lost batching efficiency to hide. Maximum content
is **7,998 characters** including metadata; maximum serialized request is
**10,003 bytes**, below the unchanged 30 MiB ceiling. No oversized-context,
row-fragment or ambiguous-definition warnings occurred in this corpus.

All parsed text and source-cell/table conversion observations are exactly
unchanged from v6. Ordered lexical/numeric output coverage, exact rendered
row/header coverage, request limits, identities/ACLs, fiscal metadata, stable
repeat-run IDs and recognized-heading consistency pass for every document.
An additional occurrence audit checks that repeated source context cannot
conceal lost duplicate data rows or unexplained extra middle rows. These checks
complement, rather than replace, the synthetic negative controls on inference.
The unchanged parser retains the same 1,660,777 lexical and 223,297 numeric
tokens and all 5,259 source-table conversion observations; all 29,802 original
Markdown data rows retain their rendered headers and occurrence coverage.

The original broad adjacent-context diagnostic is **unchanged**. It demands
that a note referenced anywhere in a table accompany every row, even rows that
do not carry that reference. The new marker-scoped audit is separately reported:
it checks contiguous, explicit definitions on the rows/header carrying their
marker. Neither metric certifies all footnotes in all documents.

Some broad diagnostic pairs become missing intentionally: for example, a BAC
row marked `(4)` no longer receives a `(1)` definition merely because another
row references `(1)`. There are no newly missing explicit linked-note pairs or
unit-label pairs. Treating the disappearance of these unrelated repetitions as
a real evidence loss would encourage incorrect attribution. Both before/after
metrics and the new broad misses remain available in the private receipts.
There are **558 new broad-diagnostic misses** of this kind (all note-shaped,
not units); 913 old broad misses are resolved. The original diagnostic was not
relaxed or replaced to obtain a passing result.

## Source-backed review examples

| Source | Relationship inspected | Outcome |
|---|---|---|
| JPM annual selected metrics and selected income statement | 2025/2024/2023 year row and millions/per-share exceptions previously left in the body under a generic header. | Leading year/unit rows repeat verbatim; actual financial data rows remain in their original order. |
| PNC annual changes in equity | `(a)` on dated balance rows and the following preferred-stock par-value exclusion. | The lettered definition travels with marked balance rows. Account-label/unit schema repeats; the note is not assigned to every unrelated transaction. |
| WFC quarterly summary | Quarter-ended, six-month, percent-change groups and their actual date rows. | Source multi-level rows and merged-column references repeat together; no inferred new period or value. |
| USB quarterly average balances | Source 2023/2022 comparative label, balances/interest/yield groups, millions/unaudited label. | Literal `v` comparison syntax is recognized as a date-band label, not rewritten in output. |
| BAC commercial credit exposure | Utilized/unfunded groups, combined `(2, 3, 4)` markers and September/December date columns. | Grouped references preserve each explicit definition; financial parenthesized amounts are not split into note references. |

The remaining cases are not hidden as generic successes. They include Level-3
fair-value rollforwards in PNC/JPM with domain numbers, long narrative qualifiers
and mixed dated captions, and certain BAC exposure/change header labels. These
are often visibly headers to a human, but broadening text-only inference to
arbitrary numeric prose risks treating financial observations as repeatable
schema. Resolving them safely should use explicit source-structure evidence,
with new positive/negative fixtures, rather than another unrestricted label rule.

| Remaining period diagnostic pairs | v6 | v7 |
|---|---:|---:|
| PNC 10-K 2026 | 53 | 8 |
| PNC 10-Q 2026 | 60 | 16 |
| JPM 10-K 2026 | 126 | 49 |
| JPM 10-Q 2024 | 109 | 44 |
| BAC 10-K 2026 | 216 | 26 |
| BAC 10-Q 2025 | 286 | 26 |
| Other 14 corpus documents | 214 | 0 |

Do not read this table as 169 independently adjudicated financial errors.
It counts row/context pairs from the unchanged heuristic, with representative
remaining source bands manually inspected. It nevertheless establishes that
the corpus does not yet support a universal self-contained financial-context
claim.

Other untested/ambiguous cases remain: notes across pages, definitions separated
by narrative, duplicate marker definitions, symbol-only notes, indirect
cross-references and qualifiers whose complete bundle exceeds a budget.
The corpus still excludes PDF/OCR, amendments, uncached incorporated reports and
non-bank issuers. Audit counts are diagnostics, not financial accuracy scores.

## Live pilot and reprocessing implications

All **556 PNC proxy payloads are identical to frozen v6**, including IDs,
metadata and content. Against the actual frozen live v5 payloads, v7 retains the
previously documented 554 shared IDs, two new IDs and 12 stale IDs; only seven
whole payloads are identical. The pay-ratio evidence content is unchanged across
v5/v6/v7, with ordinal 429 in v5 and 422 in v6/v7.

The historical user-reported three successes remain evidence for live v5 only.
A future approved v7 retest still needs the v6-equivalent PNC payload replacement;
this table-context repair adds no further PNC payload changes. Other financial
documents do change. Neither live connection was updated.

The [existing staged upload-before-delete/rollback proposal](evidence-corpus-validation.md#live-pilot-compatibility-and-staged-proposal)
still applies, now targeting version 7. Pin the reviewed revision and exact
document/filing scope; preserve old desired/acknowledged/potential IDs; acknowledge
all desired uploads before any separately approved scoped stale deletion.
Mixed index versions are not an evaluation window. Restoring SQLite alone cannot
roll back Graph. No whole-filing/global prune, reset or broad reprocessing is
authorized by this offline work.

## Reproduction

Private group `corpus-v1` contains `manifest-v7-review2.json`,
`candidate-v7-review2`, `comparison-v7-review2.json`,
`linked-audit-v7-review2.json` and `table-context-summary-v7-review2.json`.
Earlier v7 intermediate directories are distinct and are not final evidence.
Select the pinned repository `src` using `PYTHONPATH`; do not reinstall the
shared editable environment. Use fresh output paths:

```powershell
python -m tests.corpus_replay --manifest '<private manifest-v7-review2.json>' --output '<new output>'
python -m tests.corpus_compare --baseline '<frozen candidate-v6-final>' --candidate '<new output>' --output '<new comparison.json>'
python -m tests.table_context_audit --baseline '<frozen candidate-v6-final>' --candidate '<new output>' --output '<new linked-audit.json>'
```

Enable `SEC_TABLE_CONTEXT_EVIDENCE` for final v7 receipts and source-hash checks.
Keep `SEC_CORPUS_EVIDENCE`, `SEC_EVIDENCE_PILOT_SOURCE` and
`SEC_EVIDENCE_PILOT_BASELINE` enabled for the historical corpus and actual-source
positive control, with an isolated pytest `--basetemp`.

Final verification: **401 tests passed**, with all optional real-source and
frozen-corpus audits enabled and no skips. The only warning is the pre-existing
Pydantic class-based configuration deprecation.
