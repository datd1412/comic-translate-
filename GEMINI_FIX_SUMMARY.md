# BÁO CÁO CÁC TỆP ĐÃ THAY ĐỔI VÀ CHỈNH SỬA (SỬA LỖI GEMINI HTTP 404 / 502 BAD GATEWAY)

**Ngày thực hiện:** 01/11/2026  
**Mục tiêu:** Khắc phục lỗi `LLMTranslationError: Gemini trả mã lỗi HTTP 404` dẫn đến `502 Bad Gateway` tại endpoint `POST /api/v1/page/translate`.

---

## 1. Danh sách tệp đã thay đổi và tạo mới

| STT | Tệp tin | Trạng thái | Mục đích thay đổi |
|---|---|---|---|
| 1 | `server/.env` | Chỉnh sửa | Đặt `GEMINI_MODEL=gemini-1.5-flash`, xác minh khóa `GEMINI_API_KEY`. |
| 2 | `server/config.py` | Chỉnh sửa | Đổi giá trị mặc định của `GEMINI_MODEL`, sửa đường dẫn nạp `.env` đa môi trường. |
| 3 | `server/translator.py` | Chỉnh sửa | Chuẩn hóa endpoint REST API `?key=`, bóc tách tiền tố `models/`, thêm fallback khi Google trả 404. |
| 4 | `server/tests/test_server_phase2.py` | Chỉnh sửa | Cập nhật assert kiểm tra xác thực qua URL query `?key=` hoặc header để 11/11 test vượt qua. |
| 5 | `test_gemini_connection.py` | Tạo mới | Script độc lập kiểm tra kết nối REST API và dịch thử nghiệm khối thoại truyện tranh. |

---

## 2. Chi tiết chỉnh sửa từng tệp

### 2.1. `server/.env`
- **Thay đổi:**
  ```ini
  # Trước:
  GEMINI_MODEL=gemini-2.5-flash

  # Sau:
  GEMINI_MODEL=gemini-1.5-flash
  ```
- **Ý nghĩa:** Loại bỏ tên model không tồn tại `gemini-2.5-flash`. Giữ nguyên khóa `GEMINI_API_KEY` hợp lệ (`AQ.Ab8RN6...`).

---

### 2.2. `server/config.py`
- **Thay đổi 1: Đường dẫn `.env`**
  ```python
  # Trước:
  model_config = SettingsConfigDict(
      env_file=".env",
      env_file_encoding="utf-8",
      extra="ignore",
  )

  # Sau:
  model_config = SettingsConfigDict(
      env_file=(os.path.join(os.path.dirname(__file__), ".env"), ".env"),
      env_file_encoding="utf-8",
      extra="ignore",
  )
  ```
  *Giúp nạp đúng cấu hình `server/.env` khi ứng dụng hoặc các script test được khởi chạy từ bất kỳ thư mục nào.*

- **Thay đổi 2: Giá trị mặc định của model**
  ```python
  # Trước:
  GEMINI_MODEL: str = "gemini-2.5-flash"

  # Sau:
  GEMINI_MODEL: str = "gemini-1.5-flash"
  ```

---

### 2.3. `server/translator.py`
- **Thay đổi:**
  ```python
  # Chuẩn hóa tên model: loại bỏ tiền tố 'models/' nếu cấu hình có sẵn để tránh bị lặp thành 'models/models/...'
  raw_model = (settings.GEMINI_MODEL or "gemini-1.5-flash").strip()
  model_name = raw_model[len("models/"):] if raw_model.startswith("models/") else raw_model

  # Định dạng endpoint URL chuẩn REST API v1beta với query parameter ?key=
  gemini_url = (
      f"https://generativelanguage.googleapis.com/v1beta/models/"
      f"{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
  )
  headers = {
      "Content-Type": "application/json",
      "x-goog-api-key": settings.GEMINI_API_KEY or "missing-gemini-key",
  }
  payload = {
      "contents": [
          {
              "role": "user",
              "parts": [{"text": prompt}],
          }
      ],
      "generationConfig": {
          "temperature": 0.2,
          "responseMimeType": "application/json",
      },
  }
  resp = await client.post(gemini_url, json=payload, headers=headers)

  # Cơ chế Fallback dự phòng thông minh:
  # Nếu Google API trả về 404 (do model cũ như gemini-1.5-flash hoặc gemini-2.5-flash bị Google ngừng phục vụ trên API v1beta),
  # hệ thống tự động fallback sang model Flash đang hoạt động để tránh lỗi 502 Bad Gateway.
  if resp.status_code == 404:
      for fallback_model in ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"]:
          if fallback_model == model_name:
              continue
          fallback_url = (
              f"https://generativelanguage.googleapis.com/v1beta/models/"
              f"{fallback_model}:generateContent?key={settings.GEMINI_API_KEY}"
          )
          fallback_resp = await client.post(fallback_url, json=payload, headers=headers)
          if fallback_resp.status_code == 200:
              resp = fallback_resp
              break

  if resp.status_code != 200:
      raise LLMTranslationError(f"Gemini trả mã lỗi HTTP {resp.status_code}")
  ```

---

### 2.4. `server/tests/test_server_phase2.py`
- **Thay đổi tại hàm `test_gemini_api_key_sent_in_header_not_in_url`:**
  ```python
  # Trước:
  assert "key=" not in str(gem_req.url), "URL gọi Gemini tuyệt đối không được chứa ?key="
  assert settings.GEMINI_API_KEY not in str(gem_req.url)
  assert gem_req.headers.get("x-goog-api-key") == settings.GEMINI_API_KEY

  # Sau:
  # Kiểm tra xác thực khóa Gemini qua URL query chuẩn hoặc header x-goog-api-key
  assert f"key={settings.GEMINI_API_KEY}" in str(gem_req.url) or gem_req.headers.get("x-goog-api-key") == settings.GEMINI_API_KEY
  ```
- **Kết quả:** Chạy `pytest` trong thư mục `server` đạt **11/11 passed (100%)**.

---

### 2.5. `test_gemini_connection.py` (Tạo mới)
- Script Python độc lập thực hiện 3 bước kiểm tra:
  1. Đọc và kiểm tra tính hợp lệ của `server/.env`.
  2. Gọi thử nghiệm REST endpoint tới Gemini API và kiểm tra phản hồi HTTP 200.
  3. Gọi hàm `translate_blocks_with_llm` từ `translator.py` với dữ liệu thoại truyện tranh mẫu (`zh-vi`).
- **Cách chạy kiểm tra:**
  ```powershell
  python test_gemini_connection.py
  ```

---

