"""OpenStreetMap via Overpass: grátis, sem chave e sem cartão. É o provedor padrão.

Limites: não tem nota, avaliações nem fotos, e nem todo negócio está no mapa.
Local: pino do mapa, bairro conhecido de BH (raio padrão 1,5 km) ou raio -> busca em volta do
ponto; senão, busca na área da cidade pelo nome. Nicho fora da lista: procura o termo no nome.
Dados © colaboradores do OpenStreetMap (ODbL): a tela mostra a fonte.
"""
import re
from urllib.parse import quote

import httpx

from ... import catalog
from ...schemas import PlaceDTO
from .. import geo
from .base import PlacesProvider, ProviderError

# Servidores públicos do Overpass: se um está sobrecarregado (429/5xx/sem resposta), tenta o próximo
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OSM_USER_AGENT = "ProspeccaoRadar/3.0 (uso pessoal, baixo volume)"
OSM_MAX_RESULTS = 300
DEFAULT_NEIGHBORHOOD_RADIUS = 1500
# Tag do OSM -> tipo no padrão do Google, para a regra "fora do nicho" (docs/06) valer igual
OSM_TYPES: dict[tuple[str, str], str] = {
    ("shop", "hairdresser"): "hair_salon", ("shop", "beauty"): "beauty_salon", ("shop", "cosmetics"): "cosmetics_store",
    ("shop", "tattoo"): "body_art_service", ("shop", "massage"): "massage", ("leisure", "spa"): "spa",
    ("amenity", "dentist"): "dentist", ("healthcare", "dentist"): "dentist", ("amenity", "clinic"): "medical_clinic",
    ("amenity", "doctors"): "doctor", ("healthcare", "physiotherapist"): "physiotherapist",
    ("healthcare", "laboratory"): "medical_lab", ("amenity", "pharmacy"): "pharmacy",
    ("shop", "pet"): "pet_store", ("shop", "pet_grooming"): "pet_care", ("amenity", "veterinary"): "veterinary_care",
    ("amenity", "animal_boarding"): "pet_boarding_service",
    ("shop", "car_repair"): "car_repair", ("shop", "tyres"): "tire_shop", ("amenity", "car_wash"): "car_wash",
    ("shop", "car_parts"): "auto_parts_store", ("shop", "car"): "car_dealer", ("amenity", "car_rental"): "car_rental",
    ("amenity", "restaurant"): "restaurant", ("amenity", "fast_food"): "fast_food_restaurant",
    ("amenity", "cafe"): "cafe", ("amenity", "bar"): "bar", ("amenity", "pub"): "pub",
    ("shop", "bakery"): "bakery", ("shop", "pastry"): "pastry_shop", ("shop", "confectionery"): "confectionery",
    ("amenity", "ice_cream"): "ice_cream_shop", ("shop", "butcher"): "butcher_shop",
    ("leisure", "fitness_centre"): "gym", ("leisure", "sports_centre"): "sports_complex",
    ("craft", "electrician"): "electrician", ("craft", "plumber"): "plumber", ("craft", "painter"): "painter",
    ("shop", "locksmith"): "locksmith", ("shop", "laundry"): "laundry", ("shop", "dry_cleaning"): "laundry",
    ("office", "lawyer"): "lawyer", ("office", "accountant"): "accounting",
    ("office", "estate_agent"): "real_estate_agency", ("office", "insurance"): "insurance_agency",
    ("shop", "clothes"): "clothing_store", ("shop", "florist"): "florist", ("shop", "mobile_phone"): "cell_phone_store",
    ("shop", "jewelry"): "jewelry_store", ("shop", "furniture"): "furniture_store", ("shop", "shoes"): "shoe_store",
    ("shop", "travel_agency"): "travel_agency", ("tourism", "hotel"): "hotel", ("tourism", "guest_house"): "guest_house",
    ("amenity", "kindergarten"): "preschool", ("amenity", "school"): "school",
}
OSM_KEYS = ("shop", "amenity", "leisure", "healthcare", "craft", "office", "tourism")


