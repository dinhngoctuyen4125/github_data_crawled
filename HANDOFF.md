# HANDOFF: mở rộng bộ dữ liệu O/U deprecated API

## Bối cảnh và mục tiêu
- Repo là gói replication của bài báo "LLMs Meet Library Evolution". Kiến trúc và lệnh xem trong `CLAUDE.md`.
- Mục tiêu: crawl GitHub và Sourcegraph để thêm mẫu O (outdated) và U (up-to-dated), sao cho mỗi ô (mapping, U/O, milestone) đủ chỉ tiêu.
  - Chỉ tiêu của một ô = số lớn nhất trên evolution path của ô đó (hoặc `--cap`), trừ đi số đếm trong `manual_reviews/API_MIGRATION_COUNTS_BEFORE.md`.
  - Ô mà API không tồn tại ở milestone đó thì có chỉ tiêu 0.
- pytorch và tensorflow do người dùng chạy trên máy khác (hướng dẫn ở `llm_dep/crawling/README.md`).
  - Kết quả đã được chép về `data/pytorch/crawl/`, `data/tensorflow/crawl/`, kèm log `data/crawl_tensorflow.log`.
  - Không có `cache/` của hai máy đó.

## Yêu cầu, ràng buộc và quyết định đã thống nhất
- Luôn trả lời bằng tiếng Việt, đơn giản, dễ hiểu, dạng bullet, đủ ý, không lan man.
- Phải giải thích và được đồng ý trước khi sửa code hoặc dữ liệu.
- Token nằm trong `.env` (gitignored): không in ra, không chia sẻ. Email và thông tin cá nhân của người dùng là riêng tư.
- Tôn trọng rate limit: không xoay vòng token, không lách giới hạn. Chạy crawl lần lượt, không song song trên cùng token.
- Giữ nguyên bộ key của mẫu, không thêm trường mới cho từng mẫu.
- Mẫu được phép là hàm/method **hoặc** khối lệnh rời (tối đa 5 câu lệnh cấp module), giống bài báo.
  - Dữ liệu gốc có 5,3% mẫu không phải hàm (1.459/27.427), dữ liệu crawl có khoảng 22%.
  - Người dùng đã quyết định giữ cả hai loại.
- Người dùng tự chạy `run_others.ps1`. Claude chỉ cập nhật lệnh vào script; chỉ chạy thử nhỏ, ghi ra thư mục tạm, không ghi vào `data/`.
- Bảng tiến độ:
  - dùng đúng các cột: Thư viện | Tập | Ô cần lấp | Ô đã lấp đủ | Lượt lấp ô / cần (kèm %);
  - nhóm theo thư viện, O trước U;
  - từ khi có dữ liệu ngoài thì đưa cả pytorch và tensorflow vào cuối bảng (tensorflow tính với `--cap 500`), không thêm dòng tổng.
- Ba loại lệnh crawl (người dùng đặt tên):
  - #1: Sourcegraph, truy vấn api_name + dependency, gán version theo dependency;
  - #2: Sourcegraph, chỉ truy vấn api_name, gán theo signature;
  - #3: GitHub, chỉ truy vấn api_name, gán theo signature.
- Chạy bằng Python 3.11: `C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe`.
  - conda base là Python 3.13, không còn `lib2to3`; env `crawl` là Python 3.10, thiếu `tomllib`.

## Công việc đã hoàn thành (code đã commit)
- `extract.py`:
  - đọc file Python 2 (chỉ dùng fixer cú pháp của lib2to3, text ánh xạ 1:1 về dòng gốc);
  - resolve import tương đối trong bản sao thư viện (package suy từ đường dẫn file).
- Hỗ trợ notebook, cờ `--notebooks`:
  - tìm kiếm: GitHub `extension:ipynb`, Sourcegraph `file:\.ipynb$`;
  - `notebook_to_script` (`extract.py`):
    - nối các ô code thành một script, đọc được nbformat 3 và 4;
    - dòng magic hoặc shell được chuyển thành comment;
    - cell `%%bash` hoặc cell không parse được thì comment cả cell;
  - bỏ qua `.ipynb_checkpoints/`;
  - cache chỉ lưu code (`github.strip_notebook`).
- Sửa lỗi `self` trong `signature.py`:
  - lời gọi qua tên class `pd.DataFrame.pad(x, ...)` coi `x` là `self`, bớt 1 tham số vị trí rồi mới so với chữ ký;
  - nhận dạng dạng này theo AST (`Call.receiver`), không theo chuỗi text;
  - `selfcheck` không đổi (`disagree=0`).
