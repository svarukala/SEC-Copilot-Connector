"""Document parser for SEC EDGAR filings - SGML/HTML to Markdown conversion."""

import re
import hashlib
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter
from soupsieve import SelectorSyntaxError

from .models import DocumentInfo, FilingMetadata, ParsedDocument
from .utils import get_logger

logger = get_logger("parser")


def _is_bold_block(tag) -> bool:
    """Require bold styling for every visible text run, not just a leading label."""
    for text in tag.find_all(string=True):
        if not text.strip():
            continue
        parent = text.parent
        bold = False
        while parent is not None:
            weight = re.search(
                r"(?:^|;)\s*font-weight\s*:\s*(bold|normal|[1-9]00)\b",
                parent.get("style", ""), re.IGNORECASE,
            )
            if weight:
                bold = weight.group(1).lower() in {"bold", "600", "700", "800", "900"}
                break
            if parent.name in {"b", "strong"}:
                bold = True
                break
            if parent is tag:
                break
            parent = parent.parent
        if not bold:
            return False
    return True


def _bullet_layout_rows(direct_cells) -> bool:
    """Only marker + optional empty spacers + one prose cell is a list layout."""
    found = False
    for cells in direct_cells:
        if any(cell.name == "th" or cell.has_attr("colspan") or cell.has_attr("rowspan")
               or cell.find("table") for cell in cells):
            return False
        values = [cell.get_text(" ", strip=True) for cell in cells]
        populated = [value for value in values if value]
        if not populated:
            continue
        if (len(populated) != 2 or populated[0] not in {"\u2022", "\u220e", "\u25a0", "\u25cf"}
                or not re.search(r"[A-Za-z]", populated[1])):
            return False
        found = True
    return found


def _is_styled_heading(tag, label: str) -> bool:
    """Do not promote styled sentence fragments, list introductions, or dates."""
    if re.search(r"[.,:!?;]$", label) or not _is_bold_block(tag):
        return False
    if re.search(r":\s*[$\u20ac\u00a3]?\s*\d[\d,.]*\s*$", label):
        return False
    date_label = re.sub(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+",
        "", label, flags=re.IGNORECASE,
    )
    date_label = re.sub(r"^for\s+(?:the\s+)?", "", date_label, flags=re.IGNORECASE)
    date_label = re.sub(r"\bquarterly\s+period\b", "quarter", date_label, flags=re.IGNORECASE)
    if _is_period_heading(date_label):
        return False
    following = tag.find_next(["p", "div", "table", "h1", "h2", "h3"])
    if following is not None and following.name in {"p", "div"}:
        continuation = following.get_text(" ", strip=True)
        if (not following.find(["p", "div", "table"]) and continuation
                and continuation[0].islower() and _is_bold_block(following)):
            return False
    return True


def _is_period_heading(value: str) -> bool:
    """Recognize short date labels, not narrative sentences that mention years."""
    if len(value) > 100 or not re.search(r"\b(?:19|20)\d{2}\b", value):
        return False
    remainder = re.sub(r"\b(?:19|20)\d{2}\b", "", value.lower())
    remainder = re.sub(
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
        r"|fiscal|years?|quarters?|months?|weeks?|ended|ending|as|at|of|and|the|three|six|nine|twelve|q[1-4])\b",
        "", remainder,
    )
    remainder = re.sub(r"\b(?:[0-2]?\d|3[01])\b", "", remainder)
    return not re.search(r"\w", remainder)


