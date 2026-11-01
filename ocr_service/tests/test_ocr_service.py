from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
import pytest

os.environ["OCR_SKIP_STARTUP_MODEL_LOAD"] = "1"

SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from config import settings  # noqa: E402
from engine import DetectedLine, OCREngine  # noqa: E402
from main import app, set_ocr_engine_for_testing, state  # noqa: E402
from pipeline import (  # noqa: E402
    ShiftedLine,
    compute_slice_windows,
    deduplicate_overlapping_lines,
    filter_japanese_furigana,
    filter_tiny_and_watermark_lines,
    group_lines_into_blocks,
    run_ocr_page_pipeline,
)


def _make_png_bytes(width: int = 400, height: int = 600) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_reading_order_zh_ko_en_and_ja_with_furigana_filtering() -> None:
    # 1. Kiểm tra tiếng Anh (en): gom dòng ngang trong cùng bong bóng (trên -> dưới)
    #    và sắp các bong bóng trên trang (trên -> dưới, trái -> phải)
    en_lines = [
        # Bong bóng 2 (bên phải, hàng trên)
        ShiftedLine(bbox=[450, 100, 620, 130], text="Second bubble", score=0.95),
        # Bong bóng 1 (bên trái, hàng trên - gồm 2 dòng xếp dọc)
        ShiftedLine(bbox=[80, 135, 240, 165], text="world!", score=0.96),
        ShiftedLine(bbox=[80, 100, 240, 130], text="Hello", score=0.98),
        # Bong bóng 3 (hàng dưới)
        ShiftedLine(bbox=[200, 400, 420, 435], text="Bottom bubble", score=0.92),
    ]
    en_blocks = group_lines_into_blocks(en_lines, lang="en", image_height=1000)
    assert len(en_blocks) == 3
    assert [b.text for b in en_blocks] == [
        "Hello world!",
        "Second bubble",
        "Bottom bubble",
    ]
    assert [b.id for b in en_blocks] == [1, 2, 3]

    # 2. Kiểm tra cột dọc tiếng Trung (zh): các cột dọc trong cùng bong bóng phải đọc PHẢI -> TRÁI
    zh_vert_lines = [
        # Cột trái (đọc sau): x = 100..135
        ShiftedLine(bbox=[100, 200, 135, 380], text="第二列", score=0.94),
        # Cột phải (đọc trước): x = 145..180
        ShiftedLine(bbox=[145, 200, 180, 380], text="第一列", score=0.97),
    ]
    zh_blocks = group_lines_into_blocks(zh_vert_lines, lang="zh", image_height=1000)
    assert len(zh_blocks) == 1
    assert zh_blocks[0].text == "第一列第二列"

    # 3. Kiểm tra tiếng Nhật (ja): lọc furigana (dòng dọc hẹp nằm sát cột chính)
    #    và sắp thứ tự bong bóng trên trang từ PHẢI sang TRÁI
    ja_raw_lines = [
        # Bong bóng bên phải (đọc trước trong manga Nhật):
        # Cột kanji phải (rộng 36px): x = 640..676
        ShiftedLine(bbox=[640, 100, 676, 300], text="俺は", score=0.96),
        # Dòng furigana hẹp (rộng 12px < 0.62 * 36px) nằm sát bên phải cột "俺は": x = 678..690
        ShiftedLine(bbox=[678, 105, 690, 210], text="おれ", score=0.81),
        # Cột kanji trái trong cùng bong bóng phải (rộng 36px): x = 595..631
        ShiftedLine(bbox=[595, 100, 631, 300], text="行くぞ", score=0.95),
        # Bong bóng bên trái (đọc sau trong cùng hàng ngang): x = 120..160
        ShiftedLine(bbox=[120, 110, 160, 290], text="待って", score=0.93),
    ]
    ja_no_furigana = filter_japanese_furigana(ja_raw_lines)
    assert len(ja_no_furigana) == 3
    assert all(ln.text != "おれ" for ln in ja_no_furigana)

    ja_blocks = group_lines_into_blocks(ja_no_furigana, lang="ja", image_height=1000)
    assert len(ja_blocks) == 2
    assert ja_blocks[0].text == "俺は行くぞ"
    assert ja_blocks[1].text == "待って"


