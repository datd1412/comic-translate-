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
    - Kế thừa toàn bộ ngữ cảnh: series_title, custom_context (preset thể loại/xưng hô), glossary, previous_lines.
    - Hướng dẫn LLM nắm bắt thứ tự đọc tự nhiên (RTL hoặc LTR), giữ mạch câu thoại giữa các bóng kề nhau.
    - Khôi phục tên riêng phương Tây (Back-transliteration): Wolfgang, Amelia, Mozart... thay vì âm Hán-Việt thô kệch.
    - Khắc phục câu bị ngắt vụn qua nhiều bóng thoại (Sentence fragmentation).
    - Văn phong tự nhiên, giàu biểu cảm, tự dọn rác OCR ở đầu/cuối bóng thoại (dấu phẩy, đuôi bóng).
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
    if previous_lines:
        prev_lines_formatted = []
        for line in previous_lines[-8:]:
            if isinstance(line, dict):
                src = str(line.get("source_text") or line.get("text") or "").strip()
                trans = str(line.get("translation") or "").strip()
                if src and trans:
                    prev_lines_formatted.append(f'  + Gốc: "{src}" -> Dịch: "{trans}"')
                elif trans:
                    prev_lines_formatted.append(f'  + Dịch: "{trans}"')
                elif src:
                    prev_lines_formatted.append(f'  + "{src}"')
            elif isinstance(line, str) and line.strip():
                prev_lines_formatted.append(f'  + {line.strip()}')
        prev_str = "\n".join(prev_lines_formatted) if prev_lines_formatted else "Không có thoại trang trước"
    else:
        prev_str = "Không có thoại trang trước"

    custom_ctx_str = (
        f"- Bối cảnh truyện / Thể loại / Quy tắc xưng hô: {custom_context}\n"
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
        f"Bạn là dịch giả truyện tranh Việt Nam xuất sắc, chuyển ngữ từ {source_lang_name} sang tiếng Việt sống động, mượt mà và tự nhiên.\n"
        f"- Tên bộ truyện: {series_title}\n"
        f"{custom_ctx_str}"
        f"- Bảng thuật ngữ / xưng hô (Glossary): {glossary_str}\n"
        f"- CÁC CÂU THOẠI TRANG TRƯỚC (RẤT QUAN TRỌNG ĐỂ KẾ THỪA MẠCH TRUYỆN & XƯNG HÔ):\n{prev_str}\n\n"
        f"THỨ TỰ ĐỌC TỰ NHIÊN:\n"
        f"Các khối chữ bên dưới đã được sắp xếp theo đúng thứ tự đọc: {direction_desc}.\n\n"
        "QUY TẮC DỊCH BẮT BUỘC:\n"
        "1. KẾ THỪA NGỮ CẢNH TỪ TRANG TRƯỚC (NẾU CÓ):\n"
        "   Sử dụng mạch truyện và đại từ nhân xưng (tôi/cậu, anh/em, ta/ngươi...) đã dùng ở trang trước để đảm bảo tính liên tục, không bị nhảy xưng hô vô lý.\n"
        "2. KHÔI PHỤC TÊN RIÊNG PHƯƠNG TÂY (BACK-TRANSLITERATION):\n"
        "   Khi gặp tên nhân vật hoặc địa danh phương Tây được phiên âm sang chữ Hán (ví dụ: 阿梅莉亚 -> Amelia, 沃尔冈夫 -> Wolfgang, 莫扎特 -> Mozart, 玛利亚 -> Maria, 伦敦 -> London, 约翰 -> John), "
        "BẮT BUỘC khôi phục về tên gốc Latin chuẩn quốc tế. TUYỆT ĐỐI KHÔNG dịch theo âm Hán-Việt thô kệch (như A-mai-lợi-á, Oát-nhĩ-cương-phu).\n"
        "3. LIÊN KẾT CÂU BỊ TÁCH BÓNG THOẠI (SENTENCE FRAGMENTATION):\n"
        "   Nhiều câu thoại dài bị chia cắt thành 2 hoặc nhiều bóng thoại liên tiếp. Hãy xem xét tổng thể để hiểu trọn vẹn mạch ý, "
        "sau đó phân bổ bản dịch tiếng Việt vào từng id tương ứng sao cho tự nhiên, câu từ mạch lạc, không ngắt cụt câu vô lý.\n"
        "4. NHẬN DIỆN CHỮ PHỒN THỂ & NGỮ NGHĨA TRUYỆN TRANH:\n"
        "   Văn bản có thể là chữ Hán Phồn Thể (như 鬍/鬍子 = râu/để râu, 輪迴/循環 = vòng lặp thời gian, 戲劇 = kịch...). "
        "Hãy nhận diện đúng từ vựng theo ngữ cảnh câu chuyện. Tuyệt đối không dịch sai lệch thành 'rùa', 'nhẹ nhàng' hay 'nuôi con'.\n"
        "5. XỬ LÝ CHỮ IN ÁO / NHÃN HIỆU / LOGO / ĐỐM NHIỄU (GIBBERISH & NOISE):\n"
        "   Nếu gặp chữ tiếng Anh in trên áo/đồ vật (như 'NUMBER GIRL', 'MBERGA', 'HMEESGR', 'MERGR') hoặc các ký tự rác/vô nghĩa do OCR nhận diện sai, hãy giữ nguyên chữ gốc hoặc để trống (\"\"). TUYỆT ĐỐI KHÔNG tự bịa thành câu thoại vô nghĩa (như '3 nhé', 'hoắc chạy đến') hay từ tượng thanh (SFX) vô lý.\n"
        "6. VĂN PHONG TRUYỆN TRANH TỰ NHIÊN & THOÁT Ý:\n"
        "   Dùng khẩu ngữ tiếng Việt đời thường, biểu cảm sống động theo tâm lý nhân vật (vui, buồn, tức giận, mỉa mai). "
        "Tuân thủ bối cảnh thể loại nếu có cung cấp ở trên. Tránh dịch cứng nhắc từng từ kiểu Google Dịch.\n"
        "7. TỰ ĐỘNG SỬA LỖI & DỌN RÁC OCR:\n"
        "   Tự sửa các từ bị OCR nhận diện nhầm nét chữ Hán dựa vào ngữ cảnh. "
        "Loại bỏ dấu phẩy rác (，), dấu chấm hoặc ký tự lạ ở đầu hoặc cuối câu do dính đuôi bóng thoại.\n"
        "8. GIỮ NGUYÊN ID VÀ CẤU TRÚC JSON:\n"
        "   Dịch đầy đủ mọi phần tử trong danh sách, giữ đúng `id`. CHỈ TRẢ VỀ DUY NHẤT MỘT JSON OBJECT theo mẫu:\n"
        '{"translations": [{"id": 0, "translation": "câu dịch 1"}, {"id": 1, "translation": "câu dịch 2"}]}\n'
        "Tuyệt đối không giải thích hay thêm ký hiệu markdown nào bên ngoài JSON.\n\n"
        f"DANH SÁCH KHỐI CHỮ CẦN DỊCH (THEO THỨ TỰ ĐỌC):\n{json.dumps(input_items, ensure_ascii=False)}"
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
            llm_temp = float(getattr(settings, "LLM_TEMPERATURE", 0.2))
            payload = {
                "model": settings.DEEPSEEK_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "Bạn là dịch giả truyện tranh Việt Nam, chỉ trả lời bằng JSON hợp lệ.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": llm_temp,
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
        raw_model = (settings.GEMINI_MODEL or "gemini-3.1-flash-lite").strip()
        model_name = raw_model[len("models/"):] if raw_model.startswith("models/") else raw_model

        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
        )
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": settings.GEMINI_API_KEY or "missing-gemini-key",
        }
        llm_temp = float(getattr(settings, "LLM_TEMPERATURE", 0.2))
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": llm_temp,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }
        resp = await client.post(gemini_url, json=payload, headers=headers)
        if resp.status_code == 404:
            # Dự phòng: Nếu model cấu hình bị Google khai tử trên API v1beta, tự động fallback
            for fallback_model in ["gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-flash-lite-latest", "gemini-3.8-flash"]:
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


