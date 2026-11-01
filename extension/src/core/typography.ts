/**
 * Toàn bộ 134 ký tự tiếng Việt có dấu (chữ thường + chữ hoa) để kiểm định độ phủ font chữ.
 */
export const VIETNAMESE_DIACRITICS_FULL =
  "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ" +
  "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ";

export const VIETNAMESE_FONT_FAMILY =
  "'Be Vietnam Pro', 'Noto Sans', 'Segoe UI', Roboto, Arial, sans-serif";

export interface FontCoverageReport {
  isComplete: boolean;
  totalRequiredChars: number;
  missingChars: string[];
  fontFamily: string;
}

/**
 * Kiểm tra xem bảng ký tự kiểm thử có bao phủ đầy đủ 100% 134 ký tự tiếng Việt có dấu
 * và không chứa ký tự lỗi Unicode (`\uFFFD`) hay không.
 */
export function verifyVietnameseFontCoverage(
  sampleText: string = VIETNAMESE_DIACRITICS_FULL
): FontCoverageReport {
  const missingChars: string[] = [];
  if (sampleText.includes("\uFFFD")) {
    missingChars.push("\uFFFD");
  }
  for (const ch of VIETNAMESE_DIACRITICS_FULL) {
    if (!sampleText.includes(ch)) {
      missingChars.push(ch);
    }
  }
  return {
    isComplete: missingChars.length === 0,
    totalRequiredChars: VIETNAMESE_DIACRITICS_FULL.length,
    missingChars,
    fontFamily: VIETNAMESE_FONT_FAMILY,
  };
}

export interface FitTextOptions {
  minFontSize?: number;
  maxFontSize?: number;
  lineHeightRatio?: number;
  paddingPx?: number;
}

export interface FittedTextLayout {
  fontSizePx: number;
  lineHeightPx: number;
  lines: string[];
  fitsWithoutOverflow: boolean;
}

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

/**
 * Ngắt dòng tiếng Việt theo từ và tự động co cỡ chữ (`auto-fit font size`)
 * để toàn bộ bản dịch vừa khít trong khung `boxWidth x boxHeight` của bong bóng thoại.
 */
export function fitTextInBox(
  text: string,
  boxWidth: number,
  boxHeight: number,
  options: FitTextOptions = {}
): FittedTextLayout {
  const cleaned = (text || "").replace(/\s+/g, " ").trim();
  const minFont = options.minFontSize ?? 10;
  const maxFont = options.maxFontSize ?? 26;
  const lineHeightRatio = options.lineHeightRatio ?? 1.24;
  const paddingPx = options.paddingPx ?? 4;

  const usableW = Math.max(16, boxWidth - paddingPx * 2);
  const usableH = Math.max(14, boxHeight - paddingPx * 2);

  if (!cleaned) {
    return {
      fontSizePx: minFont,
      lineHeightPx: Math.round(minFont * lineHeightRatio),
      lines: [],
      fitsWithoutOverflow: true,
    };
  }

  const words = cleaned.split(" ");

  const wrapAtFontSize = (fontSize: number): string[] => {
    // Trung bình độ rộng 1 ký tự tiếng Việt có dấu với font Be Vietnam Pro / Noto Sans ~ 0.54 * fontSize
    const avgCharWidth = fontSize * 0.54;
    const maxCharsPerLine = Math.max(4, Math.floor(usableW / avgCharWidth));

    const lines: string[] = [];
    let currentLine = "";

    for (const word of words) {
      if (!currentLine) {
        if (word.length > maxCharsPerLine) {
          // Cắt từ quá dài (ví dụ URL hoặc chuỗi cảm thán AAAAA...)
          for (let i = 0; i < word.length; i += maxCharsPerLine) {
            lines.push(word.slice(i, i + maxCharsPerLine));
          }
          currentLine = lines.pop() || "";
        } else {
          currentLine = word;
        }
      } else if (currentLine.length + 1 + word.length <= maxCharsPerLine) {
        currentLine += ` ${word}`;
      } else {
        lines.push(currentLine);
        currentLine = word;
      }
    }
    if (currentLine) {
      lines.push(currentLine);
    }
    return lines;
  };

  for (let fontSize = maxFont; fontSize >= minFont; fontSize -= 1) {
    const lines = wrapAtFontSize(fontSize);
    const lineHeightPx = Math.max(fontSize + 2, Math.round(fontSize * lineHeightRatio));
    const totalHeight = lines.length * lineHeightPx;
    const longestLineChars = Math.max(...lines.map((l) => l.length), 1);
    const estMaxLineWidth = longestLineChars * fontSize * 0.54;

    if (totalHeight <= usableH && estMaxLineWidth <= usableW * 1.08) {
      return {
        fontSizePx: fontSize,
        lineHeightPx,
        lines,
        fitsWithoutOverflow: true,
      };
    }
  }

  const fallbackLines = wrapAtFontSize(minFont);
  const fallbackLineHeight = Math.max(minFont + 2, Math.round(minFont * lineHeightRatio));
  return {
    fontSizePx: minFont,
    lineHeightPx: fallbackLineHeight,
    lines: fallbackLines,
    fitsWithoutOverflow: fallbackLines.length * fallbackLineHeight <= usableH,
  };
}
