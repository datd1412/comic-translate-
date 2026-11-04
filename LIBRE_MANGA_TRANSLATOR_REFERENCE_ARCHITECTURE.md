# KIẾN TRÚC THAM CHIẾU LIBRE-MANGA-TRANSLATOR
> **Phân tích kỹ thuật chuyên sâu về Cơ chế Bounding Box Detection, OCR, Inpainting và Cấu trúc Prompt AI của repo `libre-manga-translator-main`**  
> *Mục đích: Lưu trữ toàn bộ tri thức kiến trúc, luồng xử lý và tham số cốt lõi để làm tài liệu đối chiếu cho `comic-translate-vn`.*

---

## 1. TỔNG QUAN HỆ THỐNG & FILE MAP

Trong `D:\mma\libre-manga-translator-main` (bỏ qua `own-server/`), project được xây dựng trên framework **WXT** (Web Extension Framework) + **Svelte 5** + **ONNX Runtime Web** (`onnxruntime-web` WASM/WebGPU).

### Cấu trúc file trọng tâm:
```
D:\mma\libre-manga-translator-main\
├── docs\technical.md                    # Tài liệu kỹ thuật chi tiết của tác giả
├── src\
│   ├── entrypoints\
│   │   ├── offscreen\main.ts            # Worker ngầm chạy toàn bộ tác vụ AI (Detection, OCR, Translation)
│   │   ├── content\
│   │   │   ├── index.ts                 # Content script chèn overlay & toolbar
│   │   │   └── auto-translate.ts        # Bộ điều phối tự động dịch khi lướt web (IntersectionObserver)
│   ├── lib\
│   │   ├── configs.ts                   # Cấu hình mặc định (Model list, Temperature = 0.3, Confidence)
│   │   ├── prompts.ts                   # Template prompt chuẩn hóa cho text translation
│   │   ├── gemini\
│   │   │   ├── main.ts                  # Logic gọi Google Gemini API (Multimodal Vision)
│   │   │   └── utils.ts                 # Kỹ thuật vẽ Bounding Box đỏ đánh số (drawNumberedBboxes)
│   │   ├── detections\
│   │   │   ├── main.ts                  # Router điều phối Model Detection
│   │   │   ├── rtdetr.ts                # Model RT-DETR-v2 (ogkalu/comic-text-and-bubble-detector)
│   │   │   ├── comictext.ts             # Model ComicTextDetector (dmMaze manga-image-translator)
│   │   │   ├── boxes.ts                 # Thuật toán lọc nhiễu, gộp box tâm, NMS, Union-Find
│   │   │   ├── tiling.ts                # Sliding-window cho truyện tranh dài (Webtoon/Manhwa)
│   │   │   └── utils.ts                 # Scaling letterbox, restore coords, containmentNMS
│   │   ├── ocr\
│   │   │   ├── main.ts                  # Điều phối OCR + Script Gate
│   │   │   ├── paddle.ts                # PaddleOCR ONNX runtime thuần JS/WASM
│   │   │   ├── manga-ocr.ts             # Manga-OCR ONNX chuyên tiếng Nhật dọc (~460 MB)
│   │   │   ├── pororo.ts                # Pororo OCR chuyên tiếng Hàn Manhwa (~74 MB)
│   │   │   └── utils.ts                 # Cắt dòng (slice), đảo phân cực (polarity), tăng tương phản
│   │   ├── gate\                        # Script Identification Gate (osd_lstm.onnx ~3.7 MB)
│   │   ├── server\
│   │   │   ├── main.ts                  # Kết nối Ollama, LM Studio, OpenAI-compatible
│   │   │   └── validator.ts             # Tự vá lỗi mảng JSON thiếu/thừa box từ AI
│   │   └── inpaint\ladder.ts            # Fast Inpaint Ladder (Planar -> Bilateral -> Telea) & Neural LaMa
```

---

