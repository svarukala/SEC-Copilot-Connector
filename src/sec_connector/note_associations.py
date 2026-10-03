"""Bounded, source-local table note ownership before page/section splitting."""

from collections import Counter
import hashlib
import re

from .utils import get_logger

logger = get_logger("notes")

TABLE = re.compile(r"^[ \t]*\|[^\n]*(?:\n[ \t]*\|[^\n]*)*", re.M)
SYMBOL = r"(?:\\?\*){1,3}|[\u2020\u2021]"
MARKER = rf"\([a-z0-9]+\)|\[[a-z0-9]+\]|\[(?:{SYMBOL})\]|{SYMBOL}"
NOTE_START = re.compile(rf"^({MARKER})(?:(?<=[)\]])\s*|\s+)(?=\S)", re.I)
MARKER_ONLY = re.compile(rf"^(?:{MARKER})$", re.I)


def cells(row: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def canonical_marker(marker: str) -> str:
    return marker.replace("\\", "")


def linked_marker(marker: str, rows: str) -> bool:
    marker = canonical_marker(marker)
    for row in rows.splitlines():
        for cell in cells(row):
            grouped = marker.startswith("(") and any(
                marker[1:-1] in re.split(r",\s*", group)
                for group in re.findall(r"\(([a-z0-9]{1,2}(?:,\s*[a-z0-9]{1,2})+)\)", cell, re.I)
            )
            if re.fullmatch(SYMBOL, marker):
                # Escaped Markdown symbols are literal; bare emphasis is not.
                literal = re.sub(rf"\[(?:{SYMBOL})\]", "", cell)
                literal = re.sub(r"\d\s+(?:\\\*)+\s+\d", "", literal)
                symbols = re.findall(r"(?:\\\*)+|[\u2020\u2021]+", literal)
                bare = re.findall(r"(?<![\\*\w])\*{1,3}(?=\s*$)", literal)
                if marker not in [canonical_marker(s) for s in symbols + bare]:
                    continue
            elif marker not in canonical_marker(cell) and not grouped:
                continue
            if (re.fullmatch(r"\(\d+\)", marker) and not re.search(r"[A-Za-z]", cell)
                    and not re.fullmatch(r"(?:19|20)\d{2}", cell.replace(marker, "").strip())):
                continue
            return True
    return False


def unique_notes(notes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    counts = Counter(marker for marker, _ in notes)
    ambiguous = {marker for marker, count in counts.items() if count > 1}
    if ambiguous:
        logger.warning("Duplicate table note markers %s; not repeating ambiguous definitions",
                       ", ".join(sorted(ambiguous)))
    return [(marker, note) for marker, note in notes if marker not in ambiguous]


def _note_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(
        rf"\n\s*\n|\n(?=[ \t]*(?:{MARKER})(?:(?<=[)\]])\s*|\s+)\S)", text.strip(),
        flags=re.I,
    ) if part.strip()]


def adjacent_notes(following: str, table: str) -> list[tuple[str, str]]:
    notes = []
    for paragraph in _note_paragraphs(following):
        match = NOTE_START.match(paragraph)
        if not match:
            break
        marker = canonical_marker(match[1])
        if linked_marker(marker, table):
            notes.append((marker, paragraph))
    return unique_notes(notes)


def _definitions(block: str) -> list[tuple[str, str]]:
    if not block.startswith("|"):
        definitions = []
        for paragraph in _note_paragraphs(block):
            match = NOTE_START.match(paragraph)
            if not match:
                return []
            definitions.append((canonical_marker(match[1]), paragraph))
        return definitions
    rows = [cells(row) for row in block.splitlines()]
    if len(rows) < 2 or (len(rows) > 2 and any(rows[0])):
        return []
    definitions = []
    for row in rows[:1] if len(rows) == 2 else rows[2:]:
        values = [value for value in row if value]
        if not values:
            continue
        if (len(values) != 2 or not MARKER_ONLY.fullmatch(values[0])
                or not re.search(r"[A-Za-z]", values[1])):
            return []
        definitions.append((canonical_marker(values[0]), " ".join(values)))
    return definitions


def _footer(block: str) -> tuple[str, str] | None:
    rows = block.splitlines()
    if len(rows) != 3 or any(cells(rows[0])):
        return None
    values = [value for value in cells(rows[2]) if value]
    if len(values) != 2:
        return None
    numbers = [v for v in values if re.fullmatch(r"\d{1,4}", v)]
    labels = [v for v in values if re.search(r"[A-Za-z]", v)]
    return (labels[0], numbers[0]) if len(numbers) == len(labels) == 1 else None


def _scope(block: str, table: str, marker: str) -> str:
    """Repeat only a short adjacent statement naming a unique marked row label."""
    if block.startswith("|"):
        rows = block.splitlines()
        if len(rows) != 3 or any(cells(rows[0])):
            return ""
        values = [v for v in cells(rows[2]) if re.search(r"[A-Za-z]", v)]
        if len(values) != 1:
            return ""
        block = values[0]
    if not block or len(block) > 400 or block.startswith("#") or NOTE_START.match(block):
        return ""
    labels = []
    for row in table.splitlines()[2:]:
        for cell in cells(row):
            if linked_marker(marker, cell):
                label = re.sub(rf"(?:{MARKER})", "", cell).strip()
                if re.fullmatch(r"[A-Za-z]+(?:[ -][A-Za-z]+){1,7}", label):
                    labels.append(label)
    if len(labels) == 1 and re.search(r"\b" + re.escape(labels[0]) + r"\b", block, re.I):
        return block
    return ""


def collect_table_notes(content: str) -> dict[str, list[tuple[str, str]]]:
    """Bind definitions to unique source tables; never search across another data table.

    A single page boundary may carry a note sequence through repeated page
    furniture. Independent headings/tables end ownership. Unmarked intervening
    narrative is bounded and is never copied as a qualifier.
    """
    blocks = []
    offset = 0
    for match in TABLE.finditer(content):
        blocks.extend(p.strip() for p in re.split(
            r"\n\s*\n|(?=---PAGE---)|(?<=---PAGE---)", content[offset:match.start()]
        ) if p.strip())
        blocks.append(match[0].strip())
        offset = match.end()
    blocks.extend(p.strip() for p in re.split(
        r"\n\s*\n|(?=---PAGE---)|(?<=---PAGE---)", content[offset:]
    ) if p.strip())
    table_counts = Counter(block for block in blocks if block.startswith("|"))
    footer_pages: dict[str, set[str]] = {}
    for index, block in enumerate(blocks[:-1]):
        footer = _footer(block)
        if footer and blocks[index + 1] == "---PAGE---":
            footer_pages.setdefault(footer[0], set()).add(footer[1])
    page_headers: set[str] = set()
    prefix = True
    result = {}
    for index, table in enumerate(blocks):
        if table == "---PAGE---":
            page_headers, prefix = set(), True
            continue
        if prefix and table.startswith("#"):
            page_headers.add(table)
        elif table != "---":
            prefix = False
        if not table.startswith("|") or _definitions(table):
            continue
        key = hashlib.sha256(table.encode("utf-8")).hexdigest()
        result[key] = []
        if table_counts[table] != 1:
            continue
        notes = []
        pages = narrative = scanned = 0
        in_page_prefix = False
        for following_index in range(index + 1, min(index + 33, len(blocks))):
            following = blocks[following_index]
            scanned += len(following)
            if scanned > 16000:
                logger.warning("Table note search exceeds bounded source window; definitions not associated")
                notes.clear()
                break
            definitions = _definitions(following)
            if definitions:
                notes.extend(definitions)
                in_page_prefix = False
                continue
            if following == "---PAGE---":
                pages += 1
                if pages > 1:
                    break
                in_page_prefix = True
                continue
            if following == "---":
                continue
            if following.startswith("#"):
                if in_page_prefix and following in page_headers:
                    continue
                break
            footer = _footer(following)
            if (footer and len(footer_pages.get(footer[0], set())) > 1
                    and following_index + 1 < len(blocks)
                    and blocks[following_index + 1] == "---PAGE---"):
                continue
            if following.startswith("|"):
                break
            narrative += len(following)
            in_page_prefix = False
            if narrative > 800:
                break
        else:
            if index + 33 < len(blocks):
                logger.warning("Table note search exceeds bounded block window; definitions not associated")
                notes.clear()
        for marker, note in unique_notes(notes):
            if linked_marker(marker, table):
                scope = _scope(blocks[index - 1], table, marker) if index else ""
                result[key].append((marker, scope + "\n\n" + note if scope else note))
    return result
