"""Provedores de busca com HTTP falso: nenhuma chamada real ao Google nem ao OpenStreetMap."""
import json

import httpx
import pytest

from app.services import lead_service, quota
from app.services.providers import (GooglePlacesProvider, MockProvider, OsmProvider, ProviderError, QuotaExceeded,
                                    get_provider)
from app.services.providers.google import FIELD_MASK, TEXT_SEARCH_URL, neighborhood_from_address

KEY = "chave-de-teste-nao-real"


def place(i: int, **kw) -> dict:
    base = {"id": f"ChIJtest{i:012d}", "displayName": {"text": f"Salão {i}"},
            "formattedAddress": "R. X, 123 - Savassi, Belo Horizonte - MG, 30140-000, Brasil",
            "nationalPhoneNumber": "(31) 98888-0000", "rating": 4.7, "userRatingCount": 120,
            "types": ["hair_salon"], "businessStatus": "OPERATIONAL", "photos": [{}] * 6,
            "regularOpeningHours": {"weekdayDescriptions": ["segunda: 09:00–18:00"]},
            "location": {"latitude": -19.93, "longitude": -43.93}}
    base.update(kw)
    return base


class FakeGoogle:
    """Servidor falso: guarda as requisições e responde páginas."""

    def __init__(self, pages=None, status=200, fail=False):
        self.pages = pages or [[place(1), place(2)]]
        self.status, self.fail, self.requests = status, fail, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("sem rede")
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": f"eco {KEY}"}})
        body = json.loads(request.content)
        idx = int(body.get("pageToken", "0"))
        data = {"places": self.pages[idx]}
        if idx + 1 < len(self.pages):
            data["nextPageToken"] = str(idx + 1)
        return httpx.Response(200, json=data)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def google(fake, used=lambda: 0, max_per_day=30, **kw) -> GooglePlacesProvider:
    return GooglePlacesProvider(KEY, max_per_day, used, client=fake.client(), **kw)


# --------------------------------------------------------------------------- Google
def test_google_sem_chave_nao_chama():
    with pytest.raises(ProviderError, match="GOOGLE_MAPS_API_KEY"):
        GooglePlacesProvider("", 30, lambda: 0)


def test_google_field_mask_tipo_e_idioma():
    fake = FakeGoogle()
    out = google(fake).search("salão de beleza", "Savassi, Belo Horizonte")
    req = fake.requests[0]
    assert str(req.url) == TEXT_SEARCH_URL
    assert req.headers["X-Goog-FieldMask"] == FIELD_MASK
    assert "places.reviews" not in FIELD_MASK and "nextPageToken" in FIELD_MASK
    body = json.loads(req.content)
    assert body["includedType"] == "beauty_salon"
    assert body["languageCode"] == "pt-BR" and body["regionCode"] == "BR"
    assert "Savassi" in body["textQuery"]
    assert len(out) == 2 and out[0].neighborhood == "Savassi" and out[0].photos_count == 6


def test_google_nicho_fora_da_lista_nao_manda_tipo():
    fake = FakeGoogle()
    google(fake).search("loja de aquário raro", "Belo Horizonte")
    assert "includedType" not in json.loads(fake.requests[0].content)


def test_google_pino_vira_location_bias():
    fake = FakeGoogle()
    google(fake).search("dentista", "Centro", 2000, (-19.92, -43.94))
    circle = json.loads(fake.requests[0].content)["locationBias"]["circle"]
    assert circle["center"] == {"latitude": -19.92, "longitude": -43.94} and circle["radius"] == 2000.0


def test_google_pagina_ate_3_e_conta_cada_pagina():
    fake = FakeGoogle(pages=[[place(i) for i in range(20)], [place(i) for i in range(20, 40)],
                             [place(i) for i in range(40, 60)], [place(99)]])
    p = google(fake)
    out = p.search("salão de beleza", "BH")
    assert len(out) == 60 and p.last_requests_made == 3 and len(fake.requests) == 3


def test_google_para_de_paginar_quando_a_cota_acaba():
    fake = FakeGoogle(pages=[[place(1)], [place(2)], [place(3)]])
    p = google(fake, used=lambda: 29)
    out = p.search("salão de beleza", "BH")
    assert len(out) == 1 and p.last_requests_made == 1


def test_google_trava_antes_de_chamar_na_31a():
    fake = FakeGoogle()
    p = google(fake, used=lambda: 30)
    with pytest.raises(QuotaExceeded, match="30 de 30"):
        p.search("salão de beleza", "BH")
    assert fake.requests == [] and p.last_requests_made == 0


