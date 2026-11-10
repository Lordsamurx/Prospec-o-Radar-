"""Catálogos em arquivo de dados: nichos/setores, serviços e plataformas.

Carregados e validados uma vez. Erro de cadastro (campo faltando, tipo do Google que não
existe, alias repetido) derruba a carga com uma mensagem clara: melhor falhar ao iniciar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_DIR = Path(__file__).resolve().parent
OFFER_TEMPLATES = ("landing", "institucional", "cardapio", "agendamento", "links")
Service3 = tuple[str, str, str]  # (ícone, título, texto)


class CatalogError(ValueError):
    pass


def fold(text: str | None) -> str:
    """Minúsculas, sem acento e com espaços simples."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


# --------------------------------------------------------------------------- serviços
@dataclass(frozen=True)
class ServiceItem:
    key: str
    name: str
    short: str
    description: str
    delivers: tuple[str, ...] = ()
    price_min: float | None = None
    price_max: float | None = None
    deadline: str = ""
    recurring: bool = False
    active: bool = True
    kind: str = "site"
    template: str | None = None
    combines_with: tuple[str, ...] = ()

    @property
    def price_text(self) -> str:
        return price_text(self.price_min, self.price_max, self.recurring)


def brl(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + (s[:-3] if s.endswith(",00") else s)


def price_text(lo: float | None, hi: float | None, recurring: bool = False) -> str:
    if lo is None and hi is None:
        return "preço a definir"
    if lo is not None and hi is not None and lo != hi:
        txt = f"{brl(lo)} a {brl(hi)}"
    else:
        txt = brl(lo if lo is not None else hi)  # type: ignore[arg-type]
    return txt + ("/mês" if recurring else "")


def load_services(path: Path | None = None) -> dict[str, ServiceItem]:
    raw = yaml.safe_load((path or CATALOG_DIR / "services.yaml").read_text(encoding="utf-8")) or {}
    out: dict[str, ServiceItem] = {}
    for i, s in enumerate(raw.get("services") or []):
        for req in ("key", "name", "short", "description"):
            if not s.get(req):
                raise CatalogError(f"services.yaml: serviço nº {i + 1} sem o campo obrigatório '{req}'.")
        if s["key"] in out:
            raise CatalogError(f"services.yaml: chave repetida '{s['key']}'.")
        tpl = s.get("template")
        if tpl and tpl not in OFFER_TEMPLATES:
            raise CatalogError(f"services.yaml: serviço '{s['key']}' com template desconhecido '{tpl}'.")
        out[s["key"]] = ServiceItem(
            key=s["key"], name=s["name"], short=s["short"], description=s["description"],
            delivers=tuple(s.get("delivers") or ()),
            price_min=_num(s.get("price_min")), price_max=_num(s.get("price_max")),
            deadline=s.get("deadline") or "", recurring=bool(s.get("recurring")),
            active=s.get("active", True) is not False, kind=s.get("kind") or "site",
            template=tpl, combines_with=tuple(s.get("combines_with") or ()),
        )
    for s in out.values():
        for c in s.combines_with:
            if c not in out:
                raise CatalogError(f"services.yaml: '{s.key}' combina com serviço inexistente '{c}'.")
    return out


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        n = float(str(v).replace(",", "."))
    except ValueError:
        raise CatalogError(f"services.yaml: preço inválido '{v}'. Use só números.") from None
    if n < 0:
        raise CatalogError(f"services.yaml: preço negativo '{v}'.")
    return n


# --------------------------------------------------------------------------- nichos
@dataclass(frozen=True)
class Sector:
    key: str
    label: str
    color: str
    icon: str
    template: str
    default_offer: str
    offers: tuple[str, ...]
    pitch: str
    tagline: str
    cta: str
    wa_message: str
    services: tuple[Service3, ...]


@dataclass(frozen=True)
class Niche:
    key: str
    sector: str
    label: str
    plural: str
    term: str
    aliases: tuple[str, ...] = ()
    google_types: frozenset[str] = frozenset()
    type_suffixes: tuple[str, ...] = ()
    included_type: str | None = None
    osm: tuple[str, ...] = ()
    min_rating: float = 4.0
    min_reviews: int = 15
    tagline: str = ""
    cta: str = ""
    wa_message: str = ""
    services: tuple[Service3, ...] = ()
    services_by_type: dict[str, tuple[Service3, ...]] = field(default_factory=dict)
    template: str = "landing"
    default_offer: str = "landing"
    pitch: str = ""

    @property
    def checks_category(self) -> bool:
        return bool(self.google_types or self.type_suffixes)

    @property
    def is_other(self) -> bool:
        return self.key == "outro"

    def matches(self, categories) -> bool:
        cats = set(categories or [])
        return bool(cats & self.google_types) or any(c.endswith(s) for c in cats for s in self.type_suffixes)

    def services_for(self, categories) -> tuple[Service3, ...]:
        cats = set(categories or [])
        return next((v for k, v in self.services_by_type.items() if k in cats), self.services)


def _triples(items, where: str) -> tuple[Service3, ...]:
    out = []
    for it in items or []:
        if not isinstance(it, (list, tuple)) or len(it) != 3:
            raise CatalogError(f"niches.yaml: {where}: cada serviço precisa de [ícone, título, texto].")
        out.append((str(it[0]), str(it[1]), str(it[2])))
    return tuple(out)


def load_google_types(path: Path | None = None) -> frozenset[str]:
    text = (path or CATALOG_DIR / "google_types.txt").read_text(encoding="utf-8")
    body = ",".join(l for l in text.splitlines() if not l.startswith("#"))
    return frozenset(t.strip() for t in body.split(",") if t.strip())


class NicheCatalog:
    def __init__(self, sectors: list[Sector], niches: list[Niche]):
        self.sectors = sectors
        self.sector_by_key = {s.key: s for s in sectors}
        self.all = niches
        self.by_key = {n.key: n for n in niches}
        self.other = self.by_key["outro"]
        self.niches = [n for n in niches if not n.is_other]
        # alias dobrado -> nicho (a chave e o rótulo também contam)
        self._alias: list[tuple[str, Niche]] = []
        for n in self.niches:
            for a in {fold(n.key.replace("_", " ")), fold(n.label), fold(n.term), *(fold(a) for a in n.aliases)}:
                if a:
                    self._alias.append((a, n))
        self._alias.sort(key=lambda x: -len(x[0]))

    def get(self, key: str | None) -> Niche | None:
        return self.by_key.get(key or "")

    def get_or_other(self, key: str | None) -> Niche:
        return self.by_key.get(key or "") or self.other

    def label(self, key: str | None) -> str:
        n = self.get(key)
        return n.label if n else (key or "—")

    def sector_of(self, key: str | None) -> Sector:
        return self.sector_by_key[self.get_or_other(key).sector]

    def by_sector(self) -> list[tuple[Sector, list[Niche]]]:
        return [(s, [n for n in self.all if n.sector == s.key]) for s in self.sectors]

    def resolve(self, text: str | None) -> Niche:
        """Texto da busca -> nicho. Chave exata ganha; senão o alias mais longo contido no texto."""
        if text and text in self.by_key:
            return self.by_key[text]
        t = f" {fold(text)} "
        for alias, n in self._alias:  # já ordenado do mais longo ao mais curto
            if f" {alias} " in t:
                return n
        return self.other

    def pick(self, current: str | None, new: str, categories) -> str:
        """Nicho a gravar quando o mesmo lugar aparece em outra busca.

        Mantém o atual se ele combina com as categorias; senão fica o da busca nova."""
        cur = self.get(current)
        if cur is None or cur.is_other:
            return new
        if not categories or not cur.checks_category or cur.matches(categories):
            return cur.key
        return new


REQUIRED_NICHE = ("key", "sector", "label", "plural")
REQUIRED_SECTOR = ("key", "label", "color", "icon", "template", "default_offer", "offers", "pitch", "tagline", "cta",
                   "wa_message", "services")


def load_niches(path: Path | None = None, services: dict[str, ServiceItem] | None = None,
                google_types: frozenset[str] | None = None) -> NicheCatalog:
    raw = yaml.safe_load((path or CATALOG_DIR / "niches.yaml").read_text(encoding="utf-8")) or {}
    services = services if services is not None else load_services()
    gtypes = google_types if google_types is not None else load_google_types()
    dflt = raw.get("defaults") or {}
    sectors: list[Sector] = []
    for i, s in enumerate(raw.get("sectors") or []):
        for req in REQUIRED_SECTOR:
            if not s.get(req):
                raise CatalogError(f"niches.yaml: setor nº {i + 1} ({s.get('key', '?')}) sem o campo obrigatório '{req}'.")
        if s["template"] not in OFFER_TEMPLATES:
            raise CatalogError(f"niches.yaml: setor '{s['key']}' com template desconhecido '{s['template']}'.")
        for k in (s["default_offer"], *s["offers"]):
            if k not in services:
                raise CatalogError(f"niches.yaml: setor '{s['key']}' cita serviço inexistente '{k}'.")
        sectors.append(Sector(
            key=s["key"], label=s["label"], color=s["color"], icon=s["icon"], template=s["template"],
            default_offer=s["default_offer"], offers=tuple(s["offers"]), pitch=s["pitch"], tagline=s["tagline"],
            cta=s["cta"], wa_message=s["wa_message"], services=_triples(s["services"], f"setor {s['key']}"),
        ))
    by_sector = {s.key: s for s in sectors}
    if len(by_sector) != len(sectors):
        raise CatalogError("niches.yaml: chave de setor repetida.")
    niches: list[Niche] = []
    seen: set[str] = set()
    alias_owner: dict[str, str] = {}
    for i, n in enumerate(raw.get("niches") or []):
        for req in REQUIRED_NICHE:
            if not n.get(req):
                raise CatalogError(f"niches.yaml: nicho nº {i + 1} ({n.get('key', '?')}) sem o campo obrigatório '{req}'.")
        key = n["key"]
        if key in seen:
            raise CatalogError(f"niches.yaml: chave de nicho repetida '{key}'.")
        seen.add(key)
        sec = by_sector.get(n["sector"])
        if sec is None:
            raise CatalogError(f"niches.yaml: nicho '{key}' aponta para setor inexistente '{n['sector']}'.")
        if key != "outro" and not n.get("term"):
            raise CatalogError(f"niches.yaml: nicho '{key}' sem o campo obrigatório 'term'.")
        types = frozenset(n.get("google_types") or [])
        unknown = types - gtypes
        if unknown:
            raise CatalogError(f"niches.yaml: nicho '{key}' usa tipo do Google desconhecido: {', '.join(sorted(unknown))}.")
        inc = n.get("included_type") or None
        if inc and inc not in gtypes:
            raise CatalogError(f"niches.yaml: nicho '{key}' com included_type desconhecido '{inc}'.")
        offer = n.get("default_offer") or sec.default_offer
        if offer not in services:
            raise CatalogError(f"niches.yaml: nicho '{key}' com default_offer inexistente '{offer}'.")
        tpl = n.get("template") or services[offer].template or sec.template
        if tpl not in OFFER_TEMPLATES:
            raise CatalogError(f"niches.yaml: nicho '{key}' com template desconhecido '{tpl}'.")
        for a in n.get("aliases") or []:
            fa = fold(str(a))
            if fa in alias_owner and alias_owner[fa] != key:
                raise CatalogError(f"niches.yaml: alias '{a}' repetido em '{alias_owner[fa]}' e '{key}'.")
            alias_owner[fa] = key
        osm = n.get("osm") or []
        if isinstance(osm, str):
            osm = [osm]
        niches.append(Niche(
            key=key, sector=sec.key, label=n["label"], plural=n["plural"], term=n.get("term") or "",
            aliases=tuple(str(a) for a in n.get("aliases") or ()), google_types=types,
            type_suffixes=tuple(n.get("type_suffixes") or ()), included_type=inc, osm=tuple(osm),
            min_rating=float(n.get("min_rating", dflt.get("min_rating", 4.0))),
            min_reviews=int(n.get("min_reviews", dflt.get("min_reviews", 15))),
            tagline=n.get("tagline") or sec.tagline, cta=n.get("cta") or sec.cta,
            wa_message=n.get("wa_message") or sec.wa_message,
            services=_triples(n.get("services"), f"nicho {key}") or sec.services,
            services_by_type={k: _triples(v, f"nicho {key}") for k, v in (n.get("services_by_type") or {}).items()},
            template=tpl, default_offer=offer, pitch=n.get("pitch") or sec.pitch,
        ))
    if "outro" not in seen:
        raise CatalogError("niches.yaml: falta o nicho genérico 'outro'.")
    return NicheCatalog(sectors, niches)


@dataclass(frozen=True)
class Platforms:
    social: tuple[str, ...]
    platform: dict[str, str]
    builders: dict[str, tuple[str, ...]]


def load_platforms(path: Path | None = None) -> Platforms:
    raw = yaml.safe_load((path or CATALOG_DIR / "platforms.yaml").read_text(encoding="utf-8")) or {}
    return Platforms(
        social=tuple(raw.get("social") or ()),
        platform={str(k).lower(): str(v) for k, v in (raw.get("platform") or {}).items()},
        builders={k: tuple(v) for k, v in (raw.get("builders") or {}).items()},
    )


@lru_cache
def services() -> dict[str, ServiceItem]:
    return load_services()


@lru_cache
def niches() -> NicheCatalog:
    return load_niches(services=services())


@lru_cache
def platforms() -> Platforms:
    return load_platforms()
