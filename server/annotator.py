from __future__ import annotations

import io
import base64
from typing import Any
from PIL import Image, ImageDraw, ImageFont


def _load_badge_font(size: int) -> ImageFont.ImageFont:
    for font_name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf", "tahoma.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def draw_numbered_bboxes(
    image: Image.Image,
    boxes: list[dict[str, Any]],
    max_dim: int = 1024,
    quality: int = 75,
) -> str:
    """
    Kỹ thuật vẽ khung đỏ đánh số thứ tự [1], [2] theo chuẩn Libre Manga Translator:
    - Thu nhỏ ảnh về chiều dài/rộng tối đa max_dim (mặc định 1024px) để giảm tải token & băng thông.
    - Vẽ đường viền đỏ nổi bật (#ef4444) và huy hiệu số thứ tự ở góc trên mỗi bóng thoại.
    - Nén JPEG chất lượng 75% thành chuỗi Base64 (dung lượng chỉ ~120KB - 180KB).
    """
    w, h = image.size
    scale = 1.0
    if max(w, h) > max_dim:
        scale = float(max_dim) / float(max(w, h))

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    # Tạo canvas thu nhỏ
    canvas = image.convert("RGB").resize((new_w, new_h), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)

    line_width = max(2, int(round(2.5 * scale)))
    font_size = max(12, min(20, int(round(16 * scale))))
    font = _load_badge_font(font_size)

    for idx, item in enumerate(boxes):
        bbox = item.get("bbox") or [0, 0, 0, 0]
        x1 = int(round(bbox[0] * scale))
        y1 = int(round(bbox[1] * scale))
        x2 = int(round(bbox[2] * scale))
        y2 = int(round(bbox[3] * scale))

        num_str = str(idx + 1)
        try:
            tb = draw.textbbox((0, 0), num_str, font=font)
            tw = tb[2] - tb[0]
            th = tb[3] - tb[1]
        except Exception:
            tw = 8 * len(num_str)
            th = 12

        pad_x, pad_y = 4, 2
        badge_w = tw + pad_x * 2
        badge_h = th + pad_y * 2

        # 1. Vẽ viền đỏ quanh bóng thoại
        draw.rectangle([x1, y1, x2, y2], outline="#ef4444", width=line_width)

        # 2. Vẽ huy hiệu đỏ chứa số thứ tự ở ngay phía trên viền trái (tránh đè lên chữ bên trong bóng)
        badge_y = max(0, y1 - badge_h) if y1 >= badge_h else y1
        badge_x1 = max(0, min(new_w - badge_w, x1))
        badge_x2 = min(new_w, badge_x1 + badge_w)
        badge_y2 = min(new_h, badge_y + badge_h)

        draw.rectangle([badge_x1, badge_y, badge_x2, badge_y2], fill="#ef4444", outline="#ffffff", width=1)
        draw.text((badge_x1 + pad_x, badge_y + pad_y - 1), num_str, fill="#ffffff", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