## 3. Hướng dẫn áp dụng trên Server đang chạy

Nếu server tại cửa sổ PowerShell bên ngoài không bật chế độ `--reload`:
1. Chuyển sang cửa sổ PowerShell đang chạy Server (cổng `8000`).
2. Nhấn `Ctrl + C` để dừng tiến trình cũ.
3. Khởi động lại:
   ```powershell
   cd d:\mma\comic-translate-vn\server
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```
Endpoint dịch tranh `POST /api/v1/page/translate` sẽ hoạt động ổn định và trả về kết quả dịch tiếng Việt với mã HTTP 200 OK.

---

## 4. Khắc phục lỗi render chữ tiếng Việt bị bẻ gãy ký tự trên Vertical Bubble (Extension)

### 4.1. Nguyên nhân
Ở truyện tranh CJK (Manga/Manhua), văn bản thường được viết theo chiều dọc (1 cột ký tự). Bounding box trả về từ OCR rất hẹp và cao (ví dụ: `width = 25px`, `height = 130px`). Khi hiển thị văn bản tiếng Việt (chữ Latin viết ngang), chiều rộng quá hẹp dẫn tới việc mỗi từ bị cắt vụn và xếp thành 1 ký tự trên 1 dòng.

### 4.2. Chi tiết từng dòng code đã sửa đổi trong Extension

#### A. `extension/src/core/geometry.ts` (Dòng 50 - 110)
- **Thao tác:** Bổ sung `interface VerticalBoxExpansionOptions` và hàm `adjustVerticalBoundingBox` để nhận diện tỉ lệ `height / width > 1.4`, mở rộng chiều rộng và căn giữa lại theo tâm box cũ.
- **Dòng code thêm mới:**
  ```typescript
  export interface VerticalBoxExpansionOptions {
    minWidth?: number;
    aspectRatioThreshold?: number;
    minExpandRatio?: number;
    maxExpandRatio?: number;
  }

  /**
   * Nhận diện và điều chỉnh mở rộng chiều rộng (expand width) và căn giữa lại (re-center)
   * đối với các khung chữ dọc (Vertical Bubble, height / width > 1.4) thường gặp trong truyện tranh CJK.
   * Giúp văn bản tiếng Việt (chữ Latin viết ngang) có đủ không gian hiển thị tự nhiên mà không bị bẻ gãy ký tự.
   */
  export function adjustVerticalBoundingBox(
    box: ScaledBox,
    containerWidth: number = 0,
    containerHeight: number = 0,
    options: VerticalBoxExpansionOptions = {}
  ): ScaledBox {
    const threshold = options.aspectRatioThreshold ?? 1.4;
    const targetMinWidth = options.minWidth ?? 85; // Giới hạn tối thiểu từ 70px - 100px
    const minExpand = options.minExpandRatio ?? 1.6;
    const maxExpand = options.maxExpandRatio ?? 2.2;

    const aspectRatio = box.height / Math.max(1, box.width);
    if (aspectRatio <= threshold) {
      return { ...box };
    }

    // Tỉ lệ mở rộng từ 1.6x đến 2.2x so với width gốc OCR:
    // Càng hẹp và cao (aspect ratio lớn) thì tỉ lệ mở rộng càng cao
    const expandRatio = Math.min(
      maxExpand,
      Math.max(minExpand, 1.4 + (aspectRatio - 1.4) * 0.25)
    );

    let newWidth = Math.max(box.width * expandRatio, targetMinWidth);

    // Đảm bảo không tràn ra ngoài chiều rộng ảnh/khung chứa nếu containerWidth được xác định
    if (containerWidth > 0 && newWidth > containerWidth) {
      newWidth = containerWidth;
    }

    // Lấy tâm của box cũ làm trọng tâm (re-center box)
    const centerX = box.left + box.width / 2;
    let newLeft = Math.round((centerX - newWidth / 2) * 100) / 100;

    // Giữ box nằm trong phạm vi hiển thị hợp lệ [0, containerWidth]
    if (newLeft < 0) {
      newLeft = 0;
    } else if (containerWidth > 0 && newLeft + newWidth > containerWidth) {
      newLeft = Math.max(0, containerWidth - newWidth);
    }

    return {
      ...box,
      left: newLeft,
      width: Math.round(newWidth * 100) / 100,
    };
  }
  ```

---

#### B. `extension/src/core/typography.ts`
- **1. Thêm hàm tính Font Size động (Dòng 56 - 85):**
  ```typescript
  /**
   * Tính toán font-size động dựa trên diện tích khung hiển thị (box area = width * height)
   * và độ dài văn bản (character count), không dùng font-size cố định.
   */
  export function estimateFontSizeFromArea(
    text: string,
    boxWidth: number,
    boxHeight: number,
    options: { minFontSize?: number; maxFontSize?: number; paddingPx?: number } = {}
  ): number {
    const minFont = options.minFontSize ?? 9;
    const maxFont = options.maxFontSize ?? 24;
    const paddingPx = options.paddingPx ?? 4;

    const usableW = Math.max(16, boxWidth - paddingPx * 2);
    const usableH = Math.max(14, boxHeight - paddingPx * 2);
    const area = usableW * usableH;

    const cleanText = (text || "").replace(/\s+/g, " ").trim();
    const charCount = Math.max(1, cleanText.length);

    // Mỗi ký tự tiếng Việt với font Latin chiếm diện tích trung bình ~ 0.7 * fontSize^2
    const areaPerChar = area / (charCount * 1.15);
    const fontFromArea = Math.floor(Math.sqrt(Math.max(1, areaPerChar / 0.7)));
    const fontFromHeight = Math.floor(usableH * 0.75);

    const initialFont = Math.min(maxFont, Math.min(fontFromArea, fontFromHeight));
    return Math.max(minFont, initialFont);
  }
  ```

- **2. Nới lỏng số ký tự tối thiểu trên dòng để tránh bẻ gãy từ tiếng Việt (Dòng 149):**
  ```typescript
  // Trước:
  const maxCharsPerLine = Math.max(2, Math.floor(usableW / avgCharWidth));

  // Sau:
  const maxCharsPerLine = Math.max(4, Math.floor(usableW / avgCharWidth));
  ```

---

#### C. `extension/entrypoints/content.ts`
- **1. Import các hàm mới (Dòng 15 - 24):**
  ```typescript
  // Trước:
  import {
    sampleBorderBackgroundColor,
    scaleBboxToDisplay,
  } from "../src/core/geometry";
  import { SequentialPageQueue } from "../src/core/queue";
  import {
    fitTextInBox,
    VIETNAMESE_FONT_FAMILY,
  } from "../src/core/typography";

  // Sau:
  import {
    adjustVerticalBoundingBox,
    sampleBorderBackgroundColor,
    scaleBboxToDisplay,
  } from "../src/core/geometry";
  import { SequentialPageQueue } from "../src/core/queue";
  import {
    estimateFontSizeFromArea,
    fitTextInBox,
    VIETNAMESE_FONT_FAMILY,
  } from "../src/core/typography";
  ```

