import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("MODE", "sample")
    # .env may name a real key and a real radio; a test must never reach either
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("MESH_GATEWAY", "off")
    monkeypatch.setenv("API_TOKEN", "")  # tests that need a token set their own
    monkeypatch.setenv("SENSOR_SIM", "false")
    get_settings.cache_clear()
    from app.db import init_db

    init_db()
    yield
    get_settings.cache_clear()
