export type LangPair = "zh-vi" | "en-vi";

export const MAX_CUSTOM_CONTEXT_LENGTH = 500;

export const CUSTOM_CONTEXT_PLACEHOLDER =
  "Truyện Đại Quản Gia Là Ma Hoàng. Thể loại: Tu tiên, trùng sinh. Nam chính Trác Phàm xưng ta - ngươi/bổn tọa...";

export interface ContextPresetChip {
  id: "tu_tien" | "do_thi" | "hoc_duong" | "he_thong" | "au_co";
  label: string;
  snippet: string;
}

export const CONTEXT_PRESET_CHIPS: ContextPresetChip[] = [
  {
    id: "tu_tien",
    label: "+ Tu tiên/Cổ trang",
    snippet:
      "Thể loại: Tu tiên / Cổ trang. Xưng hô: ta - ngươi, bổn tọa/bản tôn, huynh - đệ/muội, tiền bối - vãn bối, hắn - nàng.",
  },
  {
    id: "do_thi",
    label: "+ Đô thị/Hiện đại",
    snippet:
      "Thể loại: Đô thị / Hiện đại. Xưng hô: tôi - cậu/anh/cô, anh - em, sếp - nhân viên, văn phong hiện đại tự nhiên.",
  },
  {
    id: "hoc_duong",
    label: "+ Học đường",
    snippet:
      "Thể loại: Học đường. Xưng hô: tớ - cậu, mình - bạn, đàn anh/đàn chị - đàn em, thầy/cô - em.",
  },
  {
    id: "he_thong",
    label: "+ Hệ thống/Murim",
    snippet:
      "Thể loại: Hệ thống / Thợ săn / Murim. Xưng hô: tôi - cậu/ngươi, ký chủ - hệ thống, giữ thuật ngữ kỹ năng/cấp bậc.",
  },
  {
    id: "au_co",
    label: "+ Âu cổ/Fantasy",
    snippet:
      "Thể loại: Âu cổ / Quý tộc / Kỳ ảo Tây phương. Giữ tên gốc Latin (Amelia, Wolfgang...). Xưng hô: tôi - cậu/anh/em, ngài - thần, cha/mẹ - con.",
  },
];

/**
 * Chèn hoặc nối gợi ý xưng hô từ nút Quick Preset Chip vào nội dung `textarea` hiện tại,
 * đảm bảo không vượt quá `MAX_CUSTOM_CONTEXT_LENGTH` (500 ký tự).
 */
export function applyContextPreset(
  currentText: string,
  presetId: ContextPresetChip["id"]
): string {
  const preset = CONTEXT_PRESET_CHIPS.find((p) => p.id === presetId);
  const cleanCurrent = (currentText || "").trim();
  if (!preset) {
    return cleanCurrent.slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
  }
  if (cleanCurrent.includes(preset.snippet)) {
    return cleanCurrent.slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
  }
  const combined = cleanCurrent
    ? `${cleanCurrent} ${preset.snippet}`
    : preset.snippet;
  return combined.slice(0, MAX_CUSTOM_CONTEXT_LENGTH);
}

/**
 * Đóng gói payload `context` gửi kèm trong `context_json` của `POST /api/v1/page/translate`
 * (không phát sinh bất kỳ API call phụ nào).
 */
export function buildTranslationContextPayload(
  seriesTitle: string,
  customContext: string
): { series_title: string; custom_context: string } {
  return {
    series_title: (seriesTitle || "").trim(),
    custom_context: (customContext || "")
      .trim()
      .slice(0, MAX_CUSTOM_CONTEXT_LENGTH),
  };
}

export interface SiteAdapter {
  id: "baozimh" | "hivetoons";
  displayName: string;
  hostnames: string[];
  langPair: LangPair;
  candidateSelectors: string[];
  refererOrigin: string;
  minDisplayWidth: number;
  minNaturalWidth: number;
  minHeight: number;
  selectorVerificationNote: string;
}

