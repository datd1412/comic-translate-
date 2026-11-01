from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

from ocr_probe import compute_timing_summary, probe_directory

GROUND_TRUTH_DISCLAIMER = (
    "LƯU Ý: Ground truth tiếng Trung do AI chép, chưa kiểm bằng người. "
    "Các chỉ số CER / missed / extra trên tập tiếng Trung cần đối chiếu thêm bằng mắt."
)


def normalize_text_for_cer(text: str) -> str:
    """Chuẩn hóa khoảng trắng để tính CER công bằng giữa nhiều dòng trong 1 bong bóng."""
    return re.sub(r"\s+", "", text.strip())


def levenshtein_distance(s1: str, s2: str) -> int:
    """Khoảng cách chỉnh sửa Levenshtein ở mức ký tự."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def compute_cer(reference: str, hypothesis: str) -> float:
    """Tính Character Error Rate (CER) = edit_distance(ref, hyp) / max(1, len(ref))."""
    ref_norm = normalize_text_for_cer(reference)
    hyp_norm = normalize_text_for_cer(hypothesis)
    if not ref_norm and not hyp_norm:
        return 0.0
    if not ref_norm:
        return 1.0
    dist = levenshtein_distance(ref_norm, hyp_norm)
    return round(dist / len(ref_norm), 4)


def compute_iou(box_a: list[int], box_b: list[int]) -> float:
    """Tính IoU giữa hai khung [x1, y1, x2, y2]."""
    x_left = max(box_a[0], box_b[0])
    y_top = max(box_a[1], box_b[1])
    x_right = min(box_a[2], box_b[2])
    y_bottom = min(box_a[3], box_b[3])

    if x_right <= x_left or y_bottom <= y_top:
        return 0.0

    inter_area = float((x_right - x_left) * (y_bottom - y_top))
    area_a = float(max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1]))
    area_b = float(max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1]))
    union_area = area_a + area_b - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def is_line_inside_gt_box(line_box: list[int], gt_box: list[int], min_containment: float = 0.5) -> bool:
    """
    Vì PaddleOCR trả từng dòng chữ nhỏ còn ground_truth có thể ghi bbox của cả bong bóng thoại,
    ta kiểm tra tỉ lệ diện tích dòng chữ nằm bên trong bbox bong bóng (containment ratio) hoặc IoU.
    """
    x_left = max(line_box[0], gt_box[0])
    y_top = max(line_box[1], gt_box[1])
    x_right = min(line_box[2], gt_box[2])
    y_bottom = min(line_box[3], gt_box[3])

    if x_right <= x_left or y_bottom <= y_top:
        return False

    inter_area = float((x_right - x_left) * (y_bottom - y_top))
    line_area = float(max(1, (line_box[2] - line_box[0]) * (line_box[3] - line_box[1])))
    containment = inter_area / line_area
    return containment >= min_containment or compute_iou(line_box, gt_box) >= 0.3


def evaluate_single_image(
    gt_blocks: list[dict[str, Any]],
    pred_lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Đối chiếu các dòng OCR dự đoán (pred_lines) với danh sách khối bong bóng chuẩn (gt_blocks).
    Mỗi phần tử trong gt_blocks có dạng:
      {"id": "b1", "bbox": [x1, y1, x2, y2] (tùy chọn), "text": "nội dung chuẩn"}
    Nếu gt_block có bbox: gom tất cả pred_lines nằm trong gt_box (theo thứ tự từ trên xuống) để ghép thành văn bản dự đoán của bong bóng đó.
    Nếu gt_block không có bbox: khớp greedy theo độ tương đồng ký tự (CER thấp nhất, không vượt quá 0.7).
    """
    used_pred_indices: set[int] = set()
    block_results: list[dict[str, Any]] = []
    missed_blocks = 0
    total_edit_distance = 0
    total_ref_chars = 0

    for gt_idx, gt in enumerate(gt_blocks):
        gt_id = gt.get("id", f"gt_{gt_idx + 1}")
        gt_text = str(gt.get("text", "")).strip()
        gt_bbox = gt.get("bbox")

        matched_indices: list[int] = []
        if isinstance(gt_bbox, list) and len(gt_bbox) == 4:
            for p_idx, pred in enumerate(pred_lines):
                if p_idx in used_pred_indices:
                    continue
                pred_bbox = pred.get("bbox", [0, 0, 0, 0])
                if is_line_inside_gt_box(pred_bbox, gt_bbox):
                    matched_indices.append(p_idx)
            # Sắp xếp dòng trong bong bóng từ trên xuống dưới, trái sang phải
            matched_indices.sort(
                key=lambda idx: (
                    pred_lines[idx].get("bbox", [0, 0, 0, 0])[1],
                    pred_lines[idx].get("bbox", [0, 0, 0, 0])[0],
                )
            )
        else:
            # Fallback khi ground_truth chỉ có text mà không vẽ bbox
            best_idx = None
            best_cer = 1.0
            for p_idx, pred in enumerate(pred_lines):
                if p_idx in used_pred_indices:
                    continue
                candidate_cer = compute_cer(gt_text, str(pred.get("text", "")))
                if candidate_cer < best_cer:
                    best_cer = candidate_cer
                    best_idx = p_idx
            if best_idx is not None and best_cer <= 0.7:
                matched_indices.append(best_idx)

        for idx in matched_indices:
            used_pred_indices.add(idx)

        hyp_text = " ".join(str(pred_lines[i].get("text", "")).strip() for i in matched_indices).strip()
        ref_norm = normalize_text_for_cer(gt_text)
        hyp_norm = normalize_text_for_cer(hyp_text)

        if not matched_indices or not hyp_norm:
            missed_blocks += 1
            dist = len(ref_norm)
            cer = 1.0 if ref_norm else 0.0
        else:
            dist = levenshtein_distance(ref_norm, hyp_norm)
            cer = round(dist / max(1, len(ref_norm)), 4)

        total_edit_distance += dist
        total_ref_chars += len(ref_norm)

        block_results.append(
            {
                "gt_id": gt_id,
                "gt_text": gt_text,
                "hypothesis_text": hyp_text,
                "matched_line_ids": [pred_lines[i].get("id", i + 1) for i in matched_indices],
                "is_missed": len(matched_indices) == 0 or not hyp_norm,
                "cer": cer,
            }
        )

    extra_lines = [
        pred_lines[i] for i in range(len(pred_lines)) if i not in used_pred_indices
    ]

    image_cer = (
        round(total_edit_distance / total_ref_chars, 4)
        if total_ref_chars > 0
        else 0.0
    )

    return {
        "gt_block_count": len(gt_blocks),
        "pred_line_count": len(pred_lines),
        "missed_blocks": missed_blocks,
        "extra_blocks": len(extra_lines),
        "cer": image_cer,
        "total_edit_distance": total_edit_distance,
        "total_ref_chars": total_ref_chars,
        "blocks": block_results,
        "extra_detected_items": [
            {
                "id": item.get("id"),
                "bbox": item.get("bbox"),
                "text": item.get("text"),
                "score": item.get("score"),
            }
            for item in extra_lines
        ],
    }


