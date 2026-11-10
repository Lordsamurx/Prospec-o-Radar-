"""Integração pela API: páginas, busca, lead, funil, "não contatar", LGPD, lote, CSV e JSON."""
import re
from datetime import datetime

import pytest

from conftest import get_id

PAGES = ["/", "/leads", "/leads?view=mapa", "/buscas", "/funil", "/servicos", "/metricas", "/config", "/ajuda",
         "/sessao"]
JSON_PAGES = ["/", "/leads", "/buscas", "/funil", "/servicos", "/metricas", "/config", "/ajuda", "/sessao",
              "/api/quota", "/health"]


def leads_json(client, **params) -> dict:
    r = client.get("/leads", params={"format": "json", **params})
    assert r.status_code == 200, r.text
    return r.json()


def first(client, **params) -> dict:
    return leads_json(client, **params)["leads"][0]


# --------------------------------------------------------------------------- páginas
@pytest.mark.parametrize("path", PAGES)
def test_paginas_abrem_em_portugues(seeded, path):
    r = seeded.get(path)
    assert r.status_code == 200, r.text[:300]
    assert '<html lang="pt-BR"' in r.text
    assert not re.search(r">\s*Enviar\s*<", r.text), "a app não tem botão Enviar"


@pytest.mark.parametrize("path", JSON_PAGES)
def test_tudo_tem_json(seeded, path):
    r = seeded.get(path, params={"format": "json"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert isinstance(r.json(), dict)


def test_paginas_abrem_com_banco_vazio(client):
    for path in PAGES:
        assert client.get(path).status_code == 200, path


def test_pagina_que_nao_existe_e_lead_que_nao_existe(seeded):
    assert seeded.get("/nao-existe").status_code == 404
    assert seeded.get("/leads/999999", params={"format": "json"}).status_code == 404
    r = seeded.get("/leads/999999")
    assert r.status_code == 404 and "Lead não encontrado" in r.text


def test_health_nao_mostra_segredo(seeded):
    body = seeded.get("/health").json()
    assert body["status"] == "ok" and body["leads"] > 0 and set(body) == {"status", "version", "provider", "leads"}


def test_nenhuma_rota_envia_mensagem():
    """Regra do projeto: a app nunca envia. Só existe "marquei como enviado" (/sent)."""
    from app.main import app

    paths = list(app.openapi()["paths"])
    assert not [p for p in paths if re.search(r"send|enviar|dispar", p)]
    assert "/outreach/{draft_id}/sent" in paths and "/leads/{lead_id}/sent" in paths


# --------------------------------------------------------------------------- busca
def test_busca_cria_leads_e_repetir_nao_duplica(client):
    body = {"niche": "salão de beleza", "location": "Belo Horizonte"}
    r = client.post("/buscas", json=body, params={"format": "json"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] > 0 and d["total"] == d["created"] and d["provider"] == "mock"
    r2 = client.post("/buscas", json=body, params={"format": "json"}).json()
    assert r2["created"] == 0 and r2["updated"] == d["total"]
    assert leads_json(client)["total"] == d["total"]
    hist = client.get("/buscas", params={"format": "json"}).json()["history"]
    assert len(hist) == 2 and hist[0]["niche_key"] == "salao"


def test_busca_html_e_endereco_antigo(client):
    r = client.post("/buscas", data={"niche": "dentista", "location": "Belo Horizonte"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "leads-changed" in r.headers["hx-trigger"]
    assert client.post("/search", json={"niche": "dentista", "location": "BH"}, params={"format": "json"}).status_code == 200


def test_busca_invalida(client):
    r = client.post("/buscas", json={"niche": "", "location": ""}, params={"format": "json"})
    assert r.status_code == 422 and "Diga o que procurar" in r.json()["error"]
    r = client.post("/buscas", json={"niche": "dentista", "location": "BH", "radius_km": "900"}, params={"format": "json"})
    assert r.status_code == 422 and "raio" in r.json()["error"].lower()


def test_busca_por_pino_no_mapa(client):
    r = client.post("/buscas", json={"niche": "pet shop", "lat": -19.9385, "lng": -43.9353, "radius_km": "1,5"},
                    params={"format": "json"})
    assert r.status_code == 200, r.text
    s = client.get("/buscas", params={"format": "json"}).json()["history"][0]
    assert s["lat"] == -19.9385 and s["radius_m"] == 1500 and s["location"]


def test_busca_em_lote_fila_e_cancelar(client):
    r = client.post("/buscas/lote", json={"lines": "pizzaria em Savassi\ndentista, Lourdes\npizzaria em savassi"},
                    params={"format": "json"})
    assert r.status_code == 200 and r.json()["queued"] == 2, r.text
    queue = client.get("/buscas", params={"format": "json"}).json()["queue"]
    assert [q["niche"] for q in queue] == ["pizzaria", "dentista"]
    done = client.post("/buscas/fila/processar", params={"format": "json"}).json()
    assert len(done["done"]) == 1 and done["pending"] == 1
    client.post(f"/buscas/fila/{queue[1]['id']}/cancelar", params={"format": "json"})
    assert client.get("/buscas", params={"format": "json"}).json()["queue"] == []
    assert client.post("/buscas/lote", json={"lines": ""}, params={"format": "json"}).status_code == 422


def test_lote_por_nichos_e_bairros(client):
    r = client.post("/buscas/lote", json={"niches": ["salao", "barbearia"], "neighborhoods": ["Savassi", "Lourdes"]},
                    params={"format": "json"})
    assert r.json()["queued"] == 4


def test_repetir_busca(client):
    client.post("/buscas", json={"niche": "academia", "location": "Belo Horizonte"}, params={"format": "json"})
    sid = client.get("/buscas", params={"format": "json"}).json()["history"][0]["id"]
    r = client.post(f"/buscas/{sid}/repetir", params={"format": "json"})
    assert r.status_code == 200 and r.json()["created"] == 0
    assert client.post("/buscas/99999/repetir", params={"format": "json"}).status_code == 404


def test_cota_no_osm_e_no_google(client, monkeypatch):
    q = client.get("/api/quota").json()
    assert q["limited"] is False and q["limit"] == 30


# --------------------------------------------------------------------------- lista e drawer
def test_lista_filtra_e_ordena(seeded):
    all_ = leads_json(seeded)
    sem = leads_json(seeded, site="sem")
    assert 0 < sem["total"] < all_["total"]
    assert all(l["site_status"] != "own" for l in sem["leads"])
    a = leads_json(seeded, score="A")
    assert a["total"] and all(l["score"] == "A" for l in a["leads"])
    two = seeded.get("/leads?format=json&niche=salao&niche=barbearia").json()
    assert {l["niche"] for l in two["leads"]} == {"salao", "barbearia"}
    assert [l["score"] for l in all_["leads"]][0] == "A"


def test_lista_htmx_devolve_so_o_fragmento(seeded):
    r = seeded.get("/leads", headers={"HX-Request": "true", "HX-Target": "results"})
    assert r.status_code == 200 and "<html" not in r.text and "data-open-lead" in r.text


def test_nome_abre_o_maps_em_nova_aba(seeded):
    html = seeded.get("/leads").text
    assert re.search(r'<a[^>]+href="https://www\.google\.com/maps[^"]*"[^>]+target="_blank"[^>]+rel="noopener', html)


def test_drawer_mostra_diagnostico_e_servicos(seeded):
    lead = first(seeded, site="sem", score="A")
    d = seeded.get(f"/leads/{lead['id']}", params={"format": "json"}).json()
    assert d["recommendations"] and d["recommendations"][0]["key"]
    assert d["diagnosis"] and d["strategy"]["title"] and d["package"]["items"]
    assert d["events"][-1]["to"] == "NOVO", "histórico do mais novo para o mais antigo"
    html = seeded.get(f"/leads/{lead['id']}", headers={"HX-Request": "true"}).text
    assert lead["name"] in html and "Histórico" in html
    full = seeded.get(f"/leads/{lead['id']}")
    assert full.status_code == 200 and '<html lang="pt-BR"' in full.text


def test_paleta_de_comandos(seeded):
    name = first(seeded)["name"]
    r = seeded.get("/api/command", params={"q": name[:5].lower()}).json()
    assert any(l["name"] == name for l in r["leads"])
    assert seeded.get("/api/command", params={"q": "a"}).json() == {"leads": []}


def test_lead_manual(client):
    r = client.post("/leads/manual", json={"name": "Padaria do Zé", "niche": "padaria", "neighborhood": "Centro",
                                           "phone": "31988887777"}, params={"format": "json"})
    assert r.status_code == 201 and r.json()["place_id"].startswith("manual-")
    lead = first(client)
    assert lead["name"] == "Padaria do Zé" and lead["phone"] == "(31) 98888-7777" and lead["phone_type"] == "mobile"
    assert client.post("/leads/manual", json={"name": " "}, params={"format": "json"}).status_code == 422


# --------------------------------------------------------------------------- etapa, nota, anotações
def test_mudar_etapa_grava_evento_e_proxima_acao(seeded):
    lid = get_id(seeded, site="sem")
    r = seeded.patch(f"/leads/{lid}/status", json={"status": "abordado"}, params={"format": "json"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ABORDADO" and r.json()["next_action_at"]
    events = seeded.get(f"/leads/{lid}", params={"format": "json"}).json()["events"]
    assert events[0]["type"] == "status" and events[0]["to"] == "ABORDADO"
    assert seeded.patch(f"/leads/{lid}/status", json={"status": "XYZ"}, params={"format": "json"}).status_code == 422


def test_perdido_pede_motivo_e_fechado_guarda_valor(seeded):
    lid = get_id(seeded, site="sem")
    r = seeded.patch(f"/leads/{lid}/status", json={"status": "PERDIDO", "lost_reason": "preco"},
                     params={"format": "json"}).json()
    assert r["lost_reason"] == "preco"
    seeded.patch(f"/leads/{lid}/status", json={"status": "FECHADO", "value": "1.500,00", "recurring": "90"},
                 params={"format": "json"})
    d = seeded.get(f"/leads/{lid}", params={"format": "json"}).json()
    assert d["status"] == "FECHADO" and d["proposal_value"] == 1500.0
    assert seeded.get("/funil", params={"format": "json"}).json()["values"]["FECHADO"] == 1500.0


def test_etapa_pelo_kanban_devolve_o_cartao(seeded):
    lid = get_id(seeded, site="sem")
    r = seeded.patch(f"/leads/{lid}/status?view=kanban", data={"status": "CONVERSA"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "funnel-changed" in r.headers["hx-trigger"] and "<html" not in r.text


def test_nota_manual_e_volta_para_automatica(seeded):
    lead = first(seeded, score="A")
    r = seeded.patch(f"/leads/{lead['id']}/score", json={"score": "c", "note": "vi o perfil"},
                     params={"format": "json"}).json()
    assert r["score"] == "C" and r["manual"] is True and r["score_auto"] == "A"
    r = seeded.patch(f"/leads/{lead['id']}/score", json={"score": "auto"}, params={"format": "json"}).json()
    assert r["score"] == "A" and r["manual"] is False
    assert seeded.patch(f"/leads/{lead['id']}/score", json={"score": "Z"}, params={"format": "json"}).status_code == 422
    notes = [e["note"] for e in seeded.get(f"/leads/{lead['id']}", params={"format": "json"}).json()["events"]]
    assert any("A → C" in n for n in notes if n)


def test_tags_observacoes_servicos_e_proxima_acao(seeded):
    lid = get_id(seeded)
    r = seeded.post(f"/leads/{lid}/tags", json={"add": "Quente!, indicação"}, params={"format": "json"}).json()
    assert r["tags"] == ["quente", "indicação"]
    assert leads_json(seeded, tag="quente")["total"] == 1
    r = seeded.post(f"/leads/{lid}/tags", json={"remove": "quente"}, params={"format": "json"}).json()
    assert r["tags"] == ["indicação"]
    assert seeded.post(f"/leads/{lid}/notes", json={"notes": " dona Ana "}, params={"format": "json"}).json()["notes"] == "dona Ana"
    r = seeded.post(f"/leads/{lid}/offered", json={"services": ["landing", "nao_existe", "avaliacoes"]},
                    params={"format": "json"}).json()
    assert r["offered"] == ["landing", "avaliacoes"]
    r = seeded.post(f"/leads/{lid}/next-action", json={"label": "Ligar", "date": "2026-12-01"},
                    params={"format": "json"}).json()
    assert r["next_action"] == "Ligar" and r["next_action_at"] == "2026-12-01T12:00:00"  # 9h de Brasília
    assert seeded.post(f"/leads/{lid}/next-action", json={"date": "ontem"}, params={"format": "json"}).status_code == 422


def test_checagem_manual_do_perfil(client):
    client.post("/leads/manual", json={"name": "Barbearia Sem Nota", "niche": "barbearia", "phone": "31988887777"},
                params={"format": "json"})
    lead = first(client)
    assert lead["rating"] is None
    r = client.post(f"/leads/{lead['id']}/gmb-check", json={"rating": "4,8", "reviews": "150", "photos": "12", "hours": "on"},
                    params={"format": "json"}).json()
    assert r["gmb_check"]["rating"] == 4.8 and r["gmb_check"]["reviews"] == 150 and r["score"] == "A"


# --------------------------------------------------------------------------- não contatar e LGPD
def test_nao_contatar_esconde_de_tudo_e_bloqueia(seeded):
    lead = first(seeded, site="sem", score="A")
    lid, name = lead["id"], lead["name"]
    total = leads_json(seeded)["total"]
    funil = seeded.get("/funil", params={"format": "json"}).json()["total"]
    metricas = seeded.get("/metricas", params={"format": "json"}).json()["total"]
    r = seeded.post(f"/leads/{lid}/dnc", json={"note": "pediu para parar"}, params={"format": "json"})
    assert r.json() == {"id": lid, "do_not_contact": True, "status": "DESCARTADO"}

    assert leads_json(seeded)["total"] == total - 1
    assert lid not in [l["id"] for l in leads_json(seeded, limit=1000)["leads"]]
    assert lid not in [l["id"] for l in leads_json(seeded, status="DESCARTADO", show_archived="1")["leads"]]
    assert seeded.get("/funil", params={"format": "json"}).json()["total"] == funil - 1
    assert seeded.get("/metricas", params={"format": "json"}).json()["total"] == metricas - 1
    assert seeded.get("/api/command", params={"q": name.lower()}).json()["leads"] == []
    assert name not in seeded.get("/export.csv").text
    assert name not in seeded.get("/leads?format=csv").text
    for page in ("/", "/leads", "/funil", "/sessao", "/leads?view=mapa"):
        assert name not in seeded.get(page).text, page
    today = seeded.get("/", params={"format": "json"}).json()
    assert lid not in [l["id"] for k in ("approach", "followups", "talks") for l in today[k]]
    assert lid not in seeded.get("/sessao", params={"format": "json"}).json()["queue"]

    j = {"format": "json"}
    assert seeded.post(f"/leads/{lid}/site", params=j).status_code == 409
    assert seeded.post(f"/leads/{lid}/outreach", json={}, params=j).status_code == 409
    assert seeded.post(f"/leads/{lid}/sent", json={}, params=j).status_code == 409
    assert seeded.get(f"/leads/{lid}/proposta", params=j).status_code == 409
    assert seeded.post(f"/leads/{lid}/proposta", json={}, params=j).status_code == 409
    assert seeded.get(f"/leads/{lid}/diagnostico", params=j).status_code == 409
    assert seeded.patch(f"/leads/{lid}/status", json={"status": "ABORDADO"}, params=j).status_code == 409
    seeded.post("/leads/bulk", json={"ids": [lid], "action": "status", "status": "ABORDADO"}, params=j)
    seeded.post("/leads/bulk", json={"ids": [lid], "action": "samples"}, params=j)
    d = seeded.get(f"/leads/{lid}", params=j).json()
    assert d["status"] == "DESCARTADO" and d["opportunity"] == 0


def test_excluir_de_vez_lgpd(client):
    body = {"niche": "salão de beleza", "location": "Belo Horizonte"}
    client.post("/buscas", json=body, params={"format": "json"})
    lead = first(client)
    lid = lead["id"]
    client.post(f"/leads/{lid}/site", params={"format": "json"})
    slug = client.get(f"/leads/{lid}", params={"format": "json"}).json()["id"]
    assert client.post(f"/leads/{lid}/delete", json={}, params={"format": "json"}).status_code == 422
    r = client.post(f"/leads/{lid}/delete", json={"confirm": "sim", "reason": "pedido do dono"}, params={"format": "json"})
    assert r.json() == {"deleted": lid} and slug
    assert client.get(f"/leads/{lid}", params={"format": "json"}).status_code == 404
    from app.db import new_session
    from app.models import DeletionLog, LeadEvent, Site

    s = new_session()
    try:
        log = s.query(DeletionLog).one()
        assert log.reason == "pedido do dono" and lead["place_id"] not in log.place_id_hash and len(log.place_id_hash) == 64
        assert s.query(LeadEvent).filter_by(lead_id=lid).count() == 0 and s.query(Site).filter_by(lead_id=lid).count() == 0
    finally:
        s.close()
    again = client.post("/buscas", json=body, params={"format": "json"}).json()
    assert again["created"] == 0, "lugar excluído a pedido não volta numa busca nova"
    assert lead["name"] not in client.get("/export.csv").text
    assert client.get("/config", params={"format": "json"}).json()["deletions"] == 1


# --------------------------------------------------------------------------- lote e CSV
def test_acoes_em_lote(seeded):
    ids = [l["id"] for l in leads_json(seeded, site="sem")["leads"][:3]]
    j = {"format": "json"}
    assert seeded.post("/leads/bulk", json={"ids": ids, "action": "tag", "tag": "lote 1"}, params=j).json()["done"] == 3
    assert leads_json(seeded, tag="lote 1")["total"] == 3
    assert seeded.post("/leads/bulk", json={"ids": ids, "action": "status", "status": "ANALISADO"}, params=j).json()["done"] == 3
    assert seeded.post("/leads/bulk", json={"ids": ids, "action": "samples"}, params=j).json()["done"] == 3
    assert {l["status"] for l in leads_json(seeded, tag="lote 1")["leads"]} == {"AMOSTRA"}
    csv = seeded.post("/leads/bulk", json={"ids": ids, "action": "csv"}, params=j)
    assert csv.headers["content-type"].startswith("text/csv") and len(csv.text.strip().splitlines()) == 4
    total = leads_json(seeded)["total"]
    seeded.post("/leads/bulk", json={"ids": ids[:2], "action": "archive"}, params=j)
    assert leads_json(seeded)["total"] == total - 2
    assert leads_json(seeded, show_archived="1")["total"] == total
    seeded.post("/leads/bulk", json={"ids": ids[:2], "action": "unarchive"}, params=j)
    seeded.post("/leads/bulk", json={"ids": ids[:1], "action": "dnc"}, params=j)
    assert leads_json(seeded)["total"] == total - 1
    assert seeded.post("/leads/bulk", json={"ids": [], "action": "tag", "tag": "x"}, params=j).status_code == 422
    assert seeded.post("/leads/bulk", json={"ids": ids, "action": "explodir"}, params=j).status_code == 422


def test_lote_por_formulario(seeded):
    ids = [str(l["id"]) for l in leads_json(seeded)["leads"][:2]]
    r = seeded.post("/leads/bulk", data={"ids": ids, "action": "tag", "tag": "form"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "bulk-done" in r.headers["hx-trigger"]
    assert leads_json(seeded, tag="form")["total"] == 2


def test_csv_abre_no_excel_e_nao_vira_formula(client):
    client.post("/leads/manual", json={"name": "=HYPERLINK(\"http://x\";\"clique\")", "niche": "padaria",
                                       "neighborhood": "+Centro"}, params={"format": "json"})
    lid = first(client)["id"]
    client.post(f"/leads/{lid}/notes", json={"notes": "@cmd"}, params={"format": "json"})
    r = client.get("/leads", params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf"), "BOM para o Excel abrir os acentos"
    header, row = r.text.lstrip("﻿").strip().splitlines()[:2]
    assert header.startswith("name;niche;sector")
    assert "'=HYPERLINK" in row and "'+Centro" in row and "'@cmd" in row
    full = client.get("/export.csv")
    assert "'=HYPERLINK" in full.text and "radar-leads-" in full.headers["content-disposition"]


def test_csv_respeita_os_filtros(seeded):
    rows = seeded.get("/leads", params={"format": "csv", "niche": "salao"}).text.strip().splitlines()
    assert len(rows) - 1 == leads_json(seeded, niche="salao")["total"]


# --------------------------------------------------------------------------- funil, hoje, sessão, métricas
def test_funil_conta_por_etapa_e_por_nicho(seeded):
    f = seeded.get("/funil", params={"format": "json"}).json()
    assert f["total"] == leads_json(seeded)["total"] == sum(f["counts"].values())
    assert set(f["counts"]) >= {"NOVO", "ANALISADO", "AMOSTRA", "ABORDADO", "FOLLOWUP", "CONVERSA", "PROPOSTA", "FECHADO",
                                "PRODUCAO", "ENTREGUE", "SEM_RESPOSTA", "PERDIDO", "DESCARTADO"}
    assert f["by_niche"]["salao"] > 0
    assert seeded.get("/funnel", follow_redirects=False).status_code == 307
    r = seeded.get("/funil", headers={"HX-Request": "true", "HX-Target": "kanban"})
    assert r.status_code == 200 and "<html" not in r.text


def test_hoje_e_sessao(seeded):
    t = seeded.get("/", params={"format": "json"}).json()
    assert t["approach"] and t["week_goal"] == 5 and t["next_step"]["kind"] == "approach"
    s = seeded.get("/sessao", params={"format": "json"}).json()
    assert s["remaining"] > 1 and s["lead"]["id"] == s["queue"][0]
    s2 = seeded.get("/sessao", params={"format": "json", "skip": str(s["queue"][0])}).json()
    assert s2["lead"]["id"] == s["queue"][1] and s2["remaining"] == s["remaining"] - 1
    html = seeded.get("/sessao").text
    assert "Marquei como enviado" in html and "Copiar" in html


def test_meta_da_semana_conta_as_abordagens(seeded):
    lid = get_id(seeded, site="sem", score="A")
    seeded.post(f"/leads/{lid}/sent", json={}, params={"format": "json"})
    assert seeded.get("/", params={"format": "json"}).json()["week_done"] == 1


def test_metricas(seeded):
    lid = get_id(seeded, site="sem", score="A")
    seeded.post(f"/leads/{lid}/sent", json={}, params={"format": "json"})
    seeded.patch(f"/leads/{lid}/status", json={"status": "FECHADO", "value": "2000"}, params={"format": "json"})
    m = seeded.get("/metricas", params={"format": "json"}).json()
    assert m["won_month"] == 1 and m["revenue_month"] == 2000.0 and m["by_niche"] and len(m["weeks"]) >= 4


# --------------------------------------------------------------------------- datas em Brasília
def test_o_dia_vira_a_meia_noite_de_brasilia():
    from app.services import timeutil

    late = datetime(2026, 11, 10, 2, 30)  # 23:30 do dia 9 em Brasília
    assert timeutil.day_start(late) == datetime(2026, 11, 9, 3, 0)
    assert timeutil.fmt(late) == "09/11/2026 23:30"
    assert timeutil.week_start(late) == datetime(2026, 11, 9, 3, 0)  # segunda-feira
    assert timeutil.month_start(late) == datetime(2026, 11, 1, 3, 0)
    assert timeutil.from_local(datetime(2026, 12, 1, 9)) == datetime(2026, 12, 1, 12)
    assert timeutil.fmt_day(datetime(2026, 11, 10, 15), late) == "amanhã"


def test_cota_so_conta_o_dia_de_brasilia(session):
    from app.models import Search
    from app.services import quota, timeutil

    start = timeutil.day_start()
    session.add(Search(niche="a", location_text="x", provider="google", requests_made=5,
                       created_at=start - __import__("datetime").timedelta(minutes=1)))
    session.add(Search(niche="b", location_text="x", provider="google", requests_made=2, created_at=start))
    session.commit()
    assert quota.requests_today(session, "google") == 2


def test_datas_na_tela_em_brasilia(seeded):
    lid = get_id(seeded)
    seeded.post(f"/leads/{lid}/next-action", json={"label": "Ligar", "date": "2031-03-05"}, params={"format": "json"})
    html = seeded.get(f"/leads/{lid}", headers={"HX-Request": "true"}).text
    assert "05/03/2031" in html
