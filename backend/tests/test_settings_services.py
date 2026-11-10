"""Configurações, catálogo de serviços editável e tela Serviços por categoria."""
from conftest import get_id

J = {"format": "json"}


def cfg(client) -> dict:
    return client.get("/config", params=J).json()


def test_configuracoes_padrao(client):
    c = cfg(client)
    assert c["provider"] == "mock" and c["limit"] == 30 and c["weekly_goal"] == 5 and c["cadence"] == [3, 5, 7]
    assert c["has_google_key"] is False and c["has_password"] is False and c["proposal_validity"] == 7
    assert c["preview_link_is_local"] is True and c["franchises"]


def test_franquias_rebaixam_a_nota(seeded):
    lead = seeded.get("/leads", params={**J, "score": "A"}).json()["leads"][0]
    word = lead["name"].split()[0]
    r = seeded.post("/config", json={"section": "franchises", "franchises": f"{word}\nOutra Rede, {word}"}, params=J)
    assert r.status_code == 200 and r.json()["franchises"] == [word, "Outra Rede"]
    d = seeded.get(f"/leads/{lead['id']}", params=J).json()
    assert d["score"] == "C" and "Franquia" in d["score_reason"]
    assert lead["id"] not in [l["id"] for l in seeded.get("/leads", params={**J, "hide_franchises": "1", "limit": 500}).json()["leads"]]


def test_meta_cadencia_e_validade(seeded):
    r = seeded.post("/config", json={"section": "goal", "weekly_goal": "8", "cadence": "2, 4", "proposal_validity": "15"},
                    params=J).json()
    assert r["weekly_goal"] == 8 and r["cadence"] == [2, 4] and r["proposal_validity"] == 15
    assert seeded.get("/", params=J).json()["week_goal"] == 8
    lid = get_id(seeded, site="sem", score="A")
    sent = seeded.post(f"/leads/{lid}/sent", json={}, params=J).json()
    from datetime import datetime

    days = (datetime.fromisoformat(sent["next_action_at"]) - datetime.utcnow()).days
    assert days in (1, 2), "follow-up 1 em 2 dias, pela cadência nova"
    for bad in ({"weekly_goal": "0"}, {"cadence": "0"}, {"cadence": "a,b"}, {"proposal_validity": "400"},
                {"cadence": "1,2,3,4,5,6,7"}):
        assert seeded.post("/config", json={"section": "goal", **bad}, params=J).status_code == 422


def test_perfil_do_vendedor(client):
    assert client.post("/config", json={"section": "seller", "name": ""}, params=J).status_code == 422
    r = client.post("/config", json={"section": "seller", "name": "  Samuel  V. ", "what": "sites", "tone": "leve",
                                     "city": "BH"}, params=J).json()
    assert r["seller"] == {"name": "Samuel V.", "what": "sites", "tone": "leve", "city": "BH"}


def test_limites_por_nicho(seeded):
    lead = seeded.get("/leads", params={**J, "score": "A", "niche": "salao"}).json()["leads"][0]
    r = seeded.post("/config", json={"section": "limits", "niche": "salao", "min_rating": "4,9", "min_reviews": "5000"},
                    params=J).json()
    assert r["niche_limits"]["salao"] == {"min_rating": 4.9, "min_reviews": 5000}
    assert seeded.get(f"/leads/{lead['id']}", params=J).json()["score"] == "B"
    seeded.post("/config", json={"section": "limits", "niche": "salao", "reset": "1"}, params=J)
    assert seeded.get(f"/leads/{lead['id']}", params=J).json()["score"] == "A"
    assert seeded.post("/config", json={"section": "limits", "niche": "nao-existe"}, params=J).status_code == 422
    assert seeded.post("/config", json={"section": "limits", "niche": "salao", "min_rating": "9"}, params=J).status_code == 422


