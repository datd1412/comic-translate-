from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from ocr_probe import (
    IMAGE_EXTENSIONS,
    LANG_MAP,
    normalize_paddle_result,
)
from visualize_probe import draw_probe_annotations

NEAR_SEAM_THRESHOLD_PX = 40
NEAR_SEAM_NOTE = (
    "Ngưỡng 40 px quanh đường nối chỉ dùng để thống kê, chưa kiểm chứng. "
    "Script này chỉ đo đạc, KHÔNG có bất kỳ logic gộp khối nào."
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ensure_outside_project(target_path: Path, allow_in_tests: bool = False) -> Path:
    """Đảm bảo không ghi ảnh xuất ra vào bên trong thư mục dự án."""
    resolved = target_path.resolve()
    if not allow_in_tests:
        try:
            resolved.relative_to(PROJECT_ROOT)
            raise ValueError(
                f"Đường dẫn xuất ảnh ({resolved}) không được nằm trong thư mục dự án ({PROJECT_ROOT}). "
                "Hãy chỉ định đường dẫn tuyệt đối ngoài dự án."
            )
        except ValueError as exc:
            if "không được nằm trong thư mục dự án" in str(exc):
                raise
    return resolved


def create_default_stitch_ocr_runner(lang: str) -> Callable[[Image.Image, str], Any]:
    """
    Khởi tạo PaddleOCR và nhận trực tiếp đối tượng PIL.Image trong bộ nhớ (hoặc mảng numpy)
    để dải ảnh ghép không cần lưu tạm vào thư mục dự án.
    """
    import inspect
    import numpy as np  # type: ignore
    from paddleocr import PaddleOCR  # type: ignore

    paddle_lang = LANG_MAP.get(lang.lower(), lang)
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

    def _run(image: Image.Image, label: str) -> Any:
        rgb_arr = np.array(image.convert("RGB"))
        # Chuyển RGB sang BGR cho quy ước mảng ảnh của PaddleOCR/OpenCV
        bgr_arr = rgb_arr[:, :, ::-1]
        if hasattr(ocr_engine, "predict"):
            try:
                return list(ocr_engine.predict(bgr_arr))
            except Exception:
                pass
        ocr_sig = inspect.signature(ocr_engine.ocr)
        if "cls" in ocr_sig.parameters:
            return ocr_engine.ocr(bgr_arr, cls=True)
        return ocr_engine.ocr(bgr_arr)

    return _run


def stitch_two_images_vertically(top_img: Image.Image, bottom_img: Image.Image) -> tuple[Image.Image, int]:
    """Ghép hai lát theo chiều dọc thành một dải. Trả về (ảnh ghép, tọa độ y của đường nối)."""
    width = max(top_img.width, bottom_img.width)
    seam_y = top_img.height
    total_height = top_img.height + bottom_img.height
    stitched = Image.new("RGB", (width, total_height), color=(255, 255, 255))
    stitched.paste(top_img.convert("RGB"), (0, 0))
    stitched.paste(bottom_img.convert("RGB"), (0, seam_y))
    return stitched, seam_y


def find_closest_block_to_seam_top(
    top_lines: list[dict[str, Any]],
    top_slice_height: int,
    near_threshold_px: int = NEAR_SEAM_THRESHOLD_PX,
) -> dict[str, Any] | None:
    """
    Tìm khối chữ ở lát trên gần đường nối nhất (đường nối nằm ở y = top_slice_height).
    Khoảng cách tới đường nối = max(0, top_slice_height - y2).
    """
    if not top_lines:
        return None

    best_info: dict[str, Any] | None = None
    for ln in top_lines:
        bbox = ln.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = bbox
        dist_px = max(0, int(top_slice_height - y2))
        line_height_px = max(0, int(y2 - y1))
        text_str = str(ln.get("text", "")).strip()
        last_char = text_str[-1] if text_str else ""

        candidate = {
            "id": ln.get("id"),
            "bbox": bbox,
            "distance_to_seam_px": dist_px,
            "line_height_px": line_height_px,
            "last_char": last_char,
            "text": text_str,
            "score": ln.get("score"),
            "within_40px_of_seam": dist_px <= near_threshold_px,
        }
        if best_info is None or dist_px < best_info["distance_to_seam_px"]:
            best_info = candidate

    return best_info


def find_closest_block_to_seam_bottom(
    bottom_lines: list[dict[str, Any]],
    near_threshold_px: int = NEAR_SEAM_THRESHOLD_PX,
) -> dict[str, Any] | None:
    """
    Tìm khối chữ ở lát dưới gần đường nối nhất (đường nối là mép trên y = 0 của lát dưới).
    Khoảng cách tới đường nối = max(0, y1).
    """
    if not bottom_lines:
        return None

    best_info: dict[str, Any] | None = None
    for ln in bottom_lines:
        bbox = ln.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = bbox
        dist_px = max(0, int(y1))
        line_height_px = max(0, int(y2 - y1))
        text_str = str(ln.get("text", "")).strip()
        last_char = text_str[-1] if text_str else ""

        candidate = {
            "id": ln.get("id"),
            "bbox": bbox,
            "distance_to_seam_px": dist_px,
            "line_height_px": line_height_px,
            "last_char": last_char,
            "text": text_str,
            "score": ln.get("score"),
            "within_40px_of_seam": dist_px <= near_threshold_px,
        }
        if best_info is None or dist_px < best_info["distance_to_seam_px"]:
            best_info = candidate

    return best_info


def draw_stitched_strip_visualization(
    stitched_img: Image.Image,
    stitched_lines: list[dict[str, Any]],
    seam_y: int,
) -> Image.Image:
    """
    Vẽ các khung chữ lên ảnh dải ghép và kẻ đường nối (seam_y) bằng một màu riêng biệt
    (màu hồng tím đậm #D946EF, khác hẳn màu cam và xanh dương của khung chữ).
    """
    annotated = draw_probe_annotations(stitched_img, stitched_lines)
    draw = ImageDraw.Draw(annotated)
    seam_color = (217, 70, 239)  # Hồng tím nổi bật (#D946EF)
    draw.line([(0, seam_y), (annotated.width, seam_y)], fill=seam_color, width=3)
    draw.text((8, max(0, seam_y - 14)), f"SEAM y={seam_y}px", fill=seam_color)
    return annotated


def probe_slice_sets(
    slice_dirs: list[Path],
    lang: str,
    vis_output_dir: Path,
    runner: Callable[[Image.Image, str], Any] | None = None,
    allow_vis_in_tests: bool = False,
) -> dict[str, Any]:
    """
    Chạy kiểm tra đường nối trên một hoặc nhiều thư mục lát cắt liên tiếp.
    Chỉ đo đạc và xuất ảnh dải ghép ngoài dự án, không viết logic gộp khối.
    """
    resolved_vis_dir = ensure_outside_project(vis_output_dir, allow_in_tests=allow_vis_in_tests)
    resolved_vis_dir.mkdir(parents=True, exist_ok=True)

    active_runner = runner if runner is not None else create_default_stitch_ocr_runner(lang)

    sets_report: list[dict[str, Any]] = []
    total_seams = 0
    seams_near_at_least_one_side = 0
    seams_near_both_sides = 0

    for set_dir in slice_dirs:
        if not set_dir.exists() or not set_dir.is_dir():
            raise FileNotFoundError(f"Thư mục bộ lát không tồn tại: {set_dir}")

        slice_files = sorted(
            [
                p
                for p in set_dir.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
            ],
            key=lambda p: p.name,
        )
        if len(slice_files) < 2:
            sets_report.append(
                {
                    "set_name": set_dir.name,
                    "set_dir": str(set_dir.resolve()),
                    "slice_count": len(slice_files),
                    "seam_count": 0,
                    "seams": [],
                }
            )
            continue

        # Đọc và OCR từng lát riêng
        slice_cache: dict[str, dict[str, Any]] = {}
        for sl_path in slice_files:
            with Image.open(sl_path) as im:
                copied_im = im.convert("RGB").copy()
            raw_res = active_runner(copied_im, sl_path.name)
            lines = normalize_paddle_result(
                raw_res, image_width=copied_im.width, image_height=copied_im.height
            )
            slice_cache[sl_path.name] = {
                "image": copied_im,
                "lines": lines,
            }

        seams_in_set: list[dict[str, Any]] = []
        set_vis_subdir = resolved_vis_dir / set_dir.name
        set_vis_subdir.mkdir(parents=True, exist_ok=True)

        for i in range(len(slice_files) - 1):
            top_file = slice_files[i]
            bottom_file = slice_files[i + 1]
            top_data = slice_cache[top_file.name]
            bottom_data = slice_cache[bottom_file.name]

            top_img: Image.Image = top_data["image"]
            bottom_img: Image.Image = bottom_data["image"]
            top_lines: list[dict[str, Any]] = top_data["lines"]
            bottom_lines: list[dict[str, Any]] = bottom_data["lines"]

            # Ghép 2 lát kề nhau theo chiều dọc và OCR lại trên dải ghép
            stitched_img, seam_y = stitch_two_images_vertically(top_img, bottom_img)
            stitched_label = f"{top_file.stem}__{bottom_file.stem}_stitched"
            raw_stitched = active_runner(stitched_img, stitched_label)
            stitched_lines = normalize_paddle_result(
                raw_stitched,
                image_width=stitched_img.width,
                image_height=stitched_img.height,
            )

            closest_top = find_closest_block_to_seam_top(top_lines, top_img.height)
            closest_bottom = find_closest_block_to_seam_bottom(bottom_lines)

            top_within_40px = bool(closest_top and closest_top["within_40px_of_seam"])
            bottom_within_40px = bool(closest_bottom and closest_bottom["within_40px_of_seam"])
            at_least_one_side_within_40px = top_within_40px or bottom_within_40px
            both_sides_within_40px = top_within_40px and bottom_within_40px

            total_seams += 1
            if at_least_one_side_within_40px:
                seams_near_at_least_one_side += 1
            if both_sides_within_40px:
                seams_near_both_sides += 1

            count_top = len(top_lines)
            count_bottom = len(bottom_lines)
            count_before_stitch = count_top + count_bottom
            count_after_stitch = len(stitched_lines)

            vis_img = draw_stitched_strip_visualization(stitched_img, stitched_lines, seam_y)
            vis_out_path = set_vis_subdir / f"seam_{i + 1:02d}_{top_file.stem}__{bottom_file.stem}.png"
            vis_img.save(vis_out_path, format="PNG")

            seams_in_set.append(
                {
                    "seam_index": i + 1,
                    "top_slice": top_file.name,
                    "bottom_slice": bottom_file.name,
                    "seam_y_px": seam_y,
                    "closest_block_top_side": closest_top,
                    "closest_block_bottom_side": closest_bottom,
                    "has_block_within_40px_top": top_within_40px,
                    "has_block_within_40px_bottom": bottom_within_40px,
                    "has_block_within_40px_at_least_one_side": at_least_one_side_within_40px,
                    "has_block_within_40px_both_sides": both_sides_within_40px,
                    "threshold_note": NEAR_SEAM_NOTE,
                    "block_count_comparison": {
                        "top_slice_blocks": count_top,
                        "bottom_slice_blocks": count_bottom,
                        "sum_before_stitch": count_before_stitch,
                        "stitched_strip_blocks": count_after_stitch,
                        "diff_after_minus_before": count_after_stitch - count_before_stitch,
                    },
                    "visualized_strip_path": str(vis_out_path),
                }
            )

        sets_report.append(
            {
                "set_name": set_dir.name,
                "set_dir": str(set_dir.resolve()),
                "slice_count": len(slice_files),
                "seam_count": len(seams_in_set),
                "seams": seams_in_set,
            }
        )

    return {
        "lang": lang,
        "near_seam_threshold_px": NEAR_SEAM_THRESHOLD_PX,
        "near_seam_note": NEAR_SEAM_NOTE,
        "summary": {
            "total_slice_sets": len(slice_dirs),
            "total_seams": total_seams,
            "seams_with_near_block_at_least_one_side": seams_near_at_least_one_side,
            "seams_with_near_block_both_sides": seams_near_both_sides,
        },
        "sets": sets_report,
    }


def print_stitch_probe_report(report: dict[str, Any]) -> None:
    print(f"[Stitch Probe] {report['near_seam_note']}")
    for s in report.get("sets", []):
        print(f"\n=== Bộ lát: {s['set_name']} ({s['slice_count']} lát, {s['seam_count']} đường nối) ===")
        for seam in s.get("seams", []):
            print(
                f"  * Đường nối #{seam['seam_index']}: {seam['top_slice']} + {seam['bottom_slice']} "
                f"(seam_y = {seam['seam_y_px']} px)"
            )
            top_b = seam["closest_block_top_side"]
            if top_b:
                print(
                    f"    - Khối gần đường nối nhất ở LÁT TRÊN: cách đường nối={top_b['distance_to_seam_px']} px, "
                    f"cao={top_b['line_height_px']} px, ký tự cuối='{top_b['last_char']}', "
                    f"trong 40px={top_b['within_40px_of_seam']}"
                )
            else:
                print("    - Khối gần đường nối nhất ở LÁT TRÊN: (không có khối nào)")

            bot_b = seam["closest_block_bottom_side"]
            if bot_b:
                print(
                    f"    - Khối gần đường nối nhất ở LÁT DƯỚI: cách đường nối={bot_b['distance_to_seam_px']} px, "
                    f"cao={bot_b['line_height_px']} px, ký tự cuối='{bot_b['last_char']}', "
                    f"trong 40px={bot_b['within_40px_of_seam']}"
                )
            else:
                print("    - Khối gần đường nối nhất ở LÁT DƯỚI: (không có khối nào)")

            cmp_cnt = seam["block_count_comparison"]
            print(
                f"    - Có khối nằm trong 40 px quanh đường nối (chưa kiểm chứng): "
                f"ít nhất 1 bên={seam['has_block_within_40px_at_least_one_side']}, "
                f"cả 2 bên={seam['has_block_within_40px_both_sides']}"
            )
            print(
                f"    - Số khối trước ghép: {cmp_cnt['sum_before_stitch']} "
                f"({cmp_cnt['top_slice_blocks']} + {cmp_cnt['bottom_slice_blocks']}) "
                f"| Sau khi ghép: {cmp_cnt['stitched_strip_blocks']} "
                f"(chênh lệch: {cmp_cnt['diff_after_minus_before']})"
            )
            print(f"    - Ảnh dải ghép đã vẽ: {seam['visualized_strip_path']}")

    summary = report["summary"]
    print("\n=== TỔNG HỢP CUỐI ===")
    print(f"  - Tổng số bộ lát: {summary['total_slice_sets']}")
    print(f"  - Tổng số đường nối: {summary['total_seams']}")
    print(
        f"  - Số đường nối có khối sát mép (trong 40 px, chưa kiểm chứng) ở ÍT NHẤT MỘT BÊN: "
        f"{summary['seams_with_near_block_at_least_one_side']}"
    )
    print(
        f"  - Số đường nối có khối sát mép (trong 40 px, chưa kiểm chứng) ở CẢ HAI BÊN: "
        f"{summary['seams_with_near_block_both_sides']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 0: Đo đạc các khối chữ quanh đường nối giữa các lát ảnh liên tiếp "
            "(chỉ đo, không có logic gộp khối)."
        )
    )
    parser.add_argument(
        "--slice-dirs",
        type=Path,
        nargs="+",
        required=True,
        help="Một hoặc nhiều thư mục (đường dẫn tuyệt đối, ngoài dự án), mỗi thư mục là một bộ lát liên tiếp",
    )
    parser.add_argument(
        "--lang",
        required=True,
        choices=["zh", "ch", "en", "ko", "ja"],
        help="Ngôn ngữ chạy PaddleOCR",
    )
    parser.add_argument(
        "--vis-output-dir",
        type=Path,
        required=True,
        help="Thư mục lưu ảnh dải ghép có vẽ khung và đường nối (bắt buộc đường dẫn tuyệt đối ngoài dự án)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Tùy chọn: Đường dẫn lưu báo cáo JSON (ngoài dự án)",
    )
    args = parser.parse_args()

    report = probe_slice_sets(
        slice_dirs=args.slice_dirs,
        lang=args.lang,
        vis_output_dir=args.vis_output_dir,
    )
    if args.output_json is not None:
        out_json = ensure_outside_project(args.output_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Stitch Probe] Đã lưu JSON tại: {out_json}")

    print_stitch_probe_report(report)


if __name__ == "__main__":
    main()
