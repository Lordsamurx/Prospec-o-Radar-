"""Configuração lida do .env da pasta v3/.

Segredos (chave do Google, senha, chaves de IA) são SecretStr: nunca aparecem em repr ou log.
Se a v3 ainda não tem .env próprio, aproveita do .env do protótipo (pasta de cima) só estas
chaves: GOOGLE_MAPS_API_KEY, PLACES_PROVIDER, limite diário, APP_USER/APP_PASSWORD e BASE_URL.
O banco do protótipo nunca é herdado: a v3 tem o próprio.
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]  # .../v3
APP_DIR = Path(__file__).resolve().parent
PARENT_KEYS = {
    "GOOGLE_MAPS_API_KEY": "google_maps_api_key",
    "PLACES_PROVIDER": "places_provider",
    "MAX_PLACES_REQUESTS_PER_DAY": "max_places_requests_per_day",
    "MAX_SEARCHES_PER_DAY": "max_places_requests_per_day",
    "APP_USER": "app_user",
    "APP_PASSWORD": "app_password",
    "BASE_URL": "base_url",
}


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip().upper()] = v
    return out


class ParentEnvSource(PydanticBaseSettingsSource):
    """Fonte de menor prioridade: chaves permitidas do .env do protótipo."""

    def get_field_value(self, field, field_name):  # pragma: no cover - não usado
        return None, field_name, False

    def __call__(self) -> dict:
        if os.environ.get("RADAR_NO_PARENT_ENV") == "1":
            return {}
        raw = read_env_file(ROOT_DIR.parent / ".env")
        out: dict = {}
        for env_key, field in PARENT_KEYS.items():
            if raw.get(env_key) and field not in out:
                out[field] = raw[env_key]
        return out


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore",
                                      populate_by_name=True)

    places_provider: str = "osm"  # osm (padrão, grátis) | google | mock
    google_maps_api_key: SecretStr = SecretStr("")
    database_url: str = "sqlite:///./data/radar.db"
    max_places_requests_per_day: int = Field(
        default=30, validation_alias=AliasChoices("MAX_PLACES_REQUESTS_PER_DAY", "MAX_SEARCHES_PER_DAY",
                                                  "max_places_requests_per_day"))
    search_cache_days: int = 30
    google_stale_days: int = 30
    base_url: str = "http://localhost:8000"
    # Endereço público das amostras (Cloudflare Pages). Vazio = usa BASE_URL/previews/.
    previews_public_url: str = ""
    cloudflare_pages_project: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    app_user: str = "samuel"
    app_password: SecretStr = SecretStr("")
    previews_dir: str = "data/previews"
    backups_dir: str = "data/backups"
    exports_dir: str = "data/exports"
    templates_site_dir: str = "templates-site"
    default_center_lat: float = -19.9191  # Praça Sete, BH
    default_center_lng: float = -43.9386
    default_city: str = "Belo Horizonte"
    # Opcionais (4.10). Sem chave = recurso desligado.
    pagespeed_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    auto_backup: bool = True

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return init_settings, env_settings, dotenv_settings, ParentEnvSource(settings_cls), file_secret_settings

    def _resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def resolved_database_url(self) -> str:
        """Caminho relativo do SQLite é resolvido a partir da pasta v3/."""
        prefix = "sqlite:///"
        url = self.database_url
        if url.startswith(prefix):
            rel = url[len(prefix):]
            if rel != ":memory:":
                path = Path(rel)
                if not path.is_absolute():
                    path = (ROOT_DIR / rel).resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                return prefix + path.as_posix()
        return url

    @property
    def database_path(self) -> Path | None:
        url = self.resolved_database_url
        if url.startswith("sqlite:///") and ":memory:" not in url:
            return Path(url[len("sqlite:///"):])
        return None

    @property
    def previews_path(self) -> Path:
        return self._resolve(self.previews_dir)

    @property
    def backups_path(self) -> Path:
        return self._resolve(self.backups_dir)

    @property
    def exports_path(self) -> Path:
        return self._resolve(self.exports_dir)

    @property
    def templates_site_path(self) -> Path:
        return self._resolve(self.templates_site_dir)

    def preview_url(self, slug: str) -> str:
        """Link da amostra que vai na mensagem: o endereço público, se houver; senão o da própria app."""
        if self.previews_public_url.strip():
            return f"{self.previews_public_url.strip().rstrip('/')}/{slug}/"
        return f"{self.base_url.rstrip('/')}/previews/{slug}/"

    @property
    def preview_link_is_local(self) -> bool:
        """True quando o link da amostra só abre neste computador (não serve para mandar ao lead)."""
        url = self.previews_public_url.strip() or self.base_url
        return any(h in url for h in ("localhost", "127.0.0.1", "0.0.0.0"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