async def translate_page_multimodal_gemini(
    image: Any,
    detected_boxes: list[dict[str, Any]],
    lang_pair: str = "zh-vi",
    context: dict[str, Any] | None = None,
    reading_direction: str = "rtl",
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """
    Dịch trang truyện tranh theo cơ chế Multimodal Vision với ô đỏ đánh số (chuẩn Libre Manga):
    1. Đóng dấu số thứ tự [1], [2], ... lên từng bóng thoại và nén JPEG 75% (~150KB).
    2. Gửi ảnh trực tiếp tới Gemini Vision để AI đồng thời đọc chữ và chuyển ngữ trong 1 lần gọi duy nhất.
    3. Tự vá lỗi (Self-Healing) đảm bảo số lượng kết quả khớp 100% với danh sách bóng thoại đầu vào.
    """
    from annotator import draw_numbered_bboxes

    if not detected_boxes:
        return []

    count = len(detected_boxes)
    annotated_b64 = draw_numbered_bboxes(image, detected_boxes, max_dim=1024, quality=75)

    ctx = context or {}
    series_title = str(ctx.get("series_title") or "Không rõ").strip()
    glossary = ctx.get("glossary") or {}
    previous_lines = ctx.get("previous_lines") or []
    custom_context = str(ctx.get("custom_context") or "").strip()

    source_lang_name = (
        "tiếng Trung (Manhua)"
        if lang_pair.lower().startswith("zh")
        else "tiếng Anh / tiếng Nhật"
    )

    glossary_str = (
        json.dumps(glossary, ensure_ascii=False)
        if glossary
        else "Không có bảng thuật ngữ riêng"
    )

    prev_lines_formatted: list[str] = []
    if previous_lines:
        for line in previous_lines[-8:]:
            if isinstance(line, dict):
                t_val = str(line.get("text") or line.get("translation") or "").strip()
                if t_val:
                    prev_lines_formatted.append(f"  + {t_val}")
            elif isinstance(line, str) and line.strip():
                prev_lines_formatted.append(f"  + {line.strip()}")
    prev_str = "\n".join(prev_lines_formatted) if prev_lines_formatted else "Không có thoại trang trước"

    custom_ctx_str = (
        f"- Bối cảnh truyện / Thể loại / Quy tắc xưng hô: {custom_context}\n"
        if custom_context
        else ""
    )

    dir_desc = "từ Phải sang Trái (RTL)" if reading_direction.lower() == "rtl" else "từ Trái sang Phải (LTR)"

    system_prompt = (
        f"Bạn là dịch giả truyện tranh Việt Nam xuất sắc, chuyển ngữ từ {source_lang_name} sang tiếng Việt sống động, mượt mà và tự nhiên.\n"
        f"- Tên bộ truyện: {series_title}\n"
        f"{custom_ctx_str}"
        f"- Bảng thuật ngữ / xưng hô: {glossary_str}\n"
        f"- CÁC CÂU THOẠI TRANG TRƯỚC (KẾ THỪA MẠCH TRUYỆN & XƯNG HÔ):\n{prev_str}\n\n"
        f"THỨ TỰ ĐỌC: Các ô thoại đã được đánh số đỏ [1], [2], ... theo thứ tự đọc {dir_desc}.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. Dịch chuẩn xác nội dung trong các ô đỏ có số thứ tự [1], [2], ... sang tiếng Việt tự nhiên, phù hợp bối cảnh nhân vật.\n"
        "2. Khôi phục tên riêng phương Tây (Amelia, Wolfgang, Mozart,...) thay vì âm Hán-Việt thô kệch.\n"
        "3. TUYỆT ĐỐI BỎ QUA bất kỳ chữ nào nằm ngoài ô đỏ (chữ in trên áo thun, logo mép tranh, watermark).\n"
        f"4. Mảng 'translations' BẮT BUỘC có ĐÚNG {count} phần tử, đúng thứ tự từ Box 1 đến Box {count}.\n"
        f"5. Mảng 'sourceTexts' BẮT BUỘC có ĐÚNG {count} phần tử, chứa chữ gốc bạn nhìn thấy trong từng ô đỏ.\n\n"
        "CHỈ TRẢ VỀ DUY NHẤT MỘT JSON OBJECT theo mẫu:\n"
        "{\n"
        '  "translations": ["câu dịch cho box 1", "câu dịch cho box 2"],\n'
        '  "sourceTexts": ["chữ gốc box 1", "chữ gốc box 2"]\n'
        "}\n"
        "Tuyệt đối không giải thích hay thêm ký hiệu markdown nào bên ngoài JSON."
    )

    user_prompt = f"Vui lòng xử lý và dịch {count} bóng thoại được đánh số đỏ [1] đến [{count}] trong trang truyện."

    raw_model = (settings.GEMINI_MODEL or "gemini-3.1-flash-lite").strip()
    model_name = raw_model[len("models/"):] if raw_model.startswith("models/") else raw_model

    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": settings.GEMINI_API_KEY or "missing-gemini-key",
    }
    llm_temp = float(getattr(settings, "LLM_TEMPERATURE", 0.3))
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": annotated_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": llm_temp,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS)
    try:
        resp = await client.post(gemini_url, json=payload, headers=headers)
        if resp.status_code == 404:
            # Fallback nếu model bị 404
            for fallback_model in ["gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-flash-lite-latest", "gemini-3.8-flash"]:
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
            raise LLMTranslationError(f"Gemini Vision trả mã lỗi HTTP {resp.status_code}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMTranslationError("Gemini Vision không trả về candidates nào.")

        parts = candidates[0].get("content", {}).get("parts") or []
        raw_text = "".join(str(p.get("text") or "") for p in parts).strip()

        # Parse JSON
        parsed_obj: dict[str, Any] = {}
        try:
            parsed_obj = json.loads(raw_text)
        except Exception:
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text, flags=re.IGNORECASE)
            if fence_match:
                try:
                    parsed_obj = json.loads(fence_match.group(1).strip())
                except Exception:
                    pass
            if not parsed_obj:
                obj_match = re.search(r"\{[\s\S]*\}", raw_text)
                if obj_match:
                    try:
                        parsed_obj = json.loads(obj_match.group(0))
                    except Exception:
                        pass

        raw_translations = parsed_obj.get("translations") if isinstance(parsed_obj, dict) else []
        raw_sources = parsed_obj.get("sourceTexts") if isinstance(parsed_obj, dict) else []

        # Chuẩn hóa danh sách chuỗi
        translations: list[str] = []
        if isinstance(raw_translations, list):
            for item in raw_translations:
                if isinstance(item, dict):
                    translations.append(str(item.get("translation") or item.get("text") or "").strip())
                else:
                    translations.append(str(item or "").strip())

        source_texts: list[str] = []
        if isinstance(raw_sources, list):
            for item in raw_sources:
                if isinstance(item, dict):
                    source_texts.append(str(item.get("source") or item.get("text") or "").strip())
                else:
                    source_texts.append(str(item or "").strip())

        # Self-Healing: Cân bằng số lượng mảng
        while len(translations) < count:
            translations.append("")
        if len(translations) > count:
            translations = translations[:count]

        while len(source_texts) < count:
            source_texts.append("")
        if len(source_texts) > count:
            source_texts = source_texts[:count]

        # Ghép thành cấu trúc blocks chuẩn
        merged_blocks: list[dict[str, Any]] = []
        for idx, box in enumerate(detected_boxes):
            block_id = int(box.get("id", idx))
            bbox = list(box.get("bbox") or [0, 0, 0, 0])
            s_text = source_texts[idx]
            t_text = translations[idx] or s_text

            merged_blocks.append({
                "id": block_id,
                "bbox": bbox,
                "source_text": s_text,
                "translation": t_text,
            })

        return merged_blocks
    finally:
        if owns_client:
            await client.aclose()
