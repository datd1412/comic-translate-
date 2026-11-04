from __future__ import annotations

from dataclasses import dataclass, field
import re
import statistics
import time
from typing import Any

from PIL import Image

from config import settings
from engine import DetectedLine, OCREngine

WATERMARK_PATTERNS = re.compile(
    r"(baozimh|divi5|colamanga|kuaikan|腾讯动漫|动漫|[a-z0-9\-]{2,}\.(com|org|net|cc|to|me|tv|xyz))",
    re.IGNORECASE,
)
AD_BANNER_PATTERNS = re.compile(
    r"(hivetoons|read\s+at|discord\.gg|join\s+our\s+discord|support\s+us|scanlation)",
    re.IGNORECASE,
)


@dataclass
class ShiftedLine:
    bbox: list[int]  # [x1, y1, x2, y2] trong hệ tọa độ ảnh gốc
    text: str
    score: float
    slice_index: int = 0

    @property
    def width(self) -> int:
        return max(0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> int:
        return max(0, self.bbox[3] - self.bbox[1])

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center_x(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def center_y(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0


@dataclass
class TextBlock:
    id: int
    bbox: list[int]
    text: str
    score: float
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bbox": self.bbox,
            "text": self.text,
            "score": round(self.score, 4),
            "flags": list(self.flags),
        }


def compute_slice_windows(
    image_height: int,
    threshold_px: int = settings.SLICE_HEIGHT_THRESHOLD_PX,
    chunk_height_px: int = settings.SLICE_CHUNK_HEIGHT_PX,
    overlap_px: int = settings.SLICE_OVERLAP_PX,
) -> list[tuple[int, int]]:
    """
    Tính danh sách cửa sổ cắt dọc [(y_start, y_end), ...] cho ảnh.
    Nếu image_height <= threshold_px thì giữ nguyên 1 lát [(0, image_height)].
    Nếu lớn hơn threshold_px thì cắt thành các lát cao chunk_height_px có chồng lấn overlap_px.
    """
    if image_height <= threshold_px:
        return [(0, image_height)]

    step = max(100, chunk_height_px - overlap_px)
    windows: list[tuple[int, int]] = []
    y_start = 0

    while y_start < image_height:
        y_end = min(image_height, y_start + chunk_height_px)
        windows.append((y_start, y_end))
        if y_end >= image_height:
            break
        y_start += step

    return windows


def compute_iou_and_containment(box_a: list[int], box_b: list[int]) -> tuple[float, float]:
    """Trả về (IoU, max_containment_ratio) giữa 2 bbox [x1, y1, x2, y2]."""
    x_left = max(box_a[0], box_b[0])
    y_top = max(box_a[1], box_b[1])
    x_right = min(box_a[2], box_b[2])
    y_bottom = min(box_a[3], box_b[3])

    if x_right <= x_left or y_bottom <= y_top:
        return 0.0, 0.0

    inter_area = float((x_right - x_left) * (y_bottom - y_top))
    area_a = float(max(1, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])))
    area_b = float(max(1, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])))
    union_area = area_a + area_b - inter_area

    iou = inter_area / union_area if union_area > 0 else 0.0
    max_containment = inter_area / min(area_a, area_b)
    return iou, max_containment


def deduplicate_overlapping_lines(lines: list[ShiftedLine]) -> list[ShiftedLine]:
    """
    Khử trùng lặp các khung chữ nằm ở vùng chồng lấn giữa các lát cắt bằng bbox tổng hợp.
    Nếu hai khung chồng lấp mạnh (IoU >= 0.30 hoặc containment >= 0.55), hợp nhất thành một
    khung với bbox bao ngoài và chọn text của khung đầy đủ hơn (nhiều ký tự hơn hoặc diện tích lớn hơn).
    """
    if not lines:
        return []

    kept: list[ShiftedLine] = []
    for cand in lines:
        merged = False
        for idx, existing in enumerate(kept):
            iou, containment = compute_iou_and_containment(cand.bbox, existing.bbox)
            same_or_sub_text = (
                cand.text == existing.text
                or cand.text in existing.text
                or existing.text in cand.text
            )
            is_duplicate = (
                iou >= 0.30
                or containment >= 0.55
                or (containment >= 0.30 and same_or_sub_text)
            )
            if is_duplicate:
                union_bbox = [
                    min(existing.bbox[0], cand.bbox[0]),
                    min(existing.bbox[1], cand.bbox[1]),
                    max(existing.bbox[2], cand.bbox[2]),
                    max(existing.bbox[3], cand.bbox[3]),
                ]
                # Ưu tiên giữ text dài hơn (không bị cắt cụt ở mép lát cắt), nếu bằng nhau thì chọn diện tích/score lớn hơn
                if len(cand.text.strip()) > len(existing.text.strip()):
                    best_text = cand.text
                elif len(cand.text.strip()) < len(existing.text.strip()):
                    best_text = existing.text
                else:
                    best_text = cand.text if cand.area > existing.area else existing.text

                kept[idx] = ShiftedLine(
                    bbox=union_bbox,
                    text=best_text,
                    score=max(existing.score, cand.score),
                    slice_index=existing.slice_index,
                )
                merged = True
                break
        if not merged:
            kept.append(cand)

    return kept


