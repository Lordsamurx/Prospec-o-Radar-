"""Gera a amostra estática de site a partir de templates-site/<modelo>/.

Um modelo por tipo de oferta: landing, institucional, cardapio, agendamento, links.
Textos e serviços vêm do catálogo de nichos; as cores vêm do setor.
Saída: data/previews/<slug>/{index.html, base.css, style.css, script.js, robots.txt}.
Estática e portátil (sem servidor), com noindex e faixa "Amostra".
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .. import catalog
from . import normalize

TEMPLATES = catalog.OFFER_TEMPLATES
TEMPLATE_LABELS = {"landing": "Landing page", "institucional": "Site institucional", "cardapio": "Cardápio digital",
                   "agendamento": "Página de agendamento", "links": "Página de links"}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(hex_color: str, target: tuple[int, int, int], t: float) -> str:
    r, g_, b = _rgb(hex_color)
    return "#%02x%02x%02x" % tuple(round(c + (tc - c) * t) for c, tc in zip((r, g_, b), target))


def _luminance(hex_color: str) -> float:
    def ch(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g_, b = (ch(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g_ + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def palette_for(sector_color: str) -> dict:
    """Cores da amostra a partir da cor do setor, garantindo contraste AA do texto sobre a marca."""
    brand = sector_color
    for _ in range(12):  # escurece até o texto branco ter contraste 4,5:1
        if contrast(brand, "#ffffff") >= 4.5:
            break
        brand = _mix(brand, (0, 0, 0), 0.12)
    return {"brand": brand, "brand_ink": "#ffffff", "soft": _mix(sector_color, (255, 255, 255), 0.88),
            "deep": _mix(brand, (0, 0, 0), 0.55)}


def slug_for(lead) -> str:
    return f"{normalize.slugify(lead.name)[:60]}-{lead.id}"


def template_for(lead, services: dict[str, catalog.ServiceItem]) -> str:
    """Modelo da amostra: o do primeiro serviço escolhido (ou recomendado) que tiver modelo; senão o do nicho."""
    for key in [*(lead.offered or []), lead.rec_main]:
        svc = services.get(key or "")
        if svc is not None and svc.template in TEMPLATES and svc.kind == "site":
            return svc.template
    return catalog.niches().get_or_other(lead.niche).template


def build_context(lead) -> dict:
    cat = catalog.niches()
    niche = cat.get_or_other(lead.niche)
    sector = cat.sector_by_key[niche.sector]
    services = niche.services_for(lead.categories)
    raw_hours = (lead.opening_hours or "").replace("\n", ";")
    hours = [h.strip() for h in raw_hours.split(";") if h.strip()]
    wa_text = niche.wa_message.format(name=lead.name)
    rating = lead.rating
    return {
        "name": lead.name,
        "neighborhood": lead.neighborhood,
        "city": lead.city or "",
        "address": lead.address or "",
        "phone": lead.phone,
        "phone_digits": normalize.phone_digits(lead.phone) or "",
        "whatsapp_url": normalize.whatsapp_link(lead.phone, wa_text),
        "wa_number": ("55" + (normalize.phone_digits(lead.phone) or "")) if normalize.phone_type(lead.phone) == "mobile" else "",
        "maps_url": lead.maps_url,
        "rating": rating,
        "rating_text": normalize.stars(rating) if rating else "",
        "reviews_count": lead.reviews_count,
        "hours": hours,
        "services": [{"icon": i, "title": t, "text": x} for i, t, x in services],
        "niche_label": "" if niche.is_other else niche.label,
        "niche_plural": niche.plural,
        "sector_icon": sector.icon,
        "tagline": niche.tagline,
        "cta": niche.cta,
        "palette": palette_for(sector.color),
        "year": date.today().year,
    }


def generate(lead, templates_dir: Path, out_root: Path, template: str = "landing") -> tuple[str, Path]:
    if template not in TEMPLATES:
        raise ValueError(f"Modelo desconhecido: {template}")
    src = templates_dir / template
    shared = templates_dir / "_shared"
    if not (src / "index.html").exists():
        raise FileNotFoundError(f"Modelo não encontrado: {src}")
    slug = slug_for(lead)
    out = out_root / slug
    out.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader([str(src), str(shared)]), autoescape=select_autoescape(["html"]),
                      undefined=StrictUndefined)
    html = env.get_template("index.html").render(**build_context(lead))
    (out / "index.html").write_text(html, encoding="utf-8")
    for folder in (shared, src):
        for asset in folder.iterdir():
            if asset.is_file() and asset.suffix in (".css", ".js", ".svg", ".png", ".jpg", ".webp"):
                shutil.copyfile(asset, out / asset.name)
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    return slug, out
