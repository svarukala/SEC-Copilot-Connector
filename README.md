# Get started with the SEC Copilot Connector

Import public SEC EDGAR filings into Microsoft 365 for search and Copilot
grounding. This connector supports 10-K, 10-Q, 8-K, DEF 14A, amendments, and
selected HTML/text exhibits.

## What this release improves

- **Richer schema:** 22 properties provide issuer, ticker, form, reporting period,
  document, and section context, with links to the actual SEC source document.
- **Financial-table fidelity:** removes duplicated layout content and improves
  header detection while preserving independent financial values and merged-cell
  relationships.
- **Historical coverage:** configurable filing-date windows, historical
  submissions, amendments, and selected exhibits.
- **Reliable synchronization:** checkpointed recovery, unchanged-upload skipping,
  and obsolete-item cleanup only after replacement uploads succeed.
- **Request-size protection:** validates the complete serialized Graph request
  against the configured 30 MiB (31,457,280-byte) ceiling.

> Imported items use a tenant-wide `everyone` read ACL. Use this connector for
> public SEC filings, not confidential documents. PDF exhibits are unsupported.
> Upload acknowledgment does not guarantee immediate search visibility or
> accurate Copilot answers.

## 1. Prepare your environment

You need Git, Python 3.10+ (3.11 or 3.12 recommended), outbound HTTPS access to SEC
EDGAR and Microsoft Graph, and a Microsoft 365 tenant configured for the search
or Copilot experience you intend to use. Confirm applicable licenses and
connector capacity with your tenant administrator.

In Microsoft Entra admin center, create an **App registration** for your tenant.
Record its tenant ID and application/client ID, then create a client secret and
securely capture its **value**, not its secret ID. Add these Microsoft Graph
**application permissions**, and have an authorized administrator grant consent:

- `ExternalConnection.ReadWrite.OwnedBy`
- `ExternalItem.ReadWrite.OwnedBy`

Use that same app to create and operate the connection. You also need a real
organization/contact email for the SEC request user agent.

## 2. Download and install

Run in PowerShell. The commands use the virtual environment directly, so no
activation or execution-policy change is needed.

```powershell
git clone https://github.com/svarukala/SEC-Copilot-Connector.git
Set-Location SEC-Copilot-Connector
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\sec-connector.exe --help
```

Keep the repository root as your working directory for all commands. Relative
cache and state paths are resolved from the working directory.

## 3. Set credentials and choose the scope

Replace the placeholders below. The secret prompt hides input; credentials
remain in this process environment. Do not commit secrets or include them in
logs, screenshots, or support requests.

```powershell
$env:AZURE_TENANT_ID = "<tenant-id>"
$env:AZURE_CLIENT_ID = "<application-client-id>"
$env:AZURE_CLIENT_SECRET = [System.Net.NetworkCredential]::new(
    "", (Read-Host "Client secret value" -AsSecureString)
).Password
$env:SEC_USER_AGENT = "YourOrganization SEC-Connector (your-real-contact@company.com)"
Write-Output "Client secret configured: $([bool]$env:AZURE_CLIENT_SECRET)"
```

Edit the existing entries in [config/config.yaml](config/config.yaml); **do not
append duplicate YAML sections**. Choose your own new, alphanumeric connection
ID and date window. For example:

```yaml
azure:
  connection_id: "customersecfilingsv2"
  connection_name: "SEC EDGAR Filings"

filings:
  start_date: "2021-09-10"
  end_date: null

sync:
  prune_missing_filings: false
```

This is a partial example: retain the other configuration entries, including
credential environment-variable references and form/exhibit selection.
The example selects five years of **filing dates** as of September 10, 2026.
Dates are inclusive; this is not a rolling cutoff or a reporting-period filter.
The shipped configuration instead starts at **2019-09-09** and uses a
demonstration connection ID, so review it before running.

Leave OCR disabled for first-time setup. It requires separately installed
dependencies, a local engine, and local image assets.

## 4. Create the connection and schema

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml setup
```

Use a **new connection ID when moving from an older populated schema**. Do not
reset an existing connection just to try this release. Setup creates the
connection and follows schema provisioning, waiting up to 15 minutes; resolve
any reported error before proceeding. The same configuration is used below.

## 5. Start with a small PNC sample

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml ingest -t PNC --test --no-prune
```

**This uploads real content to Microsoft 365; it is not a dry run.** By default
it selects at most two filings for one ticker and five chunks per filing.
These are sampled filings, not complete coverage. `--save-payloads` also still
uploads; see [local inspection](docs/operations.md#inspect-content-without-uploading)
if you need a no-upload option.

## 6. Import all five companies

After the sample succeeds, run without sampling limits:

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml ingest -t PNC,WFC,JPM,BAC,USB --no-prune
```

The full run expands the sample. Tickers are processed sequentially; Graph PUTs
run with concurrency capped at five. Multi-year backfills can take hours.
Keep the process running, the machine awake, and network access available.

Watch the running terminal or [follow the log](docs/operations.md#monitor-a-run).
Do not run `status` while ingestion owns the destination lock. After an
interruption, use the same working directory, credentials, and configuration:

```powershell
.\.venv\Scripts\sec-connector.exe -c .\config\config.yaml resume
```

`resume` handles already queued work, not discovery of tickers the interrupted
run had not reached. Rerun the five-ticker `ingest` command to include those
tickers; already completed filings refresh and unchanged item hashes skip PUTs.

After ingestion, allow time for Microsoft 365 indexing. Use the Microsoft 365
admin experience to manage the connection, and Microsoft Search or an appropriately
licensed Copilot experience to retrieve content. Select **your new connection**
as the declarative agent's knowledge source; restrict unrelated sources initially.

Try: "Compare PNC and its four peers for the same reporting period. Cite the
filing and table for each metric, preserve units and precision, and flag
incompatible definitions or missing evidence."

## Next reference

[Operations and troubleshooting](docs/operations.md) covers monitoring, recurring
sync, adding older history, recovery, parser upgrades, OCR, and deletion.
The authoritative property definitions are in [config/schema.json](config/schema.json).
