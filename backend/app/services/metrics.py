"""Métricas do funil (seção 4.7): conversão entre etapas, por nicho, setor e serviço; tempo médio
em cada etapa; receita fechada no mês; receita recorrente; abordagens por semana. Só leitura."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog
from ..models import STATUS_LABELS, WON, Lead, LeadEvent
from .timeutil import month_start, to_local, utcnow, week_start

# caminho principal do funil; cada etapa lateral conta como ter chegado até um ponto dele
PATH = ["NOVO", "ANALISADO", "AMOSTRA", "ABORDADO", "CONVERSA", "PROPOSTA", "FECHADO"]
RANK = {s: i for i, s in enumerate(PATH)}
RANK.update({"FOLLOWUP": RANK["ABORDADO"], "SEM_RESPOSTA": RANK["ABORDADO"], "PRODUCAO": RANK["FECHADO"],
             "ENTREGUE": RANK["FECHADO"]})


def reached_rank(lead: Lead, events: list[LeadEvent]) -> int:
    """Etapa mais avançada do caminho principal em que o lead já esteve."""
    ranks = [RANK.get(lead.status, -1)]
    ranks += [RANK.get(e.to_status or "", -1) for e in events if e.type in ("status", "import")]
    ranks += [RANK.get(e.from_status or "", -1) for e in events if e.type == "status"]
    best = max(ranks)
    if best < RANK["ABORDADO"] and lead.contacted_at:
        best = RANK["ABORDADO"]
    return max(best, 0)


def _conv(group: dict[str, list[int]]) -> list[dict]:
    rows = []
    for key, ranks in group.items():
        n = len(ranks)
        approached = sum(r >= RANK["ABORDADO"] for r in ranks)
        talked = sum(r >= RANK["CONVERSA"] for r in ranks)
        won = sum(r >= RANK["FECHADO"] for r in ranks)
        rows.append({"key": key, "leads": n, "approached": approached, "talked": talked, "won": won,
                     "reply_rate": round(100 * talked / approached) if approached else None,
                     "win_rate": round(100 * won / approached) if approached else None})
    return sorted(rows, key=lambda r: (-r["won"], -r["approached"], -r["leads"]))


def compute(db: Session, include_mock: bool = False, now: datetime | None = None, services: dict | None = None) -> dict:
    now = now or utcnow()
    cat = catalog.niches()
    q = select(Lead).where(Lead.archived.is_(False), Lead.do_not_contact.is_(False))  # "não contatar" fica fora de tudo
    if not include_mock:
        q = q.where(Lead.is_mock.is_(False))
    leads = db.scalars(q).all()
    ids = [l.id for l in leads]
    events_by: dict[int, list[LeadEvent]] = defaultdict(list)
    if ids:
        for e in db.scalars(select(LeadEvent).where(LeadEvent.lead_id.in_(ids)).order_by(LeadEvent.created_at, LeadEvent.id)):
            events_by[e.lead_id].append(e)

    ranks = {l.id: reached_rank(l, events_by[l.id]) for l in leads}
    stage_counts = [sum(r >= i for r in ranks.values()) for i in range(len(PATH))]
    steps = []
    for i, s in enumerate(PATH):
        prev = stage_counts[i - 1] if i else None
        steps.append({"key": s, "label": STATUS_LABELS[s], "count": stage_counts[i],
                      "rate": round(100 * stage_counts[i] / prev) if prev else None})

    by_niche: dict[str, list[int]] = defaultdict(list)
    by_sector: dict[str, list[int]] = defaultdict(list)
    by_service: dict[str, list[int]] = defaultdict(list)
    for l in leads:
        by_niche[l.niche or "outro"].append(ranks[l.id])
        by_sector[l.sector or "outros"].append(ranks[l.id])
        keys = (l.sold_services or []) if l.status in WON else ([l.rec_main] if l.rec_main else [])
        for k in keys:
            by_service[k].append(ranks[l.id])
    niche_rows = [{**r, "label": cat.label(r["key"])} for r in _conv(by_niche)]
    sector_rows = [{**r, "label": cat.sector_by_key[r["key"]].label if r["key"] in cat.sector_by_key else r["key"],
                    "color": cat.sector_by_key[r["key"]].color if r["key"] in cat.sector_by_key else "#888"}
                   for r in _conv(by_sector)]
    service_rows = [{**r, "label": services[r["key"]].name if services and r["key"] in services else r["key"]}
                    for r in _conv(by_service)]

    # tempo médio em cada etapa (dias entre entrar e sair)
    durations: dict[str, list[float]] = defaultdict(list)
    for l in leads:
        prev_at, prev_status = None, None
        for e in events_by[l.id]:
            if e.type != "status" or not e.to_status:
                continue
            if prev_status and prev_at:
                durations[prev_status].append((e.created_at - prev_at).total_seconds() / 86400)
            prev_at, prev_status = e.created_at, e.to_status
    stage_time = [{"key": s, "label": STATUS_LABELS[s], "days": round(sum(v) / len(v), 1), "n": len(v)}
                  for s, v in ((s, durations.get(s, [])) for s in STATUS_LABELS) if v]

    m0 = month_start(now)
    won_month = [l for l in leads if l.status in WON and l.closed_at and l.closed_at >= m0]
    revenue_month = sum(l.proposal_value or 0 for l in won_month)
    recurring = sum(l.recurring_value or 0 for l in leads if l.status in WON)
    open_proposals = sum(l.proposal_value or 0 for l in leads if l.status == "PROPOSTA")

    # abordagens por semana (últimas 8, da mais antiga para a atual)
    w0 = week_start(now)
    weeks = [{"start": w0 - timedelta(weeks=i), "count": 0} for i in range(7, -1, -1)]
    for l in leads:
        for e in events_by[l.id]:
            if e.type == "enviado" and (e.note or "").startswith("Abordagem"):
                for w in weeks:
                    if w["start"] <= e.created_at < w["start"] + timedelta(weeks=1):
                        w["count"] += 1
    for w in weeks:
        w["label"] = to_local(w["start"]).strftime("%d/%m")

    lost = defaultdict(int)
    for l in leads:
        if l.status == "PERDIDO":
            lost[l.lost_reason or "outro"] += 1
    return {"total": len(leads), "steps": steps, "by_niche": niche_rows[:15], "by_sector": sector_rows,
            "by_service": service_rows, "stage_time": stage_time, "revenue_month": revenue_month,
            "won_month": len(won_month), "recurring": recurring, "open_proposals": open_proposals, "weeks": weeks,
            "lost": dict(lost)}
