from __future__ import annotations

import json
import re
from typing import Any
import httpx

from config import settings


class LLMTranslationError(Exception):
    """Lỗi khi gọi dịch vụ LLM (Gemini / DeepSeek)."""


def build_comic_translation_prompt(
    blocks: list[dict[str, Any]],
    lang_pair: str,
    context: dict[str, Any] | None = None,
    reading_direction: str = "rtl",
) -> str:
    """
    Xây dựng prompt dịch truyện tranh sang tiếng Việt:
    - Kế thừa toàn bộ ngữ cảnh: series_title, custom_context, glossary, previous_lines.
    - Hướng dẫn LLM nắm bắt thứ tự đọc tự nhiên (RTL hoặc LTR), giữ mạch câu thoại giữa các bóng kề nhau.
    - Yêu cầu tự khắc phục lỗi chính tả OCR dựa theo ngữ cảnh, bảo toàn cảm xúc và văn phong truyện tranh.
    - Chỉ trả về JSON thuần định dạng {"translations": [{"id": ..., "translation": "..."}]} không kèm giải thích.
    """
    ctx = context or {}
    series_title = str(ctx.get("series_title") or "Không rõ").strip()
    glossary = ctx.get("glossary") or {}
    previous_lines = ctx.get("previous_lines") or []
    custom_context = str(ctx.get("custom_context") or "").strip()

    source_lang_name = (
        "tiếng Trung (Manhua)"
        if lang_pair.lower().startswith("zh")
        else "tiếng Anh (Webtoon/Manhwa/Comic)"
    )

    glossary_str = (
        json.dumps(glossary, ensure_ascii=False)
        if glossary
        else "Không có bảng thuật ngữ riêng"
    )
    prev_str = (
        json.dumps(previous_lines[-10:], ensure_ascii=False)
        if previous_lines
        else "Không có thoại trang trước"
    )
    custom_ctx_str = (
        f"- Bối cảnh bổ sung & Lưu ý xưng hô: {custom_context}\n"
        if custom_context
        else ""
    )

    direction_val = (reading_direction or "rtl").strip().lower()
    direction_desc = (
        "từ Phải sang Trái (RTL - Manga Nhật Bản / Manhua)"
        if direction_val == "rtl"
        else "từ Trái sang Phải (LTR - Manhwa Hàn Quốc / Webtoon)"
    )

    input_items = [
        {"id": int(b["id"]), "source_text": str(b.get("text") or b.get("source_text") or "")}
        for b in blocks
    ]

    return (
        f"Bạn là biên dịch viên truyện tranh chuyên nghiệp dịch từ {source_lang_name} sang tiếng Việt.\n"
        f"- Tên bộ truyện: {series_title}\n"
        f"{custom_ctx_str}"
        f"- Bảng thuật ngữ / xưng hô (Glossary): {glossary_str}\n"
        f"- Các câu thoại liền trước để giữ mạch xưng hô: {prev_str}\n\n"
        f"ĐẶC ĐIỂM THỨ TỰ ĐỌC:\n"
        f"Danh sách các khối chữ dưới đây đã được sắp xếp đúng theo THỨ TỰ ĐỌC TỰ NHIÊN: {direction_desc}.\n"
        "Rất nhiều câu thoại dài bị tác giả chia cắt ra 2 hoặc nhiều bóng thoại liền kề nhau "
        "(ví dụ bóng trước là 'Con cứ...' và bóng sau nối tiếp là '...đi lấy chồng đi').\n"
        "Hãy nắm bắt mạch ngữ cảnh liên tục giữa các đoạn để dịch tự nhiên, đúng văn phong hội thoại đời thường, "
        "tuyệt đối không dịch cụt lủn hay ngắt đôi ngữ nghĩa vô lý.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. Giữ nhất quán đại từ nhân xưng (tôi/cậu, anh/em, ta/ngươi, hắn/nàng...) xuyên suốt trang, phù hợp với ngữ cảnh hội thoại.\n"
        "2. Tự động sửa chữa các lỗi chính tả do OCR quét nhận diện sai nét chữ Hán/ký tự nếu phát hiện từ vô lý.\n"
        "3. Câu dịch ngắn gọn, tự nhiên để vừa khung bóng thoại, giữ nguyên sắc thái cảm thán (!, ?, ...).\n"
        "4. Dịch ĐẦY ĐỦ tất cả các phần tử trong danh sách đầu vào, giữ nguyên chính xác `id` gốc của từng khối.\n"
        "5. CHỈ TRẢ VỀ DUY NHẤT MỘT JSON OBJECT HỢP LỆ theo mẫu:\n"
        '{"translations": [{"id": 0, "translation": "câu dịch 1"}, {"id": 1, "translation": "câu dịch 2"}]}\n'
        "Tuyệt đối không thêm lời giải thích hay ký hiệu markdown nào ngoài JSON.\n\n"
        f"DANH SÁCH KHỐI CHỮ CẦN DỊCH (ĐÚNG THỨ TỰ ĐỌC):\n{json.dumps(input_items, ensure_ascii=False)}"
    )


