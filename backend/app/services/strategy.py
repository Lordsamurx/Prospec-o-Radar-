"""Estratégia por lead, calculada na hora e sem IA (seção 4.10, item 6). Função pura."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import catalog
from .diagnose import Diagnostico, g
from .normalize import stars
from .recommend import Recomendacao

SCENARIOS = {
    "bem_avaliado_sem_site": ("Reputação pronta, vitrine faltando",
                              "Mostre que a parte difícil (clientes satisfeitos) já existe; o site só leva isso para quem ainda não conhece."),
    "invisivel": ("Negócio escondido",
                  "Comece pelo básico e barato: ser achado. Mostre uma busca no Google onde ele não aparece."),
    "so_rede_social": ("Refém da rede social",
                       "Não fale mal do Instagram: o site soma. Rede social é para quem já segue; Google é para quem está procurando agora."),
    "preso_plataforma": ("Cliente da plataforma, não dele",
                         "Fale de taxa, de concorrente ao lado e de quem fica com o contato do cliente."),
    "site_datado": ("Site que atrapalha",
                    "Mostre o problema na tela do celular dele. O site atual pode estar espantando cliente."),
    "bem_resolvido": ("Já tem o básico",
                      "Não ofereça site. Ofereça crescimento: mais avaliações, mais buscas por bairro, conteúdo."),
}
COMMON_OBJECTIONS = [
    ("Já tenho Instagram.", "Ótimo, ele continua. O Instagram fala com quem já segue; o site aparece para quem digita no Google e ainda não conhece vocês. Um leva para o outro."),
    ("Site é caro.", "Faço em etapas e o valor é fechado antes de começar. A amostra que montei já mostra como fica, sem compromisso."),
    ("Foi um conhecido que fez.", "Sem problema, dá para aproveitar o que já existe. Posso mostrar só os pontos que estão custando cliente hoje e vocês decidem."),
    ("Agora não é o momento.", "Tranquilo. Deixo a amostra com vocês e volto a falar em algumas semanas. Posso?"),
    ("Meus clientes vêm por indicação.", "Indicação é o melhor canal. Só que hoje quem recebe a indicação pesquisa o nome no Google antes de ligar; o site confirma a indicação."),
]
SCENARIO_OBJECTIONS = {
    "preso_plataforma": ("Já vendo bem pelo aplicativo.",
                         "Continua vendendo. O link próprio é para o cliente que já conhece vocês pedir direto, sem taxa e sem ver o concorrente."),
    "site_datado": ("Meu site funciona.",
                    "Funciona no computador. No celular, que é de onde vem a maioria das buscas, ele {issue}"),
    "bem_resolvido": ("Já tenho site.",
                      "E está bom. A ideia é fazer ele trabalhar mais: aparecer por bairro, juntar avaliações e trazer mais ligações."),
    "invisivel": ("Não sei se vale a pena para o meu tamanho.",
                  "Para negócio pequeno é onde mais vale: uma página simples já faz vocês aparecerem quando alguém pesquisa aqui no bairro."),
}


@dataclass(frozen=True)
class Estrategia:
    scenario: str
    title: str
    angle: str
    hooks: tuple[str, ...]
    objections: tuple[tuple[str, str], ...]
    next_step: str


def strategy(lead: Any, d: Diagnostico, profile_key: str, niche: catalog.Niche, recs: list[Recomendacao]) -> Estrategia:
    title, angle = SCENARIOS.get(profile_key, SCENARIOS["invisivel"])
    name = g(lead, "name") or "o negócio"
    bairro = g(lead, "neighborhood") or g(lead, "city") or "a região"
    hooks: list[str] = []
    if d.rating is not None and d.reputation_strong:
        hooks.append(f"Nota {stars(d.rating)} com {d.reviews} avaliações: a reputação existe, só não aparece fora do Maps.")
    elif d.rating is not None:
        hooks.append(f"Nota {stars(d.rating)} com {d.reviews} avaliações: dá para crescer com um jeito fácil de pedir avaliação.")
    elif not d.google_known:
        hooks.append("Ainda não conferido no Google: abra o Maps e anote nota, avaliações e fotos antes de abordar.")
    if d.site_kind == "none" and niche.term:
        hooks.append(f"Quem pesquisa '{niche.term} em {bairro}' não encontra uma página de {name}.")
    if d.site_kind == "social":
        hooks.append(f"O link do perfil leva para o {d.platform or 'perfil'}: não dá para ver serviços, preços e horário num lugar só.")
    if d.site_kind == "platform":
        hooks.append(f"O 'site' é uma página no {d.platform}: lá o cliente vê o concorrente a um toque.")
    for issue in d.site_issues[:2]:
        hooks.append("No site atual: " + issue[0].lower() + issue[1:])
    if d.has_hours is False:
        hooks.append("O perfil no Google está sem horário de funcionamento.")
    if d.photos is not None and d.photos < 5 and d.google_known:
        hooks.append(f"O perfil no Google tem {d.photos} foto(s): os concorrentes costumam ter dezenas.")
    if d.phone_kind == "mobile":
        hooks.append("Tem celular no cadastro: dá para abordar pelo WhatsApp.")
    elif d.phone_kind == "landline":
        hooks.append("Só telefone fixo: ligue em horário comercial e peça o WhatsApp do responsável.")
    objections = list(COMMON_OBJECTIONS)
    extra = SCENARIO_OBJECTIONS.get(profile_key)
    if extra:
        q, a = extra
        issue = (d.site_issues[0][0].lower() + d.site_issues[0][1:]) if d.site_issues else "deixa a desejar."
        objections.insert(0, (q, a.format(issue=issue)))
    if profile_key == "bem_resolvido":
        objections = [o for o in objections if o[0] != "Já tenho Instagram."]
    main = recs[0].name if recs else None
    if d.is_franchise:
        nxt = "Franquia ou rede: só aborde se souber quem decide na unidade."
    elif not d.google_known:
        nxt = "Conferir o perfil no Google Maps e preencher a checagem; depois gerar a amostra."
    elif not d.has_phone:
        nxt = "Achar um contato (Instagram ou visita) antes de gerar a amostra."
    elif main:
        via = "pelo WhatsApp" if d.phone_kind == "mobile" else "por ligação"
        nxt = f"Gerar a amostra de {main.lower()} e abordar {via}."
    else:
        nxt = "Sem serviço ativo para sugerir: revise o catálogo de serviços."
    return Estrategia(profile_key, title, angle, tuple(hooks), tuple(objections), nxt)
