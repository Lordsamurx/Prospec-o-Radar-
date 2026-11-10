"""Contrato dos provedores de busca. Todos devolvem list[PlaceDTO]."""
from abc import ABC, abstractmethod

from ...schemas import PlaceDTO


class ProviderError(RuntimeError):
    """Erro com mensagem que pode ir direto para a tela."""


class QuotaExceeded(ProviderError):
    """Limite diário atingido: nada foi chamado."""


class PlacesProvider(ABC):
    name: str = "base"
    cost_per_request_usd: float = 0.0
    attribution: str | None = None

    def __init__(self) -> None:
        self.last_requests_made = 0

    @abstractmethod
    def search(self, niche: str, location: str, radius_m: int | None = None,
               center: tuple[float, float] | None = None) -> list[PlaceDTO]:
        """`center` = pino do mapa. Sem pino, o provedor resolve o local pelo texto."""
