from __future__ import annotations

from typing import Any


def extract_bbox(block: dict[str, Any]) -> tuple[float, float, float, float]:
    """
    Chuẩn hóa bounding box về dạng (x1, y1, x2, y2).
    Hỗ trợ cả 'bbox': [x1, y1, x2, y2] lẫn các trường x, y, width, height.
    """
    bbox = block.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    x1 = float(block.get("x") or block.get("left") or block.get("x_min") or 0.0)
    y1 = float(block.get("y") or block.get("top") or block.get("y_min") or 0.0)
    w = float(block.get("w") or block.get("width") or 50.0)
    h = float(block.get("h") or block.get("height") or 30.0)
    x2 = float(block.get("right") or block.get("x_max") or (x1 + w))
    y2 = float(block.get("bottom") or block.get("y_max") or (y1 + h))
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


class TextRowCluster:
    def __init__(self, first_block: dict[str, Any], first_bbox: tuple[float, float, float, float]):
        self.blocks: list[dict[str, Any]] = [first_block]
        self.bboxes: list[tuple[float, float, float, float]] = [first_bbox]
        # Anchor cố định là y1, y2 của khối đầu tiên (không mở rộng khi add khối mới)
        self.anchor_y1 = first_bbox[1]
        self.anchor_y2 = first_bbox[3]

    def vertical_iou(self, bbox: tuple[float, float, float, float]) -> float:
        """
        Tính chỉ số IoU theo chiều dọc giữa bbox và anchor cố định của cụm.
        """
        y1, y2 = bbox[1], bbox[3]
        inter = max(0.0, min(self.anchor_y2, y2) - max(self.anchor_y1, y1))
        union = max(self.anchor_y2, y2) - min(self.anchor_y1, y1)
        if union <= 0.0:
            return 0.0
        return inter / union

    def matches(self, bbox: tuple[float, float, float, float], threshold: float) -> bool:
        return self.vertical_iou(bbox) >= threshold

    def add(self, block: dict[str, Any], bbox: tuple[float, float, float, float]) -> None:
        self.blocks.append(block)
        self.bboxes.append(bbox)
        # Chú ý: Giữ nguyên anchor_y1, anchor_y2 cố định


def sort_blocks_by_reading_order(
    blocks: list[dict[str, Any]],
    reading_direction: str = "rtl",
) -> list[dict[str, Any]]:
    """
    Sắp xếp các khối văn bản (text blocks) theo thứ tự đọc tự nhiên của truyện tranh:
    - Thuật toán Vertical Overlap Clustering với anchor cố định: gom các bóng thoại cùng hàng ngang.
    - Sắp xếp các hàng từ Trên xuống Dưới (anchor_y1 tăng dần).
    - Trong từng hàng:
        + Nếu reading_direction == "rtl" (Manga Nhật): sắp xếp Phải -> Trái (x_min giảm dần).
        + Nếu reading_direction == "ltr" (Manhwa Hàn / Webtoon): sắp xếp Trái -> Phải (x_min tăng dần).
    - Giữ nguyên 100% tất cả các trường dữ liệu gốc (id, bbox, text, v.v.).
    """
    if not blocks:
        return []
    if len(blocks) == 1:
        return list(blocks)

    direction = (reading_direction or "rtl").strip().lower()
    is_rtl = direction != "ltr"
    threshold = 0.3 if is_rtl else 0.5

    # Sắp xếp thô ban đầu theo chiều dọc từ trên xuống dưới
    indexed_blocks = [(b, extract_bbox(b)) for b in blocks]
    indexed_blocks.sort(key=lambda item: item[1][1])

    clusters: list[TextRowCluster] = []

    for block, bbox in indexed_blocks:
        best_cluster: TextRowCluster | None = None
        best_iou = -1.0

        for cluster in clusters:
            iou = cluster.vertical_iou(bbox)
            if iou >= threshold:
                if iou > best_iou:
                    best_iou = iou
                    best_cluster = cluster

        if best_cluster is not None:
            best_cluster.add(block, bbox)
        else:
            clusters.append(TextRowCluster(block, bbox))

    # Sắp xếp các cụm dòng từ Trên xuống Dưới theo anchor
    clusters.sort(key=lambda c: (c.anchor_y1, c.anchor_y2))

    # Trong từng cụm dòng, sắp xếp theo x_min
    result: list[dict[str, Any]] = []
    for cluster in clusters:
        cluster.blocks.sort(
            key=lambda b: extract_bbox(b)[0],
            reverse=is_rtl,  # True: Phải -> Trái (RTL); False: Trái -> Phải (LTR)
        )
        result.extend(cluster.blocks)

    return result
