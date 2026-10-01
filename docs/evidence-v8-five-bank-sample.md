# Version-8 five-bank live sample

## Completed live result

**One new connection was created and all 25 documents / 8,513 items were uploaded
and read back successfully.** Final item checkpoint:
**2026-10-01 00:43:00 UTC (2026-09-30 20:43:00 EDT)**.
The independently checked local receipt confirms the exact frozen item-ID/hash
sets, every document count and all source/payload/provenance hashes. No writer
lock remains.

| Issuer | Documents | Desired | PUT acknowledged | GET verified |
|---|---:|---:|---:|---:|
| PNC | 5 | 2,064 | 2,064 | 2,064 |
| WFC | 5 | 1,110 | 1,110 | 1,110 |
| JPM | 5 | 2,222 | 2,222 | 2,222 |
| BAC | 5 | 2,162 | 2,162 | 2,162 |
| USB | 5 | 955 | 955 | 955 |
| **Total** | **25** | **8,513** | **8,513** | **8,513** |

Final connection GET confirms ID **`secevidencev820260930`**, name
**SEC evidence pilot v8 - five-bank sample**, native connection state **`ready`**,
and all **22 schema properties** compatible with the frozen schema. The native
schema operation completed and was tracked in the dedicated journal. Maximum
emitted content is **7,998 characters**; maximum serialized request is
**10,003 bytes**. All 8,513 GETs matched submitted properties/content/ACL, with
the five extra Graph metadata properties separately retained as described below.
Transient PUT/GET failures recovered under bounded retry; no unresolved upload
or readback failure remains.

**Native connection readiness and Graph persistence are not proof of search
visibility or Copilot answer quality.** The loader did not edit or evaluate an
agent. A subsequent user-reported evaluation is recorded separately below.
Production `secedgar20260909v2` and both earlier PNC pilot connections were not
mutated. No delete, prune/reset, broad ingest, source download, shared database/
cache/environment edit, main merge or push was performed.

The sanitized [machine-readable result](evidence-v8-five-bank-results.json)
records counts, limits, revision identities and receipt hashes. Private evidence
is in the session's `files\sample-v8-25` directory: `plan.json`, `preflight.json`,
`live-state\sample.json`, `final-receipt.json`, `final-connection-readback.json`,
the frozen candidate payload sets and source audits. Initial uploader revision:
`c88dd619b7dbadca4ae6aa427da542886da56b92`; corrected readback revision:
`d4034c7d3e0ea4bb7a7c1a4099706653e52a8dd4`. The latter did not alter version-8
processing or any uploaded payload.

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
GET comparisons verify ID, every submitted properties/content value and ACL.
OData protocol annotations are excluded; the separately documented, typed
five-property service metadata band is retained separately in the private
journal, never substituted for submitted fields. Other unexpected properties
still fail verification. No DELETE path or discovery/ingest call is used.

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
pins exact source bytes and payloads. Completion evidence is recorded above;
the matrix below identifies the exact delivered scope.

### Frozen document matrix

Each count below now has matching PUT acknowledgments and exact submitted-field
GET verification in the final receipt. Filing dates are filing metadata, not
dates inferred from filenames. Two different
exhibits in one accession remain distinct documents and have distinct sequence
prefixes/DocumentIds. No document or identical source bytes count twice within
an issuer.

