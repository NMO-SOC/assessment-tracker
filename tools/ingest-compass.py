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
    """Loose key for matching names: ignores case, spacing, hyphens, punctuation,
    and treats '&' as 'and'."""
    s = str(s or "").lower().replace("–", "-").replace("—", "-")
    s = s.replace("&", "and").replace("’", "'")
    s = re.sub(r"[,.'‘’\"]", "", s)
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
    m = re.search(r"(S\d)[_ ]*([0-9]{2}[A-Z]+?)[0-9]*[_ ]*(?:[0-9]+[_ ]*)?(CAT\s*\d+)", str(text), re.I)
    if not m:
        return None
    return norm(m.group(1) + subject(m.group(2)) + m.group(3))


def read_export(path):
    """Return (criterion -> Counter of bands, n_rows, skipped_columns)."""
    data = open(path, "rb").read()
    raw = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            raw = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raw = data.decode("utf-8", errors="replace")
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
                                      "from the tracker: {taskName: {csvColumn: VC2Ecode | [codes]}}")
    ap.add_argument("--create-missing", action="store_true",
                    help="if an alias names a content description with no record on that task, "
                         "add one (date and class copied from the task's other records)")
    ap.add_argument("--task-map", help="JSON map for exports whose filename doesn't match the "
                                       "tracker's task name: {filenameFragment: exactTaskName}")
    args = ap.parse_args()

    def load_map(path):
        if not path:
            return {}
        with open(path, encoding="utf-8") as fh:
            return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}

    aliases = {}
    for tname, cols in load_map(args.aliases).items():
        if isinstance(cols, dict):
            aliases[norm(tname)] = {norm(k): v for k, v in cols.items()}
    task_map = {norm(k): v for k, v in load_map(args.task_map).items()}

    paths = []
    for pattern in args.csvs:
        paths.extend(sorted(glob.glob(pattern)) or [pattern])

    with open(args.coverage, encoding="utf-8") as fh:
        doc = json.load(fh)
    coverage = doc.get("coverage", doc)

    # index records by exact task name, then criterion or cd code
    index, by_cd, by_code, all_tasks = {}, {}, {}, set()
    for code, records in coverage.items():
        for rec in records:
            tname = rec.get("assessment") or ""
            all_tasks.add(tname)
            index.setdefault((norm(tname), norm(rec.get("notes"))), []).append((code, rec))
            by_cd.setdefault((norm(tname), code), []).append((code, rec))
            tc = task_code(tname)
            if tc:
                by_code.setdefault(tc, set()).add(tname)

    def resolve_task(base):
        """Filename -> the tracker's task name. Explicit map first, then code."""
        for frag, tname in task_map.items():
            if frag and frag in norm(base):
                return tname, "mapped"
        tc = task_code(base)
        if tc and tc in by_code:
            names = sorted(by_code[tc])
            if len(names) == 1:
                return names[0], "by code"
            return None, "code %s is ambiguous: %s" % (tc, "; ".join(names))
        return None, "no matching task"

    applied, unmatched, oddities, created = [], [], [], []

    for path in paths:
        base = os.path.basename(path)
        tallies, nrows, skipped = read_export(path)
        tname, how = resolve_task(base)
        if not tname:
            unmatched.append((base, "-", how))
            continue
        tc = norm(tname)
        print("\n%s\n  -> %s  (%s, %d student rows)" % (base, tname, how, nrows))
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
                    targets = target if isinstance(target, list) else [target]
                    hits, missing = [], []
                    for t in targets:
                        got = by_cd.get((tc, t), [])
                        hits.extend(got)
                        if not got:
                            missing.append(t)
                    via = " (alias -> %s)" % ", ".join(targets)
                    for t_code in missing:
                        if not args.create_missing:
                            unmatched.append((base, crit,
                                "alias names %s but the task has no record on it "
                                "(re-run with --create-missing to add it)" % t_code))
                            continue
                        sibling = next((r for (tn, _c), lst in by_cd.items() if tn == tc
                                        for _cc, r in lst), None)
                        new = {"id": "%08x" % (abs(hash(tc + t_code + crit)) & 0xffffffff),
                               "assessment": tname,
                               "date": (sibling or {}).get("date", ""),
                               "cls": (sibling or {}).get("cls", ""),
                               "notes": crit.strip()}
                        coverage.setdefault(t_code, []).append(new)
                        by_cd.setdefault((tc, t_code), []).append((t_code, new))
                        hits.append((t_code, new))
                        created.append((t_code, tname, crit.strip()))
                    if not hits:
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
    if created:
        print("\nNew records added (no existing record carried this criterion):")
        for code, tname, crit in created:
            print("  %s on %s  <- %s" % (code, tname, crit))
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