export const SITE_ADAPTERS: SiteAdapter[] = [
  {
    id: "baozimh",
    displayName: "Baozimh (Trung -> Việt)",
    hostnames: [
      "baozimh.org",
      "www.baozimh.org",
      "baozimh.com",
      "www.baozimh.com",
      "cn.baozimh.com",
      "tw.baozimh.com",
    ],
    langPair: "zh-vi",
    candidateSelectors: [
      ".comic-contain img",
      ".chapter-img img",
      "amp-img img",
      "img[data-src]",
      "img",
    ],
    refererOrigin: "https://www.baozimh.org/",
    minDisplayWidth: 280,
    minNaturalWidth: 450,
    minHeight: 300,
    selectorVerificationNote:
      "selector thực tế: chưa kiểm chứng, sử dụng bộ quét heuristic + công cụ Inspector nội bộ của Extension",
  },
  {
    id: "hivetoons",
    displayName: "Hivetoons (Anh -> Việt)",
    hostnames: [
      "hivetoons.org",
      "www.hivetoons.org",
      "hivetoons.com",
      "www.hivetoons.com",
      "hivecomic.com",
      "www.hivecomic.com",
    ],
    langPair: "en-vi",
    candidateSelectors: [
      ".reading-content img",
      ".chapter-content img",
      "main img",
      "img[data-src]",
      "img",
    ],
    refererOrigin: "https://hivetoons.org/",
    minDisplayWidth: 280,
    minNaturalWidth: 450,
    minHeight: 300,
    selectorVerificationNote:
      "selector thực tế: chưa kiểm chứng, sử dụng bộ quét heuristic + công cụ Inspector nội bộ của Extension",
  },
];

/**
 * Tìm adapter tương ứng với URL hoặc hostname.
 * Hỗ trợ thêm query `?site=baozimh` hoặc `?site=hivetoons` trên `127.0.0.1` / `localhost`
 * để phục vụ kiểm thử E2E cục bộ mà không gọi tới trang thật.
 */
export function matchSiteAdapter(urlOrHost: string): SiteAdapter | null {
  if (!urlOrHost || typeof urlOrHost !== "string") {
    return null;
  }
  const raw = urlOrHost.trim();
  if (!raw) {
    return null;
  }

  let hostname = "";
  let searchParams: URLSearchParams | null = null;

  try {
    const parsed = raw.includes("://") ? new URL(raw) : new URL(`https://${raw}`);
    hostname = parsed.hostname.toLowerCase();
    searchParams = parsed.searchParams;
  } catch {
    hostname = raw.split("/")[0].split(":")[0].toLowerCase();
  }

  if (hostname === "127.0.0.1" || hostname === "localhost") {
    const simulatedSite = searchParams?.get("site")?.toLowerCase();
    if (simulatedSite === "baozimh") {
      return SITE_ADAPTERS[0];
    }
    if (simulatedSite === "hivetoons") {
      return SITE_ADAPTERS[1];
    }
    return null;
  }

  for (const adapter of SITE_ADAPTERS) {
    if (
      adapter.hostnames.some(
        (h) => hostname === h || hostname.endsWith(`.${h}`)
      )
    ) {
      return adapter;
    }
  }
  return null;
}

const EXCLUDED_TOKEN_REGEX =
  /\b(avatar|logo|icon|banner|ads|advert| qrcode|thumb-small|emoji|button)\b/i;

export interface ImageCandidateMetrics {
  naturalWidth: number;
  naturalHeight: number;
  displayWidth: number;
  displayHeight: number;
  src: string;
  alt?: string;
  className?: string;
  id?: string;
}

/**
 * Bộ lọc Heuristic phát hiện ảnh trang truyện (loại trừ icon/logo/avatar/banner quảng cáo nhỏ).
 */
export function isComicCandidateImage(
  metrics: ImageCandidateMetrics,
  adapter?: SiteAdapter | null
): boolean {
  const src = (metrics.src || "").trim();
  if (!src || src.startsWith("data:image/gif") || src.startsWith("about:")) {
    return false;
  }

  const metaText = `${metrics.className || ""} ${metrics.id || ""} ${metrics.alt || ""} ${src}`;
  if (EXCLUDED_TOKEN_REGEX.test(metaText)) {
    return false;
  }

  const minNatW = adapter?.minNaturalWidth ?? 450;
  const minDispW = adapter?.minDisplayWidth ?? 280;
  const minH = adapter?.minHeight ?? 300;

  const effectiveWidthOk =
    metrics.naturalWidth >= minNatW || metrics.displayWidth >= minDispW;
  const effectiveHeight = Math.max(metrics.naturalHeight, metrics.displayHeight);

  return effectiveWidthOk && effectiveHeight >= minH;
}

