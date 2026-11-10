"""Importa o banco do protótipo (v1/v2): python scripts/dev.py import-v1 <caminho do .db>.

Traz leads, eventos, notas manuais, "não contatar", amostras e rascunhos, mapeando as etapas
antigas para o funil novo. Abre o banco antigo só para leitura e não mexe nele.
Leads fictícios (mock-) vêm marcados como fictícios. Rodar duas vezes não duplica.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog
from ..models import V1_STATUS_MAP, Lead, LeadEvent, OutreachDraft, Site
from . import lead_service, normalize
from .app_settings import Ctx

# nichos do protótipo que mudaram de nome ou foram desmembrados
V1_NICHE_MAP = {"salao": "salao", "barbearia": "barbearia", "estetica": "estetica", "dentista": "dentista",
                "petshop": "petshop", "oficina": "oficina", "restaurante": "restaurante", "academia": "academia",
                "outro": "outro"}


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return None


def _json(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        cur = conn.execute(f"SELECT * FROM {table}")  # noqa: S608 - nome fixo no código
    except sqlite3.Error:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def import_v1(db: Session, ctx: Ctx, path: str | Path, previews_src: Path | None = None,
              previews_dst: Path | None = None, base_url: str = "http://localhost:8000") -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Banco não encontrado: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        leads = _rows(conn, "leads")
        events = _rows(conn, "lead_events")
        sites = _rows(conn, "sites")
        drafts = _rows(conn, "outreach_drafts")
        searches = {s["id"]: s for s in _rows(conn, "searches")}
    finally:
        conn.close()
    if not leads and not searches:
        raise ValueError("Esse arquivo não parece ser um banco do protótipo (sem a tabela leads).")

    cat = catalog.niches()
    stats = {"leads": 0, "skipped": 0, "events": 0, "sites": 0, "drafts": 0, "mock": 0, "do_not_contact": 0,
             "manual_scores": 0}
    id_map: dict[int, Lead] = {}
    for row in leads:
        place_id = row.get("place_id")
        if not place_id:
            continue
        if db.scalar(select(Lead.id).where(Lead.place_id == place_id)):
            stats["skipped"] += 1
            continue
        niche = V1_NICHE_MAP.get(row.get("niche") or "")
        if niche is None:  # banco antes do multi-nicho: descobre pelo texto da busca
            s = searches.get(row.get("search_id")) or {}
            niche = cat.resolve(s.get("niche") or row.get("niche") or "").key
        cats = _json(row.get("categories"), [])
        niche = cat.pick(niche, niche, [c for c in cats if not str(c).startswith("osm:")])
        provider = "mock" if place_id.startswith("mock-") else "osm" if place_id.startswith("osm-") else "google"
        old_status = row.get("status") or "ACHADO"
        lead = Lead(
            place_id=place_id, name=row.get("name") or "(sem nome)", niche=niche,
            address=row.get("address"), neighborhood=row.get("neighborhood"), city=row.get("city"),
            phone=normalize.format_phone(row.get("phone")), phone_type=normalize.phone_type(row.get("phone")),
            whatsapp=row.get("whatsapp"), website_url=normalize.safe_url(row.get("website_url")),
            maps_url=normalize.safe_url(row.get("maps_url")), rating=row.get("rating"),
            reviews_count=row.get("reviews_count") or 0, categories=cats, opening_hours=row.get("opening_hours"),
            photos_count=row.get("photos_count") or 0, business_status=row.get("business_status"),
            lat=row.get("lat"), lng=row.get("lng"), source_provider=provider, is_mock=provider == "mock",
            score_manual=row.get("score_manual") or None, status=V1_STATUS_MAP.get(old_status, "NOVO"),
            do_not_contact=bool(row.get("do_not_contact")), contacted_at=_dt(row.get("contacted_at")),
            fetched_at=_dt(row.get("fetched_at")) or lead_service.utcnow(),
            created_at=_dt(row.get("created_at")) or lead_service.utcnow(),
        )
        lead.stage_changed_at = _dt(row.get("updated_at")) or lead.created_at
        lead.last_touch_at = lead.contacted_at
        if lead.status in ("ABORDADO", "CONVERSA", "PROPOSTA"):
            from . import funnel

            nxt = funnel.after_status(lead.status, lead.stage_changed_at, ctx.cadence, 0)
            lead.next_action, lead.next_action_at = nxt.label, nxt.at
        lead_service.refresh(lead, ctx)
        db.add(lead)
        db.flush()
        id_map[row["id"]] = lead
        stats["leads"] += 1
        stats["mock"] += lead.is_mock
        stats["do_not_contact"] += lead.do_not_contact
        stats["manual_scores"] += bool(lead.score_manual)
        db.add(LeadEvent(lead_id=lead.id, type="import",
                         note=f"Importado do protótipo (etapa antiga: {old_status})."))

    for ev in events:
        lead = id_map.get(ev.get("lead_id"))
        if lead is None:
            continue
        db.add(LeadEvent(
            lead_id=lead.id, type=ev.get("type") or "status",
            from_status=V1_STATUS_MAP.get(ev.get("from_status") or "", None),
            to_status=V1_STATUS_MAP.get(ev.get("to_status") or "", None),
            note=ev.get("note"), created_at=_dt(ev.get("created_at")) or lead.created_at))
        stats["events"] += 1

    import shutil

    for s in sites:
        lead = id_map.get(s.get("lead_id"))
        slug = s.get("slug")
        if lead is None or not slug or db.scalar(select(Site.id).where(Site.slug == slug)):
            continue
        db.add(Site(lead_id=lead.id, template="landing", slug=slug,
                    preview_url=f"{base_url.rstrip('/')}/previews/{slug}/", status=s.get("status") or "preview",
                    created_at=_dt(s.get("created_at")) or lead.created_at))
        stats["sites"] += 1
        if previews_src and previews_dst and (previews_src / slug).is_dir() and not (previews_dst / slug).exists():
            shutil.copytree(previews_src / slug, previews_dst / slug)

    for d in drafts:
        lead = id_map.get(d.get("lead_id"))
        if lead is None or not d.get("text"):
            continue
        db.add(OutreachDraft(lead_id=lead.id, channel=d.get("channel") or "whatsapp", kind="primeira",
                             text=d["text"], approved=bool(d.get("approved")), sent_at=_dt(d.get("sent_at")),
                             created_at=_dt(d.get("created_at")) or lead.created_at))
        stats["drafts"] += 1
    db.commit()
    return stats
