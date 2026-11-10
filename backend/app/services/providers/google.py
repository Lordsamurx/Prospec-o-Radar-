"""Places API (New): Text Search e Place Details. Só roda com PLACES_PROVIDER=google e chave no .env.

- field mask fixo, para não pagar campo que não usamos;
- includedType do nicho; até `max_pages` páginas de 20 (cada página = 1 requisição cobrada);
- trava ANTES de chamar: para em MAX_PLACES_REQUESTS_PER_DAY (a contagem vem do banco);
- requisição que falhou também conta (last_requests_made).
A chave nunca aparece em mensagem de erro nem em log.
"""
import re
from collections.abc import Callable

import httpx

from ... import catalog
from ...schemas import PlaceDTO
from .base import PlacesProvider, ProviderError, QuotaExceeded

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/"
FIELDS = ("id", "displayName", "formattedAddress", "addressComponents", "nationalPhoneNumber", "websiteUri",
          "googleMapsUri", "rating", "userRatingCount", "regularOpeningHours", "types", "photos", "businessStatus",
          "location")
FIELD_MASK = ",".join("places." + f for f in FIELDS) + ",nextPageToken"
DETAILS_MASK = ",".join(FIELDS)


class GooglePlacesProvider(PlacesProvider):
    name = "google"
    cost_per_request_usd = 0.035  # Text Search Enterprise depois da cota grátis (docs/05 do protótipo)
    attribution = "Dados do Google Maps"

    def __init__(self, api_key: str, max_per_day: int, requests_today: Callable[[], int],
                 client: httpx.Client | None = None, max_pages: int = 3,
                 center: tuple[float, float] | None = None) -> None:
        super().__init__()
        if not api_key:
            raise ProviderError("PLACES_PROVIDER=google, mas GOOGLE_MAPS_API_KEY está vazia no .env. Nenhuma chamada foi feita.")
        self._key = api_key
        self.max_per_day = max_per_day
        self.requests_today = requests_today
        self.client = client or httpx.Client(timeout=20)
        self.max_pages = max_pages
        self.center = center

    def __repr__(self) -> str:  # nunca mostra a chave
        return f"<GooglePlacesProvider max_per_day={self.max_per_day}>"

    def _check_quota(self) -> int:
        used = self.requests_today()
        if used >= self.max_per_day:
            raise QuotaExceeded(
                f"Limite de hoje atingido ({used} de {self.max_per_day} requisições ao Google). "
                "A fila continua amanhã; nada foi chamado agora.")
        return used

    def _headers(self, mask: str) -> dict:
        return {"Content-Type": "application/json", "X-Goog-Api-Key": self._key, "X-Goog-FieldMask": mask}

    def body(self, niche: str, location: str, radius_m: int | None, page_token: str | None,
             center: tuple[float, float] | None = None) -> dict:
        n = catalog.niches().resolve(niche)
        term = niche if n.is_other else (n.term or niche)
        text = f"{term} em {location}" if location.strip() else term
        body: dict = {"textQuery": text, "languageCode": "pt-BR", "regionCode": "BR"}
        if n.included_type:  # só puxa lugares desse tipo (o texto ainda ordena)
            body["includedType"] = n.included_type
        point = center or (self.center if radius_m else None)
        if point:
            body["locationBias"] = {"circle": {"center": {"latitude": point[0], "longitude": point[1]},
                                               "radius": float(min(radius_m or 1500, 50000))}}
        if page_token:
            body["pageToken"] = page_token
        return body

    def search(self, niche, location, radius_m=None, center=None):
        self.last_requests_made = 0
        used = self._check_quota()
        results: list[PlaceDTO] = []
        token: str | None = None
        for _ in range(self.max_pages):
            if used + self.last_requests_made >= self.max_per_day:
                break
            try:
                resp = self.client.post(TEXT_SEARCH_URL, json=self.body(niche, location, radius_m, token, center),
                                        headers=self._headers(FIELD_MASK))
            except httpx.HTTPError as exc:
                self.last_requests_made += 1  # pode ter sido cobrada: conta para o limite
                if results:
                    break
                raise ProviderError(f"Sem conexão com o Google Places ({type(exc).__name__}).") from None
            self.last_requests_made += 1
            if resp.status_code != 200:
                if results:
                    break
                # não repassa o corpo cru (pode ecoar dados da requisição)
                raise ProviderError(_status_message(resp.status_code))
            try:
                data = resp.json()
            except ValueError:
                raise ProviderError("Resposta inválida do Google Places.") from None
            results += [self.to_dto(p) for p in data.get("places", []) if p.get("id")]
            token = data.get("nextPageToken")
            if not token:
                break
        return results

    def details(self, place_id: str) -> PlaceDTO:
        """Atualiza um lugar pelo place_id (1 requisição, conta na cota)."""
        self.last_requests_made = 0
        self._check_quota()
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", place_id or ""):
            raise ProviderError("place_id inválido para atualizar no Google.")
        try:
            resp = self.client.get(DETAILS_URL + place_id, headers=self._headers(DETAILS_MASK),
                                   params={"languageCode": "pt-BR", "regionCode": "BR"})
        except httpx.HTTPError as exc:
            self.last_requests_made += 1
            raise ProviderError(f"Sem conexão com o Google Places ({type(exc).__name__}).") from None
        self.last_requests_made += 1
        if resp.status_code != 200:
            raise ProviderError(_status_message(resp.status_code))
        try:
            return self.to_dto(resp.json())
        except (ValueError, KeyError):
            raise ProviderError("Resposta inválida do Google Places.") from None

    @staticmethod
    def to_dto(p: dict) -> PlaceDTO:
        comps = p.get("addressComponents") or []

        def comp(kind: str) -> str | None:
            for c in comps:
                if kind in (c.get("types") or []):
                    return c.get("longText")
            return None

        address = p.get("formattedAddress")
        neighborhood = comp("sublocality_level_1") or comp("sublocality") or neighborhood_from_address(address)
        hours = (p.get("regularOpeningHours") or {}).get("weekdayDescriptions")
        loc = p.get("location") or {}
        return PlaceDTO(
            place_id=p["id"],
            name=((p.get("displayName") or {}).get("text") or "(sem nome)")[:200],
            address=address,
            neighborhood=neighborhood,
            city=comp("administrative_area_level_2") or comp("locality"),
            phone=p.get("nationalPhoneNumber"),
            website_url=p.get("websiteUri"),
            maps_url=p.get("googleMapsUri"),
            rating=p.get("rating"),
            reviews_count=p.get("userRatingCount") or 0,
            business_status=p.get("businessStatus"),
            opening_hours="; ".join(hours) if hours else None,
            photos_count=len(p.get("photos") or []),  # a API devolve no máx. 10
            categories=p.get("types") or [],
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
        )


def _status_message(code: int) -> str:
    if code == 403:
        return ("O Google recusou a chave (403). Confira no Google Cloud se a Places API (New) está ativada, "
                "se a chave permite essa API e se o faturamento do projeto está ativo.")
    if code == 429:
        return "O Google avisou que a cota da chave acabou (429). Tente amanhã."
    if code == 400:
        return "O Google recusou a busca (400). Tente escrever o nicho e o local de outro jeito."
    return f"Google Places respondeu {code}. Confira a chave e a cota."


def neighborhood_from_address(address: str | None) -> str | None:
    """'R. X, 123 - Savassi, Belo Horizonte - MG, 30140-000, Brasil' -> 'Savassi'."""
    if not address:
        return None
    m = re.search(r" - ([^,]+), [^,]+ - [A-Z]{2}", address)
    return m.group(1).strip() if m else None
