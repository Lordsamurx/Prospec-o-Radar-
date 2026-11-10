"""Normalização de telefone (BR), classificação do site e utilidades de texto. Funções puras."""
import re
import unicodedata
from urllib.parse import quote, urlparse

from .. import catalog


def fold(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower().strip()


def phone_digits(phone: str | None) -> str | None:
    """Só os dígitos, sem o +55. Devolve DDD + número (10 ou 11 dígitos) ou None."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone.split(";")[0])
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) in (11, 12):  # 0 + DDD
        digits = digits[1:]
    return digits if len(digits) in (10, 11) else None


def phone_type(phone: str | None) -> str | None:
    """'mobile' (11 dígitos, começa com 9 depois do DDD), 'landline' (10 dígitos, 2–5) ou None."""
    d = phone_digits(phone)
    if not d:
        return None
    if len(d) == 11 and d[2] == "9":
        return "mobile"
    if len(d) == 10 and d[2] in "2345":
        return "landline"
    return None


def format_phone(phone: str | None) -> str | None:
    d = phone_digits(phone)
    if not d:
        return (phone or "").strip()[:40] or None
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    return f"({d[:2]}) {d[2:6]}-{d[6:]}"


def whatsapp_link(phone: str | None, text: str | None = None) -> str | None:
    """Link wa.me só para celular. Não envia nada: abre o WhatsApp do Samuel com o texto pronto."""
    if phone_type(phone) != "mobile":
        return None
    url = f"https://wa.me/55{phone_digits(phone)}"
    if text:
        url += "?text=" + quote(text)
    return url


def host_of(url: str | None) -> str:
    if not url or not url.strip():
        return ""
    raw = url.strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = (urlparse(raw).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _match(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def classify_site(url: str | None, extra_platforms: dict[str, str] | None = None) -> tuple[str, str | None]:
    """(situação, plataforma). Situação: none | social | platform | own.

    'platform' = página dentro de um serviço de terceiros (iFood, Booksy, Wix grátis...).
    A lista vem de catalog/platforms.yaml mais o que o Samuel cadastrar em Configurações."""
    host = host_of(url)
    if not host:
        return "none", None
    p = catalog.platforms()
    if any(_match(host, d) for d in p.social):
        return "social", _social_name(host)
    table = {**p.platform, **{k.lower(): v for k, v in (extra_platforms or {}).items()}}
    for domain in sorted(table, key=len, reverse=True):
        if _match(host, domain):
            return "platform", table[domain]
    return "own", None


def _social_name(host: str) -> str:
    for needle, name in (("instagram", "Instagram"), ("facebook", "Facebook"), ("fb.", "Facebook"),
                         ("linktr", "Linktree"), ("wa.", "WhatsApp"), ("whatsapp", "WhatsApp"),
                         ("tiktok", "TikTok"), ("youtube", "YouTube")):
        if needle in host:
            return name
    return "página de links"


def site_status(url: str | None) -> str:
    return classify_site(url)[0]


def safe_url(url: str | None) -> str | None:
    """Só aceita http(s). Bloqueia javascript:, data: e afins vindos da fonte externa."""
    if not url or not url.strip():
        return None
    raw = url.strip()
    if "://" not in raw and not raw.lower().startswith(("javascript:", "data:", "vbscript:")):
        raw = "https://" + raw
    try:
        p = urlparse(raw)
    except ValueError:
        return None
    return raw[:400] if p.scheme in ("http", "https") and p.hostname else None


def is_https(url: str | None) -> bool:
    return bool(url) and url.strip().lower().startswith("https://")


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t or "lead"


def stars(rating: float | None) -> str:
    return f"{rating:.1f}".replace(".", ",") if rating is not None else "sem nota"


def csv_cell(value) -> str:
    """Evita injeção de fórmula no Excel (=, +, -, @ no começo da célula)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def clean_tag(text: str) -> str:
    """Tag curta: minúsculas, só letras, números, espaço e hífen."""
    t = re.sub(r"[^\w\s-]", "", (text or "").lower(), flags=re.UNICODE).replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()[:30].strip()
