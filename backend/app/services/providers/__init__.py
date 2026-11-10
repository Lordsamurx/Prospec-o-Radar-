"""Fontes de negócios. PLACES_PROVIDER no .env escolhe: osm (padrão) | google | mock."""
from collections.abc import Callable

from .base import PlacesProvider, ProviderError, QuotaExceeded
from .google import GooglePlacesProvider
from .mock import MockProvider
from .osm import OsmProvider

__all__ = ["PlacesProvider", "ProviderError", "QuotaExceeded", "GooglePlacesProvider", "MockProvider", "OsmProvider",
           "get_provider"]


def get_provider(settings, requests_today: Callable[[], int] = lambda: 0) -> PlacesProvider:
    kind = (settings.places_provider or "osm").lower()
    center = (settings.default_center_lat, settings.default_center_lng)
    if kind == "google":
        return GooglePlacesProvider(
            api_key=settings.google_maps_api_key.get_secret_value(),
            max_per_day=settings.max_places_requests_per_day,
            requests_today=requests_today,
            center=center,
        )
    if kind == "mock":
        return MockProvider()
    return OsmProvider(center=center)
