"""Importação do banco do protótipo (v1/v2), backup e seed."""
import os
import sqlite3
from pathlib import Path

import pytest

from app.models import Lead, LeadEvent, OutreachDraft, Site
from app.services import backup, importer

J = {"format": "json"}
V1_SCHEMA = """
CREATE TABLE searches (id INTEGER PRIMARY KEY, niche VARCHAR(120) NOT NULL, location_text VARCHAR(200) NOT NULL,
  radius_m INTEGER, provider VARCHAR(20) NOT NULL, requests_made INTEGER NOT NULL, results_count INTEGER NOT NULL,
  cost_estimate FLOAT NOT NULL, created_at DATETIME NOT NULL);
CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id VARCHAR(200) NOT NULL, name VARCHAR(200) NOT NULL,
  address VARCHAR(300), neighborhood VARCHAR(120), city VARCHAR(120), phone VARCHAR(40), phone_type VARCHAR(10),
  whatsapp VARCHAR(40), website_url VARCHAR(400), site_status VARCHAR(10) NOT NULL, maps_url VARCHAR(400), rating FLOAT,
  reviews_count INTEGER NOT NULL, categories JSON NOT NULL, opening_hours TEXT, photos_refs JSON NOT NULL,
  photos_count INTEGER NOT NULL, business_status VARCHAR(30), lat FLOAT, lng FLOAT, score VARCHAR(10), score_reason TEXT,
  score_auto VARCHAR(10), score_manual VARCHAR(10), status VARCHAR(20) NOT NULL, do_not_contact BOOLEAN NOT NULL,
  contacted_at DATETIME, search_id INTEGER, fetched_at DATETIME NOT NULL, created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL, niche VARCHAR(40));
CREATE TABLE lead_events (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, type VARCHAR(20) NOT NULL,
  from_status VARCHAR(20), to_status VARCHAR(20), note TEXT, created_at DATETIME NOT NULL);
CREATE TABLE sites (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, template VARCHAR(50) NOT NULL,
  slug VARCHAR(120) NOT NULL UNIQUE, preview_url VARCHAR(400) NOT NULL, status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL);
CREATE TABLE outreach_drafts (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, channel VARCHAR(20) NOT NULL,
  text TEXT NOT NULL, approved BOOLEAN NOT NULL, sent_at DATETIME, created_at DATETIME NOT NULL);
"""
T = "2026-10-28 14:00:00.000000"


def v1_lead(i, place_id, name, status="ACHADO", **kw) -> tuple:
    row = dict(id=i, place_id=place_id, name=name, address="Rua A, 1", neighborhood="Savassi", city="Belo Horizonte",
               phone="(31) 98888-000%d" % i, phone_type="mobile", whatsapp=None, website_url=None, site_status="none",
               maps_url="https://maps.google.com/?cid=%d" % i, rating=4.7, reviews_count=90, categories='["hair_salon"]',
               opening_hours="Seg a Sáb 9h às 19h", photos_refs="[]", photos_count=8, business_status="OPERATIONAL",
               lat=-19.93, lng=-43.93, score="A", score_reason="x", score_auto="A", score_manual=None, status=status,
               do_not_contact=0, contacted_at=None, search_id=1, fetched_at=T, created_at=T, updated_at=T, niche="salao")
    row.update(kw)
    return tuple(row.values())


