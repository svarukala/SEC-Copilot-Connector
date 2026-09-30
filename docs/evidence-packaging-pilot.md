# Experimental evidence-packaging pilot

This branch is an **experimental pilot**, not a production rollout or proof of
Copilot answer quality. Its original offline stage made no live changes.
The later isolated two-connection load requires explicit approval and the frozen
manifest loader described below. Do not install this branch into an active
ingestion environment or run a broad `--reprocess` to try it.

## Exact source and treatment

The only actual filing replayed is PNC, CIK `0000713676`, accession
`0001193125-26-102189`, primary document `d62941ddef14a.htm`, sequence 1,
DEF 14A filed March 11, 2026. Source SHA-256:
`6b370b9316b08382d62d88c7b8286d9bee1ea4dd89633237a74d211f501b4931`.
Stable Graph `DocumentId`:
`4b9b7aa293e61ab7bfd24424cb87df10235eb683c9b0386fbec9ca765b74f3b5`.
The cached HTML and original SQLite manifest were opened read-only. OCR was
disabled, matching the stored processing options; no source was downloaded.

The implementation is generic, with no issuer, amount, year, or answer matching:

- Recognize short, fully bold nested inline-CSS headings outside tables and
  navigation links; partial emphasis and CSS-styled narrative sentences remain
  prose. Existing explicit headings continue to work.
- Convert unambiguous bullet-marker/spacer/prose table rows to list items.
  Preserve structured, spanned, numeric, nested, captioned, and image-bearing
  tables through the existing table conversion path.
- Keep an entire page section together if it fits the character and byte budgets,
  including adjacent prose, lists, financial tables, and footnotes. Otherwise use
  the existing bounded prose/table splitting. Do not coalesce across page or
  section boundaries. The 4,000-character target guides necessary splits;
  8,000 characters remains the upper bound, not a new target.
- Preserve the raw SEC `reportDate` in stored metadata, but use it for the
  `ReportPeriodEnd` property and report-period prefix only for 10-K/10-Q and their
  amendments. Proxy meeting dates and 8-K event dates are not fiscal periods.
  No compensation year is inferred from the filing year or meeting date.

Processing version is now 5. Existing prepared manifests remain replayable;
this change does not rewrite them. Do not assume ordinary resume applies this
experiment to existing prepared payloads.

## Offline observations

| Observation | Current-code baseline (v4) | Candidate (v5) |
|---|---|---|
| Full primary-document item count | 1,089 | 566 |
| Items containing the three numeric pay-ratio facts | 3 | 1 |
| Numeric evidence ordinals | 759-761 | 429 |
| Numeric evidence content length | 604 / 396 / 398 characters | 2,477 characters |
| Section title on numeric evidence | Prior equity-award/MNPI section | CEO pay ratio |
| Proxy date treatment | April 22, 2026 labeled report period | Raw date retained; fiscal property/prefix omitted |
| Largest content item | 6,458 characters | 7,993 characters |
| Largest serialized request | 7,560 bytes | 9,109 bytes |

The historical v3 SQLite snapshot contained **1,091** primary-document payloads;
it is retained separately and is not confused with the v4 baseline replay.
Both replays use identical source bytes, 4,000/8,000/200 character settings,
30 MiB request ceiling, document metadata, and no OCR.

The candidate evidence item `0000713676-000119312526102189-1-119-2` contains the
heading, explicit year ended December 31, **2025**, CEO compensation
**$29,530,103**, median employee compensation **$130,900**, reported ratio
**226 to 1**, methodology, and footnote. It preserves the printed page **110**.
`Page=119` remains the source segment ordinal, not the printed page number.
The ratio is retained as reported, not recomputed from rounded displayed values.

The full before/after parsed documents contain the same **92,274 lexical tokens
in identical order**. Every candidate source token also appears in order across
the output items (ignoring page markers and permitting repeated context).
These checks establish textual coverage for this cached document, not universal
parser correctness or retrieval success. Synthetic regressions additionally
cover financial table structure, false headings, section boundaries, byte
limits, and fiscal-period metadata. The full offline suite passed 300 tests with
the exact-source replay and baseline coverage comparison enabled. Final payload
artifacts reproduced byte-for-byte; historical scoped payload snapshots were
unchanged.