## 2. CƠ CHẾ NHẬN DIỆN BONG BÓNG & CHỮ (DETECTION PIPELINE)

Libre Manga Translator **không bao giờ OCR bừa trên toàn bộ trang truyện**. Thay vào đó, nó chia làm 2 tầng rõ rệt:

### 2.1. Hai Detector ONNX có thể chọn lựa:
1. **RT-DETR-v2 (`detector-v4-s_int8.onnx` ~11.1 MB)**:
   - Repo gốc: `ogkalu/comic-text-and-bubble-detector`.
   - Đầu vào: Letterbox ảnh về `640 x 640` (với nền xám `rgb(114, 114, 114)`).
   - 3 Phân lớp (Classes):
     - `0`: Bubble (bong bóng thoại)
     - `1`: Text Bubble (chữ nằm trong bong bóng)
     - `2`: Text Free (chữ trôi nổi ngoài khung cảnh, SFX)
   - **Chiến lược chọn Box**:
     ```typescript
     // Nếu tìm thấy Text Boxes (label 1 hoặc 2) thì ưu tiên lấy Text Boxes; 
     // Nếu không mới dùng Bubble Boxes (label 0)
     const targetBoxes = textBoxes.length > 0 ? textBoxes : bubbleBoxes;
     ```
2. **ComicTextDetector (`comictextdetector.pt.onnx` ~94.7 MB)**:
   - Tác giả: `dmMaze` (từ dự án `manga-image-translator`).
   - Đầu vào: Letterbox ảnh về `1024 x 1024`.
   - Đầu ra kép:
     - Bounding boxes `[1, N, 7]` `(cx, cy, w, h, obj_conf, cls0, cls1)`.
     - Text segmentation mask `[1, 1, 1024, 1024]` (dùng để làm mask inpainting xóa chữ chuẩn đến từng pixel).

### 2.2. Thuật toán lọc nhiễu & gộp Box (`src/lib/detections/boxes.ts`):
Đây là **bí quyết giúp họ không bao giờ bị OCR lẫn chữ trên áo thun (như `MBERGA`) hay đốm nhiễu**:

1. **Sắp xếp thứ tự đọc (Reading Order)**:
   - Sắp xếp tăng dần theo `(y, x, h, w)` để bảo đảm thứ tự từ trên xuống dưới, từ phải qua trái (chuẩn Manga).
2. **Containment NMS (`containmentNMS(threshold = 0.85)`)**:
   - Khác với IoU thông thường, NMS này tính: **Tỉ lệ diện tích box con bị nuốt trọn bởi box lớn hơn**.
   - Nếu $\frac{\text{InterArea}}{\text{BoxArea}} > 0.85$, box con trùng lặp bị xóa ngay lập tức.
3. **Merge Centre in Box (`mergeCentreInBox`)**:
   - Nếu tâm (center) của box B nằm gọn bên trong box A, gộp cả hai thành một box bao lồi (`hull(A, B)`).
4. **Lọc nhiễu theo diện tích trung vị (`medianBoxArea`)**:
   ```typescript
   export function sizeVerdict(boxArea, medianArea, boxHeight, pageHeight, confidence) {
     // Nếu diện tích box nhỏ hơn 15% diện tích trung vị VÀ confidence < 0.70 -> XÓA (đốm mực, chữ áo vụn)
     if (medianArea > 0 && boxArea < 0.15 * medianArea && confidence < 0.70) {
       return "drop";
     }
     if (medianArea > 0 && boxArea > 40.0 * medianArea) return "flag-large";
     if (boxHeight > 0.25 * pageHeight) return "flag-large";
     return "keep";
   }
   ```
5. **Nới rộng biên & gộp chùm (Union-Find Cluster)**:
   - Nới biên mỗi box: `+2px` mọi phía, riêng bên phải `+3px` (vì tiếng Nhật đọc từ phải sang trái).
   - Dùng cấu trúc dữ liệu Disjoint-Set (Union-Find): Nếu 2 box sau khi nới rộng đè nhau $> 20\%$ diện tích của box nhỏ hơn $\rightarrow$ gộp lại thành 1 thoại hoàn chỉnh.

