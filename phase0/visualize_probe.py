from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def draw_probe_annotations(
    image: Image.Image,
    lines: list[dict[str, Any]],
) -> Image.Image:
    """
    Vẽ khung chữ (polygon + bbox), số thứ tự (#id) và điểm tin cậy (score)
    lên bản sao của ảnh gốc để kiểm tra trực quan bằng mắt.
    """
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()

    for idx, line in enumerate(lines):
        line_id = line.get("id", idx + 1)
        score = float(line.get("score", 0.0))
        bbox = line.get("bbox", [0, 0, 0, 0])
        polygon = line.get("polygon")

        # Chọn màu khung theo mức điểm tin cậy để dễ phân biệt bằng mắt:
        # Đỏ cam đậm cho điểm cao (từ 0.80 trở lên), Tím xanh cho điểm thấp (nhỏ hơn 0.80)
        if score >= 0.80:
            stroke_color = (234, 88, 12, 255)      # Cam đậm (#EA580C)
            fill_color = (249, 115, 22, 36)        # Cam nhạt bán trong suốt
            badge_bg = (234, 88, 12, 235)
        else:
            stroke_color = (37, 99, 235, 255)      # Xanh dương (#2563EB)
            fill_color = (59, 130, 246, 36)
            badge_bg = (37, 99, 235, 235)

        if isinstance(polygon, list) and len(polygon) >= 3:
            pts = [(int(round(float(p[0]))), int(round(float(p[1])))) for p in polygon]
            draw.polygon(pts, fill=fill_color, outline=stroke_color)
            # Vẽ viền dày 2px cho dễ nhìn trên trang webtoon lớn
            for i in range(len(pts)):
                p1 = pts[i]
                p2 = pts[(i + 1) % len(pts)]
                draw.line([p1, p2], fill=stroke_color, width=2)
            anchor_x, anchor_y = pts[0]
        elif isinstance(bbox, list) and len(bbox) == 4:
            x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
            draw.rectangle([x1, y1, x2, y2], fill=fill_color, outline=stroke_color, width=2)
            anchor_x, anchor_y = x1, y1
        else:
            continue

        label = f"#{line_id} ({score:.2f})"
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]

        pad_x = 4
        pad_y = 2
        badge_w = text_w + pad_x * 2
        badge_h = text_h + pad_y * 2

        badge_x1 = max(0, min(anchor_x, canvas.width - badge_w))
        badge_y1 = anchor_y - badge_h if anchor_y - badge_h >= 0 else anchor_y
        badge_x2 = badge_x1 + badge_w
        badge_y2 = badge_y1 + badge_h

        draw.rectangle([badge_x1, badge_y1, badge_x2, badge_y2], fill=badge_bg)
        draw.text(
            (badge_x1 + pad_x, badge_y1 + pad_y),
            label,
            fill=(255, 255, 255, 255),
            font=font,
        )

    combined = Image.alpha_composite(canvas, overlay)
    return combined.convert("RGB")


def visualize_probe_report(
    images_dir: Path,
    probe_json_path: Path,
    output_dir: Path,
) -> list[Path]:
    """
    Đọc file JSON của ocr_probe.py, tìm ảnh tương ứng trong images_dir,
    vẽ khung + số thứ tự + điểm tin cậy và lưu sang output_dir (hỗ trợ đường dẫn tuyệt đối ngoài dự án).
    """
    if not images_dir.exists() or not images_dir.is_dir():
        raise FileNotFoundError(f"Thư mục ảnh gốc không tồn tại: {images_dir}")
    if not probe_json_path.exists() or not probe_json_path.is_file():
        raise FileNotFoundError(f"File JSON probe không tồn tại: {probe_json_path}")

    probe_data = json.loads(probe_json_path.read_text(encoding="utf-8"))
    images_entries = probe_data.get("images", [])

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for entry in images_entries:
        image_name = entry.get("image_name")
        if not image_name:
            continue
        src_path = images_dir / image_name
        if not src_path.exists():
            continue

        lines = entry.get("lines", [])
        with Image.open(src_path) as img:
            annotated = draw_probe_annotations(img, lines)
            stem = Path(image_name).stem
            out_path = output_dir / f"{stem}_vis.png"
            annotated.save(out_path, format="PNG")
            saved_paths.append(out_path)

    return saved_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 0: Vẽ khung, số thứ tự (#id) và điểm tin cậy (score) từ kết quả ocr_probe.py lên ảnh gốc."
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        required=True,
        help="Đường dẫn thư mục chứa ảnh gốc (ví dụ: D:\\comic_samples\\baozimh_pages)",
    )
    parser.add_argument(
        "--probe-json",
        type=Path,
        required=True,
        help="Đường dẫn file JSON xuất từ ocr_probe.py (ví dụ: D:\\comic_samples\\out\\baozimh_probe.json)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Đường dẫn thư mục lưu ảnh đã vẽ khung (tuyệt đối, ngoài dự án, ví dụ: D:\\comic_samples\\vis_baozimh)",
    )
    args = parser.parse_args()

    saved = visualize_probe_report(
        images_dir=args.images_dir,
        probe_json_path=args.probe_json,
        output_dir=args.output_dir,
    )
    print(f"[Visualize Probe] Đã xuất {len(saved)} ảnh có vẽ khung vào: {args.output_dir.resolve()}")
    for p in saved:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