def test_vertical_tiling_overlap_deduplication_and_noise_filtering() -> None:
    # Ảnh cao 3000px (> 1500px) -> cắt lát cao 1400px, chồng lấn 150px
    # Lát 0: 0..1400, Lát 1: 1250..2650, Lát 2: 2500..3000
    windows = compute_slice_windows(
        image_height=3000,
        threshold_px=1500,
        chunk_height_px=1400,
        overlap_px=150,
    )
    assert windows == [(0, 1400), (1250, 2650), (2500, 3000)]

    class OverlapMockEngine(OCREngine):
        def __init__(self) -> None:
            self.call_idx = 0

        def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
            idx = self.call_idx
            self.call_idx += 1
            if idx == 0:
                # Lát 0 (y_offset = 0):
                # - 1 dòng ở y=1300..1350 (nằm đúng vùng chồng lấn 1250..1400, bị cắt hơi ngắn chữ)
                # - 1 dòng thật nhưng điểm thấp (score = 0.38 < 0.60) -> phải giữ lại và gắn cờ low_confidence
                return [
                    DetectedLine(bbox=[100, 200, 280, 240], text="低分真话", score=0.38),
                    DetectedLine(bbox=[150, 1300, 360, 1345], text="重叠区完整台", score=0.88),
                ]
            if idx == 1:
                # Lát 1 (y_offset = 1250):
                # - Cùng dòng ở vùng chồng lấn (y cục bộ = 50..100 -> y toàn cục = 1300..1350), bản đầy đủ chữ
                # - 1 khung quá nhỏ (4x4 px) -> phải bị lọc bỏ
                # - 1 ký tự đơn lẻ cô lập ("|") -> phải bị lọc bỏ
                return [
                    DetectedLine(bbox=[150, 50, 365, 100], text="重叠区完整台词", score=0.95),
                    DetectedLine(bbox=[50, 400, 54, 404], text="..", score=0.90),
                    DetectedLine(bbox=[500, 600, 520, 630], text="|", score=0.75),
                ]
            # Lát 2 (y_offset = 2500):
            # - 1 watermark sát mép dưới ảnh (y cục bộ = 470..495 -> y toàn cục = 2970..2995 trên ảnh cao 3000)
            return [
                DetectedLine(bbox=[600, 470, 790, 495], text="baozimh.com", score=0.99),
            ]

    img = Image.new("RGB", (800, 3000), color=(255, 255, 255))
    blocks, stats = run_ocr_page_pipeline(img, lang="zh", engine=OverlapMockEngine())

    assert stats["slice_count"] == 3
    # Kết quả chỉ còn đúng 2 khối thật: dòng điểm thấp (có cờ low_confidence) và dòng ở vùng chồng lấn đã hợp nhất
    assert len(blocks) == 2
    assert blocks[0]["text"] == "低分真话"
    assert "low_confidence" in blocks[0]["flags"]

    assert blocks[1]["text"] == "重叠区完整台词"
    assert blocks[1]["bbox"] == [150, 1300, 365, 1350]


@pytest.mark.asyncio
async def test_health_and_secret_header_authentication() -> None:
    class DummyEngine(OCREngine):
        def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
            return [DetectedLine(bbox=[20, 20, 180, 60], text="Hello test", score=0.99)]

    set_ocr_engine_for_testing(DummyEngine())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. /health hoạt động không cần secret
        res_health = await client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json()["status"] == "ok"

        # 2. Thiếu header X-Internal-Secret -> trả 401
        png_bytes = _make_png_bytes()
        res_no_auth = await client.post(
            "/v1/ocr-page",
            data={"lang": "en"},
            files={"image": ("page.png", png_bytes, "image/png")},
        )
        assert res_no_auth.status_code == 401

        # 3. Sai header X-Internal-Secret -> trả 401
        res_bad_auth = await client.post(
            "/v1/ocr-page",
            headers={"X-Internal-Secret": "wrong-secret"},
            data={"lang": "en"},
            files={"image": ("page.png", png_bytes, "image/png")},
        )
        assert res_bad_auth.status_code == 401


