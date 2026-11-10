"""Proposta e diagnóstico: páginas HTML imprimíveis (o navegador salva como PDF)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import LeadEvent, Proposal
from ..services import lead_service, proposal, recommend, timeutil
from ..web import ctx_of, lead_or_404, read_body, render, wants_json

router = APIRouter()


def _num(v):
    if v in (None, ""):
        return None
    try:
        s = str(v).replace("R$", "").strip()
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        return max(0.0, float(s))
    except ValueError:
        return None


@router.get("/leads/{lead_id}/proposta")
def proposal_page(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    if lead.do_not_contact:
        raise HTTPException(409, "Lead marcado como não contatar.")
    ctx = ctx_of(db)
    ins = lead_service.insight(lead, ctx)
    saved = lead.proposals[0] if lead.proposals else None
    prices = {i["key"]: i["price"] for i in (saved.items if saved else []) if i.get("price") is not None}
    for key, value in request.query_params.items():  # ?preco_landing=1500 para simular
        if key.startswith("preco_") and _num(value) is not None:
            prices[key[6:]] = _num(value)
    # proposta salva mostra só os serviços que o Samuel deixou nela
    pkg = recommend.package_from_services([i["key"] for i in saved.items], ctx.services) if saved and saved.items else ins.package
    items = proposal.build_items(pkg, ctx.services, prices)
    total, monthly = proposal.totals(items)
    created = saved.created_at if saved else timeutil.utcnow()
    days = saved.validity_days if saved else ctx.proposal_validity
    site = lead.latest_site
    data = {"lead_id": lead.id, "items": items, "total": total, "monthly": monthly, "validity_days": days,
            "valid_until": proposal.valid_until(created, days).isoformat(), "saved": bool(saved)}
    if wants_json(request):
        return JSONResponse(data)
    return render(request, "proposal.html", {
        "lead": lead, "ins": ins, "items": items, "total": total, "monthly": monthly, "created": created,
        "valid_until": proposal.valid_until(created, days), "days": days, "site": site, "ctx": ctx,
        "saved": saved, "notes": saved.notes if saved else "", "preview": f"/previews/{site.slug}/" if site else None,
        "sample_url": get_settings().preview_url(site.slug) if site else None})


@router.post("/leads/{lead_id}/proposta")
async def save_proposal(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """Guarda a proposta com os valores fechados. Não muda a etapa: quem marca "Proposta enviada" é o Samuel."""
    lead = lead_or_404(db, lead_id)
    if lead.do_not_contact:
        raise HTTPException(409, "Lead marcado como não contatar.")
    body = await read_body(request)
    ctx = ctx_of(db)
    ins = lead_service.insight(lead, ctx)
    keys = [k[6:] for k in body if k.startswith("preco_")]
    pkg = ins.package if not keys else recommend.package_from_services(
        [r.key for r in ins.package.items if r.key in keys] or keys, ctx.services)
    prices = {k[6:]: _num(v) for k, v in body.items() if k.startswith("preco_") and _num(v) is not None}
    items = proposal.build_items(pkg, ctx.services, prices)
    total, monthly = proposal.totals(items)
    try:
        days = max(1, min(90, int(body.get("validity_days") or ctx.proposal_validity)))
    except ValueError:
        days = ctx.proposal_validity
    p = Proposal(lead_id=lead.id, items=items, total=total, monthly=monthly, validity_days=days,
                 notes=(body.get("notes") or "").strip()[:2000] or None)
    db.add(p)
    if total is not None:
        lead.proposal_value = total
    if monthly is not None:
        lead.recurring_value = monthly
    db.add(LeadEvent(lead_id=lead.id, type="proposta", note="Proposta montada" + (
        f": {proposal.catalog.brl(total)}" if total is not None else "") + "."))
    db.commit()
    data = {"id": p.id, "lead_id": lead.id, "total": total, "monthly": monthly, "validity_days": days}
    if wants_json(request):
        return JSONResponse(data, status_code=201)
    from fastapi.responses import RedirectResponse

    return RedirectResponse(f"/leads/{lead.id}/proposta", status_code=303)


@router.get("/leads/{lead_id}/diagnostico")
def diagnosis_page(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """Diagnóstico de uma página, pronto para salvar em PDF e mandar junto com a amostra."""
    lead = lead_or_404(db, lead_id)
    if lead.do_not_contact:
        raise HTTPException(409, "Lead marcado como não contatar.")
    ctx = ctx_of(db)
    ins = lead_service.insight(lead, ctx)
    problems = proposal.plain_problems(ins.diag)
    if wants_json(request):
        return JSONResponse({"lead_id": lead.id, "problems": problems, "dims": ins.diag.dims,
                             "services": [r.name for r in ins.recs[:4]], "pagespeed": lead.pagespeed_score})
    site = lead.latest_site
    s = get_settings()
    return render(request, "diagnosis.html", {"lead": lead, "ins": ins, "problems": problems, "ctx": ctx,
                                              "site": site, "sample_url": s.preview_url(site.slug) if site else None,
                                              "now": timeutil.utcnow()})
