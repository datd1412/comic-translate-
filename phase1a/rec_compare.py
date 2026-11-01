from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any, Callable

from PIL import Image

PHASE0_DIR = Path(__file__).resolve().parent.parent / "phase0"
import sys

if str(PHASE0_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE0_DIR))

from ocr_probe import LANG_MAP, normalize_paddle_result  # noqa: E402

DEFAULT_LOW_SCORE_THRESHOLD = 0.6


def extract_text_and_score_from_rec_output(raw_out: Any) -> tuple[str, float]:
    """
    Trích xuất (text, score) từ kết quả của TextRecognition hoặc PaddleOCR.
    Hỗ trợ cả định dạng PaddleOCR 3.x (TextRecognition trả về rec_text / rec_score hoặc rec_texts / rec_scores)
    và PaddleOCR 2.x.
    """
    if not raw_out:
        return "", 0.0

    first = raw_out[0] if isinstance(raw_out, list) and len(raw_out) > 0 else raw_out
    payload = first.get("res", first) if isinstance(first, dict) else first

    # Trường hợp TextRecognition đơn lẻ trong PaddleOCR 3.x / PaddleX: {'rec_text': '...', 'rec_score': 0.95}
    if isinstance(payload, dict) or hasattr(payload, "keys"):
        if "rec_text" in payload:
            txt = str(payload["rec_text"]).strip()
            sc = float(payload["rec_score"]) if "rec_score" in payload else 0.0
            return txt, round(sc, 4)
        if "rec_texts" in payload:
            texts = [str(t).strip() for t in payload["rec_texts"] if str(t).strip()]
            scores = [float(s) for s in payload.get("rec_scores", [])] if hasattr(payload, "get") else []
            if not scores and "rec_scores" in payload:
                scores = [float(s) for s in payload["rec_scores"]]
            joined = " ".join(texts)
            avg_sc = round(sum(scores) / len(scores), 4) if scores else 0.0
            return joined, avg_sc

    # Fallback qua normalize_paddle_result
    lines = normalize_paddle_result(raw_out)
    if not lines:
        return "", 0.0
    joined_text = " ".join(ln["text"] for ln in lines)
    avg_score = round(sum(float(ln["score"]) for ln in lines) / len(lines), 4)
    return joined_text, avg_score


def create_default_crop_recognizers(
    base_lang: str,
) -> dict[str, Callable[[Image.Image], tuple[str, float]] | None]:
    """
    Tạo các bộ nhận dạng cho 3 phương án trên ảnh crop dòng chữ:
    (1) no_orient: Tắt use_textline_orientation (chạy trên crop gốc).
    (2) chinese_cht: Dùng lang='chinese_cht' (nếu không tồn tại thì trả về None và ghi nhận thông báo).
    (3) upscale_2x: Dùng cùng bộ nhận dạng không xoay dòng trên ảnh crop đã phóng 2x.
    """
    import numpy as np  # type: ignore
    from paddleocr import PaddleOCR  # type: ignore

    paddle_lang = LANG_MAP.get(base_lang.lower(), base_lang)
    init_sig = inspect.signature(PaddleOCR.__init__)
    accepts_var_kw = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in init_sig.parameters.values()
    )

    def _can_pass(name: str) -> bool:
        return accepts_var_kw or (name in init_sig.parameters)

    def _build_engine(lang_code: str) -> Any:
        kw: dict[str, Any] = {"lang": lang_code}
        if _can_pass("use_doc_orientation_classify"):
            kw["use_doc_orientation_classify"] = False
        if _can_pass("use_doc_unwarping"):
            kw["use_doc_unwarping"] = False
        if _can_pass("use_textline_orientation"):
            kw["use_textline_orientation"] = False
        elif _can_pass("use_angle_cls"):
            kw["use_angle_cls"] = False
        return PaddleOCR(**kw)

    def _find_direct_rec_predictor(engine: Any) -> Any | None:
        for attr in ("paddlex_pipeline", "_pipeline", "pipeline"):
            pipe = getattr(engine, attr, None)
            if pipe is not None and hasattr(pipe, "text_rec_model"):
                return getattr(pipe, "text_rec_model")
        return None

    def _make_crop_callable(engine: Any) -> Callable[[Image.Image], tuple[str, float]]:
        rec_predictor = _find_direct_rec_predictor(engine)

        def _recognize_crop(crop_img: Image.Image) -> tuple[str, float]:
            rgb = np.array(crop_img.convert("RGB"))
            bgr = rgb[:, :, ::-1]

            # Ưu tiên gọi trực tiếp text_rec_model trên ảnh crop dòng chữ (bỏ qua det và orientation)
            if rec_predictor is not None:
                try:
                    if hasattr(rec_predictor, "predict"):
                        raw = list(rec_predictor.predict(bgr))
                    else:
                        raw = list(rec_predictor(bgr))
                    txt, sc = extract_text_and_score_from_rec_output(raw)
                    if txt:
                        return txt, sc
                except Exception:
                    pass

            # Nếu gọi qua pipeline tổng (det+rec), đệm viền trắng 16px quanh crop để detector không bỏ sót chữ sát mép
            padded = Image.new("RGB", (crop_img.width + 32, crop_img.height + 32), (255, 255, 255))
            padded.paste(crop_img.convert("RGB"), (16, 16))
            bgr_pad = np.array(padded)[:, :, ::-1]
            if hasattr(engine, "predict"):
                raw_full = list(engine.predict(bgr_pad))
            else:
                raw_full = engine.ocr(bgr_pad)
            return extract_text_and_score_from_rec_output(raw_full)

        return _recognize_crop

    base_engine = _build_engine(paddle_lang)
    base_no_orient_fn = _make_crop_callable(base_engine)

    cht_fn: Callable[[Image.Image], tuple[str, float]] | None = None
    cht_status_note = "OK"
    try:
        cht_engine = _build_engine("chinese_cht")
        cht_fn = _make_crop_callable(cht_engine)
    except Exception as exc:
        cht_fn = None
        cht_status_note = f"Bỏ qua lang='chinese_cht' vì không khả dụng hoặc lỗi khởi tạo: {exc}"

    return {
        "no_orient": base_no_orient_fn,
        "chinese_cht": cht_fn,
        "upscale_2x": base_no_orient_fn,
        "chinese_cht_status": cht_status_note,  # type: ignore[dict-item]
    }


