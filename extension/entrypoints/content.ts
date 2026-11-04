import { defineContentScript } from "wxt/sandbox";
import {
  applyContextPreset,
  buildTranslationContextPayload,
  CONTEXT_PRESET_CHIPS,
  CUSTOM_CONTEXT_PLACEHOLDER,
  deriveCssSelectorForElement,
  extractBestImageUrl,
  isComicCandidateImage,
  matchSiteAdapter,
  MAX_CUSTOM_CONTEXT_LENGTH,
  type ContextPresetChip,
  type SiteAdapter,
} from "../src/core/adapters";
import {
  adjustVerticalBoundingBox,
  resolveBoxCollisions,
  sampleBorderBackgroundColor,
  scaleBboxToDisplay,
} from "../src/core/geometry";
import { SequentialPageQueue } from "../src/core/queue";
import {
  estimateFontSizeFromArea,
  fitTextInBox,
  VIETNAMESE_FONT_FAMILY,
} from "../src/core/typography";

interface TranslatedBlock {
  id: number;
  bbox: [number, number, number, number];
  source_text: string;
  translation: string;
}

interface ManagedPageItem {
  img: HTMLImageElement;
  stage: HTMLDivElement;
  overlayLayer: HTMLDivElement;
  loadingIndicator: HTMLDivElement;
  translateBtn: HTMLButtonElement;
  toggleBtn: HTMLButtonElement;
  debugBadge: HTMLDivElement;
  blocks: TranslatedBlock[];
  showingOriginal: boolean;
  pageKey: string;
  isTranslating: boolean;
  isTranslated: boolean;
  isIntersectingViewport: boolean;
}

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  main() {
    const adapter = matchSiteAdapter(window.location.href);
    if (!adapter) {
      return;
    }
    initComicTranslatorOnPage(adapter);
  },
});

