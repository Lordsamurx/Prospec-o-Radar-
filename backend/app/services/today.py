"""Tela Hoje e fila da sessão de prospecção. Só leitura: nada aqui muda um lead."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Lead, LeadEvent
from . import funnel
from .app_settings import Ctx
from .filters import SCORE_ORDER
from .timeutil import day_end, utcnow, week_start


def _base(include_mock: bool):
    conds = [Lead.do_not_contact.is_(False), Lead.archived.is_(False)]
    if not include_mock:
        conds.append(Lead.is_mock.is_(False))
    return conds


def session_queue(db: Session, ctx: Ctx, include_mock: bool = False, now: datetime | None = None,
                  limit: int = 50) -> list[Lead]:
    """Ordem do modo foco: follow-ups vencidos primeiro (o mais atrasado na frente), depois quem
    ainda não foi abordado, do mais quente ao mais frio (nota, depois oportunidade)."""
    now = now or utcnow()
    base = _base(include_mock)
    due = db.scalars(select(Lead).where(
        *base, Lead.status.in_(["ABORDADO", "FOLLOWUP"]), Lead.next_action_at.is_not(None),
        Lead.next_action_at <= day_end(now), Lead.followup_step < len(ctx.cadence),
    ).order_by(Lead.next_action_at, Lead.id).limit(limit)).all()
    fresh = db.scalars(select(Lead).where(
        *base, Lead.status.in_(["NOVO", "ANALISADO", "AMOSTRA"]), Lead.score.in_(["A", "B"]),
        Lead.phone.is_not(None), Lead.phone != "",
    ).order_by(SCORE_ORDER, Lead.opportunity.desc(), Lead.id).limit(max(0, limit - len(due)))).all()
    return [*due, *fresh]


def week_approaches(db: Session, now: datetime | None = None, include_mock: bool = False) -> int:
    """Abordagens (primeira mensagem marcada como enviada) desde segunda-feira."""
    conds = [LeadEvent.type == "enviado", LeadEvent.note.like("Abordagem%"), LeadEvent.created_at >= week_start(now)]
    q = select(func.count()).select_from(LeadEvent).join(Lead, Lead.id == LeadEvent.lead_id).where(*conds)
    if not include_mock:
        q = q.where(Lead.is_mock.is_(False))
    return int(db.scalar(q) or 0)


def today(db: Session, ctx: Ctx, include_mock: bool = False, now: datetime | None = None) -> dict:
    now = now or utcnow()
    base = _base(include_mock)
    end = day_end(now)
    waiting = db.scalars(select(Lead).where(
        *base, Lead.status.in_(["ABORDADO", "FOLLOWUP"]), Lead.next_action_at.is_not(None), Lead.next_action_at <= end,
    ).order_by(Lead.next_action_at)).all()
    followups = [l for l in waiting if (l.followup_step or 0) < len(ctx.cadence)]
    no_reply = [l for l in waiting if funnel.suggest_no_reply(l.status, l.followup_step or 0, l.next_action_at, now, ctx.cadence)]
    approach = db.scalars(select(Lead).where(
        *base, Lead.status.in_(["ANALISADO", "AMOSTRA", "NOVO"]), Lead.score.in_(["A", "B"]),
        Lead.phone.is_not(None), Lead.phone != "",
    ).order_by((Lead.status == "AMOSTRA").desc(), SCORE_ORDER, Lead.opportunity.desc()).limit(6)).all()
    stale_cut = now - timedelta(days=funnel.STALE_TALK_DAYS)
    talks = db.scalars(select(Lead).where(
        *base, Lead.status == "CONVERSA", func.coalesce(Lead.last_touch_at, Lead.stage_changed_at) <= stale_cut,
    ).order_by(Lead.stage_changed_at)).all()
    proposals = db.scalars(select(Lead).where(
        *base, Lead.status == "PROPOSTA", Lead.stage_changed_at <= now - timedelta(days=funnel.STALE_PROPOSAL_DAYS),
    ).order_by(Lead.stage_changed_at)).all()
    production = db.scalars(select(Lead).where(*base, Lead.status.in_(["FECHADO", "PRODUCAO"]))
                            .order_by(Lead.stage_changed_at)).all()
    unchecked = int(db.scalar(select(func.count()).select_from(Lead).where(
        *base, Lead.source_provider == "osm", Lead.gmb_check.is_(None), Lead.status.in_(["NOVO", "ANALISADO"]))) or 0)
    done = week_approaches(db, now, include_mock)
    # o próximo passo mais importante, em uma frase
    if followups:
        step = ("followups", f"{len(followups)} follow-up(s) para hoje", "Começar pelos follow-ups")
    elif talks:
        step = ("talks", f"{len(talks)} conversa(s) parada(s) há mais de 3 dias", "Retomar as conversas")
    elif proposals:
        step = ("proposals", f"{len(proposals)} proposta(s) sem retorno", "Cobrar as propostas")
    elif approach:
        step = ("approach", f"{max(0, ctx.weekly_goal - done)} abordagem(ns) para bater a meta da semana"
                if done < ctx.weekly_goal else "Meta da semana batida. Quer adiantar mais uma?", "Abrir a sessão de prospecção")
    else:
        step = ("search", "Nenhum lead pronto para abordar", "Fazer uma busca nova")
    return {"followups": followups, "no_reply": no_reply, "approach": approach, "talks": talks,
            "proposals": proposals, "production": production, "unchecked": unchecked,
            "week_done": done, "week_goal": ctx.weekly_goal, "next_step": step, "now": now}
