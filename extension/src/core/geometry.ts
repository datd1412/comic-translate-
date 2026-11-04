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
  const targetMinWidth = options.minWidth ?? 85; // Giới hạn tối thiểu từ 70px - 100px
  const minExpand = options.minExpandRatio ?? 1.6;
  const maxExpand = options.maxExpandRatio ?? 2.2;
  const hardMaxWidth = options.maxWidth ?? (options.text ? 180 : 135);

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

  // 2. Độ rộng mục tiêu thích ứng theo độ dài văn bản dịch tiếng Việt
  let desiredWidth = targetMinWidth;
  const cleanText = (options.text || "").trim();
  if (cleanText) {
    const words = cleanText.split(/\s+/).filter(Boolean);
    const wordCount = words.length;
    if (wordCount >= 10) {
      desiredWidth = Math.max(targetMinWidth, 140);
    } else if (wordCount >= 6) {
      desiredWidth = Math.max(targetMinWidth, 115);
    } else if (wordCount >= 3) {
      desiredWidth = Math.max(targetMinWidth, 95);
    }
  }

  // 3. Khung bong bóng dọc (Vertical Bubble) trong tranh:
  let newWidth = box.width;

  if (box.width < desiredWidth) {
    // Khung rất hẹp (1 cột chữ CJK 20px - 45px): mở rộng 1.6x - 2.2x và đạt tối thiểu desiredWidth
    const expandRatio = Math.min(
      maxExpand,
      Math.max(minExpand, 1.4 + (aspectRatio - 1.4) * 0.25)
    );
    newWidth = Math.min(hardMaxWidth, Math.max(box.width * expandRatio, desiredWidth));
  } else {
    // Khung đã đủ rộng: chỉ thêm chút đệm nhẹ, không nhân 2.2x tránh tràn ra ngoài bong bóng vẽ
    newWidth = Math.min(box.width + 16, Math.min(box.width * 1.15, hardMaxWidth));
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

  // 4. Mở rộng chiều cao thích ứng (Adaptive height expansion) nếu văn bản nhiều dòng
  let newHeight = box.height;
  let newTop = box.top;
  if (options.allowHeightExpansion && cleanText) {
    const usableW = Math.max(20, newWidth - 12);
    const charsPerLine = Math.max(4, Math.floor(usableW / (11 * 0.54)));
    const estLines = Math.ceil(cleanText.length / charsPerLine);
    const neededH = estLines * (11 * 1.25 + 2) + 10;
    if (neededH > box.height) {
      newHeight = Math.round(
        Math.min(box.height * 1.35, Math.max(box.height, neededH)) * 100
      ) / 100;
      if (containerHeight > 0 && newHeight > containerHeight) {
        newHeight = containerHeight;
      }
      const centerY = box.top + box.height / 2;
      newTop = Math.round((centerY - newHeight / 2) * 100) / 100;
      if (newTop < 0) {
        newTop = 0;
      } else if (containerHeight > 0 && newTop + newHeight > containerHeight) {
        newTop = Math.max(0, containerHeight - newHeight);
      }
    }
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
 * Duyệt các cặp box bị chồng lấn (overlap cả X và Y) và dãn cách nhẹ sang hai phía,
 * đồng thời co nhẹ chiều rộng nếu không gian quá chật để không bao giờ có cảnh
 * một khung thoại che đè mất chữ của khung thoại bên cạnh.
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
  const maxPasses = 5;

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

        // Chỉ xử lý nếu hai box thực sự giao nhau
        if (ox > 0 && oy > 0) {
          hasCollision = true;

          const c1x = b1.left + b1.width / 2;
          const c2x = b2.left + b2.width / 2;
          const c1y = b1.top + b1.height / 2;
          const c2y = b2.top + b2.height / 2;

          const dx = Math.abs(c1x - c2x);
          const dy = Math.abs(c1y - c2y);

          // Phân biệt hướng cần dãn cách:
          // Nếu khoảng cách tâm theo X lớn hơn Y, hoặc overlap X nhỏ hơn overlap Y -> dãn ngang
          if (ox <= oy || dx >= dy) {
            const [leftBox, rightBox] = c1x <= c2x ? [b1, b2] : [b2, b1];
            const shift = (ox + gap) / 2;

            leftBox.left = Math.max(0, leftBox.left - shift);
            if (containerWidth > 0) {
              rightBox.left = Math.min(
                containerWidth - rightBox.width,
                rightBox.left + shift
              );
            } else {
              rightBox.left += shift;
            }

            // Nếu sau khi dãn biên vẫn còn cọ xát (do chạm viền ảnh), co bớt chiều rộng hai box
            const remainingOx = leftBox.left + leftBox.width - rightBox.left;
            if (remainingOx > -gap) {
              const excess = remainingOx + gap;
              const trim = excess / 2;
              if (leftBox.width > 60) {
                leftBox.width = Math.max(60, leftBox.width - trim);
              }
              if (rightBox.width > 60) {
                rightBox.width = Math.max(60, rightBox.width - trim);
                if (containerWidth > 0) {
                  rightBox.left = Math.min(
                    containerWidth - rightBox.width,
                    rightBox.left + trim
                  );
                } else {
                  rightBox.left += trim;
                }
              }
            }
          } else {
            // Dãn dọc
            const [topBox, bottomBox] = c1y <= c2y ? [b1, b2] : [b2, b1];
            const shift = (oy + gap) / 2;

            topBox.top = Math.max(0, topBox.top - shift);
            if (containerHeight > 0) {
              bottomBox.top = Math.min(
                containerHeight - bottomBox.height,
                bottomBox.top + shift
              );
            } else {
              bottomBox.top += shift;
            }

            const remainingOy = topBox.top + topBox.height - bottomBox.top;
            if (remainingOy > -gap) {
              const excess = remainingOy + gap;
              const trim = excess / 2;
              if (topBox.height > 24) {
                topBox.height = Math.max(24, topBox.height - trim);
              }
              if (bottomBox.height > 24) {
                bottomBox.height = Math.max(24, bottomBox.height - trim);
                if (containerHeight > 0) {
                  bottomBox.top = Math.min(
                    containerHeight - bottomBox.height,
                    bottomBox.top + trim
                  );
                } else {
                  bottomBox.top += trim;
                }
              }
            }
          }
        }
      }
    }

    if (!hasCollision) {
      break;
    }
  }

  // Làm tròn 2 chữ số thập phân
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
