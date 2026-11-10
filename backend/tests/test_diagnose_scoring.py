"""Raio-X, nota A/B/C (docs/06), perfil digital e índice de oportunidade. Funções puras."""
import pytest
from conftest import lead

from app import catalog
from app.services import opportunity, profile, scoring
from app.services.diagnose import Limits, diagnose

FR = ["Rede Fictícia"]


def diag(**kw):
    l = lead(**kw)
    return l, diagnose(l, catalog.niches().get_or_other(l["niche"]), FR)


# ---------------------------------------------------------------- nota (docs/06)
def test_score_a_no_site_good_rating_phone_open():
    assert scoring.score(lead())[0] == "A"


@pytest.mark.parametrize("kw,expected,fragment", [
    ({"website_url": "https://instagram.com/x"}, "B", "Instagram"),
    ({"website_url": "https://www.ifood.com.br/x"}, "B", "iFood"),
    ({"website_url": "http://salaoteste.com.br"}, "B", "sem HTTPS"),
    ({"website_url": "https://salaoteste.com.br"}, "C", "site próprio"),
    ({"reviews_count": 3}, "B", "poucas avaliações"),
    ({"rating": 3.2}, "B", "abaixo"),
    ({"phone": None}, "C", "Sem telefone"),
    ({"business_status": "CLOSED_PERMANENTLY"}, "DESCARTE", "Fechado"),
    ({"business_status": "CLOSED_TEMPORARILY"}, "DESCARTE", "temporariamente"),
    ({"categories": ["restaurant"]}, "DESCARTE", "fora do nicho"),
    ({"do_not_contact": True}, "DESCARTE", "não contatar"),
])
def test_score_rules(kw, expected, fragment):
    got, reason = scoring.score(lead(**kw))
    assert got == expected
    assert fragment.lower() in reason.lower()


def test_score_franchise_is_c():
    got, reason = scoring.score(lead(name="Salão Rede Fictícia Savassi"), FR)
    assert got == "C" and "franquia" in reason.lower()


def test_score_manual_wins_and_shows_automatic():
    got, reason = scoring.score(lead(website_url="https://salaoteste.com.br", score_manual="A"))
    assert got == "A" and "automática seria C" in reason


def test_score_osm_without_check_is_b_and_asks_to_check_maps():
    got, reason = scoring.score(lead(place_id="osm-node-1", rating=None, reviews_count=0, photos_count=0))
    assert got == "B" and "Google Maps" in reason


def test_score_osm_checked_by_samuel_can_reach_a():
    l = lead(place_id="osm-node-1", rating=None, reviews_count=0,
             gmb_check={"checked": True, "exists": True, "rating": 4.7, "reviews": 60, "photos": 9, "hours": True})
    got, reason = scoring.score(l)
    assert got == "A" and "conferido por você" in reason


def test_score_osm_checked_not_on_google_is_b():
    l = lead(place_id="osm-node-1", rating=None, reviews_count=0, gmb_check={"checked": True, "exists": False})
    assert scoring.score(l)[0] == "B"


def test_score_limits_per_niche_change_the_grade():
    l = lead(rating=4.1, reviews_count=20)
    assert scoring.score(l)[0] == "A"
    assert scoring.score(l, limits=Limits(4.5, 50))[0] == "B"


# ---------------------------------------------------------------- diagnóstico (um sinal por teste)
@pytest.mark.parametrize("url,kind", [(None, "none"), ("https://instagram.com/x", "social"),
                                      ("https://x.booksy.com/a", "platform"), ("https://sites.google.com/view/x", "platform"),
                                      ("http://x.com.br", "own_nohttps"), ("https://x.com.br", "own_ok")])
def test_diagnose_site_kind(url, kind):
    assert diag(website_url=url)[1].site_kind == kind


@pytest.mark.parametrize("check,kind", [
    ({"checked": True, "down": True}, "own_down"),
    ({"checked": True, "https": False}, "own_nohttps"),
    ({"checked": True, "https": True, "viewport": False}, "own_weak"),
    ({"checked": True, "https": True, "builder": "Wix"}, "own_weak"),
    ({"checked": True, "https": True, "slow": True, "elapsed_ms": 6200}, "own_weak"),
    ({"checked": True, "https": True, "viewport": True}, "own_ok"),
])
def test_diagnose_reads_site_check(check, kind):
    _, d = diag(website_url="https://x.com.br", site_check=check)
    assert d.site_kind == kind


