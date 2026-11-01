from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import inspect
import logging
import os
import threading
from typing import Any

# Tắt MKL-DNN / OneDNN mặc định trước khi import paddle để tránh kẹt ở ReduceMeanCheckIfOneDNNSupport trên CPU Windows
os.environ.setdefault("FLAGS_use_mkldnn", "0")

import numpy as np
from PIL import Image

from config import settings

logger = logging.getLogger("ocr_service.engine")

LANG_MAP: dict[str, str] = {
    "zh": "ch",
    "ch": "ch",
    "en": "en",
    "ko": "korean",
    "korean": "korean",
    "ja": "japan",
    "japan": "japan",
}


@dataclass
class DetectedLine:
    bbox: list[int]  # [x1, y1, x2, y2]
    text: str
    score: float


def polygon_to_bbox(polygon: Any) -> list[int]:
    """Chuyển polygon 4 điểm hoặc bbox [x1, y1, x2, y2] về [x1, y1, x2, y2] nguyên."""
    if hasattr(polygon, "tolist"):
        polygon = polygon.tolist()
    if not polygon:
        return [0, 0, 0, 0]
    if isinstance(polygon[0], (int, float)) and len(polygon) == 4:
        return [
            int(round(float(polygon[0]))),
            int(round(float(polygon[1]))),
            int(round(float(polygon[2]))),
            int(round(float(polygon[3]))),
        ]
    xs = [float(pt[0]) for pt in polygon]
    ys = [float(pt[1]) for pt in polygon]
    return [
        int(round(min(xs))),
        int(round(min(ys))),
        int(round(max(xs))),
        int(round(max(ys))),
    ]


def parse_raw_paddle_output(raw_result: Any) -> list[DetectedLine]:
    """Chuẩn hóa kết quả từ cả PaddleOCR 3.x (PP-OCRv5/PaddleX) và PaddleOCR 2.x về danh sách DetectedLine."""
    lines: list[DetectedLine] = []
    if not raw_result:
        return lines

    first_elem = (
        raw_result[0]
        if isinstance(raw_result, list) and len(raw_result) > 0
        else raw_result
    )
    is_v3_dict_like = (
        isinstance(first_elem, dict)
        or (hasattr(first_elem, "keys") and "rec_texts" in first_elem)
        or (isinstance(first_elem, dict) and "res" in first_elem)
    )

    if is_v3_dict_like:
        pages = raw_result if isinstance(raw_result, list) else [raw_result]
        for page in pages:
            payload = page.get("res", page) if isinstance(page, dict) else page
            rec_texts = payload["rec_texts"] if "rec_texts" in payload else []
            rec_scores = payload["rec_scores"] if "rec_scores" in payload else []
            polys = (
                payload["rec_polys"]
                if "rec_polys" in payload
                else (
                    payload["dt_polys"]
                    if "dt_polys" in payload
                    else (payload["rec_boxes"] if "rec_boxes" in payload else [])
                )
            )
            for i, text in enumerate(rec_texts):
                text_str = str(text).strip()
                if not text_str:
                    continue
                score_val = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                raw_poly = polys[i] if i < len(polys) else []
                bbox = polygon_to_bbox(raw_poly)
                lines.append(
                    DetectedLine(
                        bbox=bbox,
                        text=text_str,
                        score=round(score_val, 4),
                    )
                )
        return lines

    # Định dạng PaddleOCR 2.x
    page_items = raw_result
    if (
        isinstance(raw_result, list)
        and len(raw_result) > 0
        and isinstance(raw_result[0], list)
        and (
            len(raw_result[0]) == 0
            or (
                isinstance(raw_result[0][0], (list, tuple))
                and len(raw_result[0][0]) == 2
                and isinstance(raw_result[0][0][1], (list, tuple))
            )
        )
    ):
        page_items = raw_result[0]

    for item in page_items or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        raw_poly, text_score = item[0], item[1]
        if not isinstance(text_score, (list, tuple)) or len(text_score) < 2:
            continue
        text_str = str(text_score[0]).strip()
        if not text_str:
            continue
        score_val = float(text_score[1])
        bbox = polygon_to_bbox(raw_poly)
        lines.append(
            DetectedLine(
                bbox=bbox,
                text=text_str,
                score=round(score_val, 4),
            )
        )
    return lines


