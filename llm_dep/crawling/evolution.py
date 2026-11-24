"""Mappings and migration evolution paths, with [v1, v2) milestone lookup."""
import bisect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from packaging.version import InvalidVersion, Version

LIBS = ["numpy", "pandas", "scikit-learn", "scipy", "seaborn", "tensorflow", "pytorch", "transformers"]

# PyPI / conda distribution names that provide each library.
PACKAGES = {
    "numpy": ["numpy"],
    "pandas": ["pandas"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "scipy": ["scipy"],
    "seaborn": ["seaborn"],
    "tensorflow": ["tensorflow", "tensorflow-gpu", "tensorflow-cpu", "tensorflow-macos"],
    "pytorch": ["torch", "pytorch"],
    "transformers": ["transformers"],
}
# Distribution whose PyPI release list is used for each library.
PYPI_NAME = {"scikit-learn": "scikit-learn", "pytorch": "torch"}

USABLE = ("active", "deprecated")
# Change types that affect whether a call is valid (signature or lifecycle); the others
# (implementation, annotations, binding/source moves) do not.
CALL_AFFECTING = {"parameter_added", "parameter_removed", "parameter_rename", "parameter_kind_changed",
                  "parameter_order_changed", "default_changed", "call_syntax_changed",
                  "introduced", "deprecated", "removed"}


def pypi_name(lib: str) -> str:
    return PYPI_NAME.get(lib, lib)


def parse_version(v) -> Optional[Version]:
    try:
        return Version(str(v))
    except InvalidVersion:
        return None


@dataclass
class ApiState:
    name: str
    status: str
    signatures: List[str]
    call_syntax: Optional[dict]


@dataclass
class Path_:
    mapping_id: int
    library: str
    deprecated_api: str
    replacement_api: str
    deprecated_version: Optional[str]
    milestones: List[str]                       # version strings as written in the evolution file
    states: Dict[str, Dict[str, ApiState]]      # milestone -> api name -> state
    changed: Dict[str, Set[str]] = field(default_factory=dict)   # milestone -> APIs with a recorded change
    call_changed: Dict[str, Set[str]] = field(default_factory=dict)   # same, signature/lifecycle changes only
    _keys: List[Version] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._keys = [Version(v) for v in self.milestones]

    def milestone_for(self, version) -> Optional[str]:
        """Milestone v1 such that v1 <= version < v2 (last interval is [vn, inf)); None before v1."""
        v = version if isinstance(version, Version) else parse_version(version)
        if v is None:
            return None
        v = Version(v.public)  # drop local tags such as +cu118
        i = bisect.bisect_right(self._keys, v) - 1
        return self.milestones[i] if i >= 0 else None

    def state(self, milestone: str, api: str) -> Optional[ApiState]:
        return self.states.get(milestone, {}).get(api)

    def unchanged_between(self, api: str, milestones: List[str], signature_only: bool = False) -> bool:
        """True when `api` has no recorded change at any of `milestones` after the first one,
        i.e. those milestones exist only because the other API of the pair changed.
        signature_only: ignore changes that do not affect calls (implementation, annotations...)."""
        ordered = sorted(milestones, key=Version)
        table = self.call_changed if signature_only else self.changed
        return all(api not in table.get(m, set()) for m in ordered[1:])

    def target_api(self, kind: str) -> str:
        return self.deprecated_api if kind == "O" else self.replacement_api

    def feasible(self, kind: str, milestone: str) -> bool:
        st = self.state(milestone, self.target_api(kind))
        return st is not None and st.status in USABLE


class Evolution:
    def __init__(self, data_dir: Path):
        data_dir = Path(data_dir)
        mapping = json.load(open(data_dir / "api_mapping_versions.json", encoding="utf-8"))
        self.paths: Dict[int, Path_] = {}
        for lib in LIBS:
            for e in json.load(open(data_dir / lib / "migration_evolution.json", encoding="utf-8")):
                m = next(x for x in mapping if x["id"] == e["mapping_id"])
                states = {
                    ms["version"]: {
                        s["name"]: ApiState(s["name"], s["status"], s.get("signatures") or [], s.get("call_syntax"))
                        for s in ms["api_states"]
                    }
                    for ms in e["milestones"]
                }
                self.paths[m["id"]] = Path_(
                    m["id"], lib, m["deprecated_api"], m["replacement_api"], m["deprecated_version"],
                    [ms["version"] for ms in e["milestones"]], states,
                    {ms["version"]: {c.get("api") for c in ms.get("changes", [])} for ms in e["milestones"]},
                    {ms["version"]: {c.get("api") for c in ms.get("changes", []) if c.get("type") in CALL_AFFECTING}
                     for ms in e["milestones"]},
                )
        self.by_deprecated = {p.deprecated_api: p for p in self.paths.values()}
        self.by_replacement: Dict[str, List[Path_]] = {}
        for p in self.paths.values():
            self.by_replacement.setdefault(p.replacement_api, []).append(p)

    def library_paths(self, lib: str) -> List[Path_]:
        return [p for p in self.paths.values() if p.library == lib]

    def paths_for(self, kind: str, api: str) -> List[Path_]:
        """Paths whose O (deprecated) or U (replacement) target is `api`."""
        if kind == "O":
            p = self.by_deprecated.get(api)
            return [p] if p else []
        return self.by_replacement.get(api, [])

    def targets(self, lib: str, kind: str) -> List[str]:
        return sorted({p.target_api(kind) for p in self.library_paths(lib)})
