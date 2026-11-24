"""Read files, trees and commit dates of a GitHub repository at a fixed commit (cached)."""
import datetime as dt
import os
from typing import List, Optional

from . import net

MISSING = "\x00missing"


class GitHub:
    def __init__(self, cache: net.DiskCache):
        self.cache = cache
        self.token = os.environ.get("GITHUB_TOKEN")

    def _api_headers(self):
        h = {"Accept": "application/vnd.github+json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _sourcegraph_raw(self, repo, commit, path):
        sg_token = os.environ.get("SRC_ACCESS_TOKEN") or os.environ.get("SOURCEGRAPH_TOKEN")
        r = net.get(f"https://sourcegraph.com/github.com/{repo}@{commit}/-/raw/{path}",
                    headers={"Authorization": f"token {sg_token}"} if sg_token else None)
        if r is not None and "text/html" in r.headers.get("Content-Type", ""):
            return None
        return r

    def raw(self, repo: str, commit: str, path: str, fallback: bool = False) -> Optional[str]:
        """File content at commit. Commits indexed by Sourcegraph are sometimes no longer served by
        GitHub: with fallback=True a GitHub miss is retried on Sourcegraph, and when that succeeds
        the commit is remembered so later files of it are read from Sourcegraph directly."""
        key = f"raw:{repo}@{commit}:{path}"
        v = self.cache.get(key)
        if v is not None:
            return None if v == MISSING else v
        sg_only = self.cache.get(f"sgonly:{repo}@{commit}") is not None
        r = None if sg_only else net.get(f"https://raw.githubusercontent.com/{repo}/{commit}/{path}")
        if r is None and (fallback or sg_only):
            r = self._sourcegraph_raw(repo, commit, path)
            if r is not None and not sg_only:
                self.cache.put(f"sgonly:{repo}@{commit}", "1")
        text = r.content.decode("utf-8", errors="replace") if r is not None else None
        self.cache.put(key, MISSING if text is None else text)
        return text

    def tree(self, repo: str, commit: str) -> Optional[List[str]]:
        """All blob paths at commit; None when unavailable (no token, truncated tree, error)."""
        if not self.token:
            return None
        key = f"tree:{repo}@{commit}"
        v = self.cache.get_json(key)
        if v is not None:
            return v.get("paths")
        r = net.get(f"https://api.github.com/repos/{repo}/git/trees/{commit}", headers=self._api_headers(),
                    params={"recursive": "1"})
        paths = None
        if r is not None:
            data = r.json()
            if not data.get("truncated"):
                paths = [e["path"] for e in data.get("tree", []) if e.get("type") == "blob"]
        self.cache.put_json(key, {"paths": paths})
        return paths

    def stars(self, repo: str) -> int:
        """Stargazer count of a repository (cached; -1 when unknown)."""
        key = f"stars:{repo}"
        v = self.cache.get_json(key)
        if v is None:
            r = net.get(f"https://api.github.com/repos/{repo}", headers=self._api_headers()) if self.token else None
            v = {"stars": int(r.json().get("stargazers_count", -1)) if r is not None else -1}
            if r is not None:
                self.cache.put_json(key, v)
        return v["stars"]

    def commit_date(self, repo: str, commit: str) -> Optional[dt.datetime]:
        if not self.token:
            return None
        key = f"date:{repo}@{commit}"
        v = self.cache.get_json(key)
        if v is None:
            r = net.get(f"https://api.github.com/repos/{repo}/commits/{commit}", headers=self._api_headers())
            date = None
            if r is not None:
                date = r.json().get("commit", {}).get("committer", {}).get("date")
            v = {"date": date}
            self.cache.put_json(key, v)
        return dt.datetime.fromisoformat(v["date"].replace("Z", "+00:00")) if v.get("date") else None
