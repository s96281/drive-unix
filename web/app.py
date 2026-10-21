"""FastAPI Composition Root for drive-unix web services."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.routers.files import router as files_router
from web.routers.remotes import router as remotes_router
from web.routers.schedule import router as schedule_router
from web.routers.settings import router as settings_router
from web.routers.sync import router as sync_router
from web.routers.upstash import router as upstash_router

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="drive-unix Web API",
        version="0.1.0",
        description="Modern Web Interface & REST API for multi-provider file synchronization",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS configuration: Allow localhost and public access
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API Routers
    app.include_router(remotes_router)
    app.include_router(files_router)
    app.include_router(sync_router)
    app.include_router(schedule_router)
    app.include_router(settings_router)
    app.include_router(upstash_router)

    # Health check endpoint
    @app.get("/api/health")
    def health_check():
        return {"status": "ok", "app": "drive-unix", "version": "0.1.0"}

    # Mount static assets if static folder exists
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
