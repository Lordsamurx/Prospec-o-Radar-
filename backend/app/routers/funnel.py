"""Funil: contagem por etapa e por nicho; kanban com colunas recolhíveis e valor por coluna."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import STATUSES, Lead
from ..services import filters, lead_service, timeutil
from ..web import ctx_of, include_mock, is_htmx, render, wants_json

router = APIRouter()
COLLAPSED_DEFAULT = {"NOVO", "ENTREGUE", "SEM_RESPOSTA", "PERDIDO", "DESCARTADO"}


@router.get("/funil")
def funnel(request: Request, db: Session = Depends(get_db)):
    mock = include_mock(request)
    counts = lead_service.funnel_counts(db, mock)
    niche_counts = lead_service.niche_counts(db, mock)
    cat = catalog.niches()
    by_niche = sorted(niche_counts.items(), key=lambda kv: (-kv[1], cat.label(kv[0])))
    conds = [Lead.do_not_contact.is_(False), Lead.archived.is_(False)]
    if not mock:
        conds.append(Lead.is_mock.is_(False))
    niche = request.query_params.get("niche")
    if niche:
        conds.append(Lead.niche == niche)
    leads = db.scalars(select(Lead).where(*conds).order_by(filters.SCORE_ORDER, Lead.opportunity.desc())).all()
    by_status: dict[str, list[Lead]] = {s: [] for s in STATUSES}
    for lead in leads:
        by_status.setdefault(lead.status, []).append(lead)
    values = {s: sum(l.proposal_value or 0 for l in rows) for s, rows in by_status.items()}
    if wants_json(request):
        return JSONResponse({"counts": counts, "total": sum(counts.values()), "by_niche": dict(by_niche),
                             "values": values})
    ctx = {"counts": counts, "by_status": by_status, "total": sum(counts.values()), "by_niche": by_niche[:12],
           "values": values, "collapsed_default": COLLAPSED_DEFAULT, "now": timeutil.utcnow(), "ctx": ctx_of(db),
           "niche": niche, "services": ctx_of(db).services}
    if is_htmx(request) and request.headers.get("hx-target") == "funnel-counts":
        return render(request, "partials/funnel_counts.html", ctx)
    if is_htmx(request) and request.headers.get("hx-target") == "kanban":
        return render(request, "partials/kanban.html", ctx)
    return render(request, "funnel.html", ctx, db=db)
