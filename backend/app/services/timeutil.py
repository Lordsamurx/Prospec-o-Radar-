"""Datas: o banco guarda UTC sem fuso; a tela e as contas de "hoje" usam Brasília."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def from_local(value: datetime) -> datetime:
    return value.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def day_start(now: datetime | None = None) -> datetime:
    """Começo do dia de hoje em Brasília, devolvido em UTC."""
    local = to_local(now or utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def day_end(now: datetime | None = None) -> datetime:
    return day_start(now) + timedelta(days=1)


def week_start(now: datetime | None = None) -> datetime:
    local = to_local(now or utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    local -= timedelta(days=local.weekday())  # segunda-feira
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def month_start(now: datetime | None = None) -> datetime:
    local = to_local(now or utcnow()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def fmt(value: datetime | None, with_time: bool = True) -> str:
    if not value:
        return "—"
    return to_local(value).strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def fmt_day(value: datetime | None, now: datetime | None = None) -> str:
    """'hoje', 'amanhã', 'ontem', 'há 3 dias', 'em 5 dias' ou a data."""
    if not value:
        return "—"
    days = (to_local(value).date() - to_local(now or utcnow()).date()).days
    if days == 0:
        return "hoje"
    if days == 1:
        return "amanhã"
    if days == -1:
        return "ontem"
    if -30 <= days < 0:
        return f"há {-days} dias"
    if 0 < days <= 30:
        return f"em {days} dias"
    return to_local(value).strftime("%d/%m/%Y")