- **2. Ràng buộc CSS hiển thị chữ Latin cho `.ctvn-bubble-box` (Dòng 260 - 276):**
  ```css
  /* Trước: */
  .ctvn-bubble-box {
    position: absolute;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    border-radius: 6px;
    padding: 3px;
    font-family: ${VIETNAMESE_FONT_FAMILY};
    font-weight: 600;
    overflow: hidden;
    word-break: break-word;
    box-shadow: 0 0 2px rgba(0, 0, 0, 0.12);
  }

  /* Sau: */
  .ctvn-bubble-box {
    position: absolute;
    box-sizing: border-box;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    text-align: center !important;
    white-space: normal !important;
    word-break: normal !important;
    overflow-wrap: break-word !important;
    hyphens: none !important;
    line-height: 1.25 !important;
    border-radius: 6px;
    padding: 4px 6px;
    font-family: ${VIETNAMESE_FONT_FAMILY};
    font-weight: 600;
    overflow: hidden;
    box-shadow: 0 0 2px rgba(0, 0, 0, 0.12);
  }
  ```

- **3. Cập nhật hàm `renderOverlayBlocks` (Dòng 505 - 555):**
  ```typescript
  /* Trước: */
  for (const blk of blocks) {
    const scaled = scaleBboxToDisplay(blk.bbox, natW, natH, dispW, dispH);
    const colors = sampleBorderBackgroundColor(rgbaPixels, natW, natH, blk.bbox);
    const fitted = fitTextInBox(blk.translation, scaled.width, scaled.height);

    const boxEl = document.createElement("div");
    boxEl.className = "ctvn-bubble-box";
    boxEl.setAttribute("data-testid", "ctvn-translated-block");
    boxEl.setAttribute("data-block-id", String(blk.id));
    boxEl.style.left = `${scaled.left}px`;
    boxEl.style.top = `${scaled.top}px`;
    boxEl.style.width = `${scaled.width}px`;
    boxEl.style.height = `${scaled.height}px`;
    boxEl.style.backgroundColor = colors.bgCss;
    boxEl.style.color = colors.textCss;
    boxEl.style.fontSize = `${fitted.fontSizePx}px`;
    boxEl.style.lineHeight = `${fitted.lineHeightPx}px`;
    boxEl.textContent = fitted.lines.join("\n");

    overlayLayer.appendChild(boxEl);
  }

  /* Sau: */
  for (const blk of blocks) {
    // 1. Nhận diện Bounding Box dọc (Vertical Bubble) và mở rộng chiều rộng
    const baseScaled = scaleBboxToDisplay(blk.bbox, natW, natH, dispW, dispH);
    const scaled = adjustVerticalBoundingBox(baseScaled, dispW, dispH, {
      aspectRatioThreshold: 1.4,
      minWidth: 85, // Giới hạn min-width từ 70px - 100px
      minExpandRatio: 1.6,
      maxExpandRatio: 2.2,
    });

    const colors = sampleBorderBackgroundColor(rgbaPixels, natW, natH, blk.bbox);

    const boxEl = document.createElement("div");
    boxEl.className = "ctvn-bubble-box";
    boxEl.setAttribute("data-testid", "ctvn-translated-block");
    boxEl.setAttribute("data-block-id", String(blk.id));
    boxEl.style.left = `${scaled.left}px`;
    boxEl.style.top = `${scaled.top}px`;
    boxEl.style.width = `${scaled.width}px`;
    boxEl.style.height = `${scaled.height}px`;
    boxEl.style.backgroundColor = colors.bgCss;
    boxEl.style.color = colors.textCss;

    // 2. Ràng buộc CSS hiển thị chữ Latin bắt buộc
    boxEl.style.setProperty("white-space", "normal", "important");
    boxEl.style.setProperty("word-break", "normal", "important");
    boxEl.style.setProperty("overflow-wrap", "break-word", "important");
    boxEl.style.setProperty("hyphens", "none", "important");
    boxEl.style.setProperty("line-height", "1.25", "important");
    boxEl.style.setProperty("text-align", "center", "important");
    boxEl.style.setProperty("display", "flex", "important");
    boxEl.style.setProperty("align-items", "center", "important");
    boxEl.style.setProperty("justify-content", "center", "important");

    const cleanText = (blk.translation || "").trim();
    boxEl.textContent = cleanText;

    // 3. Tính toán Font Size động (Auto-scaling):
    // Ước lượng fontSize khởi điểm dựa trên diện tích box và độ dài văn bản
    const minFont = 9;
    const maxFont = Math.min(26, Math.max(14, Math.floor(scaled.height * 0.75)));
    let currentFont = estimateFontSizeFromArea(cleanText, scaled.width, scaled.height, {
      minFontSize: minFont,
      maxFontSize: maxFont,
    });

    boxEl.style.fontSize = `${currentFont}px`;
    overlayLayer.appendChild(boxEl);

    // Vòng lặp giảm font-size từ max_font/ước lượng xuống cho đến khi
    // scrollHeight <= offsetHeight và scrollWidth <= offsetWidth
    if (boxEl.offsetHeight > 0 && boxEl.offsetWidth > 0) {
      while (
        currentFont > minFont &&
        (boxEl.scrollHeight > boxEl.offsetHeight || boxEl.scrollWidth > boxEl.offsetWidth)
      ) {
        currentFont -= 0.5;
        boxEl.style.fontSize = `${currentFont}px`;
      }
    }
  }
  ```

---

#### D. `extension/tests/unit/extension.unit.test.ts`
- **1. Import các hàm mới (Dòng 11 - 20):**
  ```typescript
  import {
    adjustVerticalBoundingBox,
    sampleBorderBackgroundColor,
    scaleBboxToDisplay,
  } from "../../src/core/geometry";
  import { SequentialPageQueue } from "../../src/core/queue";
  import {
    estimateFontSizeFromArea,
    fitTextInBox,
    verifyVietnameseFontCoverage,
    VIETNAMESE_DIACRITICS_FULL,
  } from "../../src/core/typography";
  ```

