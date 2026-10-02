# Scoped maintenance: live storage validation

**The first PNC-only live upgrade passed its bounded acceptance set.** This report
records one approved production update and its tested prompts, not universal
filing support or retrieval accuracy. No tenant identifiers, credentials, private paths, raw
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

## Bounded PNC agent acceptance

On October 2, 2026 at approximately 12:53 EDT, the user reported trying the
original prompt, **"what is the PNC CEO pay ratio for 2025"**, three times with
**Auto**, with accurate answers every time (**3/3, user-reported**).
At approximately 13:02 EDT, the user explicitly confirmed the supporting-amounts
check: "I validated #1 and it is good, mark it passed." The coordinating review
also assessed the supplied date, methodology and false-premise responses.

| Check | Result and evidence |
|---|---|
| Original simple ratio prompt | Passed: Auto 3/3, user-reported; original response artifacts were not supplied. |
| #1 Supporting amounts | Passed by explicit user validation; this answer was not supplied for independent review. |
| #2 Compensation, filing and meeting dates | Passed: the supplied response distinguished 2025 compensation, March 11, 2026 filing and April 22, 2026 meeting; it included the correct amounts and 226-to-1 ratio, with the primary proxy and an 8-K corroboration. |
| #3 Healthcare and employee methodology | Passed: the user confirmed the prompt numbering; the coordinating reviewer checked the cached source for W-2 Box 5, 56,088 US employees at December 31, 2023, healthcare premiums for both CEO and median employee, and the stated Summary Compensation Table difference. |
| #4 False premise: compensation year 2026 | Passed: the supplied response rejected the 2026 premise, stated 2025 and 226 to 1, and cited the correct proxy. |

The methodology response had a minor completeness note: it could also mention
that the selected median employee was reused because there were no material
workforce changes. This was not judged a wrong answer.

This completes the **first PNC-only upgrade's tested acceptance scope**.
Supplied responses and citations were reviewed for the checks identified above,
but exact runtime knowledge binding, retrieval traces and use of fresh chats
were not independently confirmed. There is no claim of independently captured
response evidence for the original three attempts or #1. No broader issuer/
filing accuracy or additional maintenance authorization follows from acceptance.

## Validation boundaries

The implementation's full offline suite passed **515 tests**, with four existing
private-corpus opt-ins skipped. This includes **66 maintenance tests** covering
WAL-consistent backup, old-reader rejection, normal-command guards, drift,
ambiguous mutation outcomes, property-removal failure, atomic checkpoints and
resumable rollback.

Live interruption/resume and live rollback were **not exercised**. Their evidence
is offline failure injection. Readback is not transactional across Graph items,
and exact storage equality/404 does not prove indexing readiness, retrieval
quality or Copilot accuracy. No agent configuration was changed. The bounded
user/coordinating-review acceptance above is separate from storage verification
and is not a universal accuracy claim. No additional live batch is authorized
by this result.

Use the [operator procedure](maintenance.md) only for its supported
completed, unsampled, sole-document, OCR-disabled scope. Multi-document and
in-flight filings are not supported by this command. Format 4 remains after
rollback; older connector executables cannot reopen the database. A database or
Git restore alone is not a Graph rollback.

## Reusable acceptance prompts

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

> In the same proxy's CEO pay-ratio methodology, how are healthcare benefits
> treated for the CEO and median employee? Cite the disclosure and distinguish
> stated methodology from assumptions.

> Does this proxy disclose the CEO pay ratio for compensation year 2026?
> Identify the compensation year actually supported by its pay-ratio disclosure,
> cite it, and do not relabel a prior-year ratio as 2026.

> Summarize the compensation disclosures immediately before and after the CEO pay
> ratio section. Preserve their stated periods and table/footnote context, and
> cite the supporting sections.

The last neighboring-disclosure prompt is an optional additional control, not
an independently recorded pass in the bounded set above.

Accept accurate, source-grounded answers and relevant citations, not merely the
presence of new item counts. Keep broader maintenance batches gated on that
human acceptance and a separate scope-specific authorization.
