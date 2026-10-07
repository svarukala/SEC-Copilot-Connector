# Scoped in-place maintenance

**Validated for the supported single-document, non-OCR scope**, through one
approved PNC update with live storage verification and bounded agent acceptance;
see the [sanitized validation result](maintenance-live-validation.md).
The prepared-delivery, local rotated-image OCR and complete multi-document
extensions below have **offline coverage only**, not customer/live acceptance.
Rollback and interrupted-operation
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
2. Confirm the supported exact-inventory eligibility and OCR inputs below. Stop all
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

Standard single-document maintenance handles exactly one explicitly selected
`.htm` or `.txt` document that is the **sole persisted document in a completed,
unsampled, inventory-complete filing**. The separate multi-document selection
below handles **every** persisted document in one such filing, with OCR disabled
in both the captured old settings and the desired configuration.
All old chunks must be acknowledged, the old
delivered hashes and cached payloads must agree, and reconciliation must be empty.
It does not rediscover SEC inventory, download source, provision a connection,
change schema, enumerate untracked remote items, prune other filings, or deploy
agents/skills. An explicit `prepare --recover-prepared` permits the bounded
interrupted-delivery alternative below; it does not waive inventory or ownership
checks. That recovery opt-in remains single-document only.

| Persisted class | Safe route / boundary |
|---|---|
| Completed, unsampled, sole parsed document; consistent acknowledged payloads/cache | Standard maintenance, subject to exact source and remote checks. |
| Completed, unsampled, multiple parsed HTML/text documents; complete inventory including primary; uniform OCR-disabled source/cache provenance | Explicit repeated `--document` selection of the entire persisted inventory. One frozen plan, full-manifest activation, and a filing-wide verification gate. |
| Complete inventory and fully prepared sole-document manifest; partial acknowledgments or lost PUT ACK | Prefer ordinary `resume` to finish the old generation. Opt-in `--recover-prepared` can instead freeze a replacement if every tracked ID has an exact retained payload, each acknowledged hash agrees, and every remote value matches that payload or is an allowed 404. |
| All prepared items remotely absent, none acknowledged | Same opt-in, only with a complete nonempty retained manifest/cache and proven local ownership. An empty observed remote baseline is **not** permission to adopt an untracked filing. |
| Failed download/parse, missing source/cache/payloads, missing or incomplete inventory, no documents | Not reconstructable by maintenance. Restore the captured inputs/settings and investigate ordinary resume under separately approved scope. Do not mark inventory complete manually. |
| Prior-generation delivered hash differs, acknowledged item missing remotely, unmatched reconciliation ID, foreign remote value or cross-filing collision | Fail closed. Preserve state and receipts; investigate ownership/history. No automatic overwrite, delete, adoption or discard. |
| Multi-document subset, incomplete delivery, mixed processing provenance, inherited/desired OCR, missing primary, duplicate sequence, unsupported source type | Not supported. No automatic expansion, adoption, partial upgrade, or OCR-disable workaround. |
| Sampled, retiring, or running/interrupted run record | Not supported. Resolve the original run/scope separately; do not delete run records or clear guards to force eligibility. |

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
New bundles identify backend `tesseract-cli-v1` and its explicit configuration.
They bind Python/platform, Pillow version and Python/native file hashes, the
resolved Tesseract binary, adjacent runtime DLLs and `eng.traineddata` hashes,
engine/language inventory, the isolated effective environment, and the existing
`--psm 7`, rotation/upscaling settings. Runtime capture currently requires an
approved bundled Windows engine with adjacent DLLs; arbitrary system-installed
shared-library layouts on other platforms are not certified.
An unavailable engine or unidentifiable default English model blocks preparation
when OCR inputs exist. Recovery checks provenance but **never reruns recognition**.
No provenance fields are added to Graph properties/content.

Older cache fingerprints bind source HTML and settings, **not historical image
bytes**. Plans label that historical OCR provenance unknown; only exact stored
old payloads plus matching remote receipts justify rollback. Current reviewed
assets cannot retroactively certify old images or OCR accuracy. The desired
cache/options include a bundle hash. New ordinary OCR generations bypass the
source-only cache entirely because it cannot certify image/model bytes.
Already prepared payload replay remains source/runtime-independent. The direct
backend preserves preprocessing but replaces pytesseract with bounded subprocess
execution; non-OCR captured options, cache identities and outputs are unchanged.

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
inventory, not just a ticker/date guess. Use its existing cached
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
Single-document plans use **plan format 2**; complete multi-document plans use
**plan format 3**. SQLite remains state format 3 until activation.
OCR bytes/outputs are included only in eligible single-document plans.

