"""FastAPI Composition Root for drive-unix web services."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from web.log_bridge import setup_log_bridge
from web.storage_pool import storage_pool
from web.routers.events import router as events_router
from web.routers.files import router as files_router
from web.routers.remotes import router as remotes_router
from web.routers.schedule import router as schedule_router
from web.routers.settings import router as settings_router
from web.routers.sync import router as sync_router
from web.routers.upstash import router as upstash_router

STATIC_DIR = Path(__file__).resolve().parent / "static"


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that serves index.html for SPA deep-link routing."""

    async def get_response(self, path: str, scope: Any) -> Any:
        try:
            response = await super().get_response(path, scope)
            if response.status_code == 404 and "." not in path and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            return response
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in path and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle; cleanly tear down connection pools on shutdown."""
    yield
    storage_pool.clear()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="drive-unix Web API",
        version="0.1.0",
        description="Modern Web Interface & REST API for multi-provider file synchronization",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Initialize log bridge
    setup_log_bridge()

    # CORS configuration: Allow localhost and public access
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API Routers
    app.include_router(events_router)
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
        app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
