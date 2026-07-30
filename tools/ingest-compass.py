#!/usr/bin/env python3
"""
Fold Compass learning-task exports into the tracker's coverage records.

Reads one or more LearningTaskExport CSVs plus a coverage.json, and writes a new
coverage.json in which each matching record gains a `dist` tally:

    "dist": {"Established": 57, "Exceeding": 17, ... , "(Excluded)": 1}

Matching is criterion column heading -> the `notes` of a record on the same
assessment task. The task is identified by the code in the CSV filename
(e.g. S1_07EN_CAT1), so naming drift between Compass and the tracker is fine.

PRIVACY: only counts are written. Student names, comments, submission states and
per-student rows are read and discarded. Never commit the CSVs themselves --
the tracker repo is public.

Usage:
    python3 tools/ingest-compass.py coverage.json exports/*.csv -o coverage-new.json
    python3 tools/ingest-compass.py coverage.json exports/*.csv --dry-run
"""

import argparse
import csv
import glob
import io
import json
import os
import re
import sys
from collections import Counter, OrderedDict

BANDS = ["Requires Support", "Developing", "Established", "Highly Developed", "Exceeding"]
EXCLUDED = "(Excluded)"
VALID = BANDS + [EXCLUDED]

# Columns that are never criteria
META_COLS = {"id", "name", "submission state", "sn", "comment (open)", "comment", "result", "total"}


def norm(s):
    """Loose key for matching names: ignores case, spacing and hyphenation."""
    s = str(s or "").lower().replace("–", "-").replace("—", "-")
    return re.sub(r"[\s\-]+", "", s)


def subject(tok):
    """08ENG and 08EN are the same subject in Compass exports; ADVEN is not."""
    tok = tok.upper()
    m = re.match(r"^([0-9]{2})(.*)$", tok)
    if not m:
        return tok
    level, rest = m.group(1), m.group(2)
    if rest in ("ENG", "EN"):
        rest = "EN"
    return level + rest


def task_code(text):
    """Pull an assessment code like S1_07EN_CAT1 out of a filename or task name."""
    m = re.search(r"(S\d)[_ ]*([0-9]{2}[A-Z]+[0-9]*)[_ ]*(CAT\s*\d+)", str(text), re.I)
    if not m:
        return None
    return norm(m.group(1) + subject(m.group(2)) + m.group(3))


def read_export(path):
    """Return (criterion -> Counter of bands, n_rows, skipped_columns)."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read()
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows:
        return {}, 0, []
    tallies, skipped = OrderedDict(), []
    for col in rows[0].keys():
        if col is None or col.strip().lower() in META_COLS:
            continue
        counts = Counter()
        for r in rows:
            v = (r.get(col) or "").strip()
            if not v:
                continue          # blanks are ignored, as requested
            if v in VALID:
                counts[v] += 1
            else:
                counts["__other__:" + v] += 1
        if counts:
            tallies[col] = counts
        else:
            skipped.append(col)
    return tallies, len(rows), skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("coverage", help="existing coverage.json")
    ap.add_argument("csvs", nargs="+", help="LearningTaskExport CSV files (globs ok)")
    ap.add_argument("-o", "--out", help="where to write the updated coverage.json")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--aliases", help="JSON map for criteria whose Compass wording differs "
                                      "from the tracker: {taskCode: {csvColumn: VC2Ecode}}")
    args = ap.parse_args()

    aliases = {}
    if args.aliases:
        with open(args.aliases, encoding="utf-8") as fh:
            for tc, cols in json.load(fh).items():
                if tc.startswith("_") or not isinstance(cols, dict):
                    continue          # comment keys
                aliases[task_code(tc) or norm(tc)] = {norm(k): v for k, v in cols.items()}

    paths = []
    for pattern in args.csvs:
        paths.extend(sorted(glob.glob(pattern)) or [pattern])

    with open(args.coverage, encoding="utf-8") as fh:
        doc = json.load(fh)
    coverage = doc.get("coverage", doc)

    # index records by (task code, normalised criterion) and by (task code, cd code)
    index, by_cd, tasks_seen = {}, {}, {}
    for code, records in coverage.items():
        for rec in records:
            tc = task_code(rec.get("assessment"))
            if tc:
                tasks_seen.setdefault(tc, set()).add(rec.get("assessment"))
            index.setdefault((tc, norm(rec.get("notes"))), []).append((code, rec))
            by_cd.setdefault((tc, code), []).append((code, rec))

    applied, unmatched, oddities = [], [], []

    for path in paths:
        base = os.path.basename(path)
        tc = task_code(base)
        tallies, nrows, skipped = read_export(path)
        if not tc:
            unmatched.append((base, "-", "no assessment code in the filename"))
            continue
        if tc not in tasks_seen:
            unmatched.append((base, "-", "no records for this task in coverage.json"))
            continue
        print("\n%s\n  task %s -> %s  (%d student rows)"
              % (base, tc, sorted(tasks_seen[tc])[0], nrows))
        for crit, counts in tallies.items():
            others = {k.split(":", 1)[1]: v for k, v in counts.items() if k.startswith("__other__:")}
            dist = {b: counts[b] for b in VALID if counts[b]}
            if others:
                oddities.append((base, crit, others))
            if not dist:
                continue
            hits = index.get((tc, norm(crit)), [])
            via = ""
            if not hits:
                target = aliases.get(tc, {}).get(norm(crit))
                if target:
                    hits = by_cd.get((tc, target), [])
                    via = " (via alias -> %s)" % target
                    if not hits:
                        unmatched.append((base, crit, "alias points at %s but no such record on the task" % target))
                        continue
            if not hits:
                unmatched.append((base, crit, "no record with this criterion on the task"))
                continue
            for code, rec in hits:
                rec["dist"] = dist
                applied.append((code, crit, sum(dist[b] for b in BANDS if b in dist)))
                print("    %-11s %-42s %s%s" % (code, crit[:42],
                      " ".join("%s=%d" % (b[:3], dist[b]) for b in VALID if b in dist), via))
            if len(hits) > 1:
                oddities.append((base, crit, "matched %d records: %s"
                                 % (len(hits), ", ".join(c for c, _ in hits))))
        for col in skipped:
            print("    (ignored empty column: %s)" % col)

    print("\n%d record(s) updated." % len(applied))
    if oddities:
        print("\nValues outside the rating scale — not counted:")
        for base, crit, others in oddities:
            print("  %s / %s: %s" % (base, crit, others))
    if unmatched:
        print("\nNeeds your input:")
        for base, crit, why in unmatched:
            print("  %s / %s: %s" % (base, crit, why))

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0
    out = args.out or "coverage-updated.json"
    doc["coverage"] = coverage
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("\nWrote %s — import it via Data -> Import JSON." % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
