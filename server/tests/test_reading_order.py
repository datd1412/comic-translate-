from __future__ import annotations

import pytest
from reading_order import extract_bbox, sort_blocks_by_reading_order
from translator import parse_llm_translation_output


def test_reading_order_rtl_and_ltr():
    block_a = {
        "id": 101,
        "bbox": [800, 100, 860, 140],
        "text": "去结婚吧",
    }
    block_b = {
        "id": 102,
        "bbox": [950, 105, 1010, 145],
        "text": "你就",
    }

    # RTL: B (bên phải, x=950) phải đứng TRƯỚC A (bên trái, x=800)
    rtl_sorted = sort_blocks_by_reading_order([block_a, block_b], reading_direction="rtl")
    assert len(rtl_sorted) == 2
    assert rtl_sorted[0]["id"] == 102
    assert rtl_sorted[1]["id"] == 101
    assert rtl_sorted[0]["text"] == "你就"
    assert rtl_sorted[1]["text"] == "去结婚吧"

    # LTR: A (bên trái, x=800) phải đứng TRƯỚC B (bên phải, x=950)
    ltr_sorted = sort_blocks_by_reading_order([block_a, block_b], reading_direction="ltr")
    assert len(ltr_sorted) == 2
    assert ltr_sorted[0]["id"] == 101
    assert ltr_sorted[1]["id"] == 102
    assert ltr_sorted[0]["text"] == "去结婚吧"
    assert ltr_sorted[1]["text"] == "你就"


def test_reading_order_vertical_separation():
    # 2 block ở 2 tầng khác nhau không bị gom cụm nhầm
    top_block = {"id": 1, "bbox": [100, 50, 200, 90], "text": "Hàng trên"}
    bottom_block = {"id": 2, "bbox": [100, 300, 200, 340], "text": "Hàng dưới"}

    sorted_blocks = sort_blocks_by_reading_order([bottom_block, top_block], reading_direction="rtl")
    assert [b["id"] for b in sorted_blocks] == [1, 2]


def test_reading_order_mock_translation_id_mapping():
    """
    Kiểm tra khả năng ánh xạ đúng 100% ID sau khi dịch giả lập (mock LLM response).
    Dù danh sách gửi vào LLM theo thứ tự RTL (B trước, A sau),
    kết quả trả về vẫn gắn chuẩn xác bản dịch vào đúng block ID gốc.
    """
    block_a = {"id": 101, "bbox": [800, 100, 860, 140], "text": "去结婚吧"}
    block_b = {"id": 102, "bbox": [950, 105, 1010, 145], "text": "你就"}

    # Thứ tự đọc RTL: B trước, A sau
    sorted_blocks = sort_blocks_by_reading_order([block_a, block_b], reading_direction="rtl")

    # Giả lập LLM hiểu ngữ cảnh liền mạch và trả về JSON có kèm ID:
    mock_llm_json = """
    {
        "translations": [
            {"id": 102, "translation": "Con cứ"},
            {"id": 101, "translation": "đi kết hôn đi!"}
        ]
    }
    """

    merged = parse_llm_translation_output(mock_llm_json, sorted_blocks)
    assert len(merged) == 2

    by_id = {b["id"]: b["translation"] for b in merged}
    assert by_id[102] == "Con cứ"
    assert by_id[101] == "đi kết hôn đi!"

