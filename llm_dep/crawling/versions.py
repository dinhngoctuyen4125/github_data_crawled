"""Resolve the library version a file was written against, and place it on an evolution path."""
import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from packaging.version import Version

from . import deps
from .evolution import PACKAGES, Path_
from .github import GitHub
from .pypi import Releases


@dataclass
class Resolution:
    status: str                          # ok | no_dependency | unsatisfiable
    library: str
    files: List[str] = field(default_factory=list)
    specs: List[str] = field(default_factory=list)
    candidates: List[str] = field(default_factory=list)   # versions allowed by the declaration
    commit_date: Optional[str] = None
    bounded: bool = False                # the declaration has both a lower and an upper bound

    def to_json(self):
        return asdict(self)


@dataclass
class Placement:
    status: str                  # ok | ambiguous | before_path
    milestone: Optional[str]     # first milestone v1 (kept for compatibility)
    version_range: List[str]     # [min, max] of candidate versions used
    milestones: List[str] = field(default_factory=list)   # every milestone the declaration spans


class VersionResolver:
    def __init__(self, github: GitHub, releases: Releases, use_commit_date: bool = True):
        self.gh = github
        self.releases = releases
        self.use_commit_date = use_commit_date

    def resolve(self, lib: str, repo: str, commit: str, source_path: str) -> Resolution:
        key = f"res2:{lib}:{repo}@{commit}:{source_path}"
        cached = self.gh.cache.get_json(key)
        if cached is not None:
            return Resolution(**cached)
        res = self._resolve(lib, repo, commit, source_path)
        self.gh.cache.put_json(key, res.to_json())
        return res

    def _resolve(self, lib, repo, commit, source_path) -> Resolution:
        tree = self.gh.tree(repo, commit)
        date = self.gh.commit_date(repo, commit) if self.use_commit_date else None
        releases = self.releases.versions(lib, before=date)
        for _, files in deps.candidate_files(source_path, tree).items():
            specs = []
            for f in files:
                specs += deps.parse_file(f, self.gh.raw(repo, commit, f), PACKAGES[lib])
            if not specs:
                continue
            locked = [s for s in specs if s.exact and deps.file_kind(s.file) in deps.LOCK_FILES]
            use = locked or specs
            cand: Optional[set] = None
            for s in use:
                c = s.candidates(releases)
                cand = c if cand is None else cand & c
            bounds = [s.bounds() for s in use]   # the intersection is bounded if some spec bounds each side
            return Resolution(
                "ok" if cand else "unsatisfiable", lib,
                files=sorted({s.file for s in use}), specs=[s.raw for s in use],
                candidates=[str(v) for v in sorted(cand or [])],
                commit_date=date.isoformat() if date else None,
                bounded=any(lo for lo, _ in bounds) and any(up for _, up in bounds),
            )
        return Resolution("no_dependency", lib, commit_date=date.isoformat() if date else None)


def place(res: Resolution, path: Path_, mode: str = "strict", api: Optional[str] = None,
          signature_only: bool = False, require_bounded: bool = True) -> Placement:
    """strict: the allowed versions must fall in one [v1, v2) interval, or span several intervals
    between which `api` itself has no recorded change (the milestones only exist because the other
    API of the pair changed); the sample then belongs to every spanned milestone.
    latest: use the newest allowed version (what pip would pick at commit time)."""
    if res.status != "ok":
        return Placement(res.status, None, [])
    if require_bounded and not res.bounded:     # e.g. `pandas>=0.24` or bare `pandas`
        return Placement("unbounded", None, [])
    vers = sorted(Version(v) for v in res.candidates)
    rng = [str(vers[0]), str(vers[-1])]
    if mode == "latest":
        ms = path.milestone_for(vers[-1])
        return Placement("ok" if ms else "before_path", ms, rng, [ms] if ms else [])
    spanned = {path.milestone_for(v) for v in vers}
    if None in spanned:            # part of the range lies before the path: API state unknown there
        return Placement("before_path" if len(spanned) == 1 else "ambiguous", None, rng)
    ordered = sorted(spanned, key=Version)
    if len(ordered) > 1 and (api is None or not path.unchanged_between(api, ordered, signature_only)):
        return Placement("ambiguous", None, rng)
    return Placement("ok", ordered[0], rng, ordered)
