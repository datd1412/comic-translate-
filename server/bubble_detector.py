from __future__ import annotations

import logging
import os
from typing import Any
import numpy as np
import onnxruntime as ort
from PIL import Image

logger = logging.getLogger("comic_translate.bubble_detector")

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "detection", "detector-v4-s_int8.onnx"
)


def _rect_of(box: list[float]) -> dict[str, float]:
    return {
        "x": min(box[0], box[2]),
        "y": min(box[1], box[3]),
        "w": max(0.0, abs(box[2] - box[0])),
        "h": max(0.0, abs(box[3] - box[1])),
    }


def _area(r: dict[str, float]) -> float:
    return r["w"] * r["h"]


def containment_nms(boxes: list[list[float]], threshold: float = 0.85) -> list[list[float]]:
    """
    Non-Maximum Suppression dựa trên tỉ lệ lồng nhau (Containment):
    Nếu diện tích box con bị phủ > threshold bởi box khác thì loại bỏ box con.
    """
    sorted_boxes = sorted(boxes, key=lambda b: b[4] if len(b) > 4 else 0.0, reverse=True)
    keep: list[list[float]] = []

    for box in sorted_boxes:
        bx1, by1, bx2, by2 = box[:4]
        b_area = max(1.0, (bx2 - bx1) * (by2 - by1))
        suppressed = False

        for k in keep:
            kx1, ky1, kx2, ky2 = k[:4]
            ix1 = max(bx1, kx1)
            iy1 = max(by1, ky1)
            ix2 = min(bx2, kx2)
            iy2 = min(by2, ky2)

            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2 - ix1) * (iy2 - iy1)
                if inter / b_area > threshold:
                    suppressed = True
                    break

        if not suppressed:
            keep.append(box)

    return keep


