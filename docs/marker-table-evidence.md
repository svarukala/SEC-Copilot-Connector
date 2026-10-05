# Source-derived marker-table evidence (processing v10)

An exact sparse table can still be misread when matching distant column names
to markers. Processing v10 adds a deterministic representation of visible cells
for a deliberately bounded class of matrices. It is not an answer generator,
issuer-specific rule, or proof of retrieval or Copilot accuracy.

## Representation

The parser's Markdown is unchanged: original table rows, spacers, numbers,
headings, and notes remain in source order. A source-table-hash-bound sidecar
captures ordered row labels, their field headers, multi-level column paths,
original HTML row/column coordinates, and each exact marker or empty cell.
Unambiguous vertical row-label spans retain hierarchical identity. No names,
table indexes, text keywords, expected counts, or evaluation answers select tables.

The chunker adds separately labelled evidence blocks immediately after the
owning source table. Every block repeats the table hash, source row, full row
path and field headers, nearby bounded source context, and neutral cell-state
semantics. Each association explicitly includes its column path and coordinate.
`blank` means **no marker shown**, not false or no relationship. `marked`
retains the literal source symbol, including check marks, without inferring an
affirmative meaning. Source-linked notes (including the existing bounded scope
association) travel with every applicable row/header association. Each component
of a grouped reference such as `(a,b)` requires its own definition. References
in repeated captions, preceding prose, and the normal section/document prefix
also require source-bound definitions; context-only references not owned by the
existing table-note association are conservatively excluded from expansion.
Unresolved note references or insufficient space suppress that table's entire expansion,
with a warning, rather than emitting an incomplete qualifier or partial matrix.
Unrelated notes are not globally appended.

Derived evidence retains the complete intervening source context, including
long captions and full-width source titles, rather than the source splitter's
optional short-caption subset. If that context cannot fit with an association
and its notes, expansion is omitted. A preceding block containing independent
note definitions also prevents expansion rather than transferring those notes
to a different table. The original source text remains unchanged in all cases.

Evidence uses normal document URL, filing identity, page, section and chunk
ordinal attribution. Page is the connector's source segment ordinal, not an
inferred printed page. New chunks use existing deterministic IDs and complete
serialized-request size validation; additions can shift subsequent subchunk
IDs/ordinals. Neither the old item count nor identical downstream IDs is promised.
No Graph schema change or new processing option is needed.

Before returning chunks for persistence, the chunker uses the same pure external
item builder and canonical serialization as Graph to check the complete request,
including JSON escaping, all metadata, ACL, and the configured/captured icon URL.
If any candidate request exceeds the ceiling, all marker additions for that
document are omitted and its original source-only chunking is restored. This
also prevents ordinal growth from making a previously fitting source request
oversized. Associations are not fragmented and the limit is never increased.
An independently oversized source-only request still uses the existing failure
path; this fallback is not a repair for pre-existing oversized source content.

## Eligibility and deliberate exclusions

Accepted tables are rectangular source grids with one to four consistently
populated row-label fields entirely on one side of two to 32 marker columns.
Leading headers may be explicit or already recognized by the parser; every
marker column needs a unique, nonempty ordered header path. Each column in the
marker region must have a dedicated path: a parent-only path that prefixes a
sibling leaf path is ambiguous and excludes the table, rather than creating a
phantom aggregate column from an empty leaf gutter. Labelled all-blank leaves
remain explicit. All cells in the marker region must be blank or the same glyph:
bullet, filled/open circle,
filled/open square, check mark (two variants), or checked box.
These glyphs are only visible marks, not semantic classifications.

Only wholly empty source columns are discarded from the sidecar; a labelled
all-blank column and an all-blank data row remain explicit. Reordered axes,
labels on the right, empty spacer columns, multi-level column headers, and
vertical hierarchical row labels do not depend on a particular domain.

Excluded: mixed marker types, X/yes/no text, numbers (including zero), dashes,
asterisks and footnote-only cells, missing/duplicate headers or row paths,
mixed prose/value columns, ragged/overlapping/malformed spans, spanned marker
or blank cells, horizontal body-label spans, group-only body rows, nested and
presentation tables, and unresolved images. OCR-resolved text may qualify through
the ordinary parser; v10 adds no OCR engine. Escaped pipes, literal HTML, or
unresolved image placeholders in labels are deliberately excluded rather than
reparsed from Markdown. Identical repeated source tables are not expanded
because content-hash-only ownership cannot distinguish their local notes.
Exclusion never removes the original table.

Per table: at most 68 populated source rows, 128 physical columns, 256 data
associations, and 64 KiB of added UTF-8 evidence. Per document: at most 32 eligible
tables and 2,048 associations (therefore at most 2 MiB of added evidence).
Character and UTF-8 chunk budgets apply including context and full notes.
An association is never split; a table that cannot fit complete associations
is left source-only. These are conservative support limits, not arbitrary-table
coverage guarantees.

## Generations and validation

Processing **10** changes completed-document cache fingerprints. Captured old
options are not rewritten, and ordinary resume replays exact prepared payloads
without parsing. Explicit reprocessing is required to rebuild incompatible
in-flight generations. SQLite format **4** and maintenance formats **1/2/3**
remain unchanged. Historical plan bytes/digests and inspection/source-free
rollback remain supported; forward runtime/provenance drift fails closed and
requires the original runtime. New maintenance provenance and optional
diagnostic hashes include `marker_tables.py`. The frozen v8 sample uploader
remains pinned to v8 and is not repurposed by this change.

Generic regressions cover independent raw-grid mappings, reorder/rename
metamorphisms, span/blank/header ambiguities, semantic exclusions, repeated
tables, qualifiers, size bounds, serialization, and attribution. Private
exact-source before/after receipts measure unchanged parsed/source rows
separately from added derived text and payload/ID changes. Existing source
oracles are not edited to accept new answers. Offline evidence availability
does not establish live indexing, retrieval or agent accuracy.

No code upgrade authorizes uploads, connection creation, or replacement of an
existing pilot. A later isolated live comparison requires separate approval.