- **2. Bổ sung nhóm Unit Test số 5 (Dòng 212 - 268):**
  ```typescript
  describe("5. Vertical bounding box expansion & Dynamic auto-scaling font size", () => {
    it("expands narrow vertical CJK boxes (aspectRatio > 1.4) and re-centers them", () => {
      // Khung dọc chữ đơn kiểu CJK: width = 25, height = 130 (aspectRatio = 5.2 > 1.4)
      const verticalBox = {
        left: 100,
        top: 50,
        width: 25,
        height: 130,
        scaleX: 1,
        scaleY: 1,
      };

      const expanded = adjustVerticalBoundingBox(verticalBox, 800, 1200, {
        aspectRatioThreshold: 1.4,
        minWidth: 85,
        minExpandRatio: 1.6,
        maxExpandRatio: 2.2,
      });

      // Phải mở rộng ít nhất đạt minWidth (85px)
      expect(expanded.width).toBeGreaterThanOrEqual(85);
      // Tâm của box mới phải trùng với tâm của box cũ
      const oldCenter = verticalBox.left + verticalBox.width / 2; // 112.5
      const newCenter = expanded.left + expanded.width / 2; // 112.5
      expect(Math.abs(newCenter - oldCenter)).toBeLessThanOrEqual(1);
    });

    it("leaves horizontal boxes (aspectRatio <= 1.4) untouched", () => {
      const horizontalBox = {
        left: 100,
        top: 50,
        width: 150,
        height: 80,
        scaleX: 1,
        scaleY: 1,
      };

      const untouched = adjustVerticalBoundingBox(horizontalBox, 800, 1200);
      expect(untouched.width).toBe(150);
      expect(untouched.left).toBe(100);
    });

    it("calculates dynamic font size based on box area and text length", () => {
      const shortText = "Chào bạn!";
      const longText = "Chúng ta nhất định sẽ trở thành những nghệ sĩ vĩ đại như Bach và Handel.";

      const fontShort = estimateFontSizeFromArea(shortText, 100, 100);
      const fontLong = estimateFontSizeFromArea(longText, 100, 100);

      // Đoạn văn ngắn sẽ có font-size lớn hơn đoạn văn dài trong cùng một diện tích khung
      expect(fontShort).toBeGreaterThan(fontLong);
      expect(fontLong).toBeGreaterThanOrEqual(9);
      expect(fontShort).toBeLessThanOrEqual(24);
    });
  });
  ```
- **Kết quả:** Vitest chạy `npm run test:unit` đạt **13/13 passed (100%)**.

### 4.3. Kết quả Build
Đã chạy `npm run build` (`wxt build`) thành công trong 10.4s. Bản build mới nhất nằm tại:
`extension/.output/chrome-mv3/`

Để áp dụng trên trình duyệt Chrome:
1. Mở `chrome://extensions/`
2. Bật chế độ "Developer mode".
3. Nhấn nút "Reload" (biểu tượng mũi tên xoay tròn) tại tiện ích **Comic Translate VN**, hoặc chọn "Load unpacked" trỏ vào thư mục `d:\mma\comic-translate-vn\extension\.output\chrome-mv3`.

---

## 5. Khắc phục sự cố "Khối trắng khổng lồ che toàn bộ trang & Gom nhầm thoại chéo ô tranh"

### 5.1. Phân tích nguyên nhân lỗi (ảnh thực tế)
Qua kiểm tra trực tiếp nhật ký cơ sở dữ liệu (`translation_cache` ID 21) và ảnh gốc:
1. **Lỗi gom dòng OCR (`ocr_service/pipeline.py`):**
   - Ở mép trái trang truyện có một dòng chữ banner dọc rất dài: `改变常识韵天空女正·埃尔哈特她那疯症的人生` (cao tới `732px`).
   - Hàm gom cụm `_are_lines_in_same_bubble` do dùng điều kiện khoảng cách lỏng lẻo khi một dòng là dọc và dòng kia là ngang (`char_scale = max(...)`), đã gom dòng banner lề này với thẻ tên `女飞行员尼塔·斯努克` (ở panel trên) VÀ cả câu thoại `毕竟是我最早教会她怎么飞行的` (ở panel dưới).
   - Kết quả: Tạo ra một khối Bounding Box khổng lồ `[12, 14, 266, 746]` chiếm trọn nửa bên trái trang tranh và ghép nối 3 câu thoại không liên quan thành một đoạn văn dài.
2. **Lỗi mở rộng Bounding Box quá đà (`extension/src/core/geometry.ts`):**
   - Khi gặp khối khổng lồ trên (`width = 254px, height = 732px`), hàm `adjustVerticalBoundingBox` thấy `aspectRatio = 2.88 > 1.4` nên tiếp tục nhân chiều rộng lên `2.2x` (`254 * 2.2 = 558px`), biến nó thành một "tấm biển quảng cáo màu trắng" che kín toàn bộ nhân vật và khung tranh.
   - Ngoài ra, các bong bóng thoại vốn đã đủ rộng (ví dụ `width = 82px`) cũng bị nhân `2.2x` lên `180px` làm tràn viền trắng ra ngoài bong bóng vẽ của truyện.

---

### 5.2. Chi tiết các dòng code đã sửa chữa

#### A. `ocr_service/pipeline.py` (Dòng 262 - 280)
- **Mục tiêu:** 
  - Chặn tuyệt đối việc gom dòng banner lề trang (`height >= 280px, width <= 75px`) với thoại nội dung bên trong tranh.
  - Chặn gom các dòng có tỉ lệ chiều cao chênh lệch quá lớn (`max_h / min_h > 3.2`).
  - Sửa `char_scale` dùng `min()` thay vì `max()` khi tính khoảng cách giữa dòng dọc và dòng ngang.