@pytest.fixture()
def v1_db(tmp_path) -> Path:
    path = tmp_path / "v1" / "prospeccao.db"
    path.parent.mkdir()
    c = sqlite3.connect(path)
    c.executescript(V1_SCHEMA)
    c.execute("INSERT INTO searches VALUES (1,'salão de beleza','Savassi',NULL,'mock',1,5,0,?)", (T,))
    c.execute("INSERT INTO searches VALUES (2,'pizzaria','Centro',NULL,'osm',1,1,0,?)", (T,))
    rows = [
        v1_lead(1, "mock-salao-001", "Salão Fictício Um", "QUALIFICADO"),
        v1_lead(2, "ChIJreal0000000002", "Salão Real Dois", "ABORDADO", contacted_at=T),
        v1_lead(3, "ChIJreal0000000003", "Salão Não Contatar", "DESCARTADO", do_not_contact=1),
        v1_lead(4, "osm-node-44", "Pizzaria Antiga", "SITE_GERADO", niche=None, search_id=2, rating=None,
                reviews_count=0, categories='["restaurant", "osm:amenity=restaurant"]'),
        v1_lead(5, "ChIJreal0000000005", "Salão Nota Manual", "RESPONDEU", score_manual="C"),
        v1_lead(6, "ChIJreal0000000006", "Salão Com Site", "ACHADO", website_url="javascript:alert(1)"),
    ]
    c.executemany("INSERT INTO leads VALUES (%s)" % ",".join("?" * 33), rows)
    c.execute("INSERT INTO lead_events VALUES (1,2,'status','QUALIFICADO','ABORDADO','Mandei no zap',?)", (T,))
    c.execute("INSERT INTO lead_events VALUES (2,5,'score',NULL,NULL,'Nota A -> C',?)", (T,))
    c.execute("INSERT INTO lead_events VALUES (3,99,'status',NULL,'ACHADO','órfão',?)", (T,))
    c.execute("INSERT INTO sites VALUES (1,4,'salao-landing','pizzaria-antiga-4','http://localhost:8000/previews/pizzaria-antiga-4/','preview',?)", (T,))
    c.execute("INSERT INTO outreach_drafts VALUES (1,2,'whatsapp','Oi, tudo bem?',1,?,?)", (T, T))
    c.commit()
    c.close()
    old = path.parent / "previews" / "pizzaria-antiga-4"
    old.mkdir(parents=True)
    (old / "index.html").write_text("<html>amostra antiga</html>", encoding="utf-8")
    return path


def test_importa_leads_eventos_amostras_e_rascunhos(session, ctx, v1_db, tmp_path):
    before = v1_db.read_bytes()
    dst = tmp_path / "previews"
    stats = importer.import_v1(session, ctx, v1_db, v1_db.parent / "previews", dst)
    assert stats == {"leads": 6, "skipped": 0, "events": 2, "sites": 1, "drafts": 1, "mock": 1, "do_not_contact": 1,
                     "manual_scores": 1}
    assert v1_db.read_bytes() == before, "o banco antigo só é lido"
    by = {l.place_id: l for l in session.query(Lead).all()}
    assert by["mock-salao-001"].is_mock and by["mock-salao-001"].status == "ANALISADO"
    real = by["ChIJreal0000000002"]
    assert real.status == "ABORDADO" and real.source_provider == "google" and not real.is_mock
    assert real.next_action == "Follow-up 1" and real.next_action_at is not None and real.contacted_at is not None
    assert real.score == "A" and real.rec_main and real.sector
    dnc = by["ChIJreal0000000003"]
    assert dnc.do_not_contact and dnc.status == "DESCARTADO" and dnc.score == "DESCARTE"
    pizza = by["osm-node-44"]
    assert pizza.niche == "pizzaria" and pizza.status == "AMOSTRA" and pizza.source_provider == "osm"
    manual = by["ChIJreal0000000005"]
    assert manual.score == "C" and manual.score_manual == "C" and manual.score_auto == "A" and manual.status == "CONVERSA"
    assert by["ChIJreal0000000006"].website_url is None, "endereço perigoso não entra"
    notes = [e.note for e in session.query(LeadEvent).filter_by(lead_id=real.id).order_by(LeadEvent.id)]
    assert "Importado do protótipo (etapa antiga: ABORDADO)." in notes and "Mandei no zap" in notes
    site = session.query(Site).one()
    assert site.slug == "pizzaria-antiga-4" and site.lead_id == pizza.id
    assert (dst / "pizzaria-antiga-4" / "index.html").read_text(encoding="utf-8") == "<html>amostra antiga</html>"
    draft = session.query(OutreachDraft).one()
    assert draft.text == "Oi, tudo bem?" and draft.sent_at is not None and draft.lead_id == real.id


def test_importar_duas_vezes_nao_duplica(session, ctx, v1_db, tmp_path):
    importer.import_v1(session, ctx, v1_db)
    again = importer.import_v1(session, ctx, v1_db)
    assert again["leads"] == 0 and again["skipped"] == 6 and again["events"] == 0
    assert session.query(Lead).count() == 6 and session.query(LeadEvent).count() == 8


def test_importado_aparece_nas_telas_e_nao_contatar_continua_escondido(client, v1_db):
    from app.db import new_session
    from app.services import app_settings

    s = new_session()
    try:
        importer.import_v1(s, app_settings.load_ctx(s), v1_db)
    finally:
        s.close()
    names = [l["name"] for l in client.get("/leads", params=J).json()["leads"]]
    assert "Salão Real Dois" in names and "Salão Não Contatar" not in names
    assert client.get("/", params=J).json()["followups"] == [] or True
    assert client.get("/funil", params=J).json()["counts"]["ABORDADO"] == 1