/**
 * Trích xuất URL ảnh thực tế từ thẻ `<img>`, hỗ trợ đầy đủ lazy-load
 * (`data-src`, `data-original`, `data-lazy-src`, `data-url`, `srcset`, `currentSrc`, `src`) và `blob:`.
 */
export function extractBestImageUrl(img: HTMLImageElement): string {
  const lazyAttrs = [
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-url",
    "data-echo",
  ];
  for (const attr of lazyAttrs) {
    const val = img.getAttribute(attr)?.trim();
    if (val && !val.startsWith("data:image/svg") && !val.startsWith("data:image/gif")) {
      return resolveRelativeUrl(val, img.baseURI);
    }
  }

  const srcset =
    img.getAttribute("data-srcset")?.trim() || img.getAttribute("srcset")?.trim();
  if (srcset) {
    const candidates = srcset
      .split(",")
      .map((part) => part.trim().split(/\s+/)[0])
      .filter(Boolean);
    if (candidates.length > 0) {
      return resolveRelativeUrl(candidates[candidates.length - 1], img.baseURI);
    }
  }

  // Nếu là ảnh trong Web Component <amp-img>, kiểm tra thuộc tính src/data-src trên thẻ cha
  const ampParent = img.closest("amp-img");
  if (ampParent) {
    for (const attr of lazyAttrs) {
      const val = ampParent.getAttribute(attr)?.trim();
      if (val && !val.startsWith("data:image/svg") && !val.startsWith("data:image/gif")) {
        return resolveRelativeUrl(val, img.baseURI);
      }
    }
    const ampSrc = (ampParent.getAttribute("src") || "").trim();
    if (ampSrc && !ampSrc.startsWith("data:image/gif") && !ampSrc.startsWith("data:image/svg")) {
      return resolveRelativeUrl(ampSrc, img.baseURI);
    }
  }

  const direct = (img.currentSrc || img.getAttribute("src") || img.src || "").trim();
  if (direct && !direct.startsWith("data:image/gif")) {
    return resolveRelativeUrl(direct, img.baseURI);
  }
  return "";
}

function resolveRelativeUrl(url: string, baseUri?: string): string {
  if (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("blob:") ||
    url.startsWith("data:")
  ) {
    return url;
  }
  try {
    return new URL(url, baseUri || "https://localhost/").href;
  } catch {
    return url;
  }
}

/**
 * Trích xuất CSS selector tổng quát của vùng chứa ảnh khi người dùng click chọn ảnh
 * trong chế độ "Debug / Tự lấy Selector trên trang" (In-page DOM Inspector).
 */
export function deriveCssSelectorForElement(img: Element): string {
  const parent = img.parentElement;
  if (!parent) {
    return "img";
  }

  const cleanClasses = (el: Element): string[] =>
    Array.from(el.classList).filter(
      (c) => c && !c.startsWith("ctvn-") && !/^[0-9]/.test(c)
    );

  const grandParent = parent.parentElement;
  if (grandParent && grandParent.id && !grandParent.id.startsWith("ctvn-")) {
    return `#${grandParent.id} img`;
  }
  if (parent.id && !parent.id.startsWith("ctvn-")) {
    return `#${parent.id} img`;
  }

  const parentClasses = cleanClasses(parent);
  if (parentClasses.length > 0) {
    return `${parent.tagName.toLowerCase()}.${parentClasses.slice(0, 2).join(".")} img`;
  }

  if (grandParent) {
    const gpClasses = cleanClasses(grandParent);
    if (gpClasses.length > 0) {
      return `${grandParent.tagName.toLowerCase()}.${gpClasses.slice(0, 2).join(".")} img`;
    }
  }

  const imgClasses = cleanClasses(img);
  if (imgClasses.length > 0) {
    return `img.${imgClasses.slice(0, 2).join(".")}`;
  }
  return `${parent.tagName.toLowerCase()} > img`;
}