def parse_llm_translation_output(
    raw_text: str,
    original_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Phân tích chuỗi JSON trả về từ LLM một cách an toàn:
    - Tự động bóc tách khối markdown ```json ... ``` hoặc tìm cặp `{...}` / `[...]` đầu tiên.
    - Nếu LLM trả thiếu hoặc thừa khối, hoặc JSON bị hỏng một phần, ghép theo `id` (hoặc vị trí)
      và dùng `source_text` làm giá trị dự phòng cho các khối bị thiếu để không làm hỏng toàn trang.
    """
    cleaned = (raw_text or "").strip()

    # Bóc tách ```json ... ``` nếu có
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    parsed_data: Any = None
    try:
        parsed_data = json.loads(cleaned)
    except Exception:
        # Thử tìm object {...} hoặc array [...] trong chuỗi
        obj_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
        if obj_match:
            try:
                parsed_data = json.loads(obj_match.group(1))
            except Exception:
                parsed_data = None

    items_list: list[Any] = []
    if isinstance(parsed_data, dict):
        if isinstance(parsed_data.get("translations"), list):
            items_list = parsed_data["translations"]
        elif isinstance(parsed_data.get("blocks"), list):
            items_list = parsed_data["blocks"]
    elif isinstance(parsed_data, list):
        items_list = parsed_data

    by_id: dict[int, str] = {}
    positional: list[str] = []

    for item in items_list:
        if isinstance(item, dict):
            trans_val = str(
                item.get("translation")
                or item.get("translated_text")
                or item.get("text")
                or ""
            ).strip()
            if trans_val:
                positional.append(trans_val)
                if "id" in item:
                    try:
                        by_id[int(item["id"])] = trans_val
                    except (ValueError, TypeError):
                        pass
        elif isinstance(item, str) and item.strip():
            positional.append(item.strip())

    merged_blocks: list[dict[str, Any]] = []
    for idx, orig in enumerate(original_blocks):
        block_id = int(orig.get("id", idx))
        source_text = str(orig.get("text") or orig.get("source_text") or "").strip()
        bbox = list(orig.get("bbox") or [0, 0, 0, 0])

        translated = by_id.get(block_id)
        if not translated and idx < len(positional) and len(by_id) == 0:
            translated = positional[idx]
        if not translated:
            # Fallback an toàn về source_text nếu LLM bỏ sót khối
            translated = source_text

        merged_blocks.append(
            {
                "id": block_id,
                "bbox": bbox,
                "source_text": source_text,
                "translation": translated,
            }
        )

    return merged_blocks


async def translate_blocks_with_llm(
    blocks: list[dict[str, Any]],
    lang_pair: str,
    context: dict[str, Any] | None = None,
    reading_direction: str = "rtl",
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """
    Gửi toàn bộ các khối chữ của 1 trang truyện sang Gemini (hoặc DeepSeek) trong 1 lần gọi:
    - Nhận diện thứ tự đọc (RTL hoặc LTR) để LLM dịch liền mạch theo ngữ cảnh.
    - Cấu hình max_output_tokens=2048 và temperature=0.2 để phản hồi mượt mà, không bị ngắt JSON giữa chừng.
    """
    if not blocks:
        return []

    prompt = build_comic_translation_prompt(
        blocks,
        lang_pair=lang_pair,
        context=context,
        reading_direction=reading_direction,
    )
    provider = (settings.LLM_PROVIDER or "gemini").strip().lower()

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS)

    try:
        if provider == "deepseek":
            url = f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.DEEPSEEK_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "Bạn là dịch giả truyện tranh Việt Nam, chỉ trả lời bằng JSON hợp lệ.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
                "response_format": {"type": "json_object"},
            }
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise LLMTranslationError(f"DeepSeek trả mã lỗi HTTP {resp.status_code}")
            data = resp.json()
            raw_text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return parse_llm_translation_output(raw_text, blocks)

        # Mặc định: Google Gemini REST API v1beta chuẩn với key trên URL query
        raw_model = (settings.GEMINI_MODEL or "gemini-1.5-flash").strip()
        model_name = raw_model[len("models/"):] if raw_model.startswith("models/") else raw_model

        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
        )
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": settings.GEMINI_API_KEY or "missing-gemini-key",
        }
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }
        resp = await client.post(gemini_url, json=payload, headers=headers)
        if resp.status_code == 404:
            # Dự phòng: Nếu model cấu hình (ví dụ gemini-1.5-flash / gemini-2.5-flash)
            # bị Google khai tử trên API v1beta, tự động fallback sang model Flash đang hoạt động
            for fallback_model in ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"]:
                if fallback_model == model_name:
                    continue
                fallback_url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{fallback_model}:generateContent?key={settings.GEMINI_API_KEY}"
                )
                fallback_resp = await client.post(fallback_url, json=payload, headers=headers)
                if fallback_resp.status_code == 200:
                    resp = fallback_resp
                    break

        if resp.status_code != 200:
            raise LLMTranslationError(f"Gemini trả mã lỗi HTTP {resp.status_code}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMTranslationError("Gemini không trả về candidates nào.")
        parts = candidates[0].get("content", {}).get("parts") or []
        raw_text = "".join(str(p.get("text") or "") for p in parts)
        return parse_llm_translation_output(raw_text, blocks)
    finally:
        if owns_client:
            await client.aclose()
