export interface ScaledBox {
  left: number;
  top: number;
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
}

/**
 * Quy đổi tọa độ `bbox = [x1, y1, x2, y2]` từ kích thước ảnh gốc (`naturalWidth x naturalHeight`)
 * sang kích thước hiển thị CSS thực tế trên trang (`displayWidth x displayHeight`).
 */
export function scaleBboxToDisplay(
  bbox: [number, number, number, number] | number[],
  naturalWidth: number,
  naturalHeight: number,
  displayWidth: number,
  displayHeight: number
): ScaledBox {
  const safeNatW = Math.max(1, naturalWidth);
  const safeNatH = Math.max(1, naturalHeight);
  const safeDispW = Math.max(1, displayWidth);
  const safeDispH = Math.max(1, displayHeight);

  const scaleX = safeDispW / safeNatW;
  const scaleY = safeDispH / safeNatH;

  const [rawX1 = 0, rawY1 = 0, rawX2 = 0, rawY2 = 0] = bbox;
  const x1 = Math.max(0, Math.min(safeNatW, Math.min(rawX1, rawX2)));
  const y1 = Math.max(0, Math.min(safeNatH, Math.min(rawY1, rawY2)));
  const x2 = Math.max(0, Math.min(safeNatW, Math.max(rawX1, rawX2)));
  const y2 = Math.max(0, Math.min(safeNatH, Math.max(rawY1, rawY2)));

  const left = Math.round(x1 * scaleX * 100) / 100;
  const top = Math.round(y1 * scaleY * 100) / 100;
  const width = Math.max(12, Math.round((x2 - x1) * scaleX * 100) / 100);
  const height = Math.max(12, Math.round((y2 - y1) * scaleY * 100) / 100);

  return {
    left,
    top,
    width,
    height,
    scaleX,
    scaleY,
  };
}

export interface VerticalBoxExpansionOptions {
  minWidth?: number;
  maxWidth?: number;
  aspectRatioThreshold?: number;
  minExpandRatio?: number;
  maxExpandRatio?: number;
  text?: string;
  allowHeightExpansion?: boolean;
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
  const targetMinWidth = options.minWidth ?? 85;
  const hardMaxWidth = options.maxWidth ?? 115;

  const aspectRatio = box.height / Math.max(1, box.width);
  if (aspectRatio <= threshold) {
    return { ...box };
  }

  // 1. Chỉ coi là lề trang (margin banner) nếu thực sự nằm sát mép biên ảnh (< 6% hoặc > 94%)
  const isEdgeX =
    containerWidth > 0
      ? box.left < containerWidth * 0.06 ||
        box.left + box.width > containerWidth * 0.94
      : false;
  const isMarginBanner =
    isEdgeX &&
    ((containerHeight > 0 && box.height > containerHeight * 0.35) ||
      (box.height >= 320 && box.width <= 60));

  if (isMarginBanner) {
    const marginWidth = Math.min(Math.max(box.width, 60), 80);
    const centerX = box.left + box.width / 2;
    let newLeft = Math.round((centerX - marginWidth / 2) * 100) / 100;
    if (newLeft < 0) newLeft = 0;
    return { ...box, left: newLeft, width: marginWidth };
  }

  // 2. Độ rộng mục tiêu vừa vặn với kích thước bong bóng truyện tranh,
  // không nở quá to (tối đa 115px) để không tràn qua viền khung tranh hay che mất hình vẽ
  let desiredWidth = targetMinWidth;
  if (box.width <= 35) {
    desiredWidth = 85;
  } else if (box.width <= 60) {
    desiredWidth = 95;
  } else {
    desiredWidth = Math.min(box.width + 12, hardMaxWidth);
  }

