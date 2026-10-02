# Scoped in-place maintenance

**Validated for the supported single-document, non-OCR scope**, through one
approved PNC update with live storage verification and bounded agent acceptance;
see the [sanitized validation result](maintenance-live-validation.md).
The prepared-delivery and local rotated-image OCR extensions below have **offline
coverage only**, not customer/live acceptance. Rollback and interrupted-operation
recovery are covered by offline failure injection, not a live rollback exercise.
This is not validation for all filings or general scanned-document OCR.
Installing or merging this code does not authorize production changes.
Obtain a separate execution approval after reviewing the frozen plan and backup
retention. `apply`, maintenance `resume`, and `rollback` perform real Graph
overwrites/deletions. There is no transaction spanning Graph and SQLite.

## Operator checklist

1. Install the reviewed build containing `maintenance --help`; retain that exact
   executable/environment through recovery. An older editable checkout or entry
   point is not made compatible merely by updating another checkout.
2. Confirm the supported sole-document eligibility and OCR inputs below. Stop all
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

Maintenance handles exactly one explicitly selected `.htm` or `.txt`
document that is the **sole persisted document in a completed, unsampled,
inventory-complete filing**. All old chunks must be acknowledged, the old
delivered hashes and cached payloads must agree, and reconciliation must be empty.
It does not rediscover SEC inventory, download source, provision a connection,
change schema, enumerate untracked remote items, prune other filings, or deploy
agents/skills. An explicit `prepare --recover-prepared` permits the bounded
interrupted-delivery alternative below; it does not waive inventory or ownership
checks. Multi-document migration is not supported.

| Persisted class | Safe route / boundary |
|---|---|
| Completed, unsampled, sole parsed document; consistent acknowledged payloads/cache | Standard maintenance, subject to exact source and remote checks. |
| Complete inventory and fully prepared sole-document manifest; partial acknowledgments or lost PUT ACK | Prefer ordinary `resume` to finish the old generation. Opt-in `--recover-prepared` can instead freeze a replacement if every tracked ID has an exact retained payload, each acknowledged hash agrees, and every remote value matches that payload or is an allowed 404. |
| All prepared items remotely absent, none acknowledged | Same opt-in, only with a complete nonempty retained manifest/cache and proven local ownership. An empty observed remote baseline is **not** permission to adopt an untracked filing. |
| Failed download/parse, missing source/cache/payloads, missing or incomplete inventory, no documents | Not reconstructable by maintenance. Restore the captured inputs/settings and investigate ordinary resume under separately approved scope. Do not mark inventory complete manually. |
| Prior-generation delivered hash differs, acknowledged item missing remotely, unmatched reconciliation ID, foreign remote value or cross-filing collision | Fail closed. Preserve state and receipts; investigate ownership/history. No automatic overwrite, delete, adoption or discard. |
| Sampled, retiring, multi-document, or running/interrupted run record | Not supported. Resolve the original run/scope separately; do not delete run records or clear guards to force eligibility. |

Ordinary `resume` operates on **all** queued filings at the destination, not this
one selected document, and can download missing inputs and perform writes/deletes.
Use it only after reviewing that scope, captured processing version/schema,
ownership and authorization. It replays already prepared payloads without
upgrading them; after successful completion, prepare a separate maintenance plan.
It is not an ownership-repair tool for ambiguous or foreign remote data.

For opt-in prepared delivery, the plan separates the original **local prepared
manifest** from the **actually observed remote baseline**. A pending item matching
its retained payload is a verified potentially delivered item, not a fabricated
local ACK. A pending 404 stays an explicit absence. Known old-only absent IDs are
never deleted and must stay absent through completion/recovery. An acknowledged
404 is disagreement, not an eligible absence. Rollback restores only the observed
remote set and the exact original incomplete local checkpoints; it does not
upload previously absent pending items or mark the old filing completed.

Use the existing destination-bound format-3 (or already upgraded format-4)
database, cached source and approved
configuration. The supplied source must reproduce the **old cache fingerprint**.
Both old and desired payloads must use the connector's existing everyone/grant
ACL, exact CIK/accession/filename/sequence/derived DocumentId and bounded item IDs.
Foreign/local cross-filing IDs, occupied desired-only IDs, remote/local old
payload differences, and incompatible schemas block preparation/application.

