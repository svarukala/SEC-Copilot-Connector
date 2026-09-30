# Version-8 five-bank live sample

## Approved scope and loader

The user authorized **one new connection and exactly 25 documents: five each for
PNC, WFC, JPM, BAC and USB**. The destination is `secevidencev820260930`, display
name **SEC evidence pilot v8 - five-bank sample**, in tenant
`144b8c80-398d-405e-8055-fc9a9d5013f8`. Its 21-character alphanumeric ID and display
name meet the [Graph externalConnection limits](https://learn.microsoft.com/graph/api/resources/externalconnectors-externalconnection?view=graph-rest-1.0).
This authorization does not extend to agents, skills, evaluations, deletion,
existing connections or broad ticker/date ingestion.

`python -m sec_connector.sample_upload` accepts a private frozen plan and its
separately supplied SHA-256. It validates five documents per approved ticker,
unique document/source/item identities, exact accession/filename/sequence/CIK,
source and payload hashes, reviewed preflight evidence, processing-code/config/
schema hashes, per-document ordered chunk counts, ACL and request budgets.
Exhibit type is distinct from filing form. No payload is reparsed during upload.

The loader reuses the tested pilot create/schema journal: existing connections
are rejected, unknown create/schema acknowledgments are never redispatched,
native schema operation identity is retained, and exact schema readback is
required. A dedicated exclusive lock prevents concurrent sample writers.
Individual idempotent PUTs and GET readbacks run at most five at a time; every
acknowledgment is atomically checkpointed, including successful requests from a
partially failed batch. Resume is bound to the same plan, app and destination.
GET comparisons verify ID, all properties/content values and ACL, excluding only
OData protocol annotations. No DELETE path or discovery/ingest call is used.

The production path was reviewed: `parse_document` carries the source header
sidecar through `chunk_with_limit`/`chunk_document`; Graph payload construction
does not serialize it. Processing version remains **8**, with no new parser,
chunker or payload transformation semantics. Cache fingerprints include captured
processing version/settings; ordinary resume replays prepared payloads rather
than upgrading them. This sample has independent frozen files/journal, not the
original connector database.

## Selection and evidence

The sample retains the validated 20-source v8 corpus and adds five cached sources:
WFC's second-quarter 2026 financial supplement and 2025 proxy, JPM's second-quarter
2026 supplement, BAC's corresponding financial supplement, and USB's earnings
release. These provide substantive text/tables, not image-only presentation
exports. PNC includes the original 2026 proxy positive control and a 2022 proxy.
Each issuer has a proxy, annual filing and quarterly filing plus two complementary
documents. BAC retains its previously validated voting-results 8-K.

WFC and USB annual primary filings are incorporation-limited. The authorized
cached document inventory contains no incorporated annual report exhibit for
those selected annual filings. Rather than silently downloading one, the sample
retains those annuals and supplements them with substantive cached quarterly and
earnings material. This is not a claim to index their complete incorporated
annual reports. Older JPM/USB/BAC quarterlies deliberately retain validated
period/layout controls, not a latest-only coverage claim.

Private evidence lives under `sample-v8-25`, separate from all frozen v4/v5/v6/v7
and prior v8 artifacts. Original cache/source/SQLite are read-only; the new plan
pins exact source bytes and payloads. Receipt and matrix are added after live
completion; this section alone does not assert a connection exists.

## Operation and evaluation boundaries

```powershell
python -m sec_connector.sample_upload --plan '<private plan.json>' --plan-sha256 '<reviewed hash>'
python -m sec_connector.sample_upload --plan '<same plan.json>' --plan-sha256 '<same hash>' --state-dir '<dedicated sample state>' --execute
```

The first command is offline validation. The second requires the existing
environment credentials for the approved tenant, validates MSAL token
tenant/app/audience/application roles, and checks destination absence before
creation. Resume uses exactly the same arguments; an unknown create/schema
dispatch requires manual reconciliation, not a new journal.

Upload acknowledgment and matching external-item GETs establish Graph storage
persistence, **not search/index readiness or Copilot answer quality**. No agent
binding or evaluation is performed here. Any future evaluation must independently
verify source visibility, use fresh chats, and keep exact base instructions and
installed skill content/version fixed. Source-grounded acceptance questions
belong to a separate evaluation handoff, not runtime instructions.
