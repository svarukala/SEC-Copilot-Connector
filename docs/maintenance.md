# Scoped in-place maintenance

**Validated for the supported single-document, non-OCR scope**, through one
approved PNC update with live storage verification and bounded agent acceptance;
see the [sanitized validation result](maintenance-live-validation.md).
Rollback and interrupted-operation recovery are covered by offline failure
injection, not by a live rollback exercise. This is not validation for all filings.
Installing or merging this code does not authorize production changes.
Obtain a separate execution approval after reviewing the frozen plan and backup
retention. `apply`, maintenance `resume`, and `rollback` perform real Graph
overwrites/deletions. There is no transaction spanning Graph and SQLite.

## Operator checklist

1. Install the reviewed build containing `maintenance --help`; retain that exact
   executable/environment through recovery. An older editable checkout or entry
   point is not made compatible merely by updating another checkout.
2. Confirm the supported sole-document/OCR-disabled scope below. Stop all
   local, scheduled and other-machine writers and retain a private recovery area.
3. Run `prepare`, then `inspect`; review the new plan's exact IDs, content,
   properties, ACLs and digest. Never reuse another customer's plan or receipts.
4. Obtain explicit approval for that digest, scoped writes, backup retention and
   permanent state format 4. Run `apply` with a new recovery directory.
5. On interruption use the same plan with maintenance `resume`, not normal
   `resume` or `reset`. Authorize `rollback` separately if reversal is required.
6. Inspect completed checkpoints and verify the desired/stale sets and local
   state. Keep the newer runtime and recovery evidence. Allow indexing, then
   obtain live agent-answer acceptance before authorizing another batch.

## Install or update before preparing a plan

