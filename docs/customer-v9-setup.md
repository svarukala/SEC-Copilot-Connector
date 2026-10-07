# Three-document v9 + OCR installation and import

This procedure uses a **fresh installation and a new, unused Graph connection**.
Leave the existing connector, app, database, configuration and agent unchanged.
Use the reviewed v9 setup commit supplied with the delivery, not a v10 branch.
Package 1.0.1 retains processing version **9** and the existing state format.

`prepare-exact` verifies the manifest against SEC submissions and filing detail
inventories, downloads only the selected full primary documents and the visible
rotated-text images they need, and builds every payload **without Graph access,
credentials, or a database**. `import-exact --upload` is a separate, live action.
Neither command falls back to ticker-wide ingestion.

## Exact scope

Use [documents.yaml](../config/customer-v9/documents.yaml) unchanged:

| Filing | Filing date (not fiscal period) | Accession | Primary filename |
|---|---|---|---|
| PNC 2025 DEF 14A | 2025-03-12 | 0001193125-25-052937 | d889589ddef14a.htm |
| PNC FY2023 10-K | 2024-02-21 | 0000713676-24-000028 | pnc-20231231.htm |
| PNC FY2024 10-K | 2025-02-21 | 0000713676-25-000027 | pnc-20241231.htm |

All three have CIK `0000713676`. No exhibits, amendments, sampled pages or page
caps are included. Proxy-only ingestion does not cover this scope.
The manifest binds ticker, CIK, accession, form, filing date and filename;
the SEC detail inventory also supplies the primary document's sequence and size.
Unknown manifest keys, duplicates, missing entries and identity mismatches fail.
Date windows and `--max-filings 3` are **not** substitutes for this manifest.

## 1. Fresh installation (PowerShell, no activation required)

Prerequisites: Python 3.12, Git, approved Python package access, and an approved
Windows Tesseract bundle with all runtime DLLs, image-codec dependencies and
`tessdata\eng.traineddata`. Preserve the bundle's license notices. Pillow is a
Python dependency; pip does **not** install the native Tesseract engine or model.
Use your organization's approved feed/native software package; do not disable
TLS validation or substitute an unapproved mirror if access fails.

Run from a parent directory where `SEC-Connector-v9-OCR` does not already exist:

```powershell
git clone https://github.com/svarukala/SEC-Copilot-Connector.git SEC-Connector-v9-OCR
if ($LASTEXITCODE -ne 0) { throw "Clone failed" }
Set-Location SEC-Connector-v9-OCR
$ReleaseCommit = Read-Host "Approved v9 setup commit SHA from the delivery"
git checkout --detach $ReleaseCommit
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
$ApprovedPythonFeed = Read-Host "Your organization's approved Python simple-index HTTPS URL"
.\.venv\Scripts\python.exe -m pip install --index-url $ApprovedPythonFeed ".[ocr]"
if ($LASTEXITCODE -ne 0) { throw "Approved package installation failed" }
.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency check failed" }
.\.venv\Scripts\python.exe -c "import sec_connector; print(sec_connector.__version__); print(sec_connector.__file__)"
.\.venv\Scripts\python.exe -m sec_connector --help
```

An approved **complete wheelhouse** is an alternative to the feed: install its
reviewed `sec-connector[ocr]==1.0.1` wheel and dependencies with
`.\.venv\Scripts\python.exe -m pip install --no-index --find-links C:\ApprovedWheelhouse "sec-connector[ocr]==1.0.1"`.
The source/configuration/runbook must still be from the same reviewed delivery.
Do not use an editable install or an older installation's Python executable.

Remain in this fresh repository root for every command below. Relative `data`
paths resolve from the current directory. Use
[config/customer-v9/config.yaml](../config/customer-v9/config.yaml), **not** the
demonstration `config/config.yaml`.

```powershell
$env:SEC_USER_AGENT = Read-Host "SEC identifying User-Agent including your real contact email"
$env:SEC_TESSERACT_EXE = Read-Host "Absolute path to the approved native tesseract.exe"
$env:SEC_TESSDATA_DIR = Read-Host "Absolute path to its approved tessdata directory"
if (-not (Test-Path $env:SEC_TESSERACT_EXE -PathType Leaf)) { throw "Missing Tesseract" }
if (-not (Test-Path (Join-Path $env:SEC_TESSDATA_DIR "eng.traineddata") -PathType Leaf)) { throw "Missing English model" }
$Config = "config\customer-v9\config.yaml"
$Manifest = "config\customer-v9\documents.yaml"
```

