# 📖 Comic Translate VN

Hệ thống dịch truyện tranh trực tiếp trên trình duyệt sang tiếng Việt, hỗ trợ toàn diện **Manga Nhật Bản (RTL)**, **Manhua Trung Quốc**, và **Manhwa/Webtoon Hàn Quốc (LTR)** với công nghệ AI tiên tiến (PaddleOCR + Google Gemini LLM).

---

## 🌟 Tính năng nổi bật

- **Chuyển đổi chiều đọc linh hoạt (Reading Direction):**
  - `📖 Manga (RTL)`: Tự động sắp xếp các bóng thoại từ **Phải sang Trái**, trên xuống dưới cho Manga Nhật và Manhua Trung.
  - `📜 Manhwa (LTR)`: Sắp xếp từ **Trái sang Phải** cho Webtoon cuộn dọc.
  - Tự động nhận diện hướng đọc theo tên miền (hivetoon, webtoon, baozimh...) và lưu cấu hình bền vững vào `chrome.storage`.
- **Thuật toán Gom cụm Tọa độ Đọc tự nhiên (Vertical Overlap Clustering):**
  - Nhóm các bóng thoại cùng hàng ngang dựa trên tỷ lệ giao thoa chiều dọc ($\ge 30\%$).
  - Nối liền ngữ cảnh các câu thoại bị tác giả chia cắt ra nhiều bóng thoại liền kề, loại bỏ triệt để hiện tượng dịch ngắt cụt câu.
- **Tối ưu Bounding Box dọc (Vertical Bubble) cho chữ Latin:**
  - Tự động phát hiện khung chữ dọc của CJK (`height / width > 1.4`).
  - Mở rộng chiều rộng (`1.6x - 2.2x`) và căn giữa lại theo trọng tâm cũ, tính toán font-size động (Auto-scaling) đảm bảo chữ tiếng Việt không bị bẻ gãy từng ký tự trên 1 dòng.
- **Prompt LLM Dịch Truyện Tranh Chuyên Sâu:**
  - Tự động sửa chữa lỗi nhận diện nét chữ Hán của OCR dựa trên ngữ cảnh toàn trang.
  - Xưng hô tự nhiên theo văn phong đời thường (`tôi - cậu`, `con bé - nhỏ đó`, `anh - em`), bảo toàn cảm xúc cảm thán (`!`, `?`, `...`).
  - Ràng buộc ánh xạ ID 1-1, chống 100% nguy cơ lệch thoại nhân vật.
- **Hệ thống Cache & Idempotency Thông minh:**
  - Tra cứu cache theo `(user_id, image_hash_direction, lang_pair)`, tiết kiệm chi phí API và phản hồi tức thì khi cuộn lại trang cũ.
  - Tách biệt cache giữa chế độ RTL và LTR.

---

## 🏗️ Kiến trúc Hệ thống

```
comic-translate-vn/
├── extension/          # Chrome Extension Manifest V3 (WXT + TypeScript + Vitest)
├── server/             # Backend API Gateway (FastAPI + SQLite + Gemini / DeepSeek)
├── ocr_service/        # Microservice OCR nội bộ (FastAPI + PaddleOCR v4 / PP-OCR)
├── phase0/             # Nghiên cứu thử nghiệm đánh giá độ chính xác OCR
├── phase1a/            # Benchmark tốc độ và kiểm thử ghép lát cắt Webtoon
└── tests/              # Bộ kiểm thử tích hợp toàn diện
```

---

## 🚀 Hướng dẫn Cài đặt & Chạy cục bộ

### 1. Yêu cầu hệ thống
- **Python:** 3.10 – 3.12
- **Node.js:** 18+ và npm / pnpm
- Khóa API Google Gemini từ [Google AI Studio](https://aistudio.google.com/)

---

### 2. Cài đặt & Khởi động OCR Service

```powershell
cd ocr_service
pip install -r requirements.txt
cp .env.example .env
# Chạy OCR service trên cổng 8001
uvicorn main:app --host 127.0.0.1 --port 8001
```

---

### 3. Cài đặt & Khởi động Backend Server

```powershell
cd ../server
pip install -r requirements.txt
cp .env.example .env
```

Chỉnh sửa file `server/.env`:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-flash
OCR_SERVICE_URL=http://127.0.0.1:8001
OCR_INTERNAL_SECRET=dev-secret-key-123
DEBUG=true
```

Khởi động server trên cổng 8000:
```powershell
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

### 4. Build & Nạp Chrome Extension

```powershell
cd ../extension
npm install
npm run build
```

**Nạp Extension vào Chrome / Edge / Brave:**
1. Truy cập `chrome://extensions/` trên trình duyệt.
2. Bật công tắc **Developer mode** (Chế độ dành cho nhà phát triển) ở góc trên bên phải.
3. Bấm **Load unpacked** (Tải tiện ích đã giải nén).
4. Chọn thư mục: `extension/.output/chrome-mv3`.

---

## 🧪 Kiểm thử (Testing)

### Kiểm thử Backend & Thuật toán Thứ tự đọc
```powershell
$env:PYTHONPATH="server"; pytest server/tests
# 14 tests pass (test_reading_order, test_server_phase2)
```

### Kiểm thử Extension & Typography Tiếng Việt
```powershell
npm --prefix extension run test:unit
# 13 tests pass (134/134 ký tự tiếng Việt có dấu NFC, geometry scaling, queue)
```

---

## 📌 Các phím tắt & Thao tác trên Extension

| Nút bấm trên Floating Toolbar | Chức năng |
| :--- | :--- |
| `[ 📖 Manga (RTL) ]` / `[ 📜 Manhwa (LTR) ]` | Chuyển đổi hướng đọc tự nhiên giữa Manga (Phải $\to$ Trái) và Webtoon (Trái $\to$ Phải). |
| `Dịch toàn bộ khi cuộn` | Tự động dịch các trang truyện khi người dùng cuộn tới gần tầm nhìn (Viewport). |
| `Xem bản gốc / Bản dịch` | Bật/tắt nhanh lớp phủ dịch thuật của toàn bộ trang trên màn hình. |
| `Ngữ cảnh truyện` | Mở drawer nhập lưu ý xưng hô / bối cảnh nhân vật để AI dịch sát cốt truyện hơn. |
| `Debug Selector` | Thanh công cụ kiểm tra selector CSS của ảnh truyện trên website mới. |

---

## 📄 License

Dự án được phát triển phục vụ mục đích nghiên cứu và hỗ trợ cộng đồng đọc truyện tranh Việt Nam.
