"""Statistics of crawled samples per evolution cell, and export to O/U json files.

    python -m llm_dep.crawling.report [--export]

Writes manual_reviews/API_MIGRATION_COUNTS_AFTER.md: an exact copy of the BEFORE file in which
each U / O cell becomes `crawled/needed`, where needed = (max of the path, or --cap) - BEFORE
count, and 0 when the API does not exist at that milestone. Samples of cells that BEFORE already
filled are trimmed (unless --keep-extra). With --export also writes
data/<lib>/O_crawled.json and U_crawled.json.
"""
import argparse
import collections
import json
import re
from pathlib import Path

from .evolution import LIBS, Evolution
from .quota import Quota, parse_counts_md
from .run import load_jsonl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--crawl", default="data", help="root holding <lib>/crawl/samples.jsonl")
    ap.add_argument("--before", default="manual_reviews/API_MIGRATION_COUNTS_BEFORE.md")
    ap.add_argument("--out", default="manual_reviews/API_MIGRATION_COUNTS_AFTER.md")
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--keep-extra", action="store_true",
                    help="keep samples of cells that BEFORE already filled (default: trim them)")
    args = ap.parse_args()

    data = Path(args.data)
    ev = Evolution(data)
    quota = Quota(ev, parse_counts_md(Path(args.before), ev), cap=args.cap, baseline="existing")

    def need(cell):
        """Samples to crawl on top of BEFORE to reach the cell target (0 when the API does not
        exist at that milestone or BEFORE already reaches the target)."""
        if not quota.feasible(cell):
            return 0
        return max(0, quota.target[cell[0]] - quota.before[cell[0]][cell[1]].get(cell[2], 0))

    samples, dropped = {}, collections.Counter()
    for lib in LIBS:
        kept = []
        for s in load_jsonl(Path(args.crawl) / lib / "crawl" / "samples.jsonl"):
            cells = [(a["mapping_id"], s["kind"], a["milestone"]) for a in s["assignments"]]
            # keep a sample (in crawl order) only while one of its cells still needs samples
            if args.keep_extra or any(quota.filled[c] < need(c) for c in cells):
                quota.add(cells)
                kept.append(s)
            else:
                dropped[lib] += 1
        samples[lib] = kept
    if dropped:
        print(f"trimmed samples of cells already filled by BEFORE: {dict(dropped)}")
    # Samples written before the signature branch existed carry no `assigned_by`: dependency branch.
    print(f"{'library':14} {'dependency O/U':>15} {'signature O/U':>15} {'(sig. dep-verified)':>20}")
    for lib, ss in samples.items():
        c = collections.Counter((s.get("assigned_by", "dependency"), s["kind"]) for s in ss)
        ver = sum(1 for s in ss if s.get("assigned_by") == "signature" and s.get("dependency_verified"))
        if ss:
            print(f"{lib:14} {c['dependency', 'O']:>7}/{c['dependency', 'U']:<7} "
                  f"{c['signature', 'O']:>7}/{c['signature', 'U']:<7} {ver:>20}")

    # Same file as BEFORE, only the numbers of the U / O rows are replaced.
    out_lines, cur, versions = [], None, None
    for line in Path(args.before).read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^(\S+) → (\S+)\s*$", line)
        if m:
            cur, versions = ev.by_deprecated.get(m.group(1)), None
        elif cur is not None and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells[0] == "Version":
                versions = cells[1:]
            elif cells[0] in ("U", "O") and versions:
                vals = []
                for v in versions:
                    cell = (cur.mapping_id, cells[0], v)
                    vals.append(f"{quota.filled[cell]}/{need(cell)}")
                line = f"| {cells[0]} | " + " | ".join(vals) + " |"
        out_lines.append(line)
    Path(args.out).write_text("\n".join(out_lines), encoding="utf-8")
    total = quota.total_deficit()
    print(f"wrote {args.out}; remaining deficit (cap={args.cap}) {total}")

    if args.export:
        for lib, ss in samples.items():
            by_kind = collections.defaultdict(list)
            for s in ss:
                by_kind[s["kind"]].append(s)
            for kind in "OU":
                f = Path(args.crawl) / lib / f"{kind}_crawled.json"
                f.parent.mkdir(parents=True, exist_ok=True)
                json.dump(by_kind[kind], open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                print(f"{f}: {len(by_kind[kind])} samples")


if __name__ == "__main__":
    main()
