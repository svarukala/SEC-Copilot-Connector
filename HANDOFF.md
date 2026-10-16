# SEC Copilot Connector handoff

Last verified: **2026-10-16 (authorized pre-merge verification)**. This is the portable continuation record for the
standalone product. Update it with meaningful progress; do not treat dated
remote status or historical results as permanently current.

## Start here: published does not mean merged

Repository: <https://github.com/svarukala/SEC-Copilot-Connector>.
The legacy `SEC-Connector` folder in `svarukala/AgenticProjects` is **not** the
current product source. Do not copy it over this repository or use its older
editable Python installation.

| Reference | Verified identity/status before this documentation update |
|---|---|
| GitHub `main` before PR #9 merge | `b472a1b14bb8f86e679fb9f6ccc661ec9e778358`, reviewed v9 merge |
| Customer setup branch | `svarukala-customer-v9-setup` |
| Published customer setup tip before this handoff update | `de242a6b577385390f69760f41a68f7baaa970b2`; product code unchanged from `d3099150556628778d0311b15a0d1ced8bcbaf81` |
| Setup implementation | `27ff921ce7c2b17d68e11079c8c84056957098ee` |
| [PR #9](https://github.com/svarukala/SEC-Copilot-Connector/pull/9) at pre-merge check | OPEN/CLEAN/MERGEABLE, targeting `main`; user authorized normal merge on 2026-10-16 |
| Reviewed v9 integration head | `048e6ccbee487e93856008877b6a73266c9161fa`, merged via [PR #8](https://github.com/svarukala/SEC-Copilot-Connector/pull/8) |
| Parked combined v10 branch | `svarukala-review-combined-sec-upgrades`, published tip `7e1caffae4dbed88cff7d759e8042233a9f93e4c`; not the customer baseline |

The user explicitly authorized merging PR #9 after final unchanged-head checks
on 2026-10-16. This documentation is prepared **before** that operation and does
not claim it has completed. The execution path is a normal merge of the exact
verified head, without admin bypass, force or branch deletion. GitHub's PR
record is the authoritative completed-state and merge-commit receipt.
**After confirming PR #9 is MERGED and its merge commit is contained in remote
main, recover from main**, not the former unmerged feature-branch workflow.
The recovery commands below enforce that condition.
Use `git log -1 -- HANDOFF.md` to identify this documentation revision; the table
pins tested input commits rather than attempting to embed this file's own hash.

## Final authorized merge checks (2026-10-16)

- Live input refs matched `de242a6...` (PR head) and `b472a1b...` (main).
  No reviews, required checks or active branch rules were listed; main was
  unprotected. Normal GitHub merge checks still apply; never bypass a new rule.
- Product source, tests, configuration and dependency manifest were unchanged
  from the 2026-10-11 full validation of `d309915...`.
- Current focused source tests: `tests\test_exact_import.py` and
  `tests\test_cli.py`: **52 passed** in 7.65 seconds, with the existing Pydantic
  deprecation warning. Installed 1.0.1 / processing 9 module/resource byte
  equality, `pip check`, and main/prepare-exact/import-exact CLI help passed.
- The only merge-preparation change is this handoff transition. Earlier full
  tests/native-OCR evidence below remain historical, not fresh runs today.
- After merging, verify the merge tree equals the checked head tree, both
  expected parents are present, remote main contains the merge, v10 remains
  excluded, and the handoff/runbook are published with the email file absent.
  No Graph, tenant, customer, agent or shared-main-checkout actions are authorized
  by this source merge.

**Decision retained:** processing version **9**, package **1.0.1**, existing
destination-state format **3**. V10 marker-table changes caused a real search
regression; the user parked v10 troubleshooting. Do not switch to, merge, or
restart v10 work without a new decision. Default v9 parsing/payload behavior,
historical prepared replay/rollback and version guards remain intact.

## Historical crash-recovery audit (2026-10-11)

On 2026-10-11, after fetching GitHub refs:

- Customer setup local and remote tips matched `d309915...`; its worktree was
  clean before this handoff change. All 13 inspected standalone worktrees
  (including the detached prewarm checkout) had no tracked modifications or
  ordinary untracked files. Other owners' files were not modified.
- Zero commits reachable from local product branches were absent from **all**
  fetched remote branches. This does not mean every branch is merged into main.
- Git object connectivity passed. The shared main checkout was explicitly
  excluded from filesystem/status checks and was not changed. Ref metadata
  indicates its local `main` is stale at
  `6d34733b404631b2e6b25caa73a3ac910bf80aa7`, behind GitHub main; use fresh remote
  refs, not that checkout, for recovery.
- There were 154 app/checkpoint commits reachable only outside local product
  and remote branch histories. These are not ordinary unpublished product
  commits and are not guaranteed to transfer with a clone. They were not
  published, deleted or used to overwrite source.
- Installed package sanity passed: `pip check`, module/CLI help, and byte
  equality of all 21 installed Python modules plus packaged config/schema
  against the tested source. No dependency reinstall was needed.
- That day's full-source pytest run against `d309915...`: **922 passed, 4 skipped,
  14 subtests passed**, in 409.41 seconds. One existing Pydantic class-based
  `Config` deprecation warning; no failures. Source was selected explicitly
  through `PYTHONPATH`, not inferred from a clean Git status.
- That day's **offline** full-document preparation used the approved real native
  OCR bundle and existing verified cache. It reproduced all 2,198 payloads and
  the entire previous online bundle byte-for-byte, SHA256
  `366ca3555078936e64a6a34b00efa404df11a512fb59da9be77fcff7fbeb4993`.
  This was not a fresh SEC download or a live Graph test.

Historical validation on 2026-10-07 is preserved in
[the source-provenance receipt](docs/customer-v9-validation.json): fresh wheel
installation, actual SEC downloads, 922 tests passed / 4 skipped / 14 subtests,
clean-online/cache/offline equality, exact payload equality with reviewed v9,
native OCR and missing-engine/model/asset failure checks. Do not relabel that
receipt as a new test run. No live M365 upload, indexing or agent-accuracy
validation was performed in that run or in this crash-recovery follow-up.

## Exact scope and supported procedure

Use the [customer runbook](docs/customer-v9-setup.md),
[configuration](config/customer-v9/config.yaml) and
[exact manifest](config/customer-v9/documents.yaml). All documents are PNC,
CIK `0000713676`, full primary documents, not exhibits, amendments or samples.

| Document | Filing date | Accession | Filename | Local items |
|---|---|---|---|---|
| 2025 DEF 14A | 2025-03-12 | 0001193125-25-052937 | d889589ddef14a.htm | 681 |
| FY2023 10-K | 2024-02-21 | 0000713676-24-000028 | pnc-20231231.htm | 754 |
| FY2024 10-K | 2025-02-21 | 0000713676-25-000027 | pnc-20241231.htm | 763 |

The proxy requires 13 distinct director-name images, recognized at 26
occurrences; the v9 selector finds no rotated-text candidates in the annual
reports. Largest serialized requests were 7,967 / 8,488 / 8,962 bytes.
This is limited rotated-text OCR, not general chart/image/PDF recognition.
Proxy-only or `--max-filings 3` is not an equivalent selection.

- `prepare-exact`: validates all manifest identities against SEC metadata,
  stages only bounded same-filing selected OCR assets, and prepares full
  payloads without Graph credentials, Graph sessions or a database.
- `prepare-exact --offline`: additionally opens no SEC network session; requires
  the verified inventory, source/assets and matching input hashes.
- `import-exact --upload`: **live Graph writes**, requiring the reviewed bundle
  digest and exact manifest, current schema/settings and a new destination or
  retry of the same generation. All three documents use one config/app/
  connection/destination-scoped database. Repeat the same exact import to retry
  pending uploads; do not silently replace its bundle or state.
- The email Markdown file was intentionally deleted by user request in
  `d309915...`. Do not recreate it. No email was sent.

## Fresh-machine recovery (PowerShell)

Use a new directory. Obtain GitHub CLI (`gh`) access to verify the merge and your organization's approved
Python package feed or complete wheelhouse. Python 3.12 is the tested version;
do not transfer an old virtual environment between machines.

```powershell
git clone https://github.com/svarukala/SEC-Copilot-Connector.git SEC-Connector-v9-Recovery
if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
Set-Location SEC-Connector-v9-Recovery
git fetch origin
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
$PR = gh pr view 9 --repo svarukala/SEC-Copilot-Connector --json state,mergeCommit | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $PR.state -ne "MERGED" -or -not $PR.mergeCommit.oid) {
    throw "PR #9 merge is not confirmed; stop and inspect GitHub"
}
git merge-base --is-ancestor $PR.mergeCommit.oid origin/main
if ($LASTEXITCODE -ne 0) { throw "Remote main does not contain the recorded merge" }
git switch main
if ($LASTEXITCODE -ne 0) { throw "Cannot select main" }
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw "Cannot fast-forward this fresh checkout" }
git status --short
git rev-parse HEAD
git log -1 -- HANDOFF.md
```

These commands verify the completed PR merge, then recover main in a **fresh
clone**; they do not merge the PR or modify a shared checkout. They deliberately
stop if the authorized merge has not completed. If main has subsequently moved,
review its additional changes, or use `git checkout --detach $PR.mergeCommit.oid`
in this fresh clone for the exact merged release. Do not reset a populated local
checkout to make it match. For the historical tested pre-handoff code, the
immutable commit is `d309915...`.

```powershell
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
$ApprovedPythonFeed = Read-Host "Organization-approved Python simple-index HTTPS URL"
.\.venv\Scripts\python.exe -m pip install --index-url $ApprovedPythonFeed ".[ocr,dev]"
if ($LASTEXITCODE -ne 0) { throw "Approved installation failed" }
.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency check failed" }
.\.venv\Scripts\python.exe -c "import sec_connector; from sec_connector.pipeline import PROCESSING_VERSION; print(sec_connector.__version__, PROCESSING_VERSION, sec_connector.__file__)"
.\.venv\Scripts\python.exe -m sec_connector --help
.\.venv\Scripts\python.exe -m sec_connector prepare-exact --help
.\.venv\Scripts\python.exe -m sec_connector import-exact --help
$PriorPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path (Get-Location) "src"
    .\.venv\Scripts\python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Source tests failed" }
} finally {
    $env:PYTHONPATH = $PriorPythonPath
}
```

Setting `PYTHONPATH` just for tests ensures tests exercise the checkout, not a
stale installed wheel. Outside that block the CLI exercises the installed
package. Inspect its printed path; do not reuse an older editable installation.
For an offline installation, use an approved complete wheelhouse with build,
runtime and dev dependencies; do not substitute unapproved mirrors or bypass
TLS. Dependency ranges can resolve differently later; preserve the validated
wheel/dependency receipts through approved storage for precise reproduction.

### Native OCR and local preparation

Provision a complete approved **Windows Tesseract** bundle separately: native
executable, DLL/image-codec dependencies and `eng.traineddata`, with its license
notices. Pip's `[ocr]` extra supplies Pillow, not the engine/model. Historical
validation used Tesseract 5.4.0.20240606; the public validation receipt records
engine/model hashes. A fresh native bundle must be approved and validated, not
silently treated as the same runtime.

```powershell
$env:SEC_USER_AGENT = Read-Host "Identifying SEC User-Agent with real contact email"
$env:SEC_TESSERACT_EXE = Read-Host "Approved absolute path to tesseract.exe"
$env:SEC_TESSDATA_DIR = Read-Host "Approved absolute path to tessdata"
.\.venv\Scripts\python.exe -m sec_connector --config config\customer-v9\config.yaml prepare-exact `
    --manifest config\customer-v9\documents.yaml --cache data\exact-cache `
    --out data\prepared-recovery.json
if ($LASTEXITCODE -ne 0) { throw "Preparation failed; do not upload" }
```

This command downloads from SEC, not Graph. To use an already securely
transferred intact cache without any network, add `--offline` and choose an
unused output filename. A fresh empty cache cannot be used offline. Keep the
repository root as cwd. Config expands environment variables but does not load
`.env`; re-enter required variables in a new shell.

Do not compare a new machine's whole-bundle digest blindly with the old one:
captured native paths/runtime/dependencies can differ. Review and validate new
preparation; hashes are integrity evidence, not a publisher signature or
authorization to upload.

## What Git recovery does NOT restore

GitHub preserves tracked source, tests, configuration templates and docs on
published branches. It does not preserve all runtime state or prove a cloud
destination is healthy. Do not commit or indiscriminately stage:

- Credentials, tenant secrets, customer reports/workbooks and private logs.
  Retrieve secrets through an approved secret store; do not paste them in this
  handoff. Customer artifacts need approved secure transfer and access controls.
- Native OCR binaries/models and Python virtual environments. Re-provision
  approved native software and recreate the venv; preserve approved wheelhouse,
  licenses and dependency/runtime hashes separately when needed.
- Download caches, exact prepared bundles/digests, payload copies, scoped SQLite
  databases, recovery receipts and detailed private validation evidence. Transfer
  them securely with integrity checks, or regenerate public SEC preparation.
  Rebuilding source is not equivalent to recovering delivery acknowledgments.
- App-local checkpoint history and legacy presentation edits. The coordinator's
  separate AgenticProjects audit found a pre-existing uncommitted presentation,
  preserved privately rather than published. That file and custom reports are
  not guaranteed by this product repository's Git recovery.

Before moving an in-progress/live installation, stop all writers and use a
consistent approved database backup (including SQLite journal/WAL state as
applicable), exact original bundle/digest and recovery receipts. Preserve the
original destination identity and runtime/configuration provenance. Do not run
two machines as writers. Do not copy a database to a different destination or
delete it to suppress errors. If state is lost or paths/settings must change,
investigate documented recovery constraints before any live operation.

## Authorization boundaries and next actions

1. The user authorized PR #9's normal source merge on 2026-10-16. Verify its
   completed GitHub merge record and remote main as above before recovery.
   This supersedes the earlier crash-recovery-only authorization, but does
   not authorize any live Microsoft 365 operation or v10 integration.
2. For machine migration, recover the reviewed source and securely transfer or
   regenerate only the needed private artifacts. Rerun tests and Graph-free
   preparation before trusting the new environment.
3. Only after separate customer authorization, follow the runbook's **LIVE**
   section for a separate new app/unused connection with
   `ExternalConnection.ReadWrite.OwnedBy` and
   `ExternalItem.ReadWrite.OwnedBy` application permissions plus admin consent.
   Enter secrets securely; keep all three documents on the same destination.
4. Do not touch the existing connector, tenant app, customer database/config or
   agent. `setup`, `import-exact --upload`, ordinary `ingest` (including
   `--test` or `--save-payloads`), reset and applicable maintenance actions can
   perform live writes; they are not local previews.
5. Search/indexing/agent accuracy remains a separate, unperformed live
   acceptance step. Keep v10 parked and the deleted email file absent.

When progress changes these facts, update this handoff in the same justified
change: date, tested product commit, remote/PR state, decisions, validation and
remaining risks. Keep historical evidence labeled historical. After publishing,
verify the remote tip and that `HANDOFF.md` is accessible on GitHub. This is a
contributor/agent maintenance obligation, not a background scheduled job.
