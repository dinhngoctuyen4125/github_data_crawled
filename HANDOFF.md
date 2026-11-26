# HANDOFF: mở rộng bộ dữ liệu O/U deprecated API

## Bối cảnh và mục tiêu

- Repo là gói replication của bài báo "LLMs Meet Library Evolution". Kiến trúc và lệnh xem trong `CLAUDE.md`.
- Mục tiêu: crawl GitHub và Sourcegraph để thêm mẫu O (outdated) và U (up-to-dated), đến khi mỗi ô (mapping, U/O, milestone) đủ chỉ tiêu.
  - Chỉ tiêu của mapping = max(số lớn nhất ở hai hàng U/O trong BEFORE, `--min-target`), sau đó không vượt `--cap`.
  - Cần lấp của một ô = chỉ tiêu − số BEFORE. Ô mà API không tồn tại ở milestone đó có chỉ tiêu 0.
- pytorch và tensorflow còn được crawl trên máy khác (hướng dẫn ở `llm_dep/crawling/README.md`).
  - Kết quả đã chép về `data/pytorch/crawl/` và `data/tensorflow/crawl/`, kèm log `data/crawl_tensorflow.log`.
  - Cache của máy tensorflow nằm ở `cache_tensorflow/`. Không có cache của máy pytorch.

## Yêu cầu, ràng buộc và quyết định đã thống nhất

- Trả lời bằng tiếng Việt, dạng bullet, ngắn gọn nhưng đủ ý.
- Phải giải thích và được đồng ý trước khi sửa code hoặc dữ liệu.
- Token nằm trong `.env` (gitignored): không in ra, không chia sẻ. Email và thông tin cá nhân của người dùng là riêng tư.
- Tôn trọng rate limit: không xoay vòng token, không lách giới hạn. Mỗi lúc chỉ chạy một lệnh crawl.
- Giữ nguyên bộ key của mẫu, không thêm trường mới cho từng mẫu.
- Mẫu là hàm/method **hoặc** khối tối đa 5 câu lệnh cấp module, giống bài báo.
  - Dữ liệu gốc có 5,3% mẫu không phải hàm, dữ liệu crawl có khoảng 22%. Người dùng giữ cả hai loại.
- Chỉ tiêu dùng chung cho cả hai hàng U và O của một mapping: số lớn nhất của cả hai hàng.
  - Người dùng đã xem phương án tính riêng từng hàng và **giữ cách hiện tại**.
- Mức sàn **100 mẫu mỗi ô** (`--min-target 100`, quyết định ngày 2026-11-27).
  - Lệnh `report` phải dùng cùng mức sàn.
- Người dùng tự chạy `run_others.ps1`. Claude chỉ cập nhật lệnh trong script.
  - Claude chỉ chạy thử nhỏ, ghi ra thư mục tạm, không ghi vào `data/`.
- Ba loại lệnh crawl (người dùng đặt tên):
  - #1: Sourcegraph, truy vấn tên API + dependency, gán version theo dependency;
  - #2: Sourcegraph, chỉ truy vấn tên API, gán theo signature;
  - #3: GitHub, chỉ truy vấn tên API, gán theo signature.
- Bảng tiến độ có các cột: Thư viện | Tập | Số file đã truy xuất | Ô đã lấp đủ | Lượt lấp ô / cần.
  - Thứ tự dòng: numpy, pandas, scikit-learn, scipy, seaborn, transformers, pytorch, tensorflow; O trước U; không có dòng tổng.
  - Tensorflow tính với `--cap 500`.
  - Lập xong bảng thì so với bảng gần nhất trong file này.
- Chạy bằng Python 3.11: `C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe`.

## Công việc đã hoàn thành (code đã commit, trừ phần ghi rõ)

- Trích lời gọi (`extract.py`):
  - đọc được file Python 2 và notebook (`--notebooks`);
  - resolve import tương đối trong bản sao thư viện;
  - nhận alias bằng phép gán ở cấp module (`tf1 = tf.compat.v1`, `GMM = mixture.GMM`);
  - nhận lời gọi qua tên class `pd.DataFrame.pad(x, ...)`, coi `x` là `self`.
- Truy vấn mới cho API `compat.v1.*`: GitHub `"compat.v1" <tên>`, Sourcegraph `compat.v1 .<tên>(`.
- `signature.py`: keyword trùng tên tham số positional-only được đưa vào `**kwargs`, như Python làm (commit 79052bb).
- `report.py`:
  - đổi `AFTER.md` cũ thành `API_MIGRATION_COUNTS_NEED.md` (`đã crawl/cần`);
  - thêm `API_MIGRATION_COUNTS_AFTER.md` là số mẫu cuối cùng: BEFORE + mẫu crawl được giữ, `-` khi API không tồn tại, cạnh mỗi cặp ghi `(max BEFORE = N)`.
- **Chưa commit** (2026-11-27):
  - thêm `--min-target` (`quota.py`, `run.py`, `report.py`);
  - dọn code `llm_dep/crawling`:
    - gộp `binds`/`binds_starred`;
    - chuyển phần đọc bảng BEFORE và các công thức chỉ tiêu về `quota.py`;
    - tách hàm dùng chung `net.sourcegraph_token()`;
    - bỏ trường không dùng `Placement.milestone`;
    - mô tả đầu mỗi file chỉ còn một dòng;
  - tăng tốc trích lời gọi khoảng 1,4–2 lần (tách dòng bằng regex, `walk_stmts` bỏ qua cây con biểu thức);
  - kiểm tra hành vi không đổi:
    - `selfcheck` không đổi;
    - chuỗi truy vấn và chỉ tiêu giống hệt;
    - `--plan`, NEED/AFTER giống hệt (phần lệch chỉ do mẫu mới của lần chạy đang diễn ra);
    - kết quả trích lời gọi giống hệt trên 1.358 file.
