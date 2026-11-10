"""Tela Hoje (página inicial), Sessão de prospecção (modo foco) e Ajuda."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..services import backup, lead_service, normalize, outreach_text
from ..services import today as today_service
from ..web import ctx_of, include_mock, render, wants_json

router = APIRouter()


def _brief(lead) -> dict:
    return {"id": lead.id, "name": lead.name, "niche": lead.niche, "score": lead.score, "status": lead.status,
            "opportunity": lead.opportunity, "next_action": lead.next_action,
            "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None}


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    ctx = ctx_of(db)
    if s.auto_backup and s.database_path is not None and backup.auto_backup_due(s.backups_path):
        try:  # backup automático diário, feito na primeira visita do dia
            backup.backup_now(s.database_path, s.backups_path, "auto")
        except Exception:
            pass
    data = today_service.today(db, ctx, include_mock(request))
    if wants_json(request):
        return JSONResponse({
            **{k: [_brief(l) for l in data[k]] for k in ("followups", "no_reply", "approach", "talks", "proposals", "production")},
            "week_done": data["week_done"], "week_goal": data["week_goal"], "unchecked": data["unchecked"],
            "next_step": {"kind": data["next_step"][0], "text": data["next_step"][1], "cta": data["next_step"][2]},
        })
    counts = lead_service.funnel_counts(db, include_mock(request))
    return render(request, "today.html", {**data, "counts": counts, "total": sum(counts.values()),
                                          "has_real": lead_service.has_real_leads(db), "ctx": ctx}, db=db)


@router.get("/sessao")
def session(request: Request, db: Session = Depends(get_db)):
    """Modo foco: um lead por vez. `skip` guarda os que o Samuel pulou nesta sessão."""
    s = get_settings()
    ctx = ctx_of(db)
    skip = {int(x) for x in request.query_params.get("skip", "").split(",") if x.isdigit()}
    queue = [l for l in today_service.session_queue(db, ctx, include_mock(request)) if l.id not in skip]
    lead = queue[0] if queue else None
    if wants_json(request):
        return JSONResponse({"remaining": len(queue), "lead": _brief(lead) if lead else None,
                             "queue": [l.id for l in queue]})
    view = {"lead": lead, "remaining": len(queue), "skip": ",".join(str(x) for x in sorted(skip)), "ctx": ctx}
    if lead is not None:
        ins = lead_service.insight(lead, ctx)
        is_follow = lead.status in ("ABORDADO", "FOLLOWUP")
        kind = f"followup{min((lead.followup_step or 0) + 1, 3)}" if is_follow else "primeira"
        channel = "whatsapp" if lead.phone_type == "mobile" else "ligacao"
        site = lead.latest_site
        text = outreach_text.draft(lead, ins.diag, ins.recs, ctx.seller, s.preview_url(site.slug) if site else None,
                                   channel, kind)
        view.update(ins=ins, kind=kind, channel=channel, text=text, site=site,
                    wa=normalize.whatsapp_link(lead.phone, text) if channel == "whatsapp" else None)
    return render(request, "session.html", view, db=db)


@router.get("/ajuda")
def help_page(request: Request, db: Session = Depends(get_db)):
    if wants_json(request):
        return JSONResponse({"page": "ajuda"})
    return render(request, "help.html", {"ctx": ctx_of(db)}, db=db)
