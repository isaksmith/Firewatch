import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("MODE", "sample")
    get_settings.cache_clear()
    from app.db import init_db

    init_db()
    yield
    get_settings.cache_clear()
