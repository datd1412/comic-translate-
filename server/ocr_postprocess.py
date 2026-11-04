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


def _combine_dialogue_texts(t1: str, t2: str) -> str:
    """
    Nối hai đoạn văn bản của cùng một bong bóng thoại:
    - Nếu kết thúc chuỗi trước hoặc mở đầu chuỗi sau là chữ CJK (Hán/Nhật/Hàn/dấu câu CJK),
      nối trực tiếp không cần dấu cách.
    - Với chữ Latin/số: nối kèm dấu cách đơn.
    """
    t1 = t1.strip()
    t2 = t2.strip()
    if not t1:
        return t2
    if not t2:
        return t1

    cjk_pattern = r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u3000-\u303f\uff00-\uffef]"
    if re.search(cjk_pattern, t1[-1]) or re.search(cjk_pattern, t2[0]):
        return f"{t1}{t2}"
    return f"{t1} {t2}"


def merge_adjacent_vertical_dialogue(
    dialogue_blocks: list[dict[str, Any]],
    reading_direction: str = "rtl",
) -> list[dict[str, Any]]:
    """
    Gom các cột chữ dọc liền kề thuộc cùng một bong bóng thoại / khung thoại thành một khối duy nhất.
    Đảm bảo:
    1. Chỉ xét các khối thoại có dáng cột dọc (cao > 1.25 lần rộng). Các dòng ngang hoặc khối ngang
       HOÀN TOÀN không bị ảnh hưởng và không bao giờ bị gom nhầm thành cột dọc.
    2. Hai cột trong cùng bóng thoại phải có cỡ chữ (chiều rộng cột) tương đồng (tỷ lệ <= 2.5),
       khoảng cách ngang hẹp (gap_x <= col_w * 2.0 và <= 85px), và có độ phủ dọc hoặc căn lề trên/dưới.
    3. Ghép văn bản theo đúng thứ tự đọc (Manga RTL: cột bên phải trước, cột bên trái sau;
       LTR: cột bên trái trước, cột bên phải sau).
    4. Bounding box của khối hợp nhất bao trùm tất cả các cột thành phần.
    """
    if len(dialogue_blocks) <= 1:
        return list(dialogue_blocks)

    n = len(dialogue_blocks)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    bboxes = [extract_bbox(b) for b in dialogue_blocks]

    for i in range(n):
        x1_i, y1_i, x2_i, y2_i = bboxes[i]
        w_i, h_i = max(0.0, x2_i - x1_i), max(0.0, y2_i - y1_i)
        is_vert_i = h_i > w_i * 1.25

        if not is_vert_i:
            continue

        for j in range(i + 1, n):
            x1_j, y1_j, x2_j, y2_j = bboxes[j]
            w_j, h_j = max(0.0, x2_j - x1_j), max(0.0, y2_j - y1_j)
            is_vert_j = h_j > w_j * 1.25

            if not is_vert_j:
                continue

            col_w = max(w_i, w_j, 1.0)
            min_w = max(1.0, min(w_i, w_j))
            if col_w / min_w > 2.5:
                continue

            gap_x = max(0.0, max(x1_i - x2_j, x1_j - x2_i))
            if gap_x > col_w * 2.0 or gap_x > 85.0:
                continue

            overlap_y = max(0.0, min(y2_i, y2_j) - max(y1_i, y1_j))
            min_h = max(1.0, min(h_i, h_j))
            y_overlap_ratio = overlap_y / min_h
            top_aligned = abs(y1_i - y1_j) <= col_w * 2.5
            bottom_aligned = abs(y2_i - y2_j) <= col_w * 2.5
            gap_y = max(0.0, max(y1_i - y2_j, y1_j - y2_i))

            if (y_overlap_ratio >= 0.15 or top_aligned or bottom_aligned) and gap_y <= col_w * 1.5:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    merged: list[dict[str, Any]] = []
    is_rtl = str(reading_direction or "").lower() == "rtl"

    for indices in groups.values():
        if len(indices) == 1:
            merged.append(dialogue_blocks[indices[0]])
            continue

        group_blocks = [dialogue_blocks[idx] for idx in indices]

        # Sắp xếp các cột trong cụm theo thứ tự đọc:
        # Với Manga RTL: cột bên phải (center_x lớn hơn) đọc trước -> sort giảm dần theo center_x
        # Với LTR: cột bên trái (center_x nhỏ hơn) đọc trước -> sort tăng dần theo center_x
        if is_rtl:
            group_blocks.sort(key=lambda b: -((extract_bbox(b)[0] + extract_bbox(b)[2]) / 2.0))
        else:
            group_blocks.sort(key=lambda b: ((extract_bbox(b)[0] + extract_bbox(b)[2]) / 2.0))

        # Ghép nội dung văn bản
        combined_text = str(group_blocks[0].get("text", "") or "")
        for gb in group_blocks[1:]:
            next_text = str(gb.get("text", "") or "")
            combined_text = _combine_dialogue_texts(combined_text, next_text)

        # Tính bounding box bao quát toàn bộ cụm
        all_bboxes = [extract_bbox(b) for b in group_blocks]
        u_x1 = round(min(b[0] for b in all_bboxes), 2)
        u_y1 = round(min(b[1] for b in all_bboxes), 2)
        u_x2 = round(max(b[2] for b in all_bboxes), 2)
        u_y2 = round(max(b[3] for b in all_bboxes), 2)

        # Tính trung bình score (nếu có)
        scores = [float(b["score"]) for b in group_blocks if "score" in b and b["score"] is not None]
        avg_score = round(sum(scores) / len(scores), 4) if scores else None

        merged_block = dict(group_blocks[0])
        merged_block["bbox"] = [u_x1, u_y1, u_x2, u_y2]
        merged_block["text"] = combined_text
        if avg_score is not None:
            merged_block["score"] = avg_score

        # Cập nhật points nếu có
        if "points" in merged_block:
            merged_block["points"] = [
                [u_x1, u_y1],
                [u_x2, u_y1],
                [u_x2, u_y2],
                [u_x1, u_y2],
            ]

        # Kết hợp flags nếu có
        all_flags: list[str] = []
        for gb in group_blocks:
            for flag in gb.get("flags", []):
                if flag not in all_flags:
                    all_flags.append(flag)
        if all_flags:
            merged_block["flags"] = all_flags

        merged.append(merged_block)

    return merged