- Đã chạy (người dùng chạy):
  - đợt notebook cho các thư viện còn thiếu;
  - lượt đọc lại cache pandas sau khi sửa lỗi `self`;
  - `report --export`.
  - `AFTER.md` cập nhật lúc 09:43 ngày 2026-11-26.
- Dữ liệu: đã gỡ 7 mẫu `pd.DataFrame.pad(...)` khỏi `data/pandas/crawl/samples.jsonl` để gán lại.
  - 5 mẫu được nhận lại, gán đủ 1.1.0–2.3.3.
  - 2 mẫu thừa (ô đã đủ) chỉ còn trong bản sao lưu `data/pandas/crawl/samples.jsonl.bak-unbound-self`.
- Dữ liệu tensorflow: đã bỏ 1.499 mẫu trùng khỏi `data/tensorflow/crawl/samples.jsonl` (9.940 → 8.441 dòng).
  - Bản sao lưu: `data/tensorflow/crawl/samples.jsonl.bak-dup`.
  - Nguyên nhân (theo `data/crawl_tensorflow.log`): lệnh #3 từng chạy **hai tiến trình song song**. Có 890 dòng log lặp lại, hai dòng `tensorflow done` cùng lúc 07:13:53 ngày 25. Mỗi mẫu bị ghi hai lần liền nhau, cùng repo và path.
  - pytorch không bị trùng.

## Tiến độ hiện tại (2026-11-26, sau khi bỏ trùng tensorflow)
| Thư viện | Tập | Ô cần lấp | Ô đã lấp đủ | Lượt lấp ô / cần |
|---|---|---|---|---|
| numpy | O | 21 | 21 (100%) | 18,827/18,827 (100%) |
| numpy | U | 12 | 12 (100%) | 75/75 (100%) |
| pandas | O | 105 | 97 (92%) | 484/492 (98.4%) |
| pandas | U | 22 | 22 (100%) | 163/163 (100%) |
| scikit-learn | O | 33 | 31 (94%) | 10,723/11,521 (93.1%) |
| scikit-learn | U | 34 | 34 (100%) | 470/470 (100%) |
| scipy | O | 55 | 50 (91%) | 3,923/4,042 (97.1%) |
| scipy | U | 54 | 54 (100%) | 4,454/4,454 (100%) |
| seaborn | O | 20 | 19 (95%) | 8,422/9,006 (93.5%) |
| seaborn | U | 15 | 7 (47%) | 834/4,651 (17.9%) |
| transformers | O | 44 | 36 (82%) | 36/44 (81.8%) |
| transformers | U | 218 | 218 (100%) | 603/603 (100%) |
| pytorch | O | 129 | 60 (47%) | 46,112/88,964 (51.8%) |
| pytorch | U | 61 | 61 (100%) | 6,573/6,573 (100%) |
| tensorflow | O | 349 | 178 (51%) | 26,977/68,089 (39.6%) |
| tensorflow | U | 39 | 33 (85%) | 290/842 (34.4%) |

Cách tính bảng:
- Script tạm: `C:\Users\tuyen\AppData\Local\Temp\claude\dc8dc83bc3ce8279\1eeb09e3-f8d8-43be-9e0f-3fdb399b714c\scratchpad\fill_all.py`. Script này có cap riêng cho từng thư viện (tensorflow 500). Thư mục scratchpad có thể bị xoá.
- Chạy bằng `PYTHONIOENCODING=utf-8 PYTHONPATH=. python <path>`.
- Logic:
  - dựng `Quota(ev, parse_counts_md(BEFORE), baseline="existing")`;
  - nạp mọi `samples.jsonl`, chỉ cộng mẫu còn chạm ô thiếu;
  - với mỗi ô khả thi, `need = target - BEFORE`, rồi đếm số ô và số lượt đã lấp (tối đa `need`).

## Các ô O còn thiếu và nguyên nhân (đã kiểm tra)
- `sklearn.mixture.GMM`, chỉ thiếu ở 0.9 và 0.10 (245/644 mỗi ô):
  - chữ ký 0.9/0.10 dùng `cvtype`, chưa có `n_iter`, `n_init`, `params`;
  - 409/654 mẫu dùng `covariance_type=` hoặc `n_iter=`, nên không gắn được vào hai bản này. Đây là quy tắc đúng.
- `seaborn.tsplot`, chỉ thiếu ở 0.1 (100/684):
  - chữ ký 0.1 là `tsplot(x, data, ...)`, người dùng thường viết `tsplot(data, time=...)`;
  - 473/573 mẫu không gắn được vào 0.1.
