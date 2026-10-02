# Scoped maintenance: live storage validation

**Provisional pending live agent response acceptance.** This report records one
approved production update, not universal filing support, retrieval quality or
customer acceptance. No tenant identifiers, credentials, private paths, raw
receipts or reusable production plan are included.

## Executed scope and result

On October 2, 2026 (UTC), the reviewed maintenance implementation updated one
completed, unsampled proxy-statement document that was the sole persisted document
in its filing. OCR was disabled. The operator explicitly confirmed all writers
were stopped and approved the exact reviewed plan, recovery backup and permanent
state-format change before application.

| Check | Result |
|---|---:|
| Original tracked and remotely verified items | 1,091 |
| Desired items | 556 |
| Changed shared IDs | 520 |
| Originally absent new IDs | 36 |
| Old-only stale IDs | 571 |
| Independent post-apply exact desired GET matches | 556 |
| Independent post-apply stale 404s | 571 |
| Desired items retaining the removed `ReportPeriodEnd` property | 0 |
| Final local chunks / delivered hashes / reconciliation candidates | 556 / 556 / 0 |

The source and effective processing options matched the approved frozen v8
payloads exactly. Preparation found no old remote-payload or schema drift.
Application completed without a recovery retry or rollback. Every desired PUT
had durable intent, acknowledgment and exact GET verification; journal timestamps
confirmed the full desired verification gate preceded stale DELETE intents.
Stale items were checked against their original payloads before deletion and
confirmed absent afterward.

A separate read-only verification repeated all 1,127 desired/stale observations.
The selected filing was completed with the correct desired cache, fingerprint,
processing options and delivered hashes. Processing remained **v8**; the
destination database became **format 4**. Unrelated filing/document/chunk/cache/
delivery/reconciliation/run rows matched their pre-run hashes. Source,
configuration and environment-file hashes and modification times were unchanged.
The apply process exited and the local destination lock was available and released.

The consistent SQLite backup passed integrity checking and retained the original
format-3 scope and unrelated rows. Private recovery evidence retained the complete
reviewed plan, 1,091 old replayable remote observations and 36 initial absence
observations. Recovery artifacts and the newer runtime remain retained.

## Validation boundaries

The implementation's full offline suite passed **515 tests**, with four existing
private-corpus opt-ins skipped. This includes **66 maintenance tests** covering
WAL-consistent backup, old-reader rejection, normal-command guards, drift,
ambiguous mutation outcomes, property-removal failure, atomic checkpoints and
resumable rollback.

Live interruption/resume and live rollback were **not exercised**. Their evidence
is offline failure injection. Readback is not transactional across Graph items,
and exact storage equality/404 does not prove indexing readiness, retrieval
quality or Copilot accuracy. No agent configuration was changed and no user
answer-acceptance result is claimed. No additional live batch is authorized by
this result.

Use the [provisional operator procedure](maintenance.md) only for its supported
completed, unsampled, sole-document, OCR-disabled scope. Multi-document and
in-flight filings are not supported by this command. Format 4 remains after
rollback; older connector executables cannot reopen the database. A database or
Git restore alone is not a Graph rollback.

## Acceptance prompts for the next human review

Use fresh chats with the intended connection selected, retaining the existing
agent configuration. Record the agent version, knowledge binding, prompt,
response, citations and test time. Substitute the actual issuer and stated
compensation year; do not inject expected answers into the prompt.

> For [issuer], report the CEO's total compensation, median employee's total
> compensation, and CEO-to-median-employee pay ratio for [year]. Cite the source
> section supporting each figure and state the compensation year explicitly.

> Distinguish the filing date, annual meeting date and compensation year in that
> disclosure. Does the annual meeting date establish a fiscal report-period end?
> Cite the source and do not infer an unstated period.

> Summarize the compensation disclosures immediately before and after the CEO pay
> ratio section. Preserve their stated periods and table/footnote context, and
> cite the supporting sections.

Accept accurate, source-grounded answers and relevant citations, not merely the
presence of new item counts. Keep broader maintenance batches gated on that
human acceptance and a separate scope-specific authorization.