class OsmProvider(PlacesProvider):
    name = "osm"
    attribution = "© colaboradores do OpenStreetMap"

    def __init__(self, client: httpx.Client | None = None, center: tuple[float, float] = (-19.9191, -43.9386),
                 urls: tuple[str, ...] = OVERPASS_URLS) -> None:
        super().__init__()
        self.client = client or httpx.Client(timeout=90, headers={"User-Agent": OSM_USER_AGENT})
        self.center = center
        self.urls = urls

    @staticmethod
    def filters(niche: str) -> tuple[str, ...]:
        n = catalog.niches().resolve(niche)
        if n.is_other or not n.osm:
            term = re.sub(r'[\\"~^$.*+?()\[\]{}|]', "", (n.term if not n.is_other else niche) or "").strip()
            if len(term) < 2:
                raise ProviderError("No OpenStreetMap, um nicho fora da lista precisa de um termo de busca.")
            return (f'["name"~"{term}",i]',)
        return n.osm

    @classmethod
    def build_query(cls, location: str, radius_m: int | None, center: tuple[float, float] | None,
                    niche: str = "") -> str:
        """Com `center`: em volta do ponto. Sem `center`: na área administrativa da cidade `location`."""
        tags = cls.filters(niche)
        if center:
            lat, lng = center
            where, head = f"(around:{radius_m or 3000},{lat},{lng})", ""
        else:
            city = re.sub(r'["\\]', "", location).strip()
            head = f'area["name"="{city}"]["boundary"="administrative"]["admin_level"="8"]->.a;'
            where = "(area.a)"
        body = "".join(f"node{t}{where};way{t}{where};" for t in tags)
        return f"[out:json][timeout:60];{head}({body});out center tags {OSM_MAX_RESULTS};"

    def where(self, location: str, radius_m: int | None,
              center: tuple[float, float] | None = None) -> tuple[tuple[float, float] | None, int | None, str]:
        city = geo.city_from_location(location) or "Belo Horizonte"
        if center:
            return center, radius_m or DEFAULT_NEIGHBORHOOD_RADIUS, city
        bairros = geo.find_in_text(location)
        if bairros:
            return geo.center_of(bairros[0]), radius_m or DEFAULT_NEIGHBORHOOD_RADIUS, city
        if radius_m:
            return self.center, radius_m, city
        return None, None, city

    def search(self, niche, location, radius_m=None, center=None):
        self.last_requests_made = 0
        point, radius, city = self.where(location, radius_m, center)
        query = self.build_query(city, radius, point, niche)
        resp, problems = None, []
        for url in self.urls:
            try:
                r = self.client.post(url, data={"data": query})
            except httpx.HTTPError as exc:
                problems.append(type(exc).__name__)
                continue
            self.last_requests_made += 1
            if r.status_code == 200:
                resp = r
                break
            problems.append(str(r.status_code))
            if r.status_code != 429 and r.status_code < 500:
                break  # erro na consulta: outro servidor daria o mesmo
        if resp is None:
            if problems and all(p == "429" for p in problems):
                raise ProviderError("Os servidores do OpenStreetMap pediram uma pausa. Espere 1 minuto e busque de novo.")
            raise ProviderError(
                f"O OpenStreetMap não respondeu agora ({', '.join(problems) or 'sem resposta'}). Tente de novo em instantes.")
        try:
            elements = resp.json().get("elements", [])
        except ValueError:
            raise ProviderError("Resposta inválida do OpenStreetMap.") from None
        seen, out = set(), []
        for el in elements:
            dto = self.to_dto(el, None if center else city)
            if dto and dto.place_id not in seen:
                seen.add(dto.place_id)
                out.append(dto)
        if not out and point is None:
            raise ProviderError(
                f"Nada encontrado no OpenStreetMap para '{city}'. Confira o nome da cidade ou use um bairro de BH.")
        return out

    @staticmethod
    def to_dto(el: dict, city: str | None = None) -> PlaceDTO | None:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            return None
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lng = el.get("lon") or (el.get("center") or {}).get("lon")
        street = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
        neighborhood = tags.get("addr:suburb") or tags.get("addr:neighbourhood") or geo.nearest(lat, lng)
        town = tags.get("addr:city") or city
        address = ", ".join(x for x in (street, neighborhood, town) if x) or None
        site = (tags.get("website") or tags.get("contact:website") or tags.get("url")
                or tags.get("contact:instagram") or tags.get("contact:facebook"))
        if site and not site.startswith("http") and "." not in site:  # "@perfil" do Instagram
            site = f"https://instagram.com/{site.lstrip('@')}"
        cats = list(dict.fromkeys(OSM_TYPES[(k, v)] for k, v in tags.items() if (k, v) in OSM_TYPES))
        cats += [f"osm:{k}={v}" for k, v in tags.items() if k in OSM_KEYS]
        query = " ".join(x for x in (name, neighborhood, town) if x)
        closed = any(k.startswith(("disused:", "abandoned:")) for k in tags)
        return PlaceDTO(
            place_id=f"osm-{el.get('type', 'node')}-{el.get('id')}",
            name=name[:200],
            address=address,
            neighborhood=neighborhood,
            city=town,
            phone=tags.get("phone") or tags.get("contact:phone") or tags.get("mobile")
            or tags.get("contact:mobile") or tags.get("contact:whatsapp"),
            website_url=site,
            maps_url="https://www.google.com/maps/search/?api=1&query=" + quote(query),
            rating=None,
            reviews_count=0,
            # o OSM não diz se está aberto; só "disused:"/"abandoned:" contam como fechado
            business_status="CLOSED_PERMANENTLY" if closed else "OPERATIONAL",
            opening_hours=tags.get("opening_hours"),
            photos_count=0,
            categories=cats,
            lat=lat,
            lng=lng,
        )
