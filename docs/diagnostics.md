# Read-only evidence diagnostics and report comparison

Use this tool to distinguish cached inputs, captured processing settings,
operator-selected code, prepared payloads, local delivery acknowledgments, and
optional Graph read-back. It **does not assess semantic accuracy**. Matching
hashes or topic tokens do not establish correct financial table associations,
user search visibility, indexing completion, agent binding, or retrieval traces.

Do not update, repackage, reprocess, or repair a baseline to collect diagnostics.
The diagnostic never imports `StateManager`, the ingestion pipeline, or the
connector CLI. Offline collection and comparison use only the Python 3.10+
standard library. Graph mode explicitly requires the existing MSAL and PyYAML
dependencies; it does not install packages or automatically load `.env`.

## Safety and supported state

- Stop ingestion and maintenance writers before collection. State versions **3
  and 4** with the required manifest/cache columns are supported. Older,
  future, missing, or incompatible state is rejected, never created or migrated.
- SQLite opens with `mode=ro`, `immutable=1`, and `PRAGMA query_only=ON`; the
  connection is explicitly closed. Immutable mode prevents SQLite from creating
  WAL shared-memory sidecars. Existing `-wal`, `-shm`, or `-journal` files cause
  rejection rather than a potentially stale main-database read. **Do not delete
  those files.** Have the operator provide a consistent, journal-free snapshot
  using their established backup procedure. This tool does not checkpoint or
  copy a database.
- File size, modification time, and identity are checked around the read.
  These are not a writer lock or a guarantee against concurrent changes. Later
  Graph receipts are not atomic with the local read. Keep writers stopped
  throughout comparable collections.
- `completed` and `rolled_back` are terminal maintenance phases. All other
  phases, including unknown future phases, are findings; no operation is resumed.
- Outputs must be **new `.json` files in an existing private directory**,
  outside the code/download directories and the database's containing directory.
  Inputs and existing files cannot be overwritten. The output is reserved
  exclusively before authentication; failed collection retains a redacted
  incomplete report where possible. Output I/O failure is never success.
- On POSIX the new file uses mode `0600`. On Windows it inherits the directory's
  ACL: **use an operator-approved private directory**. The tool cannot certify
  Windows directory permissions. Do not place reports in the repository, a
  shared folder, or a publicly synced location.

Reports omit raw payload/content/ACL values, configuration, credentials, local
paths, headings, raw service responses, and raw exceptions. They contain
connection/item IDs, exact public filing scopes, hashes, fixed evidence counters,
state/check results, current-interpreter dependency versions, and Graph-added
property names. Review them before sharing via an approved channel. Error codes
are intentionally generic; do not collect unfiltered logs or send `.env`, state
databases, private maintenance plans, or customer workbooks.

## Standalone Windows collection

Obtain just `src\sec_connector\diagnostics.py` from the reviewed diagnostic
release and save it as `sec_diagnostics.py` in a separate tools directory.
It is self-contained: **do not upgrade the installed connector to run it**.
Alternatively, in a development checkout run
`python .\src\sec_connector\diagnostics.py`; a normal package installation
also exposes `sec-diagnostics`. There is no `sec-connector diagnostics` command,
since that would initialize the production CLI.

Use the interpreter from the existing ingestion environment. Identify the
exact destination database, download root, installed `sec_connector` package
directory, schema file actually selected by that installation, and exact
connection ID (not its display name). Do not choose the first database found.
The installed wheel normally carries `sec_connector\resources\schema.json`;
a source checkout normally uses `config\schema.json`. `--schema` is explicit
so the diagnostic never guesses which file represents the baseline.

The following uses placeholders, not usable credentials or customer paths.
Replace all bracketed values. The output directory must already exist with
appropriate private ACLs.

```powershell
& "<existing-venv>\Scripts\python.exe" "<tools>\sec_diagnostics.py" collect `
  --db "<exact-existing-state-file>" `
  --downloads "<existing-download-root>" `
  --code-root "<installed-sec_connector-directory>" `
  --schema "<actual-schema.json>" `
  --connection-id "<exact-existing-connection-id>" `
  --out "<private-directory>\baseline-local.json"
$LASTEXITCODE
```

The default scope is exactly these PNC primary documents, with no SEC discovery
or network access:

| Filing | CIK | Accession | Document |
|---|---|---|---|
| 2025 proxy | 0000713676 | 0001193125-25-052937 | d889589ddef14a.htm |
| Fiscal-2023 annual | 0000713676 | 0000713676-24-000028 | pnc-20231231.htm |

Scope can be reused explicitly with repeatable `--scope
CIK:accession:filename` arguments. Supplying any replaces both defaults. There
are at most eight exact, unique scopes; only `.htm` and `.txt` basenames are
accepted, never directories, globs, or date ranges. For example, append:

```powershell
  --scope "0000713676:0001193125-25-052937:d889589ddef14a.htm"
```

Only these exact documents' source bytes and payloads are read. Other documents
in the selected filings are represented by filename hashes and states, not
reprocessed. Fixed PNC topic probes remain the same for custom scopes; they are
locators, not a general evaluator. No candidate matches is not evidence of
missing semantic content.

## Optional Graph GET-only receipts

Only after normal Graph access has been approved, repeat `collect` with a new
output filename and append:

```powershell
  --graph --config "<existing-config.yaml>"
```

Use the same credential-configured shell as ingestion. Only `${NAME}`
environment substitution is supported; unresolved values fail explicitly.
Config tenant and connection must match the selected database and explicit
connection ID **before MSAL is imported or authentication starts**. If the
production command used a connection override, request a reviewed diagnostic
configuration instead of modifying production configuration.

Authentication contacts Microsoft Entra and uses the existing application's
Graph permissions. The diagnostic does not grant or modify permissions.
Graph operations are exclusively `GET` against the hard-coded Graph v1.0
endpoint: the exact connection, its schema, and up to **40** locally prepared
topic-bearing item IDs in lexical order. There is no connection-wide enumeration,
pagination, PUT, PATCH, DELETE, SEC request, or repair. Entra token acquisition
itself is authentication, not a Graph GET operation.

Graph redirects are not followed. Each GET has a 45-second socket timeout,
at most three attempts, a response-size bound, and bounded numeric retry delay.
These are per-request bounds, not a total wall-clock deadline. HTTP failures,
invalid shapes/JSON, and transport failures are retained as incomplete receipts.
Schema/connection failures stop item inspection while retaining earlier receipts.
Item errors do not erase earlier successful item checks.

Candidate and selected counts, truncation, per-scope candidate counts, and every
attempted item receipt are explicit. An empty, truncated, or scope-missing
evidence sample is **incomplete**. A complete receipt set still covers only
the selected evidence IDs, not all uploaded content.

Schema fingerprints normalize property order, label/alias set order, enum case,
omitted false flags, and OData metadata. Refinability and unknown definition
fields participate in drift detection. Extra remote properties are explicit
findings, not silently ignored. Item comparisons normalize ACL entry order,
but preserve content, property values, and property-array order exactly.

## Offline report comparison

Run without credentials, config, state, or network access:

```powershell
& "<existing-venv>\Scripts\python.exe" "<tools>\sec_diagnostics.py" compare `
  --before "<private-directory>\baseline-local.json" `
  --after "<private-directory>\later-local.json" `
  --out "<private-directory>\comparison.json"
$LASTEXITCODE
```

The versioned comparison flags **input, runtime, settings, payload, delivery,
destination, maintenance, and Graph** differences separately, with category
fingerprints rather than copying raw input values. It tolerates reordered
document/item lists and ignores collection timestamps. Missing/incompatible
reports and incomplete checks do not become a pass, even if the two reports
look identical. Compare equivalent scopes and modes; offline versus Graph
collection is itself a Graph difference, not evidence of changed remote content.

| Exit | Meaning |
|---|---|
| `0` | Requested checks collected without findings, or equivalent complete reports without findings. **Not a semantic/retrieval pass.** |
| `1` | Collection findings, comparison differences, or findings retained in either compared report. |
| `2` | Incomplete/unsupported/invalid collection or comparison, unsafe output, or I/O failure. |

## Interpretation and limitations

Per-filing options are hashed in full and separately for known setting groups.
The stored processing version and captured schema hash are compared against the
operator-selected runtime and schema. A newer installed parser **does not mean**
an old prepared payload was rebuilt. Source bytes, source/cache fingerprint,
cache versus desired manifest, per-item content/properties/ACL/payload hashes,
delivery hashes and filing ownership, state, stale delivery and reconciliation counts provide
different evidence and should not be conflated.

Source fingerprints mirror the current pipeline's stored fingerprint format,
without importing or re-running it. Sampled manifests cannot reconstruct the
original per-document remaining-page budget, so their source fingerprint is
explicitly unverifiable. Missing caches and unsupported historical fingerprint
formats remain findings, not automatic corruption diagnoses.

The selected code root is operator-supplied. Dependency versions and hashed
`direct_url.json` provenance describe **this diagnostic's interpreter**, not
necessarily that selected tree, nor the interpreter that produced historical
payloads. OCR package versions are included, but the external OCR engine is
never invoked and its version is not verified. Raw provenance URLs are omitted.

`[rotated text]` counts and remaining Markdown image references identify possible
unresolved image content. An image reference can be intentional; this diagnostic
does not download images, run OCR, or prove that adjacent image assets are missing.

A Graph 403 is a permission failure, not proof of missing content. A 404 says the
requested resource was not found at that destination. A read-back mismatch
justifies investigation, not automatic repair or an indexing-failure diagnosis.
Matching Graph/local bytes still do not explain what an agent retrieved.

Collect user/agent evidence separately through approved procedures: agent ID and
published version, bound connection IDs and knowledge sources, instruction/skill
versions, signed-in user access and admin indexing status, exact prompts,
timestamps, fresh-chat indicators, model mode, answers and citations. Keep Auto
and Think Deeper trials separate. None of that user visibility or retrieval
evidence is inferred from this report.

## Maintainer checks

Run the synthetic diagnostics with the standard-library test runner (the Graph
configuration tests use the repository's existing PyYAML dependency):

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -p test_diagnostics.py
```

The same tests run under pytest. No test contacts Graph/Entra/SEC, imports
production initialization, or reads customer state. Keep state compatibility,
terminal phase names, stored payload serialization, and fingerprint assumptions
aligned with production changes. Update the report version when its format
changes incompatibly.
