"""Sourcegraph streaming search: API-usage queries, optionally restricted to repositories whose
dependency declarations mention a given library version (`repo:has.file(content:...)`)."""
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Iterable, List

from packaging.version import Version

from . import net

STREAM_URL = "https://sourcegraph.com/.api/search/stream"

# Common import aliases of each top-level module.
MODULE_ALIASES = {"tensorflow": ["tf"], "numpy": ["np"], "pandas": ["pd"], "scipy": ["sp"], "seaborn": ["sns"]}
# Regex for the distribution names in dependency files (no groups: used inside a predicate).
PKG_REGEX = {
    "numpy": "numpy", "pandas": "pandas", "scikit-learn": r"s\w*-?learn", "scipy": "scipy",
    "seaborn": "seaborn", "tensorflow": r"tensorflow[\w-]*", "pytorch": "torch", "transformers": "transformers",
}


# Copies of installed packages committed into repositories are library code, not usages.
EXCLUDE = r"-file:site-packages/ -file:dist-packages/"
VENDORED = re.compile(r"(^|/)(site-packages|dist-packages|\.?venv(?:[-_.\d][^/]*)?|virtualenvs?|node_modules|\.Trash[^/]*)/|(^|/)[^/]*env[^/]*/lib/python")


@dataclass(frozen=True)
class Hit:
    repo: str          # owner/name
    commit: str
    path: str
    stars: int


def api_queries(api: str, method_only: bool = False) -> List[str]:
    """Keyword queries for calls of `api` (fixes the alias lookup of search_sourcegraph.py).
    method_only: for `pkg.Class.method`, also search files that mention only the package and
    `.method(` (receivers typed by inference, e.g. `df = pd.read_csv(...)`, never name the class)."""
    parts = api.split(".")
    top = parts[0]
    names = {f"{api}("} | {f"{alias}{api[len(top):]}(" for alias in MODULE_ALIASES.get(top, [])}
    queries = [" OR ".join(sorted(names))]
    if len(parts) >= 2:
        if parts[-1][:1].isupper():                           # class: module + Class(
            kw = [".".join(parts[:-1]), f"{parts[-1]}("]
        elif len(parts) >= 3 and parts[-2][:1].isupper():     # method: module Class .method(
            kw = [".".join(parts[:-2]), parts[-2], f".{parts[-1]}("]
        else:                                                  # function: module .func(
            kw = [".".join(parts[:-1]), f".{parts[-1]}("]
        queries.append(" ".join(kw))
        if method_only and len(parts) >= 3 and parts[-2][:1].isupper():
            queries.append(f"{top} .{parts[-1]}(")
    return queries


def minor_groups(versions: Iterable[Version]) -> List[str]:
    return sorted({f"{v.major}.{v.minor}" for v in versions}, key=Version)


def dependency_predicate(lib: str, minor: str) -> str:
    """repo:has.file predicate matching e.g. `numpy==1.12.1`, `numpy>=1.12`, `numpy = "^1.12"`."""
    ver = re.escape(minor)
    return rf"repo:has.file(content:{PKG_REGEX[lib]}.?\s*[=~^<>!]+\s*.?{ver}[^0-9])"


def parse_sse(text: str):
    """Yield (event, data) of a text/event-stream body. Lines are split on '\\n' only: JSON
    payloads may legally contain U+2028 etc., which str.splitlines() would split on."""
    event, buf = None, []
    for line in text.split("\n"):
        line = line[:-1] if line.endswith("\r") else line
        if line == "":
            if buf:
                yield event, "\n".join(buf)
            event, buf = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[6:] if line.startswith("data: ") else line[5:])
    if buf:
        yield event, "\n".join(buf)


class SearchUnavailable(RuntimeError):
    """Sourcegraph kept refusing searches (throttling / bot protection): stop instead of skipping."""


class Sourcegraph:
    def __init__(self, cache: net.DiskCache, min_interval: float = 5.0, cached_only: bool = False,
                 notebooks: bool = False):
        self.cache = cache
        self.cached_only = cached_only       # never send new searches (re-evaluate cached ones only)
        self.lang = r"file:\.ipynb$" if notebooks else "lang:python"     # notebooks: search .ipynb files
        self.token = os.environ.get("SRC_ACCESS_TOKEN") or os.environ.get("SOURCEGRAPH_TOKEN")
        self.min_interval = min_interval     # seconds between two uncached searches
        self._last = 0.0

    def search(self, query: str, count: int) -> List[Hit]:
        full = f"context:global {self.lang} type:file select:file count:{count} {EXCLUDE} {query}"
        key = f"sg:{full}"
        cached = self.cache.get_json(key)
        if cached is not None:
            return [Hit(**h) for h in cached]
        if self.cached_only:
            return []
        headers = {"Accept": "text/event-stream"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        wait = self._last + self.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        # Sourcegraph outages / throttling can last minutes: retry for up to ~15 minutes.
        r = net.get(STREAM_URL, headers=headers, timeout=600, ok_404=False, retries=9, max_delay=300,
                    params={"q": full, "v": "V3", "t": "keyword", "display": "-1", "cm": "t", "max-line-len": "0"})
        self._last = time.time()
        if r is None or "text/event-stream" not in r.headers.get("Content-Type", ""):
            raise SearchUnavailable(f"sourcegraph search unavailable: {full}")
        hits = {}
        for event, data in parse_sse(r.content.decode("utf-8", errors="replace")):
            if event == "matches":
                try:
                    matches = json.loads(data)
                except json.JSONDecodeError as e:
                    logging.warning("skipping malformed sourcegraph event (%s) for %r", e, full)
                    continue
                for m in matches:
                    repo = m.get("repository", "")
                    if not repo.startswith("github.com/") or "commit" not in m or "path" not in m:
                        continue
                    h = Hit(repo[len("github.com/"):], m["commit"], m["path"], int(m.get("repoStars") or 0))
                    hits[(h.repo, h.commit, h.path)] = h
            elif event == "alert":
                logging.warning("sourcegraph alert for %r: %s", full, data[:300])
        out = sorted(hits.values(), key=lambda h: -h.stars)
        self.cache.put_json(key, [h.__dict__ for h in out])
        return out