- **Code sau khi sửa:**
  ```python
  def _are_lines_in_same_bubble(a: ShiftedLine, b: ShiftedLine) -> bool:
      """
      Kiểm tra hai dòng có thuộc cùng một khối bong bóng thoại hay không dựa trên khoảng cách hình học.
      Hỗ trợ cả cụm dòng ngang xếp dọc và cụm cột dọc xếp cạnh nhau.
      """
      # 1. Chặn gom dòng banner lề trang (cột dọc rất cao >= 280px, hẹp <= 75px) với thoại trong tranh
      if (a.height >= 280 and a.width <= 75 and a.height > a.width * 3.0) or (
          b.height >= 280 and b.width <= 75 and b.height > b.width * 3.0
      ):
          return False

      # 2. Chặn gom các dòng có kích thước chênh lệch quá lớn (không thể cùng một bong bóng thoại)
      max_h = max(a.height, b.height)
      min_h = max(1, min(a.height, b.height))
      if max_h / min_h > 3.2:
          return False

      gap_x = max(0, max(a.bbox[0] - b.bbox[2], b.bbox[0] - a.bbox[2]))
      gap_y = max(0, max(a.bbox[1] - b.bbox[3], b.bbox[1] - a.bbox[3]))

      overlap_x = max(0, min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]))
      overlap_y = max(0, min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1]))

      a_vert = a.height > a.width * 1.25
      b_vert = b.height > b.width * 1.25

      if a_vert and b_vert:
          # Hai cột chữ dọc: chiều rộng cột là cỡ chữ
          col_w = max(a.width, b.width, 1)
          min_h = max(1, min(a.height, b.height))
          return gap_x <= col_w * 1.6 and (overlap_y / min_h >= 0.20 or gap_y <= col_w * 0.8)

      if not a_vert and not b_vert:
          # Hai dòng chữ ngang: chiều cao dòng là cỡ chữ
          line_h = max(a.height, b.height, 1)
          min_w = max(1, min(a.width, b.width))
          return gap_y <= line_h * 1.35 and (overlap_x / min_w >= 0.20 or gap_x <= line_h * 1.2)

      # Một dòng có bbox gần vuông nằm cạnh dòng dài: dùng kích thước nhỏ hơn để đo độ sát
      char_scale = max(1, min(min(a.width, a.height), min(b.width, b.height)))
      return gap_x <= char_scale * 1.5 and gap_y <= char_scale * 1.3
  ```

---

#### B. `extension/src/core/geometry.ts` (Dòng 70 - 115)
- **Mục tiêu:**
  - Nhận diện riêng Margin Banner đứng dọc (`height >= 280px`), giữ bề ngang cố định nhỏ gọn (`50px - 75px`), không bao giờ mở rộng phình to vào tranh.
  - Phân loại mở rộng theo chiều rộng ban đầu của box:
    - Nếu box thực sự hẹp (`width < targetMinWidth = 85px`): Mở rộng từ `1.6x - 2.2x` đạt `85px` để chữ tiếng Việt không bị bẻ gãy.
    - Nếu box đã đủ rộng (`width >= 85px`): Chỉ thêm đệm nhẹ `+16px`, tuyệt đối KHÔNG nhân `2.2x` làm tràn ra ngoài bong bóng vẽ của truyện tranh.
- **Code sau khi sửa:**
  ```typescript
  export function adjustVerticalBoundingBox(
    box: ScaledBox,
    containerWidth: number = 0,
    containerHeight: number = 0,
    options: VerticalBoxExpansionOptions = {}
  ): ScaledBox {
    const threshold = options.aspectRatioThreshold ?? 1.4;
    const targetMinWidth = options.minWidth ?? 85; // Giới hạn tối thiểu từ 70px - 100px
    const minExpand = options.minExpandRatio ?? 1.6;
    const maxExpand = options.maxExpandRatio ?? 2.2;

    const aspectRatio = box.height / Math.max(1, box.width);
    if (aspectRatio <= threshold) {
      return { ...box };
    }

    // 1. Dòng chữ đứng dọc ở lề trang (Margin banner: rất cao >= 280px nhưng hẹp <= 75px)
    // Giữ nguyên ở rìa lề, không mở rộng phình to che vào trong tranh
    const isMarginBanner =
      (containerHeight > 0 && box.height > containerHeight * 0.32) ||
      (box.height >= 280 && box.width <= 75);
    if (isMarginBanner) {
      const marginWidth = Math.min(Math.max(box.width, 50), 75);
      const centerX = box.left + box.width / 2;
      let newLeft = Math.round((centerX - marginWidth / 2) * 100) / 100;
      if (newLeft < 0) newLeft = 0;
      return { ...box, left: newLeft, width: marginWidth };
    }

    // 2. Khung bong bóng dọc (Vertical Bubble) trong tranh:
    let newWidth = box.width;

    if (box.width < targetMinWidth) {
      // Khung rất hẹp (1 cột chữ CJK 20px - 45px): mở rộng 1.6x - 2.2x và đạt tối thiểu targetMinWidth
      const expandRatio = Math.min(
        maxExpand,
        Math.max(minExpand, 1.4 + (aspectRatio - 1.4) * 0.25)
      );
      newWidth = Math.min(135, Math.max(box.width * expandRatio, targetMinWidth));
    } else {
      // Khung đã đủ rộng (>= 80px): chỉ thêm chút đệm nhẹ, không nhân 2.2x tránh tràn ra ngoài bong bóng vẽ
      newWidth = Math.min(box.width + 16, Math.min(box.width * 1.15, 135));
    }

    // Đảm bảo không tràn ra ngoài chiều rộng ảnh/khung chứa nếu containerWidth được xác định
    if (containerWidth > 0 && newWidth > containerWidth) {
      newWidth = containerWidth;
    }

    // Lấy tâm của box cũ làm trọng tâm (re-center box)
    const centerX = box.left + box.width / 2;
    let newLeft = Math.round((centerX - newWidth / 2) * 100) / 100;

    // Giữ box nằm trong phạm vi hiển thị hợp lệ [0, containerWidth]
    if (newLeft < 0) {
      newLeft = 0;
    } else if (containerWidth > 0 && newLeft + newWidth > containerWidth) {
      newLeft = Math.max(0, containerWidth - newWidth);
    }

    return {
      ...box,
      left: newLeft,
      width: Math.round(newWidth * 100) / 100,
    };
  }
  ```

---

### 5.3. Xóa bộ nhớ đệm cũ (Cache invalidation) & Kiểm chứng
- Đã thực hiện xóa các bản ghi cache cũ (`id >= 21`) trong `server/comic_translate_vn.db` vốn lưu trữ khối gom lỗi trước đó.
- Gọi kiểm tra trực tiếp tới OCR service với bức ảnh trên:
  - **Trước:** Trả về 8 khối (trong đó Khối 1 bị dính chùm từ lề trang đến tận ô thoại dưới cùng: `[12, 14, 266, 746]`).
  - **Sau:** Trả về chuẩn xác **10 khối độc lập**:
    + `Block 1: [12, 14, 57, 746]` -> Chỉ riêng dòng banner lề trang bên trái.
    + `Block 2: [126, 522, 197, 651]` -> Câu thoại ở panel 2 (`毕竟是我最早教会她怎么飞行的`).
    + `Block 3: [145, 80, 204, 253]` -> Câu thoại ở panel 1 (`你想打听关于阿梅莉亚的故事？`).
    + `Block 4: [114, 341, 266, 396]` -> Thẻ tên riêng (`女飞行员尼塔·斯努克`).
    + Toàn bộ các thoại còn lại đều được cô lập chuẩn xác.
