"""Lista (lista ou mapa), drawer, etapa, nota, tags, checagens, ações em lote, LGPD e export CSV."""
import csv
import io
from datetime import datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog
from ..config import get_settings
from ..db import get_db
from ..models import LOST_REASONS, SCORES, STATUS_LABELS, STATUSES, Lead, Site
from ..schemas import FilterParams, LeadOut
from ..services import ai, filters, geo, lead_service, normalize, site_check, site_generator, timeutil
from ..services.providers import ProviderError
from ..web import (ctx_of, include_mock, is_htmx, json_or_html, lead_or_404, read_body, read_multi, render, toast,
                   wants_json)

router = APIRouter()
TRIGGER = {"leads-changed": True, "funnel-changed": True}
PAGE = 300


def _num(v, cast=float):
    """Número digitado à brasileira ("1.500,00") ou simples ("1500"). Vazio ou inválido: None."""
    if v in (None, ""):
        return None
    t = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return cast(float(t)) if cast is int else cast(t)
    except ValueError:
        return None


def parse_filters(request: Request) -> FilterParams:
    items = list(request.query_params.multi_items())
    f = FilterParams.from_query(items)
    if include_mock(request):
        f = f.model_copy(update={"show_mock": True})
    return f


def run_filters(db: Session, f: FilterParams, limit: int = PAGE) -> tuple[list[Lead], int]:
    settings = get_settings()
    ctx = ctx_of(db)
    center = None
    if f.radius_km and f.neighborhood and not geo.known(f.neighborhood):
        # bairro fora da tabela: usa a média das coordenadas dos leads dele
        lat, lng = db.execute(select(func.avg(Lead.lat), func.avg(Lead.lng)).where(
            func.lower(Lead.neighborhood) == f.neighborhood.strip().lower())).one()
        if lat is not None and lng is not None:
            center = (lat, lng)
    q = filters.build_query(f, ctx.franchises, (settings.default_center_lat, settings.default_center_lng),
                            center=center, stale_days=settings.google_stale_days)
    return list(db.scalars(q.limit(limit)).all()), int(db.scalar(filters.count_query(q)) or 0)


def _list_ctx(request: Request, db: Session, f: FilterParams) -> dict:
    settings = get_settings()
    ctx = ctx_of(db)
    leads, total = run_filters(db, f)
    mock = f.show_mock
    counts = lead_service.niche_counts(db, mock)
    cat = catalog.niches()
    groups = []
    for sector, niches in cat.by_sector():
        rows = [(n, counts.get(n.key, 0)) for n in niches if counts.get(n.key, 0) or n.key in f.niche]
        if rows:
            groups.append((sector, rows, sum(c for _, c in rows)))
    base = [(k, v) for k, v in f.to_query() if not (k == "show_mock" and settings.places_provider.lower() == "mock")]
    tags = sorted({t for (row,) in db.execute(select(Lead.tags).where(Lead.tags != "")) for t in row.split(",") if t})
    view = request.query_params.get("view", "lista")
    now = timeutil.utcnow()
    return {
        "leads": leads, "total": total, "shown": len(leads), "f": f, "ctx": ctx, "now": now,
        "all_count": sum(counts.values()), "chips": [c for c in filters.chips(f, ctx.services)
                                                     if not (c["key"] == "show_mock" and settings.places_provider.lower() == "mock")],
        "niche_groups": groups, "services": ctx.services, "tags": tags, "view": view if view in ("lista", "mapa") else "lista",
        "qs": urlencode(base), "more_count": sum(1 for k, _ in base if k not in (*filters.BAR_KEYS, "sort")),
        "neighborhoods": db.scalars(select(Lead.neighborhood).where(Lead.neighborhood.is_not(None)).distinct()
                                    .order_by(Lead.neighborhood)).all(),
        "cities": db.scalars(select(Lead.city).where(Lead.city.is_not(None)).distinct().order_by(Lead.city)).all(),
        "stale_ids": {l.id for l in leads if lead_service.is_stale(l, settings, now)},
        "center": (settings.default_center_lat, settings.default_center_lng),
        "map_points": [{"id": l.id, "name": l.name, "lat": l.lat, "lng": l.lng, "score": l.score or "",
                        "sub": " · ".join(x for x in (cat.label(l.niche), l.neighborhood) if x)}
                       for l in leads if l.lat is not None and l.lng is not None] if view == "mapa" else [],
    }


