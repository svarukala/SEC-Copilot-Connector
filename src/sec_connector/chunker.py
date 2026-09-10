"""Document chunking strategies for SEC filings."""

import re
from typing import Optional

from .config import GRAPH_MAX_ITEM_BYTES, ChunkingConfig
from .models import ContentChunk, ParsedDocument
from .utils import get_logger

logger = get_logger("chunker")

PAGE_MARKER = "---PAGE---"
MAX_CHUNK_BYTES = GRAPH_MAX_ITEM_BYTES


def estimate_size_bytes(text: str) -> int:
    """Estimate the byte size of text in UTF-8."""
    return len(text.encode("utf-8"))


def split_by_pages(content: str) -> list[str]:
    """Split content by page markers.

    Args:
        content: Markdown content with ---PAGE--- markers

    Returns:
        List of page contents
    """
    pages = re.split(r"\n*---PAGE---\n*", content)
    return [p.strip() for p in pages if p.strip()]


def split_by_sections(content: str) -> list[str]:
    """Split content by markdown section headers.

    Args:
        content: Markdown content

    Returns:
        List of section contents
    """
    section_pattern = r"(^#{1,3}\s+.+$)"
    parts = re.split(section_pattern, content, flags=re.MULTILINE)

    sections = []
    current = ""

    for part in parts:
        if re.match(r"^#{1,3}\s+", part):
            if current.strip():
                sections.append(current.strip())
            current = part
        else:
            current += part

    if current.strip():
        sections.append(current.strip())

    return sections


def split_by_size(
    content: str,
    target_size: int,
    max_size: int,
    overlap: int = 200,
) -> list[str]:
    """Split content by character size with overlap.

    Args:
        content: Text content
        target_size: Target chunk size in characters
        max_size: Maximum chunk size in characters
        overlap: Overlap between chunks in characters

    Returns:
        List of chunks
    """
    if not 0 < target_size <= max_size or not 0 <= overlap < target_size:
        raise ValueError("Require 0 < target_size <= max_size and 0 <= overlap < target_size")
    return _split_content(content, target_size, max_size, overlap, MAX_CHUNK_BYTES)