| Issuer | Filing form | Filed | Accession | Filename | Sequence | Items |
|---|---|---|---|---|---:|---:|
| PNC | DEF 14A | 2026-03-11 | 0001193125-26-102189 | d62941ddef14a.htm | 1 | 556 |
| PNC | DEF 14A | 2022-03-16 | 0000713676-22-000023 | pnc2022proxystatement.htm | 1 | 344 |
| PNC | 10-K | 2026-02-20 | 0000713676-26-000020 | pnc-20251231.htm | 1 | 639 |
| PNC | 10-Q | 2026-08-05 | 0001628280-26-053170 | pnc-20260630.htm | 1 | 393 |
| PNC | 8-K | 2026-07-15 | 0001628280-26-048244 | q22026financialsupplement.htm | 3 | 132 |
| WFC | DEF 14A | 2026-03-18 | 0000072971-26-000200 | wfc-20260318.htm | 1 | 318 |
| WFC | DEF 14A | 2025-03-19 | 0000072971-25-000090 | wfc-20250317.htm | 1 | 291 |
| WFC | 10-K | 2026-02-24 | 0000072971-26-000133 | wfc-20251231_d2.htm | 1 | 60 |
| WFC | 10-Q | 2026-07-28 | 0000072971-26-000302 | wfc-20260630.htm | 1 | 370 |
| WFC | 8-K | 2026-07-14 | 0000072971-26-000288 | wfc2qer07-14x26ex992xsuppl.htm | 3 | 71 |
| JPM | DEF 14A | 2026-04-06 | 0000019617-26-000096 | jpm-20260402.htm | 1 | 268 |
| JPM | 10-K | 2026-02-13 | 0001628280-26-008131 | jpm-20251231.htm | 1 | 1,035 |
| JPM | 10-Q | 2024-10-30 | 0000019617-24-000611 | jpm-20240930.htm | 1 | 764 |
| JPM | 8-K | 2026-07-14 | 0001628280-26-048078 | a2q26erfexhibit991narrative.htm | 2 | 14 |
| JPM | 8-K | 2026-07-14 | 0001628280-26-048078 | a2q26erfex992supplement.htm | 3 | 141 |
| BAC | DEF 14A | 2026-03-23 | 0001193125-26-118929 | d43888ddef14a.htm | 1 | 342 |
| BAC | 10-K | 2026-02-25 | 0000070858-26-000157 | bac-20251231.htm | 1 | 907 |
| BAC | 10-Q | 2025-10-31 | 0000070858-25-000405 | bac-20250930.htm | 1 | 732 |
| BAC | 8-K | 2026-05-06 | 0000070858-26-000273 | bac-20260504.htm | 1 | 20 |
| BAC | 8-K | 2026-07-14 | 0000070858-26-000353 | bac-06302026ex993.htm | 4 | 161 |
| USB | DEF 14A | 2026-03-10 | 0001104659-26-025844 | tm261379-1_def14a.htm | 1 | 404 |
| USB | 10-K | 2026-02-23 | 0000036104-26-000011 | usb-20251231.htm | 1 | 96 |
| USB | 10-Q | 2023-11-01 | 0001193125-23-268341 | d542369d10q.htm | 1 | 392 |
| USB | 8-K | 2026-07-16 | 0000036104-26-000039 | a2q26earningssupplement.htm | 3 | 21 |
| USB | 8-K | 2026-07-16 | 0000036104-26-000039 | a2q26earningsrelease.htm | 2 | 42 |

Total: **25 documents / 8,513 items**. Issuer totals: PNC 2,064; WFC 1,110;
JPM 2,222; BAC 2,162; USB 955.

### Offline preflight and remaining limitations

All 20 previous v8 payload sets reproduced byte-for-byte. The additional five
sources preserve v7 parser Markdown and source cells, ordered lexical/numeric
coverage and data-row occurrences. IDs/output are deterministic; exact document
metadata, everyone-grant ACL, context-inclusive 8,000-character bounds and
31,457,280-byte serialized request ceilings pass. The complete suite, including
opt-in historical and source-structure audits, passed **442 tests, zero skipped**.
Loader coverage includes altered allowlists/provenance, cross-document identity
and prefix collisions, count errors, exact readback mismatch and partial-batch
resume. No shared environment reinstall was used.

One additional JPM source-derived header band was manually checked against its
native rows, spans, alignment, period groups and first data boundary. No new
period-context or explicitly linked-note gaps were introduced. The unchanged
period diagnostic for the additional sources decreased from **23 to 17**:
11 remain in JPM's earnings supplement and six in USB's earnings release. These
are pre-existing conservative-header/co-location limitations, not missing source
rows, and are **not certified as universally self-contained**. Three new broad
JPM note-diagnostic misses concern unmarked noninterest-revenue rows; the nearby
`(a)` qualifier belongs to marked net-yield rows, not those unmarked rows.
Existing indirect/cross-page and oversized-context limitations remain as
documented in the [v8 remediation report](evidence-source-header-remediation.md).
No semantic expansion was made for this live sample.

