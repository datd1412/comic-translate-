from __future__ import annotations

from contextlib import asynccontextmanager
import os
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
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

