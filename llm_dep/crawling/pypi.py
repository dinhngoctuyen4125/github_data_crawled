"""Release history of each library from PyPI (versions + first upload time)."""
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from packaging.version import Version

from . import net
from .evolution import parse_version, pypi_name


class Releases:
    def __init__(self, cache: net.DiskCache, extra_versions: Dict[str, List[str]] = None):
        self.cache = cache
        self.extra = extra_versions or {}
        self._mem: Dict[str, Dict[Version, Optional[dt.datetime]]] = {}

    def get(self, lib: str) -> Dict[Version, Optional[dt.datetime]]:
        """Final (non pre/dev) releases -> upload date. Milestone versions not on PyPI (e.g. torch
        0.4.1) are added with an unknown date."""
        if lib in self._mem:
            return self._mem[lib]
        name = pypi_name(lib)
        data = self.cache.get_json(f"pypi:{name}")
        if data is None:
            r = net.get(f"https://pypi.org/pypi/{name}/json", ok_404=False)
            if r is None:
                raise RuntimeError(f"cannot fetch PyPI releases for {name}")
            raw = r.json()["releases"]
            data = {}
            for v, files in raw.items():
                times = [f["upload_time_iso_8601"] for f in files if f.get("upload_time_iso_8601")]
                yanked = files and all(f.get("yanked") for f in files)
                if not yanked:
                    data[v] = min(times) if times else None
            self.cache.put_json(f"pypi:{name}", data)
        out: Dict[Version, Optional[dt.datetime]] = {}
        for v, t in data.items():
            pv = parse_version(v)
            if pv is None or pv.is_prerelease or pv.is_devrelease:
                continue
            out[pv] = dt.datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
        for v in self.extra.get(lib, []):
            pv = parse_version(v)
            if pv is not None:
                out.setdefault(pv, None)
        self._mem[lib] = out
        return out

    def versions(self, lib: str, before: Optional[dt.datetime] = None) -> List[Version]:
        rel = self.get(lib)
        return sorted(v for v, t in rel.items() if before is None or t is None or t <= before)
