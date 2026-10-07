import os
from pathlib import Path

import pytest

os.environ["JOBFINDER_NO_KEYRING"] = "1"
os.environ["JOBFINDER_ALLOWED_HOSTS"] = "testserver"  # FastAPI TestClient's host

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    from app import config, db

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "SECRETS_FALLBACK_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(config, "LINKEDIN_PROFILE_DIR", tmp_path / "li-profile")
    db.init_db()
    return tmp_path