### Local rotated-image OCR

Set `processing.ocr_images: true` in the reviewed configuration when OCR is
required. Captured old OCR-enabled settings must not be silently switched off.
Eligibility follows the production v8 parser: selected SGML document, hidden
content removal, then visible narrow/tall `<img>` elements in source order.
Ordinary images, hidden images and other SGML documents are not OCR inputs.
An inherited `ocr_images: true` with no applicable images needs no OCR engine.
This is **not** PDF OCR, arbitrary scanned-page OCR, remote image retrieval, or
automatic language selection.

Supply the existing HTML/text and predownloaded referenced images under its
parent directory (the approved bundle root). No images or language models are
downloaded. Missing assets, absolute/remote/data URLs, traversal, URL query or
fragment ambiguity, and symlinks/junctions/reparse points fail closed. Keep the
bundle and runtime unchanged until forward recovery finishes.

Format-2 plans retain source bytes, each actually consumed image's bytes/hash,
original reference and exact resolved path, cleaned OCR text, and desired payloads.
They bind Python/platform and dependency versions, the resolved Tesseract binary
and default `eng.traineddata` hashes, engine/language inventory, relevant
environment settings, and the existing `--psm 7`, rotation/upscaling settings.
An unavailable engine or unidentifiable default English model blocks preparation
when OCR inputs exist. Recovery checks provenance but **never reruns recognition**.
No provenance fields are added to Graph properties/content.

Older cache fingerprints bind source HTML and settings, **not historical image
bytes**. Plans label that historical OCR provenance unknown; only exact stored
old payloads plus matching remote receipts justify rollback. Current reviewed
assets cannot retroactively certify old images or OCR accuracy. The desired
cache/options include a bundle hash so ordinary source-only refresh cannot
mistakenly reuse this OCR cache. Ordinary ingestion's OCR behavior is unchanged.

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

Only for the eligible fully prepared interrupted-delivery class, add
`--recover-prepared` to the same exact-scope `prepare` command. It remains GET-only
and does not run ordinary resume automatically. Review actual remote old/absent
sets as well as local checkpoint counts; those counts can legitimately differ.

`prepare` opens SQLite with `mode=ro`, without StateManager initialization,
migration or acquiring the destination lock. It uses production
`parse_document -> chunk_with_limit -> GraphClient.build_payload`, and the
same cache fingerprint function as ingestion. Processing semantics remain v8.
It freezes source hash, processing configuration/module/dependency versions,
tenant/app/connection/path, full schema hash, scoped local rows, raw old remote
responses, replayable normalized old payloads, desired payloads and hashes,
exact new/stale IDs, and observed 404 timestamps. The output must be a new file.
New plans use **plan format 2**; SQLite remains format 3 until activation.
OCR bytes/outputs are included when applicable.

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

### Existing plans and version boundaries

Plan format 2 is separate from state format 4 and processing version 8. Neither
the state schema nor v8 content semantics changed for these extensions. Existing
format-1 plans remain readable/inspectable and eligible for source-free rollback,
with their original payloads, cache/options, digest and recovery evidence.
**There is no automatic plan migration or digest rewrite.** Forward apply/resume
still requires the exact code/dependency/config provenance captured at prepare:
use the retained original runtime to finish a format-1 operation, or separately
authorize rollback. New code intentionally refuses forward code drift rather
than silently blessing new processing. Old maintenance executables reject
format-2 plans; old format-3-only state readers still reject activated format 4.
Never change either version number manually.

The offline extension suite uses synthetic HTML/PNG inputs, fake Graph outcomes,
and stub image decoding/recognition; it exercises production OCR discovery,
rotation/upscaling/cleanup and frozen-output replay. A sanitized format-1 fixture
was generated by the original `53dd715` implementation. The complete suite passed
601 tests (four existing private-corpus opt-ins skipped). Pillow, pytesseract and
Tesseract were **not installed in that validation environment**; no actual-engine
accuracy or real OCR-corpus validation is claimed. No shared dependencies were
installed and no customer state/source or tenant was accessed.

