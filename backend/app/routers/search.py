"""Buscas: nova busca (texto ou mapa), busca em lote, fila, histórico e repetir."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog
from ..config import get_settings
from ..db import get_db
from ..models import Search, SearchJob
from ..schemas import SearchIn
from ..services import geo, lead_service, quota
from ..services.providers import ProviderError
from ..web import ctx_of, json_or_html, read_body, read_multi, render, wants_json

router = APIRouter()
TRIGGER = {"leads-changed": True, "quota-changed": True}


def _num(v, cast=float):
    try:
        return cast(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _search_out(s: Search) -> dict:
    return {"id": s.id, "niche": s.niche, "niche_key": s.niche_key, "location": s.location_text,
            "radius_m": s.radius_m, "lat": s.lat, "lng": s.lng, "provider": s.provider,
            "requests_made": s.requests_made, "results": s.results_count, "new": s.new_count,
            "cached": s.cached_from_id is not None, "error": s.error, "at": s.created_at.isoformat()}


def _page_ctx(db: Session) -> dict:
    s = get_settings()
    history = db.scalars(select(Search).order_by(Search.created_at.desc(), Search.id.desc()).limit(40)).all()
    jobs = db.scalars(select(SearchJob).where(SearchJob.status == "pendente").order_by(SearchJob.id)).all()
    failed = db.scalars(select(SearchJob).where(SearchJob.status == "erro").order_by(SearchJob.id.desc()).limit(5)).all()
    return {"history": history, "jobs": jobs, "failed": failed, "counts": lead_service.niche_counts(db, True),
            "neighborhoods": [v[0] for v in geo.NEIGHBORHOODS.values()], "default_city": s.default_city,
            "center": (s.default_center_lat, s.default_center_lng)}


@router.get("/buscas")
def searches_page(request: Request, db: Session = Depends(get_db)):
    ctx = _page_ctx(db)
    if wants_json(request):
        return JSONResponse({"history": [_search_out(s) for s in ctx["history"]],
                             "queue": [{"id": j.id, "niche": j.niche, "location": j.location_text} for j in ctx["jobs"]],
                             "quota": quota.status(db, get_settings()).to_dict()})
    return render(request, "searches.html", ctx, db=db)


async def _do_search(request: Request, db: Session):
    body = await read_body(request)
    if body.get("radius_km"):
        km = _num(body.pop("radius_km"))
        body["radius_m"] = int(km * 1000) if km is not None else -1  # -1 força a mensagem de raio inválido
    body = {k: v for k, v in body.items() if v not in ("", None)}
    try:
        data = SearchIn.model_validate(body)
        if not data.location.strip() and (data.lat is None or data.lng is None):
            raise ValueError("local")
    except (ValidationError, ValueError) as exc:
        fields = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")} if isinstance(exc, ValidationError) else set()
        msg = ("O raio precisa ficar entre 0,1 e 50 km." if fields == {"radius_m"}
               else "Diga o que procurar e onde (um bairro, uma cidade ou um pino no mapa).")
        return json_or_html(request, {"error": msg}, "partials/search_result.html", {"error": msg}, status_code=422)
    settings = get_settings()
    center = (data.lat, data.lng) if data.lat is not None and data.lng is not None else None
    location = data.location.strip() or (geo.nearest(*center, max_km=3) if center else "") or settings.default_city
    try:
        result = lead_service.run_search(db, settings, ctx_of(db), data.niche, location, data.radius_m, center)
    except ProviderError as exc:
        msg = str(exc)
        return json_or_html(request, {"error": msg, "quota": quota.status(db, settings).to_dict()},
                            "partials/search_result.html", {"error": msg}, status_code=400, trigger={"quota-changed": True})
    s = result["search"]
    payload = {"search_id": s.id, "provider": s.provider, "niche_key": s.niche_key, "total": result["total"],
               "created": result["created"], "updated": result["updated"], "cached": result["cached"],
               "requests_made": s.requests_made, "cost_estimate_usd": s.cost_estimate,
               "attribution": result["attribution"], "quota": quota.status(db, settings).to_dict()}
    return json_or_html(request, payload, "partials/search_result.html",
                        {"r": payload, "niche_label": catalog.niches().label(s.niche_key), "search": s}, trigger=TRIGGER)


@router.post("/buscas")
async def search(request: Request, db: Session = Depends(get_db)):
    return await _do_search(request, db)


@router.post("/search", include_in_schema=False)
async def search_legacy(request: Request, db: Session = Depends(get_db)):
    """Mesmo endereço do protótipo."""
    return await _do_search(request, db)


@router.post("/buscas/lote")
async def batch(request: Request, db: Session = Depends(get_db)):
    """Fila: linhas de texto ("pizzaria em Savassi"), ou nichos × bairros, ou nichos × pinos do mapa."""
    body = await read_body(request)
    settings = get_settings()
    items = lead_service.parse_batch_lines(body.get("lines", ""), settings.default_city)
    niches = await read_multi(request, "niches")
    hoods = await read_multi(request, "neighborhoods")
    city = (body.get("city") or settings.default_city).strip()
    radius = _num(body.get("radius_km"))
    radius_m = int(radius * 1000) if radius and 0.1 <= radius <= 50 else None
    for n in niches:
        label = catalog.niches().get(n).label if catalog.niches().get(n) else n
        for b in hoods:
            items.append({"niche": label, "location": f"{b}, {city}", "radius_m": radius_m})
    pins = body.get("pins")
    if isinstance(pins, str) and pins.strip():
        import json

        try:
            pins = json.loads(pins)
        except ValueError:
            pins = []
    for pin in pins if isinstance(pins, list) else []:
        lat, lng = _num(pin.get("lat")), _num(pin.get("lng"))
        if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        pr = _num(pin.get("radius_m"), int) or 1500
        place = geo.nearest(lat, lng, max_km=3) or city
        for n in niches:
            label = catalog.niches().get(n).label if catalog.niches().get(n) else n
            items.append({"niche": label, "location": f"{place}, {city}" if place != city else city,
                          "radius_m": max(100, min(pr, 50000)), "lat": round(lat, 6), "lng": round(lng, 6)})
    if not items:
        msg = "Nada para buscar: escreva uma linha por busca, ou marque nichos e bairros (ou pinos no mapa)."
        return json_or_html(request, {"error": msg}, "partials/queue.html", {**_page_ctx(db), "error": msg}, status_code=422, db=db)
    if len(items) > 200:
        raise HTTPException(422, "Lote grande demais: no máximo 200 buscas por vez.")
    added = lead_service.enqueue(db, items)
    q = quota.status(db, settings)
    return json_or_html(request, {"queued": added, "pending": q.pending_jobs, "quota": q.to_dict()},
                        "partials/queue.html", {**_page_ctx(db), "added": added, "autorun": True}, db=db,
                        trigger={"toast": f"{added} busca(s) na fila"})


@router.post("/buscas/fila/processar")
def process(request: Request, db: Session = Depends(get_db)):
    """Roda a próxima busca da fila. A tela chama de novo enquanto houver fila e cota."""
    settings = get_settings()
    result = lead_service.process_queue(db, settings, ctx_of(db), max_jobs=1)
    again = bool(result["done"] or result["errors"]) and result["pending"] > 0 and not result["stopped"]
    return json_or_html(request, {**result, "quota": quota.status(db, settings).to_dict()}, "partials/queue.html",
                        {**_page_ctx(db), "result": result, "autorun": again}, db=db, trigger=TRIGGER)


@router.post("/buscas/fila/{job_id}/cancelar")
def cancel_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(SearchJob, job_id)
    if job and job.status == "pendente":
        job.status = "cancelada"
        db.commit()
    return json_or_html(request, {"id": job_id, "status": "cancelada"}, "partials/queue.html", _page_ctx(db), db=db)


@router.post("/buscas/{search_id}/repetir")
def repeat(search_id: int, request: Request, db: Session = Depends(get_db)):
    """Repete uma busca do histórico. Respeita o cache do Google e a cota do dia."""
    old = db.get(Search, search_id)
    if not old:
        raise HTTPException(404, "Busca não encontrada.")
    settings = get_settings()
    center = (old.lat, old.lng) if old.lat is not None and old.lng is not None else None
    try:
        result = lead_service.run_search(db, settings, ctx_of(db), old.niche, old.location_text, old.radius_m, center)
    except ProviderError as exc:
        msg = str(exc)
        return json_or_html(request, {"error": msg}, "partials/search_result.html", {"error": msg}, status_code=400)
    s = result["search"]
    payload = {"search_id": s.id, "provider": s.provider, "niche_key": s.niche_key, "total": result["total"],
               "created": result["created"], "updated": result["updated"], "cached": result["cached"],
               "requests_made": s.requests_made, "cost_estimate_usd": s.cost_estimate,
               "attribution": result["attribution"], "quota": quota.status(db, settings).to_dict()}
    return json_or_html(request, payload, "partials/search_result.html",
                        {"r": payload, "niche_label": catalog.niches().label(s.niche_key), "search": s}, trigger=TRIGGER)


@router.get("/api/quota")
def quota_api(request: Request, db: Session = Depends(get_db)):
    q = quota.status(db, get_settings())
    if request.headers.get("hx-request") == "true":
        return render(request, "partials/quota_chip.html", {"quota": q})
    return JSONResponse(q.to_dict())