Obtain the reviewed `main` release from the
[repository](https://github.com/svarukala/SEC-Copilot-Connector) using your
organization's approved source-control process. Preserve your existing
configuration, environment credentials, destination database and cached downloads;
do not replace them with sample settings. Stop all writers before updating.
From the updated repository root, use your intended Python environment and
approved package repository configuration, as in [operations](operations.md):

```powershell
# Configure pip to use your organization's approved package source first.
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: .
.\.venv\Scripts\python.exe -m sec_connector maintenance --help
```

These are customer installation instructions, not a request to reinstall a
shared environment during recovery. Retain the same installed build and
dependencies from prepare through completion/recovery. Do not update code or
dependencies in an unfinished operation. If using an editable checkout or
`PYTHONPATH`, confirm it resolves to the intended reviewed source, not an older
checkout. Use `python -m sec_connector` from that environment rather than a
possibly stale `sec-connector` executable on PATH.

## Supported scope and prerequisites

This first release handles exactly one explicitly selected `.htm` or `.txt`
document that is the **sole persisted document in a completed, unsampled,
inventory-complete filing**. All old chunks must be acknowledged, the old
delivered hashes and cached payloads must agree, and reconciliation must be empty.
It does not rediscover SEC inventory, download source, provision a connection,
change schema, enumerate untracked remote items, prune other filings, or deploy
agents/skills. Incomplete/in-flight/multi-document filings and OCR (old or new)
are rejected, not silently downgraded. Local-image/OCR provenance is not supported.

Use the existing destination-bound format-3 (or already upgraded format-4)
database, cached source and approved
configuration. The supplied source must reproduce the **old cache fingerprint**.
Both old and desired payloads must use the connector's existing everyone/grant
ACL, exact CIK/accession/filename/sequence/derived DocumentId and bounded item IDs.
Foreign/local cross-filing IDs, occupied desired-only IDs, remote/local old
payload differences, and incompatible schemas block preparation/application.

Stop normal ingestion and scheduled jobs. Quiesce **all** other-machine and
out-of-band writers and keep them stopped throughout maintenance or rollback.
The destination OS lock excludes cooperating local processes only; it is not
a distributed Graph lease. Already-running old clients on another machine are
not stopped by a database version change. `--maintenance-ack` is the operator's
explicit acknowledgement of that responsibility and authorization for scoped
remote writes. Do not delete lock files or forcibly terminate another writer.

## Prepare and review (no source-state or Graph mutations)

The standard `-c` configuration selects credentials and the destination database
base path. Optional top-level `-n` selects an **exact**, unsanitized connection ID.
Use the same working directory and resolved database path for all steps.
Choose an existing, access-restricted directory **outside the repository** for
plans and recovery: these contain full filing content, ACLs, identity and local
state; the database backup also contains unrelated filings. Never commit them.
The tool does not change OS permissions, encrypt artifacts, or save credentials.

Illustrative PowerShell forms (replace placeholders with the approved scope):
Select the exact CIK, accession, filename and sequence from the persisted
sole-document inventory, not just a ticker/date guess. Use its existing cached
source bytes; do not substitute a freshly downloaded or manually edited document.
The source path below is illustrative, not a required cache location.
All commands use the same config and working directory so relative database/cache
paths resolve consistently. Confirm `azure.connection_id` is the intended
populated connection; if overriding it, use the same exact top-level `-n` value
for every command. Do not run setup/reset to adopt or recreate the connection.

```powershell
.\.venv\Scripts\python.exe -m sec_connector -c .\config\config.yaml maintenance prepare `
  --cik "<10-digit-CIK>" --accession "<accession>" `
  --filename "<filename.htm>" --sequence 1 `
  --source "C:\private\cached\<filename.htm>" --out "C:\private\upgrade-plan.json"

# Copy the digest printed by prepare; do not regenerate it after editing a plan.
.\.venv\Scripts\python.exe -m sec_connector -c .\config\config.yaml maintenance inspect `
  --plan "C:\private\upgrade-plan.json" --plan-digest "<reviewed-digest>"
```

`prepare` opens SQLite with `mode=ro`, without StateManager initialization,
migration or acquiring the destination lock. It uses production
`parse_document -> chunk_with_limit -> GraphClient.build_payload`, and the
same cache fingerprint function as ingestion. Processing semantics remain v8.
It freezes source hash, processing configuration/module/dependency versions,
tenant/app/connection/path, full schema hash, scoped local rows, raw old remote
responses, replayable normalized old payloads, desired payloads and hashes,
exact new/stale IDs, and observed 404 timestamps. The output must be a new file.

`inspect` requires no authentication and does not acquire a lock or migrate
state. It reads the frozen plan and, if activated, durable per-ID checkpoints.
It does **not** refresh remote state or assert that the plan remains applicable.
Review the complete plan's exact ID sets, ACL, content/property differences,
source/config provenance, and expected overwrite/deletion scope, not just counts.
A digest binds the reviewed artifact; it is not a signature or access-control
mechanism. Apply refreshes observations rather than trusting an old preflight.

## Apply after explicit approval

```powershell
.\.venv\Scripts\python.exe -m sec_connector -c .\config\config.yaml maintenance apply `
  --plan "C:\private\upgrade-plan.json" --plan-digest "<reviewed-digest>" `
  --recovery-dir "C:\private\new-unique-recovery-directory" --maintenance-ack
```

Application holds the destination lock and rechecks identity, code/config,
source, schema, local scope/ownership, every old remote payload and every new
ID's absence. Before the first PUT it creates a consistent **SQLite backup via
the backup API**, integrity-checks it, and retains refreshed remote receipts
and the complete plan in `recovery.json`. Missing/corrupt recovery evidence
blocks both forward continuation and rollback. Failed capture does not activate
maintenance; preserve partial artifacts and retry with a different new recovery
directory after resolving the error.

**State format 4 is a permanent compatibility boundary, separate from processing
version 8.** Activation atomically upgrades format 3 to 4, inserts the operation
guard, installs the desired chunks/cache/options with a noncompleted filing,
and preserves old delivered IDs plus all potentially delivered IDs. The released
format-3 reader accepts only versions 1/2/3 and therefore rejects format 4 before
schema writes. New normal `setup`, `ingest`, `resume`, `reset` (and `status`)
refuse unfinished maintenance before network work. Do not manually change the
format number or remove the guard. Format 4 remains after completion **and rollback**;
old installed executables cannot reopen this database. Ordinary untouched
databases remain format 3; maintenance does not implicitly migrate formats 1/2.

Uploads are intentionally sequential (concurrency one, within the five-request
bound). Every mutation has a durable intent before dispatch; PUT ACK and exact
GET checkpoints live in the operation journal. Ordinary chunks stay pending and
old delivered hashes remain retained until the final atomic transition.
Transport does not automatically retry mutations; rerun the maintenance recovery
command after resolving transient failures.

A property-removing shared overwrite is checked early. The full desired property
bag, content and ACL must match on every desired GET; omission of an old property
such as `ReportPeriodEnd` must actually remove it. No null/date workaround or
delete/recreate fallback is used. Only strictly typed known service-added metadata
and OData annotations are excluded from comparison.

All desired PUTs must be acknowledged and the entire desired set GET-verified
before a durable verification gate permits any stale deletion. Each stale ID is
GET-checked against its original payload/scope immediately before its single
DELETE attempt, then confirmed 404. Already-absent IDs are explicitly recorded.
The final desired set and stale absence are checked again; only then does one
transaction mark the filing completed and install exact desired delivered hashes.
Unrelated filings are not reset or rewritten.

## Forward recovery versus rollback

```powershell
# Continue the same frozen operation, not ordinary "sec-connector resume".
.\.venv\Scripts\python.exe -m sec_connector -c .\config\config.yaml maintenance resume `
  --plan "C:\private\upgrade-plan.json" --plan-digest "<reviewed-digest>" --maintenance-ack

# Separately authorize reversal. Repeat this same command to resume a rollback.
.\.venv\Scripts\python.exe -m sec_connector -c .\config\config.yaml maintenance rollback `
  --plan "C:\private\upgrade-plan.json" --plan-digest "<reviewed-digest>" --maintenance-ack
```

Forward recovery uses persisted payloads, not reparsing. It rechecks source,
processing/runtime provenance, schema, local state, remote values and the complete
desired verification gate. Lost ACKs are reconciled by GET followed by an
idempotent replay of the exact payload; an intent is not proof of delivery.
Unknown DELETE outcomes are reconciled by GET/404 or a freshly checked retry.
Any drift or failure returns nonzero and retains the guard and exact checkpoints.
Do not edit payloads, acknowledgement flags, cache, state or the reviewed digest.

Rollback restores and exact-GET-verifies **the entire old remote set first**,
including overwritten common and already-retired IDs. Only afterward can it
delete originally absent new IDs for which this operation recorded PUT intent,
and only if their current values still match this operation. Unowned or changed
items are never deleted. Finally it restores only the selected filing's old local
rows/cache/options in one transaction and marks the operation rolled back.
Once rollback starts, forward resume is refused. Rollback may also be requested
after completion, but only while the selected local state still exactly matches
this operation; later ingestion/reset can invalidate it.

Rollback needs its frozen plan/recovery evidence and compatible identity/schema,
but not the original source or original parser installation; it replays captured
old payloads. Configured request-size limits still apply. Keep a known-good
installation available for forward recovery, which rejects processing drift.
The recovery file retains a copy of the plan if the standalone plan is lost.
Do not overwrite the entire destination database from its backup as an automatic
rollback step: it could erase unrelated work. **Git rollback or SQLite restore
alone does not restore Graph.** Backups and operation history are retained; no
automatic cleanup is performed.

## Limits and live release gate

Graph reads are serial observations, not a transactional snapshot. Search can
temporarily expose mixed old/new content, and indexing is asynchronous. Exact
storage readback/404 does not establish indexing readiness or Copilot accuracy.
No untracked global IDs are enumerated. Failures/drift can require operator
investigation rather than automatic completion; the guard intentionally remains.

The recorded live run confirmed property removal and complete storage
verification/retirement. The first PNC-only update also passed its bounded agent
acceptance set; storage checks alone did not establish that result. For each
new scope, allow indexing and obtain acceptance of the relevant Copilot prompts
with documented bindings and controls. Each customer's scope still needs its
own plan, review and authorization. This is not an all-filings procedure; no
further live mutation is implied by the tests or this report.