def test_google_erro_conta_e_nao_vaza_a_chave():
    fake = FakeGoogle(status=403)
    p = google(fake)
    with pytest.raises(ProviderError) as exc:
        p.search("salão de beleza", "BH")
    assert p.last_requests_made == 1
    assert KEY not in str(exc.value) and "403" in str(exc.value)
    assert KEY not in repr(p)


def test_google_sem_rede_conta_como_requisicao():
    p = google(FakeGoogle(fail=True))
    with pytest.raises(ProviderError, match="Sem conexão"):
        p.search("salão de beleza", "BH")
    assert p.last_requests_made == 1


def test_google_details_valida_place_id():
    fake = FakeGoogle()
    p = google(fake)
    with pytest.raises(ProviderError, match="place_id"):
        p.details("../../etc")
    assert fake.requests == []


def test_bairro_pelo_endereco():
    assert neighborhood_from_address("R. X, 123 - Savassi, Belo Horizonte - MG, 30140-000, Brasil") == "Savassi"
    assert neighborhood_from_address(None) is None


# --------------------------------------------------------------------------- cota no banco
def test_31a_requisicao_bloqueada_no_servidor(session, ctx, monkeypatch):
    """30 requisições gravadas hoje: a próxima busca nem chega ao Google."""
    from app.config import get_settings
    from app.models import Search

    monkeypatch.setenv("PLACES_PROVIDER", "google")
    get_settings.cache_clear()
    settings = get_settings()
    fake = FakeGoogle(pages=[[place(i)] for i in range(40)])
    for i in range(30):
        p = google(fake, used=lambda: quota.requests_today(session, "google"), max_pages=1)
        lead_service.run_search(session, settings, ctx, "salão de beleza", f"Bairro {i}", provider=p)
    assert quota.requests_today(session, "google") == 30
    assert quota.status(session, settings).blocked
    before = len(fake.requests)
    p = google(fake, used=lambda: quota.requests_today(session, "google"), max_pages=1)
    with pytest.raises(QuotaExceeded):
        lead_service.run_search(session, settings, ctx, "salão de beleza", "Bairro 31", provider=p)
    assert len(fake.requests) == before
    last = session.query(Search).order_by(Search.id.desc()).first()
    assert last.requests_made == 0 and "Limite de hoje" in last.error


def test_requisicao_que_falhou_conta_na_cota(session, ctx, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PLACES_PROVIDER", "google")
    get_settings.cache_clear()
    p = google(FakeGoogle(status=500), used=lambda: quota.requests_today(session, "google"))
    with pytest.raises(ProviderError):
        lead_service.run_search(session, get_settings(), ctx, "salão de beleza", "Savassi", provider=p)
    assert quota.requests_today(session, "google") == 1


def test_cache_ignora_maiusculas_e_acentos(session, ctx, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PLACES_PROVIDER", "google")
    get_settings.cache_clear()
    settings = get_settings()
    fake = FakeGoogle()
    r1 = lead_service.run_search(session, settings, ctx, "Salão de Beleza", "Savassi, Belo Horizonte",
                                 provider=google(fake))
    r2 = lead_service.run_search(session, settings, ctx, "  salao de  beleza ", "SAVASSI, belo horizonte",
                                 provider=google(fake))
    assert r1["cached"] is False and r1["created"] == 2
    assert r2["cached"] is True and r2["search"].requests_made == 0 and r2["search"].cached_from_id == r1["search"].id
    assert len(fake.requests) == 1
    assert quota.requests_today(session, "google") == 1
    r3 = lead_service.run_search(session, settings, ctx, "Salão de Beleza", "Lourdes, Belo Horizonte",
                                 provider=google(fake))
    assert r3["cached"] is False and len(fake.requests) == 2


def test_upsert_nao_duplica_e_preserva_o_que_e_do_samuel(session, ctx):
    from app.models import Lead

    settings = __import__("app.config", fromlist=["x"]).get_settings()
    fake = FakeGoogle(pages=[[place(1, websiteUri=None)]])
    lead_service.run_search(session, settings, ctx, "salão de beleza", "Savassi", provider=google(fake))
    lead = session.query(Lead).one()
    lead_service.set_manual_score(session, lead, "C", ctx)
    lead_service.set_tags(session, lead, ["quente"])
    lead.notes = "ligar à tarde"
    lead_service.change_status(session, lead, "CONVERSA", ctx)
    fake2 = FakeGoogle(pages=[[place(1, displayName={"text": "Salão Novo Nome"}, rating=4.9)]])
    r = lead_service.run_search(session, settings, ctx, "salão de beleza", "Lourdes", provider=google(fake2))
    assert r["created"] == 0 and r["updated"] == 1 and session.query(Lead).count() == 1
    session.refresh(lead)
    assert lead.name == "Salão Novo Nome" and lead.rating == 4.9
    assert lead.status == "CONVERSA" and lead.score == "C" and lead.tag_list == ["quente"]
    assert lead.notes == "ligar à tarde"


# --------------------------------------------------------------------------- OpenStreetMap
def osm_element(i=1, **tags):
    return {"type": "node", "id": i, "lat": -19.9385, "lon": -43.9353,
            "tags": {"name": f"Salão OSM {i}", "shop": "hairdresser", **tags}}


def osm(handler, **kw) -> OsmProvider:
    return OsmProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_osm_consulta_por_bairro_e_atribuicao():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"elements": [osm_element(1, phone="+55 31 98888-1111"), osm_element(1),
                                                      {"type": "node", "id": 9, "tags": {"shop": "hairdresser"}}]})

    p = osm(handler)
    out = p.search("salão de beleza", "Savassi, Belo Horizonte")
    query = seen[0].content.decode()
    assert "around%3A1500" in query and "hairdresser" in query
    assert len(out) == 1, "sem nome fica de fora e o repetido não duplica"
    dto = out[0]
    assert dto.place_id == "osm-node-1" and dto.rating is None and dto.reviews_count == 0
    assert "hair_salon" in dto.categories and dto.maps_url.startswith("https://www.google.com/maps/search/")
    assert p.attribution == "© colaboradores do OpenStreetMap" and p.cost_per_request_usd == 0


