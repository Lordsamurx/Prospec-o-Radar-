"""Rascunhos de abordagem. Não existe rota de envio: o Samuel copia e envia; a app só registra
"Marquei como enviado"."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import catalog
from ..config import get_settings
from ..db import get_db
from ..models import LeadEvent, OutreachDraft
from ..services import ai, lead_service, normalize, outreach_text
from ..web import ctx_of, json_or_html, lead_or_404, read_body, render, wants_json

router = APIRouter()


@router.post("/leads/{lead_id}/outreach")
async def create_draft(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    if lead.do_not_contact:
        raise HTTPException(409, "Lead marcado como não contatar.")
    body = await read_body(request)
    channel = body.get("channel") or "whatsapp"
    kind = body.get("kind") or "primeira"
    if channel not in outreach_text.CHANNELS or kind not in outreach_text.KINDS:
        raise HTTPException(422, "Canal ou tipo de mensagem inválido.")
    settings = get_settings()
    ctx = ctx_of(db)
    ins = lead_service.insight(lead, ctx)
    site = lead.latest_site
    url = settings.preview_url(site.slug) if site else None
    text = outreach_text.draft(lead, ins.diag, ins.recs, ctx.seller, url, channel, kind)
    provider = None
    if str(body.get("ai", "")).lower() in ("1", "true", "on"):
        facts = {"nome": lead.name, "nicho": catalog.niches().label(lead.niche), "bairro": lead.neighborhood,
                 "nota_google": lead.rating, "avaliacoes": lead.reviews_count, "site": ins.diag.signal("site").value,
                 "servicos_sugeridos": [r.name for r in ins.recs[:3]]}
        text, provider = ai.rewrite(text, facts, ctx.seller, outreach_text.CHANNELS[channel],
                                    ai.config_from(settings, ctx.ai_enabled))
    d = OutreachDraft(lead_id=lead.id, channel=channel, kind=kind, text=text, by_ai=bool(provider))
    db.add(d)
    db.add(LeadEvent(lead_id=lead.id, type="abordagem",
                     note=f"Rascunho criado ({outreach_text.KINDS[kind]}, {outreach_text.CHANNELS[channel]}). Não enviado."))
    db.commit()
    wa = normalize.whatsapp_link(lead.phone, text) if channel == "whatsapp" else None
    ai_failed = str(body.get("ai", "")).lower() in ("1", "true", "on") and not provider
    return json_or_html(
        request,
        {"id": d.id, "lead_id": lead.id, "channel": channel, "kind": kind, "text": text, "sent_at": None,
         "whatsapp_url": wa, "by_ai": provider, "link_is_local": bool(url) and settings.preview_link_is_local},
        "partials/outreach.html",
        {"lead": lead, "draft": d, "wa": wa, "has_site": bool(site), "channel": channel, "kind": kind,
         "provider": provider, "ai_failed": ai_failed, "local": bool(url) and settings.preview_link_is_local,
         "ai_on": ai.config_from(settings, ctx.ai_enabled).available})


@router.post("/outreach/{draft_id}/sent")
def mark_draft_sent(draft_id: int, request: Request, db: Session = Depends(get_db)):
    """"Marquei como enviado": o Samuel já enviou por conta própria; aqui só fica o registro."""
    d = db.get(OutreachDraft, draft_id)
    if not d:
        raise HTTPException(404, "Rascunho não encontrado.")
    lead = d.lead
    try:
        lead_service.mark_sent(db, lead, ctx_of(db), d.kind, d.channel, d)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from None
    payload = {"id": d.id, "lead_id": lead.id, "sent_at": d.sent_at.isoformat(), "status": lead.status,
               "next_action": lead.next_action,
               "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None}
    if wants_json(request):
        return JSONResponse(payload)
    from .leads import drawer

    return drawer(request, db, lead, "Registrado como enviado")


@router.post("/leads/{lead_id}/sent")
async def mark_sent(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """Usado na Sessão: registra o envio sem precisar de um rascunho salvo."""
    lead = lead_or_404(db, lead_id)
    body = await read_body(request)
    kind = body.get("kind") or "primeira"
    channel = body.get("channel") or "whatsapp"
    if channel not in outreach_text.CHANNELS or kind not in outreach_text.KINDS:
        raise HTTPException(422, "Canal ou tipo de mensagem inválido.")
    try:
        lead_service.mark_sent(db, lead, ctx_of(db), kind, channel)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from None
    payload = {"lead_id": lead.id, "status": lead.status, "next_action": lead.next_action,
               "next_action_at": lead.next_action_at.isoformat() if lead.next_action_at else None}
    if wants_json(request):
        return JSONResponse(payload)
    from .leads import drawer

    return drawer(request, db, lead, "Registrado como enviado")


__all__ = ["router", "render"]
