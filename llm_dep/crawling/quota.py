"""Per-cell sample quotas, from the BEFORE counts table."""
import collections
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .evolution import Evolution

Cell = Tuple[int, str, str]          # (mapping_id, "U"/"O", milestone)
PAIR = re.compile(r"^(\S+) → (\S+)\s*$", re.M)     # `dep → rep` line heading each table


def table_row(line: str) -> List[str]:
    """`| U | 1 | 2 |` -> ["U", "1", "2"]."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def cells_of(kind: str, assignments: List[dict]) -> List[Cell]:
    return [(a["mapping_id"], kind, a["milestone"]) for a in assignments]


def parse_counts_md(md_path: Path, ev: Evolution) -> Dict[int, Dict[str, Dict[str, int]]]:
    """mapping_id -> kind -> milestone -> count, from API_MIGRATION_COUNTS_BEFORE.md."""
    parts = PAIR.split(Path(md_path).read_text(encoding="utf-8"))[1:]
    out = {}
    for i in range(0, len(parts), 3):
        dep, rep, body = parts[i:i + 3]
        path = ev.by_deprecated.get(dep)
        if path is None or path.replacement_api != rep:
            raise ValueError(f"unknown pair in {md_path}: {dep} -> {rep}")
        rows = {}
        for line in body.strip().splitlines():
            cells = table_row(line)
            if cells and cells[0] in ("Version", "U", "O"):
                rows[cells[0]] = cells[1:]
        out[path.mapping_id] = {k: dict(zip(rows["Version"], map(int, rows[k]))) for k in ("U", "O")}
    return out


class Quota:
    """Target of a mapping = max(largest U / O cell of BEFORE, min_target), then at most cap; the same
    target for every cell of the mapping. Cells whose API does not exist at that milestone are
    infeasible (quota 0)."""

    def __init__(self, ev: Evolution, before: Dict[int, Dict[str, Dict[str, int]]],
                 cap: Optional[int] = None, baseline: str = "none", min_target: int = 0):
        self.ev = ev
        self.before = before
        self.baseline = baseline
        self.max_before: Dict[int, int] = {}
        self.target: Dict[int, int] = {}
        for mid, kinds in before.items():
            self.max_before[mid] = max(max(c.values(), default=0) for c in kinds.values())
            t = max(self.max_before[mid], min_target)
            self.target[mid] = min(t, cap) if cap else t
        self.filled: Dict[Cell, int] = collections.Counter()

    def feasible(self, cell: Cell) -> bool:
        mid, kind, ms = cell
        return self.ev.paths[mid].feasible(kind, ms)

    def have(self, cell: Cell) -> int:
        base = self.before[cell[0]][cell[1]].get(cell[2], 0) if self.baseline == "existing" else 0
        return base + self.filled[cell]

    def need(self, cell: Cell) -> int:
        """Samples to crawl on top of BEFORE to reach the target (0 when infeasible or already reached)."""
        if not self.feasible(cell):
            return 0
        return max(0, self.target[cell[0]] - self.before[cell[0]][cell[1]].get(cell[2], 0))

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
