"""Compare private corpus replay artifacts; does not contact services or sources."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from tests.corpus_replay import numbers, tokens


def contextual_rows(text, payloads):
    """Audit short adjacent units/linked notes; report heuristic misses for review."""
    output = {}
    row_contexts = {}
    for payload in payloads:
        content = payload["content"]["value"]
        for row in content.splitlines():
            if row.startswith("|"):
                row_contexts.setdefault(row, []).append(content)
    for match in re.finditer(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.MULTILINE):
        table = match.group()
        if not re.search(r"\b(?:19|20)\d{2}\b", table):
            continue
        preceding = text[max(0, match.start() - 600):match.start()].split("---PAGE---")[-1]
        following = text[match.end():match.end() + 600].split("---PAGE---")[0]
        context = []
        for paragraph in re.split(r"\n\s*\n", preceding)[-4:]:
            if len(paragraph) <= 240 and re.search(r"\bin (?:millions|billions|thousands)\b", paragraph, re.I):
                context.append(paragraph.strip())
        note = re.split(r"\n\s*\n", following.strip())[0]
        marker = re.match(r"^(\([a-z0-9]+\)|\[[a-z0-9]+\])", note, re.I)
        if marker and marker[1] in table and len(note) <= 240:
            context.append(note)
        for row in table.splitlines()[2:]:
            for label in context:
                key = (row, label)
                output[key] = any(label in c for c in row_contexts.get(row, []))
    return output


def period_rows(text, payloads):
    """Catch date/units rows left in the body rather than repeated as headers."""
    row_contexts = {}
    for payload in payloads:
        content = payload["content"]["value"]
        for row in content.splitlines():
            if row.startswith("|"):
                row_contexts.setdefault(row, []).append(content)
    checks = {}
    for match in re.finditer(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.MULTILINE):
        lines = match.group().splitlines()
        if len(lines) < 4 or re.search(r"\b(?:19|20)\d{2}\b", lines[0]):
            continue
        period = next((
            i for i in range(2, min(6, len(lines)))
            if len(re.findall(r"\b(?:19|20)\d{2}\b", lines[i])) >= 2
            and not re.search(r"\d,\d{3}", lines[i])
        ), None)
        if period is None:
            continue
        label = lines[period]
        for row in lines[period + 1:]:
            if re.search(r"\d,\d{3}", row):
                checks[(row, label)] = any(label in c for c in row_contexts.get(row, []))
    return checks


def compare(baseline, candidate):
    before = json.loads((baseline / "result.json").read_bytes())
    after = json.loads((candidate / "result.json").read_bytes())
    a = (baseline / "parsed.md").read_text(encoding="utf-8")
    b = (candidate / "parsed.md").read_text(encoding="utf-8")
    ta = json.loads((baseline / "tables.json").read_bytes())
    tb = json.loads((candidate / "tables.json").read_bytes())
    changes = []
    assert len(ta) == len(tb), "Source table inventory changed"
    for old, new in zip(ta, tb):
        assert old["source_cells"] == new["source_cells"], "Source cell mapping changed"
        if old["converted"] != new["converted"]:
            changes.append({
                "index": old["index"],
                "is_list": new["converted"].startswith("- "),
                "old": old["converted"], "new": new["converted"],
                "cells": old["source_cells"],
            })
    added = list((Counter(after["headings"]) - Counter(before["headings"])).elements())
    removed = list((Counter(before["headings"]) - Counter(after["headings"])).elements())
    old_context = contextual_rows(a, json.loads((baseline / "payloads.json").read_bytes()))
    new_context = contextual_rows(b, json.loads((candidate / "payloads.json").read_bytes()))
    context_regressions = [
        {"row": row, "context": label} for (row, label), preserved in new_context.items()
        if not preserved and old_context.get((row, label))
    ]
    old_period = period_rows(a, json.loads((baseline / "payloads.json").read_bytes()))
    new_period = period_rows(b, json.loads((candidate / "payloads.json").read_bytes()))
    outcomes = {
        "id": after["id"], "baseline_chunks": before["chunks"], "candidate_chunks": after["chunks"],
        "lexical_equal": tokens(a) == tokens(b),
        "numeric_equal": numbers(a) == numbers(b),
        "added_tokens": dict(Counter(tokens(b)) - Counter(tokens(a))),
        "lost_tokens": dict(Counter(tokens(a)) - Counter(tokens(b))),
        "table_count": len(ta), "table_changes": changes,
        "non_list_table_changes": sum(not c["is_list"] for c in changes),
        "added_headings": added, "removed_headings": removed,
        "suspicious_new_headings": [h for h in added if re.search(r"(?:[.!?;]$|\b(?:we|our|you|your)\b)", h, re.I)],
        "baseline_section_mixing": before["section_mixing"],
        "candidate_section_mixing": after["section_mixing"],
        "baseline_row_failures": before["row_failures"],
        "candidate_row_failures": after["row_failures"],
        "emitted_lexical_coverage": after["emitted_lexical_coverage"],
        "emitted_numeric_coverage": after["emitted_numeric_coverage"],
        "max_chars": after["max_chars"], "max_request_bytes": after["max_request_bytes"],
        "baseline_report_period": before["report_period_values"],
        "candidate_report_period": after["report_period_values"],
        "relational_rows": after["relational_rows"],
        "context_checks": len(new_context),
        "context_misses": sum(not passed for passed in new_context.values()),
        "new_context_misses": context_regressions,
        "period_checks": len(new_period),
        "period_misses": sum(not passed for passed in new_period.values()),
        "baseline_period_misses": sum(not passed for passed in old_period.values()),
        "new_period_misses": [
            {"row": row, "period": label} for (row, label), passed in new_period.items()
            if not passed and old_period.get((row, label))
        ],
    }
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for path in sorted(args.candidate.iterdir()):
        if path.is_dir() and (path / "result.json").exists() and (args.baseline / path.name / "result.json").exists():
            result = compare(args.baseline / path.name, path)
            results.append(result)
            print(json.dumps({key: value for key, value in result.items() if key not in {
                "table_changes", "added_headings", "removed_headings", "baseline_section_mixing",
                "candidate_section_mixing", "baseline_row_failures", "candidate_row_failures",
            }}, ensure_ascii=True))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2)


if __name__ == "__main__":
    main()