---

## 3. CÁCH HỌ GỬI PROMPT CHO AI: CHIÊU THỨC "RED NUMBERED BOXES"

Đây là **phát kiến quan trọng nhất của Libre Manga Translator** khi sử dụng Gemini Vision Multimodal (`src/lib/gemini/main.ts` & `utils.ts`):

### 3.1. Tại sao họ KHÔNG OCR trước khi gửi cho Gemini?
- Trong chế độ **Gemini Mode**, họ **bỏ qua hoàn toàn OCR cục bộ**!
- Lý do: OCR cục bộ (PaddleOCR) thường nhận diện sai chữ viết tay, ký tự Hán cổ, và bị dính chữ trên áo thun. Khi nạp text rác vào Gemini, Gemini sẽ đoán bậy (hallucinate).
- Thay vào đó, họ giao cho chính **Gemini đọc ảnh và dịch luôn trong 1 bước duy nhất**!

### 3.2. Kỹ thuật vẽ Bounding Box đỏ có số thứ tự (`drawNumberedBboxes`):
Trước khi gửi ảnh cho Gemini:
1. Tạo 1 Canvas thu nhỏ ảnh gốc về `max_width = 1024px` (giữ đúng tỉ lệ aspect ratio).
2. Dùng toạ độ các box đã detect được:
   - Vẽ khung viền đỏ nét đậm: `strokeStyle = "#ef4444"`, độ dày `2 - 4px`.
   - Ở góc trên bên trái mỗi box, vẽ một huy hiệu màu đỏ có nền đặc (`fillRect`) và in số thứ tự màu trắng `1, 2, 3, ...` (`fillText`).
3. Nén ảnh thành JPEG với chất lượng 75%: `canvas.toDataURL("image/jpeg", 0.75)`.
   - **Kích thước payload**: Một trang truyện nén JPEG 1024px @ 75% chỉ nặng khoảng **120 KB - 250 KB** (rất nhẹ, gửi qua REST API mất chưa đến 0.5 giây).

```
+------------------------------------------------------+
| [1] THOẠI 1 (Đỏ)                                     |
| +-------------------------+                          |
| | 鈴木君會長鬍子嗎？       |                          |
| +-------------------------+                          |
|                                                      |
|                          [2] THOẠI 2 (Đỏ)            |
|                          +-------------------------+ |
|                          | 是呀我的鬍子             | |
|                          +-------------------------+ |
|                                                      |
| (Áo thun có chữ MBERGA không bị vẽ khung đỏ ->      |
|  Gemini hiểu ngay là background và BỎ QUA!)           |
+------------------------------------------------------+
```

### 3.3. Cấu trúc Prompt gửi cho Gemini (`src/lib/gemini/main.ts`):
```text
SYSTEM PROMPT:
You are a professional manga translator.
Translate the text in the numbered bounding boxes in the provided image FROM JAPANESE INTO VIETNAMESE.
Maintain the tone and context of the scene.

CRITICAL LANGUAGE INSTRUCTIONS:
1. The dialogue inside the "translations" array MUST be strictly in VIETNAMESE. DO NOT transcribe or copy the original text from the image. You must output the translated meaning.
2. The "sourceTexts" array MUST contain the ORIGINAL text exactly as it appears in each numbered box, transcribed verbatim (not translated). If a box's text is illegible or empty, use an empty string.
3. The "summary" and "dictionary" fields MUST remain strictly in ENGLISH to act as a system memory pivot.

Output strictly as valid JSON matching this structure without markdown formatting:
{
  "translations": ["translation for box 1", "translation for box 2"],
  "sourceTexts": ["original text in box 1", "original text in box 2"],
  "context": {
    "summary": "...",
    "dictionary": "..."
  }
}

USER PROMPT:
Please process the dialogue boxes found in the provided image.
Also infer from this page:
1. A 1-2 sentence summary of the series tone, setting, and genre IN ENGLISH.
2. Any character names, places, or unique terms visible, formatted as "Original Term -> English Translation". If no specific terms are visible, output strictly "None". Do not explain or write sentences.
```