def _split_prose(content: str, target_size: int, max_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while len(content) - start > max_size:
        end = start + target_size
        boundary = content.rfind("\n\n", start + target_size // 2, end)
        if boundary < 0:
            boundary = content.rfind(" ", start + target_size // 2, end)
        if boundary >= 0:
            end = boundary + 1
        chunks.append(content[start:end])
        start = max(start + 1, end - overlap)
    chunks.append(content[start:])
    return chunks


def enforce_size_limit(content: str, max_bytes: int = MAX_CHUNK_BYTES) -> list[str]:
    """Ensure content doesn't exceed byte size limit.

    Args:
        content: Text content
        max_bytes: Maximum size in bytes

    Returns:
        List of chunks within size limit
    """
    if max_bytes < 4:
        raise ValueError("max_bytes must accommodate a four-byte UTF-8 character")
    encoded = content.encode("utf-8")
    chunks = []
    offset = 0
    while offset < len(encoded):
        # Ignore only an incomplete code point at this boundary, then consume
        # its full bytes on the next iteration.
        piece = encoded[offset:offset + max_bytes].decode("utf-8", errors="ignore")
        chunks.append(piece)
        offset += len(piece.encode("utf-8"))
    return chunks or [""]


def _fits(text: str, max_size: int, max_bytes: int) -> bool:
    return len(text) <= max_size and estimate_size_bytes(text) <= max_bytes


def _bounded_fragments(text: str, max_size: int, max_bytes: int) -> list[str]:
    return [
        piece
        for offset in range(0, len(text), max_size)
        for piece in enforce_size_limit(text[offset:offset + max_size], max_bytes)
    ]


def _split_table(
    table: str, context: str, target_size: int, max_size: int, max_bytes: int
) -> list[str]:
    rows = table.splitlines()
    header_count = 2 if len(rows) > 1 and re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+\s*", rows[1]) else 0
    header = "\n".join(rows[:header_count])
    data = rows[header_count:]
    prefix = "\n\n".join(part for part in (context, header) if part)
    if prefix:
        prefix += "\n"
    # A huge header/context is content too; emit it bounded rather than drop it
    # or reserve so much space that no code point of a data row can progress.
    if not _fits(prefix + "😀", max_size, max_bytes):
        logger.warning("Table header/context exceeds chunk budget; using bounded fragments")
        return _bounded_fragments(context + ("\n\n" if context else "") + table, max_size, max_bytes)
    if not data:
        return [prefix.rstrip("\n")] if prefix else []

    chunks = []
    current = prefix
    has_rows = False
    for row in data:
        addition = row + "\n"
        if has_rows and (
            not _fits(current + addition, max_size, max_bytes)
            or len(current + addition) > target_size
        ):
            chunks.append(current.rstrip("\n"))
            current, has_rows = prefix, False
        if not _fits(prefix + addition, max_size, max_bytes):
            if has_rows:
                chunks.append(current.rstrip("\n"))
                current, has_rows = prefix, False
            logger.warning("Indivisible table row exceeds chunk budget; preserving ordered row fragments")
            warning = "[Table row fragment; concatenate in chunk order]\n"
            fragment_prefix = prefix + warning
            if not _fits(fragment_prefix + "😀", max_size, max_bytes):
                fragment_prefix = prefix
            for piece in _bounded_fragments(
                row, max_size - len(fragment_prefix),
                max_bytes - estimate_size_bytes(fragment_prefix),
            ):
                chunks.append(fragment_prefix + piece)
        else:
            current += addition
            has_rows = True
    if has_rows:
        chunks.append(current.rstrip("\n"))
    return chunks


def _split_content(
    content: str, target_size: int, max_size: int, overlap: int, max_bytes: int
) -> list[str]:
    """Keep table rows atomic; apply overlap exclusively to prose blocks."""
    blocks = re.split(r"(^[ \t]*\|[^\n]*(?:\n[ \t]*\|[^\n]*)*)", content, flags=re.MULTILINE)
    if len(blocks) == 1:
        return [
            part for piece in _split_prose(content, target_size, max_size, overlap)
            for part in enforce_size_limit(piece, max_bytes)
        ]
    chunks = []
    for index, block in enumerate(blocks):
        if not block.strip():
            continue
        if index % 2:
            # Financial captions and units commonly occupy the immediately
            # preceding short paragraphs. Keep them with every table segment.
            paragraphs = re.split(r"\n\s*\n", blocks[index - 1].strip())
            nearby = []
            for paragraph in reversed(paragraphs):
                if not paragraph or len(paragraph) > 240:
                    break
                nearby.insert(0, paragraph)
                if len(nearby) == 3:
                    break
            following = blocks[index + 1].strip() if index + 1 < len(blocks) else ""
            notes = []
            for paragraph in re.split(r"\n\s*\n", following):
                if len(paragraph) <= 240 and re.match(r"^(?:\(\d+\)|\[\d+\]|\*|Notes?\b)", paragraph):
                    notes.append(paragraph)
                else:
                    break
            context = "\n\n".join(nearby + notes)
            # Do not let optional neighboring prose make otherwise valid rows
            # indivisible. It remains present in its own prose block.
            if not _fits(context, max_size // 3, max(4, max_bytes // 3)):
                context = ""
            chunks.extend(_split_table(block.strip(), context, target_size, max_size, max_bytes))
        else:
            chunks.extend(
                part for piece in _split_prose(block, target_size, max_size, overlap)
                for part in enforce_size_limit(piece, max_bytes)
            )
    return chunks


def chunk_document(
    parsed_doc: ParsedDocument,
    config: ChunkingConfig,
) -> list[ContentChunk]:
    """Chunk a parsed document into uploadable segments.

    Args:
        parsed_doc: Parsed document
        config: Chunking configuration

    Returns:
        List of ContentChunk objects
    """
    content = parsed_doc.content
    filing = parsed_doc.filing
    document = parsed_doc.document

    chunks = []

    pages = split_by_pages(content)
    section_title = None
    for page_num, page_content in enumerate(pages, start=1):
        sub_chunks = []
        for section in split_by_sections(page_content):
            heading = re.match(r"^#{1,3}\s+(.+)", section)
            if heading:
                section_title = re.sub(r"[*_]", "", heading.group(1)).strip()
            report_period = filing.report_period_end
            context_parts = [filing.company_name, filing.form]
            if report_period:
                context_parts.append(f"Report period: {report_period:%Y-%m-%d}")
            if section_title:
                context_parts.append(f"Section: {section_title}")
            compact_parts = []
            for part in context_parts:
                candidate = " | ".join(compact_parts + [part]) + "\n\n"
                if _fits(candidate, config.max_size // 4, config.max_item_bytes // 4):
                    compact_parts.append(part)
            context = " | ".join(compact_parts) + "\n\n" if compact_parts else ""
            char_budget = config.max_size - len(context)
            byte_budget = config.max_item_bytes - estimate_size_bytes(context)
            target = min(config.target_size, char_budget)
            overlap = min(config.overlap, target - 1)
            sub_chunks.extend(
                (context + piece, section_title)
                for piece in _split_content(section, target, char_budget, overlap, byte_budget)
                if piece
            )

        for sub_idx, (sub_content, chunk_section) in enumerate(sub_chunks):
            actual_page = page_num if len(sub_chunks) == 1 else f"{page_num}.{sub_idx + 1}"

            chunk_id = f"{filing.cik}-{filing.accession_no_dashes}-{document.sequence}-p{actual_page}"

            title = f"{filing.company_name} - {filing.form} - {filing.filing_date:%Y-%m-%d}"
            if len(pages) > 1:
                title += f" (Page {actual_page})"

            chunk = ContentChunk(
                chunk_id=chunk_id,
                filing=filing,
                document=document,
                page_number=page_num,
                subchunk_number=sub_idx + 1 if len(sub_chunks) > 1 else None,
                chunk_ordinal=len(chunks) + 1,
                section_title=chunk_section,
                content=sub_content,
                title=title,
            )
            chunks.append(chunk)

    logger.info(
        f"Chunked {document.filename} into {len(chunks)} chunks "
        f"(avg {sum(len(c.content) for c in chunks) // max(len(chunks), 1)} chars)"
    )

    return chunks


def chunk_with_limit(
    parsed_doc: ParsedDocument,
    config: ChunkingConfig,
    max_chunks: Optional[int] = None,
) -> list[ContentChunk]:
    """Chunk a document with optional limit on number of chunks.

    Args:
        parsed_doc: Parsed document
        config: Chunking configuration
        max_chunks: Maximum number of chunks to return

    Returns:
        List of ContentChunk objects (possibly limited)
    """
    chunks = chunk_document(parsed_doc, config)

    if max_chunks and len(chunks) > max_chunks:
        logger.info(f"Limiting chunks from {len(chunks)} to {max_chunks}")
        chunks = chunks[:max_chunks]

    return chunks
