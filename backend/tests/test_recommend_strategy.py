"""Recomendação de serviços (uma regra por teste), pacote e estratégia por cenário."""
from dataclasses import replace

import pytest
from conftest import lead

from app import catalog
from app.services import profile, recommend, strategy
from app.services.diagnose import diagnose


def recs(services=None, **kw):
    l = lead(**kw)
    niche = catalog.niches().get_or_other(l["niche"])
    d = diagnose(l, niche, [])
    return recommend.recommend(l, d, niche, services or catalog.services()), d, niche, l


def keys(rs, priority=None):
    return [r.key for r in rs if priority is None or r.priority == priority]


def test_no_site_booking_sector_recommends_scheduling_first():
    rs, *_ = recs()
    assert keys(rs, "principal") == ["agendamento"] and "landing" in keys(rs)


def test_no_site_food_recommends_menu_first():
    rs, *_ = recs(niche="restaurante", categories=["restaurant"])
    assert keys(rs, "principal") == ["cardapio"]


def test_no_site_other_sector_recommends_niche_default_offer():
    rs, _, niche, _ = recs(niche="oficina", categories=["car_repair"])
    assert keys(rs, "principal") == [niche.default_offer]


def test_only_social_recommends_landing_and_links():
    rs, *_ = recs(website_url="https://instagram.com/x")
    assert keys(rs, "principal") == ["landing"] and "links" in keys(rs)


def test_stuck_on_food_platform_recommends_own_menu_and_names_platform():
    rs, *_ = recs(niche="restaurante", categories=["restaurant"], website_url="https://www.ifood.com.br/x")
    assert keys(rs, "principal") == ["cardapio"] and "iFood" in rs[0].reason


def test_stuck_on_booking_platform_recommends_own_scheduling():
    rs, *_ = recs(website_url="https://x.booksy.com/a")
    assert keys(rs, "principal") == ["agendamento"] and "Booksy" in rs[0].reason


def test_weak_site_recommends_redesign():
    rs, *_ = recs(website_url="http://x.com.br")
    assert keys(rs, "principal") == ["reformulacao"]


def test_site_sale_brings_maintenance_plan():
    rs, *_ = recs()
    assert "manutencao" in keys(rs, "complemento")


def test_good_site_gets_local_seo_and_upsells_only():
    rs, *_ = recs(website_url="https://x.com.br")
    assert keys(rs, "principal") == ["seo_local"]
    assert "landing" not in keys(rs) and "carrosseis" in keys(rs, "upsell")


def test_incomplete_google_profile_recommends_optimization():
    rs, *_ = recs(photos_count=1, opening_hours=None)
    assert "gmn_otimizacao" in keys(rs)


def test_few_reviews_recommends_reviews_management():
    rs, *_ = recs(reviews_count=3)
    assert "avaliacoes" in keys(rs)


def test_low_rating_recommends_reviews_management():
    rs, *_ = recs(rating=3.9)
    assert "avaliacoes" in keys(rs)


def test_not_on_google_recommends_profile_creation_first():
    rs, *_ = recs(place_id="osm-node-1", rating=None, reviews_count=0, gmb_check={"checked": True, "exists": False})
    assert rs[0].key == "gmn_criacao" and rs[0].priority == "principal"


def test_professional_sector_gets_domain_and_email_upsell():
    rs, *_ = recs(niche="advocacia", categories=["lawyer"])
    assert "dominio_email" in keys(rs, "upsell")


def test_exactly_one_main_recommendation():
    for kw in ({}, {"website_url": "https://instagram.com/x"}, {"website_url": "https://x.com.br"},
               {"niche": "restaurante", "categories": ["restaurant"]}):
        rs, *_ = recs(**kw)
        assert len(keys(rs, "principal")) == 1


def test_inactive_service_never_appears():
    services = dict(catalog.services())
    services["agendamento"] = replace(services["agendamento"], active=False)
    services["manutencao"] = replace(services["manutencao"], active=False)
    rs, *_ = recs(services=services)
    assert "agendamento" not in keys(rs) and "manutencao" not in keys(rs) and rs


def test_package_sums_prices_and_marks_incomplete():
    services = dict(catalog.services())
    services["agendamento"] = replace(services["agendamento"], price_min=900.0, price_max=900.0)
    services["landing"] = replace(services["landing"], price_min=600.0, price_max=800.0)
    rs, *_ = recs(services=services)
    pkg = recommend.package(rs, ["agendamento", "landing"])
    assert pkg.total_min == 1500.0 and pkg.total_max == 1700.0 and pkg.complete
    assert not recommend.package(rs).complete  # manutenção e outros ainda sem preço


@pytest.mark.parametrize("kw,scenario", [
    ({"rating": None, "reviews_count": 0}, "invisivel"), ({}, "bem_avaliado_sem_site"),
    ({"website_url": "https://instagram.com/x"}, "so_rede_social"),
    ({"website_url": "https://x.booksy.com/a"}, "preso_plataforma"),
    ({"website_url": "http://x.com.br"}, "site_datado"), ({"website_url": "https://x.com.br"}, "bem_resolvido"),
])
def test_strategy_per_scenario_has_angle_hooks_and_objections(kw, scenario):
    rs, d, niche, l = recs(**kw)
    key, _ = profile.profile(d)
    st = strategy.strategy(l, d, key, niche, rs)
    assert st.scenario == scenario == key
    assert st.title and st.angle and st.next_step
    assert len(st.objections) >= 2 and all(q and a for q, a in st.objections)
    assert st.hooks


def test_strategies_differ_between_scenarios():
    a = recs()
    b = recs(website_url="https://x.com.br")
    sa = strategy.strategy(a[3], a[1], "bem_avaliado_sem_site", a[2], a[0])
    sb = strategy.strategy(b[3], b[1], "bem_resolvido", b[2], b[0])
    assert sa.angle != sb.angle and sa.objections != sb.objections
