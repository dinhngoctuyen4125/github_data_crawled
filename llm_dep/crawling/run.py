"""Crawl GitHub (via Sourcegraph) until every feasible (mapping, U/O, milestone) cell has as many
samples as the largest cell of its evolution path.

    python -m llm_dep.crawling.run --libs numpy --plan            # show deficits only
    python -m llm_dep.crawling.run --libs numpy pandas            # crawl
    python -m llm_dep.crawling.report                             # stats + export

Two assignment branches share one samples.jsonl and one quota:
  --assign dependency (default): versions from the repository's dependency declaration at the
      commit ([v1, v2) of the evolution path, both bounds required) + signature check;
  --assign signature: fallback for cells the first branch could not fill; versions = every
      milestone where the api_call binds to the API signature (like the original O/U data).
      Dependency queries are skipped; the dependency is still recorded when it resolves.
    python -m llm_dep.crawling.run --libs numpy --assign signature --cached-only   # re-use crawled files
    python -m llm_dep.crawling.run --libs numpy --assign signature                 # crawl more

Tokens (env or .env): SRC_ACCESS_TOKEN (Sourcegraph), GITHUB_TOKEN (tree listing + commit dates;
without it dependency files are probed at fixed paths and commit dates are unknown).
"""
import argparse
import collections
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Set, Tuple

from packaging.version import Version

from . import net
from .evolution import LIBS, Evolution
from .extract import extract_sites
from .github import GitHub
from .github_search import GitHubSearch, gh_queries
from .pypi import Releases
from .quota import Quota, parse_counts_md
from .signature import compatible, parse_call
from .sourcegraph import VENDORED, SearchUnavailable, Sourcegraph, api_queries, dependency_predicate, minor_groups
from .versions import VersionResolver, place


