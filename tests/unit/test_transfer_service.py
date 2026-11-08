import pytest

from application.transfer_service import TransferOperationError, TransferService


class FalseUploadStorage:
    def upload(self, local_path, remote_path, callback=None):
        return False


class FalseDownloadStorage:
    def download(self, remote_path, local_path, recursive=False, callback=None):
        return False


def test_upload_false_is_a_real_failure(tmp_path):
    local_file = tmp_path / "a.txt"
    local_file.write_text("x", encoding="utf-8")

    with pytest.raises(TransferOperationError):
        TransferService.call_upload(
            FalseUploadStorage(),
            str(local_file),
            "/a.txt",
        )


def test_download_false_is_a_real_failure(tmp_path):
    with pytest.raises(TransferOperationError):
        TransferService.call_download(
            FalseDownloadStorage(),
            "/a.txt",
            str(tmp_path / "a.txt"),
        )


def test_run_batch_collects_all_failures_and_keeps_peer_successes():
    def worker(job: str) -> None:
        if job.startswith("bad"):
            raise RuntimeError(job)

    result = TransferService.run_batch(
        ["good-1", "bad-1", "good-2", "bad-2"],
        worker,
        workers=4,
    )

    assert result.succeeded == 2
    assert result.failed == 2
    assert not result.success
    assert {failure.job for failure in result.failures} == {"bad-1", "bad-2"}


def test_run_batch_rejects_zero_workers():
    with pytest.raises(ValueError):
        TransferService.run_batch([], lambda job: None, workers=0)