def test_diagnose_platform_signal_names_the_platform():
    _, d = diag(website_url="https://www.ifood.com.br/delivery/x", niche="restaurante", categories=["restaurant"])
    s = d.signal("site")
    assert d.platform == "iFood" and s.tone == "ruim" and "iFood" in s.phrase


def test_diagnose_contact_signals():
    assert diag()[1].signal("contato").value == "Celular"
    assert diag(phone="(31) 3222-1111")[1].signal("contato").value == "Telefone fixo"
    assert diag(phone=None)[1].signal("contato").tone == "ruim"


def test_diagnose_google_gaps_photos_hours_reviews():
    _, d = diag(photos_count=2, opening_hours=None, reviews_count=4)
    keys = {s.key for s in d.by_dimension("google")}
    assert {"fotos", "horario", "poucas_avaliacoes"} <= keys
    assert d.signal("fotos").tone == "atencao" and d.signal("horario").tone == "atencao"


def test_diagnose_reputation_strong_and_low_rating():
    assert diag()[1].reputation_strong is True
    _, d = diag(rating=3.9)
    assert d.reputation_strong is False and d.signal("nota_baixa") is not None


def test_diagnose_osm_unknown_google_is_marked_unknown():
    _, d = diag(place_id="osm-node-9", rating=None, reviews_count=0)
    assert d.google_known is False
    assert d.dims["google"] is None and d.signal("google").tone == "desconhecido"


def test_diagnose_franchise_and_closed_signals():
    assert diag(name="Rede Fictícia Centro")[1].signal("franquia") is not None
    assert diag(business_status="CLOSED_PERMANENTLY")[1].signal("fechado") is not None


def test_diagnose_missing_items_on_homepage_become_a_signal():
    _, d = diag(website_url="https://x.com.br",
                site_check={"checked": True, "https": True, "viewport": True, "analyzed": True, "has": ["telefone"],
                            "missing": ["botão de WhatsApp", "mapa"]})
    assert d.site_missing == ["botão de WhatsApp", "mapa"] and "mapa" in d.signal("site_falta").phrase


def test_diagnose_pagespeed_signal():
    assert diag(website_url="https://x.com.br", pagespeed_score=38)[1].signal("pagespeed").tone == "ruim"


# ---------------------------------------------------------------- perfil digital (os seis)
@pytest.mark.parametrize("kw,expected", [
    ({"rating": None, "reviews_count": 0}, "invisivel"),
    ({}, "bem_avaliado_sem_site"),
    ({"website_url": "https://instagram.com/x"}, "so_rede_social"),
    ({"website_url": "https://x.booksy.com/a"}, "preso_plataforma"),
    ({"website_url": "http://x.com.br"}, "site_datado"),
    ({"website_url": "https://x.com.br"}, "bem_resolvido"),
])
def test_profile_six_types(kw, expected):
    key, reason = profile.profile(diag(**kw)[1])
    assert key == expected and reason


# ---------------------------------------------------------------- índice de oportunidade
def test_opportunity_is_high_without_site_and_low_with_good_site():
    hot, parts = opportunity.opportunity(diag()[1])
    cold, _ = opportunity.opportunity(diag(website_url="https://x.com.br")[1])
    assert hot >= 80 and cold < 50 and hot > cold
    assert sum(p.points for p in parts) == hot
    assert all(p.points <= p.cap for p in parts if p.cap)


def test_opportunity_zero_for_closed_out_of_niche_or_do_not_contact():
    assert opportunity.opportunity(diag(business_status="CLOSED_PERMANENTLY")[1])[0] == 0
    assert opportunity.opportunity(diag(categories=["restaurant"])[1])[0] == 0
    assert opportunity.opportunity(diag()[1], do_not_contact=True)[0] == 0


def test_opportunity_franchise_is_cut():
    normal, _ = opportunity.opportunity(diag()[1])
    cut, parts = opportunity.opportunity(diag(name="Rede Fictícia Sion")[1])
    assert cut < normal and any(p.key == "franquia" for p in parts)


def test_opportunity_mobile_beats_landline():
    assert opportunity.opportunity(diag()[1])[0] > opportunity.opportunity(diag(phone="(31) 3222-1111")[1])[0]