def is_edge_watermark(
    line: ShiftedLine,
    image_width: int,
    image_height: int,
    edge_margin_px: int = settings.WATERMARK_EDGE_MARGIN_PX,
) -> bool:
    """
    Kiểm tra dòng chữ có phải watermark nằm sát mép ảnh (ví dụ: baozimh.com, DIVI5.com, 腾讯动漫) hay không.
    """
    dist_top = max(0, line.bbox[1])
    dist_bottom = max(0, image_height - line.bbox[3])
    dist_left = max(0, line.bbox[0])
    dist_right = max(0, image_width - line.bbox[2])
    near_edge = min(dist_top, dist_bottom, dist_left, dist_right) <= edge_margin_px
    if not near_edge:
        return False
    return bool(WATERMARK_PATTERNS.search(line.text))


def filter_tiny_and_watermark_lines(
    lines: list[ShiftedLine],
    image_width: int,
    image_height: int,
    min_w: int = settings.MIN_BOX_WIDTH_PX,
    min_h: int = settings.MIN_BOX_HEIGHT_PX,
    min_area: int = settings.MIN_BOX_AREA_PX,
) -> list[ShiftedLine]:
    """
    Loại bỏ các khung quá nhỏ vô nghĩa và watermark sát mép ảnh.
    TUYỆT ĐỐI KHÔNG lọc bỏ dòng theo ngưỡng điểm tin cậy (score).
    """
    filtered: list[ShiftedLine] = []
    for ln in lines:
        if ln.width < min_w or ln.height < min_h or ln.area < min_area:
            continue
        if is_edge_watermark(ln, image_width=image_width, image_height=image_height):
            continue
        filtered.append(ln)
    return filtered


def filter_japanese_furigana(lines: list[ShiftedLine]) -> list[ShiftedLine]:
    """
    Với tiếng Nhật (ja): lọc bỏ các dòng furigana (dòng chữ dọc hẹp bất thường nằm cạnh cột chữ chính)
    trước khi gom dòng thành khối để furigana không bị ghép lẫn vào câu thoại.
    """
    if len(lines) <= 1:
        return list(lines)

    vertical_widths = [
        ln.width for ln in lines if ln.height > ln.width * 1.15 and ln.width > 0
    ]
    median_v_width = float(statistics.median(vertical_widths)) if vertical_widths else 0.0

    kept: list[ShiftedLine] = []
    for i, cand in enumerate(lines):
        is_vertical = cand.height > cand.width * 1.1
        if not is_vertical:
            kept.append(cand)
            continue

        is_furigana = False
        for j, other in enumerate(lines):
            if i == j:
                continue
            other_is_vertical = other.height > other.width * 1.15
            if not other_is_vertical:
                continue

            # Kiểm tra chồng lấp theo chiều dọc (cùng cột/bên cạnh cột chính)
            y_overlap = max(0, min(cand.bbox[3], other.bbox[3]) - max(cand.bbox[1], other.bbox[1]))
            if y_overlap < 0.30 * min(cand.height, other.height):
                continue

            # Khoảng cách ngang từ tâm hoặc mép giữa cand và other phải rất gần
            x_gap = max(0, max(cand.bbox[0] - other.bbox[2], other.bbox[0] - cand.bbox[2]))
            # Furigana hẹp hơn hẳn cột kanji chính (nhỏ hơn 62% bề rộng cột chính) và nằm sát bên
            if cand.width <= 0.62 * other.width and x_gap <= other.width * 1.2:
                is_furigana = True
                break

        if not is_furigana and median_v_width > 0 and len(vertical_widths) >= 3:
            if cand.width < 0.50 * median_v_width:
                is_furigana = True

        if not is_furigana:
            kept.append(cand)

    return kept


