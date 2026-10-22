"""Unit tests for Global Server-Sent Events (SSE) broadcaster and stream (/api/events)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager
from web.events import broadcaster


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_broadcaster_publish_and_history():
    seq1 = broadcaster.publish("test.event", {"hello": "world"})
    assert seq1 > 0

    seq2 = broadcaster.publish("log", {"level": "INFO", "message": "Test log message"})
    assert seq2 == seq1 + 1


def test_broadcaster_async_stream():
    async def _test():
        gen = broadcaster.stream(last_event_id=None)
        hello_msg = await gen.asend(None)
        assert "event: hello" in hello_msg
        assert "server_time" in hello_msg
        await gen.aclose()

    asyncio.run(_test())
