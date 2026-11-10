"""Amostras de site, mensagens de abordagem, proposta e diagnóstico."""
import re

import pytest

from conftest import get_id

J = {"format": "json"}
TEMPLATES = ["landing", "institucional", "cardapio", "agendamento", "links"]


# --------------------------------------------------------------------------- amostras
@pytest.mark.parametrize("template", TEMPLATES)
def test_cada_modelo_gera_amostra_com_noindex(seeded, env, template):
    lid = get_id(seeded, site="sem", score="A")
    r = seeded.post(f"/leads/{lid}/site", json={"template": template}, params=J)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["template"] == template and d["local_url"] == f"/previews/{d['slug']}/"
    folder = env / "previews" / d["slug"]
    html = (folder / "index.html").read_text(encoding="utf-8")
    name = seeded.get(f"/leads/{lid}", params=J).json()["name"]
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert 'class="amostra"' in html and "Não é o site oficial" in html
    assert name.replace("&", "&amp;") in html and '<html lang="pt-BR"' in html
    assert (folder / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert (folder / "style.css").is_file() and (folder / "base.css").is_file()
    assert not re.search(r'(src|href)="https?://(?!wa\.me|www\.google\.com/maps|api\.whatsapp)', html), \
        "amostra não depende de arquivo de fora"
    page = seeded.get(d["local_url"])
    assert page.status_code == 200 and page.headers["x-robots-tag"] == "noindex, nofollow"
    assert seeded.get(f"/previews/{d['slug']}/style.css").status_code == 200
    assert seeded.get(f"/previews/{d['slug']}", follow_redirects=False).status_code == 307


def test_amostra_muda_a_etapa_e_gerar_de_novo_nao_duplica(seeded):
    lid = get_id(seeded, site="sem", score="A")
    a = seeded.post(f"/leads/{lid}/site", params=J).json()
    b = seeded.post(f"/leads/{lid}/site", json={"template": "links"}, params=J).json()
    assert a["slug"] == b["slug"] and b["template"] == "links"
    d = seeded.get(f"/leads/{lid}", params=J).json()
    assert d["status"] == "AMOSTRA"
    assert [e["type"] for e in d["events"]].count("site") == 2
    from app.db import new_session
    from app.models import Site

    s = new_session()
    try:
        assert s.query(Site).filter_by(lead_id=lid).count() == 1
    finally:
        s.close()


def test_modelo_invalido_e_previa_que_nao_existe(seeded):
    lid = get_id(seeded)
    assert seeded.post(f"/leads/{lid}/site", json={"template": "../etc"}, params=J).status_code == 422
    assert seeded.get("/previews/nao-existe/").status_code == 404
    assert seeded.get("/previews/..%2F..%2Fapp/main.py").status_code == 404


def test_modelo_segue_o_servico_escolhido(seeded):
    lid = get_id(seeded, niche="restaurante")
    seeded.post(f"/leads/{lid}/offered", json={"services": ["cardapio"]}, params=J)
    assert seeded.post(f"/leads/{lid}/site", params=J).json()["template"] == "cardapio"


def test_amostra_escapa_o_nome(client, env):
    client.post("/leads/manual", json={"name": "<script>alert(1)</script> & Cia", "niche": "padaria",
                                       "phone": "31988887777"}, params=J)
    lid = get_id(client)
    d = client.post(f"/leads/{lid}/site", params=J).json()
    html = (env / "previews" / d["slug"] / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_link_publico_das_amostras(seeded, monkeypatch):
    from app.config import get_settings

    lid = get_id(seeded, site="sem", score="A")
    local = seeded.post(f"/leads/{lid}/site", params=J).json()
    assert local["link_is_local"] is True and local["preview_url"].startswith("http://localhost:8000/previews/")
    monkeypatch.setenv("PREVIEWS_PUBLIC_URL", "https://amostras.example.pages.dev/")
    get_settings.cache_clear()
    pub = seeded.post(f"/leads/{lid}/site", params=J).json()
    assert pub["link_is_local"] is False
    assert pub["preview_url"] == f"https://amostras.example.pages.dev/{pub['slug']}/"
    msg = seeded.post(f"/leads/{lid}/outreach", json={}, params=J).json()
    assert pub["preview_url"] in msg["text"] and msg["link_is_local"] is False


# --------------------------------------------------------------------------- mensagens
@pytest.mark.parametrize("channel", ["whatsapp", "instagram", "email", "ligacao"])
def test_rascunho_nos_4_canais(seeded, channel):
    lead = seeded.get("/leads", params={**J, "site": "sem", "score": "A"}).json()["leads"][0]
    r = seeded.post(f"/leads/{lead['id']}/outreach", json={"channel": channel}, params=J)
    assert r.status_code == 200, r.text
    d = r.json()
    assert lead["name"] in d["text"] and d["sent_at"] is None and d["by_ai"] is None
    assert "{" not in d["text"] and "None" not in d["text"]
    if channel == "whatsapp":
        assert d["whatsapp_url"].startswith("https://wa.me/55")
    else:
        assert d["whatsapp_url"] is None
    if channel == "email":
        assert d["text"].startswith("Assunto: ")
    if channel == "ligacao":
        assert "ROTEIRO DE LIGAÇÃO" in d["text"] and "Não contatar" in d["text"]


def test_rascunho_nao_envia_e_nao_muda_a_etapa(seeded):
    lid = get_id(seeded, site="sem", score="A")
    before = seeded.get(f"/leads/{lid}", params=J).json()["status"]
    seeded.post(f"/leads/{lid}/outreach", json={}, params=J)
    d = seeded.get(f"/leads/{lid}", params=J).json()
    assert d["status"] == before
    assert d["events"][0]["type"] == "abordagem" and "Não enviado" in d["events"][0]["note"]
    html = seeded.post(f"/leads/{lid}/outreach", data={"channel": "whatsapp"}, headers={"HX-Request": "true"}).text
    assert "Copiar" in html and "Marquei como enviado" in html
    assert not re.search(r">\s*Enviar\s*<", html)


def test_mensagem_usa_a_amostra_e_o_perfil_do_vendedor(seeded):
    lid = get_id(seeded, site="sem", score="A")
    seeded.post("/config", json={"section": "seller", "name": "Samuel Teste", "what": "faço sites", "tone": "leve",
                                 "city": "Contagem"}, params=J)
    sem = seeded.post(f"/leads/{lid}/outreach", json={}, params=J).json()["text"]
    assert "Samuel Teste" in sem and "Contagem" in sem and "Quer ver?" in sem
    site = seeded.post(f"/leads/{lid}/site", params=J).json()
    com = seeded.post(f"/leads/{lid}/outreach", json={}, params=J).json()["text"]
    assert site["preview_url"] in com


def test_marquei_como_enviado_e_follow_ups(seeded):
    lid = get_id(seeded, site="sem", score="A")
    d = seeded.post(f"/leads/{lid}/outreach", json={"kind": "primeira"}, params=J).json()
    sent = seeded.post(f"/outreach/{d['id']}/sent", params=J).json()
    assert sent["status"] == "ABORDADO" and sent["sent_at"] and sent["next_action"] == "Follow-up 1"
    first_due = sent["next_action_at"]
    for n, kind in enumerate(("followup1", "followup2", "followup3"), start=1):
        f = seeded.post(f"/leads/{lid}/outreach", json={"kind": kind}, params=J).json()
        assert f["kind"] == kind and f["text"]
        s = seeded.post(f"/outreach/{f['id']}/sent", params=J).json()
        assert s["status"] == "FOLLOWUP"
    assert s["next_action_at"] != first_due
    events = seeded.get(f"/leads/{lid}", params=J).json()["events"]
    assert [e["type"] for e in events].count("enviado") == 4
    assert seeded.post("/outreach/99999/sent", params=J).status_code == 404


def test_canal_ou_tipo_invalido(seeded):
    lid = get_id(seeded)
    assert seeded.post(f"/leads/{lid}/outreach", json={"channel": "sms"}, params=J).status_code == 422
    assert seeded.post(f"/leads/{lid}/outreach", json={"kind": "spam"}, params=J).status_code == 422
    assert seeded.post(f"/leads/{lid}/sent", json={"channel": "sms"}, params=J).status_code == 422


def test_ia_ligada_sem_chave_cai_no_modelo_fixo(seeded):
    lid = get_id(seeded, site="sem", score="A")
    base = seeded.post(f"/leads/{lid}/outreach", json={}, params=J).json()
    ai = seeded.post(f"/leads/{lid}/outreach", json={"ai": "1"}, params=J).json()
    assert ai["by_ai"] is None and ai["text"] == base["text"]


def test_analisar_conversa_colada(seeded):
    lid = get_id(seeded)
    r = seeded.post(f"/leads/{lid}/conversation", json={"text": "Oi! Gostei, quanto fica?"}, params=J).json()
    assert r["interest"] == "alto" and r["stage"] == "PROPOSTA" and r["by"] is None and r["reply"]
    r = seeded.post(f"/leads/{lid}/conversation", json={"text": "pare de me mandar mensagem"}, params=J).json()
    assert r["do_not_contact"] is True and r["stage"] == "DESCARTADO"
    assert seeded.get(f"/leads/{lid}", params=J).json()["status"] != "DESCARTADO", "só sugere; quem decide é o Samuel"
    html = seeded.post(f"/leads/{lid}/conversation", data={"text": "legal, me conta mais"}, headers={"HX-Request": "true"})
    assert html.status_code == 200 and "<html" not in html.text


# --------------------------------------------------------------------------- proposta e diagnóstico
def test_proposta_com_precos_e_validade(seeded):
    lid = get_id(seeded, site="sem", score="A")
    p = seeded.get(f"/leads/{lid}/proposta", params=J).json()
    assert p["items"] and p["total"] is None and p["saved"] is False and p["validity_days"] == 7
    key = p["items"][0]["key"]
    sim = seeded.get(f"/leads/{lid}/proposta", params={**J, f"preco_{key}": "1.500,00"}).json()
    assert sim["total"] == 1500.0 or sim["monthly"] == 1500.0
    r = seeded.post(f"/leads/{lid}/proposta", json={f"preco_{key}": "1800", "validity_days": "10", "notes": "50% na entrada"},
                    params=J)
    assert r.status_code == 201 and r.json()["validity_days"] == 10
    saved = seeded.get(f"/leads/{lid}/proposta", params=J).json()
    assert saved["saved"] is True and [i["price"] for i in saved["items"]] == [1800.0]
    d = seeded.get(f"/leads/{lid}", params=J).json()
    assert d["status"] != "PROPOSTA", "salvar a proposta não muda a etapa"
    assert d["events"][0]["type"] == "proposta"
    html = seeded.get(f"/leads/{lid}/proposta").text
    assert "1800,00" in html and "50% na entrada" in html and "Proposta válida por" in html
    assert "R$ 1.800" in html


def test_proposta_pelo_formulario_redireciona(seeded):
    lid = get_id(seeded, site="sem", score="A")
    r = seeded.post(f"/leads/{lid}/proposta", data={"validity_days": "abc"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/leads/{lid}/proposta"


def test_diagnostico_de_uma_pagina(seeded):
    lid = get_id(seeded, site="sem", score="A")
    d = seeded.get(f"/leads/{lid}/diagnostico", params=J).json()
    assert d["problems"] and d["services"] and isinstance(d["dims"], dict)
    html = seeded.get(f"/leads/{lid}/diagnostico").text
    assert d["problems"][0] in html.replace("&#39;", "'") and '<html lang="pt-BR"' in html
