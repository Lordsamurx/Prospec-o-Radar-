"""Gerar amostra de site e servir a prévia (sempre com noindex)."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Site
from ..services import lead_service, site_generator
from ..web import ctx_of, json_or_html, lead_or_404, read_body

router = APIRouter()
NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-cache"}


@router.post("/leads/{lead_id}/site")
async def create_site(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    if lead.do_not_contact:
        raise HTTPException(409, "Lead marcado como não contatar.")
    settings = get_settings()
    ctx = ctx_of(db)
    body = await read_body(request)
    template = body.get("template") or request.query_params.get("template") or site_generator.template_for(lead, ctx.services)
    if template not in site_generator.TEMPLATES:
        raise HTTPException(422, f"Modelo inválido. Use um de: {', '.join(site_generator.TEMPLATES)}")
    slug, _ = site_generator.generate(lead, settings.templates_site_path, settings.previews_path, template)
    url = settings.preview_url(slug)
    site = db.scalar(select(Site).where(Site.slug == slug))
    if site is None:
        site = Site(lead_id=lead.id, template=template, slug=slug, preview_url=url)
        db.add(site)
    else:
        site.preview_url, site.template = url, template
    lead_service.mark_site_generated(db, lead, slug, ctx, template)
    db.refresh(lead)
    trig = {"leads-changed": True, "funnel-changed": True, "toast": "Amostra gerada"}
    if request.query_params.get("view") == "none" and request.headers.get("hx-request") == "true":
        import json

        return Response(status_code=204, headers={"HX-Trigger": json.dumps(trig)})
    return json_or_html(
        request,
        {"lead_id": lead.id, "slug": slug, "template": template, "preview_url": url, "local_url": f"/previews/{slug}/",
         "path": f"data/previews/{slug}/index.html", "link_is_local": settings.preview_link_is_local},
        "partials/site_result.html", {"lead": lead, "site": site, "local": settings.preview_link_is_local},
        trigger={"leads-changed": True, "funnel-changed": True, "toast": "Amostra gerada"})


def _safe_file(slug: str, name: str) -> Path:
    root = get_settings().previews_path.resolve()
    path = (root / slug / name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Prévia não encontrada")
    return path


@router.get("/previews/{slug}", include_in_schema=False)
def preview_redirect(slug: str):
    return RedirectResponse(f"/previews/{slug}/", status_code=307)


@router.api_route("/previews/{slug}/", methods=["GET", "HEAD"])
def preview_index(slug: str):
    return FileResponse(_safe_file(slug, "index.html"), headers=NOINDEX)


@router.api_route("/previews/{slug}/{name}", methods=["GET", "HEAD"])
def preview_asset(slug: str, name: str):
    return FileResponse(_safe_file(slug, name), headers=NOINDEX)