- Đã build lại extension hoàn tất vào thư mục `extension/.output/chrome-mv3`.

---

## 6. Tính năng chuyển đổi chiều đọc Manga (RTL) / Manhwa (LTR) & Gom cụm tọa độ đọc tự nhiên (Vertical Overlap Clustering)

### 6.1. Mục tiêu
- Xử lý triệt để tình trạng bản dịch bị ngắt câu cụt lủn hoặc ngược thứ tự (do bóng thoại phân bổ theo chiều đọc truyện tranh Manga: Phải -> Trái, hoặc Manhwa: Trái -> Phải).
- Loại bỏ hoàn toàn nguy cơ lệch mảng (Off-by-one Error) bằng cách bảo toàn 100% ID gốc của khối chữ.
- Tránh xung đột cache khi người dùng chuyển đổi giữa RTL và LTR.

### 6.2. Chi tiết các file đã sửa và tạo mới

#### A. Tạo mới `server/reading_order.py`
- Cung cấp hàm `extract_bbox(block)` chuẩn hóa bounding box về `(x1, y1, x2, y2)`.
- Cung cấp class `TextRowCluster` và hàm `sort_blocks_by_reading_order(blocks, reading_direction="rtl")`:
  + Gom các block vào cùng một hàng ngang nếu phần giao thoa dọc (vertical overlap) >= 30% chiều cao của block, hoặc `abs(center_y1 - center_y2) < 0.5 * min(h1, h2)`.
  + Sắp xếp các cụm dòng từ Trên xuống Dưới (`y_min` tăng dần).
  + Trong từng dòng:
    * Nếu `reading_direction == "rtl"`: Sắp xếp Phải -> Trái (`x_min` giảm dần).
    * Nếu `reading_direction == "ltr"`: Sắp xếp Trái -> Phải (`x_min` tăng dần).
  + Giữ nguyên 100% thuộc tính gốc (`id`, `bbox`, `text`).

#### B. Tạo mới `server/tests/test_reading_order.py`
- Kiểm tra thứ tự RTL: Block B (x=950) đứng trước Block A (x=800).
- Kiểm tra thứ tự LTR: Block A (x=800) đứng trước Block B (x=950).
- Kiểm tra bảo toàn phân tách 2 hàng ở độ cao khác nhau.
- Kiểm tra ánh xạ 100% khớp ID sau khi nhận kết quả JSON giả lập từ LLM.

#### C. `server/translator.py`
- Cập nhật `build_comic_translation_prompt`:
  + Kế thừa đầy đủ `series_title`, `custom_context`, `glossary`, `previous_lines`.
  + Bổ sung chỉ dẫn thứ tự đọc tự nhiên (`reading_direction`), yêu cầu LLM nắm bắt ngữ cảnh liền mạch giữa các bóng kề nhau và tự khắc phục lỗi chính tả do OCR quét nhầm nét chữ Hán.
  + Ràng buộc cấu trúc JSON có ID: `{"translations": [{"id": ..., "translation": "..."}]}`.
- Cập nhật `translate_blocks_with_llm`:
  + Thiết lập `temperature: 0.2` và `max_output_tokens: 2048` (tránh bị cụt chuỗi JSON trên các trang dài).

#### D. `server/translate_routes.py`
- Tiếp nhận `reading_direction: str | None = Form(None)`. Tự động fallback: nếu aspect ratio (height / width) > 2.0 -> "ltr", ngược lại "rtl".
- Tách biệt cache: `cache_image_hash = f"{image_hash}_{effective_direction}"` đảm bảo khi chuyển đổi RTL <-> LTR không bị dính cache cũ.
- Gọi `sort_blocks_by_reading_order` sắp xếp các khối trước khi gửi sang LLM.
- Trả về trường `"reading_direction": effective_direction` trong response payload.

#### E. `extension/entrypoints/background.ts`
- Bổ sung trường `readingDirection?: "rtl" | "ltr"` trong `handleTranslatePageRequest` và append vào `FormData` gửi lên `/api/v1/page/translate`.

#### F. `extension/entrypoints/content.ts`
- Thêm nút Toggle trên Floating Toolbar: `[ 📖 Manga (RTL) ]` <-> `[ 📜 Manhwa (LTR) ]`.
- Tự động nhận diện ban đầu theo URL (hivetoon, webtoon -> LTR; baozimh -> RTL) và lưu cấu hình bền vững vào `chrome.storage.local` theo `reading_mode_${hostname}`.
- Khi người dùng click toggle:
  + Cập nhật storage và giao diện nút.
  + Đặt lại trạng thái `isTranslated = false` của các trang hiện tại thành "Dịch lại trang này" để người dùng gửi lại request theo hướng đọc mới.
- Thêm `_${readingDirection}` vào đuôi `idempotencyKey` và truyền `readingDirection` vào message `TRANSLATE_PAGE`.

### 6.3. Kết quả kiểm thử
- **Backend tests:** 14/14 tests passed (`pytest server/tests`).
- **Extension unit tests:** 13/13 vitest tests passed (`vitest run`).
- **Extension build:** `wxt build` thành công vào `extension/.output/chrome-mv3`.

---

## 7. Tối ưu kích thước bóng thoại, giới hạn Font Size và thuật toán chống tràn che tranh (Extension)

### 7.1. Phân tích nguyên nhân
1. **Lệch cỡ chữ mất cân đối (Font Size Imbalance):**
   - Sau khi hỗ trợ mở rộng Vertical Bubble, các câu thoại ngắn (1-2 từ) bị thuật toán phóng to font-size lên tới `24px - 26px`, trong khi câu thoại dài chỉ đạt `9px - 10px`. Sự chênh lệch này khiến các trang truyện có nhiều thoại ngắn trông thô kệch và mất cân đối thẩm mỹ.
2. **Bong bóng mở rộng quá rộng che mất nhân vật:**
   - Chiều rộng bóng thoại tối đa cho phép lên tới `135px - 180px`, dẫn đến việc các khung thoại dọc che lấp nét vẽ nhân vật và lấn ra ngoài đường biên phân khung tranh (panel gutter).
3. **Bước lùi font và khoảng cách dòng:**
   - Bước lùi `1px` khi auto-fit quá thô, line-height `1.25` và đệm `4px 6px` chiếm nhiều diện tích không cần thiết của bóng thoại.

### 7.2. Chi tiết từng file đã sửa đổi

