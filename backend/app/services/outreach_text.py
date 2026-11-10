"""Rascunhos de abordagem. NUNCA envia: só monta o texto para o Samuel copiar.

Mensagem montada com o gancho do nicho e os serviços escolhidos, em quatro canais
(WhatsApp, Direct do Instagram, e-mail, roteiro de ligação) e mais os follow-ups 1, 2 e 3.
"""
from __future__ import annotations

from typing import Any

from .. import catalog
from . import scoring
from .diagnose import Diagnostico, g

CHANNELS = {"whatsapp": "WhatsApp", "instagram": "Direct do Instagram", "email": "E-mail", "ligacao": "Roteiro de ligação"}
KINDS = {"primeira": "Primeira mensagem", "followup1": "Follow-up 1", "followup2": "Follow-up 2",
         "followup3": "Follow-up 3 (último)"}
# o que cada serviço resolve, numa frase que cabe no meio da mensagem
PITCH = {
    "landing": "uma página simples que aparece no Google e leva a pessoa direto para o WhatsApp de vocês",
    "institucional": "um site completo, com os serviços, a equipe e o contato de vocês num endereço próprio",
    "cardapio": "um cardápio digital próprio, em que o cliente monta o pedido e manda direto no WhatsApp de vocês, sem taxa",
    "agendamento": "uma página de agendamento, em que o cliente escolhe o serviço e pede o horário pelo WhatsApp",
    "catalogo": "uma vitrine online com os produtos de vocês e pedido pelo WhatsApp",
    "links": "uma página de links com a cara de vocês para a bio do Instagram",
    "reformulacao": "uma versão nova do site de vocês: segura, rápida e boa no celular",
    "gmn_otimizacao": "deixar o perfil de vocês no Google completo, com fotos, horário e botão de WhatsApp",
    "gmn_criacao": "colocar o negócio de vocês no Google Maps, com tudo preenchido",
    "avaliacoes": "um jeito fácil de pedir avaliação no Google a cada cliente satisfeito",
    "seo_local": "páginas por bairro e por serviço, para vocês aparecerem em mais buscas da região",
    "dominio_email": "domínio e e-mail com o nome do negócio",
    "carrosseis": "carrosséis prontos para manter o Instagram de vocês ativo",
    "manutencao": "manter o site no ar, seguro e atualizado todo mês",
}


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _what(seller: dict, niche: catalog.Niche, main: str | None) -> str:
    if main in ("gmn_otimizacao", "gmn_criacao", "avaliacoes"):
        return f"ajudo {niche.plural} a aparecer melhor no Google"
    if main == "carrosseis":
        return f"faço conteúdo para {niche.plural}"
    return f"faço sites para {niche.plural}"


def offer_sentence(keys: list[str]) -> str:
    """Frase com os serviços escolhidos (o primeiro é o principal)."""
    parts = [PITCH[k] for k in keys if k in PITCH and k != "manutencao"][:2]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"Pensei em {parts[0]}."
    return f"Pensei em {parts[0]}. Também dá para {_infinitive(parts[1])}."


def _infinitive(pitch: str) -> str:
    for start, verb in (("uma ", "criar uma "), ("um ", "criar um "), ("páginas", "criar páginas"),
                        ("carrosséis", "produzir carrosséis"), ("domínio", "registrar domínio")):
        if pitch.startswith(start):
            return verb + pitch[len(start):] if start.endswith(" ") else verb + pitch[len(start):]
    return pitch


def chosen_keys(lead: Any, recs: list) -> list[str]:
    offered = [k for k in (g(lead, "offered") or []) if k in PITCH]
    if offered:
        return offered
    return [r.key for r in recs if r.priority in ("principal", "complemento")][:2]


