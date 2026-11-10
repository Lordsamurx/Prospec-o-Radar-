"""Tela Serviços por categoria: matriz setor/nicho × serviço, catálogo editável e demanda por nicho."""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import Lead
from ..services import app_settings, lead_service, metrics
from ..web import ctx_of, include_mock, json_or_html, read_body, render, wants_json

router = APIRouter()


def demand(db: Session, mock: bool) -> tuple[dict[tuple[str, str], int], dict[str, int], dict[str, int]]:
    """Quantos leads de cada nicho têm cada serviço recomendado."""
    conds = [Lead.do_not_contact.is_(False), Lead.archived.is_(False), Lead.rec_keys != ""]
    if not mock:
        conds.append(Lead.is_mock.is_(False))
    by_pair: dict[tuple[str, str], int] = defaultdict(int)
    by_service: dict[str, int] = defaultdict(int)
    main: dict[str, int] = defaultdict(int)
    for niche, rec_keys, rec_main in db.execute(select(Lead.niche, Lead.rec_keys, Lead.rec_main).where(*conds)):
        for k in (rec_keys or "").split(","):
            if k:
                by_pair[(niche or "outro", k)] += 1
                by_service[k] += 1
        if rec_main:
            main[rec_main] += 1
    return by_pair, by_service, main


@router.get("/servicos")
def services_page(request: Request, db: Session = Depends(get_db)):
    ctx = ctx_of(db)
    mock = include_mock(request)
    by_pair, by_service, main = demand(db, mock)
    cat = catalog.niches()
    counts = lead_service.niche_counts(db, mock)
    matrix = []
    for sector, niches in cat.by_sector():
        rows = []
        for n in niches:
            offers = list(dict.fromkeys([n.default_offer, *sector.offers]))
            rows.append({"niche": n, "leads": counts.get(n.key, 0), "main": n.default_offer,
                         "cells": {k: by_pair.get((n.key, k), 0) for k in offers}})
        matrix.append({"sector": sector, "rows": rows, "leads": sum(r["leads"] for r in rows),
                       "offers": list(dict.fromkeys(sector.offers))})
    highlights = sorted(((n, k, c) for (n, k), c in by_pair.items() if k in ctx.services), key=lambda x: -x[2])[:8]
    if wants_json(request):
        return JSONResponse({
            "services": [{"key": s.key, "name": s.name, "active": s.active, "price_min": s.price_min,
                          "price_max": s.price_max, "recurring": s.recurring, "leads": by_service.get(s.key, 0)}
                         for s in ctx.services.values()],
            "matrix": [{"sector": m["sector"].key, "niches": [
                {"niche": r["niche"].key, "main": r["main"], "leads": r["leads"], "recommended": r["cells"]}
                for r in m["rows"]]} for m in matrix],
            "demand": [{"niche": n, "service": k, "leads": c} for n, k, c in highlights],
        })
    return render(request, "services.html", {
        "services": ctx.services, "matrix": matrix, "by_service": by_service, "main_counts": main,
        "highlights": [(cat.get_or_other(n), ctx.services[k], c) for n, k, c in highlights], "ctx": ctx}, db=db)


@router.post("/servicos/{key}")
async def save_service(key: str, request: Request, db: Session = Depends(get_db)):
    if key not in catalog.services():
        raise HTTPException(404, "Serviço não encontrado.")
    body = await read_body(request)

    def price(v):
        if v in (None, ""):
            return None
        try:
            s = str(v).replace("R$", "").strip()
            if "," in s:
                s = s.replace(".", "").replace(",", ".")
            n = float(s)
        except ValueError:
            raise HTTPException(422, "Preço inválido. Use só números, como 1500 ou 1.500,00.") from None
        if n < 0:
            raise HTTPException(422, "Preço não pode ser negativo.")
        return n

    data: dict = {}
    for f in ("name", "short", "description", "deadline"):
        if f in body:
            val = str(body[f]).strip()[:400]
            if f == "name" and not val:
                raise HTTPException(422, "O serviço precisa de um nome.")
            data[f] = val
    if "price_min" in body or "price_max" in body:
        lo, hi = price(body.get("price_min")), price(body.get("price_max"))
        if lo is not None and hi is not None and hi < lo:
            lo, hi = hi, lo
        data["price_min"], data["price_max"] = lo, hi
    if "active" in body or body.get("_form") == "1":
        data["active"] = str(body.get("active", "")).lower() in ("1", "true", "on", "sim", "yes")
    app_settings.save_service(db, key, data)
    db.commit()
    lead_service.refresh_all(db, ctx_of(db))  # serviço inativo some das recomendações
    svc = ctx_of(db).services[key]
    by_service = demand(db, include_mock(request))[1]
    return json_or_html(request, {"key": key, "name": svc.name, "active": svc.active, "price_min": svc.price_min,
                                  "price_max": svc.price_max, "price_text": svc.price_text},
                        "partials/service_card.html", {"s": svc, "by_service": by_service, "saved": True},
                        trigger={"toast": "Serviço salvo", "leads-changed": True})


@router.get("/metricas")
def metrics_page(request: Request, db: Session = Depends(get_db)):
    ctx = ctx_of(db)
    data = metrics.compute(db, include_mock(request), services=ctx.services)
    if wants_json(request):
        out = {**data, "weeks": [{"label": w["label"], "count": w["count"]} for w in data["weeks"]]}
        return JSONResponse(out)
    return render(request, "metrics.html", {**data, "ctx": ctx}, db=db)