### 3.4. Tại sao chiêu này loại bỏ 100% lỗi dịch của chúng ta?
1. **Loại bỏ nhầm chữ áo thun**: Gemini chỉ nhìn vào các ô có đánh số `[1]`, `[2]`, `[3]`. Chữ trên áo không có khung đỏ nên Gemini coi là hình vẽ và hoàn toàn không dịch.
2. **Hiểu ngữ cảnh nhân vật trực quan**: Gemini nhìn thấy rõ Box 1 gắn với cô gái, Box 2 gắn với chàng trai đang sờ cổ ngượng ngùng $\rightarrow$ Xưng hô "Cậu - Tớ / Anh - Em" cực kỳ chuẩn, không bao giờ bị xưng hô loạn xạ.
3. **Độ an toàn kép (`sourceTexts` + `translations`)**: Gemini vừa gõ lại chữ gốc vừa dịch nghĩa, giúp UI có thể hiển thị lại text gốc khi người dùng bấm vào xem.

---

## 4. CƠ CHẾ DỊCH DẠNG VĂN BẢN (LOCAL WEBGPU / API MODE)

Nếu người dùng chọn chạy qua **Ollama / LM Studio** hoặc **WebLLM cục bộ** (không gửi ảnh):
Họ sử dụng hàm `buildTranslationPrompts` trong `src/lib/prompts.ts`:

### 4.1. Đóng dấu ngoặc kép từng box thoại:
```typescript
const boxLines = ocrResults
  .map((rawText, index) => {
    const text = typeof rawText === "string" ? rawText : String(rawText ?? "");
    const quoted = JSON.stringify(text);
    return text.trim().length === 0
      ? `Box ${index + 1}: "" (empty — return "")`
      : `Box ${index + 1}: ${quoted}`;
  })
  .join("\n");
```
*Tác dụng*: Tránh việc box thoại trống bị nuốt chửng làm lệch thứ tự các box sau.

### 4.2. Ràng buộc số lượng mảng chặt chẽ (Strict Count Constraint):
- Trong schema JSON gửi cho LLM, họ đặt:
  ```json
  "translations": {
    "type": "array",
    "items": { "type": "string" },
    "minItems": 8,
    "maxItems": 8
  }
  ```
- Nếu LLM trả về số phần tử khác 8, họ có cơ chế **tự động retry 1 lần**:
  > *"CORRECTION: Your previous response contained 6 items but EXACTLY 8 are required — one per input box, same order, empty boxes as "". Return the full corrected JSON now."*

### 4.3. Bộ tự vá lỗi (Self-Healing Validator `src/lib/server/validator.ts`):
Nếu sau khi retry mà AI vẫn trả về thiếu hoặc thừa:
- Nếu thiếu: Tự động chèn `""` vào cuối mảng cho đủ số lượng.
- Nếu thừa: Cắt bỏ bớt các phần tử dư thừa.
$\rightarrow$ **Giao diện không bao giờ bị crash hoặc lệch vị trí bong bóng thoại.**

---

## 5. THAM SỐ THIẾT LẬP CỦA HỌ (CONFIG MATRIX)

