from pathlib import Path

import pytest
from app.core.config.app_config import app_config
from app.core.storage import object_storage


@pytest.fixture(autouse=True)
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(app_config, "OBJECT_STORAGE_DIR", str(tmp_path))
    return tmp_path


async def test_delete_prefix_removes_only_that_prefix(storage_dir: Path) -> None:
    await object_storage.upload_bytes("bills", "site-a/1.pdf", b"a", "application/pdf")
    await object_storage.upload_bytes("bills", "site-b/2.pdf", b"b", "application/pdf")

    await object_storage.delete_prefix("bills", "site-a")

    assert not (storage_dir / "bills" / "site-a").exists()
    assert (storage_dir / "bills" / "site-b" / "2.pdf").exists()


async def test_delete_missing_prefix_is_fine() -> None:
    await object_storage.delete_prefix("bills", "never-existed")


@pytest.mark.parametrize("prefix", ["", ".", "..", "a/b", "../x"])
async def test_delete_prefix_rejects_paths(prefix: str) -> None:
    with pytest.raises(ValueError):
        await object_storage.delete_prefix("bills", prefix)