def _are_lines_in_same_bubble(a: ShiftedLine, b: ShiftedLine) -> bool:
    """
    Kiểm tra hai dòng có thuộc cùng một khối bong bóng thoại hay không dựa trên khoảng cách hình học.
    Hỗ trợ cả cụm dòng ngang xếp dọc và cụm cột dọc xếp cạnh nhau.
    """
    gap_x = max(0.0, max(a.bbox[0] - b.bbox[2], b.bbox[0] - a.bbox[2]))
    gap_y = max(0.0, max(a.bbox[1] - b.bbox[3], b.bbox[1] - a.bbox[3]))

    overlap_x = max(0.0, min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]))
    overlap_y = max(0.0, min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1]))

    a_vert = a.height > a.width * 1.25
    b_vert = b.height > b.width * 1.25

    if a_vert and b_vert:
        # Hai cột chữ dọc: chiều rộng cột đại diện cho cỡ chữ (font size)
        col_w = max(a.width, b.width, 1.0)
        min_w = max(1.0, min(a.width, b.width))
        if col_w / min_w > 2.5:
            return False

        # Khoảng cách ngang giữa hai cột trong cùng bong bóng (rất sát nhau)
        if gap_x > col_w * 1.35 or gap_x > 38.0:
            return False

        # Hai cột cạnh nhau trong cùng bong bóng bắt buộc phải có vùng phủ theo trục dọc Y
        # và không có khoảng cách dọc (không thể cột nọ nằm hẳn phía trên cột kia qua khung tranh)
        min_h = max(1.0, min(a.height, b.height))
        if gap_y > 10.0 or (overlap_y / min_h < 0.20):
            return False

        return True

    if not a_vert and not b_vert:
        # Hai dòng chữ ngang: chiều cao dòng đại diện cho cỡ chữ (font size)
        line_h = max(a.height, b.height, 1.0)
        min_h = max(1.0, min(a.height, b.height))
        if line_h / min_h > 2.5:
            return False

        # Khoảng cách dọc giữa hai dòng trong cùng bong bóng
        if gap_y > line_h * 1.5 or gap_y > 85.0:
            return False

        # Kiểm tra căn lề / chồng lấn ngang: hai dòng có độ phủ X hoặc chung lề trái/phải
        min_w = max(1.0, min(a.width, b.width))
        x_aligned = (
            (overlap_x / min_w >= 0.15)
            or (abs(a.bbox[0] - b.bbox[0]) <= line_h * 2.5)
            or (abs(a.bbox[2] - b.bbox[2]) <= line_h * 2.5)
        )
        return x_aligned and gap_x <= line_h * 1.5

    # Một dòng có bbox gần vuông (ví dụ dòng 1-2 ký tự cuối câu) nằm cạnh dòng dài
    char_scale = max(1.0, min(min(a.width, a.height), min(b.width, b.height)))
    return gap_x <= char_scale * 1.6 and gap_y <= char_scale * 1.4


def _meaningful_char_count(text: str) -> int:
    """Đếm số ký tự chữ/số/chữ Hán-Nhật-Hàn (bỏ khoảng trắng và dấu câu rời rạc)."""
    cleaned = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return len(cleaned)


def _is_block_vertical(component: list[ShiftedLine], lang: str) -> bool:
    """
    Xác định hướng đọc bên trong một khối theo đa số dòng có nhiều hơn 1 ký tự
    (tránh bị nhiễu bởi dòng ngắn 1 ký tự có bbox gần vuông).
    """
    multi_char_lines = [ln for ln in component if _meaningful_char_count(ln.text) >= 2]
    sample = multi_char_lines if multi_char_lines else component
    vert_votes = sum(1 for ln in sample if ln.height > ln.width * 1.2)
    if lang.lower() in ("ja", "japan") and vert_votes >= len(sample) / 2:
        return True
    return vert_votes > len(sample) / 2


