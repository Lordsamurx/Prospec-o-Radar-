"""DTOs Pydantic: dados que entram dos provedores e filtros que entram da lista."""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PlaceDTO(BaseModel):
    """Contrato único que todo provedor devolve."""

    place_id: str
    name: str
    address: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    phone: str | None = None
    website_url: str | None = None
    maps_url: str | None = None
    rating: float | None = None
    reviews_count: int = 0
    business_status: str | None = None  # OPERATIONAL | CLOSED_TEMPORARILY | CLOSED_PERMANENTLY
    opening_hours: str | None = None
    photos_count: int = 0
    categories: list[str] = Field(default_factory=list)
    lat: float | None = None
    lng: float | None = None
    niche_hint: str | None = None  # só o mock usa: nicho em que a busca fictícia devolve o lugar


SortKey = Literal["score", "opportunity", "reviews", "rating", "newest", "next_action"]
YesNo = Literal["yes", "no"]


class FilterParams(BaseModel):
    """Filtros do docs/09 mais os da v3 (setor, perfil, serviço recomendado, tag). Vazio = sem filtro."""

    niche: list[str] = Field(default_factory=list)
    sector: list[str] = Field(default_factory=list)
    city: str | None = None
    neighborhood: str | None = None
    radius_km: float | None = Field(default=None, gt=0, le=100)
    site: Literal["sem", "com"] | None = None  # barra principal: "sem" inclui rede social e plataforma
    site_status: list[Literal["none", "social", "platform", "own"]] = Field(default_factory=list)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    min_reviews: int | None = Field(default=None, ge=0)
    max_reviews: int | None = Field(default=None, ge=0)
    has_phone: YesNo | None = None
    phone_type: Literal["mobile", "landline"] | None = None
    operational_only: bool = False
    min_photos: int | None = Field(default=None, ge=0)
    has_hours: YesNo | None = None
    status: list[str] = Field(default_factory=list)
    never_contacted: bool = False
    no_reply_days: int | None = Field(default=None, ge=0)
    score: list[Literal["A", "B", "C", "DESCARTE"]] = Field(default_factory=list)
    profile: list[str] = Field(default_factory=list)
    service: list[str] = Field(default_factory=list)  # serviço recomendado
    tag: list[str] = Field(default_factory=list)
    hide_franchises: bool = False
    show_mock: bool = False  # fictícios ficam escondidos por padrão
    show_archived: bool = False
    stale: bool = False  # só dados do Google com mais de 30 dias
    overdue: bool = False  # só com próxima ação vencida
    q: str | None = None
    sort: SortKey = "score"

    LIST_FIELDS: ClassVar[tuple[str, ...]] = ("niche", "sector", "site_status", "status", "score", "profile",
                                              "service", "tag")
    BOOL_FIELDS: ClassVar[tuple[str, ...]] = ("operational_only", "never_contacted", "hide_franchises", "show_mock",
                                              "show_archived", "stale", "overdue")

    @classmethod
    def from_query(cls, items: list[tuple[str, str]]) -> "FilterParams":
        """Monta a partir de pares (chave, valor) da querystring. Ignora vazios e campos inválidos."""
        data: dict[str, Any] = {}
        for key, value in items:
            value = value.strip()
            if not value or key not in cls.model_fields:
                continue
            if key in cls.LIST_FIELDS:
                data.setdefault(key, [])
                for v in value.split(","):
                    v = v.strip()
                    if v and v not in data[key]:
                        data[key].append(v)
            elif key in cls.BOOL_FIELDS:
                data[key] = value.lower() in ("1", "true", "on", "yes", "sim")
            else:
                data[key] = value.replace(",", ".") if key in ("min_rating", "radius_km") else value
        for _ in range(len(data) + 1):
            try:
                return cls.model_validate(data)
            except ValidationError as exc:
                # tira só os campos inválidos (ex.: min_rating=abc) e mantém o resto
                bad = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")}
                if not bad:
                    break
                for k in bad:
                    loc_items = [e for e in exc.errors() if e.get("loc") and str(e["loc"][0]) == k]
                    if k in cls.LIST_FIELDS and all(len(e["loc"]) > 1 for e in loc_items):
                        drop = {e["loc"][1] for e in loc_items}
                        data[k] = [v for i, v in enumerate(data[k]) if i not in drop]
                    else:
                        data.pop(k, None)
        return cls()

    def to_query(self) -> list[tuple[str, str]]:
        """Inverso de from_query, só com o que está preenchido (para links e chips)."""
        out: list[tuple[str, str]] = []
        for key, field in type(self).model_fields.items():
            val = getattr(self, key)
            if key in self.LIST_FIELDS:
                out.extend((key, v) for v in val)
            elif key in self.BOOL_FIELDS:
                if val:
                    out.append((key, "1"))
            elif val is not None and val != field.default:
                out.append((key, f"{val:g}" if isinstance(val, float) else str(val)))
        return out


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    place_id: str
    name: str
    niche: str | None
    sector: str | None
    address: str | None
    neighborhood: str | None
    city: str | None
    phone: str | None
    phone_type: str | None
    website_url: str | None
    site_status: str
    site_kind: str
    site_platform: str | None
    maps_url: str | None
    rating: float | None
    reviews_count: int
    business_status: str | None
    photos_count: int
    opening_hours: str | None
    lat: float | None
    lng: float | None
    score: str | None
    score_reason: str | None
    score_auto: str | None
    score_manual: str | None
    profile: str | None
    opportunity: int
    rec_main: str | None
    status: str
    do_not_contact: bool
    is_mock: bool
    source_provider: str
    contacted_at: datetime | None
    next_action: str | None
    next_action_at: datetime | None
    proposal_value: float | None
    fetched_at: datetime


class SearchIn(BaseModel):
    niche: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=200)
    radius_m: int | None = Field(default=None, ge=100, le=50000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
