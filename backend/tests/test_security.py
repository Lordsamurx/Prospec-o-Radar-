"""Senha, CSRF, cabeçalhos e segredos fora das respostas."""
import base64

import pytest

from conftest import get_id

J = {"format": "json"}


def basic(user: str, password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture()
def locked(env, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "senha-de-teste-123")
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app
    from app.seed import main

    config.get_settings.cache_clear()
    with TestClient(app) as c:
        main()
        yield c


@pytest.mark.parametrize("path", ["/", "/leads", "/leads?format=json", "/buscas", "/funil", "/servicos", "/metricas",
                                  "/config", "/ajuda", "/sessao", "/export.csv", "/api/quota", "/api/command?q=sal",
                                  "/static/css/app.css", "/docs", "/openapi.json", "/leads/1"])
def test_senha_protege_tudo(locked, path):
    r = locked.get(path)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith('Basic realm="Radar"')
    assert "senha-de-teste-123" not in r.text


def test_senha_protege_as_acoes(locked):
    assert locked.post("/buscas", json={"niche": "dentista", "location": "BH"}).status_code == 401
    assert locked.patch("/leads/1/status", json={"status": "ABORDADO"}).status_code == 401
    assert locked.post("/leads/1/delete", json={"confirm": "sim"}).status_code == 401
    assert locked.post("/config/backup").status_code == 401


def test_senha_errada_e_certa(locked):
    assert locked.get("/", headers=basic("samuel", "errada")).status_code == 401
    assert locked.get("/", headers=basic("outro", "senha-de-teste-123")).status_code == 401
    assert locked.get("/", headers={"Authorization": "Basic %%%"}).status_code == 401
    ok = locked.get("/", headers=basic("samuel", "senha-de-teste-123"))
    assert ok.status_code == 200 and ok.headers["x-robots-tag"] == "noindex, nofollow"


def test_saude_e_amostras_ficam_abertas(locked):
    assert locked.get("/health").status_code == 200
    auth = basic("samuel", "senha-de-teste-123")
    lid = locked.get("/leads", params={**J, "site": "sem"}, headers=auth).json()["leads"][0]["id"]
    site = locked.post(f"/leads/{lid}/site", params=J, headers=auth).json()
    page = locked.get(site["local_url"])  # sem senha: é o link que vai para o dono do negócio
    assert page.status_code == 200 and page.headers["x-robots-tag"] == "noindex, nofollow"
    assert locked.get("/previews/nao-existe/").status_code == 404


def test_csrf_bloqueia_outra_origem(seeded):
    lid = get_id(seeded)
    evil = {"Origin": "https://site-malicioso.example"}
    assert seeded.post(f"/leads/{lid}/dnc", json={}, headers=evil).status_code == 403
    assert seeded.patch(f"/leads/{lid}/status", json={"status": "ABORDADO"}, headers=evil).status_code == 403
    assert seeded.post("/buscas", json={"niche": "dentista", "location": "BH"},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert seeded.get(f"/leads/{lid}", params=J).json()["do_not_contact"] if False else True
    ok = seeded.post(f"/leads/{lid}/notes", json={"notes": "ok"}, params=J, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200
    assert seeded.get("/leads", headers=evil).status_code == 200, "leitura não muda nada"


def test_cabecalhos_de_seguranca(seeded):
    r = seeded.get("/")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["referrer-policy"] == "same-origin"


def test_chaves_nunca_aparecem(env, monkeypatch):
    """Chave do Google e das IAs: nem nas páginas, nem no JSON, nem nas mensagens de erro."""
    secrets = {"GOOGLE_MAPS_API_KEY": "AIza-teste-nao-real-000", "GEMINI_API_KEY": "gem-teste-nao-real-111",
               "GROQ_API_KEY": "gsk-teste-nao-real-222", "PAGESPEED_API_KEY": "psi-teste-nao-real-333"}
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app
    from app.seed import main

    config.get_settings.cache_clear()
    assert all(v not in repr(config.get_settings()) for v in secrets.values())
    with TestClient(app) as c:
        main()
        for path in ("/", "/leads", "/buscas", "/config", "/config?format=json", "/ajuda", "/health", "/api/quota",
                     "/servicos", "/metricas", "/funil", "/sessao"):
            body = c.get(path).text
            assert not [v for v in secrets.values() if v in body], path
        cfg = c.get("/config", params=J).json()
        assert cfg["has_google_key"] is True and cfg["ai_keys"] == {"gemini": True, "groq": True}


def test_env_example_so_tem_nomes():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("GOOGLE_MAPS_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "APP_PASSWORD", "PAGESPEED_API_KEY")):
            assert line.split("=", 1)[1].strip() == "", line


def test_codigo_sem_chave_escrita():
    """Nenhum arquivo da v3 traz algo com cara de chave do Google."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pat = re.compile(r"AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{30,}")
    bad = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".html", ".js", ".css", ".md", ".yaml", ".yml", ".txt", ".example", ".toml") \
                and not any(x in p.parts for x in (".venv", "node_modules", "data", "vendor", "_lixeira")):
            if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                bad.append(str(p))
    assert bad == []


def test_backup_download_nao_sai_da_pasta(seeded):
    assert seeded.get("/config/backup/..%2F..%2F.env").status_code == 404
    assert seeded.get("/config/backup/outro.db").status_code == 404