### Explicit complete multi-document selection

Use a repeated three-value `--document FILENAME SEQUENCE SOURCE` option instead
of `--filename`/`--sequence`/`--source`. Each tuple refers to one persisted
document, **not** a chunk, page, form, or filing. Every document must be supplied
exactly once, including the primary and every exhibit already selected during
the original ingestion. This does not select additional exhibits from SEC.
Selection order is normalized by numeric sequence, then filename; sequences
and filenames must be unique. Chunk ordinals restart at 1 for each document.

```powershell
.\.venv\Scripts\python.exe -m sec_connector -c .\config\config.yaml maintenance prepare `
  --cik "<10-digit-CIK>" --accession "<accession>" `
  --document "annual.htm" 1 "C:\private\cached\annual.htm" `
  --document "subsidiaries.htm" 2 "C:\private\cached\subsidiaries.htm" `
  --out "C:\private\multi-document-plan.json"
```

The names/sequences above are placeholders, not a known filing inventory.
For four persisted documents, supply four tuples with their actual filenames,
sequences, and existing source paths. At least two tuples are required. Mixing
these options with the single-document selector or `--recover-prepared` is an
error. No glob, ticker/form inference, source download, or inventory repair is
performed. A sole-document filing with many chunks still uses the original
single-document selector.

Every old cache fingerprint must reproduce from its own source, exact filing
and document metadata, and the **same captured filing-wide processing options**.
Every document must have a nonempty, complete cached manifest whose uploaded
checkpoints and delivered hashes match. Missing/extra cache, chunk, or delivered
rows, old pending items, any missing acknowledged remote item, and mixed
generations fail closed. OCR-enabled multi-document settings are rejected even
if no rotated image is found; never disable inherited OCR just to pass this
gate. Historical image provenance is not inferred.

Format-3 plans freeze each document's exact scope, source path/bytes/hash and
desired cache fingerprint, the entire old local filing snapshot, and distinct
old remote and desired payload maps. Observed absences remain a separate
baseline map; they are not fabricated local delivery checkpoints. In this
completed-only class every old item must be present and verified, so baseline
absences are exactly the new desired-only IDs.

`inspect` lists per-document scopes, source hashes, and old/desired item counts
in addition to filing-wide totals. Review the whole plan, not just the counts.
Apply installs **all** desired document chunks and their individual caches in
one guarded local transaction. The shared journal covers every document.
**Every desired item across all documents must be ACKed and exact-GET verified
before the first stale item from any document can be deleted.** Resume repeats
this whole-set gate. Rollback restores/verifies the complete old remote set
before removing any operation-owned new IDs, then restores the complete old
filing snapshot atomically. Neither direction reparses sources.

Subset upgrades are intentionally excluded: processing options are stored at
filing level, so stamping new settings onto untouched old-generation documents
would lose provenance. No unselected document is implicitly modified; an
incomplete selection fails before activation. Other filings' document rows,
caches and remote items remain untouched, including unrelated work that occurred
after the backup. Forward replay requires **all** selected sources unchanged;
rollback needs none of those source files.

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
version 9.** Activation atomically upgrades format 3 to 4, inserts the operation
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

Plan formats 2 (single-document) and 3 (complete multi-document) are separate
from state format 4 and processing versions. The earlier OCR and inventory
extensions did not change non-OCR v8 semantics. The note-association follow-up
now uses **processing v9**, including `note_associations.py` in processing-code
provenance. This changes cache/payload generation, not state format 4 or plan
formats 1/2/3. Existing digests, historical options and frozen payloads are never
migrated, relabeled or automatically repackaged.

Old plans remain inspectable and support source-free rollback under their
original digests. Forward replay rejects processing/module drift and requires
the original runtime; do not rehash an activated plan to bypass this check.
Ordinary ingestion resume still replays already prepared payloads unchanged.
Unprepared old-version work needs explicit, separately authorized scoped
`ingest --reprocess`. Completed-cache fingerprints change with processing v9.
The frozen v8 sample uploader remains pinned to v8 and rejects this runtime
before source access or authentication; its old reviews/destination are not
retargeted to v9.

