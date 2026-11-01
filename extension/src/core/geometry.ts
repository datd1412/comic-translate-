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