The frozen private `plan.json` SHA-256 is
`30d54f640ff6e9fdaae04970d135d61299da19f0e61e79c582e97f20cedc0192`.
It pins loader revision `c88dd61`, version-8 processing-file hashes, exact source
and payload hashes, schema/config hashes and the reviewed `preflight.json`.
Private `manifest.json`, `candidate`, `baseline-additional`,
`comparison-additional.json` and `audit-additional.json` preserve reproducible
selection and comparison evidence without committing source corpora or journals.

### Readback adapter correction

The initial run created the connection/schema and acknowledged all **8,513 PUTs**,
then stopped with **zero verified readbacks** because Graph added five properties
not present in the submitted payload or declared schema:
`IsDGBasedSecurityEnabled`, `ows_SiteID`, `ows_WebId`, `ows_ListID`, `ows_UniqueId`.
A read-only first-item diagnosis showed no mismatch in submitted properties,
content or ACL. This is observed behavior in this destination, not a claim that
these additions are a documented universal Graph API contract.

The aggregate reader now explicitly accepts only that complete extra band:
one strictly Boolean value and four canonical GUID-shaped strings, none declared
in the frozen schema or submitted payload. It records their actual values
separately per item in the private journal **after** every submitted value/content/
ACL passes exact comparison. Missing/changed submitted values, unknown additions,
partial or malformed metadata, schema overlap, and changed content/ACL still
fail. The original single-document reader remains strict by default.

This is a receipt-comparison correction, not a processing-version or payload
change. The same plan/hash/journal is resumed; acknowledged items are not
reuploaded, and create/schema dispatch is not repeated. The frozen v8 source/
payload artifacts and all older evidence stay unchanged. The final receipt
records the readback loader revision separately from the initial frozen loader.
The correction passed **72 loader tests** and the full **453-test** suite,
including the opt-in real-source audits, with zero skips.

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

## Source-verified acceptance handoff (not executed by the loader)

These are evaluator prompts and expected answers, **not agent instructions or
skills to deploy**. Expected values were checked against the selected cached
source HTML cells and actual period/units bands. Private
`acceptance-source-rows-utf8.json` records raw row/cell/span mappings for the four
financial examples. The earlier PNC source evidence remains the positive control.

| Control | Suggested prompt | Source-backed expected answer |
|---|---|---|
| PNC proxy/year | In PNC's 2026 proxy, what CEO pay ratio was reported for 2025, and what CEO and median employee compensation supported it? | **226 to 1**, CEO **$29,530,103**, median employee **$130,900**, compensation year **2025**; printed page **110**. Report the source's ratio rather than substituting a calculated unrounded quotient. The 2026 filing/meeting year is not the compensation year. |
| WFC period/unit | From Wells Fargo's second-quarter 2026 financial supplement, give total revenue and diluted EPS for the quarter and six months ended June 30, 2026, with units. | Quarter revenue **$22,622 million**, six-month revenue **$44,068 million**; diluted EPS **$2.00** and **$3.60 per common share**, not millions per share. Summary Financial Data, printed page **3**. The supplement calls its results preliminary. |
| JPM grouped header | From JPMorgan's second-quarter 2026 supplement, compare reported and managed-basis net interest income for 2Q26 and the six months ended June 30, 2026. | Reported **$25,511 million / $50,877 million**; managed basis **$25,622 million / $51,101 million**, respectively. Keep quarterly and six-month groups distinct; do not use the adjacent change columns as amounts. Printed page **28**. |
| JPM linked note | In that supplement, what was the 2Q26 net yield on average interest-earning assets on a managed basis, and what does its linked note (a) qualify? | **2.40%**. Note **(a)** includes derivatives qualifying for hedge accounting, uses taxable-equivalent amounts where applicable and refers to Note 5 of the firm's 2025 Form 10-K for additional hedge-accounting information. Associate it with the marked net-yield row, not every nearby revenue row. Printed page **28**. |
| BAC period/per-share | From Bank of America's second-quarter 2026 supplement, give net income and diluted EPS for the quarter and first six months of 2026. | Quarter net income **$9,074 million**, six-month net income **$17,658 million**; diluted EPS **$1.21 / $2.31 per common share**, respectively. Consolidated Financial Highlights, printed page **2**. Do not substitute net income applicable to common shareholders. |
| USB attribution/period | From U.S. Bancorp's second-quarter 2026 earnings release, give net income attributable to U.S. Bancorp for 2Q26 and YTD 2026, distinguishing the prior-year quarter. | **$2,177 million** for 2Q26; **$4,122 million** YTD 2026; the 2Q25 comparison is **$1,815 million**. Use the row with the issuer attribution, not net income before noncontrolling interests. Income Statement Highlights. |

