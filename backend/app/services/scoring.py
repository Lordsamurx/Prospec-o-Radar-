"""Nota do lead A/B/C/Descarte, conforme docs/06 do protótipo. Função pura, sem HTTP.

Ordem das regras (igual à do protótipo):
1. DESCARTE: não contatar, fechado, ou categoria fora do nicho do lead.
2. C: franquia/rede, sem telefone, ou site próprio razoável (HTTPS).
3. B: só rede social ou página de plataforma, site fraco (sem HTTPS, fora do ar),
      ou sem site com poucas avaliações / nota abaixo do limite.
4. A: sem site + telefone + nota e avaliações acima do limite do nicho + aberto.
Lead do OpenStreetMap sem conferência: sem dado não é sinal ruim -> B, "confira no Google Maps".
A nota manual (score_manual) prevalece sobre tudo, mostrando qual seria a automática.
"""
from typing import Any

from .. import catalog
from .diagnose import Diagnostico, Limits, diagnose, g
from .normalize import stars


def auto_score(lead: Any, franchise_names: list[str] | None = None, diag: Diagnostico | None = None,
               limits: Limits | None = None) -> tuple[str, str]:
    niche = catalog.niches().get_or_other(g(lead, "niche"))
    d = diag or diagnose(lead, niche, franchise_names, limits)
    lim = d.limits
    if g(lead, "do_not_contact"):
        return "DESCARTE", "Marcado como não contatar."
    if not d.is_open:
        status = g(lead, "business_status") or ""
        return "DESCARTE", "Fechado no Google." if "PERMANENTLY" in status else "Fechado temporariamente."
    if d.out_of_niche:
        return "DESCARTE", f"Categoria fora do nicho ({niche.label.lower()})."

    if d.is_franchise:
        return "C", "Franquia ou rede: decisão não é do dono local."
    unchecked_osm = d.from_osm and not d.google_known
    if not d.has_phone and not d.from_osm:
        return "C", "Sem telefone para contato direto."
    if d.site_kind == "own_ok":
        return "C", "Já tem site próprio com HTTPS."

    if d.site_kind == "social":
        return "B", f"Só tem {d.platform or 'rede social'}, sem site próprio."
    if d.site_kind == "platform":
        return "B", f"Só tem página no {d.platform or 'serviço de terceiros'}, sem site próprio."
    if d.site_kind == "own_down":
        return "B", "Site fraco: o endereço não abre."
    if d.site_kind == "own_nohttps":
        return "B", "Site fraco: sem HTTPS."
    if d.site_kind == "own_weak":
        return "B", "Site fraco: " + " ".join(d.site_issues)
    # sem site
    if unchecked_osm:
        falta = "nota e telefone" if not d.has_phone else "nota"
        fonte = "no cadastro digitado" if str(g(lead, "place_id") or "").startswith("manual-") else "no OpenStreetMap"
        return "B", f"Sem site {fonte}, que não traz {falta}: confira no Google Maps (clique no nome)."
    if d.on_google is False:
        return "B", "Sem site e sem perfil no Google (você conferiu): precisa de tudo, mas falta prova de movimento."
    if not d.has_phone:
        return "B", "Sem site e sem telefone no cadastro: confira o contato no Google Maps."
    if d.rating is not None and d.rating >= lim.min_rating and d.reviews >= lim.min_reviews:
        origem = " (conferido por você no Maps)" if d.from_osm else ""
        return "A", f"Sem site, com telefone, {stars(d.rating)}★ e {d.reviews} avaliações, aberto{origem}."
    if d.reviews < lim.min_reviews:
        return "B", f"Sem site, mas poucas avaliações ({d.reviews})."
    return "B", f"Sem site, mas nota {stars(d.rating)} abaixo de {stars(lim.min_rating)}."


def score(lead: Any, franchise_names: list[str] | None = None, diag: Diagnostico | None = None,
          limits: Limits | None = None) -> tuple[str, str]:
    """Nota final: a manual prevalece; senão, a automática."""
    auto, reason = auto_score(lead, franchise_names, diag, limits)
    manual = g(lead, "score_manual")
    if manual:
        return manual, f"Ajuste manual (automática seria {auto}: {reason})"
    return auto, reason


def hook(lead: Any, diag: Diagnostico | None = None) -> str:
    """Gancho de 1 linha para a abordagem (docs/06), com o termo do nicho do lead."""
    niche = catalog.niches().get_or_other(g(lead, "niche"))
    d = diag or diagnose(lead, niche)
    name = g(lead, "name") or "o negócio"
    bairro = g(lead, "neighborhood") or g(lead, "city")
    if d.rating and d.rating >= d.limits.min_rating and d.reviews:
        base = f"vi que o {name} tem {stars(d.rating)} estrelas e {d.reviews} avaliações"
    else:
        base = f"vi o {name} no Google" if d.google_known else f"encontrei o {name} aqui na região"
    if niche.term:
        who = f"quem pesquisa '{niche.term} em {bairro}'" if bairro else f"quem pesquisa '{niche.term}' na região"
    else:
        who = f"quem procura vocês no Google em {bairro}" if bairro else "quem procura vocês no Google"
    if d.site_kind == "social":
        return f"{base}, mas {who} só acha o {d.platform or 'perfil de rede social'}, não um site."
    if d.site_kind == "platform":
        return f"{base}, mas {who} cai numa página do {d.platform or 'aplicativo'}, não num site de vocês."
    if d.site_kind == "own_down":
        return f"{base}, mas o site de vocês não está abrindo para {who}."
    if d.site_kind.startswith("own"):
        return f"{base}, e o site atual pode passar mais confiança para {who}."
    return f"{base}, mas não tem site para {who}."