class OCREngine(ABC):
    """Interface trừu tượng cho OCR Engine để tách biệt hoàn toàn logic pipeline với model PaddleOCR."""

    @abstractmethod
    def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
        """Nhận ảnh PIL RGB trong RAM và mã ngôn ngữ (zh|en|ko|ja), trả về các dòng chữ phát hiện được."""
        raise NotImplementedError


class PaddleOCREngine(OCREngine):
    """
    Triển khai OCREngine bằng PaddleOCR 3.7.0 với cấu hình tối ưu cho CPU:
    - Model Mobile: PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec (tự fallback theo ngôn ngữ nếu cần)
    - Tắt toàn bộ bước phụ: use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False
    - Chạy hoàn toàn trên mảng NumPy trong RAM, không ghi file tạm ra đĩa.
    """

    def __init__(
        self,
        det_model_name: str = settings.DET_MODEL_NAME,
        rec_model_name: str = settings.REC_MODEL_NAME,
        cpu_threads: int = settings.CPU_THREADS,
        preload_langs: tuple[str, ...] = ("zh", "en"),
    ) -> None:
        self.det_model_name = det_model_name
        self.rec_model_name = rec_model_name
        self.cpu_threads = cpu_threads
        self._instances: dict[str, Any] = {}
        self._lock = threading.Lock()

        for lg in preload_langs:
            self._get_or_create_instance(lg)

    def _get_or_create_instance(self, lang: str) -> Any:
        paddle_lang = LANG_MAP.get(lang.lower(), lang.lower())
        with self._lock:
            # Với zh và en, PP-OCRv5_mobile_rec hỗ trợ chung nên có thể dùng chung 1 instance
            cache_key = "mobile_v5_shared" if paddle_lang in ("ch", "en") else f"lang_{paddle_lang}"
            if cache_key in self._instances:
                return self._instances[cache_key]

            from paddleocr import PaddleOCR  # type: ignore

            init_sig = inspect.signature(PaddleOCR.__init__)
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in init_sig.parameters.values()
            )

            def _can_pass(name: str) -> bool:
                return accepts_var_kw or (name in init_sig.parameters)

            base_kwargs: dict[str, Any] = {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "enable_mkldnn": False,
                "cpu_threads": self.cpu_threads,
                "device": "cpu",
            }

            instance = None
            # Ưu tiên nạp trực tiếp PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec cho zh/en
            if paddle_lang in ("ch", "en"):
                try_kw = dict(base_kwargs)
                if _can_pass("text_detection_model_name"):
                    try_kw["text_detection_model_name"] = self.det_model_name
                if _can_pass("text_recognition_model_name"):
                    try_kw["text_recognition_model_name"] = self.rec_model_name
                try:
                    instance = PaddleOCR(**try_kw)
                    logger.info(
                        "Loaded PaddleOCR mobile engine (%s + %s) for cache_key=%s",
                        self.det_model_name,
                        self.rec_model_name,
                        cache_key,
                    )
                except Exception as exc:
                    logger.warning(
                        "Direct mobile model init failed (%s), falling back to lang=%s",
                        exc,
                        paddle_lang,
                    )

            if instance is None:
                fallback_kw = dict(base_kwargs)
                if _can_pass("text_detection_model_name"):
                    fallback_kw["text_detection_model_name"] = self.det_model_name
                fallback_kw["lang"] = paddle_lang
                instance = PaddleOCR(**fallback_kw)
                logger.info("Loaded PaddleOCR engine with lang=%s", paddle_lang)

            self._instances[cache_key] = instance
            return instance

    def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
        ocr_inst = self._get_or_create_instance(lang)
        rgb_arr = np.array(image_rgb.convert("RGB"))
        bgr_arr = rgb_arr[:, :, ::-1]

        if hasattr(ocr_inst, "predict"):
            raw_out = list(ocr_inst.predict(bgr_arr))
        else:
            ocr_sig = inspect.signature(ocr_inst.ocr)
            if "cls" in ocr_sig.parameters:
                raw_out = ocr_inst.ocr(bgr_arr, cls=False)
            else:
                raw_out = ocr_inst.ocr(bgr_arr)

        return parse_raw_paddle_output(raw_out)
