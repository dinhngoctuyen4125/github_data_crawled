"""Per-cell quotas: target = max count on the evolution path (from the BEFORE statistics),
cells whose target API is absent/removed at that milestone are infeasible (quota 0)."""
import collections
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from .evolution import Evolution

Cell = Tuple[int, str, str]          # (mapping_id, "U"/"O", milestone)


def parse_counts_md(md_path: Path, ev: Evolution) -> Dict[int, Dict[str, Dict[str, int]]]:
    """mapping_id -> kind -> milestone -> count, from API_MIGRATION_COUNTS_BEFORE.md."""
    text = Path(md_path).read_text(encoding="utf-8")
    parts = re.split(r"^(\S+) → (\S+)\s*$", text, flags=re.M)[1:]
    out = {}
    for i in range(0, len(parts), 3):
        dep, rep, body = parts[i:i + 3]
        path = ev.by_deprecated.get(dep)
        if path is None or path.replacement_api != rep:
            raise ValueError(f"unknown pair in {md_path}: {dep} -> {rep}")
        rows = {}
        for line in body.strip().splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] in ("Version", "U", "O"):
                rows[cells[0]] = cells[1:]
        out[path.mapping_id] = {k: dict(zip(rows["Version"], map(int, rows[k]))) for k in ("U", "O")}
    return out


class Quota:
    def __init__(self, ev: Evolution, before: Dict[int, Dict[str, Dict[str, int]]],
                 cap: Optional[int] = None, baseline: str = "none"):
        self.ev = ev
        self.before = before
        self.baseline = baseline
        self.target: Dict[int, int] = {}
        for mid, kinds in before.items():
            t = max(max(c.values(), default=0) for c in kinds.values())
            self.target[mid] = min(t, cap) if cap else t
        self.filled: Dict[Cell, int] = collections.Counter()

    def feasible(self, cell: Cell) -> bool:
        mid, kind, ms = cell
        return self.ev.paths[mid].feasible(kind, ms)

    def have(self, cell: Cell) -> int:
        base = self.before[cell[0]][cell[1]].get(cell[2], 0) if self.baseline == "existing" else 0
        return base + self.filled[cell]

    def deficit(self, cell: Cell) -> int:
        if not self.feasible(cell):
            return 0
        return max(0, self.target[cell[0]] - self.have(cell))

    def add(self, cells: Iterable[Cell]):
        for c in cells:
            self.filled[c] += 1

    def cells(self, mid: int, kind: str):
        return [(mid, kind, ms) for ms in self.ev.paths[mid].milestones]

    def open_cells(self, mid: int, kind: str):
        return [c for c in self.cells(mid, kind) if self.deficit(c) > 0]

    def total_deficit(self, mids=None, kinds=("U", "O")) -> int:
        mids = mids or list(self.target)
        return sum(self.deficit(c) for m in mids for k in kinds for c in self.cells(m, k))