function injectStyles(): void {
  if (document.getElementById("ctvn-injected-styles")) {
    return;
  }
  const style = document.createElement("style");
  style.id = "ctvn-injected-styles";
  style.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@500;600;700&display=swap');

    @keyframes ctvn-spin {
      to { transform: rotate(360deg); }
    }

    #ctvn-floating-toolbar {
      position: fixed;
      bottom: 18px;
      right: 18px;
      z-index: 2147483640;
      display: flex;
      gap: 8px;
      align-items: center;
      background: rgba(15, 23, 42, 0.94);
      color: #f8fafc;
      padding: 8px 12px;
      border-radius: 999px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.35);
      font-family: ${VIETNAMESE_FONT_FAMILY};
      font-size: 12px;
      border: 1px solid rgba(255, 255, 255, 0.16);
    }

    #ctvn-floating-toolbar button {
      background: #ea580c;
      color: #ffffff;
      border: none;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      font-family: ${VIETNAMESE_FONT_FAMILY};
    }

    #ctvn-floating-toolbar button.ctvn-secondary {
      background: #334155;
    }

    #ctvn-floating-toolbar button.ctvn-active {
      background: #16a34a;
    }

    #ctvn-context-drawer {
      position: fixed;
      bottom: 64px;
      right: 18px;
      z-index: 2147483640;
      width: 340px;
      display: none;
      background: rgba(15, 23, 42, 0.96);
      color: #f8fafc;
      padding: 12px;
      border-radius: 14px;
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.45);
      font-family: ${VIETNAMESE_FONT_FAMILY};
      font-size: 12px;
      border: 1px solid rgba(255, 255, 255, 0.18);
    }

    #ctvn-context-drawer.ctvn-open {
      display: block;
    }

    .ctvn-preset-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin: 6px 0 8px 0;
    }

    .ctvn-preset-chip {
      background: #1e293b;
      color: #fdba74;
      border: 1px solid #475569;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      font-family: ${VIETNAMESE_FONT_FAMILY};
    }

    .ctvn-preset-chip:hover {
      background: #334155;
    }

    #ctvn-context-textarea {
      width: 100%;
      box-sizing: border-box;
      min-height: 68px;
      resize: vertical;
      border-radius: 8px;
      border: 1px solid #475569;
      background: #0f172a;
      color: #f8fafc;
      padding: 7px 8px;
      font-size: 12px;
      line-height: 1.4;
      font-family: ${VIETNAMESE_FONT_FAMILY};
    }

    .ctvn-image-stage {
      position: relative !important;
      display: inline-block !important;
    }

    .ctvn-image-stage.ctvn-debug-highlight {
      outline: 3px dashed #22c55e !important;
      outline-offset: -3px !important;
    }

    .ctvn-controls-bar {
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 30;
      display: flex;
      gap: 6px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s ease;
    }

    .ctvn-image-stage:hover .ctvn-controls-bar,
    .ctvn-image-stage[data-ctvn-status="translating"] .ctvn-controls-bar,
    .ctvn-image-stage[data-ctvn-status="translated"] .ctvn-controls-bar {
      opacity: 1;
      pointer-events: auto;
    }

    .ctvn-loading-indicator {
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 32;
      display: none;
      align-items: center;
      gap: 6px;
      background: rgba(15, 23, 42, 0.88);
      color: #f8fafc;
      border: 1px solid rgba(251, 146, 60, 0.65);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 600;
      font-family: ${VIETNAMESE_FONT_FAMILY};
      pointer-events: none;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }

    .ctvn-image-stage[data-ctvn-status="translating"] .ctvn-loading-indicator {
      display: inline-flex;
    }

    .ctvn-spinner-dot {
      width: 10px;
      height: 10px;
      border: 2px solid rgba(251, 146, 60, 0.35);
      border-top-color: #fb923c;
      border-radius: 50%;
      animation: ctvn-spin 0.75s linear infinite;
    }

    .ctvn-btn {
      background: rgba(234, 88, 12, 0.95);
      color: #ffffff;
      border: 1px solid rgba(255, 255, 255, 0.25);
      border-radius: 8px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      font-family: ${VIETNAMESE_FONT_FAMILY};
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }

    .ctvn-btn.ctvn-btn-toggle {
      background: rgba(15, 23, 42, 0.9);
      display: none;
    }

    .ctvn-overlay-layer {
      position: absolute;
      inset: 0;
      z-index: 20;
      pointer-events: none;
      overflow: hidden;
    }

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
      padding: 3px 4px;
      font-family: ${VIETNAMESE_FONT_FAMILY};
      font-weight: 600;
      overflow: hidden;
      box-shadow: 0 0 2px rgba(0, 0, 0, 0.12);
    }

    .ctvn-debug-badge {
      position: absolute;
      top: 10px;
      left: 10px;
      z-index: 35;
      display: none;
      max-width: 85%;
      background: rgba(6, 78, 59, 0.94);
      color: #ecfdf5;
      border: 1px solid #34d399;
      border-radius: 8px;
      padding: 6px 8px;
      font-size: 11px;
      line-height: 1.35;
      cursor: pointer;
      font-family: monospace;
      pointer-events: auto;
    }

    .ctvn-image-stage.ctvn-debug-highlight .ctvn-debug-badge {
      display: block;
    }
  `;
  document.head.appendChild(style);
}

function trySampleImagePixels(img: HTMLImageElement): Uint8ClampedArray | null {
  try {
    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    if (w <= 0 || h <= 0) {
      return null;
    }
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return null;
    }
    ctx.drawImage(img, 0, 0, w, h);
    return ctx.getImageData(0, 0, w, h).data;
  } catch {
    return null;
  }
}

async function blobUrlToDataUrl(blobUrl: string): Promise<string | undefined> {
  try {
    const resp = await fetch(blobUrl);
    const blob = await resp.blob();
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  } catch {
    return undefined;
  }
}

/**
 * Kiểm tra xem ảnh có đang nằm trong tầm nhìn (viewport + lề 200px) hay không.
 * Nhờ hàm này, khi bật "Cuộn tới đâu dịch tới đó", Extension CHỈ xếp hàng các ảnh
 * đang nằm trong tầm nhìn, tuyệt đối không quét toàn bộ hàng chục ảnh trên DOM cùng lúc.
 */
function isElementNearViewport(el: HTMLElement, marginPx = 200): boolean {
  const rect = el.getBoundingClientRect();
  const viewHeight =
    window.innerHeight || document.documentElement.clientHeight || 800;
  return rect.bottom >= -marginPx && rect.top <= viewHeight + marginPx;
}

function initComicTranslatorOnPage(adapter: SiteAdapter): void {
  injectStyles();

  // Hàng đợi xử lý tuần tự ở client (concurrency = 1 để bảo vệ CPU PaddleOCR & tránh lỗi 429)
  const queue = new SequentialPageQueue<TranslatedBlock[]>(1);
  const managedItems = new Map<HTMLImageElement, ManagedPageItem>();
  let autoScrollEnabled = false;
  let globalShowOriginal = false;
  let debugSelectorMode = false;
  let customSelector = "";
  let customContextText = "";

  // Hướng đọc: Manga (RTL - Phải sang Trái) hoặc Manhwa (LTR - Trái sang Phải)
  const host = window.location.hostname.toLowerCase();
  const urlLower = window.location.href.toLowerCase();
  const isManhwaSite =
    host.includes("hivetoon") ||
    host.includes("webtoon") ||
    urlLower.includes("hivetoon");
  let readingDirection: "rtl" | "ltr" = isManhwaSite ? "ltr" : "rtl";
  const readingModeStorageKey = `reading_mode_${window.location.hostname}`;

  // Khung Ngữ cảnh Truyện (1 ô textarea duy nhất + 4 Quick Preset Chips) ngay trên thanh công cụ nổi
  const contextDrawer = document.createElement("div");
  contextDrawer.id = "ctvn-context-drawer";
  contextDrawer.setAttribute("data-testid", "ctvn-context-drawer");

  const chipsHtml = CONTEXT_PRESET_CHIPS.map(
    (chip) =>
      `<button type="button" class="ctvn-preset-chip" data-preset-id="${chip.id}" data-testid="ctvn-chip-${chip.id}">${chip.label}</button>`
  ).join("");

  contextDrawer.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong>Ngữ cảnh Truyện &amp; Xưng hô</strong>
      <span id="ctvn-context-counter">0/${MAX_CUSTOM_CONTEXT_LENGTH}</span>
    </div>
    <div class="ctvn-preset-chips">${chipsHtml}</div>
    <textarea
      id="ctvn-context-textarea"
      data-testid="ctvn-context-textarea"
      maxlength="${MAX_CUSTOM_CONTEXT_LENGTH}"
      placeholder="${CUSTOM_CONTEXT_PLACEHOLDER}"
    ></textarea>
  `;
  document.body.appendChild(contextDrawer);

  // Thanh công cụ nổi ở góc dưới bên phải trang đọc truyện
  const toolbar = document.createElement("div");
  toolbar.id = "ctvn-floating-toolbar";
  toolbar.innerHTML = `
    <span data-testid="ctvn-site-label">${adapter.displayName}</span>
    <button type="button" id="ctvn-btn-reading-direction" class="ctvn-secondary" data-testid="ctvn-btn-reading-direction">${
      readingDirection === "rtl" ? "[ 📖 Manga (RTL) ]" : "[ 📜 Manhwa (LTR) ]"
    }</button>
    <button type="button" id="ctvn-btn-auto-scroll" data-testid="ctvn-btn-auto-scroll">Dịch toàn bộ khi cuộn</button>
    <button type="button" id="ctvn-btn-toggle-all" class="ctvn-secondary" data-testid="ctvn-btn-toggle-all">Xem bản gốc / Bản dịch</button>
    <button type="button" id="ctvn-btn-context-toggle" class="ctvn-secondary" data-testid="ctvn-btn-context-toggle">Ngữ cảnh truyện</button>
    <button type="button" id="ctvn-btn-debug-selector" class="ctvn-secondary" data-testid="ctvn-btn-debug-selector">Debug Selector</button>
  `;
  document.body.appendChild(toolbar);

  const readingDirectionBtn = toolbar.querySelector(
    "#ctvn-btn-reading-direction"
  ) as HTMLButtonElement;
  const autoScrollBtn = toolbar.querySelector(
    "#ctvn-btn-auto-scroll"
  ) as HTMLButtonElement;
  const toggleAllBtn = toolbar.querySelector(
    "#ctvn-btn-toggle-all"
  ) as HTMLButtonElement;
  const contextToggleBtn = toolbar.querySelector(
    "#ctvn-btn-context-toggle"
  ) as HTMLButtonElement;
  const debugSelectorBtn = toolbar.querySelector(
    "#ctvn-btn-debug-selector"
  ) as HTMLButtonElement;

  function updateReadingDirectionBtnUI(): void {
    if (readingDirectionBtn) {
      readingDirectionBtn.textContent =
        readingDirection === "rtl" ? "[ 📖 Manga (RTL) ]" : "[ 📜 Manhwa (LTR) ]";
      readingDirectionBtn.title =
        readingDirection === "rtl"
          ? "Hướng đọc: Phải sang Trái (Manga Nhật / Manhua). Click để đổi."
          : "Hướng đọc: Trái sang Phải (Manhwa Hàn / Webtoon). Click để đổi.";
    }
  }

  // Khởi tạo cấu hình hướng đọc từ storage nếu có
  chrome.storage.local.get([readingModeStorageKey], (res) => {
    if (res && (res[readingModeStorageKey] === "rtl" || res[readingModeStorageKey] === "ltr")) {
      readingDirection = res[readingModeStorageKey];
      updateReadingDirectionBtnUI();
    }
  });

  readingDirectionBtn.addEventListener("click", () => {
    readingDirection = readingDirection === "rtl" ? "ltr" : "rtl";
    updateReadingDirectionBtnUI();
    chrome.storage.local.set({ [readingModeStorageKey]: readingDirection });

    // Khi chuyển nút, cập nhật các trang đã dịch để người dùng có thể gửi lại theo chiều đọc mới
    for (const item of managedItems.values()) {
      if (item.isTranslated) {
        item.isTranslated = false;
        item.img.dataset.isTranslated = "false";
        item.translateBtn.textContent = "Dịch lại trang này";
        item.translateBtn.disabled = false;
        item.stage.removeAttribute("data-ctvn-status");
        if (item.pageKey) {
          queue.resetKey(item.pageKey);
        }
      }
    }
  });

  const contextTextarea = contextDrawer.querySelector(
    "#ctvn-context-textarea"
  ) as HTMLTextAreaElement;
  const contextCounter = contextDrawer.querySelector(
    "#ctvn-context-counter"
  ) as HTMLSpanElement;

  function syncCustomContextToStorage(val: string): void {
    customContextText = val.slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
    contextTextarea.value = customContextText;
    contextCounter.textContent = `${customContextText.length}/${MAX_CUSTOM_CONTEXT_LENGTH}`;
    chrome.runtime.sendMessage({
      type: "SET_CONFIG",
      patch: { customContext: customContextText },
    });
  }

  contextToggleBtn.addEventListener("click", () => {
    const isOpen = contextDrawer.classList.toggle("ctvn-open");
    contextToggleBtn.classList.toggle("ctvn-active", isOpen);
  });

  contextTextarea.addEventListener("input", () => {
    syncCustomContextToStorage(contextTextarea.value);
  });

  contextDrawer
    .querySelectorAll<HTMLButtonElement>(".ctvn-preset-chip")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const presetId = btn.getAttribute(
          "data-preset-id"
        ) as ContextPresetChip["id"];
        const updated = applyContextPreset(contextTextarea.value, presetId);
        syncCustomContextToStorage(updated);
      });
    });

  // IntersectionObserver với rootMargin: "200px" để phát hiện trước khi ảnh truyện sắp cuộn vào tầm nhìn
  const intersectionObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const img = entry.target as HTMLImageElement;
        const item = managedItems.get(img);
        if (!item) {
          continue;
        }
        item.isIntersectingViewport = entry.isIntersecting;

        if (
          autoScrollEnabled &&
          entry.isIntersecting &&
          !item.isTranslating &&
          !item.isTranslated
        ) {
          void triggerTranslateItem(item);
        }
      }
    },
    { rootMargin: "200px" }
  );

  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const img = entry.target as HTMLImageElement;
      const item = managedItems.get(img);
      if (item && item.blocks.length > 0) {
        renderOverlayBlocks(item);
      }
    }
  });

  function renderOverlayBlocks(item: ManagedPageItem): void {
    const { img, overlayLayer, blocks, showingOriginal } = item;
    overlayLayer.innerHTML = "";
    if (showingOriginal || globalShowOriginal) {
      overlayLayer.style.display = "none";
      return;
    }
    overlayLayer.style.display = "block";

    const natW = img.naturalWidth || img.width || 800;
    const natH = img.naturalHeight || img.height || 1200;
    const dispW = img.clientWidth || img.width || natW;
    const dispH = img.clientHeight || img.height || natH;

    const rgbaPixels = trySampleImagePixels(img);

    // Bước 1: Quy đổi tọa độ và mở rộng vừa vặn với khuôn khổ bong bóng thoại
    const candidateBoxes = blocks.map((blk) => {
      const baseScaled = scaleBboxToDisplay(blk.bbox, natW, natH, dispW, dispH);
      const cleanText = (blk.translation || "").trim();
      return adjustVerticalBoundingBox(baseScaled, dispW, dispH, {
        aspectRatioThreshold: 1.4,
        minWidth: 85,
        minExpandRatio: 1.6,
        maxExpandRatio: 2.2,
        maxWidth: 115,
        text: cleanText,
        allowHeightExpansion: true,
      });
    });

    // Bước 2: Khử va chạm bằng phân vùng hướng tâm (Inward Partitioning)
    // Giữ nguyên biên ngoài cùng của cụm ô thoại để không bao giờ bị đẩy tràn qua rãnh tranh
    const resolvedBoxes = resolveBoxCollisions(candidateBoxes, dispW, dispH, 4);

    // Bước 3: Render từng ô thoại với auto-fit typography không gây layout thrashing
    for (let i = 0; i < blocks.length; i += 1) {
      const blk = blocks[i];
      const scaled = resolvedBoxes[i] || candidateBoxes[i];
      const cleanText = (blk.translation || "").trim();

      const colors = sampleBorderBackgroundColor(
        rgbaPixels,
        natW,
        natH,
        blk.bbox
      );

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

      boxEl.style.setProperty("white-space", "normal", "important");
      boxEl.style.setProperty("word-break", "normal", "important");
      boxEl.style.setProperty("overflow-wrap", "break-word", "important");
      boxEl.style.setProperty("hyphens", "none", "important");
      boxEl.style.setProperty("line-height", "1.22", "important");
      boxEl.style.setProperty("text-align", "center", "important");
      boxEl.style.setProperty("display", "flex", "important");
      boxEl.style.setProperty("align-items", "center", "important");
      boxEl.style.setProperty("justify-content", "center", "important");
      boxEl.style.setProperty("padding", "3px 4px", "important");

      // Cỡ chữ đồng đều cho thoại truyện tranh (10px - 13.5px), không phóng to dị biệt lên 26px
      const isTitleBlock =
        blk.source_text?.length <= 8 &&
        (scaled.height > 200 || scaled.width > 200);
      const targetMaxFont = isTitleBlock ? 20 : 13.5;
      const targetMinFont = 9.5;

      const fitted = fitTextInBox(cleanText, scaled.width, scaled.height, {
        minFontSize: targetMinFont,
        maxFontSize: targetMaxFont,
        lineHeightRatio: 1.22,
        paddingPx: 3,
      });

      // Bù chiều cao vi sai tối đa 6px nếu thiếu chút ít ở cỡ sàn 9.5px, không tràn sang panel kế bên
      if (!fitted.fitsWithoutOverflow && fitted.neededHeightPx > scaled.height) {
        const extraH = Math.min(6, fitted.neededHeightPx - scaled.height);
        const finalH = scaled.height + extraH;
        boxEl.style.height = `${Math.round(finalH)}px`;
        const newTop = Math.max(0, scaled.top - extraH / 2);
        boxEl.style.top = `${Math.round(newTop)}px`;
      }

      boxEl.style.fontSize = `${fitted.fontSizePx}px`;
      boxEl.style.lineHeight = `${fitted.lineHeightPx}px`;
      boxEl.textContent = cleanText;

      overlayLayer.appendChild(boxEl);

      // Dự phòng vi sai đo lường DOM: nếu vẫn còn overflow nhẹ, hạ cỡ font xuống 1 bước 0.5px
      if (
        boxEl.scrollHeight > boxEl.offsetHeight ||
        boxEl.scrollWidth > boxEl.offsetWidth
      ) {
        if (fitted.fontSizePx > 9) {
          boxEl.style.fontSize = `${Math.max(9, fitted.fontSizePx - 0.5)}px`;
        }
      }
    }
  }

  async function triggerTranslateItem(item: ManagedPageItem): Promise<void> {
    // Kiểm tra cờ chống gửi trùng lặp trên cả object quản lý lẫn dataset của thẻ <img>
    if (
      item.isTranslating ||
      item.isTranslated ||
      item.img.dataset.isTranslating === "true" ||
      item.img.dataset.isTranslated === "true"
    ) {
      return;
    }

    const imageUrl = extractBestImageUrl(item.img);
    if (!imageUrl) {
      return;
    }
    item.pageKey = imageUrl;

    if (queue.isBusyOrDone(imageUrl)) {
      return;
    }

    item.isTranslating = true;
    item.img.dataset.isTranslating = "true";
    item.stage.setAttribute("data-ctvn-status", "translating");
    item.translateBtn.textContent = "Đang dịch...";
    item.translateBtn.disabled = true;

    try {
      const res = await queue.enqueue(imageUrl, async () => {
        let imageDataUrl: string | undefined;
        if (imageUrl.startsWith("blob:")) {
          imageDataUrl = await blobUrlToDataUrl(imageUrl);
        }

        const idempotencyKey = `ctvn_${adapter.id}_${btoa(
          encodeURIComponent(imageUrl)
        )
          .replace(/[^a-zA-Z0-9]/g, "")
          .slice(-42)}_${readingDirection}`;

        const contextPayload = buildTranslationContextPayload(
          document.title || adapter.displayName,
          customContextText
        );

        const bgResp = await chrome.runtime.sendMessage({
          type: "TRANSLATE_PAGE",
          payload: {
            imageUrl,
            imageDataUrl,
            langPair: adapter.langPair,
            idempotencyKey,
            readingDirection,
            refererOrigin: adapter.refererOrigin,
            context: contextPayload,
          },
        });

        if (!bgResp || !bgResp.ok) {
          throw new Error(bgResp?.error || "Lỗi gọi dịch trang");
        }
        return (bgResp.data?.blocks || []) as TranslatedBlock[];
      });

      if (res.value) {
        item.blocks = res.value;
        item.isTranslating = false;
        item.isTranslated = true;
        item.img.dataset.isTranslating = "false";
        item.img.dataset.isTranslated = "true";
        item.showingOriginal = false;
        item.stage.setAttribute("data-ctvn-status", "translated");
        item.translateBtn.textContent = "Đã dịch";
        item.toggleBtn.style.display = "inline-block";
        item.toggleBtn.textContent = "Xem bản gốc";
        renderOverlayBlocks(item);
      }
    } catch (err) {
      item.isTranslating = false;
      item.img.dataset.isTranslating = "false";
      queue.resetKey(imageUrl);
      item.stage.setAttribute("data-ctvn-status", "error");
      item.translateBtn.textContent = "Lỗi - Thử lại";
      item.translateBtn.disabled = false;
      item.translateBtn.title = err instanceof Error ? err.message : String(err);
    }
  }

  function updateDebugUI(): void {
    debugSelectorBtn.classList.toggle("ctvn-active", debugSelectorMode);
    for (const item of managedItems.values()) {
      item.stage.classList.toggle("ctvn-debug-highlight", debugSelectorMode);
      if (debugSelectorMode) {
        const derived = deriveCssSelectorForElement(item.img);
        const natW = item.img.naturalWidth || item.img.width;
        const natH = item.img.naturalHeight || item.img.height;
        const bestUrl = extractBestImageUrl(item.img);
        item.debugBadge.textContent = `[Inspector] Selector: "${derived}" | ${natW}x${natH}px | URL: ${bestUrl.slice(
          0,
          48
        )} (Click để lưu selector này)`;
      }
    }
  }

  function attachToComicImage(img: HTMLImageElement): void {
    if (managedItems.has(img)) {
      return;
    }

    const bestUrl = extractBestImageUrl(img);
    const metrics = {
      naturalWidth: img.naturalWidth || Number(img.getAttribute("width")) || 0,
      naturalHeight: img.naturalHeight || Number(img.getAttribute("height")) || 0,
      displayWidth: img.clientWidth || img.width || 0,
      displayHeight: img.clientHeight || img.height || 0,
      src: bestUrl,
      alt: img.alt,
      className: img.className,
      id: img.id,
    };

    if (!isComicCandidateImage(metrics, adapter)) {
      return;
    }

    // Nếu ảnh dùng lazy-load data-src mà chưa gán vào src, đồng bộ sang src để hiển thị ổn định
    if (
      bestUrl &&
      (!img.getAttribute("src") ||
        img.getAttribute("src")?.startsWith("data:image/gif"))
    ) {
      img.src = bestUrl;
      if (img.dataset.phase === "placeholder") {
        img.dataset.phase = "real";
      }
    }

    const stage = document.createElement("div");
    stage.className = "ctvn-image-stage";
    stage.setAttribute("data-testid", "ctvn-image-stage");

    const parent = img.parentNode;
    if (!parent) {
      return;
    }
    parent.insertBefore(stage, img);
    stage.appendChild(img);

    // Dọn dẹp phần tử placeholder/spinner của trang web gốc (như div.placeholder của Baozimh).
    // Do img đã được bốc vào stage, logic o.parentElement?.querySelector(".placeholder")?.remove()
    // của web gốc bị trỏ nhầm vào stage và không xóa được placeholder ở thẻ cha cũ.
    const removeHostPlaceholder = () => {
      // 1. Kiểm tra phần tử anh em liền kề (trước/sau stage)
      const prev = stage.previousElementSibling as HTMLElement | null;
      if (
        prev &&
        (prev.classList.contains("placeholder") ||
          prev.classList.contains("lazyloading") ||
          prev.id === "loadimg")
      ) {
        prev.remove();
      }
      const next = stage.nextElementSibling as HTMLElement | null;
      if (
        next &&
        (next.classList.contains("placeholder") ||
          next.classList.contains("lazyloading"))
      ) {
        next.remove();
      }

      // 2. Nếu thẻ cha chỉ chứa duy nhất bức ảnh này (như div.relative của Baozimh)
      const p = stage.parentElement;
      if (p && p.querySelectorAll("img").length <= 1) {
        const ph = p.querySelector(
          ".placeholder, .lazyloading, [class*='placeholder']"
        );
        if (ph && ph !== stage && !stage.contains(ph)) {
          ph.remove();
        }
      }

      // Đảm bảo ảnh luôn hiển thị đầy đủ
      img.style.visibility = "visible";
      img.style.display = "block";
    };

    if (img.complete && (img.naturalWidth > 0 || img.width > 0)) {
      removeHostPlaceholder();
    } else {
      img.addEventListener("load", removeHostPlaceholder, { once: true });
    }
    removeHostPlaceholder();

    const overlayLayer = document.createElement("div");
    overlayLayer.className = "ctvn-overlay-layer";
    overlayLayer.setAttribute("data-testid", "ctvn-overlay-layer");

    const loadingIndicator = document.createElement("div");
    loadingIndicator.className = "ctvn-loading-indicator";
    loadingIndicator.setAttribute("data-testid", "ctvn-loading-indicator");
    loadingIndicator.innerHTML = `<span class="ctvn-spinner-dot"></span><span>Đang dịch trang...</span>`;

    const controlsBar = document.createElement("div");
    controlsBar.className = "ctvn-controls-bar";

    const translateBtn = document.createElement("button");
    translateBtn.type = "button";
    translateBtn.className = "ctvn-btn ctvn-btn-translate-page";
    translateBtn.setAttribute("data-testid", "ctvn-btn-translate-page");
    translateBtn.textContent = "Dịch trang này";

    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "ctvn-btn ctvn-btn-toggle ctvn-btn-toggle-page";
    toggleBtn.setAttribute("data-testid", "ctvn-btn-toggle-page");
    toggleBtn.textContent = "Xem bản gốc";

    const debugBadge = document.createElement("div");
    debugBadge.className = "ctvn-debug-badge";
    debugBadge.setAttribute("data-testid", "ctvn-debug-badge");

    controlsBar.appendChild(translateBtn);
    controlsBar.appendChild(toggleBtn);
    stage.appendChild(overlayLayer);
    stage.appendChild(loadingIndicator);
    stage.appendChild(controlsBar);
    stage.appendChild(debugBadge);

    img.dataset.isTranslating = "false";
    img.dataset.isTranslated = "false";

    const item: ManagedPageItem = {
      img,
      stage,
      overlayLayer,
      loadingIndicator,
      translateBtn,
      toggleBtn,
      debugBadge,
      blocks: [],
      showingOriginal: false,
      pageKey: bestUrl,
      isTranslating: false,
      isTranslated: false,
      isIntersectingViewport: false,
    };
    managedItems.set(img, item);

    translateBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      void triggerTranslateItem(item);
    });

    toggleBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      item.showingOriginal = !item.showingOriginal;
      toggleBtn.textContent = item.showingOriginal
        ? "Xem bản dịch"
        : "Xem bản gốc";
      renderOverlayBlocks(item);
    });

    debugBadge.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const selector = deriveCssSelectorForElement(img);
      customSelector = selector;
      chrome.runtime.sendMessage({
        type: "SAVE_CUSTOM_SELECTOR",
        hostname: window.location.hostname,
        selector,
      });
      debugBadge.textContent = `Đã lưu selector: "${selector}" vào bộ nhớ Extension!`;
    });

    intersectionObserver.observe(img);
    resizeObserver.observe(img);
    if (debugSelectorMode) {
      updateDebugUI();
    }
  }

  function scanPageForComicImages(): void {
    const selectors = customSelector
      ? [customSelector, ...adapter.candidateSelectors]
      : adapter.candidateSelectors;
    const combinedSelector = selectors.join(", ");
    const candidates = document.querySelectorAll<HTMLImageElement>(combinedSelector);
    candidates.forEach((img) => {
      if (img.complete && (img.naturalWidth > 0 || img.width > 0)) {
        attachToComicImage(img);
      } else {
        img.addEventListener("load", () => attachToComicImage(img), {
          once: true,
        });
        attachToComicImage(img);
      }
    });
  }

  /**
   * Khi bật chế độ "Cuộn tới đâu dịch tới đó", CHỈ đưa vào hàng đợi những ảnh
   * hiện đang nằm trong tầm nhìn (viewport + 200px), phần còn lại sẽ do IntersectionObserver
   * tự động kích hoạt tuần tự khi người đọc cuộn trang tới.
   */
  function enqueueVisibleViewportImagesOnly(): void {
    if (!autoScrollEnabled) {
      return;
    }
    for (const item of managedItems.values()) {
      if (
        !item.isTranslating &&
        !item.isTranslated &&
        (item.isIntersectingViewport || isElementNearViewport(item.img, 200))
      ) {
        void triggerTranslateItem(item);
      }
    }
  }

  autoScrollBtn.addEventListener("click", () => {
    autoScrollEnabled = !autoScrollEnabled;
    autoScrollBtn.classList.toggle("ctvn-active", autoScrollEnabled);
    autoScrollBtn.textContent = autoScrollEnabled
      ? "Đang dịch tự động khi cuộn"
      : "Dịch toàn bộ khi cuộn";
    if (autoScrollEnabled) {
      enqueueVisibleViewportImagesOnly();
    }
  });

  toggleAllBtn.addEventListener("click", () => {
    globalShowOriginal = !globalShowOriginal;
    toggleAllBtn.textContent = globalShowOriginal
      ? "Đang xem bản gốc"
      : "Xem bản gốc / Bản dịch";
    for (const item of managedItems.values()) {
      if (item.blocks.length > 0) {
        renderOverlayBlocks(item);
      }
    }
  });

  debugSelectorBtn.addEventListener("click", () => {
    debugSelectorMode = !debugSelectorMode;
    chrome.runtime.sendMessage({
      type: "SET_CONFIG",
      patch: { debugSelectorMode },
    });
    updateDebugUI();
  });

  chrome.runtime.sendMessage({ type: "GET_STATE" }, (resp) => {
    if (resp?.ok && resp.state) {
      debugSelectorMode = Boolean(resp.state.debugSelectorMode);
      customSelector =
        resp.state.customSelectors?.[window.location.hostname] || "";
      customContextText = String(resp.state.customContext || "").slice(
        0,
        MAX_CUSTOM_CONTEXT_LENGTH
      );
      contextTextarea.value = customContextText;
      contextCounter.textContent = `${customContextText.length}/${MAX_CUSTOM_CONTEXT_LENGTH}`;
      scanPageForComicImages();
      updateDebugUI();
    } else {
      scanPageForComicImages();
    }
  });

  const domObserver = new MutationObserver(() => {
    scanPageForComicImages();
  });
  domObserver.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src", "data-src", "data-original", "srcset"],
  });
}
