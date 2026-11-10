"""Recomendação de serviços por lead (seção 4.5). Função pura.

recommend(lead, diagnostico, nicho, catalogo) -> lista ordenada de Recomendacao, cada uma
com prioridade (principal / complemento / upsell) e o motivo em uma frase com dados do lead.
Serviço inativo no catálogo nunca é sugerido.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import catalog
from .diagnose import MIN_PHOTOS, UPSELL_RATING, Diagnostico, g
from .normalize import stars

SITE_SERVICES = ("landing", "institucional", "cardapio", "agendamento", "catalogo", "links")
BOOKING_SECTORS = ("beleza", "saude", "pet", "fitness")


@dataclass(frozen=True)
class Recomendacao:
    key: str
    name: str
    priority: str  # principal | complemento | upsell
    reason: str
    price_text: str = "preço a definir"
    price_min: float | None = None
    price_max: float | None = None
    recurring: bool = False


@dataclass(frozen=True)
class Pacote:
    items: tuple[Recomendacao, ...]
    total_min: float | None
    total_max: float | None
    monthly_min: float | None
    monthly_max: float | None
    complete: bool  # todos os itens têm preço

    @property
    def total_text(self) -> str:
        if self.total_min is None and self.monthly_min is None:
            return "Preencha os preços na tela Serviços para ver o total."
        parts = []
        if self.total_min is not None:
            parts.append(catalog.price_text(self.total_min, self.total_max))
        if self.monthly_min is not None:
            parts.append(catalog.price_text(self.monthly_min, self.monthly_max, True))
        return " + ".join(parts) + ("" if self.complete else " (há itens sem preço)")


def recommend(lead: Any, d: Diagnostico, niche: catalog.Niche,
              services: dict[str, catalog.ServiceItem]) -> list[Recomendacao]:
    out: dict[str, tuple[str, str]] = {}  # key -> (prioridade, motivo), na ordem de entrada

    def add(key: str, priority: str, reason: str) -> None:
        svc = services.get(key)
        if svc is None or not svc.active or key in out:
            return
        out[key] = (priority, reason)

    name = g(lead, "name") or "o negócio"
    bairro = g(lead, "neighborhood") or g(lead, "city") or "a região"
    sector = niche.sector
    rep = f"{stars(d.rating)}★ e {d.reviews} avaliações" if d.rating is not None else None
    main = niche.default_offer if niche.default_offer in SITE_SERVICES else "landing"
    kind = d.site_kind

    if d.from_osm and d.on_google is False:
        add("gmn_criacao", "principal", f"Você conferiu que {name} não aparece no Google Maps: antes de tudo, precisa existir lá.")

    if kind == "none":
        if d.reputation_strong:
            why = f"Tem {rep} e nenhum site: quem pesquisa '{niche.term or 'o serviço'} em {bairro}' não chega até {name}."
        elif d.google_known:
            why = f"Sem site: uma página simples já coloca {name} na frente de quem pesquisa em {bairro}."
        else:
            why = f"Sem site no cadastro: confira no Maps e ofereça uma página para {name} ser achado em {bairro}."
        if sector == "alimentacao":
            add("cardapio", "principal", f"Sem cardápio online, o pedido de {name} vai para o iFood ou para o concorrente. " + why)
            add("landing", "complemento", "Uma página com endereço, horário e botão de WhatsApp junto do cardápio.")
        elif sector in BOOKING_SECTORS and main != "agendamento":
            add(main, "principal", why)
            add("agendamento", "complemento", "Cliente desse tipo de negócio quer marcar horário na hora: página de agendamento pelo WhatsApp.")
        elif sector in BOOKING_SECTORS:
            add("agendamento", "principal", "Quem acha no Google quer marcar na hora. " + why)
            add("landing", "complemento", "Página de apresentação com serviços, fotos e avaliações.")
        else:
            add(main, "principal", why)
    elif kind == "platform":
        plat = d.platform or "plataforma"
        if sector == "alimentacao":
            add("cardapio", "principal", f"Hoje {name} só vende pelo {plat}, que cobra taxa e mostra o concorrente ao lado: cardápio próprio com pedido no WhatsApp.")
            add("landing", "complemento", "Página própria para aparecer no Google sem depender do aplicativo.")
        elif sector in BOOKING_SECTORS:
            add("agendamento", "principal", f"A agenda de {name} está presa no {plat}: página própria de agendamento, com a marca dele.")
            add("landing", "complemento", "Página de apresentação para o Google, fora da plataforma.")
        else:
            add(main, "principal", f"O 'site' de {name} é uma página no {plat}: endereço e visual próprios passam mais confiança.")
    elif kind == "social":
        rede = d.platform or "rede social"
        add("landing", "principal", f"{name} depende só do {rede}: uma landing page aparece no Google e leva direto ao WhatsApp.")
        add("links", "complemento", f"Página de links própria para a bio do {rede if rede != 'Linktree' else 'Instagram'}, no lugar de link genérico.")
        if sector == "alimentacao":
            add("cardapio", "complemento", "Cardápio digital com pedido pelo WhatsApp, linkado na bio.")
        elif sector in BOOKING_SECTORS:
            add("agendamento", "complemento", "Página de agendamento pelo WhatsApp, linkada na bio.")
    elif kind in ("own_nohttps", "own_down", "own_weak"):
        add("reformulacao", "principal", f"O site de {name} está fraco: " + (" ".join(d.site_issues) or "precisa de reforma."))

    if any(k in out and out[k][0] == "principal" and services[k].kind == "site" for k in out) or "reformulacao" in out:
        add("manutencao", "complemento", "Site no ar precisa de hospedagem, segurança e pequenas mudanças: plano mensal.")

    # Google Meu Negócio
    if d.google_known and d.on_google is not False:
        gaps = []
        if d.photos is not None and d.photos < MIN_PHOTOS:
            gaps.append(f"só {d.photos} foto(s)")
        if d.has_hours is False:
            gaps.append("sem horário")
        if gaps:
            add("gmn_otimizacao", "upsell" if kind == "own_ok" else "complemento",
                f"Perfil no Google incompleto ({', '.join(gaps)}): perfil completo recebe mais ligações e rotas.")
        if d.reviews < d.limits.min_reviews:
            add("avaliacoes", "upsell" if kind == "own_ok" else "complemento",
                f"Só {d.reviews} avaliações (o comum para {niche.plural} é {d.limits.min_reviews}+): QR code e link para pedir a cada cliente.")
        elif d.rating is not None and d.rating < UPSELL_RATING:
            add("avaliacoes", "upsell" if kind == "own_ok" else "complemento",
                f"Nota {stars(d.rating)}: responder as avaliações e pedir novas ajuda a passar de {stars(UPSELL_RATING)}.")

    if kind == "own_ok":
        add("seo_local", "principal" if not out else "upsell",
            f"{name} já tem site: páginas por bairro e por serviço fazem ele aparecer em mais buscas de {bairro}.")
        add("carrosseis", "upsell", "Conteúdo pronto para manter o Instagram ativo e levar gente para o site.")
        add("avaliacoes", "upsell", "Mais avaliações recentes mantêm o perfil na frente dos concorrentes.")
    elif kind in ("none", "social", "platform") and sector in ("profissionais", "saude"):
        add("dominio_email", "upsell", "E-mail com o nome do negócio (contato@...) passa mais seriedade que um Gmail.")

    # garante exatamente um principal: o primeiro da lista
    recs: list[Recomendacao] = []
    has_main = False
    for key, (priority, reason) in out.items():
        if priority == "principal":
            if has_main:
                priority = "complemento"
            has_main = True
        s = services[key]
        recs.append(Recomendacao(key, s.name, priority, reason, s.price_text, s.price_min, s.price_max, s.recurring))
    if recs and not has_main:
        first = recs[0]
        recs[0] = Recomendacao(first.key, first.name, "principal", first.reason, first.price_text, first.price_min,
                               first.price_max, first.recurring)
    order = {"principal": 0, "complemento": 1, "upsell": 2}
    return sorted(recs, key=lambda r: order[r.priority])


def package(recs: list[Recomendacao], chosen: list[str] | None = None) -> Pacote:
    """Pacote sugerido: principal + complementos (ou os serviços que o Samuel marcou)."""
    if chosen:
        items = [r for r in recs if r.key in chosen]
    else:
        items = [r for r in recs if r.priority in ("principal", "complemento")]
    return _sum(items)


def package_from_services(keys: list[str], services: dict[str, catalog.ServiceItem]) -> Pacote:
    items = [Recomendacao(s.key, s.name, "principal" if i == 0 else "complemento", s.short, s.price_text, s.price_min,
                          s.price_max, s.recurring)
             for i, s in enumerate(services[k] for k in keys if k in services)]
    return _sum(items)


def _sum(items: list[Recomendacao]) -> Pacote:
    one = [r for r in items if not r.recurring and r.price_min is not None]
    rec = [r for r in items if r.recurring and r.price_min is not None]
    complete = all(r.price_min is not None for r in items) and bool(items)
    return Pacote(
        items=tuple(items),
        total_min=sum(r.price_min for r in one) if one else None,  # type: ignore[misc]
        total_max=sum((r.price_max if r.price_max is not None else r.price_min) for r in one) if one else None,  # type: ignore[misc]
        monthly_min=sum(r.price_min for r in rec) if rec else None,  # type: ignore[misc]
        monthly_max=sum((r.price_max if r.price_max is not None else r.price_min) for r in rec) if rec else None,  # type: ignore[misc]
        complete=complete,
    )
