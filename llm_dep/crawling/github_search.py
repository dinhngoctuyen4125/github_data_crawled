"""GitHub Code Search (REST `/search/code`) as a second search source next to Sourcegraph.

GitHub indexes far more public repositories than sourcegraph.com, but:
  * at most 1000 results per query (10 pages x 100): larger result sets are split by file size
    (`size:lo..hi`, bisected until every slice has <= 1000 results);
  * ~10 searches per minute with a token: requests are spaced by `min_interval` seconds and
    rate-limit answers (403/429, Retry-After, X-RateLimit-Reset) are waited out;
  * no regex / `repo:has.file(...)`, punctuation such as `(` is ignored: queries are by API name only;
  * only the default branch is indexed (html_url carries the commit sha of that branch).
Every result page and every finished query are cached, so interrupted searches resume.
A size slice that GitHub keeps answering with 5xx/408 (search timeout on very common terms) is
split further; a slice that still fails when it is MIN_SLICE bytes wide, or that gets an unexpected
4xx, is skipped with a warning, and the query result is then not frozen in the cache, so a later
run retries the skipped slices.
"""
import logging
import math
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

from . import net
from .sourcegraph import MODULE_ALIASES, Hit, SearchUnavailable

SEARCH_URL = "https://api.github.com/search/code"
PER_PAGE = 100
MAX_RESULTS = 1000            # GitHub serves only the first 1000 results of a query
MAX_SIZE = 400_000            # files above ~384 KB are not indexed
MIN_SLICE = 4096              # narrowest size slice that is still split on persistent 5xx/408
SERVER_RETRIES = 2            # 5xx/408 answers to one request before its slice counts as failed
BLOB = re.compile(r"^https://github\.com/[^/]+/[^/]+/blob/([^/]+)/")


class SliceFailed(Exception):
    """GitHub keeps answering one query (slice) with 5xx/408: split it or skip it, do not stop."""


class SliceRejected(SliceFailed):
    """Unexpected 4xx for one query (slice): skip it without splitting, never cache it."""


def gh_queries(api: str, method_only: bool = False, notebooks: bool = False) -> List[str]:
    """Keyword queries for calls of `api` in GitHub search syntax (most precise first);
    notebooks: search `.ipynb` files instead of Python files."""
    lang = "extension:ipynb" if notebooks else "language:python"
    parts = api.split(".")
    top = parts[0]
    names = [api] + [f"{alias}{api[len(top):]}" for alias in MODULE_ALIASES.get(top, [])]
    queries = [f'"{n}" {lang}' for n in names]
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2][:1].isupper() and not parts[-1][:1].isupper():   # method
            queries.append(f'"{".".join(parts[:-2])}" {parts[-2]} {parts[-1]} {lang}')
            if method_only:
                queries.append(f'"{top}" {parts[-1]} {lang}')
        else:                                                                          # function / class
            queries.append(f'"{".".join(parts[:-1])}" {parts[-1]} {lang}')
            if len(parts) >= 3:                                                        # `from pkg import module; module.name(`
                queries.append(f'"{parts[-2]}.{parts[-1]}" {lang}')
    if "compat" in parts[1:-1]:          # `tf1 = tf.compat.v1; tf1.to_double(`: neither `tensorflow.compat.v1` nor
        i = parts.index("compat")        # `tf.compat.v1.to_double` is in the file
        if i + 1 < len(parts) - 1:
            queries.append(f'"{parts[i]}.{parts[i + 1]}" {" ".join(parts[i + 2:])} {lang}')
    return list(dict.fromkeys(queries))


