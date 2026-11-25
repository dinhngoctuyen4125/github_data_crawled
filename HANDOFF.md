# HANDOFF: mở rộng bộ dữ liệu O/U deprecated API

## Bối cảnh và mục tiêu
- Repo là gói replication của bài báo "LLMs Meet Library Evolution". Kiến trúc và lệnh xem trong `CLAUDE.md`.
- Mục tiêu: crawl GitHub và Sourcegraph để thêm mẫu O (outdated) và U (up-to-dated), sao cho mỗi ô (mapping, U/O, milestone) đủ chỉ tiêu.
  - Chỉ tiêu của một ô = số lớn nhất trên evolution path của ô đó (hoặc `--cap`), trừ đi số đếm trong `manual_reviews/API_MIGRATION_COUNTS_BEFORE.md`.
  - Ô mà API không tồn tại ở milestone đó thì có chỉ tiêu 0.
- pytorch và tensorflow do người dùng chạy trên máy khác (hướng dẫn ở `llm_dep/crawling/README.md`). Phiên này chỉ lo numpy, pandas, scikit-learn, scipy, seaborn, transformers.

## Yêu cầu, ràng buộc và quyết định đã thống nhất
- Luôn trả lời bằng tiếng Việt, đơn giản, dễ hiểu.
- Phải giải thích và được đồng ý trước khi sửa code hoặc dữ liệu.
- Token nằm trong `.env` (gitignored): không in ra, không chia sẻ. Email và thông tin cá nhân của người dùng là riêng tư.
- Tôn trọng rate limit: không xoay vòng token, không lách giới hạn.
- Chạy crawl lần lượt, không chạy song song trên cùng một token.
- Giữ nguyên bộ key của mẫu, không thêm trường mới cho từng mẫu.
- Bảng tiến độ:
  - dùng đúng các cột: Thư viện | Tập | Ô cần lấp | Ô đã lấp đủ | Lượt lấp ô / cần;
  - nhóm theo thư viện, O trước U;
  - không đưa pytorch và tensorflow vào bảng.
- Chạy bằng Python 3.11: `C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe`.
  - conda base là Python 3.13, không còn `lib2to3`, nên không đọc được file Python 2.
  - env `crawl` là Python 3.10, thiếu `tomllib`.
- Trong `run_others.ps1`, giữ riêng hai dòng sklearn: dòng 20000 đọc lại cache, dòng 40000 tìm kiếm mới cho GMM.

## Công việc đã hoàn thành
- `extract.py` đọc được file Python 2. Cách làm:
  - chỉ dùng các fixer cú pháp của lib2to3 (`PY2_SYNTAX_FIXERS`);
  - lấy lại text gốc theo từng dòng, tương ứng 1:1;
  - mỗi luồng có một `RefactoringTool` riêng.
- `extract.py` resolve được import tương đối (`from . import utils`, `from ..utils import despine`):
  - package suy từ đường dẫn file (`package_of`), bắt đầu từ thư mục cuối cùng có tên là package top-level của thư viện;
  - `run.py` truyền `path=hit.path` vào `extract_sites`;
  - đã test thủ công: đúng trong `seaborn/` và `seaborn/tests/`, bỏ qua khi file nằm ngoài package hoặc `path=None`.
- `run_others.ps1` gom toàn bộ lệnh chạy. Người dùng đã chạy xong; `AFTER.md` được cập nhật lúc 02:40.
  - Bước 1: đọc lại cache bằng luật mới (`--cached-only --reprocess`), cho cả nguồn GitHub và Sourcegraph.
  - Bước 2: tìm kiếm GitHub mới cho sklearn GMM, giới hạn 40000.
  - Bước 3: `report --export`.
- Tạo `CLAUDE.md`.

## Các file đã tạo hoặc chỉnh sửa
- `llm_dep/crawling/extract.py` (đã commit)
- `llm_dep/crawling/run.py` (đã commit)
- `run_others.ps1` (đã commit)
- `CLAUDE.md` (mới, chưa commit)
- `HANDOFF.md` (mới, chưa commit)
- Dữ liệu được cập nhật khi chạy:
  - `data/<lib>/crawl/samples.jsonl`
  - `data/<lib>/crawl/processed*.progress.jsonl`
  - `data/<lib>/{O,U}_crawled.json`
  - `manual_reviews/API_MIGRATION_COUNTS_AFTER.md`
- Script tạm dựng bảng tiến độ: `C:\Users\tuyen\AppData\Local\Temp\claude\dc8dc83bc3ce8279\61ea4ca3-c37f-4be4-804e-01b0ad8f99fc\scratchpad\fill.py`
  - chạy bằng `PYTHONIOENCODING=utf-8 PYTHONPATH=. python <path>`;
  - tiêu đề cột trong script là "Mẫu đã lấp/cần", khi báo cáo đổi thành "Lượt lấp ô / cần";
  - thư mục scratchpad có thể bị xoá.

## Tiến độ hiện tại (sau khi chạy run_others.ps1)
| Thư viện | Tập | Ô cần lấp | Ô đã lấp đủ | Lượt lấp ô / cần |
|---|---|---|---|---|
| numpy | O | 21 | 21 (100%) | 18,827/18,827 (100%) |
| numpy | U | 12 | 12 (100%) | 75/75 (100%) |
| pandas | O | 105 | 92 (88%) | 463/492 (94.1%) |
| pandas | U | 22 | 22 (100%) | 163/163 (100%) |
| scikit-learn | O | 33 | 23 (70%) | 10,215/11,521 (88.7%) |
| scikit-learn | U | 34 | 34 (100%) | 470/470 (100%) |
| scipy | O | 55 | 50 (91%) | 3,913/4,042 (96.8%) |
| scipy | U | 54 | 54 (100%) | 4,454/4,454 (100%) |
| seaborn | O | 20 | 19 (95%) | 8,411/9,006 (93.4%) |
| seaborn | U | 15 | 7 (47%) | 810/4,651 (17.4%) |
| transformers | O | 44 | 36 (82%) | 36/44 (81.8%) |
| transformers | U | 218 | 218 (100%) | 603/603 (100%) |

## Vấn đề chưa giải quyết
- Chưa xác nhận đợt crawl GMM 40000 đã chạy hết hay dừng giữa chừng. Kiểm tra trong `data/crawl.log`.
- seaborn U thiếu khoảng 3,800 lượt.
  - Mẫu U chủ yếu là `utils.despine(...)` trong chính mã nguồn seaborn.
  - Người dùng thường viết `sns.despine()`, mà cách gọi này được tính là O.
  - Vì vậy gần như không thể lấp thêm.
- sklearn O thiếu khoảng 1,300 lượt, phần lớn là GMM.
- pandas O còn 13 ô chưa đủ, scipy O còn 5 ô, transformers O còn 8 ô.

## Các bước tiếp theo (đã đề xuất, chưa được duyệt)
- Hỗ trợ notebook (`.ipynb`), có thể giúp thêm mẫu cho `seaborn.tsplot` và sklearn GMM.
- Viết lại phần mẫu dependency (dependency-sample).
- Thêm các dòng lệnh cho pytorch nếu người dùng cần.
- Commit `CLAUDE.md` và `HANDOFF.md` khi người dùng yêu cầu.