def summarize_probe_only(probe_report: dict[str, Any]) -> dict[str, Any]:
    """
    Thống kê kết quả ocr_probe khi KHÔNG có ground_truth.json
    để kết hợp kiểm tra ảnh đã vẽ khung bằng mắt (visualize_probe.py).
    """
    images = probe_report.get("images", [])
    elapsed_list: list[float] = []
    line_counts: list[int] = []
    all_scores: list[float] = []
    single_char_lines = 0
    low_score_lines = 0
    per_image_stats: list[dict[str, Any]] = []

    for img in images:
        elapsed_ms = float(img.get("elapsed_ms", 0.0))
        elapsed_list.append(elapsed_ms)
        lines = img.get("lines", [])
        line_counts.append(len(lines))

        img_single_char = 0
        img_low_score = 0
        img_scores: list[float] = []

        for ln in lines:
            txt = normalize_text_for_cer(str(ln.get("text", "")))
            sc = float(ln.get("score", 0.0))
            all_scores.append(sc)
            img_scores.append(sc)
            if len(txt) <= 1:
                single_char_lines += 1
                img_single_char += 1
            if sc < 0.80:
                low_score_lines += 1
                img_low_score += 1

        per_image_stats.append(
            {
                "image_name": img.get("image_name"),
                "width": img.get("width"),
                "height": img.get("height"),
                "elapsed_ms": elapsed_ms,
                "line_count": len(lines),
                "single_char_line_count": img_single_char,
                "low_score_line_count_under_0_80": img_low_score,
                "mean_score": round(float(statistics.mean(img_scores)), 4) if img_scores else None,
                "min_score": round(float(min(img_scores)), 4) if img_scores else None,
                "lines": lines,
            }
        )

    total_lines = sum(line_counts)
    return {
        "mode": "probe_only_no_ground_truth",
        "summary": {
            "total_images": len(images),
            "total_detected_lines": total_lines,
            "mean_lines_per_image": round(float(statistics.mean(line_counts)), 2) if line_counts else 0.0,
            "min_lines_per_image": min(line_counts) if line_counts else 0,
            "max_lines_per_image": max(line_counts) if line_counts else 0,
            "single_char_lines": single_char_lines,
            "low_score_lines_under_0_80": low_score_lines,
            "mean_confidence_score": round(float(statistics.mean(all_scores)), 4) if all_scores else None,
            "min_confidence_score": round(float(min(all_scores)), 4) if all_scores else None,
            "max_confidence_score": round(float(max(all_scores)), 4) if all_scores else None,
            "timing_summary": probe_report.get("timing_summary")
            or compute_timing_summary(elapsed_list),
        },
        "images": per_image_stats,
    }


