"""Configurações editáveis na tela (tabela settings) e o contexto que as funções puras recebem."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.orm import Session

from .. import catalog
from ..models import ServiceOverride, Setting
from .diagnose import Limits

DEFAULTS: dict[str, Any] = {
    # Redes/franquias para a regra "franquia" e o filtro "esconder franquias"
    "franchises": ["Jacques Janine", "Werner", "Studio W", "Soho", "Laces", "Walter's Coiffure", "Espaço Laser",
                   "Depyl Action", "Sobrancelhas Design", "Rede Fictícia", "OdontoCompany", "Sorridents",
                   "Smart Fit", "Bluefit", "Cobasi", "Petz", "Subway", "McDonald's", "Burger King", "Habib's",
                   "Cacau Show", "O Boticário", "Wizard", "CNA", "Fisk", "Kumon", "Localiza", "Drogasil"],
    "weekly_goal": 5,
    "cadence": [3, 5, 7],  # dias até o follow-up 1, 2 e 3
    "seller": {"name": "Samuel", "what": "sites, landing pages e Google Meu Negócio para negócios locais",
               "tone": "direto, simpático e sem enrolação", "city": "Belo Horizonte"},
    "site_analysis": True,   # Samuel autorizou em 10/11/2026: ler a página inicial do site do lead, 1 vez
    "ai_enabled": True,      # só funciona com GEMINI_API_KEY ou GROQ_API_KEY no .env
    "niche_limits": {},      # {"dentista": {"min_rating": 4.3, "min_reviews": 30}}
    "extra_platforms": {},   # {"dominio.com.br": "Nome"}
    "proposal_validity": 7,
    "last_backup": None,
}
SERVICE_EDITABLE = ("name", "short", "description", "price_min", "price_max", "deadline", "active")


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else DEFAULTS.get(key)


def put(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def all_settings(db: Session) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for row in db.query(Setting).all():
        out[row.key] = row.value
    return out


def services_with_overrides(db: Session) -> dict[str, catalog.ServiceItem]:
    base = dict(catalog.services())
    for ov in db.query(ServiceOverride).all():
        if ov.key in base and ov.data:
            data = {k: v for k, v in ov.data.items() if k in SERVICE_EDITABLE}
            base[ov.key] = replace(base[ov.key], **data)
    return base


def save_service(db: Session, key: str, data: dict) -> None:
    if key not in catalog.services():
        raise KeyError(key)
    clean = {k: v for k, v in data.items() if k in SERVICE_EDITABLE}
    row = db.get(ServiceOverride, key)
    if row is None:
        db.add(ServiceOverride(key=key, data=clean))
    else:
        row.data = {**(row.data or {}), **clean}


@dataclass
class Ctx:
    """Tudo o que diagnóstico, nota e recomendação precisam, lido uma vez por requisição."""
    franchises: list[str] = field(default_factory=lambda: list(DEFAULTS["franchises"]))
    niche_limits: dict[str, dict] = field(default_factory=dict)
    extra_platforms: dict[str, str] = field(default_factory=dict)
    services: dict[str, catalog.ServiceItem] = field(default_factory=lambda: dict(catalog.services()))
    cadence: list[int] = field(default_factory=lambda: list(DEFAULTS["cadence"]))
    weekly_goal: int = 5
    seller: dict = field(default_factory=lambda: dict(DEFAULTS["seller"]))
    site_analysis: bool = True
    ai_enabled: bool = True
    proposal_validity: int = 7

    def limits_for(self, niche: catalog.Niche) -> Limits:
        ov = self.niche_limits.get(niche.key) or {}
        try:
            return Limits(float(ov.get("min_rating", niche.min_rating)), int(ov.get("min_reviews", niche.min_reviews)))
        except (TypeError, ValueError):
            return Limits(niche.min_rating, niche.min_reviews)


def load_ctx(db: Session) -> Ctx:
    s = all_settings(db)
    cadence = [int(c) for c in (s.get("cadence") or []) if str(c).isdigit() and int(c) > 0] or list(DEFAULTS["cadence"])
    return Ctx(
        franchises=[f for f in (s.get("franchises") or []) if isinstance(f, str) and f.strip()],
        niche_limits=s.get("niche_limits") or {},
        extra_platforms=s.get("extra_platforms") or {},
        services=services_with_overrides(db),
        cadence=cadence,
        weekly_goal=int(s.get("weekly_goal") or 5),
        seller={**DEFAULTS["seller"], **(s.get("seller") or {})},
        site_analysis=bool(s.get("site_analysis")),
        ai_enabled=bool(s.get("ai_enabled")),
        proposal_validity=int(s.get("proposal_validity") or 7),
    )