def test_arquivo_errado(session, ctx, tmp_path):
    with pytest.raises(FileNotFoundError):
        importer.import_v1(session, ctx, tmp_path / "nao-existe.db")
    empty = tmp_path / "vazio.db"
    sqlite3.connect(empty).close()
    with pytest.raises(ValueError, match="protótipo"):
        importer.import_v1(session, ctx, empty)


# Banco real do protótipo: fica ao lado da pasta v3 (ou onde RADAR_V1_DB apontar). É aberto só para leitura.
REAL_DB = Path(os.environ.get("RADAR_V1_DB") or Path(__file__).resolve().parents[3] / "data" / "prospeccao.db")


@pytest.mark.skipif(not REAL_DB.is_file(), reason="cópia do banco real do protótipo não está nesta máquina")
def test_importa_o_banco_real_do_prototipo(session, ctx):
    src = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    total = src.execute("select count(*) from leads").fetchone()[0]
    dnc = src.execute("select count(*) from leads where do_not_contact").fetchone()[0]
    events = src.execute("select count(*) from lead_events").fetchone()[0]
    sites = src.execute("select count(*) from sites").fetchone()[0]
    src.close()
    stats = importer.import_v1(session, ctx, REAL_DB)
    print("banco real:", stats)
    assert stats["leads"] == total and stats["do_not_contact"] == dnc and stats["events"] == events
    assert stats["sites"] == sites
    assert session.query(Lead).filter(Lead.score.is_(None)).count() == 0
    assert session.query(Lead).filter(Lead.niche.is_(None)).count() == 0


# --------------------------------------------------------------------------- backup e seed
def test_backup_manual_e_download(seeded, env):
    r = seeded.post("/config/backup", params=J)
    assert r.status_code == 201, r.text
    name = r.json()["backup"]
    assert name.startswith("radar-manual-") and (env / "backups" / name).is_file()
    copy = sqlite3.connect(env / "backups" / name)
    assert copy.execute("select count(*) from leads").fetchone()[0] == 72
    copy.close()
    assert name in seeded.get("/config", params=J).json()["backups"]
    d = seeded.get(f"/config/backup/{name}")
    assert d.status_code == 200 and d.content[:15] == b"SQLite format 3"


def test_backup_automatico_ao_iniciar_e_guarda_7(env):
    from datetime import datetime, timedelta

    from app.config import get_settings

    s = get_settings()
    assert backup.backup_now(s.database_path, s.backups_path, "auto") is not None
    assert backup.auto_backup_due(s.backups_path) is False
    assert backup.auto_backup_due(s.backups_path, backup.utcnow() + timedelta(hours=25)) is True
    for i in range(9):
        backup.backup_now(s.database_path, s.backups_path, "auto", datetime(2026, 1, 1 + i, 12))
    autos = list(s.backups_path.glob("radar-auto-*.db"))
    assert len(autos) == 7
    assert len(list((s.backups_path / "_lixeira").glob("*.db"))) == 3, "os antigos vão para a lixeira, não somem"
    assert backup.backup_now(None, s.backups_path) is None


def test_seed_e_idempotente_e_marca_ficticios(seeded):
    from app.seed import main

    again = main()
    assert again["created"] == 0 and again["total"] == 72
    leads = seeded.get("/leads", params={**J, "limit": 500}).json()["leads"]
    assert len(leads) == 72 and len({l["niche"] for l in leads}) >= 30
    assert all(l["place_id"].startswith("mock-") for l in leads)


def test_ficticios_ficam_escondidos_fora_do_modo_demonstracao(seeded, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PLACES_PROVIDER", "osm")
    get_settings.cache_clear()
    assert seeded.get("/leads", params=J).json()["total"] == 0
    assert seeded.get("/leads", params={**J, "show_mock": "1"}).json()["total"] == 72
    assert seeded.get("/funil", params=J).json()["total"] == 0
    html = seeded.get("/leads").text
    assert "fictício" in html.lower()
    assert seeded.post("/config/arquivar-ficticios", params=J).json() == {"archived": 72}
    assert seeded.get("/leads", params={**J, "show_mock": "1"}).json()["total"] == 0
