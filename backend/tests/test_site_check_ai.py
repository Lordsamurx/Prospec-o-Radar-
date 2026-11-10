"""Checagem do site do lead e IA opcional, sempre com HTTP falso (nenhuma visita real)."""
import httpx
import pytest

from app.services import ai, site_check
from conftest import get_id

J = {"format": "json"}
PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731
GOOD = """<!doctype html><html><head><meta name="viewport" content="width=device-width">
<meta name="description" content="Salão de beleza na Savassi com hora marcada"><link rel="icon" href="/f.ico">
</head><body><a href="https://wa.me/5531988887777">Zap</a><a href="tel:+553133334444">Ligar</a>
<img src="a.jpg"><img src="b.jpg"><img src="c.jpg"><iframe src="https://www.google.com/maps/embed?x"></iframe>
<a href="/outra-pagina">não seguir</a></body></html>"""


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_site_ok_com_analise():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, html=GOOD)

    r = site_check.check_site("https://salao.example.com.br/", client_for(handler), analyze=True, resolver=PUBLIC)
    assert r["checked"] and r["analyzed"] and r["https"] and not r["down"] and r["viewport"] is True
    assert "botão de WhatsApp" in r["has"] and "mapa" in r["has"] and r["missing"] == ["e-mail"]
    assert seen == ["https://salao.example.com.br/"], "uma visita só: não segue link nenhum"
    assert "html" not in r and "body" not in r, "o conteúdo da página não é guardado"


def test_analise_desligada_nao_le_a_pagina():
    r = site_check.check_site("https://salao.example.com.br/", client_for(lambda q: httpx.Response(200, html=GOOD)),
                              analyze=False, resolver=PUBLIC)
    assert r["checked"] and r["analyzed"] is False and "viewport" not in r and "has" not in r


def test_site_fora_do_ar():
    def boom(req):
        raise httpx.ConnectError("recusou")

    r = site_check.check_site("https://caiu.example.com.br", client_for(boom), resolver=PUBLIC)
    assert r["down"] is True and "não respondeu" in r["reason"]
    r = site_check.check_site("https://x.example.com.br", client_for(lambda q: httpx.Response(500)), resolver=PUBLIC)
    assert r["down"] is True and "500" in r["reason"]
    r = site_check.check_site("https://x.example.com.br", client_for(lambda q: httpx.Response(403)), resolver=PUBLIC)
    assert r["down"] is False, "bloqueio a robô não é site fora do ar"


def test_tempo_esgotado_e_certificado():
    def slow(req):
        raise httpx.ReadTimeout("demorou")

    def cert(req):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]")

    assert "Não respondeu" in site_check.check_site("https://l.example.com", client_for(slow), resolver=PUBLIC)["reason"]
    r = site_check.check_site("https://c.example.com", client_for(cert), resolver=PUBLIC)
    assert r["bad_cert"] is True and r["down"] is False and r["https"] is False


def test_sem_https_sem_viewport_e_construtor():
    html = '<html><head><meta name="generator" content="Wix.com Website Builder"></head><body>oi</body></html>'
    r = site_check.check_site("http://velho.example.com.br", client_for(lambda q: httpx.Response(200, html=html)),
                              analyze=True, resolver=PUBLIC)
    assert r["https"] is False and r["viewport"] is False and r["builder"] and "wix" in r["builder"].lower()


def test_segue_so_redirecionamento_e_no_maximo_3():
    hops = []

    def handler(req):
        hops.append(str(req.url))
        if req.url.scheme == "http":
            return httpx.Response(301, headers={"location": "https://novo.example.com.br/"})
        return httpx.Response(200, html=GOOD)

    r = site_check.check_site("http://velho.example.com.br", client_for(handler), analyze=True, resolver=PUBLIC)
    assert r["https"] is True and r["final_host"] == "novo.example.com.br" and len(hops) == 2
    loop = client_for(lambda q: httpx.Response(302, headers={"location": "/de-novo"}))
    r = site_check.check_site("https://loop.example.com.br", loop, resolver=PUBLIC)
    assert r["down"] is True and "Redirecionamentos demais" in r["reason"]