def _source_header_end(rows) -> int:
    """Infer only a leading financial column band, before any value/stub row.

    Span geometry, alignment and a unit caption must agree. Bold text by itself
    is not evidence: subtotal/value rows terminate the band even when styled.
    """
    end = 0
    units = False
    grouped = False
    explicit_end = 0
    for index, cells in enumerate(rows):
        visible = [(cell, " ".join(cell.get_text(" ", strip=True).split()))
                   for cell in cells if cell.get_text(strip=True)]
        if not visible:
            continue
        explicit = all(
            cell.name == "th" and cell.get("scope") != "row"
            or cell.find_parent("thead") is not None
            for cell, _ in visible
        )
        if any(cell.get("scope") == "row" or cell.find(
            lambda tag: tag.name and tag.name.lower().endswith(":nonfraction")
        ) for cell, _ in visible):
            break
        if explicit:
            end = explicit_end = index + 1
            continue
        unit_stub = re.search(r"\bin (?:millions|billions|thousands)\b", visible[0][1], re.I)
        numeric_labels = [(cell, text) for cell, text in visible if not re.search(r"[A-Za-z]", text)]
        if numeric_labels and not (
            grouped and unit_stub and len(numeric_labels) >= 2
            and all(re.fullmatch(r"(?:19|20)\d{2}", text) and re.search(
                r"(?:^|;)\s*text-align\s*:\s*center\b", cell.get("style", ""), re.I
            ) for cell, text in numeric_labels)
        ):
            break
        if any(not re.fullmatch(r"\d+", str(cell.get("colspan", "1")))
               or int(cell.get("colspan", 1)) < 2 for cell, _ in visible):
            break
        styles = [cell.get("style", "") for cell, _ in visible]
        if not all(re.search(r"(?:^|;)\s*vertical-align\s*:\s*bottom\b", style, re.I)
                   for style in styles):
            break
        aligned = any(re.search(r"(?:^|;)\s*text-align\s*:\s*center\b", style, re.I)
                      for style in styles)
        if len(visible) == 1 and end and (units or not aligned):
            break
        if not (aligned or (grouped and unit_stub)):
            spans = [int(cell.get("colspan", 1)) for cell, _ in visible]
            # A leading dominant caption may have a separate table-number cell.
            if end or max(spans) < sum(spans) * 0.75:
                break
        units = units or bool(unit_stub)
        grouped = grouped or aligned
        end = index + 1
    return end if units and grouped else explicit_end


def _parse_dimension_inches(el) -> tuple[Optional[float], Optional[float]]:
    """Extract width and height from an element's style or attributes, in inches.

    Handles both inline CSS (style="width:0.14in;height:0.90in") and
    HTML attributes (width="10" height="65"), converting px to inches
    at 96 dpi.
    """
    style = el.get("style", "")

    # Try inline CSS first (inches)
    w_match = re.search(r"width:\s*([\d.]+)in", style)
    h_match = re.search(r"height:\s*([\d.]+)in", style)
    if w_match and h_match:
        return float(w_match.group(1)), float(h_match.group(1))

    # Try inline CSS (px) — convert at 96 dpi
    w_match = re.search(r"width:\s*([\d.]+)px", style)
    h_match = re.search(r"height:\s*([\d.]+)px", style)
    if w_match and h_match:
        return float(w_match.group(1)) / 96, float(h_match.group(1)) / 96

    # Try HTML attributes (assumed px at 96 dpi)
    w_attr = el.get("width")
    h_attr = el.get("height")
    if w_attr and h_attr:
        try:
            return float(w_attr) / 96, float(h_attr) / 96
        except ValueError:
            pass

    return None, None


def _is_rotated_text_image(el) -> bool:
    """Detect images that are likely rotated text (narrow width, taller height).

    SEC filings often render vertically-oriented table headers as small images
    with width << height. These typically have width ~0.13-0.15in and height
    varying by name length.
    """
    w, h = _parse_dimension_inches(el)
    if w is not None and h is not None:
        return w < 0.3 and h > w * 2
    return False


