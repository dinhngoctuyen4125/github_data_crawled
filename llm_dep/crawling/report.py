"""Count crawled samples per cell, write the NEED / AFTER tables and export the O/U json files."""
import argparse
import collections
import json
from pathlib import Path

from .evolution import LIBS, Evolution
from .quota import PAIR, Quota, cells_of, parse_counts_md, table_row
from .run import load_jsonl


def rewrite_counts(before: Path, ev: Evolution, cell_text, header_text=None) -> str:
    """The BEFORE file with every U / O number replaced by cell_text((mapping_id, kind, version)),
    and every `dep → rep` line by header_text(path, line) when given. Line endings are kept."""
    text = before.read_text(encoding="utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    out_lines, cur, versions = [], None, None
    for line in text.split(eol):
        if m := PAIR.match(line):
            cur, versions = ev.by_deprecated.get(m.group(1)), None
            if header_text and cur is not None:
                line = header_text(cur, line)
        elif cur is not None and line.startswith("|"):
            cells = table_row(line)
            if cells[0] == "Version":
                versions = cells[1:]
            elif cells[0] in ("U", "O") and versions:
                vals = [cell_text((cur.mapping_id, cells[0], v)) for v in versions]
                line = f"| {cells[0]} | " + " | ".join(vals) + " |"
        out_lines.append(line)
    return eol.join(out_lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data")
    ap.add_argument("--crawl", default="data", help="root holding <lib>/crawl/samples.jsonl")
    ap.add_argument("--before", default="manual_reviews/API_MIGRATION_COUNTS_BEFORE.md")
    ap.add_argument("--out", default="manual_reviews/API_MIGRATION_COUNTS_NEED.md",
                    help="each cell = `crawled/needed` (needed = target - BEFORE, 0 when the API is absent)")
    ap.add_argument("--after", default="manual_reviews/API_MIGRATION_COUNTS_AFTER.md",
                    help="final counts: BEFORE + kept crawled samples (`-` when the API is absent), "
                         "each pair line with the largest U / O cell of BEFORE")
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--min-target", type=int, default=0, help="same value as the crawl (run.py --min-target)")
    ap.add_argument("--export", action="store_true", help="also write data/<lib>/{O,U}_crawled.json (kept samples)")
    ap.add_argument("--keep-extra", action="store_true",
                    help="keep samples of cells that BEFORE already filled (default: trim them)")
    args = ap.parse_args()

    ev = Evolution(Path(args.data))
    before = Path(args.before)
    quota = Quota(ev, parse_counts_md(before, ev), cap=args.cap, baseline="existing", min_target=args.min_target)

    samples, dropped = {}, collections.Counter()
    for lib in LIBS:
        kept = []
        for s in load_jsonl(Path(args.crawl) / lib / "crawl" / "samples.jsonl"):
            cells = cells_of(s["kind"], s["assignments"])
            # keep a sample (in crawl order) only while one of its cells still needs samples
            if args.keep_extra or any(quota.deficit(c) > 0 for c in cells):
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

    Path(args.out).write_text(rewrite_counts(before, ev, lambda c: f"{quota.filled[c]}/{quota.need(c)}"),
                              encoding="utf-8")
    print(f"wrote {args.out}; remaining deficit (cap={args.cap}, min-target={args.min_target}) "
          f"{quota.total_deficit()}")

    final = lambda c: str(quota.have(c)) if quota.feasible(c) else "-"
    with_max = lambda path, line: f"{line.rstrip()} (max BEFORE = {quota.max_before[path.mapping_id]})"
    Path(args.after).write_text(rewrite_counts(before, ev, final, with_max), encoding="utf-8")
    print(f"wrote {args.after}")

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
