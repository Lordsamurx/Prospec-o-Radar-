"""Filtros da lista: cada um e combinados. Usa os 72 fictícios do seed."""
import pytest
from sqlalchemy import select

from app.models import Lead
from app.schemas import FilterParams
from app.services import filters, lead_service


def run(session, ctx=None, **kw):
    f = FilterParams(show_mock=True, **kw)
    return session.scalars(filters.build_query(f, ctx.franchises if ctx else [])).all()


def test_seed_spreads_over_many_sectors(seeded, session):
    leads = run(session)
    assert len(leads) == 72
    assert len({l.sector for l in leads}) >= 8 and len({l.niche for l in leads}) >= 30


def test_mock_hidden_by_default(seeded, session):
    assert session.scalars(filters.build_query(FilterParams())).all() == []


@pytest.mark.parametrize("kw,check", [
    ({"niche": ["barbearia"]}, lambda l: l.niche == "barbearia"),
    ({"niche": ["barbearia", "dentista"]}, lambda l: l.niche in ("barbearia", "dentista")),
    ({"sector": ["alimentacao"]}, lambda l: l.sector == "alimentacao"),
    ({"site": "sem"}, lambda l: l.site_status in ("none", "social", "platform")),
    ({"site": "com"}, lambda l: l.site_status == "own"),
    ({"site_status": ["social"]}, lambda l: l.site_status == "social"),
    ({"score": ["A"]}, lambda l: l.score == "A"),
    ({"score": ["A", "B"]}, lambda l: l.score in ("A", "B")),
    ({"min_rating": 4.5}, lambda l: l.rating >= 4.5),
    ({"min_reviews": 50}, lambda l: l.reviews_count >= 50),
    ({"max_reviews": 10}, lambda l: l.reviews_count <= 10),
    ({"has_phone": "no"}, lambda l: not l.phone),
    ({"phone_type": "landline"}, lambda l: l.phone_type == "landline"),
    ({"operational_only": True}, lambda l: l.business_status == "OPERATIONAL"),
    ({"min_photos": 10}, lambda l: l.photos_count >= 10),
    ({"has_hours": "no"}, lambda l: not l.opening_hours),
    ({"neighborhood": "savassi"}, lambda l: l.neighborhood == "Savassi"),
    ({"overdue": False, "min_rating": 4.8}, lambda l: l.rating >= 4.8),
    ({"profile": ["so_rede_social"]}, lambda l: l.profile == "so_rede_social"),
    ({"service": ["cardapio"]}, lambda l: "cardapio" in l.rec_list),
    ({"status": ["NOVO"]}, lambda l: l.status == "NOVO"),
    ({"q": "barbearia"}, lambda l: "barbearia" in l.name.lower()),
])
def test_each_filter(seeded, session, kw, check):
    got = run(session, **kw)
    assert 0 < len(got) < 72
    assert all(check(l) for l in got)


def test_combined_filters_narrow_the_count(seeded, session):
    a = run(session, sector=["beleza"])
    b = run(session, sector=["beleza"], site="sem")
    c = run(session, sector=["beleza"], site="sem", score=["A"], phone_type="mobile")
    assert len(a) > len(b) > len(c) > 0
    assert all(l.sector == "beleza" and l.site_status != "own" and l.score == "A" and l.phone_type == "mobile" for l in c)


def test_hide_franchises(seeded, session, ctx):
    assert len(run(session, ctx, hide_franchises=True)) < 72


def test_radius_from_neighborhood(seeded, session):
    near = run(session, neighborhood="Savassi", radius_km=1)
    far = run(session, neighborhood="Savassi", radius_km=8)
    assert 0 < len(near) < len(far)


def test_never_contacted_and_tag(seeded, session, ctx):
    lead = session.scalars(select(Lead).where(Lead.score == "A")).first()
    lead_service.mark_sent(session, lead, ctx)
    lead_service.add_tag(session, lead, "Quente")
    assert lead.id not in {l.id for l in run(session, never_contacted=True)}
    assert [l.id for l in run(session, tag=["quente"])] == [lead.id]


def test_archived_hidden_unless_asked(seeded, session):
    lead = session.scalars(select(Lead)).first()
    lead.archived = True
    session.commit()
    assert lead.id not in {l.id for l in run(session)}
    assert lead.id in {l.id for l in run(session, show_archived=True)}


def test_sort_by_score_then_opportunity(seeded, session):
    got = run(session)
    rank = {"A": 0, "B": 1, "C": 2, "DESCARTE": 3}
    keys = [(rank[l.score], -l.opportunity) for l in got]
    assert keys == sorted(keys)


def test_invalid_filter_does_not_reset_the_others():
    f = FilterParams.from_query([("min_rating", "abc"), ("niche", "barbearia"), ("score", "Z,A"), ("site", "talvez")])
    assert f.niche == ["barbearia"] and f.score == ["A"] and f.min_rating is None and f.site is None


def test_query_roundtrip_and_chips():
    f = FilterParams.from_query([("niche", "barbearia,dentista"), ("site", "sem"), ("min_rating", "4,5")])
    assert f.min_rating == 4.5
    assert ("niche", "dentista") in f.to_query() and ("min_rating", "4.5") in f.to_query()
    labels = [c["label"] for c in filters.chips(f)]
    assert "Nicho: Barbearia" in labels and "Site: sem site" in labels
    assert all("remove_qs" in c for c in filters.chips(f))