def crop_line_from_page(page_img: Image.Image, bbox: list[int], pad_px: int = 2) -> Image.Image:
    """Cắt khung dòng chữ từ trang gốc (có kẹp biên an toàn)."""
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
    cx1 = max(0, x1 - pad_px)
    cy1 = max(0, y1 - pad_px)
    cx2 = min(page_img.width, max(cx1 + 1, x2 + pad_px))
    cy2 = min(page_img.height, max(cy1 + 1, y2 + pad_px))
    return page_img.crop((cx1, cy1, cx2, cy2)).convert("RGB")


def upscale_crop_2x(crop_img: Image.Image) -> Image.Image:
    """Phóng to ảnh crop lên gấp 2 lần chiều rộng và chiều cao."""
    new_w = max(2, crop_img.width * 2)
    new_h = max(2, crop_img.height * 2)
    resample_filter = getattr(Image, "Resampling", Image).BICUBIC
    return crop_img.resize((new_w, new_h), resample=resample_filter)


def compare_low_score_lines(
    probe_json_paths: list[Path],
    score_threshold: float = DEFAULT_LOW_SCORE_THRESHOLD,
    images_dir_override: dict[str, Path] | None = None,
    recognizers_factory: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Quét các dòng có score < score_threshold trong các file probe JSON và nhận dạng lại bằng:
      (1) tắt textline orientation
      (2) lang chinese_cht (nếu không tồn tại thì bỏ qua và báo)
      (3) phóng crop 2x
    """
    active_factory = (
        recognizers_factory if recognizers_factory is not None else create_default_crop_recognizers
    )
    recognizers_by_lang: dict[str, dict[str, Any]] = {}
    comparisons: list[dict[str, Any]] = []
    chinese_cht_notices: list[str] = []

    for probe_path in probe_json_paths:
        if not probe_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file probe JSON: {probe_path}")

        probe_data = json.loads(probe_path.read_text(encoding="utf-8"))
        lang = str(probe_data.get("lang", "zh"))
        default_input_dir = Path(str(probe_data.get("input_dir", "")))
        if images_dir_override and probe_path.name in images_dir_override:
            img_dir = images_dir_override[probe_path.name]
        elif images_dir_override and lang in images_dir_override:
            img_dir = images_dir_override[lang]
        else:
            img_dir = default_input_dir

        if lang not in recognizers_by_lang:
            recognizers_by_lang[lang] = active_factory(lang)
            status_msg = str(recognizers_by_lang[lang].get("chinese_cht_status", ""))
            if status_msg and status_msg != "OK" and status_msg not in chinese_cht_notices:
                chinese_cht_notices.append(status_msg)

        recs = recognizers_by_lang[lang]
        fn_no_orient = recs.get("no_orient")
        fn_cht = recs.get("chinese_cht")
        fn_2x = recs.get("upscale_2x")

        for img_entry in probe_data.get("images", []):
            image_name = str(img_entry.get("image_name", ""))
            lines = img_entry.get("lines", [])
            low_lines = [
                ln for ln in lines if float(ln.get("score", 0.0)) < score_threshold
            ]
            if not low_lines:
                continue

            img_path = img_dir / image_name
            if not img_path.exists():
                raise FileNotFoundError(
                    f"Không tìm thấy ảnh gốc '{img_path}' cho file probe '{probe_path.name}'."
                )

            with Image.open(img_path) as page_img:
                for ln in low_lines:
                    bbox = ln.get("bbox", [0, 0, 0, 0])
                    crop_1x = crop_line_from_page(page_img, bbox)
                    crop_2x = upscale_crop_2x(crop_1x)

                    text_no_orient, score_no_orient = (
                        fn_no_orient(crop_1x) if callable(fn_no_orient) else ("", 0.0)
                    )

                    if callable(fn_cht):
                        try:
                            text_cht, score_cht = fn_cht(crop_1x)
                            cht_skipped = False
                        except Exception as exc:
                            text_cht, score_cht = "SKIPPED", 0.0
                            cht_skipped = True
                            msg = f"Lỗi khi chạy chinese_cht: {exc}"
                            if msg not in chinese_cht_notices:
                                chinese_cht_notices.append(msg)
                    else:
                        text_cht, score_cht = "SKIPPED", 0.0
                        cht_skipped = True

                    text_2x, score_2x = (
                        fn_2x(crop_2x) if callable(fn_2x) else ("", 0.0)
                    )

                    comparisons.append(
                        {
                            "probe_file": probe_path.name,
                            "lang": lang,
                            "image_name": image_name,
                            "line_id": ln.get("id"),
                            "bbox": bbox,
                            "crop_size_1x": [crop_1x.width, crop_1x.height],
                            "crop_size_2x": [crop_2x.width, crop_2x.height],
                            "old_score": float(ln.get("score", 0.0)),
                            "old_text": str(ln.get("text", "")),
                            "variant_1_no_orient": {
                                "text": text_no_orient,
                                "score": score_no_orient,
                            },
                            "variant_2_chinese_cht": {
                                "skipped": cht_skipped,
                                "text": text_cht,
                                "score": score_cht,
                            },
                            "variant_3_upscale_2x": {
                                "text": text_2x,
                                "score": score_2x,
                            },
                        }
                    )

    return {
        "score_threshold": score_threshold,
        "total_low_score_lines": len(comparisons),
        "chinese_cht_notices": chinese_cht_notices,
        "items": comparisons,
    }


def format_comparison_table(report: dict[str, Any]) -> str:
    """Tạo bảng đối chiếu rõ ràng để người dùng tự chấm."""
    lines_out: list[str] = []
    lines_out.append("================================================================================")
    lines_out.append(
        f"[Rec Compare - Bước 1A] SO SÁNH NHẬN DẠNG LẠI CÁC DÒNG ĐIỂM NHỎ HƠN {report['score_threshold']}"
    )
    lines_out.append(f"Tổng số dòng điểm thấp được kiểm tra: {report['total_low_score_lines']}")
    for notice in report.get("chinese_cht_notices", []):
        lines_out.append(f"[Thông báo chinese_cht] {notice}")
    lines_out.append("================================================================================")

    header = (
        "| File / Ảnh | #ID | Điểm cũ | Text cũ | "
        "(1) Tắt orient | (2) chinese_cht | (3) Phóng crop 2x |"
    )
    sep = "|---|---:|---:|---|---|---|---|"
    lines_out.append(header)
    lines_out.append(sep)

    for item in report.get("items", []):
        v1 = item["variant_1_no_orient"]
        v2 = item["variant_2_chinese_cht"]
        v3 = item["variant_3_upscale_2x"]

        v1_str = f"{v1['text']} ({v1['score']:.2f})"
        v2_str = "SKIPPED" if v2["skipped"] else f"{v2['text']} ({v2['score']:.2f})"
        v3_str = f"{v3['text']} ({v3['score']:.2f})"

        row = (
            f"| {item['image_name']} ({item['lang']}) "
            f"| #{item['line_id']} "
            f"| {item['old_score']:.2f} "
            f"| {item['old_text']} "
            f"| {v1_str} "
            f"| {v2_str} "
            f"| {v3_str} |"
        )
        lines_out.append(row)

    return "\n".join(lines_out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bước 1A: Với các dòng có điểm tin cậy nhỏ hơn 0.6 trong 2 file probe, "
            "nhận dạng lại bằng (1) tắt textline orientation, (2) chinese_cht, (3) phóng crop 2x."
        )
    )
    parser.add_argument(
        "--probe-jsons",
        type=Path,
        nargs="+",
        required=True,
        help="Đường dẫn tới 1 hoặc 2 file JSON xuất từ ocr_probe.py",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_LOW_SCORE_THRESHOLD,
        help="Ngưỡng điểm tin cậy cần kiểm tra lại (mặc định: 0.6)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Tùy chọn: Đường dẫn lưu kết quả JSON (ngoài dự án)",
    )
    args = parser.parse_args()

    report = compare_low_score_lines(
        probe_json_paths=args.probe_jsons,
        score_threshold=args.score_threshold,
    )
    table_text = format_comparison_table(report)
    print(table_text)

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[Rec Compare] Đã lưu chi tiết JSON tại: {args.output_json}")


if __name__ == "__main__":
    main()
