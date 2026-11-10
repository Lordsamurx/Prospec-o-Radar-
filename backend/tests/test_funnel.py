"""Cadência de follow-up, etapas, fila da sessão e tela Hoje."""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import Lead, LeadEvent
from app.services import funnel, lead_service, today
from app.services.timeutil import utcnow

T0 = datetime(2026, 11, 2, 12, 0)


def test_followup_cadence_3_5_7():
    assert funnel.followup_plan(0, T0).at == T0 + timedelta(days=3)
    assert funnel.followup_plan(1, T0).at == T0 + timedelta(days=5)
    assert funnel.followup_plan(2, T0).at == T0 + timedelta(days=7)
    assert funnel.followup_plan(0, T0).label == "Follow-up 1"


def test_after_last_followup_only_suggests_no_reply():
    plan = funnel.followup_plan(3, T0)
    assert "Sem resposta" in plan.label and plan.at == T0 + timedelta(days=7)
    assert funnel.suggest_no_reply("FOLLOWUP", 3, plan.at, plan.at + timedelta(hours=1))
    assert not funnel.suggest_no_reply("FOLLOWUP", 1, plan.at, plan.at + timedelta(hours=1))


def test_custom_cadence():
    assert funnel.followup_plan(0, T0, [2, 4]).at == T0 + timedelta(days=2)
    assert "Sem resposta" in funnel.followup_plan(2, T0, [2, 4]).label


def test_next_action_per_stage():
    assert funnel.after_status("CONVERSA", T0).at == T0 + timedelta(days=funnel.STALE_TALK_DAYS)
    assert funnel.after_status("PROPOSTA", T0).label.startswith("Cobrar")
    assert funnel.after_status("PERDIDO", T0).label is None


def _lead(session, **kw):
    return session.scalars(select(Lead).filter_by(**kw).order_by(Lead.opportunity.desc())).first()


def test_mark_sent_moves_to_abordado_and_schedules_followup(seeded, session, ctx):
    lead = _lead(session, score="A")
    lead_service.mark_sent(session, lead, ctx, "primeira", "whatsapp", now=T0)
    assert lead.status == "ABORDADO" and lead.contacted_at == T0
    assert lead.next_action == "Follow-up 1" and lead.next_action_at == T0 + timedelta(days=3)
    ev = session.scalars(select(LeadEvent).where(LeadEvent.lead_id == lead.id, LeadEvent.type == "enviado")).all()
    assert len(ev) == 1 and ev[0].note.startswith("Abordagem")


def test_followups_walk_the_cadence_then_suggest_no_reply(seeded, session, ctx):
    lead = _lead(session, score="A")
    lead_service.mark_sent(session, lead, ctx, "primeira", now=T0)
    t1 = T0 + timedelta(days=3)
    lead_service.mark_sent(session, lead, ctx, "followup1", now=t1)
    assert lead.status == "FOLLOWUP" and lead.followup_step == 1 and lead.next_action_at == t1 + timedelta(days=5)
    t2 = t1 + timedelta(days=5)
    lead_service.mark_sent(session, lead, ctx, "followup2", now=t2)
    assert lead.next_action == "Follow-up 3" and lead.next_action_at == t2 + timedelta(days=7)
    t3 = t2 + timedelta(days=7)
    lead_service.mark_sent(session, lead, ctx, "followup3", now=t3)
    assert "Sem resposta" in lead.next_action and lead.status == "FOLLOWUP"  # a app só sugere


def test_change_status_records_event_and_lost_reason(seeded, session, ctx):
    lead = _lead(session, score="A")
    before = lead.status
    lead_service.change_status(session, lead, "PERDIDO", ctx, "Achou caro", lost_reason="preco")
    ev = lead.events[0]
    assert (ev.type, ev.from_status, ev.to_status) == ("status", before, "PERDIDO")
    assert "Preço" in ev.note and lead.lost_reason == "preco" and ev.created_at is not None


def test_closing_saves_value_and_sold_services(seeded, session, ctx):
    lead = _lead(session, score="A")
    lead_service.change_status(session, lead, "FECHADO", ctx, value=1500.0, recurring=90.0)
    assert lead.proposal_value == 1500.0 and lead.recurring_value == 90.0
    assert lead.closed_at is not None and lead.sold_services == [lead.rec_main]


def test_session_queue_overdue_followups_first_then_hottest(seeded, session, ctx):
    a, b = session.scalars(select(Lead).where(Lead.score == "A").order_by(Lead.opportunity.desc()).limit(2)).all()
    now = utcnow()
    lead_service.mark_sent(session, b, ctx, "primeira", now=now - timedelta(days=4))  # follow-up vencido ontem
    queue = today.session_queue(session, ctx, include_mock=True, now=now)
    assert queue[0].id == b.id
    rest = [l for l in queue if l.status in ("NOVO", "ANALISADO", "AMOSTRA")]
    assert rest[0].id == a.id
    order = [(0 if l.score == "A" else 1, -l.opportunity) for l in rest]
    assert order == sorted(order)
    assert all(l.phone for l in rest) and all(l.score in ("A", "B") for l in rest)


def test_today_lists_followups_due_and_week_goal(seeded, session, ctx):
    lead = _lead(session, score="A")
    now = utcnow()
    lead_service.mark_sent(session, lead, ctx, "primeira", now=now - timedelta(days=3, hours=1))
    data = today.today(session, ctx, include_mock=True, now=now)
    assert [l.id for l in data["followups"]] == [lead.id]
    assert data["next_step"][0] == "followups" and data["week_goal"] == 5
    assert today.today(session, ctx, include_mock=False, now=now)["followups"] == []  # fictício não entra sem pedir


def test_do_not_contact_blocks_stage_change_and_sent(seeded, session, ctx):
    import pytest

    lead = _lead(session, score="A")
    lead_service.mark_do_not_contact(session, lead, ctx)
    assert lead.do_not_contact and lead.status == "DESCARTADO" and lead.opportunity == 0
    with pytest.raises(PermissionError):
        lead_service.change_status(session, lead, "ABORDADO", ctx)
    with pytest.raises(PermissionError):
        lead_service.mark_sent(session, lead, ctx)
