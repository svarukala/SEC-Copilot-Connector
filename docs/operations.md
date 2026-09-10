# Operations and troubleshooting

Start with [Get started](../README.md). All commands below run from the repository
root in PowerShell, using the same `config\config.yaml`, environment credentials,
and virtual environment. On macOS/Linux, use the corresponding executable in
`.venv/bin` and shell-specific environment-variable syntax.

## Monitor a run

Use the ingestion terminal or follow the latest log in a second PowerShell
window opened at the repository root:

```powershell
$log = Get-ChildItem .\data\logs -Filter "*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $log) { throw "No connector log found. Start ingestion first." }
Get-Content -LiteralPath $log.FullName -Tail 30 -Wait
```

Stop following the log with Ctrl+C in that second window; it does not stop the
ingestion process. Restart the log follower after starting a new connector run.

`ingest`, `resume`, `status`, and `reset` acquire an exclusive destination lock.
**Do not use `status` while ingestion is running.** Once the writer has stopped:

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml status
```

Status includes the destination's stored filings, chunks, acknowledged item
count, and latest run. Counts can include older, out-of-window queued records;
they are not necessarily counts for your latest date window.

| Signal | Interpretation |
|---|---|
| `completed` filing | Its selected document inventory and desired uploads are complete, with stale-item reconciliation finished. |
| `sampled` filing | Deliberately limited coverage, not a full filing. |
| Transient Graph/SEC retry | A retryable failure; the generic warning alone does not prove HTTP 429 throttling. |
| Unsupported binary exclusion | A selected exhibit could not be ingested in its format; record the coverage gap. An unsupported primary document fails the filing. |
| Table-fragment warning | A table header or row still exceeds the chunk budget; independently retrieved fragments may lack context. Investigate rather than assume perfect fidelity. |
| Nonzero exit code/errors | Work is incomplete; review logs and recover before claiming success. |

### Runtime and storage

The main ingestion path processes tickers, filings, and document downloads
sequentially, with Graph PUT concurrency capped at five. `concurrent_downloads`
is used by a separate download helper, not to parallelize the main ingestion
pipeline. Separate runs must coordinate their combined SEC traffic.

Plan for hours for a multi-year backfill, not a fixed minutes-per-ticker estimate.
One five-year WFC/JPM/BAC/USB run processed 475 filings and 106,799 acknowledged
items in approximately 7 hours 38 minutes, including WFC reprocessing. This is
an observed example, not a performance guarantee. Disk and index usage depend
on source size, selected exhibits, and chunk counts.

## Resume, refresh, or rebuild

| Intent | Command/behavior |
|---|---|
| Recover queued work | `resume` retries unfinished work and replays prepared payloads unchanged. |
| Discover new filings or additional tickers | `ingest -t ...` performs discovery and refreshes completed filings. |
| Rebuild with new parser/chunker settings | `ingest -t ... --reprocess` explicitly replaces selected in-flight manifests. |

```powershell
# Recover queued work within the configured filing-date window
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml resume

# Discover and synchronize all five tickers
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml ingest -t PNC,WFC,JPM,BAC,USB --no-prune
```

Do not run these simultaneously against the same destination. Stop the writer
before changing settings. Keep the destination database and download cache:
deleting state does not remove remote content and can lose reconciliation history.

Discovery is ticker-by-ticker. If a run stops during PNC, `resume` does not
discover WFC/JPM/BAC/USB unless they were previously queued. Use `ingest` to
discover them. An unlimited ingest also expands previously sampled filings.

Full reruns refresh source bytes by default. Fingerprints cache parsed documents;
canonical item hashes skip unchanged PUTs. Setting
`sync.refresh_downloads: false` trusts valid local downloads and can miss source
changes, so it is not recommended for normal synchronization.

The connector is command-driven, not a permanently running sync service. Schedule
`ingest` externally for recurring discovery. Set the working directory explicitly,
supply credentials securely, retain state, and avoid overlapping scheduled runs.

## Add older history or change the date window

`filings.start_date` and `filings.end_date` are inclusive **filing dates**, not
fiscal reporting periods. `null` means no bound; dates do not advance automatically.
Changing the date window does not by itself delete already uploaded content.

For example, after ingesting from September 10, 2021 onward, import the preceding
two years by editing the existing `filings` entries:

```yaml
filings:
  start_date: "2019-09-10"
  end_date: "2021-09-09"
```

Then run `ingest` for the intended ticker(s), without sampling or pruning:

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml ingest -t PNC --no-prune
```

Alternatively, widen the start date and keep `end_date: null`; newer filings will
be revisited, with unchanged payloads skipped. Restore your ongoing date scope
after an older-only backfill. Resume leaves out-of-window queued records untouched.
Retain configured forms, history, amendment, and exhibit options when editing YAML.

## Schema and parser upgrades

The canonical [schema](../config/schema.json) has 22 properties. `Url` points to
the actual primary/exhibit document; `FilingUrl` points to the filing index.
Ticker, form, and document type support refinements; reporting period, filing
date, acceptance time, document IDs, ordinals, and section titles add context.
These improve retrieval and provenance, not guaranteed answer correctness.

For an older populated schema, **use a new connection ID and reingest**. An
existing schema is reused only when it matches. Setup follows Graph's schema
operation and waits up to 15 minutes; a mismatch or terminal error must be resolved.
Use the same configured ID for setup and all subsequent commands.

