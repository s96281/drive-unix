from types import SimpleNamespace

from typer.testing import CliRunner

from cli.app import create_app
from domain.models import FileItem


runner = CliRunner()


class UploadStorage:
    def stat(self, remote_path):
        return {"type": "folder"}

    def mkdir(self, remote_path, parents=False):
        return True

    def upload(self, local_path, remote_path, callback=None):
        if remote_path.endswith("bad.txt"):
            return False
        if callback:
            callback(1, 1)
        return True


class DownloadStorage:
    def download(self, remote_path, local_path, recursive=False, callback=None):
        if remote_path == "/folder":
            raise IsADirectoryError(remote_path)
        if remote_path.endswith("bad.txt"):
            return False
        if callback:
            callback(1, 1)
        return True


def _fake_context():
    manager = SimpleNamespace(config=SimpleNamespace(default_remote="remote"))
    return SimpleNamespace(config=manager)


def test_recursive_upload_partial_failure_returns_nonzero(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "good.txt").write_text("good", encoding="utf-8")
    (source / "bad.txt").write_text("bad", encoding="utf-8")

    monkeypatch.setattr("cli.commands.transfer.CLIContext.create", _fake_context)
    monkeypatch.setattr(
        "cli.commands.transfer.get_storage_provider",
        lambda remote_name, config_manager: UploadStorage(),
    )

    result = runner.invoke(
        create_app(),
        ["upload", str(source), "remote:/dest", "--recursive", "--workers", "2"],
    )

    assert result.exit_code == 1
    assert "資料夾上傳未完成" in result.stdout
    assert "原因：" in result.stdout
    assert "下一步：" in result.stdout
    assert "整個資料夾上傳流程結束" not in result.stdout


def test_recursive_download_partial_failure_returns_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr("cli.commands.transfer.CLIContext.create", _fake_context)
    monkeypatch.setattr(
        "cli.commands.transfer.get_storage_provider",
        lambda remote_name, config_manager: DownloadStorage(),
    )
    monkeypatch.setattr(
        "application.transfer_service.get_all_files_recursive",
        lambda storage, path: {
            "good.txt": FileItem(
                name="good.txt",
                path="/folder/good.txt",
                is_dir=False,
                size=1,
            ),
            "bad.txt": FileItem(
                name="bad.txt",
                path="/folder/bad.txt",
                is_dir=False,
                size=1,
            ),
        },
    )

    result = runner.invoke(
        create_app(),
        ["download", "remote:/folder", str(tmp_path), "--workers", "2", "--recursive"],
    )

    assert result.exit_code == 1
    assert "資料夾下載未完成" in result.stdout
    assert "資料夾及其內容下載完成" not in result.stdout
