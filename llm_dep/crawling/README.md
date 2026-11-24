# Crawl thêm mẫu O/U cho pytorch, tensorflow, transformers

## 1. Chuẩn bị

- Python **3.11 trở lên**.
- Cài thư viện: `pip install requests packaging`.
- Giải nén gói dữ liệu được gửi riêng vào thư mục gốc của repo, đúng đường dẫn:
  ```
  data/pytorch/O_modified.json        data/pytorch/U_modified.json
  data/tensorflow/O_modified.json     data/tensorflow/U_modified.json
  data/transformers/O_modified.json   data/transformers/U_modified.json
  ```
  Đây là dữ liệu gốc. Crawler đọc chúng để không lấy lại các hàm đã có.
- Chép `.env.example` thành `.env`, điền token **của bạn** (`GITHUB_TOKEN`, `SRC_ACCESS_TOKEN`), rồi kiểm tra:
  ```
  python -m llm_dep.crawling.check
  ```

## 2. Chạy

Chạy từ thư mục gốc của repo, **lần lượt từng lệnh**, vì các lệnh dùng chung một token:

```
# 1. Sourcegraph, gán version theo dependency
python -m llm_dep.crawling.run --libs transformers pytorch --search-limit 5000 --wait-on-block 60
python -m llm_dep.crawling.run --libs tensorflow --cap 500 --search-limit 5000 --wait-on-block 60

# 2. Sourcegraph, gán version theo signature (dùng lại kết quả đã tải ở bước 1)
python -m llm_dep.crawling.run --libs transformers pytorch --assign signature --cached-only --search-limit 5000
python -m llm_dep.crawling.run --libs tensorflow --cap 500 --assign signature --cached-only --search-limit 5000

# 3. GitHub Code Search, gán theo signature, lấp phần còn thiếu
python -m llm_dep.crawling.run --libs transformers pytorch --source github --assign signature --search-limit 5000 --wait-on-block 30
python -m llm_dep.crawling.run --libs tensorflow --cap 500 --source github --assign signature --search-limit 5000 --wait-on-block 30
```

- Xem số mẫu còn thiếu: thêm `--plan` vào lệnh.
- Bị dừng giữa chừng (Ctrl+C, mất mạng…) thì chạy lại đúng lệnh đó, crawler sẽ chạy tiếp. Kết quả tìm kiếm và file đã tải được cache trong `cache/`.
- Log ghi ở `data/crawl.log`. Các dòng `WARNING ... 503, retry 1` hoặc `rate limited, waiting ...` là bình thường.
- Các bước chạy khá lâu: TensorFlow và PyTorch có thể mất nhiều giờ.

## 3. Gửi lại kết quả

Nén và gửi lại 3 file:
```
data/pytorch/crawl/samples.jsonl
data/tensorflow/crawl/samples.jsonl
data/transformers/crawl/samples.jsonl
```
Gửi kèm `data/crawl.log` nếu có lỗi. **Không gửi `.env`** và không cần gửi `cache/`.
