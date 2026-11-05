from __future__ import annotations

import io
import base64
import json
from typing import Any
import pytest
from PIL import Image
import httpx

from bubble_detector import containment_nms, filter_speckle, BubbleDetector, select_bubbles_and_uncovered_text


def test_bubble_does_not_discard_other_dialogue_above_or_below():
    bubble = [100, 400, 400, 700, .95]
    inner_text = [150, 450, 350, 650, .90]
    above = [50, 50, 200, 150, .90]
    below = [100, 900, 350, 1000, .85]
    result = select_bubbles_and_uncovered_text([bubble], [inner_text, above, below])
    assert result == [bubble, above, below]
    assert select_bubbles_and_uncovered_text([], [above, below]) == [above, below]
from annotator import draw_numbered_bboxes
from translator import translate_page_multimodal_gemini


def test_containment_nms_suppression():
    # Box 1 to: [0, 0, 100, 100], diện tích 10000, conf 0.95
    # Box 2 con: [10, 10, 90, 90], diện tích 6400 nằm trọn trong Box 1 (100% containment), conf 0.80
    boxes = [
        [0.0, 0.0, 100.0, 100.0, 0.95],
        [10.0, 10.0, 90.0, 90.0, 0.80],
    ]
    kept = containment_nms(boxes, threshold=0.85)
    assert len(kept) == 1
    assert kept[0][4] == 0.95


def test_filter_speckle_drops_small_noise():
    # Giả lập 5 box bình thường và 1 đốm nhiễu siêu nhỏ có conf thấp
    boxes = [
        [0.0, 0.0, 100.0, 100.0, 0.90],
        [0.0, 150.0, 100.0, 250.0, 0.90],
        [0.0, 300.0, 100.0, 400.0, 0.90],
        [0.0, 450.0, 100.0, 550.0, 0.90],
        [0.0, 600.0, 100.0, 700.0, 0.90],
        [50.0, 50.0, 52.0, 52.0, 0.40],  # Speckle 2x2 = 4 diện tích (< 15% của 10000)
    ]
    kept = filter_speckle(boxes, page_h=1000.0)
    assert len(kept) == 5


def test_annotator_draw_numbered_bboxes():
    img = Image.new("RGB", (1200, 1800), color=(255, 255, 255))
    boxes = [
        {"id": 0, "bbox": [100, 100, 300, 400]},
        {"id": 1, "bbox": [400, 500, 600, 700]},
    ]
    b64 = draw_numbered_bboxes(img, boxes, max_dim=1024, quality=75)
    assert isinstance(b64, str)
    assert len(b64) > 100

    raw_jpeg = base64.b64decode(b64)
    with Image.open(io.BytesIO(raw_jpeg)) as annotated_img:
        assert max(annotated_img.size) <= 1024
        assert annotated_img.format == "JPEG"


@pytest.mark.asyncio
async def test_multimodal_self_healing_validator():
    img = Image.new("RGB", (400, 600), color=(255, 255, 255))
    boxes = [
        {"id": 0, "bbox": [50, 50, 150, 150]},
        {"id": 1, "bbox": [50, 200, 150, 300]},
        {"id": 2, "bbox": [50, 350, 150, 450]},
    ]

    # Mock Gemini chỉ trả về 2 phần tử (thiếu 1 phần tử)
    mock_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "translations": ["Câu 1", "Câu 2"],
                                "sourceTexts": ["Gốc 1", "Gốc 2"],
                            })
                        }
                    ]
                }
            }
        ]
    }

    def _handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        results = await translate_page_multimodal_gemini(
            image=img,
            detected_boxes=boxes,
            lang_pair="zh-vi",
            http_client=client,
        )

    # Đảm bảo validator tự vá để đủ 3 phần tử theo đúng boxes
    assert len(results) == 3
    assert results[0]["translation"] == "Câu 1"
    assert results[1]["translation"] == "Câu 2"
    assert results[2]["translation"] == ""  # Tự vá slot thứ 3
    assert results[0]["id"] == 0
    assert results[1]["id"] == 1
    assert results[2]["id"] == 2

