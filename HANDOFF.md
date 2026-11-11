# SEC Copilot Connector handoff

Last verified: **2026-11-11 (authorized anonymization publication/merge review)**. This is the
portable continuation record for the standalone product. Historical results
below are not fresh live acceptance or permanently current remote status.

## Current change and publication boundary

Repository: <https://github.com/svarukala/SEC-Copilot-Connector>.
The legacy `SEC-Connector` folder in `svarukala/AgenticProjects` is not the
current product source. Do not copy it over this repository or reuse its older
editable installation.

- Starting commit: `5871eaf0b1b7149561bb9245a421a63587c7ec46`.
  Working branch: `svarukala-anonymize-engagement-references`.
  The user subsequently requested **"push and merge"** on 2026-11-11,
  authorizing publication, a scoped PR into `main` and its normal merge.
  This supersedes the earlier local-only boundary. No force, bypass, history
  rewrite, branch deletion or live tenant actions are authorized.
- This record is prepared **before publication and merge** and does not claim
  either completed. Input head was `fc7f15a9920dc2cdb11e0736140600c0c344a70f`;
  fetched main remained the starting commit above. Main was unprotected with
  no active branch rules; normal merge commits were enabled and automatic
  branch deletion disabled. Recheck final-head reviews/checks and mergeability.
  GitHub's PR state and merge SHA are the authoritative completion receipt.
- Neutralized engagement-specific narrative and sample connection display
  labels. Renamed the exact-import templates/runbook/receipt to `sample-v9`
  and updated their dependent links, commands and shipped-config test.
  Public issuer names, filing identities, financial facts and regression
  evidence remain intact. These examples do not imply issuer relationships.
- Removed current README/handoff demo links. A sanitized replacement is pending;
  no redacted recording was produced or verified. The original recording was
  not modified. No media-editing tools were available on PATH.
- This is current-documentation cleanup, not complete erasure. Git history,
  historical branches, original public attachments and comments remain
  accessible and were not rewritten or deleted. Runtime destination literals
  and protective allowlists in the existing default configuration/sample loader
  remain unchanged; changing those safely is outside this narrative task.
- No source processing changes: package **1.0.1**, processing **9**, default
  destination-state format **3**. Maintenance can permanently upgrade a selected
  database to format 4. Do not confuse state format with processing version.
  V10 remains parked after a search regression; no v10 integration is authorized.
- README disclaimer and licensing wording are unchanged. The full-license gap
  remains: package metadata declares MIT, but no full `LICENSE` file is tracked.
  Owner clarification remains necessary; no license terms were invented.

## Current verification

Verified on **2026-11-11** at implementation commit
`14bf5b1000bb28bc9729ae3ef7983bff6143629b`. Product source is unchanged from
`5871eaf0b1b7149561bb9245a421a63587c7ec46`; the sample-path, display-label,
documentation and test-reference edits were checked again after committing.
This subsequent handoff-only receipt records that verification:

- `tests\test_exact_import.py` and `tests\test_cli.py`: **52 passed** using
  checkout-selected source. Pydantic and pytest-asyncio deprecation warnings
  remain. `pip check` passed.
- All 57 relative links/anchors in changed Markdown, Markdown fence balance,
  all tracked JSON parsing, the three changed PowerShell blocks' syntax and
  `git diff --check` passed. No documented live command was executed.
- Git-normalized manifest and historical v9 receipt blobs are identical across
  their renames. Sample configuration differs only in its two display fields.
  The v8 result differs only by omission of destination identifiers.
  Runtime source, default config/schema, dependency manifest, public evaluation
  samples, fixtures, presentation and README disclaimer are unchanged.
- Initial validation was blocked by missing Python dependencies and shared
  temporary-directory permissions. A worktree-local `.venv` was provisioned
  from the configured package source with the existing dev/OCR extras, then
  tests passed with a dedicated temporary directory. No shared environment
  was modified. The local virtual environment is not part of Git recovery.
- No full-suite rerun, native-OCR acceptance, video sanitization, SEC download
  or live Graph/tenant operation is claimed. Historical results remain below.

## Historical validation, not current live acceptance

- The [2026-10-07 source-provenance receipt](docs/sample-v9-validation.json)
  records fresh-wheel installation, actual SEC downloads, native OCR,
  clean-online/cache/offline equality and payload equality with reviewed v9.
  Its dates, hashes, source identities and results are preserved unchanged.
- Full source validation of `d3099150556628778d0311b15a0d1ced8bcbaf81` on
  2026-10-11 recorded **922 passed, 4 skipped, 14 subtests passed**, with one
  Pydantic deprecation warning. Offline preparation reproduced all 2,198
  payloads from retained verified inputs. This was not a fresh SEC download
  or a live Graph run.