The OCR-specific backend revision is captured in every new OCR generation's
options and fingerprint independently of the processing-version boundary.
Unprepared legacy/unknown OCR backends fail closed before source discovery:
finish with the original runtime or explicitly reprocess the reviewed scope.
Existing format-1 and pre-CLI format-2 plans remain readable/inspectable and eligible for source-free rollback,
with their original payloads, cache/options, digest and recovery evidence.
**There is no automatic plan migration or digest rewrite.** Forward apply/resume
still requires the exact code/dependency/config provenance captured at prepare:
use the retained original runtime to finish an old operation, or separately
authorize rollback. New code intentionally refuses forward code drift rather
than silently blessing new processing. Old maintenance executables reject
unknown plan formats (including new multi-document format 3); old format-3-only
state readers still reject activated state format 4.
Never change either version number manually.

The offline extension suite uses synthetic HTML/PNG inputs, fake Graph outcomes,
and stub image decoding/recognition; it exercises production OCR discovery,
rotation/upscaling/cleanup and frozen-output replay. Sanitized fixtures were
generated by genuine `53dd715` (format 1) and `49cb53b` (pre-CLI OCR format 2)
implementations. Tests preserve original cache/options, source-free rollback,
format-4 guards and immutable plan digests; they do not migrate frozen plans.
The PR4 direct-backend suite passed **630 tests**, with four existing
private-corpus opt-ins skipped. Direct-backend tests cover argument/environment
isolation, temporary cleanup, timeouts, unavailable engine/model, exit-zero
model errors, runtime drift, source-only cache exclusion and prepared legacy
replay. This synthetic suite requires neither Pillow nor a real engine.
The separate actual-engine acceptance below uses retained approved tools;
no shared dependencies were installed.
An optional offline wheel-build check in PR4 was blocked because `hatchling`
was absent from its existing Python runtimes; no build dependency was downloaded
or installed for that check.

The multi-document suite adds synthetic two- and four-document inventories
(including HTML and text exhibits), per-document lost PUT/DELETE outcomes,
partial retirement, resumable rollback, checkpoint/transaction failures,
full-set gates, unrelated-row preservation, exact selection, and provenance
rejections. It does not use the reported PNC annual sources or any live database,
cache, SEC endpoint, or Graph tenant. The reported PNC 2023 annual primary plus
EX-21 and the PNC 2024 four-document annual inventory motivate this boundary;
their actual eligibility and content quality have **not** been certified here.
Before direct-backend integration the full offline suite passed **713 tests**, with four
existing private-corpus opt-ins skipped. Validation used a worktree-local Python
environment and explicit `PYTHONPATH` to this source, not an older installed CLI.

Direct-backend dependency integration retains format-3 dispatch: these plans
have per-document source bindings, not a top-level OCR bundle. OCR executable,
model-directory and timeout defaults do not enter OCR-disabled captured options,
payloads or document fingerprints. Changing those inactive settings does not
require an engine and does not invalidate a non-OCR plan. Code-module provenance
still changes on this upgrade: existing format-3 plans must use their original
runtime for forward recovery or use source-free rollback, just like formats
1/2. No plan digest is migrated. Multi-document OCR remains excluded.
The merged offline suite passed **745 tests**, with four existing private-corpus
opt-ins skipped. The combined maintenance/OCR suite passed 293 tests; three
additional integration cases verify inactive-backend settings and pre-backend
format-3 rollback/drift boundaries. This integration reused the existing
worktree interpreter with private test directories and installed or downloaded
nothing. It did not rerun the separate real-source acceptance reported below.

### Real-engine acceptance case (offline parser/chunker passed)

The coordinating customer-worksheet review reported an OCR-dependent case in
PNC's 2025 proxy, `d889589ddef14a.htm`, accession `0001193125-25-052937`, printed
page 25, **Transactions with directors in 2024**. The charity row has six
markers, while all 13 director-name headers are narrow rotated JPEGs with
`alt="LOGO"` and remain `[rotated text]` with v8/OCR disabled. A separately
authorized offline validation verified the actual engine's director-name
recognition, column ordering and six marker associations below. Neither
provenance capture nor synthetic tests alone establish that result.

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

After separate authorization for official private extraction tooling, a
**preliminary real Tesseract CLI comparison passed**. This is deliberately
distinct from parser/pytesseract end-to-end acceptance:

| Preliminary check | Result |
|---|---|
| Independent source-image reference | All 13 names/order visually recorded before OCR. |
| Raw CLI names, including punctuation | **13/13 exact**, without name substitutions or correction rules. |
| Second independent CLI invocation per image | **13/13 stable**; 26 successful invocations total. |
| Existing production text cleanup | Still **13/13 exact**; raw text already matched. |
| Recognized names mapped through the original rowspan-aware HTML grid | All **six** charity names match source columns **2, 5, 6, 7, 8, 13**. |
| Historical parser/pytesseract execution | Not run; the wrapper was unavailable. Superseded by the approved direct backend below. |

The comparison used existing base Python **3.12.10**, Pillow **12.3.0** and
privately extracted Tesseract **5.4.0.20240606** / Leptonica **1.84.1**, with the
bundled default English model and `--psm 7`. It reproduced the v8 Pillow
`rotate(-90, expand=True)` and integer upscaling/LANCZOS steps on private image
copies. All source JPEGs were 41 pixels wide; after rotation, scaling by three
produced 123-pixel-high PNG inputs. The command was
`tesseract.exe <private-preprocessed.png> stdout --psm 7`.
It did not replace pytesseract with a fake module or run an alternative OCR path
inside production ingestion.

Tool acquisition and identity were retained:

| Artifact | Source / SHA-256 |
|---|---|
| Tesseract installer (never executed) | [UB Mannheim release](https://github.com/UB-Mannheim/tesseract/releases/tag/v5.4.0.20240606); winget-verified `c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9` |
| 7-Zip 26.03 x64 MSI (never installed) | [Official release](https://github.com/ip7z/7zip/releases/tag/26.03), linked by 7-zip.org; release-digest-verified `c0680064d698a62dd4a5a47f403db356a6531a5473e4c4b1d090ea2590513926` |
| Extracted `tesseract.exe` | `babb405f4366b480d02cd8ff2bac8d497170f6c1711ce6f3d5d8bf0fb7fa6ed9` |
| Bundled `eng.traineddata` | `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |

The MSI's cabinet was read through read-only Windows Installer APIs and expanded
with the OS utility; the extracted 7-Zip executable then unpacked only the
Tesseract executable, runtime DLLs and English model into a private folder.
Neither installer was executed. No registry, system PATH, shared environment,
original source/cache or tenant state changed.

**Package policy:** the user confirmed the three requested wheel URLs are
organization-blocked. Retrieval/remediation stopped; no mirrors, TLS changes or
policy bypasses were used. The approved implementation removes pytesseract but
retains existing Pillow preprocessing. A standard-library-only raw-image
experiment across eight Tesseract page-segmentation modes scored **0/13** exact
names in every mode. Tesseract alone is not an accepted substitute for this case.

The approved direct backend subsequently passed actual **parser -> chunker ->
serialized payload** validation, with the engine/model/Pillow versions above:

| Direct-backend check | Result |
|---|---|
| Exact table excerpt | 13/13 names in order; six charity associations; one 2,577-byte request |
| Entire retained HTML document | 477 payloads; largest serialized request 9,044 bytes |
| Full-document rotated inputs | 26 occurrences using only the same 13 authorized assets; all matched the independent reference; no missing required rotated assets |
| Full-document charity payload | All 13 headers and six correctly associated markers co-located in one payload |
| Ordinary parser vs frozen capture hook | Identical parsed output for excerpt and full document; no provenance in Graph content |
| Non-OCR v8 regression against archived pre-CLI code | All 477 full-document payloads have the same canonical SHA-256 |
| Metadata | Retained offline replay metadata, not a fresh SEC receipt; filing date March 12, 2025; proxy `ReportPeriodEnd` suppressed |

An earlier table harness used a provisional March 11 date and a 2,549-byte request;
the verified-metadata rerun supersedes those numbers. Historical stored options
were processing v3/OCR off; the candidate explicitly uses v8, OCR on and the new
backend. No claim is made that the original generation used OCR.

Private reproducible evidence retains source/image/runtime hashes, frozen image
bytes and outputs, the independent pre-OCR reference, preliminary raw CLI
outcomes, full-document payloads, metadata provenance and scripts. The full HTML
run does not imply general scanned-image coverage: ordinary/non-rotated images
remain outside the parser's OCR eligibility. **Cross-page charity disclosure
scope/exclusions, live maintenance execution, Graph indexing and Copilot answers
remain unvalidated.** No customer source/cache/state, tenant, registry, system
PATH or shared environment was mutated. Nothing was merged or deployed.

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