The loader expands environment variables but does **not** load `.env`. These
variables must be set again in each new PowerShell process. No Azure variables
are needed for preparation.

## 2. Prepare locally (SEC network, never Graph)

```powershell
.\.venv\Scripts\python.exe -m sec_connector --config $Config prepare-exact `
    --manifest $Manifest --cache data\exact-cache --out data\prepared-online.json
if ($LASTEXITCODE -ne 0) { throw "Preparation failed; do not set up or upload" }
```

This performs complete historical metadata discovery for the selected tickers,
then verifies **every** manifest entry before downloading primary content.
Unrelated metadata may be read; unrelated documents, decorative images and
exhibits are not downloaded. SEC requests are rate-limited (5/s in this config)
with the existing retry/User-Agent rules. Sources are size-validated using the
existing narrowly scoped delivery-script normalization, not arbitrary trimming.
The size match is not a publisher checksum.

OCR is the existing v9 clockwise rotation/upscaling plus local English/PSM 7.
The preparation probes the engine/model, captures runtime hashes and rechecks
them on completion. Missing engines, DLLs, models, selected images, empty OCR
results and timeouts fail; they are never silently replaced with blank headers.
Review the recognized text, since nonempty OCR alone does not establish accuracy.

Selected image URLs must resolve to the same filing on HTTPS `www.sec.gov`.
Plain adjacent filenames and canonical same-filing archive URLs are supported.
Foreign hosts/filings, queries, fragments, traversal, ambiguous encoded names,
unsupported image types and filesystem links/junctions are rejected.
Assets are limited to 256 distinct files per document, 4 MiB per file,
32 MiB total per document and 16 million pixels per image. Asset downloads do
not follow redirects, use canonical unpadded CIK URLs, validate actual image
bytes and write atomically. Ordinary `ingest --ocr` still requires local assets;
automatic bounded staging belongs to `prepare-exact`.

Inspect the scope and OCR output:

```powershell
$Prepared = Get-Content data\prepared-online.json -Raw | ConvertFrom-Json
$Prepared.documents | ForEach-Object {
    [PSCustomObject]@{
        Accession = $_.filing.accession_number
        Filename = $_.document.filename
        Items = $_.payloads.Count
        OCROccurrences = $_.ocr.Count
        LargestRequestBytes = $_.largest_item_bytes
    }
} | Format-Table
$Prepared.documents[0].ocr | Select-Object filename,text -Unique | Format-Table -AutoSize
```

The full-source local validation produced 681 proxy items, 754 FY2023 items and
763 FY2024 items: **2,198 total**. Largest serialized requests were respectively
7,967, 8,488 and 8,962 bytes, below 31,457,280 bytes. The proxy has 13 distinct
director-name images appearing at 26 locations. Both annual reports have no
visible rotated-text candidates under the v9 selector; that does not imply
general image/chart/PDF coverage.

The 13 names, in first-occurrence order, were Joseph Alvarado; Debra A. Cafaro;
Marjorie Rodgers Cheshire; Douglas A. Dachille; William S. Demchak;
Andrew T. Feldstein; Richard J. Harshman; Daniel R. Hesse; Renu Khator;
Linda R. Medler; Robert A. Niblock; Martin Pfinsgraff; Bryan Salesky.
Item counts are evidence for these source bytes/dependencies, not an accuracy
guarantee or a substitute for exact identity checks.
The [public validation receipt](customer-v9-validation.json) records source URLs,
hashes, sizes, native-engine provenance and exact payload equality with reviewed v9.

## 3. Offline replay and cache check

```powershell
.\.venv\Scripts\python.exe -m sec_connector --config $Config prepare-exact `
    --manifest $Manifest --cache data\exact-cache --offline --out data\prepared-offline.json
if ($LASTEXITCODE -ne 0) { throw "Offline preparation failed" }
$BundleSha = (Get-FileHash data\prepared-online.json -Algorithm SHA256).Hash.ToLowerInvariant()
$OfflineSha = (Get-FileHash data\prepared-offline.json -Algorithm SHA256).Hash.ToLowerInvariant()
if ($BundleSha -ne $OfflineSha) { throw "Online/offline bundles differ; investigate before upload" }
Write-Output "Reviewed bundle SHA256: $BundleSha"
```

`--offline` opens **no network session**. It requires the previously verified
inventory, all sources/assets and matching input hashes, and reruns the local
parser/OCR with the installed engine. A normal online rerun rechecks SEC metadata
and reuses validated cached content; pass a new `--out` filename.
`--refresh` explicitly refetches selected sources/assets online. It cannot be
combined with `--offline`. An existing output bundle is never overwritten.