### Real-engine acceptance case (blocked; source independently checked)

The coordinating customer-worksheet review reported an OCR-dependent case in
PNC's 2025 proxy, `d889589ddef14a.htm`, accession `0001193125-25-052937`, printed
page 25, **Transactions with directors in 2024**. The charity row has six
markers, while all 13 director-name headers are narrow rotated JPEGs with
`alt="LOGO"` and remain `[rotated text]` with v8/OCR disabled. A separately
authorized pilot should verify the actual engine's director-name recognition,
column ordering, and association of the six markers with the correct names.
Neither provenance capture nor synthetic tests establish that result.

A subsequent, explicitly authorized read-only check on October 2, 2026 copied
the exact cached HTML into private session artifacts and downloaded **only its
13 referenced JPEGs** from the public SEC archive, using an identifying
User-Agent and one request per second. The original source's SHA-256 was
`a78e444a6885c182f38288900af321092d2323edfadc96a16e1b9f010cba5d00`;
its bytes and modification time were unchanged. Images and source content were
not committed to the repository.

Independent visual reading of a clockwise-rotated contact sheet, **before any
OCR execution**, established the following image/header order. The HTML
rowspan-aware source grid independently established the marked columns:

| Director column | Visible source header | Charity marker |
|---|---|---|
| 1 | Joseph Alvarado | No |
| 2 | Debra A. Cafaro | Yes |
| 3 | Marjorie Rodgers Cheshire | No |
| 4 | Douglas A. Dachille | No |
| 5 | William S. Demchak | Yes |
| 6 | Andrew T. Feldstein | Yes |
| 7 | Richard J. Harshman | Yes |
| 8 | Daniel R. Hesse | Yes |
| 9 | Renu Khator | No |
| 10 | Linda R. Medler | No |
| 11 | Robert A. Niblock | No |
| 12 | Martin Pfinsgraff | No |
| 13 | Bryan Salesky | Yes |

The current parser/chunker, run without OCR on the exact table excerpt,
preserved six markers in columns **2, 5, 6, 7, 8, 13**, but emitted
**13 `[rotated text]` headers**. This verifies the input and non-OCR symptom;
it does not measure OCR accuracy or establish a customer fix.

**Real-engine execution remains blocked.** The user subsequently approved
session-local PyPI Pillow/pytesseract wheels and the official-documentation-linked
UB Mannheim engine, but not additional extraction binaries. The Tesseract
5.4.0.20240606 installer was downloaded from the UB Mannheim GitHub release and
verified against the winget SHA-256
`c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9`.
It was **not executed**. Two acquisition requirements remain:

| Requirement | Observed blocker |
|---|---|
| Extract engine without installation | No existing `7z`/`7za` was found in PATH/standard locations. Windows `tar` rejects this NSIS archive as an unrecognized format. Additional extraction tooling requires approval or an existing approved extractor. |
| Install approved OCR wheels in the isolated environment | PyPI metadata is reachable, but `files.pythonhosted.org` wheel retrieval fails TLS negotiation with pip/OpenSSL, PowerShell HTTPS and Windows curl/Schannel. No certificate checks were disabled, mirrors substituted or access controls bypassed. Approved wheel delivery or network remediation is required. |

The supplied connector environment cannot import Pillow; a separate base Python
installation has Pillow but no pytesseract. No OCR dependencies were installed
in any environment. No installer, registry, system PATH or shared environment
was changed. Private source/image hashes, the independent visual reference,
verified installer, exact requested wheel URLs/hashes, empty isolated environment
and comparison script are retained. Once both acquisition requirements are
resolved, compare all 13 names and all six marked columns through the actual
parser/chunker before claiming bounded acceptance. No code, processing version,
plan format or recovery contract changed during this follow-up.

Do not conflate that case with the reported PNC 2023 10-K, printed page 36,
**9.64% CAGR** disclosure: the coordinating review identified it as an HTML
table below `Picture2.jpg`, not an OCR/image-extraction gap. These reported
acceptance targets do not authorize source downloads or customer/tenant writes.

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
