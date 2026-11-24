"""HTTP helpers with retries, on-disk caching and token handling (tokens come from env / .env)."""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import requests

USER_AGENT = "llm-dep-crawler/1.0"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def load_dotenv(path: Path = Path(".env")):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def get(url: str, headers: Optional[dict] = None, params: Optional[dict] = None, timeout: int = 60,
        retries: int = 4, stream: bool = False, ok_404: bool = True,
        max_delay: float = 300) -> Optional[requests.Response]:
    """GET with exponential backoff on 429/5xx and GitHub rate limits. None on 404 / give-up."""
    delay, last = 2.0, None
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, headers=headers, params=params, timeout=timeout, stream=stream)
        except requests.RequestException as e:
            r, last = None, type(e).__name__
        if r is not None:
            last = r.status_code
            if r.status_code == 404 and ok_404:
                return None
            if r.status_code < 400:
                return r
            if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
                reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(5, reset - time.time() + 1)
                logging.warning("rate limited by %s, sleeping %.0fs", url.split("/")[2], wait)
                time.sleep(min(wait, 3600))
                continue
            if r.status_code not in (403, 429) and r.status_code < 500:
                logging.warning("GET %s -> %s", url.split("?")[0], r.status_code)
                return None
        if attempt < retries:
            wait = delay
            if r is not None and r.headers.get("Retry-After", "").isdigit():
                wait = max(wait, int(r.headers["Retry-After"]))
            wait = min(wait, max_delay)
            logging.warning("%s -> %s, retry %d/%d in %.0fs", url.split("?")[0], last, attempt + 1, retries, wait)
            time.sleep(wait)
            delay *= 2
    logging.warning("giving up on %s (last status: %s)", url.split("?")[0], last)
    return None


class DiskCache:
    """Content cache: one file per key under root (keys hashed)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.root / h[:2] / h

    def get(self, key: str) -> Optional[str]:
        p = self._path(key)
        try:
            return p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (PermissionError, OSError):     # being replaced by another thread right now
            return None

    def put(self, key: str, value: str):
        """Atomic write: parallel workers may read the same key while it is being written."""
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(value, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:            # Windows: target briefly open by a reader
                time.sleep(0.05 * (attempt + 1))
        try:
            tmp.unlink()
        except OSError:
            pass

    def get_json(self, key: str):
        v = self.get(key)
        if not v:
            return None
        try:
            return json.loads(v)
        except json.JSONDecodeError:           # truncated by an older non-atomic write: refetch
            return None

    def put_json(self, key: str, value):
        self.put(key, json.dumps(value))
