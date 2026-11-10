"""Proposta comercial e diagnóstico de uma página (seções 4.8 e 4.10 item 5). Funções puras.

As páginas são HTML imprimível: o navegador gera o PDF (Imprimir > Salvar como PDF)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import catalog
from .recommend import Pacote


def build_items(pkg: Pacote, services: dict[str, catalog.ServiceItem], prices: dict[str, float] | None = None) -> list[dict]:
    """Itens da proposta. `prices` (opcional) é o valor fechado por serviço, digitado pelo Samuel."""
    items = []
    for r in pkg.items:
        s = services.get(r.key)
        if s is None:
            continue
        price = (prices or {}).get(r.key)
        if price is None and s.price_min is not None and (s.price_max is None or s.price_max == s.price_min):
            price = s.price_min
        items.append({"key": s.key, "name": s.name, "description": s.description, "delivers": list(s.delivers),
                      "deadline": s.deadline, "recurring": s.recurring, "price": price,
                      "price_text": catalog.price_text(price, price, s.recurring) if price is not None else s.price_text})
    return items


def totals(items: list[dict]) -> tuple[float | None, float | None]:
    """(total único, total mensal). None quando nenhum item daquele tipo tem preço."""
    one = [i["price"] for i in items if not i["recurring"] and i["price"] is not None]
    rec = [i["price"] for i in items if i["recurring"] and i["price"] is not None]
    return (sum(one) if one else None, sum(rec) if rec else None)


def valid_until(created_at: datetime, days: int) -> datetime:
    return created_at + timedelta(days=days)


def plain_problems(diag) -> list[str]:
    """Problemas em linguagem simples para o diagnóstico de uma página."""
    out = [s.phrase for s in diag.signals if s.tone in ("ruim", "atencao") and s.dimension != "porte"]
    return out[:6]