def test_redireciona_para_rede_social():
    def handler(req):
        if req.url.host == "meusalao.example.com.br":
            return httpx.Response(302, headers={"location": "https://www.instagram.com/meusalao/"})
        return httpx.Response(200, html="<html></html>")

    r = site_check.check_site("https://meusalao.example.com.br", client_for(handler), resolver=PUBLIC)
    assert r["platform_page"]


@pytest.mark.parametrize("url", ["http://localhost:8000/", "http://127.0.0.1/", "http://192.168.0.10/admin",
                                 "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data", "http://impressora.local/",
                                 "http://[::1]/"])
def test_nunca_visita_endereco_interno(url):
    called = []
    r = site_check.check_site(url, client_for(lambda q: called.append(1) or httpx.Response(200)))
    assert r.get("skipped") is True and r["checked"] is False and called == []


def test_nome_que_resolve_para_rede_interna():
    called = []
    r = site_check.check_site("https://parece-publico.example.com", client_for(lambda q: called.append(1) or httpx.Response(200)),
                              resolver=lambda h: ["10.1.2.3"])
    assert r.get("skipped") is True and called == []
    hop = client_for(lambda q: httpx.Response(302, headers={"location": "http://192.168.1.1/"}))
    assert site_check.check_site("https://ok.example.com", hop, resolver=lambda h: [h] if h[0].isdigit() else ["93.184.216.34"]).get("skipped")


def test_endereco_invalido():
    r = site_check.check_site("ftp://arquivo.example.com", client_for(lambda q: httpx.Response(200)), resolver=PUBLIC)
    assert r["down"] is True and r["reason"] == "Endereço inválido."


def test_pagina_grande_e_cortada():
    big = "<html><head></head><body>" + "x" * 2_000_000 + '<meta name="viewport" content="x"></body></html>'
    r = site_check.check_site("https://grande.example.com", client_for(lambda q: httpx.Response(200, html=big)),
                              analyze=True, resolver=PUBLIC)
    assert r["analyzed"] and r["viewport"] is False, "só lê o começo da página"


def test_pagespeed_com_resposta_falsa():
    ok = client_for(lambda q: httpx.Response(200, json={"lighthouseResult": {"categories": {"performance": {"score": 0.42}}}}))
    assert site_check.pagespeed("https://x.example.com", "", ok) == 42
    assert site_check.pagespeed("https://x.example.com", "", client_for(lambda q: httpx.Response(429))) is None
    assert site_check.pagespeed("https://x.example.com", "", client_for(lambda q: httpx.Response(200, json={}))) is None


def test_rota_de_checagem_uma_visita_por_lead(seeded, monkeypatch):
    lead = seeded.get("/leads", params={**J, "site_status": "own"}).json()["leads"][0]
    calls = []

    def fake(url, client=None, analyze=False, **kw):
        calls.append((url, analyze))
        return {"checked": True, "analyzed": analyze, "url": url, "down": True, "reason": "O site não respondeu."}

    monkeypatch.setattr(site_check, "check_site", fake)
    r = seeded.post(f"/leads/{lead['id']}/site-check", params=J)
    assert r.status_code == 200 and r.json()["site_check"]["down"] is True
    assert r.json()["site_kind"] == "own_down" and r.json()["score"] == "B"
    seeded.post(f"/leads/{lead['id']}/site-check", params=J)
    assert len(calls) == 1 and calls[0][0] == lead["website_url"], "segunda vez não visita de novo"
    seeded.post(f"/leads/{lead['id']}/site-check", params={**J, "force": "1"})
    assert len(calls) == 2
    sem_site = get_id(seeded, site_status="none")
    assert seeded.post(f"/leads/{sem_site}/site-check", params=J).status_code == 409 and len(calls) == 2


def test_analise_respeita_a_configuracao(seeded, monkeypatch):
    lead = seeded.get("/leads", params={**J, "site_status": "own"}).json()["leads"][0]
    calls = []
    monkeypatch.setattr(site_check, "check_site", lambda url, client=None, analyze=False, **kw: calls.append(analyze) or
                        {"checked": True, "analyzed": False, "url": url, "down": False, "https": True})
    seeded.post("/config", json={"section": "toggles", "site_analysis": "on"}, params=J)
    seeded.post(f"/leads/{lead['id']}/site-check", params=J)
    seeded.post("/config", json={"section": "toggles"}, params=J)
    seeded.post(f"/leads/{lead['id']}/site-check", params={**J, "force": "1"})
    assert calls == [True, False]


