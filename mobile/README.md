# ComicTranslate VN - Mobile App (MMA301 Project)

Ứng dụng Đọc truyện tranh & Dịch trực tiếp bằng AI (React Native Expo Go) kết nối với Backend Server chạy trên máy tính (FastAPI + Gemini AI + OCR).

Khung dịch mobile dùng tọa độ `[x1, y1, x2, y2]` trên ảnh gốc. Backend trả thêm
`image_width` và `image_height` để quy đổi chính xác khi website hiển thị thumbnail.
Mobile gửi `layout_mode=text_regions`: OCR tìm hình chữ nhật bao quanh từng cụm
chữ, nhận diện nội dung trong vùng đó và dịch; bản dịch được đặt lại vào chính
khung chữ nhật ấy với nền trắng che chữ gốc. Không dùng biên ngoài bóng thoại
làm vùng phủ. Cache được tách theo chế độ để không lấy nhầm khung cũ.
Chữ được đo bằng font thực tế và co trong giới hạn 9–16 CSS px, không nới khung
che tranh. Nếu nội dung không vừa, khung hiển thị `…`; chạm vào khung để đọc toàn
bộ bản dịch và chữ gốc. Nút **Xem ảnh gốc** ẩn lớp dịch trên tất cả ảnh đã dịch.
Lớp phủ được đặt ngoài DOM của reader để tránh bị AMP/lazy-loader ẩn. Khi dịch
mới, app tự hiện bản dịch và chờ WebView xác nhận đã vẽ khung trước khi báo thành công.

Bấm **Dịch khi cuộn** để bật xử lý tuần tự các ảnh đang hiện và sát màn hình.
Cuộn lên hoặc xuống để dịch tiếp; ảnh đã xử lý không được gửi lặp trong cùng
ngữ cảnh dịch. **Mỗi ảnh vẫn tính credit theo backend**. Bấm **Dừng tự dịch** để
ngừng gửi ảnh mới (ảnh đang xử lý sẽ hoàn tất). Chế độ tự dừng khi chuyển trang,
đổi cấu hình dịch, hết credit hoặc có lỗi; các lớp dịch đã vẽ vẫn được giữ lại.

Kiểm tra hồi quy layout từ thư mục gốc:

```bash
node --test scripts/mobile-overlay.test.cjs
```

Bài kiểm tra dùng Playwright trong `extension/node_modules` và Chrome đã cài;
có thể đặt `PLAYWRIGHT_CHANNEL=msedge` để dùng Edge. Kiểm tra các chiều rộng
320/390/430/780px, thay đổi kích thước, câu dài, ảnh cuộn dài và nhiều ảnh cùng parent.
Sau khi cập nhật, khởi động lại backend và reload app/trang truyện để nạp script mới.

---

## 🏗️ Kiến Trúc Hệ Thống (Client - Server)

