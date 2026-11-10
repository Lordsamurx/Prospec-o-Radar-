"""Configurações: provedor, cota, franquias, limites por nicho, meta, cadência, perfil do vendedor,
IA, análise de site, plataformas, backup e fictícios."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog
from ..config import get_settings
from ..db import get_db
from ..models import DeletionLog
from ..services import ai, app_settings, backup, lead_service, normalize
from ..web import ctx_of, read_body, render, wants_json

router = APIRouter()


def _page(request: Request, db: Session, saved: str | None = None, status_code: int = 200):
    s = get_settings()
    ctx = ctx_of(db)
    all_s = app_settings.all_settings(db)
    cfg = ai.config_from(s, ctx.ai_enabled)
    data = {
        "provider": s.places_provider, "has_google_key": bool(s.google_maps_api_key.get_secret_value()),
        "limit": s.max_places_requests_per_day, "franchises": ctx.franchises, "weekly_goal": ctx.weekly_goal,
        "cadence": ctx.cadence, "seller": ctx.seller, "site_analysis": ctx.site_analysis,
        "ai_enabled": ctx.ai_enabled, "ai_keys": {"gemini": bool(cfg.gemini_key), "groq": bool(cfg.groq_key)},
        "niche_limits": ctx.niche_limits, "extra_platforms": ctx.extra_platforms,
        "proposal_validity": ctx.proposal_validity, "base_url": s.base_url,
        "previews_public_url": s.previews_public_url, "preview_link_is_local": s.preview_link_is_local,
        "has_password": bool(s.app_password.get_secret_value()),
        "database": str(s.database_path) if s.database_path else s.database_url,
        "db_in_onedrive": "onedrive" in str(s.database_path or "").lower(),
        "deletions": int(db.scalar(select(func.count()).select_from(DeletionLog)) or 0),
        "mock_count": lead_service.mock_count(db),
    }
    if wants_json(request):
        return JSONResponse({**data, "backups": [b["name"] for b in backup.list_backups(s.backups_path)]},
                            status_code=status_code)
    return render(request, "settings.html", {**data, "backups": backup.list_backups(s.backups_path)[:12],
                                             "saved": saved, "ctx": ctx, "all": all_s,
                                             "pagespeed_key": bool(s.pagespeed_api_key.get_secret_value())},
                  status_code=status_code, db=db)


@router.get("/config")
def config_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, db)


def _lines(text: str, limit: int = 200) -> list[str]:
    out = []
    for raw in (text or "").replace(",", "\n").splitlines():
        v = " ".join(raw.split())[:80]
        if v and v.lower() not in {x.lower() for x in out}:
            out.append(v)
    return out[:limit]


@router.post("/config")
async def save_config(request: Request, db: Session = Depends(get_db)):
    body = await read_body(request)
    section = body.get("section") or ""
    recalc = False
    if section == "franchises":
        app_settings.put(db, "franchises", _lines(body.get("franchises", "")))
        recalc = True
    elif section == "goal":
        try:
            goal = int(body.get("weekly_goal") or 5)
            cadence = [int(x) for x in str(body.get("cadence") or "3,5,7").replace(" ", "").split(",") if x]
            validity = int(body.get("proposal_validity") or 7)
        except ValueError:
            raise HTTPException(422, "Use só números na meta, na cadência e na validade.") from None
        if not (1 <= goal <= 200) or not cadence or len(cadence) > 6 or any(not (1 <= c <= 60) for c in cadence) \
                or not (1 <= validity <= 90):
            raise HTTPException(422, "Meta de 1 a 200; cadência com até 6 intervalos de 1 a 60 dias; validade de 1 a 90 dias.")
        app_settings.put(db, "weekly_goal", goal)
        app_settings.put(db, "cadence", cadence)
        app_settings.put(db, "proposal_validity", validity)
    elif section == "seller":
        seller = {k: " ".join(str(body.get(k, "")).split())[:200] for k in ("name", "what", "tone", "city")}
        if not seller["name"]:
            raise HTTPException(422, "Diga seu nome: ele abre as mensagens.")
        app_settings.put(db, "seller", seller)
    elif section == "toggles":
        on = lambda k: str(body.get(k, "")).lower() in ("1", "true", "on", "sim")  # noqa: E731
        app_settings.put(db, "site_analysis", on("site_analysis"))
        app_settings.put(db, "ai_enabled", on("ai_enabled"))
        recalc = True
    elif section == "limits":
        niche = body.get("niche") or ""
        n = catalog.niches().get(niche)
        if n is None:
            raise HTTPException(422, "Escolha um nicho da lista.")
        limits = dict(ctx_of(db).niche_limits)
        if str(body.get("reset", "")).lower() in ("1", "true", "on"):
            limits.pop(niche, None)
        else:
            try:
                rating = float(str(body.get("min_rating") or n.min_rating).replace(",", "."))
                reviews = int(body.get("min_reviews") or n.min_reviews)
            except ValueError:
                raise HTTPException(422, "Use números, como 4,2 e 20.") from None
            if not (0 <= rating <= 5) or not (0 <= reviews <= 10000):
                raise HTTPException(422, "Nota de 0 a 5 e avaliações de 0 a 10.000.")
            limits[niche] = {"min_rating": rating, "min_reviews": reviews}
        app_settings.put(db, "niche_limits", limits)
        recalc = True
    elif section == "platforms":
        extra = {}
        for line in (body.get("platforms") or "").splitlines():
            domain, _, name = line.partition("=")
            host = normalize.host_of(domain.strip())
            if host and "." in host:
                extra[host] = " ".join(name.split())[:60] or host
        app_settings.put(db, "extra_platforms", extra)
        recalc = True
    else:
        raise HTTPException(422, "Seção desconhecida.")
    db.commit()
    if recalc:
        lead_service.refresh_all(db, ctx_of(db))
    return _page(request, db, saved=section)


@router.post("/config/backup")
def backup_now(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    dest = backup.backup_now(s.database_path, s.backups_path, "manual")
    if dest is None:
        raise HTTPException(409, "Este banco não é um arquivo SQLite: não há o que copiar.")
    if wants_json(request):
        return JSONResponse({"backup": dest.name, "size_kb": round(dest.stat().st_size / 1024)}, status_code=201)
    return _page(request, db, saved="backup")


@router.get("/config/backup/{name}")
def download_backup(name: str):
    root = get_settings().backups_path.resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file() or not name.startswith("radar-") or not name.endswith(".db"):
        raise HTTPException(404, "Backup não encontrado.")
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/config/arquivar-ficticios")
def archive_mock(request: Request, db: Session = Depends(get_db)):
    n = lead_service.archive_mock(db)
    if wants_json(request):
        return JSONResponse({"archived": n})
    return _page(request, db, saved="mock")
