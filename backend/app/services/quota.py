"""Cota do Google Places: 30 requisições por dia, contadas no servidor, com trava antes de chamar.

Conta pela tabela searches (requests_made), inclusive as que falharam. O dia vira à meia-noite
de Brasília. O OpenStreetMap não tem cota aqui (é grátis), mas a tela mostra o uso do mesmo jeito.
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Search, SearchJob
from . import timeutil


@dataclass(frozen=True)
class QuotaStatus:
    provider: str
    limited: bool
    used_today: int
    limit: int
    used_month: int
    pending_jobs: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used_today) if self.limited else 10**6

    @property
    def blocked(self) -> bool:
        return self.limited and self.used_today >= self.limit

    @property
    def percent(self) -> int:
        return min(100, round(100 * self.used_today / self.limit)) if self.limited and self.limit else 0

    def to_dict(self) -> dict:
        return {"provider": self.provider, "limited": self.limited, "used_today": self.used_today,
                "limit": self.limit, "remaining": self.remaining if self.limited else None,
                "used_month": self.used_month, "blocked": self.blocked, "pending_jobs": self.pending_jobs}


def requests_since(db: Session, provider: str, since) -> int:
    total = db.scalar(select(func.coalesce(func.sum(Search.requests_made), 0)).where(
        Search.provider == provider, Search.created_at >= since))
    return int(total or 0)


def requests_today(db: Session, provider: str) -> int:
    return requests_since(db, provider, timeutil.day_start())


def status(db: Session, settings) -> QuotaStatus:
    provider = (settings.places_provider or "osm").lower()
    pending = db.scalar(select(func.count()).select_from(SearchJob).where(SearchJob.status == "pendente")) or 0
    return QuotaStatus(
        provider=provider,
        limited=provider == "google",
        used_today=requests_today(db, provider),
        limit=settings.max_places_requests_per_day,
        used_month=requests_since(db, provider, timeutil.month_start()),
        pending_jobs=int(pending),
    )
