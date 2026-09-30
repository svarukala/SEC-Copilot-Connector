"""Offline structural-band audit with separately reviewed source-header bounds."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from sec_connector.chunker import _table_header_count
from tests.table_context_audit import TABLE, SEPARATOR


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def audit(text, before, after, annotations, approved, captures):
    source_tables = {
        digest(match.group()): match.group().splitlines()
        for match in TABLE.finditer(text)
        if len(match.group().splitlines()) > 1
        and SEPARATOR.fullmatch(match.group().splitlines()[1])
    }
    assert set(approved) == {a["table_sha256"] for a in annotations}, "Unreviewed annotation"
    capture_map = defaultdict(list)
    for capture in captures:
        for match in TABLE.finditer(capture["converted"]):
            capture_map[digest(match.group())].append(capture)
    contexts = []
    for payloads in (before, after):
        rows = defaultdict(list)
        for payload in payloads:
            for line in payload["content"]["value"].splitlines():
                if line.startswith("|"):
                    rows[line].append(payload["content"]["value"])
        contexts.append(rows)
    bands = []
    allowed_extra = set()
    source_counts = Counter()
    row_owners = defaultdict(set)
    for key, lines in source_tables.items():
        allowed_extra.update(lines[2:_table_header_count(lines)])
        for row in lines[2:]:
            row_owners[row].add(key)
    # Occurrences, including duplicate source tables, must not disappear.
    for match in TABLE.finditer(text):
        lines = match.group().splitlines()
        if len(lines) > 1 and SEPARATOR.fullmatch(lines[1]):
            source_counts.update(lines[2:])
    for annotation in annotations:
        key = annotation["table_sha256"]
        count = approved[key]
        assert count == annotation["source_header_rows"], "Header extends beyond reviewed bound"
        lines = source_tables[key]
        band = "\n".join(lines[:count])
        assert band == annotation["band"]
        assert capture_map[key], "Missing source-cell mapping"
        allowed_extra.update(lines[2:count])
        checks = []
        occurrence_checks = []
        ambiguous = []
        for row in lines[count:]:
            checks.append({
                "row_sha256": digest(row),
                "before": any(band in content for content in contexts[0][row]),
                "after": any(band in content for content in contexts[1][row]),
            })
            if len(row_owners[row]) == 1:
                occurrence_checks.extend(band in content for content in contexts[1][row])
            else:
                ambiguous.append(digest(row))
        bands.append({
            "table_sha256": key, "band_sha256": digest(band), "reviewed_header_rows": count,
            "source_mappings": [
                {"capture_index": c["index"], "raw_header_end": c["source_header_end"],
                 "source_cells_sha256": digest(json.dumps(c["source_cells"], sort_keys=True)),
                 "raw_header_cells": c["source_structure"][:c["source_header_end"]]}
                for c in capture_map[key]
            ],
            "checks": len(checks),
            "before_missing": sum(not c["before"] for c in checks),
            "after_missing": sum(not c["after"] for c in checks),
            "new_missing": sum(c["before"] and not c["after"] for c in checks),
            "row_checks": checks,
            "unique_occurrence_checks": len(occurrence_checks),
            "unique_occurrence_misses": sum(not passed for passed in occurrence_checks),
            "ambiguous_source_rows": ambiguous,
        })
    actual = Counter()
    for payload in after:
        for match in TABLE.finditer(payload["content"]["value"]):
            lines = match.group().splitlines()
            if len(lines) > 1 and SEPARATOR.fullmatch(lines[1]):
                actual.update(lines[2:])
    unexpected = {row: n for row, n in (actual - source_counts).items() if row not in allowed_extra}
    return {
        "bands": bands,
        "checks": sum(b["checks"] for b in bands),
        "before_missing": sum(b["before_missing"] for b in bands),
        "after_missing": sum(b["after_missing"] for b in bands),
        "new_missing": sum(b["new_missing"] for b in bands),
        "unique_occurrence_checks": sum(b["unique_occurrence_checks"] for b in bands),
        "unique_occurrence_misses": sum(b["unique_occurrence_misses"] for b in bands),
        "ambiguous_source_rows": sum(len(b["ambiguous_source_rows"]) for b in bands),
        "missing_occurrences": dict(source_counts - actual),
        "unapproved_extra_rows": unexpected,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reviews = json.loads(args.review.read_bytes())
    results = []
    for path in sorted(args.candidate.iterdir()):
        if not (path / "payloads.json").is_file():
            continue
        text = (path / "parsed.md").read_text(encoding="utf-8")
        assert text == (args.baseline / path.name / "parsed.md").read_text(encoding="utf-8")
        result = audit(
            text, json.loads((args.baseline / path.name / "payloads.json").read_bytes()),
            json.loads((path / "payloads.json").read_bytes()),
            json.loads((args.candidate / (path.name + "-annotations.json")).read_bytes()),
            reviews[path.name], json.loads((path / "tables.json").read_bytes()),
        )
        result["id"] = path.name
        results.append(result)
        print(path.name, {k: v for k, v in result.items() if k not in {
            "bands", "missing_occurrences", "unapproved_extra_rows",
        }}, "unapproved", len(result["unapproved_extra_rows"]), flush=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2)


if __name__ == "__main__":
    main()