def test_osm_cidade_inteira_usa_area():
    q = OsmProvider.build_query("Contagem", None, None, "dentista")
    assert 'area["name"="Contagem"]' in q and "(area.a)" in q and "out center tags" in q


def test_osm_nicho_fora_da_lista_busca_pelo_nome():
    assert OsmProvider.filters("taxidermia") == ('["name"~"taxidermia",i]',)
    with pytest.raises(ProviderError):
        OsmProvider.filters('"')


def test_osm_tenta_o_proximo_servidor():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if len(calls) == 1:
            return httpx.Response(504)
        return httpx.Response(200, json={"elements": [osm_element(2)]})

    p = osm(handler)
    assert len(p.search("salão de beleza", "Savassi")) == 1
    assert len(calls) == 2 and calls[0] != calls[1]


def test_osm_todos_ocupados_pede_pausa():
    p = osm(lambda r: httpx.Response(429))
    with pytest.raises(ProviderError, match="pausa"):
        p.search("salão de beleza", "Savassi")
    assert p.last_requests_made == 3


def test_osm_instagram_vira_link_e_fechado():
    dto = OsmProvider.to_dto(osm_element(3, **{"contact:instagram": "@salao3", "disused:shop": "yes"}))
    assert dto.website_url == "https://instagram.com/salao3" and dto.business_status == "CLOSED_PERMANENTLY"


def test_osm_nao_gasta_cota_do_google(session, ctx):
    from app.config import get_settings

    p = osm(lambda r: httpx.Response(200, json={"elements": [osm_element(5)]}))
    r = lead_service.run_search(session, get_settings(), ctx, "salão de beleza", "Savassi", provider=p)
    assert r["created"] == 1 and r["attribution"].startswith("©")
    assert quota.requests_today(session, "google") == 0
    lead = r["search"].leads[0] if hasattr(r["search"], "leads") else None
    assert lead is None or lead.source_provider == "osm"


# --------------------------------------------------------------------------- escolha do provedor
def test_provedor_padrao_e_osm(env, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PLACES_PROVIDER", "")
    get_settings.cache_clear()
    assert isinstance(get_provider(get_settings()), OsmProvider)
    monkeypatch.setenv("PLACES_PROVIDER", "mock")
    get_settings.cache_clear()
    assert isinstance(get_provider(get_settings()), MockProvider)
    monkeypatch.setenv("PLACES_PROVIDER", "google")
    get_settings.cache_clear()
    with pytest.raises(ProviderError):
        get_provider(get_settings())  # sem chave: não liga


def test_ficticios_sao_marcados(session, ctx):
    from app.config import get_settings
    from app.models import Lead

    lead_service.run_search(session, get_settings(), ctx, "salão de beleza", "Belo Horizonte", provider=MockProvider())
    leads = session.query(Lead).all()
    assert leads and all(l.is_mock and l.place_id.startswith("mock-") for l in leads)
