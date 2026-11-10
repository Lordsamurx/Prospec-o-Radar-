"""Bairros conhecidos de BH (centro aproximado) e contas de distância. Funções puras."""
import math
import re

from .normalize import fold

NEIGHBORHOODS: dict[str, tuple[str, float, float]] = {
    "savassi": ("Savassi", -19.9385, -43.9347),
    "funcionarios": ("Funcionários", -19.9320, -43.9310),
    "lourdes": ("Lourdes", -19.9330, -43.9450),
    "centro": ("Centro", -19.9191, -43.9386),
    "santo agostinho": ("Santo Agostinho", -19.9300, -43.9530),
    "sion": ("Sion", -19.9550, -43.9350),
    "pampulha": ("Pampulha", -19.8510, -43.9730),
    "buritis": ("Buritis", -19.9750, -43.9690),
    "castelo": ("Castelo", -19.8850, -44.0000),
    "santa efigenia": ("Santa Efigênia", -19.9250, -43.9220),
    "floresta": ("Floresta", -19.9150, -43.9300),
    "barro preto": ("Barro Preto", -19.9220, -43.9520),
    "cidade nova": ("Cidade Nova", -19.8870, -43.9300),
    "prado": ("Prado", -19.9280, -43.9640),
    "gutierrez": ("Gutierrez", -19.9370, -43.9590),
    "anchieta": ("Anchieta", -19.9500, -43.9280),
    "serra": ("Serra", -19.9400, -43.9200),
    "santa tereza": ("Santa Tereza", -19.9150, -43.9150),
    "sagrada familia": ("Sagrada Família", -19.9020, -43.9200),
    "padre eustaquio": ("Padre Eustáquio", -19.9130, -43.9830),
    "ouro preto": ("Ouro Preto", -19.8760, -43.9850),
    "venda nova": ("Venda Nova", -19.8140, -43.9540),
    "barreiro": ("Barreiro", -19.9760, -44.0260),
    "santa monica": ("Santa Mônica", -19.8300, -43.9790),
    "planalto": ("Planalto", -19.8320, -43.9500),
    "belvedere": ("Belvedere", -19.9750, -43.9390),
    "santo antonio": ("Santo Antônio", -19.9440, -43.9440),
    "cruzeiro": ("Cruzeiro", -19.9480, -43.9260),
    "carlos prates": ("Carlos Prates", -19.9150, -43.9590),
    "caicara": ("Caiçara", -19.9020, -43.9700),
    "nova suica": ("Nova Suíça", -19.9330, -43.9750),
    "estoril": ("Estoril", -19.9620, -43.9750),
    "liberdade": ("Liberdade", -19.8700, -43.9600),
    "uniao": ("União", -19.8850, -43.9200),
}
CITY_ALIASES = {"bh": "Belo Horizonte", "beaga": "Belo Horizonte", "belo horizonte": "Belo Horizonte"}


def known(neighborhood: str | None) -> bool:
    return bool(neighborhood) and fold(neighborhood) in NEIGHBORHOODS


def find_in_text(location: str | None) -> list[str]:
    """Chaves dos bairros conhecidos citados no texto do local (o mais longo primeiro)."""
    loc = fold(location)
    return [b for b in sorted(NEIGHBORHOODS, key=len, reverse=True) if re.search(rf"\b{re.escape(b)}\b", loc)]


def center_of(key: str) -> tuple[float, float]:
    _, lat, lng = NEIGHBORHOODS[key]
    return lat, lng


def display(key: str) -> str:
    return NEIGHBORHOODS[key][0]


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return math.hypot((lat1 - lat2) * 111.0, (lng1 - lng2) * 111.0 * math.cos(math.radians(lat1)))


def nearest(lat: float | None, lng: float | None, max_km: float = 1.2) -> str | None:
    """Nome do bairro conhecido mais perto do ponto (o OSM quase nunca traz o bairro)."""
    if lat is None or lng is None:
        return None
    best = None
    for key, (name, blat, blng) in NEIGHBORHOODS.items():
        d = distance_km(lat, lng, blat, blng)
        if d <= max_km and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else None


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def city_from_location(location: str) -> str:
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    city = parts[-1] if parts else (location or "").strip()
    return CITY_ALIASES.get(fold(city), city)