The bundle contains exact payloads, source/asset hashes, metadata and OCR output.
The cache is beneath `data\exact-cache\<manifest-hash>\<CIK>\<accession-no-dashes>`.
Keep both private and immutable once approved, together with the digest and
installed code/dependency/native-runtime provenance. Hashes detect local drift;
they are not a signed SEC publisher attestation. Do not modify the bundle or
silently accept an unexpected digest.

**Stop here for local-only validation.** The steps below contact Microsoft 365
and are for a customer-authorized live import. They were not run against a live
tenant as part of the local validation.

## 4. Customer-authorized new connection (LIVE)

An authorized tenant administrator must create a **separate app registration**
and grant admin consent to these Microsoft Graph **application** permissions:
`ExternalConnection.ReadWrite.OwnedBy` and `ExternalItem.ReadWrite.OwnedBy`.
Use this same new app for setup and import. Confirm tenant licenses/capacity.
Do not change the existing connector's app or permissions.
Items use the connector's tenant-wide `everyone` read ACL for public SEC data.

```powershell
$env:AZURE_TENANT_ID = Read-Host "New app's tenant ID"
$env:AZURE_CLIENT_ID = Read-Host "New app's application/client ID"
$env:AZURE_CLIENT_SECRET = [System.Net.NetworkCredential]::new(
    "", (Read-Host "New app client secret VALUE, not secret ID" -AsSecureString)
).Password
$env:SEC_CONNECTION_ID = "pnc9ocr" + [guid]::NewGuid().ToString("N").Substring(0,16)
Write-Output "Record this new connection ID for future retries: $env:SEC_CONNECTION_ID"
.\.venv\Scripts\python.exe -m sec_connector --config $Config setup
if ($LASTEXITCODE -ne 0) { throw "Setup failed; do not import" }
```

Record the generated ID securely and reuse it; do **not** generate a different
ID on retry. The fresh directory has no old state. All three documents use this
single config, app, connection and destination-scoped database
`data\state.<destination-hash>.db`. Do not copy an old `state.db` into this folder.

## 5. Import all three prepared documents (LIVE)

Use the SHA256 you reviewed in step 3, not a newly accepted hash of changed data:

```powershell
.\.venv\Scripts\python.exe -m sec_connector --config $Config import-exact `
    --manifest $Manifest --bundle data\prepared-online.json `
    --bundle-sha256 $BundleSha --upload
if ($LASTEXITCODE -ne 0) { throw "Import incomplete; retain state and repeat this exact command" }
.\.venv\Scripts\python.exe -m sec_connector --config $Config status
```

There is no ticker discovery, reparse, sampling or whole-filing pruning in this
command. It checks the entire bundle, manifest, current settings and schema,
rejects an existing database from another generation, and durably prepares all
three documents before any PUT. Payload copies are also saved beneath
`data\payloads\state.<destination-hash>\PNC\<accession-no-dashes>`.

If interrupted or partially uploaded, rerun **the same `import-exact` command**.
Acknowledged unchanged items are skipped and pending items are retried.
Keep the original bundle/digest and database. Do not use `reset`, `--test`,
`--max-pages`, or ticker-wide `ingest` for this procedure. `--test` and
`ingest --save-payloads` are live uploads, not previews.
A different bundle/generation requires a new connection/database in this fresh
import workflow; existing maintenance/reprocess/rollback procedures are unchanged.
An interrupted, not-yet-prepared exact import cannot fall back to ordinary
resume discovery; it instructs you to repeat `import-exact`.

After success, the customer should verify all three accession/document identities
in Microsoft 365 and wait for indexing before evaluating grounded answers.
Local preparation and upload acknowledgments do not establish search visibility
or Copilot/agent accuracy. Do not replace the existing agent or baseline connector
until the customer separately approves that change.

Clear the secret when done:

```powershell
Remove-Item Env:AZURE_CLIENT_SECRET
```

## Troubleshooting without expanding scope

Missing native dependency/model: install the organization's approved complete
bundle, restore the absolute paths, and repeat preparation. SEC access or TLS
failure: fix the approved network/User-Agent configuration; never bypass TLS.
Missing/corrupt cache: use online `--refresh` and a new output, review again;
offline mode cannot repair inputs. Identity mismatch or unexpected OCR text:
stop and investigate the source and manifest rather than relaxing selection.
Wrong schema/destination: stop and use the intended new connection; do not
alter the old populated connector. Keep failed-run evidence and never report
partial output as a completed three-document import.