# --------------------------------------------------------------------------- IA
SELLER = {"name": "Samuel", "city": "BH", "what": "faço sites", "tone": "leve"}
BASE = "Oi! Montei uma amostra: https://amostras.example.dev/salao-1/"


def cfg(**kw) -> ai.AIConfig:
    return ai.AIConfig(enabled=True, gemini_key="g-teste", groq_key="q-teste", **kw)


def test_ia_desligada_ou_sem_chave_usa_o_modelo_fixo():
    called = []
    c = client_for(lambda q: called.append(1) or httpx.Response(200))
    assert ai.rewrite(BASE, {}, SELLER, "WhatsApp", ai.AIConfig(enabled=False, gemini_key="x"), c) == (BASE, None)
    assert ai.rewrite(BASE, {}, SELLER, "WhatsApp", ai.AIConfig(enabled=True), c) == (BASE, None)
    assert called == []


def test_ia_gemini_responde():
    def handler(req):
        assert req.url.host == "generativelanguage.googleapis.com" and req.headers["x-goog-api-key"] == "g-teste"
        assert "g-teste" not in str(req.url), "a chave vai no cabeçalho, não no endereço"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Olá! Veja: https://amostras.example.dev/salao-1/"}]}}]})

    assert ai.rewrite(BASE, {"nome": "Salão"}, SELLER, "WhatsApp", cfg(), client_for(handler)) == (
        "Olá! Veja: https://amostras.example.dev/salao-1/", "Gemini")


def test_ia_cai_para_o_segundo_provedor():
    hosts = []

    def handler(req):
        hosts.append(req.url.host)
        if "googleapis" in req.url.host:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Oi! https://amostras.example.dev/salao-1/"}}]})

    text, provider = ai.rewrite(BASE, {}, SELLER, "WhatsApp", cfg(), client_for(handler))
    assert provider == "Groq" and hosts == ["generativelanguage.googleapis.com", "api.groq.com"]


def test_ia_todos_falham_volta_ao_modelo_fixo():
    def boom(req):
        raise httpx.ConnectError("sem rede")

    assert ai.rewrite(BASE, {}, SELLER, "WhatsApp", cfg(), client_for(boom)) == (BASE, None)
    assert ai.rewrite(BASE, {}, SELLER, "WhatsApp", cfg(), client_for(lambda q: httpx.Response(200, json={"x": 1}))) == (BASE, None)


def test_ia_que_troca_o_link_e_descartada():
    bad = client_for(lambda q: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Veja https://outro.example/"}]}}]}))
    assert ai.rewrite(BASE, {}, SELLER, "WhatsApp", cfg(groq_model="x"), bad)[1] is None


def test_prompt_so_leva_dados_publicos():
    p = ai.rewrite_prompt(BASE, {"nome": "Salão X", "bairro": "Savassi"}, SELLER, "WhatsApp")
    assert "Salão X" in p and "não invente" in p.lower() and "g-teste" not in p
    assert "g-teste" not in repr(cfg())


def test_conversa_sem_ia_e_com_ia():
    assert ai.analyze_conversation("", {}, SELLER, cfg())["summary"] == "Cole a conversa para analisar."
    good = client_for(lambda q: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text":
        'Claro: {"summary": "Quer saber o preço.", "interest": "alto", "reply": "Mando já!", "stage": "PROPOSTA", "do_not_contact": false}'}]}}]}))
    r = ai.analyze_conversation("quanto custa?", {}, SELLER, cfg(), good)
    assert r["by"] == "Gemini" and r["interest"] == "alto" and r["reply"] == "Mando já!"
    junk = client_for(lambda q: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "não sei"}]}}]}))
    r = ai.analyze_conversation("quanto custa?", {}, SELLER, cfg(), junk)
    assert r["by"] is None and r["stage"] == "PROPOSTA", "resposta estranha da IA: vale a leitura por regras"
    r = ai.analyze_conversation_rules("já tenho site, não quero")
    assert r["stage"] == "PERDIDO" and r["do_not_contact"] is False