def filter_speckle(
    boxes: list[list[float]],
    page_h: float,
    min_conf_threshold: float = 0.70,
    min_median_ratio: float = 0.15,
) -> list[list[float]]:
    """
    Bộ lọc diện tích trung vị (Median Area Filter theo chuẩn Libre Manga):
    Loại bỏ đốm mực nhỏ, rác họa tiết hoặc chữ in trên áo có diện tích < 15% diện tích trung vị.
    """
    if not boxes:
        return []

    areas = sorted([_area(_rect_of(b)) for b in boxes])
    median_a = areas[len(areas) // 2] if areas else 0.0

    kept: list[list[float]] = []
    for b in boxes:
        r = _rect_of(b)
        a = _area(r)
        conf = b[4] if len(b) > 4 else 1.0

        # Lọc speckle: quá nhỏ so với trung vị và độ tin cậy thấp
        if median_a > 0.0 and a < (min_median_ratio * median_a) and conf < min_conf_threshold:
            continue

        # Lọc box dị dạng chiếm quá 90% toàn trang
        if r["h"] > 0.95 * page_h:
            continue

        kept.append(b)

    return kept


class BubbleDetector:
    """
    Bộ phát hiện bong bóng thoại Manga/Comic sử dụng RT-DETR-v2 INT8 ONNX (11 MB).
    Hoạt động 100% trên CPU với thời gian suy luận ~150ms.
    """

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        self.model_path = model_path
        self.session: ort.InferenceSession | None = None
        self._load_session()

    def _load_session(self) -> None:
        if not os.path.exists(self.model_path):
            logger.warning("Không tìm thấy model detector tại %s", self.model_path)
            return

        so = ort.SessionOptions()
        so.log_severity_level = 3
        so.intra_op_num_threads = 4
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=so,
            providers=["CPUExecutionProvider"],
        )
        logger.info("Đã khởi tạo RT-DETR INT8 Bubble Detector thành công từ %s", self.model_path)

    def detect(
        self,
        image: Image.Image,
        min_confidence: float = 0.35,
        reading_direction: str = "rtl",
    ) -> list[dict[str, Any]]:
        """
        Nhận diện các bong bóng thoại trong ảnh và trả về danh sách box theo thứ tự đọc:
        [{"id": 0, "bbox": [x1, y1, x2, y2], "confidence": 0.95}, ...]
        """
        if self.session is None:
            self._load_session()
            if self.session is None:
                return []

        w, h = image.size

        # Preprocessing: Resize về 640x640 và chuẩn hóa float32 [0..1]
        im_resized = image.resize((640, 640), Image.Resampling.BILINEAR)
        arr = np.asarray(im_resized, dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))  # (3, 640, 640)
        im_data = arr[np.newaxis, ...]  # (1, 3, 640, 640)
        orig_size = np.array([[w, h]], dtype=np.int64)

        try:
            outputs = self.session.run(None, {"images": im_data, "orig_target_sizes": orig_size})
            labels, boxes, scores = outputs[0][0], outputs[1][0], outputs[2][0]
        except Exception as exc:
            logger.error("Lỗi khi suy luận Bubble Detector: %s", exc)
            return []

        bubble_boxes: list[list[float]] = []
        text_boxes: list[list[float]] = []

        for lab, box, scr in zip(labels, boxes, scores):
            score_val = float(scr)
            if score_val < min_confidence:
                continue

            # Giới hạn tọa độ trong kích thước ảnh gốc
            x1 = max(0.0, min(float(w), float(box[0])))
            y1 = max(0.0, min(float(h), float(box[1])))
            x2 = max(0.0, min(float(w), float(box[2])))
            y2 = max(0.0, min(float(h), float(box[3])))

            if (x2 - x1) < 8.0 or (y2 - y1) < 8.0:
                continue

            item = [x1, y1, x2, y2, score_val]
            label_id = int(lab)
            if label_id == 0:
                bubble_boxes.append(item)
            elif label_id in [1, 2]:
                text_boxes.append(item)

        # Hợp nhất thông minh bubble_boxes (label 0) và text_boxes (label 1, 2):
        # - Ưu tiên bubble_boxes vì bao quát trọn vùng trắng cần đè chữ.
        # - Giữ thêm các text_boxes (khung dẫn chuyện vuông, chữ ngoài bóng) nếu chúng KHÔNG nằm chồng lấn bên trong bubble_boxes.
        if bubble_boxes:
            target_boxes = list(bubble_boxes)
            for tb in text_boxes:
                if tb[4] < max(min_confidence, 0.45):
                    continue
                tx1, ty1, tx2, ty2 = tb[:4]
                t_area = max(1.0, (tx2 - tx1) * (ty2 - ty1))
                covered = False
                for bb in bubble_boxes:
                    bx1, by1, bx2, by2 = bb[:4]
                    ix1, iy1 = max(tx1, bx1), max(ty1, by1)
                    ix2, iy2 = min(tx2, bx2), min(ty2, by2)
                    if ix2 > ix1 and iy2 > iy1:
                        inter = (ix2 - ix1) * (iy2 - iy1)
                        if inter / t_area >= 0.30:
                            covered = True
                            break
                if not covered:
                    target_boxes.append(tb)
        else:
            target_boxes = text_boxes

        if not target_boxes:
            return []

        # Áp dụng NMS Containment và lọc nhiễu Speckle
        nms_boxes = containment_nms(target_boxes, threshold=0.85)
        filtered_boxes = filter_speckle(nms_boxes, page_h=h)

        # Sắp xếp theo thứ tự đọc chuẩn bằng thuật toán Vertical Overlap Clustering (reading_order.py)
        prelim_results: list[dict[str, Any]] = []
        for idx, b in enumerate(filtered_boxes):
            prelim_results.append({
                "id": idx,
                "bbox": [int(round(b[0])), int(round(b[1])), int(round(b[2])), int(round(b[3]))],
                "confidence": round(b[4], 3),
            })

        try:
            from reading_order import sort_blocks_by_reading_order
            sorted_results = sort_blocks_by_reading_order(
                prelim_results, reading_direction=reading_direction
            )
        except Exception:
            is_rtl = reading_direction.strip().lower() == "rtl"
            sorted_results = sorted(
                prelim_results,
                key=lambda item: (item["bbox"][1], -item["bbox"][0] if is_rtl else item["bbox"][0]),
            )

        results: list[dict[str, Any]] = []
        for idx, item in enumerate(sorted_results):
            item["id"] = idx
            results.append(item)

        return results


# Singleton instance để tái sử dụng session
_detector_instance: BubbleDetector | None = None


def get_bubble_detector() -> BubbleDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = BubbleDetector()
    return _detector_instance

