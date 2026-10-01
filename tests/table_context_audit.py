"""Additional offline audits; retain the original broad corpus diagnostics."""

from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import re


TABLE = re.compile(r"^\|[^\n]*(?:\n\|[^\n]*)*", re.M)
SEPARATOR = re.compile(r"\|(?:\s*:?-+:?\s*\|)+\s*")


def data_row_counts(text, payloads):
    """Classify extra occurrences only as contiguous leading source context.

    Every source row must still occur at least as often as in the source. An
    extra row is contextual repetition only when it is in an exact source
    table prefix, repeated immediately after that table's Markdown separator.
    Synthetic tests independently assert which rows are valid period headers.
    """
    expected = Counter()
    actual = Counter()
    prefixes = defaultdict(list)
    for match in TABLE.finditer(text):
        rows = match.group().splitlines()
        if len(rows) > 1 and SEPARATOR.fullmatch(rows[1]):
            expected.update(rows[2:])
            prefixes[tuple(rows[:2])].append(rows[2:])
    repeats = Counter()
    for payload in payloads:
        for match in TABLE.finditer(payload["content"]["value"]):
            rows = match.group().splitlines()
            if len(rows) < 2 or not SEPARATOR.fullmatch(rows[1]):
                continue
            actual.update(rows[2:])
            for source in prefixes.get(tuple(rows[:2]), []):
                for index, (left, right) in enumerate(zip(source, rows[2:])):
                    if left != right:
                        break
                    # A repeated source prefix needs no data reordering to
                    # explain it. Track occurrences, not only membership.
                    repeats[(tuple(rows[:2]), index, left)] += 1
    allowed = Counter()
    for (_, _, row), count in repeats.items():
        allowed[row] += max(0, count - 1)
    missing = expected - actual
    unexplained = (actual - expected) - allowed
    return {
        "source_data_rows": sum(expected.values()),
        "emitted_data_rows": sum(actual.values()),
        "missing_occurrences": dict(missing),
        "unexplained_extra_occurrences": dict(unexplained),
        "repeated_prefix_rows": sum((actual - expected).values()),
    }


def linked_notes(text, payloads):
    """Audit contiguous explicit definitions only on rows carrying their marker.

    Unlike the frozen broad adjacent-context metric, a marker in another data
    row does not make a note apply to every row of a table.
    """
    contexts = defaultdict(list)
    for payload in payloads:
        content = payload["content"]["value"]
        for line in content.splitlines():
            if line.startswith("|"):
                contexts[line].append(content)
    checks = {}
    for table_index, match in enumerate(TABLE.finditer(text)):
        rows = match.group().splitlines()
        if len(rows) < 3 or not SEPARATOR.fullmatch(rows[1]):
            continue
        following = text[match.end():].split("---PAGE---")[0]
        definitions = []
        for paragraph in re.split(r"\n\s*\n|\n(?=\([a-z0-9]+\)|\[[a-z0-9]+\])", following.strip()):
            label = re.match(r"^(\([a-z0-9]+\)|\[[a-z0-9]+\])\s*\S", paragraph, re.I)
            if not label:
                break
            definitions.append((label[1], paragraph))
        counts = Counter(marker for marker, _ in definitions)
        for marker, note in definitions:
            if counts[marker] != 1:
                continue
            for row_index, row in enumerate(rows[2:]):
                # Parenthesized integers alone are ambiguous signed values.
                cells = re.split(r"(?<!\\)\|", rows[0] + "|" + row)
                relevant = any((marker in cell or any(
                    marker == "(" + item + ")"
                    for group in re.findall(r"\(([a-z0-9]{1,2}(?:,\s*[a-z0-9]{1,2})+)\)", cell, re.I)
                    for item in re.split(r",\s*", group)
                )) and (
                    marker.startswith("[") or re.search(r"[A-Za-z]", cell)
                    or re.search(r"\b(?:19|20)\d{2}\b", cell.replace(marker, ""))
                ) for cell in cells)
                if relevant:
                    checks[(table_index, row_index, marker, note)] = any(
                        note in content for content in contexts.get(row, [])
                    )
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    results = []
    for path in sorted(options.candidate.iterdir()):
        if not (path / "payloads.json").is_file():
            continue
        old = options.baseline / path.name
        text = (path / "parsed.md").read_text(encoding="utf-8")
        assert text == (old / "parsed.md").read_text(encoding="utf-8")
        before = json.loads((old / "payloads.json").read_bytes())
        after = json.loads((path / "payloads.json").read_bytes())
        old_notes = linked_notes(text, before)
        new_notes = linked_notes(text, after)
        assert old_notes.keys() == new_notes.keys()
        result = {
            "id": path.name,
            "data_row_occurrences": data_row_counts(text, after),
            "linked_note_checks": len(new_notes),
            "baseline_linked_note_misses": sum(not passed for passed in old_notes.values()),
            "candidate_linked_note_misses": sum(not passed for passed in new_notes.values()),
            "resolved_linked_note_misses": sum(new_notes[key] and not old_notes[key] for key in new_notes),
            "new_linked_note_misses": [list(key) for key in new_notes if not new_notes[key] and old_notes[key]],
            "remaining_linked_note_misses": [list(key) for key, passed in new_notes.items() if not passed],
        }
        results.append(result)
        print(path.name, result["candidate_linked_note_misses"], len(result["new_linked_note_misses"]))
    with options.output.open("x", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2)


if __name__ == "__main__":
    main()
