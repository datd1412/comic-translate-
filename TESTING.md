# HƯỚNG DẪN KIỂM THỬ (TESTING.md) — COMIC TRANSLATE VN

Tài liệu này hướng dẫn cách cài đặt môi trường và chạy kiểm thử tự động từ **Phase 0**, **Phase 1 (`ocr_service`)** đến **Phase 2 (`server`)** trên Windows PowerShell.
Mọi số liệu tốc độ (ms) hoặc dung lượng RAM (MB) chưa được đo trực tiếp trên máy thật đều được ghi rõ là **"chưa đo"** hoặc **"chưa kiểm chứng"**.

---

## 1. Kiểm thử Phase 0 (Đo kiểm OCR thực nghiệm)

```powershell
cd comic-translate-vn
pytest tests/test_phase0_eval.py -v
```
- **Số lượng bài test dự kiến:** `6 passed`.

---

## 2. Kiểm thử Phase 1 (`ocr_service`)

```powershell
cd comic-translate-vn\ocr_service
pip install -r requirements.txt

# Chạy unit test nhanh (dùng MockOCREngine, không nạp PaddleOCR thật):
pytest -m "not slow" -v

# Chạy integration test với PaddleOCR 3.7.0 thật (PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec):
pytest -m "slow" -v -s
```
- **Kết quả thực tế đã kiểm chứng trên máy Windows CPU:**
  - `pytest -m "not slow" -v`: **6 passed, 1 deselected (2.23s)**.
  - `pytest -m "slow" -v -s`: **1 passed, 6 deselected (9.39s)**.

---

## 3. Kiểm thử Phase 2 (`server` — Server chính)

### 3.1. Cài đặt thư viện cho `server`
Mở PowerShell tại thư mục `comic-translate-vn\server`:

```powershell
cd comic-translate-vn\server
pip install -r requirements.txt
```

### 3.2. Chạy toàn bộ bộ kiểm thử Phase 2 (`pytest`)
```powershell
cd comic-translate-vn\server
pytest -v
```

- **Số lượng bài test dự kiến:** `11 passed` (9 nhóm kiểm thử, trong đó nhóm số 3 được parametrize thành 3 kịch bản lỗi: `ocr_500`, `llm_500`, `timeout`).
- **Chi tiết 9 nhóm bài test trong `server/tests/test_server_phase2.py`:**
  1. `test_callback_uri_validation_blocks_attacks_and_allows_valid_uris`: Kiểm tra chặn `evil.com`, `127.0.0.1.evil.com`, `127.0.0.1@evil.com`, `abc.chromiumapp.org.evil.com`, `javascript:alert(1)`, chuỗi rỗng `""` ở CẢ `/login/` và `/auth/firebase`; cho phép `http://127.0.0.1:<port>/...`, `http://localhost:<port>/...` và `https://<EXTENSION_ID>.chromiumapp.org/...`.
  2. `test_concurrent_20_requests_only_5_succeed_and_ledger_matches`: Bắn đồng thời 20 request dịch trang khi số dư chỉ đủ cho 5 trang (10 credits, mỗi trang 2 credits). Đảm bảo đúng 5 request trả HTTP 200, 15 request trả HTTP 402, số dư cuối bằng `0` (không âm), và tổng `SUM(delta_credits)` trong `CreditLedger` khớp tuyệt đối với số dư.
  3. `test_refund_credits_on_ocr_error_llm_error_or_timeout[ocr_500|llm_500|timeout]`: Kiểm tra hoàn trả nguyên tử credit và ghi bản ghi `CreditLedger(entry_type="refund")` khi `ocr_service` trả 500, LLM trả 500, hoặc bị timeout.
  4. `test_payos_webhook_idempotency_and_signature_verification`: Kiểm tra từ chối chữ ký HMAC-SHA256 giả mạo (HTTP 400) và gọi lặp lại 3 lần cùng `order_code` hợp lệ chỉ cộng credit đúng 1 lần.
  5. `test_image_hash_cache_and_idempotency_key_and_user_isolation`: Kiểm tra gửi lại cùng `idempotency_key` không trừ credit lần 2; gửi lại cùng ảnh khác `idempotency_key` của cùng user trúng cache (`CACHE_HIT_COST = 0`); gửi cùng ảnh từ user thứ 2 vẫn tính phí độc lập (không rò rỉ cache giữa 2 user).
  6. `test_gemini_api_key_sent_in_header_not_in_url`: Kiểm tra request gửi sang Gemini dùng header `x-goog-api-key` và URL hoàn toàn không chứa `?key=`.
  7. `test_dirty_llm_json_output_handling`: Kiểm tra parser bóc tách tốt chuỗi bọc trong ````json ... ```` kèm văn bản thừa và tự fallback về `source_text` khi LLM trả thiếu khối.
  8. `test_free_credits_anti_abuse_verified_once_only`: Kiểm tra tài khoản `email_verified=False` nhận 0 credit; sau khi `email_verified=True` nhận đúng `DEFAULT_FREE_CREDITS` 1 lần duy nhất dù đăng nhập lại nhiều lần.
  9. `test_per_user_rate_limiter_returns_429`: Kiểm tra giới hạn tần suất theo từng user trả HTTP 429 khi vượt ngưỡng.

### 3.3. Chạy thử Server chính ở chế độ phát triển
```powershell
cd comic-translate-vn\server
uvicorn main:app --host 127.0.0.1 --port 8000
```
Kiểm tra healthcheck ở cửa sổ PowerShell khác:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/healthz" -Method Get
```
