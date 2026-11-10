"""Helpers de resposta: a mesma rota serve HTML (página ou fragmento HTMX) ou JSON."""
import json
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import catalog
from .config import APP_DIR, get_settings
from .models import LOST_REASONS, PROFILES, SCORES, STATUS_LABELS, STATUSES, Lead
from .services import app_settings, lead_service, normalize, quota, timeutil
from .services.outreach_text import CHANNELS, KINDS
from .services.site_generator import TEMPLATE_LABELS

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

SITE_LABELS = {"none": "Sem site", "social": "Só rede social", "platform": "Plataforma", "own": "Site próprio"}
SITE_KIND_LABELS = {"none": "Sem site", "social": "Só rede social", "platform": "Página de plataforma",
                    "own_ok": "Site próprio", "own_nohttps": "Site sem HTTPS", "own_down": "Site fora do ar",
                    "own_weak": "Site com problemas"}
NAV = [("/", "Hoje", "hoje"), ("/leads", "Leads", "leads"), ("/buscas", "Buscas", "buscas"),
       ("/funil", "Funil", "funil"), ("/servicos", "Serviços", "servicos"), ("/metricas", "Métricas", "metricas")]
PRIORITY_LABELS = {"principal": "Principal", "complemento": "Complemento", "upsell": "Depois"}
TONE_LABELS = {"bom": "Bom", "atencao": "Atenção", "ruim": "Falta", "desconhecido": "Não conferido"}


def _money(v) -> str:
    return catalog.brl(float(v)) if v not in (None, "") else "—"


def _qs(pairs) -> str:
    return urlencode(list(pairs))


templates.env.globals.update(
    STATUSES=STATUSES, STATUS_LABELS=STATUS_LABELS, SCORES=SCORES, PROFILES=PROFILES, LOST_REASONS=LOST_REASONS,
    SITE_LABELS=SITE_LABELS, SITE_KIND_LABELS=SITE_KIND_LABELS, NAV=NAV, CHANNELS=CHANNELS, KINDS=KINDS,
    TEMPLATE_LABELS=TEMPLATE_LABELS, PRIORITY_LABELS=PRIORITY_LABELS, TONE_LABELS=TONE_LABELS,
    whatsapp_link=normalize.whatsapp_link, settings=get_settings, cat=catalog.niches, qs=_qs,
    PROVIDER_LABELS=lead_service.PROVIDER_LABELS,
)
templates.env.filters.update(stars=normalize.stars, dt=timeutil.fmt, day=timeutil.fmt_day, money=_money,
                             date=lambda v: timeutil.fmt(v, False))


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def wants_json(request: Request) -> bool:
    if request.query_params.get("format") == "json":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and not is_htmx(request)


async def read_body(request: Request) -> dict[str, Any]:
    """Corpo como dicionário (JSON ou formulário). Campos repetidos viram lista em `chave[]`... não:
    use read_multi para listas."""
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    form = await request.form()
    return {k: v for k, v in form.items() if isinstance(v, str)}


async def read_multi(request: Request, key: str) -> list[str]:
    """Lista de valores de um campo (checkboxes de formulário ou lista no JSON)."""
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        v = data.get(key) if isinstance(data, dict) else None
        if isinstance(v, list):
            return [str(x) for x in v]
        return [x.strip() for x in str(v).split(",") if x.strip()] if v not in (None, "") else []
    form = await request.form()
    out = [str(v) for v in form.getlist(key) if isinstance(v, str)]
    if len(out) == 1 and "," in out[0]:
        out = [x.strip() for x in out[0].split(",") if x.strip()]
    return out


def include_mock(request: Request | None = None) -> bool:
    """Fictícios aparecem no modo demonstração (PLACES_PROVIDER=mock) ou com ?show_mock=1."""
    if get_settings().places_provider.lower() == "mock":
        return True
    return bool(request) and request.query_params.get("show_mock") in ("1", "true", "on")


def chrome(request: Request, db: Session) -> dict:
    """O que toda página mostra: cota, aviso de fictícios, tela ativa."""
    s = get_settings()
    path = request.url.path
    active = next((key for href, _, key in NAV if (path == href if href == "/" else path.startswith(href))), "")
    return {"quota": quota.status(db, s), "mock_mode": s.places_provider.lower() == "mock",
            "mock_hidden": 0 if include_mock(request) else lead_service.mock_count(db), "active": active,
            "provider": s.places_provider.lower(), "has_password": bool(s.app_password.get_secret_value())}


def render(request: Request, name: str, ctx: dict, status_code: int = 200, trigger: dict | None = None,
           db: Session | None = None) -> HTMLResponse:
    if db is not None and "quota" not in ctx:
        ctx = {**chrome(request, db), **ctx}
    resp = templates.TemplateResponse(request, name, ctx, status_code=status_code)
    if trigger:
        resp.headers["HX-Trigger"] = json.dumps(trigger)
    return resp


def json_or_html(request: Request, data: Any, name: str, ctx: dict, **kw) -> HTMLResponse | JSONResponse:
    if wants_json(request):
        return JSONResponse(data, status_code=kw.get("status_code", 200))
    return render(request, name, ctx, **kw)


def lead_or_404(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    return lead


def ctx_of(db: Session) -> app_settings.Ctx:
    return app_settings.load_ctx(db)


def toast(message: str, **extra) -> dict:
    return {"toast": message, **extra}
