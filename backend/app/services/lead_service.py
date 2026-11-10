"""Operações sobre leads que mexem no banco: busca + upsert, classificação, funil, tags, LGPD."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog
from ..config import Settings
from ..models import (CONTACTED, LOST_REASONS, PRE_SAMPLE, STATUS_LABELS, STATUSES, WAITING_REPLY, WON, DeletionLog,
                      Lead, LeadEvent, Search, SearchJob)
from ..schemas import PlaceDTO
from . import funnel, normalize, opportunity, profile, quota, recommend, scoring, strategy
from .app_settings import Ctx
from .diagnose import Diagnostico, diagnose
from .providers import GooglePlacesProvider, PlacesProvider, ProviderError, QuotaExceeded, get_provider
from .timeutil import utcnow


# --------------------------------------------------------------------------- classificação
@dataclass
class Insight:
    """Tudo o que o drawer mostra sobre um lead, calculado na hora."""
    niche: catalog.Niche
    sector: catalog.Sector
    diag: Diagnostico
    score: str
    score_reason: str
    score_auto: str
    profile: str
    profile_reason: str
    opportunity: int
    parcels: list
    recs: list[recommend.Recomendacao]
    package: recommend.Pacote
    strategy: strategy.Estrategia


def insight(lead: Lead, ctx: Ctx) -> Insight:
    cat = catalog.niches()
    niche = cat.get_or_other(lead.niche)
    d = diagnose(lead, niche, ctx.franchises, ctx.limits_for(niche), ctx.extra_platforms)
    auto, auto_reason = scoring.auto_score(lead, ctx.franchises, d)
    final, reason = scoring.score(lead, ctx.franchises, d)
    prof, prof_reason = profile.profile(d)
    opp, parcels = opportunity.opportunity(d, bool(lead.do_not_contact))
    recs = recommend.recommend(lead, d, niche, ctx.services)
    chosen = [k for k in (lead.offered or []) if k in ctx.services]
    if chosen:
        extra = [k for k in chosen if k not in {r.key for r in recs}]
        pkg_recs = recs + list(recommend.package_from_services(extra, ctx.services).items)
        pkg = recommend.package(pkg_recs, chosen)
    else:
        pkg = recommend.package(recs)
    strat = strategy.strategy(lead, d, prof, niche, recs)
    return Insight(niche, cat.sector_by_key[niche.sector], d, final, reason, auto, prof, prof_reason, opp, parcels,
                   recs, pkg, strat)


def refresh(lead: Lead, ctx: Ctx) -> Insight:
    """Recalcula e grava no lead tudo o que é derivado (nota, perfil, oportunidade, recomendação)."""
    i = insight(lead, ctx)
    lead.sector = i.niche.sector
    lead.site_status = i.diag.site_status
    lead.site_kind = i.diag.site_kind
    lead.site_platform = i.diag.platform
    lead.score_auto = i.score_auto
    lead.score, lead.score_reason = i.score, i.score_reason
    lead.profile = i.profile
    lead.opportunity = i.opportunity
    lead.rec_main = i.recs[0].key if i.recs else None
    lead.rec_keys = "," + ",".join(r.key for r in i.recs) + "," if i.recs else ""
    return i


def refresh_all(db: Session, ctx: Ctx) -> int:
    """Depois de mudar franquias, limites, plataformas ou serviços: recalcula todo mundo."""
    n = 0
    for lead in db.scalars(select(Lead)).all():
        refresh(lead, ctx)
        n += 1
    db.commit()
    return n


# --------------------------------------------------------------------------- busca
def clean_text(text: str) -> str:
    return " ".join((text or "").split())


def place_hash(place_id: str) -> str:
    return hashlib.sha256(place_id.encode()).hexdigest()


def upsert_place(db: Session, dto: PlaceDTO, search_id: int | None, ctx: Ctx, niche_key: str = "outro",
                 provider: str = "osm") -> tuple[Lead | None, bool]:
    """Cria ou atualiza pelo place_id. Preserva o que é do Samuel: etapa, nota manual, não contatar,
    histórico, tags, observações e checagem manual. Lugar excluído a pedido (LGPD) não volta."""
    lead = db.scalar(select(Lead).where(Lead.place_id == dto.place_id))
    created = lead is None
    if created:
        if db.scalar(select(DeletionLog.id).where(DeletionLog.place_id_hash == place_hash(dto.place_id))):
            return None, False
        lead = Lead(place_id=dto.place_id, status="NOVO", search_id=search_id)
        db.add(lead)
    for key in ("name", "address", "neighborhood", "city", "rating", "reviews_count", "business_status",
                "opening_hours", "photos_count", "categories", "lat", "lng"):
        setattr(lead, key, getattr(dto, key))
    new_url = normalize.safe_url(dto.website_url)
    if new_url != lead.website_url:
        lead.site_check = None  # endereço mudou: a checagem antiga não vale mais
        lead.pagespeed_score = None
    lead.website_url = new_url
    lead.maps_url = normalize.safe_url(dto.maps_url)
    lead.phone = normalize.format_phone(dto.phone)
    lead.phone_type = normalize.phone_type(dto.phone)
    lead.niche = catalog.niches().pick(lead.niche, dto.niche_hint or niche_key,
                                       [c for c in dto.categories if not c.startswith("osm:")])
    lead.source_provider = provider
    lead.is_mock = dto.place_id.startswith("mock-")
    lead.fetched_at = utcnow()
    refresh(lead, ctx)
    db.flush()
    if created:
        db.add(LeadEvent(lead_id=lead.id, type="status", to_status="NOVO", created_at=lead.fetched_at,
                         note=f"Veio da busca ({PROVIDER_LABELS.get(provider, provider)})."))
        if lead.score in ("A", "B"):
            _move(db, lead, "ANALISADO", f"Automático: nota {lead.score}.", ctx)
    return lead, created


PROVIDER_LABELS = {"osm": "OpenStreetMap", "google": "Google Places", "mock": "dados fictícios",
                   "manual": "digitado", "import-v1": "importado do protótipo"}


def find_cached(db: Session, settings: Settings, niche: str, location: str, radius_m: int | None,
                center: tuple[float, float] | None) -> Search | None:
    """Mesma busca recente no Google não gasta requisição de novo (ignora maiúsculas e acentos)."""
    since = utcnow() - timedelta(days=settings.search_cache_days)
    recent = db.scalars(select(Search).where(
        Search.provider == "google", Search.created_at >= since, Search.results_count > 0,
        Search.cached_from_id.is_(None), Search.error.is_(None)).order_by(Search.created_at.desc())).all()
    fn, fl = normalize.fold(niche), normalize.fold(location)
    for s in recent:
        same_pin = (s.lat is None and center is None) or (
            center is not None and s.lat is not None and abs(s.lat - center[0]) < 1e-4 and abs(s.lng - center[1]) < 1e-4)
        if normalize.fold(s.niche) == fn and normalize.fold(s.location_text) == fl and s.radius_m == radius_m and same_pin:
            return s
    return None


def run_search(db: Session, settings: Settings, ctx: Ctx, niche: str, location: str, radius_m: int | None = None,
               center: tuple[float, float] | None = None, provider: PlacesProvider | None = None) -> dict:
    provider = provider or get_provider(settings, lambda: quota.requests_today(db, settings.places_provider))
    niche, location = clean_text(niche), clean_text(location)
    niche_key = catalog.niches().resolve(niche).key
    lat, lng = center if center else (None, None)
    base = dict(niche=niche, niche_key=niche_key, location_text=location, radius_m=radius_m, lat=lat, lng=lng,
                provider=provider.name)

    if provider.name == "google":
        cached = find_cached(db, settings, niche, location, radius_m, center)
        if cached:
            s = Search(**base, requests_made=0, results_count=cached.results_count, new_count=0,
                       cached_from_id=cached.id)
            db.add(s)
            db.commit()
            return {"search": s, "created": 0, "updated": 0, "total": cached.results_count, "cached": True,
                    "attribution": provider.attribution}

    try:
        places = provider.search(niche, location, radius_m, center)
    except Exception as exc:
        # Requisição cobrada que falhou no meio ainda conta para o limite do dia
        db.add(Search(**base, requests_made=provider.last_requests_made, results_count=0,
                      cost_estimate=round(provider.last_requests_made * provider.cost_per_request_usd, 3),
                      error=str(exc)[:300] if isinstance(exc, ProviderError) else type(exc).__name__))
        db.commit()
        raise
    search = Search(**base, requests_made=provider.last_requests_made, results_count=len(places),
                    cost_estimate=round(provider.last_requests_made * provider.cost_per_request_usd, 3))
    db.add(search)
    db.flush()
    created = kept = 0
    for dto in places:
        lead, is_new = upsert_place(db, dto, search.id, ctx, niche_key, provider.name)
        if lead is not None:
            kept += 1
            created += is_new
    search.new_count = created
    search.results_count = kept
    db.commit()
    return {"search": search, "created": created, "updated": kept - created, "total": kept, "cached": False,
            "attribution": provider.attribution}


def refresh_from_google(db: Session, settings: Settings, ctx: Ctx, lead: Lead,
                        provider: GooglePlacesProvider | None = None) -> Lead:
    """Atualiza um lead antigo pelo place_id (1 requisição, conta na cota)."""
    if lead.source_provider != "google":
        raise ProviderError("Só leads que vieram do Google podem ser atualizados pelo place_id.")
    if provider is None:
        p = get_provider(settings, lambda: quota.requests_today(db, "google"))
        if not isinstance(p, GooglePlacesProvider):
            raise ProviderError("Para atualizar, ligue o Google (PLACES_PROVIDER=google e chave no .env).")
        provider = p
    try:
        dto = provider.details(lead.place_id)
    finally:
        if provider.last_requests_made:
            db.add(Search(niche=f"atualizar: {lead.name}"[:120], niche_key=lead.niche, location_text="place_id",
                          provider="google", requests_made=provider.last_requests_made, results_count=1,
                          cost_estimate=round(provider.last_requests_made * provider.cost_per_request_usd, 3)))
            db.commit()
    dto.place_id = lead.place_id
    upsert_place(db, dto, lead.search_id, ctx, lead.niche or "outro", "google")
    db.add(LeadEvent(lead_id=lead.id, type="obs", note="Dados do Google atualizados pelo place_id."))
    db.commit()
    return lead


def is_stale(lead: Lead, settings: Settings, now: datetime | None = None) -> bool:
    """Dado do Google com mais de 30 dias: a tela marca como desatualizado."""
    return lead.source_provider == "google" and lead.fetched_at < (now or utcnow()) - timedelta(days=settings.google_stale_days)


# --------------------------------------------------------------------------- fila (busca em lote)
def enqueue(db: Session, items: list[dict]) -> int:
    """items: [{niche, location, radius_m?, lat?, lng?}]. Ignora o que já está pendente igual."""
    pending = {(normalize.fold(j.niche), normalize.fold(j.location_text), j.radius_m, j.lat, j.lng)
               for j in db.scalars(select(SearchJob).where(SearchJob.status == "pendente")).all()}
    n = 0
    for it in items:
        niche, loc = clean_text(it.get("niche", "")), clean_text(it.get("location", ""))
        key = (normalize.fold(niche), normalize.fold(loc), it.get("radius_m"), it.get("lat"), it.get("lng"))
        if len(niche) < 2 or key in pending:
            continue
        pending.add(key)
        db.add(SearchJob(niche=niche, location_text=loc, radius_m=it.get("radius_m"), lat=it.get("lat"),
                         lng=it.get("lng")))
        n += 1
    db.commit()
    return n


def parse_batch_lines(text: str, default_city: str = "") -> list[dict]:
    """'pizzaria em Savassi' por linha -> [{niche, location}]. Aceita ' em ', ' no ', ' na ', vírgula ou ' - '."""
    import re

    out = []
    for raw in (text or "").splitlines():
        line = clean_text(raw)
        if len(line) < 2:
            continue
        m = re.split(r"\s+(?:em|no|na|nos|nas)\s+|\s+-\s+|\s*;\s*", line, maxsplit=1, flags=re.I)
        if len(m) == 2 and m[0] and m[1]:
            niche, loc = m
        elif "," in line:
            niche, loc = (p.strip() for p in line.split(",", 1))
        else:
            niche, loc = line, default_city
        if default_city and normalize.fold(default_city) not in normalize.fold(loc) and loc:
            loc = f"{loc}, {default_city}"
        out.append({"niche": niche, "location": loc or default_city})
    return out


def process_queue(db: Session, settings: Settings, ctx: Ctx, max_jobs: int = 1,
                  provider: PlacesProvider | None = None) -> dict:
    """Roda até `max_jobs` buscas pendentes. Para quando a cota do dia acaba; o resto fica para amanhã."""
    done, errors, stopped = [], [], None
    for _ in range(max_jobs):
        job = db.scalar(select(SearchJob).where(SearchJob.status == "pendente").order_by(SearchJob.id))
        if job is None:
            break
        q = quota.status(db, settings)
        prov_name = provider.name if provider else q.provider
        if prov_name == "google" and q.blocked:
            stopped = f"Cota de hoje usada ({q.used_today} de {q.limit}). A fila continua amanhã."
            break
        center = (job.lat, job.lng) if job.lat is not None and job.lng is not None else None
        try:
            r = run_search(db, settings, ctx, job.niche, job.location_text, job.radius_m, center, provider)
            job.status, job.search_id, job.done_at = "feita", r["search"].id, utcnow()
            done.append({"job": job.id, "niche": job.niche, "location": job.location_text, "total": r["total"],
                         "created": r["created"]})
        except QuotaExceeded as exc:
            stopped = str(exc)
            db.commit()
            break
        except ProviderError as exc:
            job.status, job.error, job.done_at = "erro", str(exc)[:300], utcnow()
            errors.append({"job": job.id, "niche": job.niche, "location": job.location_text, "error": str(exc)})
        db.commit()
    pending = db.scalar(select(func.count()).select_from(SearchJob).where(SearchJob.status == "pendente")) or 0
    return {"done": done, "errors": errors, "stopped": stopped, "pending": int(pending)}


# --------------------------------------------------------------------------- funil
def _move(db: Session, lead: Lead, to_status: str, note: str | None, ctx: Ctx | None = None,
          now: datetime | None = None) -> LeadEvent:
    now = now or utcnow()
    ev = LeadEvent(lead_id=lead.id, type="status", from_status=lead.status, to_status=to_status, note=note,
                   created_at=now)
    lead.status = to_status
    lead.stage_changed_at = now
    if to_status in CONTACTED and lead.contacted_at is None:
        lead.contacted_at = now
    if to_status == "ABORDADO":
        lead.followup_step = 0
        lead.last_touch_at = now
    elif to_status in ("CONVERSA", "PROPOSTA"):
        lead.last_touch_at = now
    if to_status in WON and lead.closed_at is None:
        lead.closed_at = now
    if to_status != "PERDIDO":
        lead.lost_reason = None
    nxt = funnel.after_status(to_status, now, ctx.cadence if ctx else None, lead.followup_step or 0)
    lead.next_action, lead.next_action_at = nxt.label, nxt.at
    db.add(ev)
    return ev


def change_status(db: Session, lead: Lead, to_status: str, ctx: Ctx, note: str | None = None,
                  lost_reason: str | None = None, value: float | None = None,
                  sold: list[str] | None = None, recurring: float | None = None) -> LeadEvent | None:
    if to_status not in STATUSES:
        raise ValueError(f"Etapa inválida: {to_status}")
    if lead.do_not_contact and to_status != "DESCARTADO":
        raise PermissionError("Lead marcado como não contatar.")
    if value is not None:
        lead.proposal_value = value
    if recurring is not None:
        lead.recurring_value = recurring
    if sold is not None:
        lead.sold_services = [s for s in sold if s in ctx.services]
    if to_status == lead.status:
        if to_status == "PERDIDO" and lost_reason in LOST_REASONS:
            lead.lost_reason = lost_reason
        db.commit()
        return None
    if to_status == "PERDIDO":
        reason = lost_reason if lost_reason in LOST_REASONS else "outro"
        note = f"Motivo: {LOST_REASONS[reason]}." + (f" {note}" if note else "")
    ev = _move(db, lead, to_status, note, ctx)
    if to_status == "PERDIDO":
        lead.lost_reason = reason
    if to_status in WON and not lead.sold_services:
        lead.sold_services = list(lead.offered or ([lead.rec_main] if lead.rec_main else []))
    db.commit()
    return ev


def mark_sent(db: Session, lead: Lead, ctx: Ctx, kind: str = "primeira", channel: str = "whatsapp",
              draft=None, now: datetime | None = None) -> None:
    """"Marquei como enviado": grava evento e data. Quem enviou foi o Samuel; a app nunca envia."""
    if lead.do_not_contact:
        raise PermissionError("Lead marcado como não contatar.")
    now = now or utcnow()
    label = {"primeira": "Abordagem", "followup1": "Follow-up 1", "followup2": "Follow-up 2",
             "followup3": "Follow-up 3"}.get(kind, "Mensagem")
    db.add(LeadEvent(lead_id=lead.id, type="enviado", note=f"{label} marcada como enviada ({channel}).",
                     created_at=now))
    if draft is not None:
        draft.sent_at, draft.approved = now, True
    if kind == "primeira":
        if lead.status in ("NOVO", "ANALISADO", "AMOSTRA", "SEM_RESPOSTA"):
            _move(db, lead, "ABORDADO", "Abordagem enviada por você.", ctx, now)
        else:
            lead.last_touch_at = now
    else:
        lead.followup_step = (lead.followup_step or 0) + 1
        lead.last_touch_at = now
        if lead.status == "ABORDADO":
            _move(db, lead, "FOLLOWUP", f"{label} enviado por você.", ctx, now)
        elif lead.status == "FOLLOWUP":
            nxt = funnel.followup_plan(lead.followup_step, now, ctx.cadence)
            lead.next_action, lead.next_action_at = nxt.label, nxt.at
    db.commit()


def set_next_action(db: Session, lead: Lead, label: str | None, at: datetime | None) -> None:
    lead.next_action = (label or "").strip()[:200] or None
    lead.next_action_at = at
    db.add(LeadEvent(lead_id=lead.id, type="obs", note=f"Próxima ação: {lead.next_action or 'nenhuma'}."))
    db.commit()


def set_manual_score(db: Session, lead: Lead, value: str, ctx: Ctx, note: str | None = None) -> None:
    old = lead.score
    lead.score_manual = None if value == "auto" else value
    refresh(lead, ctx)
    db.add(LeadEvent(
        lead_id=lead.id, type="nota",
        note=f"Nota {old or '—'} → {lead.score}" + (" (volta à automática)" if value == "auto" else " (manual)")
        + (f". {note}" if note else "")))
    db.commit()


def mark_do_not_contact(db: Session, lead: Lead, ctx: Ctx, note: str | None = None) -> None:
    lead.do_not_contact = True
    if lead.status != "DESCARTADO":
        _move(db, lead, "DESCARTADO", note or "Não contatar.", ctx)
    lead.next_action, lead.next_action_at = None, None
    refresh(lead, ctx)
    db.commit()


def mark_site_generated(db: Session, lead: Lead, slug: str, ctx: Ctx, template: str) -> None:
    db.add(LeadEvent(lead_id=lead.id, type="site", note=f"Amostra gerada ({template}): {slug}"))
    if lead.status in PRE_SAMPLE:
        _move(db, lead, "AMOSTRA", "Amostra criada.", ctx)
    db.commit()


def save_gmb_check(db: Session, lead: Lead, ctx: Ctx, data: dict) -> None:
    """Mini formulário do drawer: o que o Samuel viu no Google Maps (leads do OSM)."""
    def num(v, cast):
        try:
            return cast(str(v).replace(",", ".")) if v not in (None, "") else None
        except ValueError:
            return None

    exists = str(data.get("exists", "yes")).lower() not in ("no", "nao", "não", "0", "false")
    rating = num(data.get("rating"), float)
    lead.gmb_check = {
        "checked": True, "exists": exists,
        "rating": min(5.0, max(0.0, rating)) if rating is not None and exists else None,
        "reviews": max(0, num(data.get("reviews"), int) or 0) if exists else 0,
        "photos": max(0, num(data.get("photos"), int) or 0) if exists else 0,
        "hours": bool(data.get("hours")) and exists,
        "at": utcnow().isoformat(timespec="seconds"),
    }
    phone = (data.get("phone") or "").strip()
    if phone and normalize.phone_digits(phone):
        lead.phone = normalize.format_phone(phone)
        lead.phone_type = normalize.phone_type(phone)
    site = (data.get("website_url") or "").strip()
    if site:
        lead.website_url = normalize.safe_url(site)
        lead.site_check = None
    refresh(lead, ctx)
    db.add(LeadEvent(lead_id=lead.id, type="checagem", note="Perfil conferido por você no Google Maps."
                     if exists else "Você conferiu: não aparece no Google Maps."))
    if lead.status == "NOVO" and lead.score in ("A", "B"):
        _move(db, lead, "ANALISADO", f"Conferido no Maps: nota {lead.score}.", ctx)
    db.commit()


def set_tags(db: Session, lead: Lead, tags: list[str]) -> None:
    clean = list(dict.fromkeys(t for t in (normalize.clean_tag(x) for x in tags) if t))[:12]
    lead.tags = "," + ",".join(clean) + "," if clean else ""
    db.commit()


def add_tag(db: Session, lead: Lead, tag: str) -> None:
    set_tags(db, lead, [*lead.tag_list, tag])


def set_offered(db: Session, lead: Lead, keys: list[str], ctx: Ctx) -> None:
    lead.offered = [k for k in dict.fromkeys(keys) if k in ctx.services and ctx.services[k].active]
    db.add(LeadEvent(lead_id=lead.id, type="obs",
                     note="Serviços a oferecer: " + (", ".join(ctx.services[k].name for k in lead.offered) or "nenhum") + "."))
    db.commit()


def delete_forever(db: Session, lead: Lead, reason: str | None, previews_root=None) -> None:
    """LGPD: exclui o lead de vez. Fica só um registro sem os dados (hash do place_id, para não reimportar)."""
    import shutil

    db.add(DeletionLog(place_id_hash=place_hash(lead.place_id), reason=(reason or "Pedido de exclusão.")[:200],
                       source_provider=lead.source_provider))
    if previews_root is not None:
        for site in lead.sites:
            target = (previews_root / site.slug).resolve()
            if previews_root.resolve() in target.parents and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
    db.delete(lead)
    db.commit()


def archive_mock(db: Session) -> int:
    rows = db.scalars(select(Lead).where(Lead.is_mock.is_(True), Lead.archived.is_(False))).all()
    for lead in rows:
        lead.archived = True
    db.commit()
    return len(rows)


def add_manual_lead(db: Session, ctx: Ctx, data: dict) -> Lead:
    """Lead digitado pelo Samuel (dados que ele mesmo viu)."""
    name = clean_text(data.get("name", ""))
    if len(name) < 2:
        raise ValueError("Informe o nome do negócio.")
    import uuid

    niche = catalog.niches().resolve(data.get("niche") or "").key
    dto = PlaceDTO(place_id=f"manual-{uuid.uuid4().hex[:12]}", name=name, neighborhood=clean_text(data.get("neighborhood", "")) or None,
                   city=clean_text(data.get("city", "")) or None, phone=data.get("phone") or None,
                   website_url=data.get("website_url") or None, business_status="OPERATIONAL",
                   maps_url="https://www.google.com/maps/search/?api=1&query=" + normalize.quote(name))
    lead, _ = upsert_place(db, dto, None, ctx, niche, "manual")
    db.commit()
    return lead  # type: ignore[return-value]


# --------------------------------------------------------------------------- contagens
def visible():
    """Condição padrão: nada de 'não contatar' nem arquivado."""
    return (Lead.do_not_contact.is_(False), Lead.archived.is_(False))


def niche_counts(db: Session, include_mock: bool = False) -> dict[str, int]:
    conds = list(visible())
    if not include_mock:
        conds.append(Lead.is_mock.is_(False))
    rows = db.execute(select(func.coalesce(Lead.niche, "outro"), func.count()).where(*conds)
                      .group_by(func.coalesce(Lead.niche, "outro"))).all()
    return {k: n for k, n in rows}


def funnel_counts(db: Session, include_mock: bool = False) -> dict[str, int]:
    conds = list(visible())
    if not include_mock:
        conds.append(Lead.is_mock.is_(False))
    rows = db.execute(select(Lead.status, func.count()).where(*conds).group_by(Lead.status)).all()
    counts = {s: 0 for s in STATUSES}
    counts.update({s: n for s, n in rows if s in counts})
    return counts


def has_real_leads(db: Session) -> bool:
    return bool(db.scalar(select(Lead.id).where(Lead.is_mock.is_(False)).limit(1)))


def mock_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Lead).where(Lead.is_mock.is_(True), Lead.archived.is_(False))) or 0)


__all__ = ["STATUS_LABELS"]
