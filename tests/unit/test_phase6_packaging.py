from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_python_tooling_targets_are_consistent() -> None:
    config = _pyproject()

    assert config["project"]["requires-python"] == ">=3.12"
    assert config["tool"]["ruff"]["target-version"] == "py312"
    assert config["tool"]["mypy"]["python_version"] == "3.12"
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_pyproject_is_the_dependency_source_of_truth() -> None:
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    development = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert runtime.splitlines()[-1] == "."
    assert development.splitlines()[-1] == "-e .[all,dev]"

    for content in (runtime, development):
        dependency_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert len(dependency_lines) == 1


def test_provider_dependencies_are_optional_extras() -> None:
    config = _pyproject()["project"]
    base = "\n".join(config["dependencies"]).lower()
    extras = config["optional-dependencies"]

    assert "paramiko" not in base
    assert "playwright" not in base
    assert "google-api-python-client" not in base
    assert "requests-oauthlib" not in base

    assert any("paramiko" in dependency for dependency in extras["sftp"])
    assert any("playwright" in dependency for dependency in extras["sharepoint"])
    assert any("google-api-python-client" in dependency for dependency in extras["google"])
    assert any("requests-oauthlib" in dependency for dependency in extras["onedrive"])


def test_console_script_is_declared() -> None:
    scripts = _pyproject()["project"]["scripts"]
    assert scripts["drive-unix"] == "main:main"


def test_base_cli_import_does_not_require_provider_extras() -> None:
    script = """
import sys
for name in ('paramiko', 'playwright', 'google', 'google_auth_oauthlib', 'googleapiclient', 'requests_oauthlib'):
    sys.modules[name] = None
import cli.app
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_ci_matrix_covers_supported_python_versions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for version in ('"3.12"', '"3.13"', '"3.14"'):
        assert version in workflow
    assert "ruff check ." in workflow
    assert "mypy" in workflow
    assert "python -m pytest" in workflow


def test_project_syntax_is_python_312_compatible() -> None:
    roots = (
        "application",
        "auth",
        "cli",
        "core",
        "domain",
        "infrastructure",
        "providers",
        "storage",
    )
    for root_name in roots:
        for path in (ROOT / root_name).rglob("*.py"):
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
                feature_version=(3, 12),
            )
    ast.parse(
        (ROOT / "main.py").read_text(encoding="utf-8"),
        filename=str(ROOT / "main.py"),
        feature_version=(3, 12),
    )


def test_optional_provider_error_is_actionable_without_masking_internal_imports() -> None:
    from storage.registry import _missing_provider_extra

    missing = ModuleNotFoundError("No module named 'paramiko'")
    missing.name = "paramiko"
    error = _missing_provider_extra(
        "SFTP",
        "sftp",
        missing,
        expected_modules=("paramiko",),
    )
    assert "drive-unix[sftp]" in str(error)

    internal = ModuleNotFoundError("No module named 'internal_bug'")
    internal.name = "internal_bug"
    try:
        _missing_provider_extra(
            "SFTP",
            "sftp",
            internal,
            expected_modules=("paramiko",),
        )
    except ModuleNotFoundError as exc:
        assert exc is internal
    else:
        raise AssertionError("unexpected internal import error masking")
