#!/usr/bin/env python3
"""
scripts/debug_page.py

Script chẩn đoán OCR, hậu xử lý và thứ tự đọc trang truyện:
1. Nhận đường dẫn ảnh, --lang (zh|en|ko|ja), --direction (ltr|rtl).
2. Đọc cấu hình OCR_SERVICE_URL và OCR_INTERNAL_SECRET từ settings của server.
3. Gửi ảnh đến call_ocr_service và lưu raw response vào fixtures/<tên ảnh>.ocr.json.
4. Chuẩn hóa normalize_text, phân loại split_blocks (dialogue, edge_strips, ignored).
5. Sắp xếp thứ tự đọc cho dialogue, đặt edge_strips lên trước, gán lại id 0..n-1.
6. In bảng thứ tự kết hợp cột kind, in danh sách ignored kèm reason.
7. Vẽ bbox và số thứ tự sắp xếp bằng Pillow, lưu fixtures/<tên ảnh>.sorted.png.
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
    from ocr_postprocess import normalize_text, split_blocks
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
        description="Chẩn đoán OCR, hậu xử lý và kiểm tra thứ tự đọc của trang truyện tranh."
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
        help="Hướng đọc: 'rtl' (Phải -> Trái cho Manga Nhật) hoặc 'ltr' (Trái -> Phải cho Webtoon/Manhwa). Mặc định: rtl",
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
            img_w, img_h = img.size
            if img.mode in ("P", "RGBA", "LA"):
                annotated_img = img.convert("RGBA").convert("RGB")
            else:
                annotated_img = img.convert("RGB")
    except Exception as err:
        print(f"LỖI: Không thể mở file ảnh '{image_file}': {err}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Đang gửi ảnh '{image_file.name}' ({img_w}x{img_h}) tới OCR service ({settings.OCR_SERVICE_URL})...")
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

    print(f"[*] Tổng số khối văn bản nhận được từ OCR: {len(blocks)}")

    # 2. Chuẩn hóa normalize_text
    for block in blocks:
        normalize_text(block)

    # 3. Phân tách split_blocks: dialogue, edge_strips, ignored
    dialogue, edge_strips, ignored = split_blocks(blocks, img_w=img_w, img_h=img_h)

    # 4. Sắp xếp thứ tự đọc cho dialogue
    sorted_dialogue = sort_blocks_by_reading_order(dialogue, reading_direction=args.direction)

    # Sắp xếp edge_strips từ trên xuống dưới
    sorted_edge_strips = sorted(edge_strips, key=lambda b: extract_bbox(b)[1])

    # Danh sách cuối cùng: edge_strips (đặt trước) + dialogue đã sort
    final_blocks = sorted_edge_strips + sorted_dialogue

    # Gán lại id = 0..n-1 theo thứ tự cuối cùng
    for new_id, block in enumerate(final_blocks):
        block["id"] = new_id

    # 5. In bảng kết quả thứ tự đọc + cột Kind
    print("\n" + "=" * 102)
    print(f"{'Thứ tự mới':<11} | {'ID':<6} | {'Kind':<10} | {'Bounding Box [x1, y1, x2, y2]':<32} | {'30 ký tự đầu của text'}")
    print("-" * 102)
    for idx, block in enumerate(final_blocks, start=1):
        block_id = str(block.get("id", "-"))
        kind = str(block.get("kind", "-"))
        bbox = extract_bbox(block)
        bbox_str = f"[{int(round(bbox[0]))}, {int(round(bbox[1]))}, {int(round(bbox[2]))}, {int(round(bbox[3]))}]"
        raw_text = str(block.get("text", "")).replace("\r", " ").replace("\n", " ").strip()
        preview_text = raw_text[:30]
        print(f"{idx:<11} | {block_id:<6} | {kind:<10} | {bbox_str:<32} | {preview_text}")
    print("=" * 102 + "\n")

    # 6. In danh sách ignored kèm reason
    if ignored:
        print(f"[*] Danh sách khối bị bỏ qua (ignored - {len(ignored)} khối):")
        print("-" * 92)
        print(f"{'ID gốc':<8} | {'Lý do (Reason)':<30} | {'30 ký tự đầu của text'}")
        print("-" * 92)
        for item in ignored:
            b_id = str(item.get("id", "-"))
            reason = str(item.get("reason", "-"))
            txt = str(item.get("text", "")).replace("\r", " ").replace("\n", " ").strip()
            print(f"{b_id:<8} | {reason:<30} | {txt[:30]}")
        print("-" * 92 + "\n")
    else:
        print("[*] Không có khối nào bị bỏ qua (ignored: 0 khối).\n")

    # 7. Vẽ bbox và số thứ tự sắp xếp lên ảnh bằng Pillow
    draw = ImageDraw.Draw(annotated_img)
    font_size = max(24, min(56, int(annotated_img.width * 0.032)))
    font = get_prominent_font(font_size)

    # Vẽ các khối ignored (màu xám mờ để dễ phân biệt khi debug)
    for item in ignored:
        bbox = extract_bbox(item)
        x1, y1, x2, y2 = [int(round(c)) for c in bbox]
        draw.rectangle([x1, y1, x2, y2], outline=(150, 150, 150), width=2)
        ign_tb = draw.textbbox((0, 0), "IGN", font=font)
        ign_w = ign_tb[2] - ign_tb[0]
        ign_h = ign_tb[3] - ign_tb[1]
        draw.rectangle([x1, max(0, y1 - ign_h - 4), x1 + ign_w + 8, max(0, y1 - ign_h - 4) + ign_h + 4], fill=(120, 120, 120))
        draw.text((x1 + 4 - ign_tb[0], max(0, y1 - ign_h - 4) + 2 - ign_tb[1]), "IGN", fill=(255, 255, 255), font=font)

    # Vẽ các khối final_blocks (edge_strips + dialogue)
    for idx, block in enumerate(final_blocks, start=1):
        bbox = extract_bbox(block)
        x1, y1, x2, y2 = [int(round(c)) for c in bbox]
        kind = block.get("kind", "dialogue")

        # Phân biệt màu sắc: Title (cam) và Dialogue (đỏ nổi bật)
        if kind == "title":
            outline_color = (255, 140, 0)
            badge_fill = (220, 110, 0)
            label_text = f"#{block['id']} [T]"
        else:
            outline_color = (255, 30, 30)
            badge_fill = (220, 20, 20)
            label_text = f"#{block['id']}"

        draw.rectangle([x1, y1, x2, y2], outline=outline_color, width=3)

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

        # Nền badge và viền trắng
        draw.rectangle([bx1, by1, bx2, by2], fill=badge_fill, outline=(255, 255, 255), width=2)
        # Chữ số thứ tự màu trắng
        text_x = bx1 + pad - tb[0]
        text_y = by1 + pad - tb[1]
        draw.text((text_x, text_y), label_text, fill=(255, 255, 255), font=font)

    # Lưu fixtures/<tên ảnh>.sorted.png
    output_image_path = fixtures_dir / f"{image_stem}.sorted.png"
    try:
        annotated_img.save(output_image_path, format="PNG")
        print(f"[✓] Đã lưu ảnh gắn số thứ tự vào: {output_image_path}")
    except Exception as err:
        print(f"LỖI: Không thể lưu file ảnh '{output_image_path}': {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
