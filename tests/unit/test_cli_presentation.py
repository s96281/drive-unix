from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from cli.app import create_app
from cli import presentation


runner = CliRunner()


def test_plain_global_option_removes_symbols(monkeypatch) -> None:
    fake_manager = SimpleNamespace(config=SimpleNamespace(tasks={}))
    monkeypatch.setattr("cli.commands.cron.ConfigManager", lambda: fake_manager)

    result = runner.invoke(create_app(), ["--plain", "schedule", "list"])

    assert result.exit_code == 0
    assert "⚠" not in result.stdout
    assert "目前沒有排程任務" in result.stdout
    assert "\x1b[" not in result.stdout


def test_no_color_removes_style_arguments(monkeypatch) -> None:
    calls: list[tuple[object, dict]] = []
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        presentation.typer,
        "secho",
        lambda message=None, **kwargs: calls.append((message, kwargs)),
    )

    presentation.configure_presentation(plain=False)
    presentation.secho("message", fg="red", bold=True)

    message, kwargs = calls[-1]
    assert message == "message"
    assert kwargs["color"] is False
    assert "fg" not in kwargs
    assert "bold" not in kwargs


def test_plain_text_strips_known_cli_symbols(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    presentation.configure_presentation(plain=True)
    try:
        assert presentation.plain_text("✅ 完成 ⚠️ 注意") == "完成 注意"
        assert presentation.live_output_enabled() is False
    finally:
        presentation.configure_presentation(plain=False)