class SECMarkdownConverter(MarkdownConverter):
    """Custom markdown converter for SEC filings."""

    def __init__(self, **options):
        self.table_header_rows = options.pop("table_header_rows", None)
        super().__init__(**options)

    def convert_table(self, el, text=None, *args, **kwargs):
        """Normalize direct cells into a grid without counting nested descendants."""
        rows = [row for row in el.find_all("tr") if row.find_parent("table") is el]
        if not rows:
            return text or ""

        direct_cells = [
            [cell for cell in row.find_all(["th", "td"])
             if cell.find_parent("tr") is row and cell.find_parent("table") is el]
            for row in rows
        ]
        source_header_end = _source_header_end(direct_cells)
        if not el.find(["caption", "img"]) and _bullet_layout_rows(direct_cells):
            items = []
            for cells in direct_cells:
                populated = [cell for cell in cells if cell.get_text(" ", strip=True)]
                if populated:
                    body = self.convert(populated[1].decode_contents()).strip()
                    items.append("- " + body.replace("\n", "\n  "))
            return "\n\n" + "\n".join(items) + "\n\n"
        if el.find("table") or el.get("role") == "presentation" or all(
            len(cells) <= 1 and not any(cell.get("colspan") for cell in cells)
            for cells in direct_cells
        ):
            # Layout wrappers must not turn their embedded financial tables into
            # escaped pipes, nor include the inner cells a second time.
            return "\n\n" + "\n\n".join(
                self.convert(cell.decode_contents()).strip()
                for cells in direct_cells for cell in cells
            ) + "\n\n"

        grid = {}
        origins = {}
        header_flags = []
        source_header_flags = []
        title_flags = []
        for row_index, cells in enumerate(direct_cells):
            source_header_flags.append(row_index < source_header_end)
            column = 0
            header_flags.append(bool(cells) and (
                all(cell.name == "th" and cell.get("scope") != "row" for cell in cells)
                or rows[row_index].find_parent("thead") is not None
            ))
            title_flags.append(len(cells) == 1 and cells[0].has_attr("colspan"))
            for cell in cells:
                while (row_index, column) in grid:
                    column += 1
                value = " ".join(self.convert(cell.decode_contents()).split())
                value = value.replace("|", "\\|")
                try:
                    # Bound malformed spans to avoid unbounded allocation.
                    rowspan = int(cell.get("rowspan", 1))
                    if rowspan == 0:
                        rowspan = len(rows) - row_index
                    rowspan = min(max(rowspan, 1), len(rows) - row_index)
                    colspan = min(max(int(cell.get("colspan", 1)), 1), 256)
                except (ValueError, TypeError):
                    rowspan = colspan = 1
                for down in range(rowspan):
                    for across in range(colspan):
                        grid.setdefault((row_index + down, column + across), value)
                        origins.setdefault((row_index + down, column + across), (row_index, column))
                column += colspan

        width = max((column for _, column in grid), default=0) + 1
        populated_rows = [
            row for row in range(len(rows))
            if any(grid.get((row, col), "") for col in range(width))
        ]
        # Collapse only columns covered by the same source cell in every row.
        # Equal-looking values in independent financial columns must stay separate.
        columns = [
            col for col in range(width)
            if col == 0 or any(
                origins.get((row, col)) != origins.get((row, col - 1))
                for row in populated_rows
            )
        ]
        matrix = [[grid.get((row, col), "") for col in columns] for row in range(len(rows))]
        origin_matrix = [[origins.get((row, col)) for col in columns] for row in range(len(rows))]
        width = len(columns)
        # SEC layout exports often interleave many completely empty spacer rows.
        populated = [index for index, values in enumerate(matrix) if any(values)]
        matrix = [matrix[index] for index in populated]
        origin_matrix = [origin_matrix[index] for index in populated]
        header_flags = [header_flags[index] for index in populated]
        source_header_flags = [source_header_flags[index] for index in populated]
        title_flags = [title_flags[index] for index in populated]
        if not matrix:
            return text or ""
        caption = el.find("caption", recursive=False)
        context = [self.convert(caption.decode_contents()).strip()] if caption else []
        # Full-width title/unit rows are context, not misleading column names.
        while matrix and title_flags[0] and len(set(matrix[0])) == 1 and matrix[0][0]:
            context.append(matrix.pop(0)[0])
            origin_matrix.pop(0)
            header_flags.pop(0)
            source_header_flags.pop(0)
            title_flags.pop(0)

        header_count = 0
        for values, explicit in zip(matrix, header_flags):
            nonempty = [re.sub(r"[*_]", "", value) for value in values if value]
            periods = any(_is_period_heading(value) for value in nonempty)
            numeric = any(re.fullmatch(r"[$(−\-]?\d[\d,.% )]*", value) for value in nonempty)
            short_labels = all(len(value) <= 120 for value in nonempty)
            heading_labels = short_labels and all(
                not re.search(r"\d", value) or _is_period_heading(value)
                for value in nonempty
            )
            first_labels = short_labels and not numeric and all(
                not re.search(r"\b(?:19|20)\d{2}\b", value) or _is_period_heading(value)
                for value in nonempty
            )
            if explicit or (heading_labels and periods) or (header_count == 0 and first_labels):
                header_count += 1
            else:
                break
        headers = []
        for column in range(width):
            labels = list(dict.fromkeys(row[column] for row in matrix[:header_count] if row[column]))
            headers.append(" / ".join(labels))
        md_rows = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        for values, source_cells in zip(matrix[header_count:], origin_matrix[header_count:]):
            rendered = []
            seen = {}
            for column, (value, source_cell) in enumerate(zip(values, source_cells), start=1):
                if value and source_cell in seen:
                    # Keep horizontal span relationships local to the intact row
                    # without copying long disclosures into every covered column.
                    rendered.append(f"[merged with column {seen[source_cell]}]")
                else:
                    rendered.append(value)
                    if value:
                        seen[source_cell] = column
            md_rows.append("| " + " | ".join(rendered) + " |")
        table_markdown = "\n".join(md_rows)
        source_count = next(
            (index for index, flag in enumerate(source_header_flags) if not flag),
            len(source_header_flags),
        )
        if self.table_header_rows is not None:
            key = hashlib.sha256(table_markdown.encode("utf-8")).hexdigest()
            count = 2 + max(0, source_count - header_count)
            # Identical Markdown from conflicting HTML structures cannot safely
            # borrow the more permissive source interpretation.
            self.table_header_rows[key] = min(self.table_header_rows.get(key, count), count)
        return "\n\n" + "\n\n".join(context + [table_markdown]) + "\n\n"

    def convert_td(self, el, text=None, *args, **kwargs):
        return text or ""

    convert_th = convert_td

    def convert_sup(self, el, text=None, *args, **kwargs):
        marker = (text or "").strip()
        if not marker:
            return ""
        return marker if marker.startswith(("(", "[")) else f"[{marker}]"

    def convert_img(self, el, text=None, *args, **kwargs):
        """Handle <img> tags in SEC filings.

        - Rotated text images (narrow width, tall): replace with [image: rotated text]
          marker so downstream processing can identify these gaps.
        - Generic alt="LOGO" images: strip entirely (decorative logos, icons, etc.)
        - Images with meaningful alt text: preserve as [alt text].
        """
        alt = (el.get("alt") or "").strip()

        if _is_rotated_text_image(el):
            # Mark as rotated text so it's clear something is missing
            return "[rotated text]"

        if alt.upper() == "LOGO" or not alt:
            # Decorative image — strip it
            return ""

        # Meaningful alt text — keep it
        return f"[{alt}]"

    def convert_br(self, el, text=None, *args, **kwargs):
        """Convert <br> to newline."""
        return "\n"

    def convert_hr(self, el, text=None, *args, **kwargs):
        """Convert <hr> to markdown horizontal rule."""
        return "\n---\n"