```
┌─────────────────────────────────────────────────────────────────┐
│               1. PC LOCAL BACKEND SERVER (FastAPI)              │
│                     http://192.168.2.39:8000                    │
│                                                                 │
│  - Xử lý nhận diện chữ & bong bóng thoại (PaddleOCR / Vision)   │
│  - Dịch sang tiếng Việt tự nhiên (Google Gemini AI)             │
│  - Quản lý tài khoản, trừ credit theo trang (-2 credit / trang) │
│  - Tạo mã thanh toán VietQR / PayOS chuẩn ngân hàng             │
└───────────────────────────────▲─────────────────────────────────┘
                                │ (RESTful API / Wi-Fi LAN)
┌───────────────────────────────▼─────────────────────────────────┐
│             2. MOBILE APP (React Native + Expo Go)              │
│                                                                 │
│  Tab 1: 🌐 Trình duyệt đọc truyện & Dịch đè bong bóng (WebView)  │
│  Tab 2: 💳 Nạp Credit qua mã VietQR PayOS (FlatList + Notif)   │
│  Tab 3: 👤 Tài khoản, Đăng nhập Dev & Lịch sử đọc (SQLite)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Đối Chiếu Chuẩn Syllabus Môn Học MMA301

| Yêu Cầu Syllabus MMA301 | Triển Khai Thực Tế Trong Ứng Dụng Này |
| :--- | :--- |
| **Expo Go** | Chạy 100% trực tiếp trên Expo Go (quét mã QR là lên). |
| **Components & Styling** | Custom Address Bar, Floating Action Buttons, Dialog Bong bóng thoại manga bo góc, Card hiển thị gói nạp. |
| **Navigation** | Bottom Tabs (`@react-navigation/bottom-tabs`) 3 màn hình: Browser, Topup, Profile. |
| **State Management (Redux)** | Redux Toolkit (`authSlice`, `settingsSlice`, `historySlice`) quản lý credit, IP server, user info. |
| **FlatList & SectionList** | FlatList danh sách gói nạp PayOS, FlatList lịch sử đọc truyện từ SQLite. |
| **Local Database (SQLite)** | `expo-sqlite` lưu trữ lịch sử các chương truyện đã đọc & bookmark offline. |
| **Mobile Notifications** | `expo-notifications` bắn thông báo đẩy khi thanh toán VietQR thành công & khi dịch xong. |
| **RESTful API & AI Backend** | Kết nối mạng LAN tới FastAPI server trên PC để gọi Gemini AI. |

---

## 🚀 Hướng Dẫn Chạy Ứng Dụng

### Bước 1: Khởi động Server Backend trên PC
Mở một cửa sổ Terminal tại thư mục gốc:
```bash
python server.py
```
> Server sẽ tự động phát hiện IP Wi-Fi của máy (ví dụ: `http://192.168.2.39:8000`).

### Bước 2: Khởi động App Mobile Expo Go
Mở một cửa sổ Terminal khác:
```bash
cd mobile
npx expo start
```
- Mở ứng dụng **Expo Go** trên điện thoại (Android hoặc iOS).
- Quét mã QR hiển thị trên màn hình máy tính để mở App.

---

## 💡 Hướng Dẫn Trình Bày Chấm Điểm (Dành Cho Thầy/Cô)

1. **Đăng nhập 1-Click (Chế độ Dev):**
   - Vào **Tab 3: Tài khoản** -> Bấm nút màu xanh lá **"⚡ Đăng nhập nhanh (Chế độ Dev - 20 Credit)"**.
   - Tài khoản được cấp ngay 20 credit để chấm điểm mà không cần gõ mật khẩu.
2. **Trải nghiệm Dịch đè Bong bóng:**
   - Vào **Tab 1: Trình duyệt** -> Bấm vào link nhanh `🥟 Baozi Manhua` hoặc `🐝 HiveToons`.
   - Bấm nút nổi **"⚡ Dịch trang (-2 Cr)"**.
   - App sẽ gửi yêu cầu lên server PC -> Server trả về tọa độ bong bóng và tiếng Việt dịch bởi Gemini -> Bong bóng tiếng Việt màu trắng chữ đen viền đậm sẽ đè trực tiếp lên tranh truyện.
   - Bấm nút **"Xem ảnh gốc / Xem bản dịch"** để so sánh.
3. **Nạp Credit VietQR & Bắn Notification:**
   - Vào **Tab 2: Nạp Credit**.
   - Bấm chọn bất kỳ gói nào (50k, 100k, 200k).
   - Modal VietQR hiển thị mã QR và thông tin chuyển khoản ngân hàng.
   - Bấm nút **"⚡ Xác nhận đã thanh toán (Dev Mode)"** -> Điện thoại bắn **Notification**: *"Bạn vừa nạp thành công X credit"* và số dư Redux tự động nhảy tăng lên.
4. **Kiểm tra SQLite Database:**
   - Quay lại **Tab 3: Tài khoản** -> Kéo xuống mục **"Lịch sử đọc & dịch (SQLite)"** để thấy danh sách các trang đã duyệt được lưu offline trong máy.