def sort_blocks_reading_order(blocks: list[TextBlock], lang: str) -> list[TextBlock]:
    """
    Sắp xếp thứ tự đọc các khối trên trang theo ngôn ngữ:
    - zh / ko / en: từ trên xuống dưới, trong cùng hàng ngang thì từ trái sang phải.
    - ja: từ trên xuống dưới theo từng hàng truyện, trong cùng hàng thì từ phải sang trái.
    """
    if not blocks:
        return []

    # Sắp sơ bộ theo y1 tăng dần để gom thành các dải hàng ngang (bands)
    prelim = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    bands: list[list[TextBlock]] = []

    for blk in prelim:
        placed = False
        blk_h = max(1, blk.bbox[3] - blk.bbox[1])
        blk_cy = (blk.bbox[1] + blk.bbox[3]) / 2.0

        for band in bands:
            ref = band[0]
            ref_h = max(1, ref.bbox[3] - ref.bbox[1])
            ref_cy = (ref.bbox[1] + ref.bbox[3]) / 2.0
            y_overlap = max(0, min(blk.bbox[3], ref.bbox[3]) - max(blk.bbox[1], ref.bbox[1]))
            if y_overlap >= 0.35 * min(blk_h, ref_h) or abs(blk_cy - ref_cy) <= 0.45 * min(blk_h, ref_h):
                band.append(blk)
                placed = True
                break
        if not placed:
            bands.append([blk])

    is_rtl_page = lang.lower() in ("ja", "japan")
    ordered: list[TextBlock] = []
    next_id = 1
    for band in bands:
        if is_rtl_page:
            # Tiếng Nhật: phải sang trái (-center_x)
            band.sort(key=lambda b: -((b.bbox[0] + b.bbox[2]) / 2.0))
        else:
            # zh / ko / en: trái sang phải (+center_x)
            band.sort(key=lambda b: (b.bbox[0] + b.bbox[2]) / 2.0)

        for blk in band:
            blk.id = next_id
            ordered.append(blk)
            next_id += 1

    return ordered


def group_lines_into_blocks(
    lines: list[ShiftedLine],
    lang: str,
    image_height: int,
    low_confidence_threshold: float = settings.LOW_CONFIDENCE_THRESHOLD,
) -> list[TextBlock]:
    """
    Gom các dòng chữ gần nhau thành khối bong bóng thoại, sắp xếp thứ tự dòng trong khối,
    loại bỏ khối ký tự đơn lẻ vô nghĩa, và gắn cờ nghi ngờ (flags) mà KHÔNG xóa dòng điểm thấp.
    """
    n = len(lines)
    if n == 0:
        return []

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

    for i in range(n):
        for j in range(i + 1, n):
            if _are_lines_in_same_bubble(lines[i], lines[j]):
                union(i, j)

    clusters: dict[int, list[ShiftedLine]] = {}
    for idx, ln in enumerate(lines):
        root = find(idx)
        clusters.setdefault(root, []).append(ln)

    blocks: list[TextBlock] = []
    is_cjk = lang.lower() in ("zh", "ch", "ja", "japan")

    for comp in clusters.values():
        vertical_block = _is_block_vertical(comp, lang=lang)
        if vertical_block:
            # Chữ dọc (ja hoặc zh cột dọc): sắp các cột từ PHẢI sang TRÁI, nếu cùng cột thì từ trên xuống.
            # Dùng avg_col_w đồng nhất cho toàn khối để tránh sai lệch bucket giữa các cột.
            avg_col_w = max(1.0, statistics.mean(ln.width for ln in comp))
            comp.sort(key=lambda ln: (-round(ln.center_x / (avg_col_w * 0.7)), ln.bbox[1]))
        else:
            # Chữ ngang (en, ko, zh ngang): sắp từ TRÊN xuống DƯỚI, trái sang phải
            avg_line_h = max(1.0, statistics.mean(ln.height for ln in comp))
            comp.sort(key=lambda ln: (round(ln.center_y / (avg_line_h * 0.7)), ln.bbox[0]))

        joiner = "" if is_cjk else " "
        combined_text = joiner.join(ln.text.strip() for ln in comp if ln.text.strip()).strip()

        # Loại bỏ khối chỉ có đúng 1 ký tự đơn lẻ hoặc toàn dấu câu rác
        if _meaningful_char_count(combined_text) <= 1 and len(comp) == 1:
            continue

        x1 = min(ln.bbox[0] for ln in comp)
        y1 = min(ln.bbox[1] for ln in comp)
        x2 = max(ln.bbox[2] for ln in comp)
        y2 = max(ln.bbox[3] for ln in comp)
        mean_score = float(statistics.mean(ln.score for ln in comp))

        flags: list[str] = []
        if any(ln.score < low_confidence_threshold for ln in comp):
            flags.append("low_confidence")

        # Gắn cờ nghi ngờ cụm nhiều dòng ngang nhỏ xếp chồng (ví dụ chữ khắc trên bia mộ ở Phase 0)
        if not vertical_block and len(comp) >= 5:
            avg_h = statistics.mean(ln.height for ln in comp)
            if avg_h <= 18.0:
                flags.append("stacked_small_horizontal")

        # Gắn cờ nghi ngờ banner quảng cáo nhóm dịch ở đầu trang webtoon dài
        if (y1 <= 300 and image_height >= 1800 and AD_BANNER_PATTERNS.search(combined_text)) or (
            AD_BANNER_PATTERNS.search(combined_text)
        ):
            flags.append("possible_ad_banner")

        blocks.append(
            TextBlock(
                id=0,
                bbox=[x1, y1, x2, y2],
                text=combined_text,
                score=round(mean_score, 4),
                flags=flags,
            )
        )

    return sort_blocks_reading_order(blocks, lang=lang)


