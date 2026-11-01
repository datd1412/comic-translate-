import { describe, expect, it } from "vitest";
import {
  applyContextPreset,
  buildTranslationContextPayload,
  deriveCssSelectorForElement,
  extractBestImageUrl,
  isComicCandidateImage,
  matchSiteAdapter,
  MAX_CUSTOM_CONTEXT_LENGTH,
} from "../../src/core/adapters";
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

describe("1. Adapter matching, Lazy-load extractor & Heuristic scanner", () => {
  it("matches baozimh.org and hivetoons.org domains and rejects unsupported domains", () => {
    const baozi = matchSiteAdapter("https://www.baozimh.org/comic/chapter/1");
    expect(baozi).not.toBeNull();
    expect(baozi?.id).toBe("baozimh");
    expect(baozi?.langPair).toBe("zh-vi");

    const hive = matchSiteAdapter("https://hivetoons.org/series/solo-chap-1");
    expect(hive).not.toBeNull();
    expect(hive?.id).toBe("hivetoons");
    expect(hive?.langPair).toBe("en-vi");

    const unsupported = matchSiteAdapter("https://vnexpress.net/tin-tuc");
    expect(unsupported).toBeNull();
  });

  it("extracts lazy-load URLs from data-src, data-original, srcset, and blob:", () => {
    const img1 = document.createElement("img");
    img1.setAttribute("src", "data:image/gif;base64,R0lGODlhAQABAAAAACw=");
    img1.setAttribute("data-src", "https://cdn.baozimh.org/page_01.jpg");
    expect(extractBestImageUrl(img1)).toBe("https://cdn.baozimh.org/page_01.jpg");

    const img2 = document.createElement("img");
    img2.setAttribute(
      "srcset",
      "https://cdn.hivetoons.org/p1_400w.webp 400w, https://cdn.hivetoons.org/p1_1000w.webp 1000w"
    );
    expect(extractBestImageUrl(img2)).toBe(
      "https://cdn.hivetoons.org/p1_1000w.webp"
    );

    const imgBlob = document.createElement("img");
    imgBlob.setAttribute("src", "blob:https://hivetoons.org/9f8e7d6c-1234");
    expect(extractBestImageUrl(imgBlob)).toBe(
      "blob:https://hivetoons.org/9f8e7d6c-1234"
    );
  });

  it("filters out small icons/logos/avatars and accepts valid comic pages", () => {
    expect(
      isComicCandidateImage({
        naturalWidth: 800,
        naturalHeight: 1400,
        displayWidth: 600,
        displayHeight: 1050,
        src: "https://cdn.baozimh.org/ch1/01.jpg",
      })
    ).toBe(true);

    expect(
      isComicCandidateImage({
        naturalWidth: 64,
        naturalHeight: 64,
        displayWidth: 64,
        displayHeight: 64,
        src: "https://cdn.baozimh.org/icon.png",
      })
    ).toBe(false);

    expect(
      isComicCandidateImage({
        naturalWidth: 900,
        naturalHeight: 400,
        displayWidth: 900,
        displayHeight: 400,
        src: "https://cdn.baozimh.org/top-banner-ads.jpg",
        className: "header-banner-ads",
      })
    ).toBe(false);
  });

  it("derives clean CSS selector for In-page DOM Inspector", () => {
    const container = document.createElement("div");
    container.className = "comic-contain reader-view";
    const img = document.createElement("img");
    container.appendChild(img);
    expect(deriveCssSelectorForElement(img)).toBe(
      "div.comic-contain.reader-view img"
    );
  });

  it("applies Quick Preset Chips and packages custom_context within 500-char limit", () => {
    const step1 = applyContextPreset("Truyện Đại Quản Gia Là Ma Hoàng.", "tu_tien");
    expect(step1).toContain("Truyện Đại Quản Gia Là Ma Hoàng.");
    expect(step1).toContain("bổn tọa/bản tôn");

    // Bấm lại cùng 1 chip không bị nhân đôi nội dung
    const step2 = applyContextPreset(step1, "tu_tien");
    expect(step2).toBe(step1);

    // Kiểm tra cắt đúng trần 500 ký tự và đóng gói vào context_json
    const longInput = "A".repeat(650);
    const payload = buildTranslationContextPayload("Đại Quản Gia", longInput);
    expect(payload.series_title).toBe("Đại Quản Gia");
    expect(payload.custom_context.length).toBe(MAX_CUSTOM_CONTEXT_LENGTH);
  });
});