For a parser/chunker update without a schema change, first stop the writer,
update the code, and reinstall with `.\.venv\Scripts\python.exe -m pip install .`.
Then explicitly rebuild the selected scope:

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml ingest -t PNC,WFC,JPM,BAC,USB --reprocess --no-prune
```

Ordinary resume retains captured processing options; `resume --ocr` does not
change them. Prepared old payloads remain replayable, but an unprepared filing
captured under an incompatible processing version can require explicit reprocessing.
Do not combine a full repair with `--test` or `--max-pages`.

Reprocessing preserves acknowledged old IDs and separately tracks IDs that might
have reached Graph before an interrupted acknowledgment. Old items are deleted
only after complete replacement uploads succeed. Parse/upload failures leave
recovery information intact; failed deletes remain resumable. Other tickers and
out-of-window records are not rebuilt.

### Legacy state

State resides in `data\state.<destination-hash>.db`, bound to tenant and connection.
The lock is released by the operating system when a process exits.
The implementation migrates supported destination-scoped formats automatically.

An unscoped legacy `data\state.db` cannot be adopted automatically. Preserve it
outside the configured path if needed, or remove it only if deliberately disposable,
then create a new connection and reingest. Do not rename it to a hashed filename.
Retire an old remote connection separately and deliberately. If Graph reports
a connection missing while local state remains, setup stops rather than silently
claiming those old items are still delivered.

## Inspect content without uploading

**Neither `--test` nor `--save-payloads` is a dry run.** Test mode uploads a sample;
`--save-payloads` writes local copies in addition to uploading.
`--max-pages` is a maximum number of chunks across a filing's documents, despite
the historical flag name.

For single-document, no-upload inspection:

```powershell
$documentUrl = Read-Host "HTTPS SEC Archives URL of a supported filing document"
.\.venv\Scripts\python.exe .\test_filing.py $documentUrl --output-dir .\data\test_output
```

This downloads from SEC and produces Markdown and production-format payloads
locally; it makes no Graph uploads and needs no Graph credentials.
It requires `SEC_USER_AGENT` and a document within the configured form/date/history
and exhibit selection. It is not an offline command or a full-backfill preview.

## Content limitations and OCR

PDF exhibits are unsupported. Unsupported binaries are logged as excluded;
missing/unusable required documents fail rather than count as successful coverage.
Items use a tenant-wide `everyone` read ACL because the source is public SEC data.

Table normalization removes empty layout rows, avoids duplicating horizontal
spans, and retains independent equal-valued financial cells. A marker such as
`[merged with column 2]` refers to that column in the **same row**. Normal-sized
table chunks retain their headers and nearby context. Genuine oversized tables
can still fragment and produce warnings.

Deeply nested HTML can fall back to plain-text extraction with a warning.
Content may survive while table relationships degrade; inspect the result before
using it for financial comparisons. Images without textual equivalents can
also leave gaps.

OCR is opt-in for local image assets, not an automatic PDF/image ingestion service:

```powershell
.\.venv\Scripts\python.exe -m pip install ".[ocr]"
# Install Tesseract separately, put it on PATH, and supply the referenced local assets.
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml ingest -t PNC --ocr --no-prune
```

The parser downloads neither OCR models nor images. Missing OCR prerequisites or
referenced assets fail explicitly. An in-flight filing needs explicit reprocessing
to change its captured OCR choice.

## Troubleshooting

| Problem | Action |
|---|---|
| Credentials missing | Set them in the process that runs the connector. Check presence with `[bool]$env:AZURE_CLIENT_SECRET`; never print the value. |
| Graph 403 | Check application permissions, admin consent, tenant, and whether this app owns the connection. Do not assume every 403 is throttling. |
| Invalid connection ID | Choose an alphanumeric identifier starting with a letter and use it consistently. |
| SEC request rejected | Use a real organization/contact user agent and respect aggregate request limits; do not bypass SEC access controls. |
| Another process owns state | Let the writer finish or deliberately stop it. Do not delete state or its lock file to bypass the lock. |
| Transient Graph/SEC failure | Let built-in retries run. If the run fails, inspect the error, correct its cause, and resume queued work. |
| Schema timeout | Inspect logs and provisioning state; rerun setup with the same intended schema/connection. A schema mismatch needs a new connection, not repeated resets. |
| Uploads succeed but content is absent in Copilot | Allow indexing time, confirm tenant access/licensing, select the correct connector knowledge source, and distinguish Search visibility from upload acknowledgment. |

Search logs without exposing credentials:

```powershell
Select-String -Path .\data\logs\*.log -Pattern "ERROR|WARNING"
```

Redact sensitive information before sharing logs. Report reproducible issues in
the [repository issue tracker](https://github.com/svarukala/SEC-Copilot-Connector/issues),
including the source accession/document, command (without credentials), and error.
For release/version information, use the repository's actual tags/releases and
[package metadata](../pyproject.toml), not an independently maintained version table.

## Deletion and reset

**Destructive operations are not part of normal setup or recovery.**

Whole-filing pruning is disabled by default. `ingest --prune` removes tracked
filings absent from a complete selected historical inventory. It rejects
date bounds, recent-only discovery, and sampling/filing limits; ticker processing
errors block pruning. There is no arbitrary single-accession delete command.
Keep pruning disabled for bounded historical backfills.

Normal synchronization can still remove obsolete chunks or removed exhibits
after full replacement delivery; `--no-prune` disables whole-filing pruning,
not this safe per-filing reconciliation. Samples never prune full content.

Only if you deliberately intend to delete the entire selected connection:

```powershell
# DESTRUCTIVE: review azure.connection_id and tenant before running.
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml reset
```

Reset clears the destination's state only after Graph acknowledges deletion or
confirms not-found. Other remote failures preserve it. It is not a remedy for
ordinary transient errors.
