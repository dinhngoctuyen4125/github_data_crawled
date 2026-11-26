# Crawl thêm mẫu O/U cho pytorch, tensorflow, transformers

## 1. Chuẩn bị

- Dùng Python **3.11 hoặc 3.12**.
  - Python 3.13 không còn `lib2to3`, nên không đọc được file Python 2.
  - Python 3.10 trở xuống thiếu `tomllib`.
- Cài thư viện: `pip install requests packaging`.
- Giải nén gói dữ liệu được gửi riêng vào thư mục gốc của repo, đúng các đường dẫn sau:

  ```text
  data/pytorch/O_modified.json        data/pytorch/U_modified.json
  data/tensorflow/O_modified.json     data/tensorflow/U_modified.json
  data/transformers/O_modified.json   data/transformers/U_modified.json
  ```

  - Đây là dữ liệu gốc. Crawler đọc chúng để không lấy lại các hàm đã có.
- Chép `.env.example` thành `.env`, điền token **của bạn** (`GITHUB_TOKEN`, `SRC_ACCESS_TOKEN`), rồi kiểm tra:

  ```bash
  python -m llm_dep.crawling.check
  ```

## 2. Chạy

- Chạy từ thư mục gốc của repo, **lần lượt từng lệnh**: các lệnh dùng chung một token.
- `--min-target 100`: mỗi ô cần ít nhất 100 mẫu.

```bash
# 1. Sourcegraph, gán version theo dependency
python -m llm_dep.crawling.run --libs transformers pytorch --min-target 100 --search-limit 5000 --wait-on-block 60
python -m llm_dep.crawling.run --libs tensorflow --cap 500 --min-target 100 --search-limit 5000 --wait-on-block 60

# 2. Sourcegraph, gán theo signature (chỉ đọc lại kết quả đã tải ở bước 1)
python -m llm_dep.crawling.run --libs transformers pytorch --min-target 100 --assign signature --cached-only --search-limit 5000
python -m llm_dep.crawling.run --libs tensorflow --cap 500 --min-target 100 --assign signature --cached-only --search-limit 5000

# 3. GitHub Code Search, gán theo signature, lấp phần còn thiếu
python -m llm_dep.crawling.run --libs transformers pytorch --min-target 100 --source github --assign signature --search-limit 5000 --wait-on-block 30
python -m llm_dep.crawling.run --libs tensorflow --cap 500 --min-target 100 --source github --assign signature --search-limit 5000 --wait-on-block 30
```

- Thêm `--plan` vào lệnh để xem số mẫu còn thiếu, không crawl.
- Bị dừng giữa chừng (Ctrl+C, mất mạng…) thì chạy lại đúng lệnh đó: crawler chạy tiếp từ chỗ dừng.
  - Kết quả tìm kiếm và file đã tải được cache trong `cache/`.
- Log ghi ở `data/crawl.log`. Các dòng `WARNING ... 503, retry 1` hoặc `rate limited, waiting ...` là bình thường.
- TensorFlow và PyTorch có thể mất nhiều giờ.
- **Không** chạy hai lệnh cùng lúc: mẫu sẽ bị ghi trùng.

## 3. Gửi lại kết quả

- Nén và gửi lại 3 file:

  ```text
  data/pytorch/crawl/samples.jsonl
  data/tensorflow/crawl/samples.jsonl
  data/transformers/crawl/samples.jsonl
  ```

- Nếu có lỗi thì gửi kèm `data/crawl.log`.
- **Không gửi `.env`**. Thư mục `cache/` thì gửi nếu được yêu cầu: nó giúp máy khác đọc lại mà không phải tìm kiếm lại.