def _ocr_image(image):
    """Run the locally installed Tesseract engine; never download models."""
    import pytesseract
    return pytesseract.image_to_string(image, config="--psm 7").strip()


def _clean_ocr_text(text: str) -> str:
    """Clean common OCR artifacts from short text strings (names, labels).

    Typical artifacts on tiny SEC images:
    - Punctuation misreads: "A:" -> "A.", "S_" -> "S."
    - Stray digits near punctuation: "S_ 3 Demchak" -> "S. Demchak"
    - Leading/trailing noise characters
    """
    # Fix misread periods (colon/underscore followed by optional stray digits before a capital)
    text = re.sub(r"(\w)[_:]\s*\d*\s+(?=[A-Z])", r"\1. ", text)
    # Years, currency symbols and footnote markers can be meaningful headers.
    text = re.sub(r"^[^\w$€£(]+", "", text)
    text = re.sub(r"[^\w.)%]+$", "", text)
    return text.strip()


def resolve_rotated_text_images(
    soup: BeautifulSoup,
    image_dir: Path,
) -> int:
    """OCR predownloaded adjacent assets only, failing explicitly on missing inputs.

    Pillow, pytesseract and a local Tesseract executable are required when a
    rotated image is present. Remote URLs and paths outside image_dir are rejected;
    all downloads belong to SECClient, not the parser.
    """
    from urllib.parse import unquote, urlsplit

    rotated_imgs = [img for img in soup.find_all("img") if _is_rotated_text_image(img)]
    if not rotated_imgs:
        return 0
    root = Path(image_dir).resolve()
    assets = []
    for img in rotated_imgs:
        src = str(img.get("src", ""))
        url = urlsplit(src)
        if not src or url.scheme or url.netloc:
            raise ValueError(f"OCR requires a predownloaded local image, not {src!r}")
        asset = (root / unquote(url.path)).resolve()
        if not asset.is_relative_to(root) or not asset.is_file():
            raise ValueError(f"OCR local image missing or outside image directory: {src!r}")
        assets.append(asset)

    try:
        from PIL import Image
        import pytesseract  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("OCR requires Pillow, pytesseract and a local Tesseract executable") from exc

    resolved = 0
    for img_tag, asset in zip(rotated_imgs, assets):
        try:
            with Image.open(asset) as image:
                rotated = image.rotate(-90, expand=True)
            w, h = rotated.size
            if h < 100:
                scale = max(3, 100 // h)
                rotated = rotated.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
            text = _clean_ocr_text(_ocr_image(rotated))
            if not text:
                raise ValueError("OCR returned no usable text")
            img_tag.replace_with(text)
            resolved += 1
        except Exception as exc:
            raise RuntimeError(f"Failed to OCR local image {asset.name}: {exc}") from exc
    return resolved


def _remove_hidden_content(soup: BeautifulSoup) -> None:
    """Apply hidden selectors while classes/styles and inline XBRL still exist."""
    hidden_css = re.compile(
        r"(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse)|"
        r"content-visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)",
        re.IGNORECASE,
    )
    hidden = []
    ix_prefixes = {"ix"}
    for tag in soup.find_all(True):
        ix_prefixes.update(
            key.split(":", 1)[1] for key, value in tag.attrs.items()
            if key.startswith("xmlns:") and "inlinexbrl" in str(value).lower()
        )
    for style in soup.find_all("style"):
        css = re.sub(r"/\*.*?\*/", "", style.get_text(), flags=re.DOTALL)
        for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if hidden_css.search(declarations):
                try:
                    hidden.extend(soup.select(selectors.strip()))
                except SelectorSyntaxError:
                    logger.warning("Unsupported CSS selector while removing hidden content: %s", selectors.strip())
    for tag in soup.find_all(True):
        if (
            tag.has_attr("hidden")
            or str(tag.get("aria-hidden", "")).lower() == "true"
            or hidden_css.search(str(tag.get("style", "")))
            or (":" in tag.name and tag.name.split(":")[-1].lower() in {"header", "hidden"}
                and tag.name.split(":")[0] in ix_prefixes)
        ):
            hidden.append(tag)
    for tag in hidden:
        if tag.parent is not None:
            tag.decompose()


def html_to_markdown(
    html: str,
    base_url: Optional[str] = None,
    *,
    local_image_dir: Optional[Path] = None,
    table_header_rows: Optional[dict[str, int]] = None,
) -> str:
    """Convert HTML content to Markdown.

    Args:
        html: HTML content string
        base_url: Deprecated; remote OCR is rejected. Use local_image_dir.
        local_image_dir: Enable OCR using only predownloaded images in this directory.

    Returns:
        Markdown formatted string
    """
    if base_url is not None:
        raise ValueError("Remote OCR is not supported; supply local_image_dir with predownloaded assets")
    html = re.sub(r"^\s*<\?xml\b.*?\?>", "", html, count=1, flags=re.IGNORECASE | re.DOTALL)
    soup = BeautifulSoup(_clean_page_markers(html), "lxml")
    _remove_hidden_content(soup)

    for tag in soup.find_all(["script", "style", "meta", "link"]):
        tag.decompose()

    if local_image_dir is not None:
        resolve_rotated_text_images(soup, local_image_dir)

    for tag in soup.find_all(True):
        style = tag.get("style", "")
        if re.search(r"(?:page-break-before|break-before)\s*:\s*(?:always|page|left|right)", style, re.IGNORECASE):
            tag.insert_before(NavigableString("\n\n---PAGE---\n\n"))
        if re.search(r"(?:page-break-after|break-after)\s*:\s*(?:always|page|left|right)", style, re.IGNORECASE):
            tag.insert_after(NavigableString("\n\n---PAGE---\n\n"))
        if tag.name in {"p", "div"} and not tag.find(["p", "div", "table"]):
            label = tag.get_text(" ", strip=True)
            if len(label) <= 180 and re.match(
                r"^(?:ITEM\s+\d+[A-Z]?[.:]\s+\S|PART\s+[IVX]+\b)", label, re.IGNORECASE
            ):
                tag.name = "h2"
            elif (not tag.find_parent("table") and not tag.find("a")
                  and 0 < len(label) <= 180 and re.search(r"[A-Za-z]", label)):
                # Preserve established bold headings; require title-like text
                # before additionally promoting nested CSS-styled text runs.
                bold = tag.find(["b", "strong"])
                if ((bold and bold.get_text(" ", strip=True) == label)
                    or re.search(r"font-weight\s*:\s*(?:bold|[6-9]00)", style, re.IGNORECASE)
                    or _is_styled_heading(tag, label)):
                    tag.name = "h3"
    # Keep descendant styles intact until heading recognition has seen them.
    for tag in soup.find_all(True):
        if tag.get("style") and tag.name not in {"img", "td", "th"}:
            del tag["style"]
        if tag.get("class"):
            del tag["class"]

    try:
        converter = SECMarkdownConverter(
            heading_style="atx",
            bullets="-",
            strip=["a"],
            table_header_rows=table_header_rows,
        )

        markdown = converter.convert(str(soup))
    except RecursionError:
        # Fall back to plain text extraction for deeply nested HTML
        logger.warning("HTML too deeply nested, falling back to text extraction")
        if table_header_rows is not None:
            table_header_rows.clear()
        markdown = soup.get_text(separator="\n")

    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n[ \t]+", "\n", markdown)

    lines = markdown.split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    markdown = "\n".join(cleaned_lines)

    return markdown.strip()


def extract_sgml_documents(content: str) -> list[dict]:
    """Extract individual documents from SGML wrapper.

    Args:
        content: Raw SGML filing content

    Returns:
        List of document dicts with 'type', 'sequence', 'filename', 'text'
    """
    documents = []

    doc_pattern = re.compile(
        r"<DOCUMENT>(.*?)</DOCUMENT>",
        re.DOTALL | re.IGNORECASE
    )

    for match in doc_pattern.finditer(content):
        doc_content = match.group(1)

        doc_type = ""
        sequence = ""
        filename = ""

        type_match = re.search(r"<TYPE>([^\n<]+)", doc_content, re.IGNORECASE)
        if type_match:
            doc_type = type_match.group(1).strip()

        seq_match = re.search(r"<SEQUENCE>([^\n<]+)", doc_content, re.IGNORECASE)
        if seq_match:
            sequence = seq_match.group(1).strip()

        fn_match = re.search(r"<FILENAME>([^\n<]+)", doc_content, re.IGNORECASE)
        if fn_match:
            filename = fn_match.group(1).strip()

        text_match = re.search(r"<TEXT>(.*?)(</TEXT>|$)", doc_content, re.DOTALL | re.IGNORECASE)
        text = text_match.group(1).strip() if text_match else doc_content

        documents.append({
            "type": doc_type,
            "sequence": sequence,
            "filename": filename,
            "text": text,
        })

    return documents


def clean_sec_text(text: str) -> str:
    """Clean SEC-specific text artifacts.

    Args:
        text: Raw text from SEC filing

    Returns:
        Cleaned text
    """
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text, flags=re.IGNORECASE)
    text = re.sub(r"&lt;", "<", text, flags=re.IGNORECASE)
    text = re.sub(r"&gt;", ">", text, flags=re.IGNORECASE)
    text = re.sub(r"&quot;", '"', text, flags=re.IGNORECASE)

    text = _clean_page_markers(text)

    text = re.sub(r"<[A-Z]+>(?=\s*\n)", "", text)

    return text