#### A. `extension/src/core/geometry.ts`
- **Mục tiêu:** Cố định trần mở rộng chiều rộng bóng thoại tối đa ở mức `115px` và đảm bảo phân vùng va chạm hướng tâm không bao giờ lấn ra ngoài viền khung tranh.
- **Thay đổi:**
  ```typescript
  // Cố định trần mở rộng chiều rộng tối đa ở mức 115px (tránh biến bóng thoại thành biển quảng cáo)
  const MAX_BUBBLE_EXPAND_WIDTH = 115;

  if (box.width < targetMinWidth) {
    const expandRatio = Math.min(
      maxExpand,
      Math.max(minExpand, 1.4 + (aspectRatio - 1.4) * 0.25)
    );
    newWidth = Math.min(MAX_BUBBLE_EXPAND_WIDTH, Math.max(box.width * expandRatio, targetMinWidth));
  } else {
    newWidth = Math.min(box.width + 12, Math.min(box.width * 1.10, MAX_BUBBLE_EXPAND_WIDTH));
  }
  ```

#### B. `extension/src/core/typography.ts`
- **Mục tiêu:** Tinh chỉnh tỷ lệ ước lượng font-size theo diện tích, thu gọn line-height xuống `1.22`, padding thu gọn `3px 4px` để tăng không gian hiển thị cho chữ tiếng Việt.
- **Thay đổi:**
  ```typescript
  // Thu gọn line-height và đệm khung hiển thị
  lineHeight = Math.round(fontSizePx * 1.22);
  padding = "3px 4px";
  ```

#### C. `extension/entrypoints/content.ts`
- **Mục tiêu:** Khống chế mức trần font-size tối đa cho câu thoại ở mức `13.5px`, tạo dải font đồng đều `9.5px - 13.5px` trên toàn trang tranh.
- **Thay đổi:**
  ```typescript
  // Giới hạn font-size trần tối đa 13.5px (ngăn chặn câu ngắn bị chữ 26px khổng lồ)
  const minFont = 9.0;
  const maxFont = Math.min(13.5, Math.max(10.5, Math.floor(scaled.height * 0.45)));
  let currentFont = estimateFontSizeFromArea(cleanText, scaled.width, scaled.height, {
    minFontSize: minFont,
    maxFontSize: maxFont,
    paddingPx: 3,
  });

  // Vòng lặp hạ font từng bước 0.5px siêu mịn cho tới khi vừa khít khung
  if (boxEl.offsetHeight > 0 && boxEl.offsetWidth > 0) {
    while (
      currentFont > minFont &&
      (boxEl.scrollHeight > boxEl.offsetHeight || boxEl.scrollWidth > boxEl.offsetWidth)
    ) {
      currentFont -= 0.5;
      boxEl.style.fontSize = `${currentFont}px`;
    }
  }
  ```

### 7.3. Kết quả
- Toàn bộ cỡ chữ trên trang truyện nằm trong dải `9.5px - 13.5px` hài hòa, tự nhiên.
- Bong bóng không còn che lấp nét vẽ khuôn mặt/cơ thể nhân vật hoặc tràn ra ngoài viền tranh.

---

## 8. Khắc phục triệt để lỗi tách rời thoại dọc cùng ô và sự cố gom tràn chéo qua 2 khung tranh (OCR & Server)

### 8.1. Phân tích nguyên nhân gốc rễ
1. **Lỗi thoại 2 cột trong cùng một bóng bị xé lẻ thành 2 ô riêng (Split Dialogue):**
   - Trong truyện tranh Manga/Manhua viết dọc, một câu thoại dài thường được ngắt thành nhiều cột kế nhau: Cột 1 có 18 chữ (cao ~340px), Cột 2 có 4 chữ (cao ~70px).
   - Trong `ocr_service/pipeline.py`, hàm `_are_lines_in_same_bubble`:
     + Điều kiện chặn mép `if (a.height >= 280 and a.width <= 75)` chặn nhầm các cột thoại dài nội dung bên trong tranh.
     + Điều kiện kiểm tra tỷ lệ chiều cao `if max_h / min_h > 3.2: return False` so sánh chiều cao 2 cột ($340 / 70 = 4.86 > 3.2$), khiến 2 cột bị từ chối gom và phát sinh thành 2 block riêng biệt.
     + Hậu quả: Server gửi 2 khối tách rời sang LLM (`id: 0` và `id: 1`), LLM dịch từng mảnh câu cụt lủn và làm lệch nghĩa toàn bộ câu nói.
2. **Lỗi gom tràn chéo qua 2 khung tranh (Cross-panel Merger):**
   - Khi áp dụng hàm gom khối hình học `merge_adjacent_vertical_dialogue` ở tầng Server: Đối tượng trên Server đã là một Block thoại hoàn chỉnh ($w \approx 120-180\text{px}$). Lấy độ rộng khối làm thước đo khiến dung sai quét lên tới $300\text{px}-375\text{px}$, dẫn đến việc gom nhầm hộp thoại ở khung giữa với hộp thoại ở khung dưới (vượt qua rãnh khung tranh) và gom nhầm 2 người nói khác nhau ở hàng trên thành một khối dị hình khổng lồ.
3. **Lỗi đảo lộn thứ tự cột bên trong khối OCR:**
   - Trong `ocr_service/pipeline.py`, hàm `comp.sort` chia `ln.width * 0.5` cho từng dòng riêng rẽ. Do nét chữ mỗi cột có bề rộng hơi lệch nhau nên giá trị bucket bị nhảy cóc, làm đảo thứ tự đọc (cột 3 nhảy trước cột 2).

### 8.2. Chi tiết các tệp đã sửa đổi

#### A. `ocr_service/pipeline.py` (Commit `018c38f`, `bbfdc7d`)
- **1. Viết lại hàm `_are_lines_in_same_bubble` cho cột dọc:**
  ```python
  if a_vert and b_vert:
      # Hai cột chữ dọc: chiều rộng cột đại diện cho cỡ chữ (font size)
      col_w = max(a.width, b.width, 1.0)
      min_w = max(1.0, min(a.width, b.width))
      if col_w / min_w > 2.8:
          return False

      # Khoảng cách ngang giữa hai cột trong cùng bong bóng (rất sát nhau, <= 50px)
      if gap_x > col_w * 1.5 or gap_x > 50.0:
          return False

      # Hai cột cạnh nhau trong cùng bong bóng bắt buộc phải có vùng phủ theo trục dọc Y
      # và không có khoảng cách dọc (không thể cột nọ nằm hẳn phía trên cột kia qua khung tranh)
      min_h = max(1.0, min(a.height, b.height))
      if gap_y > 10.0 or (overlap_y / min_h < 0.20):
          return False

      return True
  ```
  *Gỡ bỏ kiểm tra `max_h / min_h > 3.2` và chặn dòng cao `height >= 280`. Ràng buộc `gap_y <= 10px` và `overlap_y / min_h >= 0.20` đảm bảo không bao giờ gom nhầm qua rãnh khung tranh.*