describe("2. SequentialPageQueue (concurrency = 1 & deduplication)", () => {
  it("runs tasks sequentially one by one and skips duplicate image keys", async () => {
    const queue = new SequentialPageQueue<string>(1);
    const executionOrder: string[] = [];

    const task1 = queue.enqueue("https://cdn/img1.jpg", async () => {
      executionOrder.push("start-1");
      await new Promise((r) => setTimeout(r, 25));
      executionOrder.push("end-1");
      return "translated-1";
    });

    // Gửi trùng lặp cùng img1 khi img1 đang xử lý -> phải bị bỏ qua
    const dupTask1 = queue.enqueue("https://cdn/img1.jpg", async () => {
      executionOrder.push("dup-1-should-not-run");
      return "dup";
    });

    const task2 = queue.enqueue("https://cdn/img2.jpg", async () => {
      executionOrder.push("start-2");
      await new Promise((r) => setTimeout(r, 10));
      executionOrder.push("end-2");
      return "translated-2";
    });

    const [res1, resDup, res2] = await Promise.all([task1, dupTask1, task2]);
    expect(res1).toEqual({ skippedDuplicate: false, value: "translated-1" });
    expect(resDup.skippedDuplicate).toBe(true);
    expect(res2).toEqual({ skippedDuplicate: false, value: "translated-2" });
    expect(executionOrder).toEqual(["start-1", "end-1", "start-2", "end-2"]);

    // Gửi lại img1 sau khi đã hoàn tất -> vẫn phải được nhận diện là đã dịch xong
    const afterDoneDup = await queue.enqueue("https://cdn/img1.jpg", async () => "again");
    expect(afterDoneDup.skippedDuplicate).toBe(true);
    expect(afterDoneDup.value).toBe("translated-1");
  });
});

describe("3. Coordinate scaling & Background color sampling", () => {
  it("scales bbox accurately when image is resized by CSS", () => {
    const scaled = scaleBboxToDisplay(
      [100, 200, 300, 500],
      1000,
      2000,
      500,
      1000
    );
    expect(scaled.left).toBe(50);
    expect(scaled.top).toBe(100);
    expect(scaled.width).toBe(100);
    expect(scaled.height).toBe(150);
    expect(scaled.scaleX).toBe(0.5);
    expect(scaled.scaleY).toBe(0.5);
  });

  it("samples perimeter pixels around bbox for natural bubble background masking", () => {
    const w = 20;
    const h = 20;
    const rgba = new Uint8ClampedArray(w * h * 4);
    for (let i = 0; i < rgba.length; i += 4) {
      rgba[i] = 250;
      rgba[i + 1] = 248;
      rgba[i + 2] = 240;
      rgba[i + 3] = 255;
    }
    const sampled = sampleBorderBackgroundColor(rgba, w, h, [2, 2, 16, 16]);
    expect(sampled.bgCss).toBe("rgb(250, 248, 240)");
    expect(sampled.textCss).toBe("rgb(15, 23, 42)");
  });
});

describe("4. Auto-fit text layout & 100% Vietnamese diacritics coverage", () => {
  it("shrinks font size and wraps lines to fit inside speech bubble bbox", () => {
    const text = "Ngươi dám cản đường bản tôn sao?! Mau tránh ra ngay lập tức!";
    const fitted = fitTextInBox(text, 120, 90, {
      minFontSize: 10,
      maxFontSize: 26,
    });
    expect(fitted.lines.length).toBeGreaterThan(1);
    expect(fitted.fontSizePx).toBeGreaterThanOrEqual(10);
    expect(fitted.fontSizePx).toBeLessThanOrEqual(26);
    expect(fitted.fitsWithoutOverflow).toBe(true);
  });

  it("verifies full 134 Vietnamese accented characters coverage", () => {
    const report = verifyVietnameseFontCoverage(VIETNAMESE_DIACRITICS_FULL);
    expect(report.isComplete).toBe(true);
    expect(report.totalRequiredChars).toBe(134);
    expect(report.missingChars).toHaveLength(0);
  });
});

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
