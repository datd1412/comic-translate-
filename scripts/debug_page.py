#!/usr/bin/env python3
"""
scripts/debug_page.py

Script chẩn đoán OCR và thứ tự đọc trang truyện:
1. Nhận đường dẫn ảnh, --lang (zh|en|ko|ja), --direction (ltr|rtl).
2. Đọc cấu hình OCR_SERVICE_URL và OCR_INTERNAL_SECRET từ settings của server.
3. Gửi ảnh đến call_ocr_service và lưu raw response vào fixtures/<tên ảnh>.ocr.json.
4. Sắp xếp các khối văn bản bằng sort_blocks_by_reading_order và in bảng thứ tự.
5. Vẽ bbox và số thứ tự sắp xếp bằng Pillow, lưu fixtures/<tên ảnh>.sorted.png.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
import sys

# Đảm bảo mã hóa UTF-8 trên Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import HTTPException
import httpx
from PIL import Image, ImageDraw, ImageFont

# Thêm thư mục server vào sys.path để import các module nghiệp vụ
REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

try:
    from config import settings
    from reading_order import extract_bbox, sort_blocks_by_reading_order
    from translate_routes import call_ocr_service
except ImportError as err:
    print(f"LỖI: Không thể import module từ thư mục server ({SERVER_DIR}): {err}", file=sys.stderr)
    sys.exit(1)


def get_prominent_font(size: int) -> ImageFont.ImageFont:
    """Tải font chữ kích thước lớn để vẽ nhãn số thứ tự."""
    font_candidates = [
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
        "segoeui.ttf",
        "tahoma.ttf",
    ]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chẩn đoán OCR và kiểm tra thứ tự đọc (reading order) của trang truyện tranh."
    )
    parser.add_argument(
        "image_path",
        type=str,
        help="Đường dẫn đến file ảnh trang truyện (ví dụ: path/to/page_01.jpg)",
    )
    parser.add_argument(
        "--lang",
        type=str,
        choices=["zh", "en", "ko", "ja"],
        default="zh",
        help="Ngôn ngữ nguồn của ảnh (zh | en | ko | ja). Mặc định: zh",
    )
    parser.add_argument(
        "--direction",
        type=str,
        choices=["ltr", "rtl"],
        default="rtl",
        help="Hướng đọc: 'rtl' (Phải -> Trái cho Manga/Manhua) hoặc 'ltr' (Trái -> Phải cho Webtoon/Manhwa). Mặc định: rtl",
    )
    return parser.parse_args()


def validate_environment() -> None:
    """Kiểm tra cấu hình biến môi trường kết nối OCR service từ settings."""
    ocr_url = getattr(settings, "OCR_SERVICE_URL", None)
    if not ocr_url or not str(ocr_url).strip():
        print(
            "LỖI CẤU HÌNH: OCR_SERVICE_URL chưa được thiết lập trong settings / .env.\n"
            "Vui lòng cấu hình OCR_SERVICE_URL (ví dụ: http://127.0.0.1:8001).",
            file=sys.stderr,
        )
        sys.exit(1)

    ocr_secret = getattr(settings, "OCR_INTERNAL_SECRET", None)
    if not ocr_secret or not str(ocr_secret).strip():
        print(
            "LỖI CẤU HÌNH: OCR_INTERNAL_SECRET chưa được thiết lập trong settings / .env.\n"
            "Vui lòng cấu hình OCR_INTERNAL_SECRET (ví dụ: dev-secret-key-123).",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    args = parse_arguments()
    validate_environment()

    image_file = Path(args.image_path)
    if not image_file.is_file():
        print(f"LỖI: Không tìm thấy file ảnh tại đường dẫn: '{args.image_path}'", file=sys.stderr)
        sys.exit(1)

    fixtures_dir = REPO_ROOT / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    image_stem = image_file.stem
    content_type, _ = mimetypes.guess_type(str(image_file))
    if not content_type:
        content_type = "image/png"

    try:
        image_bytes = image_file.read_bytes()
        with Image.open(image_file) as img:
            if img.mode in ("P", "RGBA", "LA"):
                annotated_img = img.convert("RGBA").convert("RGB")
            else:
                annotated_img = img.convert("RGB")
    except Exception as err:
        print(f"LỖI: Không thể mở file ảnh '{image_file}': {err}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Đang gửi ảnh '{image_file.name}' tới OCR service ({settings.OCR_SERVICE_URL})...")
    print(f"[*] Tham số: lang={args.lang}, direction={args.direction}")

    try:
        raw_response = asyncio.run(
            call_ocr_service(
                image_bytes=image_bytes,
                filename=image_file.name,
                content_type=content_type,
                source_lang=args.lang,
            )
        )
    except httpx.ConnectError:
        print(
            f"LỖI KẾT NỐI: Không thể kết nối tới OCR service tại {settings.OCR_SERVICE_URL}.\n"
            "Dịch vụ OCR hiện chưa khởi chạy hoặc bị từ chối kết nối.\n"
            "Vui lòng khởi chạy OCR service trước khi chạy script chẩn đoán.",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        print(
            f"LỖI TIMEOUT: Yêu cầu tới OCR service tại {settings.OCR_SERVICE_URL} bị timeout sau "
            f"{settings.OCR_TIMEOUT_SECONDS}s.",
            file=sys.stderr,
        )
        sys.exit(1)
    except HTTPException as http_exc:
        print(
            f"LỖI HTTP từ OCR service ({http_exc.status_code}): {http_exc.detail}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as err:
        print(f"LỖI không xác định khi gọi OCR service: {err}", file=sys.stderr)
        sys.exit(1)

    # 1. Lưu raw response không chỉnh sửa vào fixtures/<tên ảnh>.ocr.json
    raw_json_path = fixtures_dir / f"{image_stem}.ocr.json"
    try:
        with open(raw_json_path, "w", encoding="utf-8") as f:
            json.dump(raw_response, f, ensure_ascii=False, indent=2)
        print(f"[✓] Đã lưu raw response OCR vào: {raw_json_path}")
    except Exception as err:
        print(f"LỖI: Không thể ghi file JSON '{raw_json_path}': {err}", file=sys.stderr)
        sys.exit(1)

    # Lấy danh sách blocks từ raw response
    if isinstance(raw_response, dict):
        blocks = raw_response.get("blocks", [])
    elif isinstance(raw_response, list):
        blocks = raw_response
    else:
        blocks = []

    print(f"[*] Tìm thấy {len(blocks)} khối văn bản (text blocks).")

    # 2. Gọi sort_blocks_by_reading_order
    sorted_blocks = sort_blocks_by_reading_order(blocks, reading_direction=args.direction)

    # 3. In bảng kết quả
    print("\n" + "=" * 88)
    print(f"{'Thứ tự mới':<11} | {'ID':<8} | {'Bounding Box [x1, y1, x2, y2]':<32} | {'30 ký tự đầu của text'}")
    print("-" * 88)
    for idx, block in enumerate(sorted_blocks, start=1):
        block_id = str(block.get("id", "-"))
        bbox = extract_bbox(block)
        bbox_str = f"[{int(round(bbox[0]))}, {int(round(bbox[1]))}, {int(round(bbox[2]))}, {int(round(bbox[3]))}]"
        raw_text = str(block.get("text", "")).replace("\r", " ").replace("\n", " ").strip()
        preview_text = raw_text[:30]
        print(f"{idx:<11} | {block_id:<8} | {bbox_str:<32} | {preview_text}")
    print("=" * 88 + "\n")

    # 4. Vẽ bbox và số thứ tự sau khi sắp xếp lên ảnh bằng Pillow
    draw = ImageDraw.Draw(annotated_img)
    font_size = max(24, min(56, int(annotated_img.width * 0.032)))
    font = get_prominent_font(font_size)

    for idx, block in enumerate(sorted_blocks, start=1):
        bbox = extract_bbox(block)
        x1, y1, x2, y2 = [int(round(c)) for c in bbox]

        # Vẽ khung bbox màu đỏ nổi bật (outline width = 3)
        draw.rectangle([x1, y1, x2, y2], outline=(255, 30, 30), width=3)

        # Vẽ nhãn số thứ tự kích thước lớn, màu nổi bật (badge màu đỏ nền với viền trắng và chữ trắng)
        label_text = str(idx)
        tb = draw.textbbox((0, 0), label_text, font=font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        pad = max(4, int(font_size * 0.15))

        badge_w = tw + 2 * pad
        badge_h = th + 2 * pad

        bx1 = max(0, x1)
        if y1 - badge_h >= 0:
            by1 = y1 - badge_h
        else:
            by1 = min(y1, max(0, annotated_img.height - badge_h))

        bx2 = bx1 + badge_w
        by2 = by1 + badge_h

        # Nền badge
        draw.rectangle([bx1, by1, bx2, by2], fill=(220, 20, 20), outline=(255, 255, 255), width=2)
        # Chữ số thứ tự
        text_x = bx1 + pad - tb[0]
        text_y = by1 + pad - tb[1]
        draw.text((text_x, text_y), label_text, fill=(255, 255, 255), font=font)

    # 5. Lưu fixtures/<tên ảnh>.sorted.png
    output_image_path = fixtures_dir / f"{image_stem}.sorted.png"
    try:
        annotated_img.save(output_image_path, format="PNG")
        print(f"[✓] Đã lưu ảnh gắn số thứ tự vào: {output_image_path}")
    except Exception as err:
        print(f"LỖI: Không thể lưu file ảnh '{output_image_path}': {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