Before/after payloads, historical payloads, source hash, and summaries are private
session artifacts, not repository data. The optional actual-source regression
requires the exact hash above and blocks socket connections:

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:SEC_EVIDENCE_PILOT_SOURCE = '<absolute path to the exact cached HTML>'
# Optional: directory containing the saved v4 parsed.md and summary.json.
$env:SEC_EVIDENCE_PILOT_BASELINE = '<absolute path to pilot-before>'
python -m pytest tests\test_evidence_packaging.py -q --basetemp '<isolated new temp directory>'
```

## Approval-only destination and replacement proposal

Propose two **new, isolated** connections in the explicitly approved tenant:
`secevidencepilot20260930a` (saved v4 baseline) and
`secevidencepilot20260930b` (saved v5 candidate). The exact proposed tenant identity
is recorded privately with the handoff, not in repository documentation.
The historical connection `secedgar20260909v2` remains untouched. Names and tenant
selection are proposals, not evidence of availability, creation, or permission.

The upload allowlist for each arm is exactly the CIK, accession, primary filename,
sequence, and stable `DocumentId` above. No exhibits, other accessions, other
issuers, or date-only selection qualify. Initial isolated loads contain the full
primary document (1,089 baseline / 566 candidate items) so neighboring evidence
and negative controls remain available. Initial loads require no deletion.
Use independent state stores; do not copy or adopt the historical database.
Current ticker/date-scoped ingestion is **not** an exact-document uploader.
Use only the scope-checked frozen-manifest loader below after approval.

If a later request explicitly authorizes replacement rather than isolated loads,
first stop/coordinate writers and record the exact destination and old IDs.
Prepare the complete desired primary-document manifest and preserve all old
acknowledged or potentially delivered IDs. Upload and acknowledge all desired
items before deleting only `old scoped IDs - desired IDs`. Incomplete delivery
must block deletion. Do not delete entire filings/connections, reset state,
prune an inventory, or reconstruct scope from dates or chunk ordinals. Chunk IDs
can overlap across versions with changed content; this is not an atomic swap.
Freeze evaluation during replacement and wait for indexing/readback afterward.

## Controlled A/B evaluation (not executed)

The user subsequently reported that updated instructions alone returned the
correct CEO pay ratio. This is a user-reported successful observation, not a
controlled repeated evaluation: exact instruction/skill versions and chat
freshness were not captured. The packaging hypothesis is therefore improved
consistency and less dependence on follow-up retrieval, **not** correction of a
universally failing baseline. The updated instructions can be the shared A/B
configuration once their exact version is confirmed, without changing them
between arms.

Hold the **base agent instructions and installed skills identical** across A/B.
Record the exact instruction hash and each skill's presence, version, and content
hash, including the separately authored evidence-recovery and CEO-pay-ratio
skills if installed. If skills are absent, record absent in both arms. Do not add
or edit a skill in only one arm, improve the prompt mid-trial, or mix packaging
and instruction changes. Any instruction/skill variant is a separate experiment.

Record schema, ACL, source hash, payload-manifest hashes, agent/model identity
when available, knowledge-source restrictions, indexing/readback timestamps,
and run order. Use the same configuration except the selected A/B connection
and this documented packaging treatment (headings, coalescing, and date semantics).
Restrict the agent to one arm at a time; do not expose both arms or the historical
connection in the same trial. Disable other knowledge/web sources where possible
or record their presence as a limitation.

After independently verifying indexing and source access in each arm, run each
prompt at least three times per arm in **fresh chats**, alternating/randomizing
arm order. Do not paste the expected numbers into prompts or reuse a conversation.
Retain verbatim responses and cited document/page evidence; do not treat a missing
citation or unavailable indexing as a factual pass.

| Prompt/control | Predefined evaluation |
|---|---|
| "Using PNC's DEF 14A filed March 11, 2026, what CEO-to-median-employee pay ratio was reported? Include the year and both compensation amounts, with a source citation." | Correct reported ratio, both amounts, 2025 compensation year, correct filing and printed page 110. |
| "What was PNC's CEO pay ratio for 2025, according to its 2026 proxy?" | Same supported answer; distinguish compensation year from proxy year. |
| "Does the 2026 proxy's CEO pay-ratio disclosure describe 2026 compensation? Explain the relevant dates." | It reports 2025 compensation; April 22, 2026 is not a fiscal period end. |
| "Does this filing establish PNC's CEO pay ratio for compensation earned in 2026?" | State that this disclosure does not establish it; do not reuse 226 to 1 as a 2026 compensation fact. |
| "How was the median employee selected, and why can the CEO amount differ from the Summary compensation table?" | Ground methodology in the source, including employee population and health-care premium contributions; do not substitute Summary compensation/CAP amounts. |
| "In the neighboring Pay versus performance section, which Company-Selected Measure is identified? Is compensation actually paid the CEO pay-ratio numerator?" | Source identifies one-year adjusted ROE; distinguish CAP from pay-ratio compensation and cite the appropriate neighboring section. |

Score reported ratio, CEO amount, median amount, compensation year, citation,
and absence of unsupported inference separately. Compare complete-answer rates
and period/neighbor-control outcomes, retaining failures and run counts.
Advance only if the candidate improves coherent source-grounded answers without
regressing period or neighbor controls; a tie or inconsistent results remain
inconclusive. **Offline co-location is not actual Copilot success.**

## Frozen-manifest loader

`python -m sec_connector.pilot_upload --plan <private-plan.json>` performs local
validation only. It does not authenticate, create state, or contact Graph.
The private plan binds the approved tenant, forbidden historical connection,
two new destination IDs, source hash, schema hash, each manifest path/hash/count,
and exact CIK/accession/filename/sequence/DocumentId/form/filing-date scope.
The plan contains no credentials. Credentials come only from the existing
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` environment variables.