- Historical exact-import validation did not establish live upload, indexing
  or agent accuracy. The separate [maintenance report](docs/maintenance-live-validation.md)
  describes its own bounded non-OCR live scope; it is not acceptance of these
  exact-import or OCR procedures.

## Public sample and supported procedure

Use the [sample runbook](docs/sample-v9-setup.md),
[configuration](config/sample-v9/config.yaml) and
[exact manifest](config/sample-v9/documents.yaml). The sample selects three
complete public PNC primary documents, CIK `0000713676`; it is not page-limited
CLI test mode. No exhibits or amendments are included.

| Document | Filing date | Accession | Filename | Historical items |
|---|---|---|---|---|
| 2025 DEF 14A | 2025-03-12 | 0001193125-25-052937 | d889589ddef14a.htm | 681 |
| FY2023 10-K | 2024-02-21 | 0000713676-24-000028 | pnc-20231231.htm | 754 |
| FY2024 10-K | 2025-02-21 | 0000713676-25-000027 | pnc-20241231.htm | 763 |

The proxy uses 13 distinct rotated director-name images at 26 occurrences.
Largest historical requests were 7,967 / 8,488 / 8,962 bytes. This is limited
rotated-text OCR, not general chart/image/PDF recognition.

- `prepare-exact` validates manifest identities, stages bounded same-filing OCR
  assets and prepares full payloads without Graph credentials, sessions or a
  database. `--offline` additionally requires verified cached inputs and opens
  no SEC session. Proxy-only or `--max-filings 3` is not equivalent selection.
- `import-exact --upload` performs live Graph writes. It requires the reviewed
  bundle/digest, exact manifest, matching settings/schema and a new destination
  or retry of the same generation. All three documents use one config/app/
  connection/database. Retry the same exact import after interruption.
- Renamed repository paths are for new sample use. Do not move or rewrite an
  existing installation's private configuration, original prepared bundle,
  captured native paths or destination state to match them. New UI labels do
  not rename any live connection. Preserve original inputs through recovery.
- The previously deleted email Markdown file must remain absent. Do not
  recreate it or treat historical email-related work as permission to send mail.

## Recovery and local-only risks

Recover into a **fresh clone**, not by resetting or overwriting a populated or
shared checkout. Fetch remote refs, inspect the intended reviewed commit and
PR state, and explicitly select that revision. Publication alone does not mean
merged: confirm this branch's PR is MERGED and its merge commit is contained in
remote main before recovering the change from main. Verify the merged tree
contains the reviewed README, handoff and renamed sample files. Use
`git log -1 -- HANDOFF.md` to identify this record's revision.

Follow the sample runbook for a fresh virtual environment and approved package
feed or complete wheelhouse. Use `PYTHONPATH` pointing to the checkout's `src`
when testing source; otherwise verify the installed package location to avoid
an older editable installation. Re-provision approved native Tesseract,
DLL/image-codec dependencies and `eng.traineddata` with license notices.
Pip's OCR extra supplies Pillow, not the native engine/model.

Git does not preserve credentials, private reports/logs, caches, payload bundles,
destination-scoped SQLite databases, native binaries/models, virtual environments
or app-local checkpoint history. Retrieve credentials through approved storage
and transfer needed runtime artifacts securely with integrity checks. Config
expands environment variables but does not load `.env`.

Before moving an in-progress installation, stop all writers and retain a
consistent database backup including journal/WAL state, the original exact
bundle/digest, runtime provenance and recovery receipts. Preserve destination
identity; never run two writers, copy state to another destination or delete
state to suppress errors. A Git/database restore alone is not a Graph rollback.
New native paths/dependencies can change bundle digests: review new preparation
rather than assuming it is identical to historical evidence.

## Remaining work and authorization

1. Complete the authorized scoped PR using normal merge gates and an exact-head
   guard. After pushing, verify the remote tip and published handoff. After
   merging, verify GitHub's merged state, reviewed-head ancestry and the merged
   README/handoff/sample blobs on remote main. Do not report pre-merge checks
   as completion or repeat an already completed merge.
2. Produce and fully review a sanitized demo before adding a replacement link.
   This task does not remove existing external artifacts or historical copies.
3. Keep licensing clarification and v10 decisions separate. No live SEC/Graph,
   tenant, app, agent or destination-state actions are authorized here.
4. For a separately approved live sample, follow the runbook's **LIVE** section.
   `setup`, `import-exact --upload`, `ingest` (including `--test` and
   `--save-payloads`), reset and applicable maintenance commands are not previews.
   Upload acknowledgments do not establish indexing or Copilot accuracy.
