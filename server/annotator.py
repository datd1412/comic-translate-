from __future__ import annotations

import io
import base64
from typing import Any
from PIL import Image, ImageDraw, ImageFont


def draw_numbered_bboxes(
    image: Image.Image,
    boxes: list[dict[str, Any]],
    max_dim: int = 1536,
    quality: int = 85,
) -> str:
    """
    Kỹ thuật vẽ khung đỏ đánh số thứ tự [1], [2] theo chuẩn Libre Manga Translator:
    - Thu nhỏ ảnh về độ phân giải sắc nét max_dim (1536px) để nét chữ Hán/Nhật rõ ràng, tránh nhòe nét.
    - Vẽ đường viền đỏ nổi bật (#ef4444) và huy hiệu số thứ tự ở vị trí an toàn, không đè lên chữ.
    - Nén JPEG chất lượng 85% thành chuỗi Base64 (~200KB - 280KB, siêu nhẹ và truyền cực nhanh).
    """
    w, h = image.size
    scale = 1.0
    if max(w, h) > max_dim:
        scale = float(max_dim) / float(max(w, h))

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    # Tạo canvas thu nhỏ với thuật toán chống vỡ nét LANCZOS
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

        # 2. Vẽ huy hiệu đỏ: ưu tiên đặt phía trên mép ngoài bóng thoại (y1 - badge_h)
        # Nếu chạm nóc ảnh thì đặt phía dưới đáy (y2), TUYỆT ĐỐI không đè lên chữ bên trong
        if y1 >= badge_h:
            badge_y1 = y1 - badge_h
            badge_y2 = y1
        else:
            badge_y1 = min(new_h - badge_h, y2)
            badge_y2 = badge_y1 + badge_h

        badge_x2 = min(new_w, x1 + badge_w)
        draw.rectangle([x1, badge_y1, badge_x2, badge_y2], fill="#ef4444")
        # In số màu trắng nổi bật
        draw.text((x1 + 4, badge_y1 + 2), num_str, fill="#ffffff", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

