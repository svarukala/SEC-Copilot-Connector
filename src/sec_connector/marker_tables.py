"""Conservative source-grid marker evidence; no membership/boolean inference."""

from collections import Counter
import hashlib
import json
import re

from .models import MarkerCell, MarkerRow
from .note_associations import MARKER, NOTE_START, TABLE, canonical_marker, linked_marker
from .utils import get_logger

logger = get_logger("marker_tables")

# Glyph identity is retained. Even a check mark means only "marker shown".
GLYPHS = frozenset("\u2022\u25cf\u25cb\u25a0\u25a1\u2713\u2714\u2611")
MAX_CELLS = 256
MAX_TABLE_BYTES = 65536
MAX_DOCUMENT_CELLS = 2048
MAX_DOCUMENT_TABLES = 32


def _label(value: str, *, header: bool = False) -> bool:
    return (
        0 < len(value) <= 240
        and not re.search(r"[\\|<>`\n]", value)
        and not re.fullmatch(r"\[.*\]", value)
        and (any(c.isalpha() for c in value) or header and value.isdecimal())
    )


def capture(matrix, origins, header_count, source_rows) -> list[MarkerRow]:
    """Accept rectangular single-symbol matrices with uniquely resolved axes.

    Only wholly empty columns are spacers. Body spans are allowed exclusively
    for vertical row labels; markers and blanks must each be independent cells.
    """
    if not 1 <= header_count < len(matrix) or len(matrix) > 68:
        return []
    width = len(matrix[0])
    if width > 128 or any(len(row) != width for row in matrix):
        return []
    if any(origin is None for row in origins for origin in row):
        return []
    active = [c for c in range(width) if any(row[c] for row in matrix)]
    body = matrix[header_count:]
    data = [c for c in active if all(row[c] in GLYPHS or not row[c] for row in body)]
    labels = [c for c in active if c not in data]
    if not 2 <= len(data) <= 32 or not 1 <= len(labels) <= 4:
        return []
    if not (max(labels) < min(data) or max(data) < min(labels)):
        return []
    if len(body) * len(data) > MAX_CELLS:
        return []
    symbols = {row[c] for row in body for c in data if row[c]}
    if len(symbols) != 1 or not all(_label(row[c]) for row in body for c in labels):
        return []
    paths = {}
    for c in active:
        path, seen = [], set()
        for r in range(header_count):
            value, origin = matrix[r][c], origins[r][c]
            if value and origin not in seen:
                if not _label(value, header=True):
                    return []
                path.append(value)
                seen.add(origin)
        paths[c] = path
    identities = [tuple(v.casefold().strip("*_ ") for v in paths[c]) for c in data]
    if any(not identity for identity in identities) or len(set(identities)) != len(data):
        return []
    if any(len(parent) < len(leaf) and leaf[:len(parent)] == parent
           for parent in identities for leaf in identities):
        return []
    # A shared header must not straddle the row-label and marker axes.
    for r in range(header_count):
        if {origins[r][c] for c in labels if matrix[r][c]} & {
            origins[r][c] for c in data if matrix[r][c]
        }:
            return []
    row_identities = [tuple(row[c].casefold().strip("*_ ") for c in labels) for row in body]
    if len(set(row_identities)) != len(body):
        return []
    counts = Counter(origin for row in origins for origin in row)
    result = []
    for r in range(header_count, len(matrix)):
        for c in data:
            if counts[origins[r][c]] != 1 or origins[r][c] != (source_rows[r], c):
                return []
        for c in labels:
            if (origins[r][c][0] < source_rows[header_count]
                    or any(origins[r][c] == origins[r][other]
                           for other in range(width) if other != c)):
                return []
        result.append(MarkerRow(
            row=source_rows[r] + 1,
            labels=[matrix[r][c] for c in labels],
            label_headers=[paths[c] for c in labels],
            cells=[MarkerCell(column=origins[r][c][1] + 1, header=paths[c],
                              marker=matrix[r][c]) for c in data],
        ))
    return result


def bind_unique(content: str, candidates: dict[str, list[MarkerRow]]) -> None:
    counts = Counter(hashlib.sha256(m[0].strip().encode("utf-8")).hexdigest()
                     for m in TABLE.finditer(content))
    total = accepted = 0
    for key, rows in list(candidates.items()):
        size = sum(len(row.cells) for row in rows)
        if (not rows or counts[key] != 1 or accepted >= MAX_DOCUMENT_TABLES
                or total + size > MAX_DOCUMENT_CELLS):
            del candidates[key]
            continue
        total += size
        accepted += 1


def render(
    key: str, rows: list[MarkerRow], context: str, notes: list[tuple[str, str]],
    max_size: int, max_bytes: int, outer_context: str = "",
) -> list[str]:
    """All-or-none bounded table expansion; never emit a detached qualifier."""
    if any(NOTE_START.match(p.strip()) for p in re.split(r"\n\s*\n", context)):
        logger.warning("Marker evidence omitted: preceding context contains independently owned notes")
        return []

    def fits(text):
        return len(text) <= max_size and len(text.encode("utf-8")) <= max_bytes

    def quoted(value):
        return json.dumps(value, ensure_ascii=False)

    chunks = []
    for row in rows:
        prefix = "\n\n".join(p for p in (
            context,
            f"[Derived marker-table evidence; source table SHA256 {key}; source row {row.row}]",
            "Row path: " + quoted(row.labels),
            "Row field headers: " + quoted(row.label_headers),
            "Cell states describe only visible source marks. Blank means no marker shown, "
            "not false or no relationship; marked is not an inferred affirmative.",
        ) if p)
        lines, selected = [], []

        def package(extra_lines, extra_notes):
            return prefix + "\n" + "\n".join(extra_lines) + "".join(
                "\n\n" + note for _, note in extra_notes
            )

        for cell in row.cells:
            identity = " | ".join([context, outer_context] + row.labels
                                  + [v for path in row.label_headers for v in path] + cell.header)
            refs = {canonical_marker(m[0]) for m in re.finditer(MARKER, identity, re.I)
                    if linked_marker(m[0], identity)}
            for group in re.findall(r"\(\s*([a-z0-9]+(?:\s*,\s*[a-z0-9]+)+)\s*\)", identity, re.I):
                parts = re.split(r"\s*,\s*", group)
                if any(not part.isdecimal() for part in parts) or all(len(part) <= 2 for part in parts):
                    refs.update(f"({part})" for part in parts)
            applicable = [(m, n) for m, n in notes if linked_marker(m, identity)]
            if not refs.issubset({m for m, _ in applicable}):
                logger.warning("Marker evidence omitted: unresolved source note reference")
                return []
            line = (f"Column {cell.column}; header path: {quoted(cell.header)}; "
                    + (f"marked; source marker: {quoted(cell.marker)}"
                       if cell.marker else 'blank; source cell: "" (no marker shown)'))
            combined = list(dict.fromkeys(selected + applicable))
            if lines and not fits(package(lines + [line], combined)):
                chunks.append(package(lines, selected))
                lines, selected = [], []
                combined = applicable
            if not fits(package([line], applicable)):
                logger.warning("Marker evidence omitted: association/context/notes exceed chunk budget")
                return []
            lines.append(line)
            selected = combined
        chunks.append(package(lines, selected))
    if sum(len(c.encode("utf-8")) for c in chunks) > MAX_TABLE_BYTES:
        logger.warning("Marker evidence omitted: bounded table expansion exceeded")
        return []
    return chunks
