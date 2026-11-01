from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    @application.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "comic-translate-vn-server"}

    return application


app = create_app()