Exact source citations:

- [PNC 2026 proxy, accession 0001193125-26-102189](https://www.sec.gov/Archives/edgar/data/0000713676/000119312526102189/d62941ddef14a.htm).
- [WFC 2Q26 supplement, accession 0000072971-26-000288](https://www.sec.gov/Archives/edgar/data/0000072971/000007297126000288/wfc2qer07-14x26ex992xsuppl.htm).
- [JPM 2Q26 supplement, accession 0001628280-26-048078](https://www.sec.gov/Archives/edgar/data/0000019617/000162828026048078/a2q26erfex992supplement.htm).
- [BAC 2Q26 supplement, accession 0000070858-26-000353](https://www.sec.gov/Archives/edgar/data/0000070858/000007085826000353/bac-06302026ex993.htm).
- [USB 2Q26 release, accession 0000036104-26-000039](https://www.sec.gov/Archives/edgar/data/0000036104/000003610426000039/a2q26earningsrelease.htm).

For an operator-approved evaluation, bind the intended agent knowledge source
exclusively to **SEC evidence pilot v8 - five-bank sample**
(`secevidencev820260930`) and verify that binding and search visibility before
interpreting results. This handoff does not perform or authorize that agent edit.
Keep exact base instructions and installed skill presence/content/version fixed;
record them alongside model, source binding, prompt, chat freshness, attempt
count, full answer, citations and timestamps. Use fresh chats for repeated
attempts and keep the expected-answer sheet out of runtime context. The five-bank
sample is not itself a controlled packaging A/B because the existing live
baseline/candidate connections contain only one PNC document.

Include neighbor controls: PNC's 2022 versus 2026 proxy must not be blended;
JPM's quarter/half-year/change columns must not be swapped; WFC/BAC per-share
exceptions must not inherit the million-dollar unit; USB attributed income must
not become consolidated net income. Retrieval failure does not prove the
uploaded connector lacks a disclosure. Previous user-reported PNC success
remains a promising observation, not measured v8 efficacy or latency.

## October 1 user observation and bounded JPM diagnosis

### Reported evaluation, not independently captured execution

At **2026-10-01 10:29 EDT**, the user reported testing all **seven supplied
prompts once**, each in a fresh chat: all were accurate except the JPM
linked-footnote prompt under **Auto**. One retry of the same prompt under the
user-labeled **"GPT Sol Think"** was reported accurate. This is six reported
successes and one reported failure in the initial one-pass set, plus one
successful retry, not a repeated or configuration-controlled benchmark.
The exact seven prompt texts were not captured in this diagnosis; the six-row
suggested handoff above must not be mistaken for the complete executed set.

The parent session relayed the following screenshot observations; this diagnosis
did not independently inspect screenshots or retrieved execution traces:

| Displayed selection | Relayed answer facts |
|---|---|
| Auto | Managed 2Q26 net yield **2.47%**; generic managed-basis/FTE note (a) discussing GAAP reclassifications, tax-credit/tax-exempt investments, related income-tax expense and no net-income effect; cites Non-GAAP Financial Measures note (a). |
| "GPT Sol Think" | **2.40%**; derivatives qualifying for hedge accounting, taxable-equivalent amounts where applicable, and Note 5 of the 2025 Form 10-K. These match the source-verified expected answer. |

Both screenshots displayed **SEC Candidate Agent**. Actual connection binding,
exact instructions and installed skills, underlying model selected by Auto,
retrieved passages and any retrieval differences are unverified. Fresh-chat
usage is user-reported. The screenshots do not establish identical retrieved
evidence, model-only causality, measured latency or general success rates.
No new evaluation, agent modification or live read/write was performed for this
diagnosis.

### Raw-source findings

Scope was the exact cached
`a2q26erfex992supplement.htm`, accession **0001628280-26-048078**,
plus a bounded search for the exact `2.47` token in the five already-uploaded
JPM documents. Source and payload files were read only. The target source hash
remains `d28c9dcf0f03250bfd1d921ff1f9403adaab8f726877c84765dca6b1c42e1661`;
its frozen payload-file hash remains
`47baf257309fb2b959ce780f7fc3a43f8e60926c4142570f8d599575538be2a9`.
No replay, new corpus, download or semantic change was needed.

In the [selected supplement](https://www.sec.gov/Archives/edgar/data/0000019617/000162828026048078/a2q26erfex992supplement.htm),
printed **page 28** has two distinct notes labeled **(a)**:

1. The introductory **Non-GAAP Financial Measures (a)** paragraph defines
   managed basis from reported U.S. GAAP results, reclassifies revenue to an FTE
   basis, discusses tax-credit/tax-exempt investments and corresponding tax
   expense, and states the adjustments do not affect net income. This is the
   source-backed match for the generic explanation relayed from Auto, not proof
   that this exact passage was retrieved.
2. After the comparison table, a separate local **(a)** says derivatives
   qualifying for hedge accounting are included, taxable-equivalent amounts are
   used where applicable, and refers to Note 5 of the 2025 Form 10-K. The table's
   **"Net yield on average interest-earning assets - managed basis (a)"** row
   links to this local note. Its **2Q26** cell is **2.40%**.

The table's actual grouped columns are quarterly **2Q26, 1Q26, 4Q25, 3Q25,
2Q25**, adjacent quarter-change columns, then **six months ended June 30:
2026, 2025**, and a change column. The managed net-yield row contains
**2.40%, 2.50%, 2.54%, 2.45%, 2.43%** for those quarters and
**2.45%, 2.51%** for the half-years. The unit caption is
**"in millions, except rates"**; the source explicitly marks yield cells `%`.
Neither a neighboring period nor a different row in this supplement supplies
**2.47**: there are **zero exact numeric-token occurrences** in rendered source
text, **zero literal `2.47` byte substrings** in its cached HTML, and none in its
141 frozen payloads.

There are three source-text occurrences of **2.40**: the page-28 managed
net-yield cell above; the **2Q26 NET YIELD ON INTEREST-EARNING ASSETS** row
on printed page **6**; and the **2Q25 interest-bearing-deposits rate** in that
page-6 annualized-yields table. Identical numeric text alone is therefore not a
sufficient row/period match.

The bounded five-JPM-document payload search found one **2.47** occurrence in
the [2025 annual report](https://www.sec.gov/Archives/edgar/data/0000019617/000162828026008131/jpm-20251231.htm),
not the requested supplement. Raw HTML confirms it is the **held-to-maturity
mortgage-backed securities average yield**, **due after one year through five
years**, at **December 31, 2025**. Its local note (a) defines average yield using
effective security yields weighted by amortized cost, with additional
coupon/premium/discount/hedging/prepayment qualifications. It is not a 2Q26
Firmwide managed net yield. Its existence is an alternate source-value
possibility, **not attribution of Auto's answer to this item**; other sources
outside this bounded JPM search and the actual retrieval remain unknown.

### Frozen uploaded-payload findings

The item hashes below were checked against both the persisted acknowledgment
and exact submitted-field GET-readback hashes in the completed sample journal.
This confirms the historical uploaded evidence, not what either live answer
retrieved on October 1. All abbreviated supplement IDs share the prefix
`0000019617-000162828026048078-3-`.

| Exact item ID or suffix | Ordinal | Frozen content and context |
|---|---:|---|
| `29-4` | **139** | **3,957 characters** including issuer/form/section prefix, full quarterly/half-year/change header bands, units, the managed-basis **2Q26 2.40%** row and its **own hedge-accounting (a)**. The generic managed-basis paragraph is **absent**. |
| `29-2` | **137** | **3,304 characters** containing the introductory generic managed-basis/FTE **(a)** and neighboring explanatory notes. No **2.40** or **2.47**, and no hedge-accounting note. |
| `29-6` | **141** | **297 characters** containing the original trailing hedge-accounting **(a)** and literal **Page 28** footer. The same note is also explicitly repeated as local context in item 139. |
| `7-7` | **33** | Earlier page-6 net-yield row with **2Q26 2.40**; this alternative occurrence's item lacks the full quarterly/half-year header band and hedge-accounting note. This is an existing context limitation, not the fully contextualized page-28 answer item. |
| `7-6` | **32** | Earlier page-6 interest-bearing-deposits row, whose **2Q25** rate is **2.40**; not the requested metric/period. |
| `0000019617-000162828026008131-1-234-5` | **746** | Separate annual-report maturity/yield item with **2.47%**, correct December 31, 2025 maturity-band header, held-to-maturity/mortgage-backed grouping and its own average-yield note (a). |

Items 137 and 139 both correctly carry source section
**`Non-GAAP Financial Measures`**, the same document URL and DocumentId
`13997fdcecaf12d30277e68dc2bed54893ca8400ee1ee14285193814233c5937`.
Their `Page` metadata is **29** and titles use **Page 29.2 / Page 29.4**:
these are parser page-segment positions, not printed-page labels. The source
footer says **Page 28**. This is a concrete citation-navigation limitation;
do not interpret a metadata/printed-page offset as a different financial period.
These fields do not identify a unique table or note scope.

**Conclusion:** the target item preserves the correct cell, full period/units
context and correct local note together. The wrong generic note is a separate,
valid source passage, **not a qualifier incorrectly appended to that target
row by packaging**. Source reuse of `(a)`, a shared broad section label, wide
tables and other less-complete chunks leave genuine retrieval/interpretation
ambiguity. No new corruption or missing-context defect was established for
item 139. Existing alternate-item context and printed-page metadata limitations
are observable, but neither is established as the cause of this answer.
Auto's **2.47%** is unsupported by the requested supplement; its origin and the
selection of the generic note cannot be assigned without execution evidence.

### Recommended targeted repeat controls (not run)

Preserve the **exact original user prompt** for the primary comparison; capture
its literal text first rather than silently substituting the suggested prompt
above. Confirm and record the selected connection, exact instruction content,
skill presence/version and user-visible model choice. Run a small balanced set
of fresh-chat repeats under Auto and the same user-labeled Think choice, varying
only that choice where the product permits it. Preserve all answers/citations
and retrieved item IDs/passages when available; an agent display name or source
URL alone does not establish identical retrieval.

Score value, metric, period, basis, correct **local** note and citation scope
separately. Specifically look for item **139** versus **137**, earlier
supplement item **33**, or annual item **746**. If retrieval traces are
unavailable, record that uncertainty rather than diagnosing a model-only cause.

Keep two follow-ups separate from the original-prompt result: a page/table-scoped
prompt explicitly asking for the marked net-yield row and its note below the
page-28 table, and, if supported, an evidence-controlled comparison supplying the
same exact item-139 passage to each choice without an answer key. The first
changes retrieval guidance; the second tests interpretation under fixed
evidence, not end-to-end retrieval. Do not combine either with the unchanged
prompt's success counts. No automatic instruction change, parser fix or live
reingestion follows from this one-pass observation.