- `scipy.stats.betai` (10/49 ở 3 ô) và `scipy.special.sph_yn` (9/10 ở 2 ô): rất ít lời gọi thật; phần lớn kết quả là bản sao scipy (`vendored_path`).
- `pandas.Series.pad` (8 ô, 0 mẫu): mọi `.pad(` tìm được là `np.pad`, `F.pad`, `str.pad`.
- transformers `SEWForSequenceClassification` và `TFWav2Vec2ForCTC.freeze_feature_extractor`:
  - 775 file khớp đều là bản sao mã nguồn transformers, chỉ định nghĩa, không gọi;
  - 66 lời gọi tìm được đều trùng dữ liệu gốc.
- seaborn U (`utils.despine`): mẫu U chủ yếu nằm trong chính mã nguồn seaborn, còn người dùng viết `sns.despine()` (được tính là O). Gần như không lấp thêm được.
- Đợt notebook đã thêm mẫu: sklearn O 90, seaborn O 11, seaborn U 3, scipy O 5, pandas O 1. Sourcegraph gần như không có notebook.

## pytorch và tensorflow: vì sao còn thiếu nhiều (đã kiểm tra)
- Nguyên nhân chung: chỉ tiêu lấy theo số lớn nhất của **cả U lẫn O** trên path ([quota.py:40](llm_dep/crawling/quota.py#L40)). Khi API thay thế rất phổ biến, ô O phải đạt bằng con số đó, dù API cũ hiếm.
  - Có thể đổi chỉ tiêu ô O thành số lớn nhất của riêng dòng O, nhưng đó là đổi cách làm. Người dùng chưa quyết định.
- pytorch O (thiếu 42.852 lượt):
  - 94% đến từ `upsample_nearest` (thiếu 25.805, có 58 mẫu) và `upsample_bilinear` (thiếu 14.518);
  - `interpolate` (U) có 1.209–1.283 mẫu trong BEFORE, nên chỉ tiêu mỗi ô O là 1.283; dữ liệu gốc O chỉ có 52 và 217 mẫu;
  - mọi milestone thiếu như nhau, tức là do ít lời gọi, không phải do chữ ký.
- tensorflow O:
  - 98% đến từ 9 mapping `to_*` → `tf.cast`;
  - `tf.cast` có 3.341 mẫu U, nên chỉ tiêu bị chặn ở cap 500 mỗi ô; dữ liệu gốc O chỉ có 0–39 mẫu.
- tensorflow U: chỉ thiếu `tf.saved_model.load` ở 1.12.0 và 1.13.1, dùng chung cho 3 mapping (nên số thiếu bị đếm 3 lần).
  - Ở hai bản này chữ ký là `load(sess, tags, export_dir, ...)`, còn `load(path)` chỉ khớp từ 2.0.
- Lệnh #3 của tensorflow đã chạy hết, không có `skipped size slice`, rate limit đều được chờ.
  - Máy tensorflow chạy code cũ (trước commit `6e45c21`), thiếu truy vấn thứ tư dạng `"v1.to_double"`, `"saved_model.load"`.

## Các hướng còn lại (chưa được duyệt)
- Đo xem bỏ các quy tắc trích xuất của bài báo sẽ thêm bao nhiêu mẫu. Bỏ chúng sẽ lệch với cách làm của bài báo. Các quy tắc:
  - mỗi file chỉ lấy 1 khối lệnh rời;
  - mỗi hàm chỉ lấy lời gọi đầu tiên;
  - khối lệnh cần ít nhất một câu lệnh đứng trước lời gọi.
- Cho phép `vendored_path` (bản sao thư viện trong `site-packages`): có thể phần lớn là trùng lặp và không đại diện cho code người dùng.
- Viết lại phần mẫu dependency (dependency-sample).
- Thêm các dòng lệnh cho pytorch nếu người dùng cần.

## Trạng thái file
- `run_others.ps1` hiện chứa lượt chạy lại lệnh #3 cho tensorflow. **Chưa chạy.**
  1. `--cached-only --reprocess`: lấp lại các ô bị trống ra sau khi bỏ trùng.
  2. Tìm kiếm GitHub mới, cho các truy vấn mà code cũ thiếu.
  3. `report --export`.
- Cần chạy trên máy tensorflow (có `cache/`):
  - cập nhật code mới nhất;
  - chép `data/tensorflow/crawl/samples.jsonl` đã bỏ trùng sang;
  - sửa `$py` cho đúng máy đó;
  - chạy từng lệnh một;
  - chạy xong thì chép `data/tensorflow/crawl/` về đây.
- Đợt kế tiếp thì thay nội dung file bằng lệnh mới.