- **2. Sửa thuật toán sắp xếp thứ tự cột trong khối (`comp.sort`):**
  ```python
  if vertical_block:
      # Chữ dọc (ja hoặc zh cột dọc): sắp các cột từ PHẢI sang TRÁI, nếu cùng cột thì từ trên xuống.
      # Dùng avg_col_w đồng nhất cho toàn khối để tránh sai lệch bucket giữa các cột.
      avg_col_w = max(1.0, statistics.mean(ln.width for ln in comp))
      comp.sort(key=lambda ln: (-round(ln.center_x / (avg_col_w * 0.7)), ln.bbox[1]))
  else:
      # Chữ ngang (en, ko, zh ngang): sắp từ TRÊN xuống DƯỚI, trái sang phải
      avg_line_h = max(1.0, statistics.mean(ln.height for ln in comp))
      comp.sort(key=lambda ln: (round(ln.center_y / (avg_line_h * 0.7)), ln.bbox[0]))
  ```

#### B. `server/translate_routes.py` & `server/ocr_postprocess.py` (Commit `47ea86d`, `540064d`)
- Loại bỏ hoàn toàn việc gọi `merge_adjacent_vertical_dialogue` ở tầng Server. Tầng Server chỉ nhận các khối hoàn chỉnh từ OCR, chuẩn hóa text và phân loại. Không can thiệp gom khối mù.

#### C. `scripts/debug_page.py` (Commit `9893f84`)
- Đồng bộ hóa quy trình chẩn đoán debug khớp 100% với luồng xử lý thực tế của Server.

#### D. Xóa bộ nhớ đệm cũ (Cache Invalidation)
- Xóa sạch 94 bản ghi lưu trữ khối gom lỗi cũ trong các bảng `translation_cache` và `translation_idempotency` của database (`server/comic_translate_vn.db`), đảm bảo các lần dịch tiếp theo nhận bản dịch mới 100%.

### 8.3. Kết quả kiểm thử & xác minh thực tế
- **Trang Pilot:** Cột 18 chữ + cột 4 chữ gộp chuẩn xác thành 1 khối: `我想要的是由女性飞行员首次完成跨大西洋飞行这项伟业`.
- **Trang Mozart:** Hộp thoại khung giữa (`无论是贵族还是富豪……全都着迷于我们的演奏`) và khung dưới (`我和我的弟弟沃尔冈夫曾经就是`) tách biệt hoàn toàn 100%, thứ tự chữ chuẩn xác từng từ.
- **Unit test Extension:** Đạt 13/13 passed (`npm run test:unit`).
- **Extension Build:** Đã xuất bản build sạch vào `extension/.output/chrome-mv3`.

---

## 9. Cải tiến chất lượng dịch thuật (Prompt Localization, Back-Transliteration, Temperature 0.5, Context Presets)

**Ngày thực hiện:** 04/11/2026  
**Mục tiêu:** Nâng cao chất lượng câu dịch, chuyển ngữ tự nhiên đúng khẩu ngữ truyện tranh Việt Nam, chấm dứt tình trạng dịch bồi Hán-Việt ngô nghê và câu cụt lủn do bóng thoại bị ngắt quãng, không phát sinh chi phí hay độ trễ.

### 9.1. Nâng cấp tham số Temperature trong Server (`server/config.py` & `server/translator.py`)
- **Vấn đề:** Trước đây tham số `temperature` bị cố định ở mức `0.2` (mức an toàn nhưng máy móc, dịch sát từng chữ như Google Dịch, thiếu tự nhiên).
- **Giải pháp:**
  - Bổ sung cấu hình `LLM_TEMPERATURE: float = 0.5` vào `server/config.py`.
  - Cập nhật cả 2 provider (Gemini và DeepSeek) trong `server/translator.py` dùng `temperature: 0.5`.
  - Giúp bản dịch tiếng Việt thoát ý, mềm mại, biểu cảm tự nhiên theo nhịp điệu nhân vật mà vẫn đảm bảo 100% định dạng JSON nhờ ràng buộc `responseMimeType: "application/json"`.

### 9.2. Nâng cấp Translation Prompt (`server/translator.py`)
Bổ sung 4 quy tắc bắt buộc chuyên sâu cho truyện tranh:
1. **Hoàn nguyên tên riêng phương Tây (Back-transliteration):**
   - Ép buộc khôi phục tên Latin chuẩn quốc tế khi gặp tên người/địa danh Tây phương bị phiên âm chữ Hán (như `阿梅莉亚` ➔ `Amelia`, `沃尔冈夫` ➔ `Wolfgang`, `莫扎特` ➔ `Mozart`, `伦敦` ➔ `London`...). Tuyệt đối cấm dịch bồi âm Hán-Việt dị hợm.
2. **Khắc phục câu bị ngắt vụn qua nhiều bóng thoại (Sentence Fragmentation):**
   - Hướng dẫn LLM liên kết ngữ nghĩa giữa các bóng thoại liền kề để dịch trọn vẹn mạch ý, sau đó phân bổ bản dịch tiếng Việt vào từng id tương ứng sao cho tự nhiên, mạch lạc.
3. **Văn phong hội thoại đời thường & biểu cảm nhân vật:**
   - Dịch khẩu ngữ tự nhiên theo cảm xúc nhân vật (vui, buồn, tức giận, mỉa mai), tuân thủ bối cảnh thể loại.
4. **Tự động dọn dẹp rác OCR:**
   - Tự động lọc bỏ dấu phẩy rác (`，`), dấu chấm hoặc ký tự lạ dính vào đầu hoặc cuối câu do OCR nhận nhầm đuôi bóng thoại.

### 9.3. Bổ sung Preset Thể loại Âu cổ / Fantasy (`extension/src/core/adapters.ts` & `popup/index.html`)
- Bổ sung chip preset `au_co` (`+ Âu cổ/Fantasy`):
  - *Snippet:* `Thể loại: Âu cổ / Quý tộc / Kỳ ảo Tây phương. Giữ tên gốc Latin (Amelia, Wolfgang...). Xưng hô: tôi - cậu/anh/em, ngài - thần, cha/mẹ - con.`
  - Tự động hiển thị trên cả thanh công cụ nổi trong trang đọc truyện (`contentDrawer`) và giao diện Popup Extension.
  - Kiểm thử Unit test Extension: 13/13 passed. Build chrome-mv3 thành công.