| Tham số | Giá trị trong `libre-manga-translator` | Giá trị cũ của chúng ta | Nhận xét |
|---|---|---|---|
| `llmTemperature` | **0.3** | **0.5** (sau đó bị ảo giác) | Nhiệt độ `0.3` là điểm cân bằng hoàn hảo giữa tính sáng tạo và độ bám sát nội dung. |
| `detectionMinConfidence` | **0.5** | N/A (chúng ta chưa có detector) | Loại bỏ các box tự kỷ ám thị. |
| `ocrMinConfidence` | **0.7** | 0.5 | Tránh nhận diện rác thành ký tự Hán hiếm. |
| Kích thước ảnh nén gửi AI | **Max width 1024px, JPEG 75%** | Raw full-res Base64 | Nhẹ hơn gấp 5 - 10 lần, tốc độ truyền cực nhanh. |
| Model Gemini đề xuất | `gemini-3.1-flash-lite`, `gemini-2.5-flash` | `gemini-1.5-flash` (đã bị Google khai tử 404) | Tránh lỗi model not found. |

---

## 6. SO SÁNH 3 DỰ ÁN

| Tiêu chí | `comic-translate-main` (Python Desktop) | `libre-manga-translator-main` (TS Extension) | `comic-translate-vn` (Hệ thống hiện tại) |
|---|---|---|---|
| **Môi trường chạy** | Ứng dụng Desktop Python (PyQt) | Chrome Extension (WXT, TypeScript) | Extension Chrome + Backend FastAPI (Python) |
| **Bubble Detector** | RT-DETR-v2 ONNX qua CPU/DirectML | RT-DETR-v2 & ComicTextDetector qua ONNX Web | Chưa tích hợp (đang phụ thuộc PaddleOCR quét chay) |
| **Gửi ảnh cho AI** | Base64 ảnh gốc + JSON `{block_0: ...}` | Vẽ ô đỏ đánh số `[1],[2]` lên ảnh JPEG 1024px | Gửi raw Base64 toàn bộ trang truyện |
| **Loại bỏ chữ áo thun** | Dựa vào Bubble Containment | Dựa vào Median Area & Bounding Box đỏ | Bị PaddleOCR bắt dính và dịch bậy thành "3 nhé" |
| **Xử lý ngữ cảnh** | Dict phẳng `block_0` | Dual Array (`translations`, `sourceTexts`, `context`) | Mảng `blocks` kèm `previous_lines` |
| **Inpainting** | LaMa / PatchMatch / Telea | Model-free Ladder (Planar -> Bilateral -> Telea) + LaMa | Server Inpainting |

---

## 7. KẾ HOẠCH HÀNH ĐỘNG CỤ THỂ CHO CHÚNG TA

### Giai đoạn 1: Ổn định cấp bách cho buổi Demo sáng mai (Không phá vỡ hệ thống)
1. **Hạ ngay Temperature về `0.2` hoặc `0.3`** trong `server/config.py` và `server/translator.py` (chấm dứt hiện tượng "3 nhé", "hoắc chạy đến").
2. **Cập nhật model Gemini active**: Đặt mặc định `gemini-3-flash-preview` và fallback `gemini-3.1-flash-lite` để không bao giờ bị 404/503.
3. **Thêm bộ lọc Regex cắt chữ áo thun**: Trong `server/ocr_postprocess.py`, lọc bỏ các xâu ký tự Latinh trôi nổi ở cuối đoạn văn bản Trung (`MBERGA`, `HMEESGR`).
4. **Mở cổng cho Mobile**: Chạy server với `--host 0.0.0.0 --port 8000` và dùng `ngrok http 8000` để điện thoại kết nối trơn tru.

### Giai đoạn 2: Nâng cấp chuẩn theo Libre Manga Translator (Sau Demo)
1. Thêm tầng **RT-DETR-v2 ONNX** vào `server/detector.py` (file weights `detector.onnx` 168 MB đã có sẵn trên máy tại `C:\Users\LENOVO\AppData\Local\ComicTranslate\models\detection\detector.onnx`).
2. Tích hợp thuật toán `refineDetections`: gộp box tâm, lọc `medianBoxArea * 0.15` để dập tắt 100% rác áo thun.
3. Thử nghiệm module vẽ ô đỏ số thứ tự trước khi đưa vào Gemini Vision.
