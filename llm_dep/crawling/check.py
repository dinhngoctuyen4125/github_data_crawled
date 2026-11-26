"""Check that GITHUB_TOKEN and SRC_ACCESS_TOKEN (env or .env) work. Never prints the tokens."""
import os
import sys

import requests

from . import net
from .sourcegraph import STREAM_URL


def main():
    if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    net.load_dotenv()
    ok = True

    gh = os.environ.get("GITHUB_TOKEN")
    if not gh:
        print("[GitHub]      THIẾU: chưa có GITHUB_TOKEN trong .env"); ok = False
    else:
        r = net.get("https://api.github.com/rate_limit", headers={"Authorization": f"Bearer {gh}"}, ok_404=False, retries=1)
        if r is None:
            print("[GitHub]      LỖI: token không hợp lệ hoặc không kết nối được"); ok = False
        else:
            core = r.json()["resources"]["core"]
            print(f"[GitHub]      OK: còn {core['remaining']}/{core['limit']} request trong giờ này")

    sg = net.sourcegraph_token()
    if not sg:
        print("[Sourcegraph] THIẾU: chưa có SRC_ACCESS_TOKEN trong .env"); ok = False
    else:
        user = None
        try:
            r = requests.post("https://sourcegraph.com/.api/graphql", headers={"Authorization": f"token {sg}"},
                              json={"query": "query{currentUser{username}}"}, timeout=60)
            if r.ok:
                user = (r.json().get("data") or {}).get("currentUser")
        except (requests.RequestException, ValueError):
            pass
        if user:
            print("[Sourcegraph] OK: token hợp lệ")
        else:
            print("[Sourcegraph] LỖI: token không hợp lệ hoặc không kết nối được"); ok = False
        try:
            r = requests.get(STREAM_URL, timeout=120,
                             headers={"Accept": "text/event-stream", "Authorization": f"token {sg}"},
                             params={"q": "context:global lang:python count:1 numpy .prod(", "v": "V3", "t": "keyword"})
            searchable = r.ok and "text/event-stream" in r.headers.get("Content-Type", "")
            status = r.status_code
        except requests.RequestException as e:
            searchable, status = False, type(e).__name__
        if searchable:
            print("[Sourcegraph] OK: tìm kiếm hoạt động")
        else:
            print(f"[Sourcegraph] BỊ CHẶN/QUÁ TẢI: tìm kiếm trả về {status}, chờ thêm rồi kiểm tra lại")
            print("\nToken đúng, nhưng Sourcegraph đang tạm chặn tìm kiếm. Chờ một lúc rồi chạy lại lệnh này.")
            return

    print("\nSẵn sàng chạy crawl." if ok else "\nSửa file .env rồi chạy lại lệnh này.")


if __name__ == "__main__":
    main()