CSV_FIELDS = ["name", "niche", "sector", "neighborhood", "city", "address", "phone", "phone_type", "website_url",
              "site_status", "site_platform", "maps_url", "rating", "reviews_count", "photos_count",
              "business_status", "score", "score_reason", "profile", "opportunity", "rec_main", "status",
              "next_action", "next_action_at", "proposal_value", "lost_reason", "tags", "notes", "source_provider",
              "fetched_at", "is_mock"]


def csv_response(leads, filename: str = "leads.csv") -> Response:
    """Separador ; e BOM para abrir certo no Excel. Células nunca viram fórmula."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(CSV_FIELDS)
    for lead in leads:
        row = []
        for k in CSV_FIELDS:
            v = getattr(lead, k)
            if k == "tags":
                v = ", ".join(lead.tag_list)
            elif isinstance(v, datetime):
                v = timeutil.fmt(v)
            row.append(normalize.csv_cell(v))
        w.writerow(row)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/leads")
def list_leads(request: Request, db: Session = Depends(get_db)):
    f = parse_filters(request)
    fmt = request.query_params.get("format")
    if fmt == "csv":
        leads, _ = run_filters(db, f, limit=100000)
        return csv_response(leads)
    if wants_json(request):
        leads, total = run_filters(db, f, limit=int(_num(request.query_params.get("limit"), int) or PAGE))
        return JSONResponse({"total": total, "filters": f.model_dump(),
                             "leads": [LeadOut.model_validate(l).model_dump(mode="json") for l in leads]})
    ctx = _list_ctx(request, db, f)
    if is_htmx(request) and request.headers.get("hx-target") == "results":
        return render(request, "partials/lead_list.html", ctx, db=db)
    return render(request, "leads.html", ctx, db=db)


@router.get("/export.csv")
def export_all(db: Session = Depends(get_db)):
    """Export completo: tudo, inclusive arquivados e fictícios (menos 'não contatar')."""
    leads = db.scalars(select(Lead).where(Lead.do_not_contact.is_(False)).order_by(Lead.id)).all()
    return csv_response(leads, f"radar-leads-{timeutil.to_local(timeutil.utcnow()):%Y%m%d}.csv")


@router.get("/api/command")
def command(request: Request, db: Session = Depends(get_db)):
    """Paleta de comandos (Ctrl+K): procura leads pelo nome."""
    q = (request.query_params.get("q") or "").strip().lower()
    if len(q) < 2:
        return JSONResponse({"leads": []})
    conds = [Lead.do_not_contact.is_(False), Lead.archived.is_(False), func.lower(Lead.name).like(f"%{q}%")]
    if not include_mock(request):
        conds.append(Lead.is_mock.is_(False))
    rows = db.scalars(select(Lead).where(*conds).order_by(filters.SCORE_ORDER, Lead.opportunity.desc()).limit(8)).all()
    cat = catalog.niches()
    return JSONResponse({"leads": [{"id": l.id, "name": l.name, "sub": " · ".join(
        x for x in (cat.label(l.niche), l.neighborhood, f"nota {l.score}" if l.score else None) if x)} for l in rows]})


def _drawer_ctx(db: Session, lead: Lead, extra: dict | None = None) -> dict:
    settings = get_settings()
    ctx = ctx_of(db)
    ins = lead_service.insight(lead, ctx)
    return {"lead": lead, "ins": ins, "ctx": ctx, "services": ctx.services, "now": timeutil.utcnow(),
            "stale": lead_service.is_stale(lead, settings), "ai_on": ai.config_from(settings, ctx.ai_enabled).available,
            "sample_template": site_generator.template_for(lead, ctx.services), **(extra or {})}


def _lead_json(db: Session, lead: Lead) -> dict:
    ins = lead_service.insight(lead, ctx_of(db))
    data = LeadOut.model_validate(lead).model_dump(mode="json")
    data.update(
        tags=lead.tag_list, notes=lead.notes, offered=lead.offered or [], gmb_check=lead.gmb_check,
        site_check=lead.site_check, profile_reason=ins.profile_reason, diagnosis=ins.diag.to_dict(),
        opportunity_parts=[p.__dict__ for p in ins.parcels],
        recommendations=[r.__dict__ for r in ins.recs],
        package={"items": [r.key for r in ins.package.items], "total_text": ins.package.total_text},
        strategy={"scenario": ins.strategy.scenario, "title": ins.strategy.title, "angle": ins.strategy.angle,
                  "hooks": list(ins.strategy.hooks), "objections": [list(o) for o in ins.strategy.objections],
                  "next_step": ins.strategy.next_step},
        events=[{"type": e.type, "from": e.from_status, "to": e.to_status, "note": e.note,
                 "at": e.created_at.isoformat()} for e in lead.events],
    )
    return data


def drawer(request: Request, db: Session, lead: Lead, message: str | None = None, extra: dict | None = None,
           trigger: dict | None = None, data: dict | None = None):
    db.refresh(lead)
    trig = {**TRIGGER, **(toast(message) if message else {}), **(trigger or {})}
    if wants_json(request):
        return JSONResponse(data if data is not None else _lead_json(db, lead))
    if request.query_params.get("view") == "kanban":
        return render(request, "partials/kanban_card.html", {"lead": lead, "now": timeutil.utcnow(), "ctx": ctx_of(db)},
                      trigger=trig)
    if request.query_params.get("view") == "none":
        return Response(status_code=204, headers={"HX-Trigger": __import__("json").dumps(trig)})
    return render(request, "partials/drawer.html", _drawer_ctx(db, lead, extra), trigger=trig)


@router.get("/leads/{lead_id}")
def lead_detail(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    if wants_json(request):
        return JSONResponse(_lead_json(db, lead))
    if not is_htmx(request):  # link direto: abre a lista com o drawer deste lead
        return render(request, "leads.html", {**_list_ctx(request, db, parse_filters(request)), "open_lead": lead.id}, db=db)
    return render(request, "partials/drawer.html", _drawer_ctx(db, lead))


@router.patch("/leads/{lead_id}/status")
async def patch_status(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    status = str(body.get("status", "")).upper()
    if status not in STATUSES:
        raise HTTPException(422, f"Etapa inválida. Use uma de: {', '.join(STATUSES)}")
    sold = await read_multi(request, "sold") if "sold" in body else None
    try:
        lead_service.change_status(db, lead, status, ctx_of(db), (body.get("note") or None),
                                   lost_reason=body.get("lost_reason") or None, value=_num(body.get("value")),
                                   sold=sold, recurring=_num(body.get("recurring")))
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from None
    return drawer(request, db, lead, f"Etapa: {lead.status_label}",
                  data={"id": lead.id, "status": lead.status, "next_action": lead.next_action,
                        "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None,
                        "lost_reason": lead.lost_reason})


@router.patch("/leads/{lead_id}/score")
async def patch_score(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    value = str(body.get("score", "")).strip()
    value = "auto" if value.lower() == "auto" else value.upper()
    if value not in SCORES and value != "auto":
        raise HTTPException(422, "Nota inválida. Use A, B, C, DESCARTE ou auto.")
    lead_service.set_manual_score(db, lead, value, ctx_of(db), body.get("note") or None)
    return drawer(request, db, lead, f"Nota {lead.score}",
                  data={"id": lead.id, "score": lead.score, "score_reason": lead.score_reason,
                        "score_auto": lead.score_auto, "manual": bool(lead.score_manual)})


@router.post("/leads/{lead_id}/dnc")
async def do_not_contact(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    lead_service.mark_do_not_contact(db, lead, ctx_of(db), body.get("note") or None)
    if wants_json(request):
        return JSONResponse({"id": lead.id, "do_not_contact": True, "status": lead.status})
    import json

    return Response(status_code=200, headers={"HX-Trigger": json.dumps(
        {**TRIGGER, "drawer-close": True, "toast": "Marcado como não contatar"})})


@router.post("/leads/{lead_id}/delete")
async def delete_lead(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """LGPD: exclui de vez. Fica só um registro sem os dados."""
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    if str(body.get("confirm", "")).lower() not in ("1", "true", "sim", "on", "excluir"):
        raise HTTPException(422, "Confirme a exclusão.")
    lead_service.delete_forever(db, lead, body.get("reason") or None, get_settings().previews_path)
    if wants_json(request):
        return JSONResponse({"deleted": lead_id})
    import json

    return Response(status_code=200, headers={"HX-Trigger": json.dumps(
        {**TRIGGER, "drawer-close": True, "toast": "Lead excluído de vez"})})


@router.post("/leads/{lead_id}/tags")
async def set_tags(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    tags = await read_multi(request, "tags")
    if body.get("remove"):
        tags = [t for t in lead.tag_list if t != normalize.clean_tag(body["remove"])]
    elif body.get("add"):
        tags = [*lead.tag_list, *str(body["add"]).split(",")]
    lead_service.set_tags(db, lead, tags)
    return drawer(request, db, lead, data={"id": lead.id, "tags": lead.tag_list})


@router.post("/leads/{lead_id}/notes")
async def set_notes(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    lead.notes = (body.get("notes") or "").strip()[:4000] or None
    db.commit()
    return drawer(request, db, lead, "Observações salvas", data={"id": lead.id, "notes": lead.notes})


@router.post("/leads/{lead_id}/offered")
async def set_offered(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    lead_service.set_offered(db, lead, await read_multi(request, "services"), ctx_of(db))
    return drawer(request, db, lead, "Serviços a oferecer atualizados", data={"id": lead.id, "offered": lead.offered})


@router.post("/leads/{lead_id}/gmb-check")
async def gmb_check(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    lead_service.save_gmb_check(db, lead, ctx_of(db), await read_body(request))
    return drawer(request, db, lead, "Checagem salva", data={"id": lead.id, "gmb_check": lead.gmb_check,
                                                             "score": lead.score, "profile": lead.profile})


@router.post("/leads/{lead_id}/next-action")
async def next_action(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    at = None
    if body.get("date"):
        try:
            at = timeutil.from_local(datetime.strptime(str(body["date"])[:10], "%Y-%m-%d").replace(hour=9))
        except ValueError:
            raise HTTPException(422, "Data inválida.") from None
    lead_service.set_next_action(db, lead, body.get("label"), at)
    return drawer(request, db, lead, "Próxima ação salva",
                  data={"id": lead.id, "next_action": lead.next_action,
                        "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None})


@router.post("/leads/{lead_id}/site-check")
def check_site(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """Uma visita ao site que o próprio negócio publicou. Com a análise ligada, lê a página inicial."""
    lead = lead_or_404(db, lead_id)
    ctx = ctx_of(db)
    if lead.site_status != "own" or not lead.website_url:
        raise HTTPException(409, "Este lead não tem site próprio para checar.")
    force = request.query_params.get("force") == "1"
    if lead.site_check and lead.site_check.get("checked") and not force:
        return drawer(request, db, lead, "Site já checado (uma visita por lead)")
    settings = get_settings()
    result = site_check.check_site(lead.website_url, None, analyze=ctx.site_analysis,
                                   extra_platforms=ctx.extra_platforms)
    result["at"] = timeutil.utcnow().isoformat(timespec="seconds")
    lead.site_check = result
    if ctx.site_analysis and result.get("analyzed") and request.query_params.get("pagespeed") == "1":
        lead.pagespeed_score = site_check.pagespeed(lead.website_url, settings.pagespeed_api_key.get_secret_value(), None)
    lead_service.refresh(lead, ctx)
    from ..models import LeadEvent

    db.add(LeadEvent(lead_id=lead.id, type="checagem",
                     note="Site checado: " + (result.get("reason") or ("abriu normalmente." if not result.get("down") else "fora do ar."))))
    db.commit()
    return drawer(request, db, lead, "Site checado")


@router.post("/leads/{lead_id}/refresh")
def refresh_google(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    try:
        lead_service.refresh_from_google(db, get_settings(), ctx_of(db), lead)
    except ProviderError as exc:
        raise HTTPException(409, str(exc)) from None
    return drawer(request, db, lead, "Dados atualizados", trigger={"quota-changed": True})


@router.post("/leads/{lead_id}/conversation")
async def conversation(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """Analisar conversa (modo manual): o Samuel COLA o texto. Nada é lido do WhatsApp."""
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    text = (body.get("text") or "").strip()[:8000]
    ctx = ctx_of(db)
    facts = {"nome": lead.name, "nicho": catalog.niches().label(lead.niche), "bairro": lead.neighborhood,
             "etapa": lead.status_label}
    result = ai.analyze_conversation(text, facts, ctx.seller, ai.config_from(get_settings(), ctx.ai_enabled))
    if wants_json(request):
        return JSONResponse(result)
    return render(request, "partials/conversation.html", {"lead": lead, "r": result, "pasted": text})


@router.post("/leads/manual")
async def add_manual(request: Request, db: Session = Depends(get_db)):
    body = await read_body(request)
    try:
        lead = lead_service.add_manual_lead(db, ctx_of(db), body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if wants_json(request):
        return JSONResponse({"id": lead.id, "place_id": lead.place_id}, status_code=201)
    import json

    return Response(status_code=201, headers={"HX-Trigger": json.dumps(
        {**TRIGGER, "toast": "Lead adicionado", "open-lead": lead.id})})


@router.post("/leads/bulk")
async def bulk(request: Request, db: Session = Depends(get_db)):
    """Ações em lote na lista: mudar etapa, pôr tag, gerar amostras, exportar, arquivar, não contatar."""
    body = await read_body(request)
    ids = [int(i) for i in await read_multi(request, "ids") if str(i).isdigit()][:500]
    action = body.get("action") or ""
    if not ids:
        raise HTTPException(422, "Marque pelo menos um lead.")
    leads = db.scalars(select(Lead).where(Lead.id.in_(ids))).all()
    ctx = ctx_of(db)
    settings = get_settings()
    done = 0
    if action == "status":
        status = str(body.get("status", "")).upper()
        if status not in STATUSES:
            raise HTTPException(422, "Etapa inválida.")
        for lead in leads:
            if not lead.do_not_contact:
                lead_service.change_status(db, lead, status, ctx, "Mudança em lote.")
                done += 1
        msg = f"{done} lead(s) em {STATUS_LABELS[status]}"
    elif action == "tag":
        tag = normalize.clean_tag(body.get("tag") or "")
        if not tag:
            raise HTTPException(422, "Escreva a tag.")
        for lead in leads:
            lead_service.add_tag(db, lead, tag)
            done += 1
        msg = f"Tag '{tag}' em {done} lead(s)"
    elif action == "samples":
        for lead in leads:
            if lead.do_not_contact:
                continue
            tpl = site_generator.template_for(lead, ctx.services)
            slug, _ = site_generator.generate(lead, settings.templates_site_path, settings.previews_path, tpl)
            site = db.scalar(select(Site).where(Site.slug == slug))
            if site is None:
                db.add(Site(lead_id=lead.id, template=tpl, slug=slug, preview_url=settings.preview_url(slug)))
            else:
                site.template, site.preview_url = tpl, settings.preview_url(slug)
            lead_service.mark_site_generated(db, lead, slug, ctx, tpl)
            done += 1
        msg = f"{done} amostra(s) gerada(s)"
    elif action == "archive":
        for lead in leads:
            lead.archived = True
            done += 1
        db.commit()
        msg = f"{done} lead(s) arquivado(s)"
    elif action == "unarchive":
        for lead in leads:
            lead.archived = False
            done += 1
        db.commit()
        msg = f"{done} lead(s) de volta à lista"
    elif action == "dnc":
        for lead in leads:
            lead_service.mark_do_not_contact(db, lead, ctx, "Não contatar (em lote).")
            done += 1
        msg = f"{done} lead(s) marcados como não contatar"
    elif action == "csv":
        return csv_response([l for l in leads if not l.do_not_contact], "leads-selecionados.csv")
    else:
        raise HTTPException(422, "Ação desconhecida.")
    if wants_json(request):
        return JSONResponse({"action": action, "done": done})
    import json

    return Response(status_code=200, headers={"HX-Trigger": json.dumps({**TRIGGER, "toast": msg, "bulk-done": True})})


__all__ = ["router", "LOST_REASONS"]
