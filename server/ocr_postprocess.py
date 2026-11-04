from __future__ import annotations

import re
from typing import Any

from reading_order import extract_bbox

CHAPTER_LABEL_PATTERN = re.compile(r"^\s*第\s*\d+\s*[话話章回集]")


def normalize_text(block: dict[str, Any]) -> dict[str, Any]:
    """
    Chuẩn hóa văn bản trong block:
    - Với khối dọc (cao > 1.5 lần rộng): thay '：' và ':' bằng '…'.
    - Ở khối bất kỳ: bỏ ký tự '中' đứng cuối text nếu ngay trước nó là nhãn chương.
    """
    text = str(block.get("text", "") or "")
    x1, y1, x2, y2 = extract_bbox(block)
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)

    # 1. Khối dọc (cao > 1.5 lần rộng): thay thế dấu hai chấm
    if h > 1.5 * w:
        text = text.replace("：", "…").replace(":", "…")

    # 2. Bỏ ký tự '中' đứng cuối text nếu ngay trước nó là nhãn chương
    stripped = text.rstrip()
    if stripped.endswith("中"):
        prefix = stripped[:-1].rstrip()
        if CHAPTER_LABEL_PATTERN.search(prefix):
            text = prefix

    block["text"] = text
    return block


def split_blocks(
    blocks: list[dict[str, Any]],
    img_w: float,
    img_h: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Phân loại các khối văn bản thành 3 nhóm: (dialogue, edge_strips, ignored).
    Mỗi phần tử được gắn thêm trường `kind`:
    - ignored: text khớp regex nhãn chương hoặc watermark góc dưới phải.
               Ghi lại {id, text, reason} vào list để debug.
    - edge_strips: các dải chữ dọc ở mép trang truyện (kind="title").
    - dialogue: các khối bóng thoại thông thường (kind="dialogue").
    """
    w_bound = max(1.0, float(img_w))
    h_bound = max(1.0, float(img_h))

    dialogue: list[dict[str, Any]] = []
    edge_strips: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []

    for block in blocks:
        text = str(block.get("text", "") or "")
        x1, y1, x2, y2 = extract_bbox(block)
        w = max(0.0, x2 - x1)
        h = max(0.0, y2 - y1)

        # Kiểm tra điều kiện ignored
        reason: str | None = None
        if CHAPTER_LABEL_PATTERN.search(text):
            reason = "chapter_label"
        elif len(text.strip()) <= 6 and y1 > 0.94 * h_bound and x1 > 0.8 * w_bound:
            reason = "bottom_right_corner_text"

        if reason is not None:
            block["kind"] = "ignored"
            block["reason"] = reason
            ignored.append(block)
            continue

        # Kiểm tra điều kiện edge_strips
        is_edge = (x1 < 0.1 * w_bound) or (x2 > 0.9 * w_bound)
        is_tall = h > 0.25 * h_bound
        is_slender = h > 3.0 * w

        if is_edge and is_tall and is_slender:
            block["kind"] = "title"
            edge_strips.append(block)
        else:
            block["kind"] = "dialogue"
            dialogue.append(block)

    return dialogue, edge_strips, ignored
