# -*- coding: utf-8 -*-
import os
import sys
import asyncio
from pathlib import Path

# Đảm bảo UTF-8 cho console Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import httpx
from dotenv import dotenv_values

# 1. Đọc file server/.env
env_path = Path(__file__).resolve().parent / "server" / ".env"
if not env_path.exists():
    print(f"[LỖI] Không tìm thấy file: {env_path}")
    sys.exit(1)

env_vars = dotenv_values(env_path)
api_key = (env_vars.get("GEMINI_API_KEY") or "").strip()
configured_model = (env_vars.get("GEMINI_MODEL") or "gemini-1.5-flash").strip()

print("=" * 60)
print("KIỂM TRA CẤU HÌNH & KẾT NỐI GEMINI API")
print("=" * 60)
print(f"File cấu hình: {env_path}")
print(f"GEMINI_MODEL: {configured_model}")
print(f"GEMINI_API_KEY: {'Đã có (' + api_key[:8] + '...' + api_key[-4:] + ')' if api_key else '[RỖNG]'}")

if not api_key:
    print("[LỖI] GEMINI_API_KEY đang bị rỗng trong server/.env!")
    sys.exit(1)

# Chuẩn hóa tên model: loại bỏ tiền tố 'models/' nếu có
model_name = configured_model[len("models/"):] if configured_model.startswith("models/") else configured_model

# 2. Kiểm tra trực tiếp URL chuẩn REST API sang Gemini
endpoint_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
print(f"\n[1] Thử nghiệm gọi REST API với model cấu hình: {model_name}")
print(f"URL: https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key=***")

headers = {"Content-Type": "application/json"}
payload = {
    "contents": [
        {
            "role": "user",
            "parts": [{"text": "Dịch sang tiếng Việt: Hello world"}],
        }
    ]
}

http_success = False
try:
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(endpoint_url, json=payload, headers=headers)
        print(f"Mã phản hồi HTTP: {resp.status_code}")

        if resp.status_code == 200:
            http_success = True
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            print(f"[THÀNH CÔNG] Gemini trả về HTTP 200!")
            print(f"Nội dung phản hồi: {text}")
        elif resp.status_code == 404:
            err_msg = resp.json().get("error", {}).get("message", resp.text)
            print(f"[CẢNH BÁO GOOGLE API] Model '{model_name}' trả về 404:")
            print(f"  -> Chi tiết từ Google: {err_msg}")
            print(f"\n[2] Tự động kiểm tra với model Flash kế nhiệm khả dụng: 'gemini-flash-lite-latest'")
            fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={api_key}"
            fb_resp = client.post(fallback_url, json=payload, headers=headers)
            print(f"Mã phản hồi HTTP: {fb_resp.status_code}")
            if fb_resp.status_code == 200:
                http_success = True
                fb_data = fb_resp.json()
                fb_text = fb_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                print(f"[THÀNH CÔNG] Kết nối Gemini API hoạt động tốt (HTTP 200 OK)!")
                print(f"Nội dung phản hồi: {fb_text}")
            else:
                print(f"[LỖI] Fallback trả về mã {fb_resp.status_code}: {fb_resp.text}")
        else:
            print(f"[LỖI] Gemini API trả về mã {resp.status_code}: {resp.text}")
except Exception as e:
    print(f"[LỖI NGOẠI LỆ] Khi gọi Gemini API: {e}")

# 3. Kiểm tra hàm dịch thuật trong translator.py
print(f"\n[3] Kiểm tra tích hợp hàm translate_blocks_with_llm trong server/translator.py:")
server_dir = str(Path(__file__).resolve().parent / "server")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

try:
    from translator import translate_blocks_with_llm

    sample_blocks = [
        {"id": 0, "text": "你好！今天天气真好。"},
        {"id": 1, "text": "确实如此，我们一起去散步吧。"},
    ]

    async def _test_translate():
        return await translate_blocks_with_llm(
            blocks=sample_blocks,
            lang_pair="zh-vi",
            context={"series_title": "Bộ truyện thử nghiệm"},
        )

    translated = asyncio.run(_test_translate())
    print("[THÀNH CÔNG] Dịch khối thoại truyện tranh hoàn tất:")
    for b in translated:
        print(f"  - Block {b['id']}: '{b['source_text']}' -> '{b['translation']}'")
except Exception as e:
    print(f"[LỖI] Gọi translator thất bại: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
if http_success:
    print("KẾT LUẬN: ĐÃ KIỂM TRA THÀNH CÔNG KẾT NỐI GEMINI API (HTTP 200) VÀ HÀM DỊCH THUẬT!")
else:
    print("KẾT LUẬN: KIỂM TRA THẤT BẠI.")
print("=" * 60)
