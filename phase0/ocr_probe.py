from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image

LANG_MAP: dict[str, str] = {
    "zh": "ch",
    "ch": "ch",
    "en": "en",
    "ko": "korean",
    "korean": "korean",
    "ja": "japan",
    "japan": "japan",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
TALL_IMAGE_THRESHOLD_PX = 1500
ORIENTATION_RATIO_NOTE = "Chỉ để thống kê theo tỉ lệ cao/rộng của bbox, chưa kiểm chứng"


def polygon_to_bbox(polygon: list[list[float]] | list[float]) -> list[int]:
    """Chuyển polygon 4 điểm [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] hoặc bbox [x1,y1,x2,y2] về [x1,y1,x2,y2]."""
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


def compute_line_geometry_metrics(
    bbox: list[int],
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """
    Chỉ đo đạc hình học của từng khối (KHÔNG lọc bỏ khối nào):
    - Tỉ lệ cao/rộng của bbox và nhãn ngang/dọc theo tỉ lệ đó (chỉ để thống kê, chưa kiểm chứng).
    - Khoảng cách từ khối tới mép ảnh gần nhất (px).
    """
    x1, y1, x2, y2 = bbox
    box_w = max(1, x2 - x1)
    box_h = max(0, y2 - y1)
    aspect_ratio_h_over_w = round(box_h / box_w, 4)

    # Nhãn ngang/dọc chỉ dựa trên tỉ lệ cao/rộng để thống kê (chưa kiểm chứng)
    orientation_label = "dọc" if aspect_ratio_h_over_w > 1.0 else "ngang"

    dist_left = max(0, x1)
    dist_top = max(0, y1)
    dist_right = max(0, image_width - x2)
    dist_bottom = max(0, image_height - y2)
    nearest_edge_distance_px = int(min(dist_left, dist_top, dist_right, dist_bottom))

    return {
        "bbox_width_px": int(x2 - x1),
        "bbox_height_px": int(box_h),
        "aspect_ratio_h_over_w": aspect_ratio_h_over_w,
        "orientation_label": orientation_label,
        "orientation_note": ORIENTATION_RATIO_NOTE,
        "nearest_edge_distance_px": nearest_edge_distance_px,
    }


def enrich_lines_with_image_geometry(
    lines: list[dict[str, Any]],
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    """Gắn thêm thông số đo đạc hình học vào từng khối mà không lọc hay thay đổi thứ tự."""
    enriched: list[dict[str, Any]] = []
    for line in lines:
        bbox = line.get("bbox", [0, 0, 0, 0])
        metrics = compute_line_geometry_metrics(bbox, image_width, image_height)
        item = dict(line)
        item.update(metrics)
        enriched.append(item)
    return enriched


def describe_raw_structure(raw_result: Any, max_depth: int = 3) -> dict[str, Any]:
    """In cấu trúc thực tế của kết quả PaddleOCR (hữu ích để xác nhận khóa của PaddleOCR 2.x vs 3.x)."""
    if max_depth <= 0:
        return {"type": type(raw_result).__name__}
    if isinstance(raw_result, dict):
        return {
            "type": "dict",
            "keys": {
                str(k): describe_raw_structure(v, max_depth - 1)
                for k, v in list(raw_result.items())[:15]
            },
        }
    if hasattr(raw_result, "keys") and callable(getattr(raw_result, "keys")):
        keys_list = list(raw_result.keys())
        return {
            "type": type(raw_result).__name__,
            "keys": {
                str(k): describe_raw_structure(raw_result[k], max_depth - 1)
                for k in keys_list[:15]
            },
        }
    if isinstance(raw_result, (list, tuple)):
        return {
            "type": type(raw_result).__name__,
            "length": len(raw_result),
            "first_item": describe_raw_structure(raw_result[0], max_depth - 1)
            if len(raw_result) > 0
            else None,
        }
    return {"type": type(raw_result).__name__, "repr_preview": repr(raw_result)[:120]}


def normalize_paddle_result(
    raw_result: Any,
    image_width: int | None = None,
    image_height: int | None = None,
) -> list[dict[str, Any]]:
    """
    Chuẩn hóa kết quả từ cả PaddleOCR 2.x lẫn PaddleOCR 3.x (PP-OCRv4/v5 pipeline)
    về danh sách đồng nhất. Nếu truyền image_width và image_height thì gắn luôn thông số đo hình học.
    """
    lines: list[dict[str, Any]] = []
    if not raw_result:
        return lines

    # Trường hợp 1: PaddleOCR 3.x trả về list các dict/OCRResult có khóa 'rec_texts', 'rec_scores', 'dt_polys'/'rec_polys'/'rec_boxes'
    first_elem = raw_result[0] if isinstance(raw_result, list) and len(raw_result) > 0 else raw_result
    is_v3_dict_like = (
        isinstance(first_elem, dict)
        or (hasattr(first_elem, "keys") and "rec_texts" in first_elem)
        or (isinstance(first_elem, dict) and "res" in first_elem)
    )

    if is_v3_dict_like:
        pages = raw_result if isinstance(raw_result, list) else [raw_result]
        idx = 1
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
                if hasattr(raw_poly, "tolist"):
                    raw_poly = raw_poly.tolist()
                bbox = polygon_to_bbox(raw_poly)
                polygon = (
                    [[int(round(float(p[0]))), int(round(float(p[1])))] for p in raw_poly]
                    if raw_poly and isinstance(raw_poly[0], (list, tuple))
                    else [
                        [bbox[0], bbox[1]],
                        [bbox[2], bbox[1]],
                        [bbox[2], bbox[3]],
                        [bbox[0], bbox[3]],
                    ]
                )
                lines.append(
                    {
                        "id": idx,
                        "bbox": bbox,
                        "polygon": polygon,
                        "text": text_str,
                        "score": round(score_val, 4),
                    }
                )
                idx += 1
        if image_width is not None and image_height is not None:
            return enrich_lines_with_image_geometry(lines, image_width, image_height)
        return lines

    # Trường hợp 2: PaddleOCR 2.x trả về [[ [ [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, score) ], ... ]]
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

    idx = 1
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
        if hasattr(raw_poly, "tolist"):
            raw_poly = raw_poly.tolist()
        bbox = polygon_to_bbox(raw_poly)
        polygon = [
            [int(round(float(pt[0]))), int(round(float(pt[1])))]
            for pt in raw_poly
        ]
        lines.append(
            {
                "id": idx,
                "bbox": bbox,
                "polygon": polygon,
                "text": text_str,
                "score": round(score_val, 4),
            }
        )
        idx += 1

    if image_width is not None and image_height is not None:
        return enrich_lines_with_image_geometry(lines, image_width, image_height)
    return lines


def compute_timing_summary(elapsed_ms_list: list[float]) -> dict[str, float | int | None]:
    """
    Tính thống kê thời gian chạy từng ảnh.
    BẮT BUỘC bỏ ảnh đầu tiên khi tính trung bình chính (mean_ms_excluding_first)
    do ảnh đầu gánh chi phí khởi tạo / warm-up của model.
    """
    count = len(elapsed_ms_list)
    if count == 0:
        return {
            "total_images": 0,
            "first_image_warmup_ms": None,
            "mean_ms_excluding_first": None,
            "median_ms_excluding_first": None,
            "min_ms_excluding_first": None,
            "max_ms_excluding_first": None,
            "all_images_mean_ms": None,
        }

    first_ms = round(float(elapsed_ms_list[0]), 2)
    all_mean = round(float(statistics.mean(elapsed_ms_list)), 2)

    if count == 1:
        return {
            "total_images": 1,
            "first_image_warmup_ms": first_ms,
            "mean_ms_excluding_first": None,
            "median_ms_excluding_first": None,
            "min_ms_excluding_first": None,
            "max_ms_excluding_first": None,
            "all_images_mean_ms": all_mean,
        }

    rest = elapsed_ms_list[1:]
    return {
        "total_images": count,
        "first_image_warmup_ms": first_ms,
        "mean_ms_excluding_first": round(float(statistics.mean(rest)), 2),
        "median_ms_excluding_first": round(float(statistics.median(rest)), 2),
        "min_ms_excluding_first": round(float(min(rest)), 2),
        "max_ms_excluding_first": round(float(max(rest)), 2),
        "all_images_mean_ms": all_mean,
    }


def create_default_paddle_runner(lang: str) -> Callable[[str], Any]:
    """Khởi tạo PaddleOCR trên CPU một lần và trả về hàm nhận đường dẫn ảnh."""
    from paddleocr import PaddleOCR  # type: ignore

    paddle_lang = LANG_MAP.get(lang.lower(), lang)
    import inspect

    init_sig = inspect.signature(PaddleOCR.__init__)
    kwargs: dict[str, Any] = {"lang": paddle_lang}
    if "use_angle_cls" in init_sig.parameters:
        kwargs["use_angle_cls"] = True
    if "use_doc_orientation_classify" in init_sig.parameters:
        kwargs["use_doc_orientation_classify"] = False
    if "use_doc_unwarping" in init_sig.parameters:
        kwargs["use_doc_unwarping"] = False
    if "use_gpu" in init_sig.parameters:
        kwargs["use_gpu"] = False
    if "show_log" in init_sig.parameters:
        kwargs["show_log"] = False

    ocr_engine = PaddleOCR(**kwargs)

    def _run(image_path: str) -> Any:
        if hasattr(ocr_engine, "predict"):
            try:
                return list(ocr_engine.predict(image_path))
            except Exception:
                pass
        ocr_sig = inspect.signature(ocr_engine.ocr)
        if "cls" in ocr_sig.parameters:
            return ocr_engine.ocr(image_path, cls=True)
        return ocr_engine.ocr(image_path)

    return _run


def probe_directory(
    input_dir: Path,
    lang: str,
    runner: Callable[[str], Any] | None = None,
    dump_raw_schema: bool = False,
) -> dict[str, Any]:
    """Chạy OCR trên toàn bộ ảnh trong thư mục, ghi nhận kết quả và các thông số đo hình học (không lọc)."""
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Thư mục ảnh không tồn tại: {input_dir}")

    image_files = sorted(
        [
            p
            for p in input_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=lambda p: p.name,
    )
    if not image_files:
        raise ValueError(f"Không tìm thấy file ảnh nào trong: {input_dir}")

    init_start = time.perf_counter()
    active_runner = runner if runner is not None else create_default_paddle_runner(lang)
    model_init_ms = round((time.perf_counter() - init_start) * 1000.0, 2)

    images_report: list[dict[str, Any]] = []
    elapsed_list: list[float] = []
    raw_schema_preview: dict[str, Any] | None = None

    for idx, img_path in enumerate(image_files):
        with Image.open(img_path) as im:
            width, height = im.size

        is_tall_image = height > TALL_IMAGE_THRESHOLD_PX
        height_label = "ảnh cao" if is_tall_image else "ảnh thường"

        t0 = time.perf_counter()
        raw_out = active_runner(str(img_path))
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        elapsed_list.append(elapsed_ms)

        if idx == 0 and dump_raw_schema:
            raw_schema_preview = describe_raw_structure(raw_out)

        lines = normalize_paddle_result(raw_out, image_width=width, image_height=height)
        images_report.append(
            {
                "image_name": img_path.name,
                "width": width,
                "height": height,
                "is_tall_image": is_tall_image,
                "height_label": height_label,
                "is_warmup_image": idx == 0,
                "elapsed_ms": elapsed_ms,
                "line_count": len(lines),
                "lines": lines,
            }
        )

    report: dict[str, Any] = {
        "lang": lang,
        "paddle_lang": LANG_MAP.get(lang.lower(), lang),
        "input_dir": str(input_dir),
        "tall_image_threshold_px": TALL_IMAGE_THRESHOLD_PX,
        "orientation_ratio_note": ORIENTATION_RATIO_NOTE,
        "model_init_ms": model_init_ms,
        "timing_summary": compute_timing_summary(elapsed_list),
        "images": images_report,
    }
    if raw_schema_preview is not None:
        report["raw_schema_preview"] = raw_schema_preview

    return report


def print_probe_console_details(report: dict[str, Any], output_path: Path, dump_raw_schema: bool) -> None:
    summary = report["timing_summary"]
    print(f"[OCR Probe] Đã lưu kết quả vào: {output_path}")
    print(f"  - Tổng số ảnh: {summary['total_images']}")
    print(f"  - Thời gian khởi tạo model: {report['model_init_ms']} ms")
    print(f"  - Thời gian ảnh đầu (warm-up): {summary['first_image_warmup_ms']} ms")
    print(
        f"  - Trung bình (đã bỏ ảnh đầu): {summary['mean_ms_excluding_first']} ms "
        f"(median: {summary['median_ms_excluding_first']} ms)"
    )
    print(f"  - Ghi chú nhãn hướng khối: {report['orientation_ratio_note']}")
    for img in report.get("images", []):
        print(
            f"\n  * Ảnh: {img['image_name']} | Kích thước: {img['width']} x {img['height']} px "
            f"| Nhãn: {img['height_label']} | Số khối: {img['line_count']} | Thời gian: {img['elapsed_ms']} ms"
        )
        for ln in img.get("lines", []):
            print(
                f"      #{ln['id']} bbox={ln['bbox']} | cao/rộng={ln['aspect_ratio_h_over_w']} "
                f"({ln['orientation_label']} - chỉ thống kê, chưa kiểm chứng) "
                f"| cách mép gần nhất={ln['nearest_edge_distance_px']} px "
                f"| score={ln['score']} | text={ln['text']}"
            )
    if dump_raw_schema and "raw_schema_preview" in report:
        print("\n  - Cấu trúc raw PaddleOCR (ảnh đầu):")
        print(json.dumps(report["raw_schema_preview"], ensure_ascii=False, indent=4))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 0: Chạy PaddleOCR (det+rec) trên toàn trang truyện để kiểm tra cổng (chỉ đo, không lọc)."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Đường dẫn thư mục chứa ảnh toàn trang (tuyệt đối, ngoài dự án)",
    )
    parser.add_argument(
        "--lang",
        required=True,
        choices=["zh", "ch", "en", "ko", "ja"],
        help="Ngôn ngữ nguồn của trang truyện (zh/ch cho baozimh.org, en cho hivetoons.org)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="File JSON xuất kết quả probe",
    )
    parser.add_argument(
        "--dump-raw-schema",
        action="store_true",
        help="In cấu trúc khóa thực tế của kết quả PaddleOCR ở ảnh đầu tiên (kiểm chứng PaddleOCR 2.x vs 3.x)",
    )
    args = parser.parse_args()

    report = probe_directory(
        input_dir=args.input_dir,
        lang=args.lang,
        dump_raw_schema=args.dump_raw_schema,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print_probe_console_details(report, args.output, args.dump_raw_schema)


if __name__ == "__main__":
    main()