def func_key(function: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", "", function).encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class Crawler:
    def __init__(self, args):
        self.args = args
        self.data = Path(args.data)
        self.ev = Evolution(self.data)
        cache = net.DiskCache(Path(args.cache))
        extra = collections.defaultdict(list)
        for p in self.ev.paths.values():
            extra[p.library] += p.milestones
        self.releases = Releases(cache, extra)
        self.gh = GitHub(cache)
        self.sg = Sourcegraph(cache, min_interval=args.sg_interval, cached_only=args.cached_only)
        self.searcher = self.sg if args.source == "sourcegraph" else GitHubSearch(cache, min_interval=args.gh_interval, cached_only=args.cached_only)
        self.resolver = VersionResolver(self.gh, self.releases, use_commit_date=not args.no_commit_date)
        self.quota = Quota(self.ev, parse_counts_md(Path(args.before), self.ev), cap=args.cap, baseline=args.baseline)
        self.indexer_apis = {
            st.name for p in self.ev.paths.values() for ms in p.states.values() for st in ms.values()
            if st.call_syntax and st.call_syntax.get("kind") == "indexer"
        }
        self.seen_funcs: Set[str] = set()
        for lib in LIBS:            # never re-add functions already in the existing O/U sets
            for kind in "OU":
                f = self.data / lib / f"{kind}_modified.json"
                if f.exists():
                    self.seen_funcs |= {func_key(s["function"]) for s in json.load(open(f, encoding="utf-8"))}
        self.stats = collections.Counter()
        self.processed: Dict[str, Set[tuple]] = {}

    def out_dir(self, lib: str) -> Path:
        d = Path(self.args.out) / lib / "crawl"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_state(self, lib: str) -> Set[tuple]:
        """Load accepted samples (quota) and processed hits of `lib` once."""
        if lib in self.processed:
            return self.processed[lib]
        for s in load_jsonl(self.out_dir(lib) / "samples.jsonl"):
            self.seen_funcs.add(func_key(s["function"]))
            self.quota.add([(a["mapping_id"], s["kind"], a["milestone"]) for a in s["assignments"]])
        self.processed[lib] = set() if self.args.reprocess else \
            {tuple(x) for x in load_jsonl(self.progress_file(lib))}
        return self.processed[lib]

    def progress_file(self, lib: str) -> Path:
        """Each assignment branch keeps its own progress: files the dependency branch rejected
        must still be evaluated by the signature branch."""
        src = "" if self.args.source == "sourcegraph" else "github."
        branch = "" if self.args.assign == "dependency" else "signature."
        return self.out_dir(lib) / f"processed.{src}{branch}progress.jsonl"

    # ------------------------------------------------------------------ planning
    def plan(self, libs):
        for lib in libs:
            print(f"\n## {lib}")
            for p in sorted(self.ev.library_paths(lib), key=lambda p: p.mapping_id):
                need = {k: sum(self.quota.deficit(c) for c in self.quota.cells(p.mapping_id, k)) for k in "UO"}
                blocked = [ms for ms in p.milestones for k in "UO" if not self.quota.feasible((p.mapping_id, k, ms))]
                print(f"[{p.mapping_id}] {p.deprecated_api} -> {p.replacement_api}: target/cell={self.quota.target[p.mapping_id]}"
                      f" need U={need['U']} O={need['O']} infeasible cells={len(blocked)}")
            print(f"total deficit {lib}: {self.quota.total_deficit([p.mapping_id for p in self.ev.library_paths(lib)])}")

    # ------------------------------------------------------------------ crawling
    def crawl(self, lib: str):
        processed = self.load_state(lib)
        out = (self.out_dir(lib) / "samples.jsonl").open("a", encoding="utf-8")
        prog = self.progress_file(lib).open("a", encoding="utf-8")
        pool = ThreadPoolExecutor(max_workers=self.args.workers)
        try:
            for kind in self.args.kinds:
                for target in self.ev.targets(lib, kind):
                    paths = [p for p in self.ev.paths_for(kind, target) if p.library == lib]
                    if not self._open(paths, kind):
                        continue
                    before = collections.Counter(self.stats)
                    for qi, query in enumerate(self._queries(lib, kind, target, paths)):
                        if not self._open(paths, kind) or (self.args.max_queries and qi >= self.args.max_queries):
                            break
                        limit = self.args.targeted_limit if "repo:has.file" in query else self.args.search_limit
                        hits = [h for h in self.searcher.search(query, limit)
                                if (kind, target, h.repo, h.commit, h.path) not in processed]
                        logging.info("%s %s %s: %d new hits for %s", lib, kind, target, len(hits), query)
                        step = self.args.workers * 2
                        for b in range(0, len(hits), step):
                            if not self._open(paths, kind):
                                break
                            batch = hits[b:b + step]
                            # downloads + dependency resolution run in parallel, acceptance is sequential
                            for h, (status, sites, res) in zip(batch, pool.map(lambda h: self._analyze(lib, target, h), batch)):
                                if status == "ok":
                                    self._accept(kind, target, paths, h, sites, res, query, out)
                                else:
                                    self.stats[status] += 1
                                key = (kind, target, h.repo, h.commit, h.path)
                                processed.add(key)
                                prog.write(json.dumps(key) + "\n")
                            out.flush(); prog.flush()
                    logging.info("%s %s %s: %s", lib, kind, target, dict(self.stats - before))
        finally:
            pool.shutdown(wait=True)
            out.close(); prog.close()

    def _open(self, paths, kind) -> bool:
        return any(self.quota.open_cells(p.mapping_id, kind) for p in paths)

    def _queries(self, lib, kind, target, paths):
        """Dependency-targeted queries for open cells first (oldest first), then broad queries."""
        method_only = self.args.infer_types and lib == "pandas"
        if self.args.source == "github":            # no repo:has.file on GitHub: API-name queries only
            return gh_queries(target, method_only=method_only)
        base = api_queries(target, method_only=method_only)
        targeted, seen = [], set()
        releases = self.releases.versions(lib)
        for p in paths:
            for (_, _, ms) in self.quota.open_cells(p.mapping_id, kind):
                i = p.milestones.index(ms)
                lo = Version(ms)
                hi = Version(p.milestones[i + 1]) if i + 1 < len(p.milestones) else None
                in_range = [v for v in releases if v >= lo and (hi is None or v < hi)]
                for minor in minor_groups(in_range):
                    if minor in seen:
                        continue
                    seen.add(minor)
                    targeted.append((Version(minor), f"{dependency_predicate(lib, minor)} {base[-1]}"))
        uniq = [q for _, q in sorted(targeted)]
        # The signature branch does not use the dependency, so targeting repositories by it is pointless.
        skip = self.args.no_targeted or self.args.assign == "signature"
        return ([] if skip else uniq) + base

    def _analyze(self, lib, target, hit) -> Tuple[str, list, object]:
        """Thread-safe part: download, extract call sites, resolve the dependency version."""
        try:
            if not self.args.include_vendored and VENDORED.search(hit.path):
                return "vendored_path", [], None
            code = self.gh.raw(hit.repo, hit.commit, hit.path, fallback=True)
            if code is None:
                return "download_failed", [], None
            sites = [s for s in extract_sites(code, [target], self.indexer_apis & {target},
                                                infer_types=self.args.infer_types and lib == "pandas") if s["matched api"] == target]
            if not sites:
                return "no_call_site", [], None
            sites = [s for s in sites if func_key(s["function"]) not in self.seen_funcs]
            if not sites:
                return "duplicate", [], None
            res = self.resolver.resolve(lib, hit.repo, hit.commit, hit.path)
            if res.status != "ok" and self.args.assign == "dependency":
                return f"dep_{res.status}", [], res
            return "ok", sites, res
        except Exception:
            logging.exception("failed on %s@%s:%s", hit.repo, hit.commit, hit.path)
            return "error", [], None

    def _accept(self, kind, target, paths, hit, sites, res, query, out):
        for site in sites:
            fk = func_key(site["function"])
            if fk in self.seen_funcs:
                self.stats["duplicate"] += 1
                continue
            if self.args.assign == "signature":
                assignments, reasons = self._assign_by_signature(kind, target, paths, site)
            else:
                assignments, reasons = self._assign_by_dependency(kind, target, paths, site, res)
            if not assignments:
                self.stats[f"rejected_{collections.Counter(reasons).most_common(1)[0][0]}"] += 1
                continue
            cells = [(a["mapping_id"], kind, a["milestone"]) for a in assignments]
            if not any(self.quota.deficit(c) > 0 for c in cells):
                self.stats["cell_full"] += 1
                continue
            self.quota.add(cells)
            self.seen_funcs.add(fk)
            self.stats[f"accepted_{kind}"] += 1
            out.write(json.dumps(self._sample(kind, target, paths, site, hit, res, assignments, query)) + "\n")

    def _place(self, res, p, target):
        return place(res, p, self.args.mode, api=target, signature_only=self.args.unchanged == "signature",
                     require_bounded=not self.args.allow_unbounded)

    def _assign_by_dependency(self, kind, target, paths, site, res):
        """Branch 1: milestones from the dependency version range, then a signature check at each."""
        assignments, reasons = [], []
        for p in paths:
            pl = self._place(res, p, target)
            if pl.status != "ok":
                reasons.append(pl.status)
                continue
            checks = [compatible(site["api_call"], target, p.state(ms, target)) for ms in pl.milestones]
            if self.args.allow_undecidable:
                checks = [p.feasible(kind, ms) if ok is None else ok for ms, ok in zip(pl.milestones, checks)]
            if all(ok is True for ok in checks):
                assignments += [{"mapping_id": p.mapping_id, "milestone": ms, "version_range": pl.version_range}
                                for ms in pl.milestones]
            else:
                reasons.append("signature_undecidable" if None in checks else "signature_mismatch")
        return assignments, reasons

    def _assign_by_signature(self, kind, target, paths, site):
        """Branch 2: every milestone at which the call binds to the API signature (the API must
        exist there: removed / not yet introduced milestones never bind). Calls with `*args` /
        `**kwargs` bind unless their explicit part fails, as in the original O/U data."""
        assignments, reasons = [], []
        for p in paths:
            checks = {ms: compatible(site["api_call"], target, p.state(ms, target), lenient_starred=True)
                      for ms in p.milestones}
            if None in checks.values():           # unparsable call
                reasons.append("signature_undecidable")
                continue
            ok = [ms for ms, c in checks.items() if c and p.feasible(kind, ms)]
            if not ok:
                reasons.append("signature_mismatch")
                continue
            assignments += [{"mapping_id": p.mapping_id, "milestone": ms, "version_range": None} for ms in ok]
        return assignments, reasons

    def _dependency_check(self, target, paths, res, assignments) -> Dict:
        """For signature-branch samples: does the dependency (when it resolves) agree?"""
        if res is None or res.status != "ok":
            return {"verified": False, "reason": f"dep_{res.status if res else 'none'}", "milestones": []}
        placed = []
        for p in paths:
            pl = self._place(res, p, target)
            if pl.status != "ok":
                return {"verified": False, "reason": pl.status, "milestones": []}
            placed += [(p.mapping_id, ms) for ms in pl.milestones]
        assigned = {(a["mapping_id"], a["milestone"]) for a in assignments}
        agree = bool(placed) and set(placed) <= assigned
        return {"verified": agree, "reason": "ok" if agree else "signature_disagrees",
                "milestones": sorted({ms for _, ms in placed}, key=Version)}

    def _sample(self, kind, target, paths, site, hit, res, assignments, query) -> Dict:
        if kind == "O":
            deprecated, replacement, expected = [target], paths[0].replacement_api, paths[0].replacement_api
        else:
            deprecated, replacement, expected = sorted(p.deprecated_api for p in paths), target, site["call name"]
        if self.args.assign == "signature":
            dep_check = self._dependency_check(target, paths, res, assignments)
        else:
            dep_check = {"verified": True, "reason": "ok", "milestones": sorted({a["milestone"] for a in assignments}, key=Version)}
        ok_res = res is not None and res.status == "ok"
        return {
            "function": site["function"],
            "source": "sourcegraph" if self.args.source == "sourcegraph" else "github_search",
            "reference dict": site["reference dict"],
            "alias dict": site["alias dict"],
            "probing input": site["probing input"],
            "deprecated api": deprecated,
            "replacement api": replacement,
            "expected call": expected,
            "category": "outdated" if kind == "O" else "up-to-dated",
            "reference": site["reference"],
            "api_call": site["api_call"],
            "type_inference": site.get("type inference"),
            "kind": kind,
            "assignments": assignments,
            "versions": sorted({a["milestone"] for a in assignments}, key=Version),
            "repository": hit.repo,
            "commit": hit.commit,
            "path": hit.path,
            "repo stars": hit.stars if hit.stars >= 0 else self.gh.stars(hit.repo),
            "dependency": {"status": res.status if res else None,
                           "files": res.files if res else [], "specs": res.specs if res else [],
                           "commit_date": res.commit_date if res else None,
                           "candidates": [res.candidates[0], res.candidates[-1]] if ok_res and res.candidates else []},
            "assigned_by": self.args.assign,
            "starred_call": bool((c := parse_call(site["api_call"], allow_starred=True)) and c.starred),
            "dependency_verified": dep_check["verified"],
            "dependency_check": dep_check,
            "query": query,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--libs", nargs="+", default=LIBS, choices=LIBS)
    ap.add_argument("--kinds", nargs="+", default=["O", "U"], choices=["O", "U"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--before", default="manual_reviews/API_MIGRATION_COUNTS_BEFORE.md")
    ap.add_argument("--out", default="data", help="crawl outputs go to <out>/<lib>/crawl/")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--mode", default="strict", choices=["strict", "latest"],
                    help="strict: all versions allowed by the dependency spec must lie in one [v1,v2); "
                         "latest: use the newest allowed version at commit time")
    ap.add_argument("--cap", type=int, default=None, help="upper bound for the per-cell target")
    ap.add_argument("--baseline", default="existing", choices=["none", "existing"],
                    help="existing: count the BEFORE numbers as already filled")
    ap.add_argument("--search-limit", type=int, default=2000, help="max results of a broad query")
    ap.add_argument("--targeted-limit", type=int, default=500, help="max results of a dependency-targeted query")
    ap.add_argument("--no-targeted", action="store_true", help="skip dependency-targeted queries")
    ap.add_argument("--no-commit-date", action="store_true", help="do not filter releases by commit date")
    ap.add_argument("--allow-undecidable", action="store_true", help="accept calls with *args/**kwargs")
    ap.add_argument("--include-vendored", action="store_true", help="keep files under site-packages/, venv/ ...")
    ap.add_argument("--wait-on-block", type=int, default=0,
                    help="when Sourcegraph blocks searches, sleep this many minutes and resume (0 = exit)")
    ap.add_argument("--sg-interval", type=float, default=5.0, help="min seconds between two Sourcegraph searches")
    ap.add_argument("--source", default="sourcegraph", choices=["sourcegraph", "github"],
                    help="search engine: sourcegraph (default) or GitHub code search (needs GITHUB_TOKEN, "
                         "API-name queries only, ~10 searches/min)")
    ap.add_argument("--gh-interval", type=float, default=6.5, help="min seconds between two GitHub code searches")
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads / dependency resolutions")
    ap.add_argument("--max-queries", type=int, default=0, help="max queries per target API (0 = all)")
    ap.add_argument("--infer-types", action="store_true",
                    help="pandas: also infer DataFrame/Series/Styler receivers from pd.read_*, pd.merge, "
                         "df.copy()... (see pandas_types.py)")
    ap.add_argument("--allow-unbounded", action="store_true",
                    help="also accept dependency declarations without both a lower and an upper bound "
                         "(e.g. `pandas>=0.24`, bare `pandas`), relying on the commit date")
    ap.add_argument("--unchanged", default="any", choices=["any", "signature"],
                    help="a version range may span milestones where the called API has no change: "
                         "any = no recorded change at all; signature = no signature/lifecycle change")
    ap.add_argument("--assign", default="dependency", choices=["dependency", "signature"],
                    help="dependency: milestones from the dependency declaration (default); "
                         "signature: fallback branch, milestones = every milestone where the call binds "
                         "to the signature (no dependency queries; dependency only recorded)")
    ap.add_argument("--cached-only", action="store_true", help="only use searches already in the cache")
    ap.add_argument("--reprocess", action="store_true",
                    help="re-evaluate hits already processed (uses cached searches/files, e.g. after a rule change)")
    ap.add_argument("--plan", action="store_true", help="only print deficits")
    args = ap.parse_args()

    if hasattr(sys.stderr, "reconfigure"):      # Windows consoles default to cp1252
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    net.load_dotenv()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(Path(args.out) / "crawl.log", encoding="utf-8")])
    c = Crawler(args)
    for lib in args.libs:
        c.load_state(lib)
    if args.plan:
        c.plan(args.libs)
        return
    if args.source == "sourcegraph" and not c.sg.token:
        logging.warning("SRC_ACCESS_TOKEN not set: Sourcegraph may reject or throttle anonymous searches")
    if not c.gh.token:
        logging.warning("GITHUB_TOKEN not set: dependency files are probed at fixed paths, commit dates unknown")
    for lib in args.libs:
        while True:
            try:
                c.crawl(lib)
                break
            except SearchUnavailable as e:
                logging.error("%s", e)
                if args.wait_on_block > 0:
                    logging.error("Nguồn tìm kiếm (%s) đang từ chối truy vấn. Tạm nghỉ %d phút rồi tự chạy tiếp "
                                  "(không bỏ qua truy vấn nào).", args.source, args.wait_on_block)
                    time.sleep(args.wait_on_block * 60)
                    continue
                logging.error("Nguồn tìm kiếm đang từ chối truy vấn (giới hạn tần suất / chống bot). Đã dừng, không bỏ qua "
                              "truy vấn nào. Chờ một lúc (vd. 1-2 giờ) rồi chạy lại đúng lệnh này để tiếp tục, "
                              "hoặc thêm --wait-on-block 60 để tự chờ.")
                raise SystemExit(2)
        logging.info("%s done: %s", lib, dict(c.stats))


if __name__ == "__main__":
    main()
