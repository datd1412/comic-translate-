from __future__ import annotations

from contextlib import asynccontextmanager
import os
import socket
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import auth_routes
import billing_routes
from config import settings
from database import init_db
import translate_routes


def _disable_windows_quickedit() -> None:
    """Tắt chế độ QuickEdit của Windows PowerShell/CMD để tránh click chuột làm treo cứng Server."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            new_mode = (mode.value & ~0x0040) | 0x0080
            kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass


_disable_windows_quickedit()


def _detect_local_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    lan_ip = _detect_local_lan_ip()
    tunnel_url = await auth_routes.ensure_tunnel_running()
    print("\n" + "=" * 68)
    print(f"🚀 [COMIC TRANSLATE VN] Server đã sẵn sàng!")
    print(f"💻 Truy cập trên Laptop (PC):   http://127.0.0.1:8000")
    print(f"📱 Địa chỉ kết nối cho Mobile:  http://{lan_ip}:8000")
    if tunnel_url:
        print(f"🌐 Tunnel cố định (HTTPS):       {tunnel_url}")
        print(f"   (Đảm bảo domain '{tunnel_url.replace('https://', '')}' có trong Firebase Authorized Domains)")
    print("=" * 68 + "\n")
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version="2.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+|[a-z0-9-]+\.trycloudflare\.com|[a-z0-9-]+\.ngrok-free\.(app|dev))(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(auth_routes.router)
    application.include_router(billing_routes.router)
    application.include_router(translate_routes.router)

    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    templates = Jinja2Templates(directory=templates_dir)

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    images_dir = os.path.join(static_dir, "images")
    if os.path.exists(images_dir):
        application.mount("/images", StaticFiles(directory=images_dir), name="images")
    if os.path.exists(static_dir):
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "landing.html", {"request": request})

    @application.get("/admin/revenue", response_class=HTMLResponse)
    async def admin_revenue(request: Request):
        return templates.TemplateResponse(request, "admin_revenue.html", {"request": request})

    @application.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "comic-translate-vn-server"}

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