def run_ocr_page_pipeline(
    image_rgb: Image.Image,
    lang: str,
    engine: OCREngine,
    slice_threshold_px: int = settings.SLICE_HEIGHT_THRESHOLD_PX,
    chunk_height_px: int = settings.SLICE_CHUNK_HEIGHT_PX,
    overlap_px: int = settings.SLICE_OVERLAP_PX,
) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    """
    Chạy trọn vẹn pipeline OCR 1 trang truyện trong RAM:
    1. Cắt lát dọc có chồng lấn nếu ảnh cao hơn slice_threshold_px (1500px).
    2. Chạy engine.detect_and_recognize trên từng lát và cộng bù tọa độ y.
    3. Khử trùng lặp ở vùng chồng lấn.
    4. Lọc khung quá nhỏ, watermark sát mép, lọc furigana (với ja).
    5. Gom dòng thành khối bong bóng thoại, lọc ký tự đơn lẻ, gắn cờ nghi ngờ (không xóa dòng điểm thấp) và sắp thứ tự đọc.
    """
    width, height = image_rgb.size
    windows = compute_slice_windows(
        image_height=height,
        threshold_px=slice_threshold_px,
        chunk_height_px=chunk_height_px,
        overlap_px=overlap_px,
    )

    t_ocr0 = time.perf_counter()
    shifted_lines: list[ShiftedLine] = []

    for slice_idx, (y_start, y_end) in enumerate(windows):
        if len(windows) == 1 and y_start == 0 and y_end == height:
            tile_img = image_rgb
        else:
            tile_img = image_rgb.crop((0, y_start, width, y_end))

        raw_lines: list[DetectedLine] = engine.detect_and_recognize(tile_img, lang=lang)
        for rl in raw_lines:
            bx1, by1, bx2, by2 = rl.bbox
            shifted_lines.append(
                ShiftedLine(
                    bbox=[bx1, by1 + y_start, bx2, by2 + y_start],
                    text=rl.text,
                    score=rl.score,
                    slice_index=slice_idx,
                )
            )

    ocr_Only_ms = round((time.perf_counter() - t_ocr0) * 1000.0, 2)

    t_post0 = time.perf_counter()
    deduped = deduplicate_overlapping_lines(shifted_lines) if len(windows) > 1 else shifted_lines
    cleaned = filter_tiny_and_watermark_lines(deduped, image_width=width, image_height=height)
    if lang.lower() in ("ja", "japan"):
        cleaned = filter_japanese_furigana(cleaned)

    blocks = group_lines_into_blocks(cleaned, lang=lang, image_height=height)
    postprocess_ms = round((time.perf_counter() - t_post0) * 1000.0, 2)

    stats = {
        "slice_count": len(windows),
        "raw_line_count": len(shifted_lines),
        "deduped_line_count": len(deduped),
        "block_count": len(blocks),
        "ocr_engine_ms": ocr_Only_ms,
        "postprocess_ms": postprocess_ms,
    }
    return [b.to_dict() for b in blocks], stats
