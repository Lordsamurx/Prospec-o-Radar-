import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Banco e pastas temporários, provedor fictício. Nada de rede e nada do .env do protótipo."""
    monkeypatch.setenv("RADAR_NO_PARENT_ENV", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("PREVIEWS_DIR", str(tmp_path / "previews"))
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("PLACES_PROVIDER", "mock")
    for key in ("GOOGLE_MAPS_API_KEY", "APP_PASSWORD", "GEMINI_API_KEY", "GROQ_API_KEY", "PREVIEWS_PUBLIC_URL",
                "PAGESPEED_API_KEY"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("MAX_PLACES_REQUESTS_PER_DAY", "30")
    from app import config, db

    config.get_settings.cache_clear()
    db.init_engine()
    yield tmp_path
    config.get_settings.cache_clear()


@pytest.fixture()
def session(env):
    from app.db import new_session

    s = new_session()
    yield s
    s.close()


@pytest.fixture()
def ctx(session):
    from app.services import app_settings

    return app_settings.load_ctx(session)


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    from app.seed import main

    main()
    return client


def lead(**kw) -> dict:
    """Lead mínimo como dicionário (as funções puras aceitam dict ou modelo)."""
    base = {"place_id": "g-123456789012", "name": "Salão Teste", "niche": "salao", "phone": "(31) 98888-1111",
            "website_url": None, "rating": 4.6, "reviews_count": 80, "photos_count": 12,
            "opening_hours": "Seg a Sáb 9h às 19h", "business_status": "OPERATIONAL", "categories": ["hair_salon"],
            "neighborhood": "Savassi", "city": "Belo Horizonte"}
    base.update(kw)
    return base


def get_id(client, **params) -> int:
    r = client.get("/leads", params={"format": "json", "show_mock": "1", **params})
    assert r.status_code == 200, r.text
    return r.json()["leads"][0]["id"]