Only after explicit approval, add `--execute --state-dir <new-private-pilot-dir>`.
Both complete manifests are validated before authentication. The loader checks
the MSAL-issued token's tenant, application, Graph audience, and application
permission claims, then checks both destinations for collisions before creating
either. It refuses to adopt an existing connection or to use the forbidden
historical connection. It retains the frozen payload ACL (`everyone` grant)
and checks each request against the existing 8,000-character/30 MiB limits.

The loader uses one independent journal per arm and an exclusive pilot lock.
Each journal binds the tenant, app, destination, hashes, scope, and count.
Connection POST and schema PATCH are dispatched at most once per journal:
an uncertain acknowledgment stops execution rather than repeating the mutation.
Schema polling follows the recorded native operation, verifies completion,
and compares the persisted schema to the frozen definition before any item PUT.
A collision race (409) is an error, not permission to adopt a connection.

Uploads are sequential bounded individual PUTs. Every acknowledged item records
its payload hash atomically on disk. Reusing the **same plan and journals** resumes
only missing uploads; uncertain item PUTs can be replayed with the same ID and
same frozen bytes. Every item is then read by its exact Graph ID and compared
with all submitted properties, content, and ACL. Readback hashes and final counts
are persisted separately from upload acknowledgments. No DELETE is supported.

Do not change the plan, remove a journal, invent a replacement destination, or
delete a surviving lock to recover an uncertain creation. First confirm no writer
is running and reconcile the saved native identity. A lock left after process
termination needs operator review. Schema timeout resumes the recorded operation,
never resubmits the PATCH. Remote readback failure does not erase acknowledged
uploads or authorize deleting them.

The final journal reports two distinct counts: PUT acknowledgments and successful
exact-item GET comparisons. Neither proves Microsoft Search indexing, agent
retrieval readiness, or Copilot efficacy. An application can read its external
items before they are available to a user's search or agent.

For agent binding, select only `SEC evidence pilot baseline`
(`secevidencepilot20260930a`) for arm A or only `SEC evidence pilot candidate`
(`secevidencepilot20260930b`) for arm B in the approved tenant. The uploader does
not create or edit agents, install skills, enable web sources, or grant new
permissions. Keep identical instructions, skills, schema and ACL configuration;
the only intended difference is the frozen packaging treatment. Perform those
bindings separately with authorization, verify source visibility in each arm,
then use the fresh-chat evaluation protocol above.
