"""Regras do funil (seção 4.7) e cadência de follow-up (4.10, item 9). Funções puras.

Nada aqui muda um lead sozinho: as funções só calculam a próxima ação e as sugestões.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import PRE_CONTACT, WAITING_REPLY

DEFAULT_CADENCE = [3, 5, 7]
STALE_TALK_DAYS = 3
STALE_PROPOSAL_DAYS = 3


@dataclass(frozen=True)
class NextAction:
    label: str | None
    at: datetime | None


def followup_plan(step: int, last_touch: datetime, cadence: list[int] | None = None) -> NextAction:
    """Próxima ação depois de `step` follow-ups enviados, contando do último contato.

    Cadência crescente: +3, +5 e +7 dias (configurável). Depois do último follow-up, espera
    mais um intervalo e SUGERE "Sem resposta" (quem confirma é o Samuel)."""
    cad = cadence or DEFAULT_CADENCE
    if step < len(cad):
        return NextAction(f"Follow-up {step + 1}", last_touch + timedelta(days=cad[step]))
    return NextAction("Sem retorno: mover para Sem resposta?", last_touch + timedelta(days=cad[-1]))


def after_status(status: str, now: datetime, cadence: list[int] | None = None, step: int = 0) -> NextAction:
    """Próxima ação sugerida ao entrar numa etapa."""
    if status in WAITING_REPLY:
        return followup_plan(step, now, cadence)
    if status == "CONVERSA":
        return NextAction("Responder e avançar a conversa", now + timedelta(days=STALE_TALK_DAYS))
    if status == "PROPOSTA":
        return NextAction("Cobrar retorno da proposta", now + timedelta(days=STALE_PROPOSAL_DAYS))
    if status == "FECHADO":
        return NextAction("Combinar o início da produção", now + timedelta(days=1))
    if status == "PRODUCAO":
        return NextAction("Entregar e pedir avaliação", None)
    if status == "AMOSTRA":
        return NextAction("Abordar com a amostra", None)
    if status in PRE_CONTACT:
        return NextAction("Gerar amostra e abordar", None)
    return NextAction(None, None)


def is_overdue(status: str, next_action_at: datetime | None, now: datetime) -> bool:
    return bool(next_action_at) and next_action_at <= now and status not in ("SEM_RESPOSTA", "PERDIDO", "DESCARTADO",
                                                                             "ENTREGUE")


def suggest_no_reply(status: str, step: int, next_action_at: datetime | None, now: datetime,
                     cadence: list[int] | None = None) -> bool:
    """True quando o último follow-up já venceu sem resposta. A app só sugere."""
    cad = cadence or DEFAULT_CADENCE
    return status in WAITING_REPLY and step >= len(cad) and bool(next_action_at) and next_action_at <= now


def followup_kind(step: int) -> str:
    """Tipo de mensagem para o follow-up de número step+1."""
    return f"followup{min(step + 1, 3)}"