def test_plataforma_extra(client):
    client.post("/leads/manual", json={"name": "Bistrô", "niche": "restaurante", "phone": "31988887777",
                                       "website_url": "https://bistro.meucardapio.example/loja"}, params=J)
    lid = get_id(client)
    assert client.get(f"/leads/{lid}", params=J).json()["site_status"] == "own"
    r = client.post("/config", json={"section": "platforms", "platforms": "meucardapio.example = Meu Cardápio\nlixo"},
                    params=J).json()
    assert r["extra_platforms"] == {"meucardapio.example": "Meu Cardápio"}
    d = client.get(f"/leads/{lid}", params=J).json()
    assert d["site_status"] == "platform" and d["site_platform"] == "Meu Cardápio"


def test_liga_e_desliga_ia_e_analise(client):
    r = client.post("/config", json={"section": "toggles", "site_analysis": "on", "ai_enabled": "on"}, params=J).json()
    assert r["site_analysis"] is True and r["ai_enabled"] is True and r["ai_keys"] == {"gemini": False, "groq": False}
    r = client.post("/config", json={"section": "toggles"}, params=J).json()
    assert r["site_analysis"] is False and r["ai_enabled"] is False
    assert client.post("/config", json={"section": "xyz"}, params=J).status_code == 422


def test_config_html(client):
    r = client.post("/config", data={"section": "seller", "name": "Samuel", "what": "x", "tone": "y", "city": "BH"})
    assert r.status_code == 200 and '<html lang="pt-BR"' in r.text


def test_aviso_de_banco_no_onedrive(client, monkeypatch, tmp_path):
    from app.config import get_settings

    folder = tmp_path / "OneDrive" / "dados"
    folder.mkdir(parents=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(folder / 'radar.db').as_posix()}")
    get_settings.cache_clear()
    assert cfg(client)["db_in_onedrive"] is True


# --------------------------------------------------------------------------- serviços
def test_catalogo_de_servicos_sem_preco_inventado(client):
    s = client.get("/servicos", params=J).json()
    assert len(s["services"]) == 14
    assert all(x["price_min"] is None and x["price_max"] is None for x in s["services"]), "preço só o Samuel define"
    assert {m["sector"] for m in s["matrix"]} and sum(len(m["niches"]) for m in s["matrix"]) >= 100
    html = client.get("/servicos").text
    assert "preço a definir" in html.lower()


def test_editar_servico_preco_e_desativar(seeded):
    r = seeded.post("/servicos/landing", json={"name": "Landing page", "price_min": "1.200,00", "price_max": "800"},
                    params=J)
    assert r.status_code == 200, r.text
    assert r.json()["price_min"] == 800.0 and r.json()["price_max"] == 1200.0 and "R$ 800" in r.json()["price_text"]
    lid = seeded.get("/leads", params={**J, "service": "landing"}).json()["leads"][0]["id"]
    assert any(i["key"] == "landing" for i in seeded.get(f"/leads/{lid}/proposta", params=J).json()["items"])
    off = seeded.post("/servicos/landing", json={"active": "0"}, params=J).json()
    assert off["active"] is False
    d = seeded.get(f"/leads/{lid}", params=J).json()
    assert "landing" not in [r["key"] for r in d["recommendations"]], "serviço inativo some das recomendações"
    assert seeded.get("/leads", params={**J, "service": "landing"}).json()["total"] == 0
    for bad in ({"price_min": "abc"}, {"price_min": "-5"}, {"name": " "}):
        assert seeded.post("/servicos/landing", json=bad, params=J).status_code == 422
    assert seeded.post("/servicos/nao-existe", json={}, params=J).status_code == 404


def test_servico_pelo_formulario(seeded):
    r = seeded.post("/servicos/avaliacoes", data={"_form": "1", "name": "Avaliações no Google", "active": "on",
                                                  "price_min": "300"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text and "R$ 300" in r.text


def test_demanda_por_nicho(seeded):
    s = seeded.get("/servicos", params=J).json()
    assert s["demand"] and s["demand"][0]["leads"] >= s["demand"][-1]["leads"]
    total = sum(x["leads"] for x in s["services"])
    assert total > 0
    row = next(n for m in s["matrix"] for n in m["niches"] if n["niche"] == "salao")
    assert row["leads"] > 0 and row["main"] in row["recommended"]