  // 3. Khung bong bóng dọc (Vertical Bubble) trong tranh:
  let newWidth = box.width;
  if (box.width < desiredWidth) {
    newWidth = Math.min(hardMaxWidth, desiredWidth);
  } else {
    newWidth = Math.min(box.width + 12, hardMaxWidth);
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

  // 4. Mở rộng chiều cao có kiểm soát (tối đa +6px) để tránh tràn qua khe rãnh giữa các panel
  let newHeight = box.height;
  let newTop = box.top;
  if (options.allowHeightExpansion) {
    const extraH = 4;
    newHeight = box.height + extraH;
    newTop = Math.max(0, box.top - extraH / 2);
  }

  return {
    ...box,
    left: newLeft,
    top: newTop,
    width: Math.round(newWidth * 100) / 100,
    height: Math.round(newHeight * 100) / 100,
  };
}

/**
 * Khử va chạm và chồng lấn giữa các ô thoại trên cùng một trang truyện.
 * Sử dụng phân vùng hướng tâm (Inward Partitioning): giữ nguyên ranh giới ngoài cùng
 * của cụm ô thoại để không bao giờ đẩy ô thoại tràn qua viền khung tranh (panel border)
 * hay rơi ra mép trang.
 */
export function resolveBoxCollisions(
  boxes: ScaledBox[],
  containerWidth: number = 0,
  containerHeight: number = 0,
  gap: number = 4
): ScaledBox[] {
  if (boxes.length <= 1) {
    return boxes.map((b) => ({ ...b }));
  }

  const result = boxes.map((b) => ({ ...b }));
  const maxPasses = 4;

  for (let pass = 0; pass < maxPasses; pass += 1) {
    let hasCollision = false;

    for (let i = 0; i < result.length; i += 1) {
      for (let j = i + 1; j < result.length; j += 1) {
        const b1 = result[i];
        const b2 = result[j];

        const ox =
          Math.min(b1.left + b1.width, b2.left + b2.width) -
          Math.max(b1.left, b2.left);
        const oy =
          Math.min(b1.top + b1.height, b2.top + b2.height) -
          Math.max(b1.top, b2.top);

        if (ox > 0 && oy > 0) {
          hasCollision = true;

          const c1x = b1.left + b1.width / 2;
          const c2x = b2.left + b2.width / 2;
          const c1y = b1.top + b1.height / 2;
          const c2y = b2.top + b2.height / 2;

          const dx = Math.abs(c1x - c2x);
          const dy = Math.abs(c1y - c2y);

          // Phân vùng hướng tâm theo chiều ngang:
          if (ox <= oy || dx >= dy) {
            const [leftBox, rightBox] = c1x <= c2x ? [b1, b2] : [b2, b1];
            const outerLeft = leftBox.left;
            const outerRight = rightBox.left + rightBox.width;
            const availableW = outerRight - outerLeft - gap;

            if (availableW > 50) {
              const sumW = leftBox.width + rightBox.width;
              const ratioLeft = leftBox.width / Math.max(1, sumW);
              const newLeftW = Math.max(25, Math.round(availableW * ratioLeft * 100) / 100);
              const newRightW = Math.max(25, Math.round((availableW - newLeftW) * 100) / 100);
              leftBox.width = newLeftW;
              rightBox.left = Math.round((outerLeft + newLeftW + gap) * 100) / 100;
              rightBox.width = newRightW;
            }
          } else {
            // Phân vùng hướng tâm theo chiều dọc:
            const [topBox, bottomBox] = c1y <= c2y ? [b1, b2] : [b2, b1];
            const outerTop = topBox.top;
            const outerBottom = bottomBox.top + bottomBox.height;
            const availableH = outerBottom - outerTop - gap;

            if (availableH > 24) {
              const sumH = topBox.height + bottomBox.height;
              const ratioTop = topBox.height / Math.max(1, sumH);
              const newTopH = Math.max(12, Math.round(availableH * ratioTop * 100) / 100);
              const newBottomH = Math.max(12, Math.round((availableH - newTopH) * 100) / 100);
              topBox.height = newTopH;
              bottomBox.top = Math.round((outerTop + newTopH + gap) * 100) / 100;
              bottomBox.height = newBottomH;
            }
          }
        }
      }
    }

    if (!hasCollision) {
      break;
    }
  }

  return result.map((b) => ({
    ...b,
    left: Math.round(b.left * 100) / 100,
    top: Math.round(b.top * 100) / 100,
    width: Math.round(b.width * 100) / 100,
    height: Math.round(b.height * 100) / 100,
  }));
}

/**
 * Lấy mẫu màu nền từ các điểm ảnh viền xung quanh `bbox` (trong mảng RGBA)
 * để che chữ gốc tự nhiên nhất. Nếu không đọc được pixel (do CORS canvas taint),
 * trả về màu trắng ngà mặc định `#ffffff`.
 */
export function sampleBorderBackgroundColor(
  rgbaData: Uint8ClampedArray | null | undefined,
  imgWidth: number,
  imgHeight: number,
  bbox: [number, number, number, number] | number[]
): { bgCss: string; textCss: string } {
  if (!rgbaData || imgWidth <= 0 || imgHeight <= 0) {
    return { bgCss: "rgb(255, 255, 255)", textCss: "rgb(15, 23, 42)" };
  }

  const [x1Raw = 0, y1Raw = 0, x2Raw = 0, y2Raw = 0] = bbox;
  const x1 = Math.max(0, Math.min(imgWidth - 1, Math.floor(Math.min(x1Raw, x2Raw))));
  const y1 = Math.max(0, Math.min(imgHeight - 1, Math.floor(Math.min(y1Raw, y2Raw))));
  const x2 = Math.max(0, Math.min(imgWidth - 1, Math.floor(Math.max(x1Raw, x2Raw))));
  const y2 = Math.max(0, Math.min(imgHeight - 1, Math.floor(Math.max(y1Raw, y2Raw))));

  let rSum = 0;
  let gSum = 0;
  let bSum = 0;
  let count = 0;

  const samplePixel = (x: number, y: number) => {
    const idx = (y * imgWidth + x) * 4;
    if (idx >= 0 && idx + 2 < rgbaData.length) {
      rSum += rgbaData[idx];
      gSum += rgbaData[idx + 1];
      bSum += rgbaData[idx + 2];
      count += 1;
    }
  };

  const stepX = Math.max(1, Math.floor((x2 - x1) / 8));
  const stepY = Math.max(1, Math.floor((y2 - y1) / 8));

  for (let x = x1; x <= x2; x += stepX) {
    samplePixel(x, y1);
    samplePixel(x, y2);
  }
  for (let y = y1; y <= y2; y += stepY) {
    samplePixel(x1, y);
    samplePixel(x2, y);
  }

  if (count === 0) {
    return { bgCss: "rgb(255, 255, 255)", textCss: "rgb(15, 23, 42)" };
  }

  const r = Math.round(rSum / count);
  const g = Math.round(gSum / count);
  const b = Math.round(bSum / count);
  const luminance = 0.299 * r + 0.587 * g + 0.114 * b;
  const textCss = luminance < 128 ? "rgb(248, 250, 252)" : "rgb(15, 23, 42)";

  return {
    bgCss: `rgb(${r}, ${g}, ${b})`,
    textCss,
  };
}