def _clean_page_markers(text: str) -> str:
    """Normalize SEC markers without decoding literal escaped HTML into tags."""
    text = re.sub(r"<PAGE>\s*", "\n\n---PAGE---\n\n", text, flags=re.IGNORECASE)
    return re.sub(r"-----+\s*PAGE\s*-----+", "\n\n---PAGE---\n\n", text, flags=re.IGNORECASE)


def parse_document(
    file_path: Path,
    filing: FilingMetadata,
    document: DocumentInfo,
    ocr_images: bool = False,
    *,
    local_image_dir: Optional[Path] = None,
) -> Optional[ParsedDocument]:
    """Parse a downloaded document file.

    Args:
        file_path: Path to downloaded file
        filing: Filing metadata
        document: Document info
        ocr_images: OCR rotated text using predownloaded assets only. Missing
                    images/dependencies or failed OCR raise explicit errors.
        local_image_dir: Image directory; defaults to file_path.parent.

    Returns:
        ParsedDocument or None if parsing fails
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return None

    if re.search(r"<DOCUMENT\s*>", content, re.IGNORECASE):
        documents = extract_sgml_documents(content)
        matches = [
            candidate for candidate in documents
            if candidate["filename"] == document.filename
            and candidate["sequence"].isdigit()
            and int(candidate["sequence"]) == document.sequence
            and candidate["type"].casefold() == document.document_type.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(
                f"SGML document selection requires exactly one match for "
                f"{document.filename!r}, sequence {document.sequence}, "
                f"type {document.document_type!r}; found {len(matches)}"
            )
        content = matches[0]["text"]

    is_html = file_path.suffix.lower() in {".htm", ".html"} or re.search(
        r"<(?:html|head|body|table|p|div|span|img|br|pre|ul|ol|li|h[1-6]|ix:[\w-]+)(?:\s|/?>)",
        content, re.IGNORECASE,
    )
    table_header_rows = {}
    if is_html:
        markdown = html_to_markdown(
            content,
            local_image_dir=(local_image_dir or file_path.parent) if ocr_images else None,
            table_header_rows=table_header_rows,
        )
    else:
        markdown = clean_sec_text(content)

    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

    if not markdown.strip():
        logger.warning(f"Document empty after parsing: {file_path}")
        return None

    return ParsedDocument(
        filing=filing,
        document=document,
        content=markdown,
        content_type="text/markdown",
        table_header_rows=table_header_rows,
    )


def parse_filing_index(content: str) -> dict:
    """Parse a filing index file to extract document list.

    Args:
        content: Index file content

    Returns:
        Dict with 'documents' list
    """
    documents = []

    lines = content.split("\n")
    in_document_section = False

    for line in lines:
        if "DOCUMENT" in line.upper() and "SEQUENCE" in line.upper():
            in_document_section = True
            continue

        if in_document_section and line.strip():
            parts = line.split()
            if len(parts) >= 3:
                documents.append({
                    "sequence": parts[0],
                    "filename": parts[1] if len(parts) > 1 else "",
                    "type": parts[2] if len(parts) > 2 else "",
                    "description": " ".join(parts[3:]) if len(parts) > 3 else "",
                })

    return {"documents": documents}