- Dữ liệu:
  - gỡ 7 mẫu `pd.DataFrame.pad(...)` để gán lại (bản sao lưu `data/pandas/crawl/samples.jsonl.bak-unbound-self`);
  - bỏ 1.499 mẫu trùng tensorflow (9.940 → 8.441 dòng, bản sao lưu `samples.jsonl.bak-dup`). Nguyên nhân: lệnh #3 từng chạy hai tiến trình song song.

## Tiến độ gần nhất (2026-11-26 22:00, trước khi có mức sàn 100)

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
| tensorflow | O | 349 | 178 (51%) | 27,269/68,089 (40.0%) |
| tensorflow | U | 39 | 33 (85%) | 290/842 (34.4%) |

- Bảng này dùng định dạng cũ. Bảng tiếp theo dùng định dạng mới và mức sàn 100, nên cột "cần" sẽ tăng.
- Ảnh hưởng của mức sàn 100 (tính ngày 2026-11-27):
  - 1.531 ô dưới 100 chỉ vì chỉ tiêu cũ dưới 100, cần thêm khoảng 130.400 lượt; riêng transformers khoảng 73.000;
  - 88 ô dưới 100 dù chỉ tiêu ≥ 100, vì đã cạn nguồn: seaborn U 8, tensorflow O 74, tensorflow U 6.

## Ô khả thi vẫn chưa có mẫu nào (BEFORE + crawl = 0), 67 ô

- transformers O, 4 ô: [135] `SEWForSequenceClassification.freeze_feature_extractor`.
- tensorflow O, 63 ô: [70] `uniform_unit_scaling` 4, [73] 7, [74] 7, [75] 8 (các `mixed_precision.*LossScale`), [83] `compat.v1.to_complex128` 11, [84] `compat.v1.to_complex64` 11, [90] 10, [101] 5.
- Mọi tập U và các thư viện còn lại: không có ô nào như vậy.
- Đây là các API cũ rất ít người gọi trực tiếp. Đợt crawl tensorflow mới không thêm được mẫu nào cho chúng.

## Nguyên nhân các tập còn thiếu (đã kiểm tra, không phải lỗi code)

- seaborn U (`utils.despine`): người dùng viết `sns.despine()` (tính là O). Mẫu U gần như chỉ có trong bản sao mã nguồn seaborn.
- pytorch O (`upsample*`, bị bỏ từ năm 2018):
  - toàn GitHub chỉ có khoảng 754 file dùng `F.upsample_nearest`;
  - trong khi đó mỗi ô cần 1.283 mẫu, vì chỉ tiêu lấy theo `interpolate` (U).
- tensorflow O (`tf.to_*` → `tf.cast`, cap 500):
  - mỗi API chỉ có 500–1.000 file trên GitHub, phần lớn là bản sao mã nguồn TF (`vendored_path`).
- tensorflow U (`tf.saved_model.load` ở 1.12/1.13.1):
  - chữ ký ở hai bản này là `load(sess, tags, export_dir)`;
  - người dùng gần như chỉ viết kiểu TF2 `load(path)`, dạng này chỉ khớp từ 2.0.
- Ô O thiếu ở milestone cũ vì chữ ký khác (quy tắc đúng):
  - `sklearn.mixture.GMM` 0.9/0.10: dùng `cvtype`, chưa có `n_iter`;
  - `seaborn.tsplot` 0.1: chữ ký `tsplot(x, data)`.
- `pandas.Series.pad`: mọi `.pad(` tìm được là `np.pad`, `F.pad`, `str.pad`.
- Đã thử sửa TabError và quét chéo target: gần như không thêm mẫu, nên không áp dụng.

## Các hướng còn lại (chưa được duyệt)

- Chạy notebook (`--notebooks`) cho pytorch và tensorflow; hai thư viện này chưa có đợt notebook nào.
- Thêm truy vấn `"F.<tên>"` cho `torch.nn.functional`: cần sửa code, ước tính thêm vài chục mẫu.
- Chạy `--cached-only` bằng nhiều tiến trình song song (process pool), nhanh hơn khoảng 5 lần.
  - Phải cẩn thận để không vượt rate limit của GitHub REST.
- Đo xem bỏ các quy tắc trích của bài báo sẽ thêm bao nhiêu mẫu (sẽ lệch với cách làm của bài báo).
- Cho phép `vendored_path`: phần lớn là trùng lặp, không đại diện cho code người dùng.

## Trạng thái file

- `run_others.ps1`: đợt **đọc lại cache với mức sàn 100**. Người dùng bắt đầu chạy lúc 02:18 ngày 2026-11-27.
  - 3 nhóm: (numpy, pandas, scikit-learn, scipy), transformers, tensorflow (`--cache cache_tensorflow`).
  - Mỗi nhóm có 6 lệnh `--cached-only --reprocess`, nên không gửi truy vấn tìm kiếm nào:
    - #1 với limit 2000;
    - #2 với limit 2000 và 5000;
    - #3 với limit 40000;
    - #2 và #3 cho notebook.
  - Cuối cùng chạy `report --export @floor`.
  - Không có pytorch (máy này không có cache) và seaborn (mức sàn không mở thêm ô nào).
- Chạy xong thì:
  - lập bảng tiến độ theo định dạng mới;
  - soạn đợt tìm mới cho các ô còn thiếu, ưu tiên pandas, scipy, scikit-learn, numpy.
- Ctrl+C trong PowerShell dừng cả script. Chạy lại đúng lệnh bị dừng thì nó tiếp tục từ chỗ dừng.