def draft(lead: Any, d: Diagnostico, recs: list, seller: dict, preview_url: str | None = None,
          channel: str = "whatsapp", kind: str = "primeira") -> str:
    niche = catalog.niches().get_or_other(g(lead, "niche"))
    name = g(lead, "name") or "o negócio"
    keys = chosen_keys(lead, recs)
    main = keys[0] if keys else None
    me = seller.get("name") or "Samuel"
    city = seller.get("city") or "BH"
    hook = _upper_first(scoring.hook(lead, d))
    offer = offer_sentence(keys)
    sample = ("Montei uma amostra gratuita com os dados públicos de vocês, só para mostrar como ficaria:\n" + preview_url
              if preview_url else "Posso montar uma amostra gratuita com os dados públicos de vocês, sem compromisso. Quer ver?")
    close = "Se gostar, ajusto cores, fotos e textos do jeito de vocês. Se não fizer sentido, sem problema!" if preview_url else ""

    if kind.startswith("followup"):
        return _followup(kind, name, me, preview_url, channel)

    if channel == "instagram":
        lines = [f"Oi! Tudo bem? Sou o {me}, {_what(seller, niche, main)} aqui em {city}.", hook]
        if offer:
            lines.append(offer)
        lines.append("Fiz uma amostra gratuita para vocês verem: " + preview_url if preview_url
                     else "Posso mandar uma amostra gratuita para vocês verem?")
        return "\n".join(lines)
    if channel == "email":
        subject = f"Assunto: Uma ideia para o {name} aparecer mais no Google"
        body = [subject, "", f"Olá, pessoal do {name}!", "",
                f"Sou o {me} e {_what(seller, niche, main)} aqui em {city}. {hook}", ""]
        if offer:
            body += [offer, ""]
        body += [sample, ""]
        if close:
            body += [close, ""]
        body += ["Se preferirem, me chamem no WhatsApp ou respondam este e-mail.", "", "Abraço,", me]
        return "\n".join(body)
    if channel == "ligacao":
        lines = [
            "ROTEIRO DE LIGAÇÃO (leia com naturalidade, não precisa seguir palavra por palavra)", "",
            f"1. Abertura: \"Oi, bom dia! Falo com o responsável pelo {name}? Aqui é o {me}, sou aqui de {city}.\"",
            f"2. Motivo: \"{hook}\"",
        ]
        if offer:
            lines.append(f"3. Proposta: \"{offer}\"")
        lines += [
            f"{4 if offer else 3}. Pedido: \"Montei uma amostra gratuita para vocês verem. Posso mandar no WhatsApp? Qual é o melhor número?\"",
            f"{5 if offer else 4}. Se disser que não tem interesse: agradeça e encerre. Se pedir para não ligar mais, marque \"Não contatar\".",
        ]
        return "\n".join(lines)
    lines = [f"Oi, tudo bem? Falo com o {name}?", "",
             f"Sou o {me}, {_what(seller, niche, main)} aqui em {city}. {hook}", ""]
    if offer:
        lines += [offer, ""]
    lines.append(sample)
    if close:
        lines += ["", close]
    return "\n".join(lines)


def _followup(kind: str, name: str, me: str, preview_url: str | None, channel: str) -> str:
    link = f"\n{preview_url}" if preview_url else ""
    if kind == "followup1":
        text = (f"Oi! Aqui é o {me} de novo. Conseguiram ver a amostra que montei para o {name}?{link}\n\n"
                "Se quiserem, mostro em 5 minutos como ficaria com as fotos e os serviços de vocês.")
    elif kind == "followup2":
        text = (f"Oi, pessoal do {name}! Sei que a rotina é corrida, então vou ser breve: a amostra continua no ar"
                f"{' aqui:' + link if link else '.'}\n\n"
                "Tem alguma dúvida sobre preço ou prazo que eu possa responder?")
    else:
        text = (f"Oi! Última mensagem para não incomodar: vou deixar a amostra do {name} no ar por mais alguns dias."
                f"{link}\n\nSe um dia fizer sentido, é só me chamar. Sucesso para vocês!")
    if channel == "ligacao":
        return "ROTEIRO DE LIGAÇÃO (retorno)\n\n\"" + text.replace("\n\n", " ").replace("\n", " ") + "\""
    if channel == "email":
        return f"Assunto: A amostra do {name}\n\n{text}\n\nAbraço,\n{me}"
    return text