def evaluate_dataset(
    ground_truth_data: dict[str, Any],
    probe_report: dict[str, Any],
) -> dict[str, Any]:
    """
    Đánh giá toàn bộ tập ảnh dựa trên ground_truth.json và kết quả từ ocr_probe.
    """
    gt_images: dict[str, list[dict[str, Any]]] = ground_truth_data.get("images", ground_truth_data)
    probe_by_name = {
        img["image_name"]: img for img in probe_report.get("images", [])
    }

    per_image_eval: list[dict[str, Any]] = []
    total_gt_blocks = 0
    total_missed_blocks = 0
    total_extra_blocks = 0
    dataset_edit_distance = 0
    dataset_ref_chars = 0
    elapsed_list: list[float] = []

    for img_name, probe_img in probe_by_name.items():
        elapsed_ms = float(probe_img.get("elapsed_ms", 0.0))
        elapsed_list.append(elapsed_ms)

        if img_name not in gt_images or not isinstance(gt_images[img_name], list):
            continue

        gt_blocks = gt_images[img_name]
        pred_lines = probe_img.get("lines", [])
        img_eval = evaluate_single_image(gt_blocks, pred_lines)
        img_eval["image_name"] = img_name
        img_eval["elapsed_ms"] = elapsed_ms
        per_image_eval.append(img_eval)

        total_gt_blocks += img_eval["gt_block_count"]
        total_missed_blocks += img_eval["missed_blocks"]
        total_extra_blocks += img_eval["extra_blocks"]
        dataset_edit_distance += img_eval["total_edit_distance"]
        dataset_ref_chars += img_eval["total_ref_chars"]

    overall_cer = (
        round(dataset_edit_distance / dataset_ref_chars, 4)
        if dataset_ref_chars > 0
        else 0.0
    )
    miss_rate = (
        round(total_missed_blocks / total_gt_blocks, 4)
        if total_gt_blocks > 0
        else 0.0
    )

    return {
        "mode": "with_ground_truth",
        "ground_truth_notice": GROUND_TRUTH_DISCLAIMER,
        "summary": {
            "evaluated_images": len(per_image_eval),
            "total_gt_blocks": total_gt_blocks,
            "total_missed_blocks": total_missed_blocks,
            "miss_rate": miss_rate,
            "total_extra_blocks_sfx_or_noise": total_extra_blocks,
            "overall_cer": overall_cer,
            "timing_summary": probe_report.get("timing_summary")
            or compute_timing_summary(elapsed_list),
        },
        "images": per_image_eval,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 0: Đánh giá kết quả OCR. Nếu truyền --ground-truth thì tính CER / missed / extra; "
            "nếu KHÔNG truyền --ground-truth thì in thống kê của probe để xem ảnh bằng mắt."
        )
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help="Thư mục chứa các trang truyện (cần nếu chưa truyền --probe-json)",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=None,
        help="Tùy chọn: Đường dẫn tới file ground_truth.json. Nếu bỏ trống sẽ chỉ in thống kê của probe.",
    )
    parser.add_argument(
        "--lang",
        default="zh",
        choices=["zh", "ch", "en", "ko", "ja"],
        help="Ngôn ngữ chạy PaddleOCR nếu không truyền --probe-json",
    )
    parser.add_argument(
        "--probe-json",
        type=Path,
        default=None,
        help="Tùy chọn: dùng lại file JSON đã xuất từ ocr_probe.py để không phải chạy lại model",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Tùy chọn: File JSON lưu báo cáo đánh giá/thống kê",
    )
    args = parser.parse_args()

    if args.probe_json is not None and args.probe_json.exists():
        probe_report = json.loads(args.probe_json.read_text(encoding="utf-8"))
    elif args.images_dir is not None:
        probe_report = probe_directory(input_dir=args.images_dir, lang=args.lang)
    else:
        raise ValueError("Phải cung cấp ít nhất --probe-json hoặc --images-dir.")

    if args.ground_truth is not None:
        gt_data = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        report = evaluate_dataset(ground_truth_data=gt_data, probe_report=probe_report)
    else:
        report = summarize_probe_only(probe_report=probe_report)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    s = report["summary"]
    timing = s["timing_summary"]

    if report["mode"] == "with_ground_truth":
        print(f"[!] {report['ground_truth_notice']}")
        if args.output is not None:
            print(f"[Eval OCR] Đã lưu báo cáo tại: {args.output}")
        print(f"  - Số ảnh đã chấm: {s['evaluated_images']}")
        print(f"  - Tổng số bong bóng chuẩn (GT): {s['total_gt_blocks']}")
        print(f"  - Số khối bị bỏ sót (Missed): {s['total_missed_blocks']} (tỉ lệ: {s['miss_rate'] * 100:.1f}%)")
        print(f"  - Số khối thừa (SFX / watermark / rác): {s['total_extra_blocks_sfx_or_noise']}")
        print(f"  - Tỉ lệ lỗi ký tự tổng thể (CER): {s['overall_cer'] * 100:.2f}%")
    else:
        print("[Eval OCR - Chế độ thống kê Probe (không dùng ground_truth.json)]")
        if args.output is not None:
            print(f"  - Đã lưu thống kê tại: {args.output}")
        print(f"  - Tổng số ảnh: {s['total_images']}")
        print(
            f"  - Tổng số dòng phát hiện: {s['total_detected_lines']} "
            f"(TB: {s['mean_lines_per_image']} dòng/ảnh, min: {s['min_lines_per_image']}, max: {s['max_lines_per_image']})"
        )
        print(f"  - Số dòng chỉ có 1 ký tự (nghi vấn rác/SFX lẻ): {s['single_char_lines']}")
        print(f"  - Số dòng có điểm tin cậy nhỏ hơn 0.80: {s['low_score_lines_under_0_80']}")
        print(
            f"  - Điểm tin cậy (score): TB={s['mean_confidence_score']}, "
            f"min={s['min_confidence_score']}, max={s['max_confidence_score']}"
        )
        print("  - Chi tiết từng ảnh:")
        for img_stat in report["images"]:
            print(
                f"    * {img_stat['image_name']} ({img_stat['width']}x{img_stat['height']}): "
                f"{img_stat['line_count']} dòng, {img_stat['single_char_line_count']} dòng 1-ký-tự, "
                f"thời gian={img_stat['elapsed_ms']} ms"
            )

    print(
        f"  - Thời gian TB (bỏ ảnh đầu): {timing['mean_ms_excluding_first']} ms "
        f"(ảnh đầu warm-up: {timing['first_image_warmup_ms']} ms)"
    )


if __name__ == "__main__":
    main()