@pytest.mark.asyncio
async def test_input_validation_content_type_file_size_and_max_pixels(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyEngine(OCREngine):
        def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
            return []

    set_ocr_engine_for_testing(DummyEngine())
    headers = {"X-Internal-Secret": settings.OCR_INTERNAL_SECRET}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Sai content-type -> bị từ chối (415)
        res_bad_type = await client.post(
            "/v1/ocr-page",
            headers=headers,
            data={"lang": "zh"},
            files={"image": ("note.txt", b"not an image", "text/plain")},
        )
        assert res_bad_type.status_code == 415

        # 2. File quá lớn -> bị từ chối (413)
        monkeypatch.setattr(settings, "MAX_FILE_BYTES", 200)
        large_png = _make_png_bytes(400, 400)
        assert len(large_png) > 200
        res_too_large = await client.post(
            "/v1/ocr-page",
            headers=headers,
            data={"lang": "zh"},
            files={"image": ("large.png", large_png, "image/png")},
        )
        assert res_too_large.status_code == 413

        # 3. Ảnh quá nhiều pixel (decompression bomb) -> bị từ chối (413)
        monkeypatch.setattr(settings, "MAX_FILE_BYTES", 10 * 1024 * 1024)
        monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 10_000)  # Giới hạn 10.000 px
        bomb_png = _make_png_bytes(200, 200)  # 40.000 px > 10.000 px
        res_too_many_pixels = await client.post(
            "/v1/ocr-page",
            headers=headers,
            data={"lang": "zh"},
            files={"image": ("bomb.png", bomb_png, "image/png")},
        )
        assert res_too_many_pixels.status_code == 413


@pytest.mark.asyncio
async def test_semaphore_concurrency_limit_and_no_disk_writes() -> None:
    class SlowMockEngine(OCREngine):
        def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
            time.sleep(0.06)
            return [DetectedLine(bbox=[30, 40, 220, 90], text="并发测试成功", score=0.95)]

    # Đặt giới hạn Semaphore = 2 tác vụ đồng thời
    set_ocr_engine_for_testing(SlowMockEngine(), max_concurrent=2)
    headers = {"X-Internal-Secret": settings.OCR_INTERNAL_SECRET}
    png_bytes = _make_png_bytes(300, 400)

    temp_dir = Path(tempfile.gettempdir())
    before_temp_files = set(os.listdir(temp_dir))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        tasks = [
            client.post(
                "/v1/ocr-page",
                headers=headers,
                data={"lang": "zh"},
                files={"image": (f"page_{i}.png", png_bytes, "image/png")},
            )
            for i in range(6)
        ]
        responses = await asyncio.gather(*tasks)

    after_temp_files = set(os.listdir(temp_dir))

    for resp in responses:
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["text"] == "并发测试成功"

    # Kiểm tra số tác vụ chạy đồng thời thực tế không bao giờ vượt quá Semaphore (2)
    assert 1 <= state.peak_concurrent_workers <= 2
    # Kiểm tra không có file ảnh nào bị ghi ra thư mục tạm trên đĩa
    assert after_temp_files == before_temp_files


@pytest.mark.asyncio
async def test_timeout_returns_504(monkeypatch: pytest.MonkeyPatch) -> None:
    class HangingMockEngine(OCREngine):
        def detect_and_recognize(self, image_rgb: Image.Image, lang: str) -> list[DetectedLine]:
            time.sleep(0.25)
            return []

    set_ocr_engine_for_testing(HangingMockEngine(), max_concurrent=2)
    monkeypatch.setattr(settings, "OCR_TIMEOUT_SECONDS", 0.05)

    headers = {"X-Internal-Secret": settings.OCR_INTERNAL_SECRET}
    png_bytes = _make_png_bytes(200, 200)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/v1/ocr-page",
            headers=headers,
            data={"lang": "en"},
            files={"image": ("slow.png", png_bytes, "image/png")},
        )
        assert resp.status_code == 504


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slow_real_paddleocr_engine_on_small_image() -> None:
    """Test tích hợp đánh dấu 'slow' chạy PaddleOCREngine thật (PP-OCRv5_mobile) trên ảnh nhỏ."""
    from engine import PaddleOCREngine

    real_engine = PaddleOCREngine(preload_langs=("en",))
    set_ocr_engine_for_testing(real_engine, max_concurrent=1)

    img = Image.new("RGB", (360, 120), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((40, 45), "HELLO WORLD", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    headers = {"X-Internal-Secret": settings.OCR_INTERNAL_SECRET}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/v1/ocr-page",
            headers=headers,
            data={"lang": "en"},
            files={"image": ("real_small.png", buf.getvalue(), "image/png")},
        )
        assert resp.status_code == 200
        blocks: list[dict[str, Any]] = resp.json()
        assert isinstance(blocks, list)