class GitHubSearch:
    def __init__(self, cache: net.DiskCache, min_interval: float = 6.5, cached_only: bool = False):
        self.cache = cache
        self.cached_only = cached_only
        self.token = os.environ.get("GITHUB_TOKEN")
        self.min_interval = min_interval
        self._last = 0.0

    # ------------------------------------------------------------------ HTTP
    def _request(self, q: str, page: int) -> dict:
        if not self.token:
            raise SearchUnavailable("GitHub code search needs GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}",
                   "X-GitHub-Api-Version": "2022-11-28"}
        backoff = 10.0
        server_errors = 0
        for attempt in range(12):
            wait = self._last + self.min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                r = net._session.get(SEARCH_URL, headers=headers, timeout=60,
                                     params={"q": q, "per_page": PER_PAGE, "page": page})
            except requests.RequestException as e:
                r, err = None, type(e).__name__
            self._last = time.time()
            if r is not None and r.status_code == 200:
                return r.json()
            if r is not None and r.status_code == 422:          # invalid query / beyond 1000 results
                logging.warning("github search rejected %r (page %d): %s", q, page, r.text[:200])
                return {"total_count": 0, "items": []}
            if r is not None and r.status_code == 401:
                raise SearchUnavailable("GITHUB_TOKEN rejected by GitHub (401)")
            if r is not None and r.status_code in (403, 429):
                ra = r.headers.get("Retry-After", "")
                if ra.isdigit():
                    wait = int(ra) + 1
                elif r.headers.get("X-RateLimit-Remaining") == "0":
                    wait = int(r.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time() + 2
                else:                                           # secondary rate limit without hint
                    wait = 60 * (attempt + 1)
                wait = max(5, min(wait, 900))
                logging.warning("github search rate limited (%s), waiting %.0fs", r.status_code, wait)
                time.sleep(wait)
                continue
            status = r.status_code if r is not None else err
            if r is not None and r.status_code < 500 and r.status_code != 408:
                logging.warning("github search %r -> %s: %s", q, status, r.text[:200])
                raise SliceRejected(q)
            if r is not None:                       # 5xx / 408 timeout: query too heavy for GitHub
                server_errors += 1
                if server_errors >= SERVER_RETRIES:
                    raise SliceFailed(q)
            logging.warning("github search %r -> %s, retry %d in %.0fs", q, status, attempt + 1, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
        raise SearchUnavailable(f"github search unavailable: {q}")

    def _page(self, q: str, page: int) -> Tuple[int, List[list]]:
        """(total_count, [[repo, commit, path], ...]) of one result page (cached)."""
        key = f"ghs:{q}|p{page}"
        v = self.cache.get_json(key)
        if v is None:
            if self.cached_only:
                return 0, []
            data = self._request(q, page)
            items = []
            for it in data.get("items", []):
                repo = (it.get("repository") or {}).get("full_name")
                m = BLOB.match(it.get("html_url", ""))
                if repo and m and it.get("path"):
                    items.append([repo, m.group(1), it["path"]])
            v = {"total": int(data.get("total_count") or 0), "items": items}
            self.cache.put_json(key, v)
        return v["total"], v["items"]

    # ------------------------------------------------------------------ search
    def _bisect(self, q: str, lo: int, hi: int, count: int, out: Dict[tuple, Hit]) -> int:
        mid = (lo + hi) // 2
        return self._collect(q, lo, mid, count, out) + self._collect(q, mid + 1, hi, count, out)

    def _collect(self, q: str, lo: Optional[int], hi: Optional[int], count: int, out: Dict[tuple, Hit]) -> int:
        """Add the hits of one size slice (whole query when lo is None) to `out`;
        returns the number of slices skipped."""
        if len(out) >= count:
            return 0
        if lo is None:
            sub, lo, hi = q, 0, MAX_SIZE
        else:
            sub = f"{q} size:{lo}..{hi}"
        try:
            total, items = self._page(sub, 1)
            if total > MAX_RESULTS and hi - lo > 1:            # bisect by file size
                return self._bisect(q, lo, hi, count, out)
            pages = min(math.ceil(total / PER_PAGE), MAX_RESULTS // PER_PAGE)
            for page in range(1, pages + 1):
                if page > 1:
                    _, items = self._page(sub, page)
                for repo, commit, path in items:
                    out.setdefault((repo, commit, path), Hit(repo, commit, path, -1))   # stars fetched lazily
                if len(out) >= count or len(items) < PER_PAGE:
                    break
        except SliceFailed as e:
            if not isinstance(e, SliceRejected) and hi - lo > MIN_SLICE:
                logging.warning("github search %r keeps failing (5xx/408): splitting size %d..%d", q, lo, hi)
                return self._bisect(q, lo, hi, count, out)
            logging.warning("github search %r: skipped size slice %d..%d", q, lo, hi)
            return 1
        return 0

    def search(self, query: str, count: int) -> List[Hit]:
        key = f"ghsq:{query}|{count}"
        cached = self.cache.get_json(key)
        if cached is not None:
            return [Hit(**h) for h in cached]
        out: Dict[tuple, Hit] = {}
        skipped = self._collect(query, None, None, count, out)
        hits = list(out.values())[:count]
        if skipped:
            logging.warning("github search %r: %d size slice(s) skipped, %d hits kept; a later run retries them",
                            query, skipped, len(hits))
        # a cached-only run, or one with skipped slices, may be partial: do not freeze it
        if not self.cached_only and not skipped:
            self.cache.put_json(key, [h.__dict__ for h in hits])
        return hits
