from __future__ import annotations

import io
import base64
from typing import Any
from PIL import Image, ImageDraw, ImageFont


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
    canvas = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)

    line_width = max(2, int(round(3 * scale)))
    badge_h = max(18, int(round(22 * scale)))

    # Cố gắng tải font mặc định có sẵn, nếu không dùng load_default
    font = ImageFont.load_default()

    for idx, item in enumerate(boxes):
        bbox = item.get("bbox") or [0, 0, 0, 0]
        x1 = int(round(bbox[0] * scale))
        y1 = int(round(bbox[1] * scale))
        x2 = int(round(bbox[2] * scale))
        y2 = int(round(bbox[3] * scale))

        num_str = str(idx + 1)
        # Tính chiều rộng huy hiệu theo số chữ số
        badge_w = max(20, int(round((14 + 10 * len(num_str)) * scale)))

        # 1. Vẽ viền đỏ quanh bóng thoại
        draw.rectangle([x1, y1, x2, y2], outline="#ef4444", width=line_width)

        # 2. Vẽ huy hiệu đỏ chứa số thứ tự ở góc trên bên trái
        badge_y = max(0, y1 - badge_h) if y1 >= badge_h else y1
        badge_x2 = min(new_w, x1 + badge_w)
        badge_y2 = min(new_h, badge_y + badge_h)

        draw.rectangle([x1, badge_y, badge_x2, badge_y2], fill="#ef4444")
        # In số màu trắng nổi bật
        draw.text((x1 + 4, badge_y + 2), num_str, fill="#ffffff", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
