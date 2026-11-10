"""Raio-X do lead (seção 4.2). Função pura: lê os dados que já temos e devolve sinais.

Cada sinal tem dimensão, valor, tom, peso (pontos de oportunidade) e uma frase que explica.
Nada de HTTP aqui: a checagem do site (services/site_check.py) grava em lead.site_check
e este módulo só lê o resultado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .. import catalog
from .normalize import classify_site, is_https, phone_digits, phone_type, stars

DIMENSIONS = {"site": "Site", "google": "Google", "contato": "Contato", "reputacao": "Reputação"}
UPSELL_RATING = 4.2  # abaixo disso vale oferecer gestão de avaliações
MIN_PHOTOS = 5


@dataclass(frozen=True)
class Limits:
    """Limites da nota A por nicho (decisão aberta nº 6 do docs/08): padrão 4,0 e 15."""
    min_rating: float = 4.0
    min_reviews: int = 15


@dataclass(frozen=True)
class Signal:
    key: str
    dimension: str  # site | google | contato | reputacao | porte
    label: str
    value: str
    tone: str  # bom | atencao | ruim | desconhecido
    weight: int  # pontos que somam no índice de oportunidade
    phrase: str


@dataclass
class Diagnostico:
    signals: list[Signal] = field(default_factory=list)
    dims: dict[str, int | None] = field(default_factory=dict)  # saúde 0–100 por dimensão (None = não conferido)
    site_kind: str = "none"  # none|social|platform|own_ok|own_nohttps|own_down|own_weak
    site_status: str = "none"  # none|social|platform|own
    platform: str | None = None
    from_osm: bool = False
    google_known: bool = True  # False = lead do OSM ainda não conferido no Maps
    on_google: bool | None = True  # False = Samuel confirmou que não aparece no Google
    rating: float | None = None
    reviews: int = 0
    photos: int | None = None
    has_hours: bool | None = None
    has_phone: bool = False
    phone_kind: str | None = None
    reputation_strong: bool = False
    is_franchise: bool = False
    is_open: bool = True
    out_of_niche: bool = False
    limits: Limits = field(default_factory=Limits)
    site_issues: list[str] = field(default_factory=list)
    site_has: list[str] = field(default_factory=list)
    site_missing: list[str] = field(default_factory=list)

    def by_dimension(self, dim: str) -> list[Signal]:
        return [s for s in self.signals if s.dimension == dim]

    def signal(self, key: str) -> Signal | None:
        return next((s for s in self.signals if s.key == key), None)

    def to_dict(self) -> dict:
        return {
            "dims": self.dims, "site_kind": self.site_kind, "platform": self.platform,
            "google_known": self.google_known, "reputation_strong": self.reputation_strong,
            "signals": [s.__dict__ for s in self.signals],
            "site_has": self.site_has, "site_missing": self.site_missing,
        }


def g(lead: Any, key: str, default: Any = None) -> Any:
    if isinstance(lead, dict):
        return lead.get(key, default)
    return getattr(lead, key, default)


def is_franchise(name: str | None, franchise_names: list[str] | None) -> bool:
    n = (name or "").lower()
    return any(f.strip().lower() in n for f in (franchise_names or []) if f and f.strip())


def site_kind_of(lead: Any, extra_platforms: dict[str, str] | None = None) -> tuple[str, str, str | None, list[str]]:
    """(kind, status, plataforma, problemas). Usa o endereço e, se houver, a checagem gravada."""
    url = g(lead, "website_url")
    status, platform = classify_site(url, extra_platforms)
    check = g(lead, "site_check") or {}
    if status != "own":
        return status, status, platform, []
    issues: list[str] = []
    if check.get("checked"):
        if check.get("down"):
            return "own_down", "own", None, ["O site não abre."]
        if check.get("bad_cert"):
            issues.append("Certificado de segurança inválido.")
        if check.get("https") is False:
            issues.append("Sem HTTPS (o navegador avisa que não é seguro).")
        if check.get("viewport") is False:
            issues.append("Não tem versão para celular.")
        if check.get("slow"):
            issues.append(f"Lento para abrir ({check.get('elapsed_ms', 0) / 1000:.1f} s).".replace(".", ",", 1))
        if check.get("builder"):
            issues.append(f"Feito em construtor pronto ({check['builder']}).")
        if check.get("platform_page"):
            issues.append("O endereço leva para uma página de plataforma.")
        if check.get("https") is False or check.get("bad_cert"):
            return "own_nohttps", "own", None, issues
        if issues:
            return "own_weak", "own", check.get("builder"), issues
        return "own_ok", "own", None, []
    if not is_https(url):
        return "own_nohttps", "own", None, ["Sem HTTPS (o navegador avisa que não é seguro)."]
    return "own_ok", "own", None, []


def diagnose(lead: Any, niche: catalog.Niche | None = None, franchise_names: list[str] | None = None,
             limits: Limits | None = None, extra_platforms: dict[str, str] | None = None,
             now: datetime | None = None) -> Diagnostico:
    niche = niche or catalog.niches().get_or_other(g(lead, "niche"))
    limits = limits or Limits(niche.min_rating, niche.min_reviews)
    d = Diagnostico(limits=limits)
    add = d.signals.append
    place_id = str(g(lead, "place_id") or "")
    d.from_osm = place_id.startswith(("osm-", "manual-"))  # fontes sem nota: OpenStreetMap e lead digitado
    check = g(lead, "gmb_check") or {}
    checked = bool(check.get("checked"))
    d.google_known = (not d.from_osm) or checked
    d.on_google = (check.get("exists") if checked else None) if d.from_osm else True

    # ---- valores efetivos: o que veio do provedor ou o que o Samuel conferiu no Maps
    rating = g(lead, "rating")
    reviews = g(lead, "reviews_count") or 0
    photos = g(lead, "photos_count") or 0
    hours = bool((g(lead, "opening_hours") or "").strip())
    if d.from_osm and checked:
        rating = check.get("rating") if check.get("rating") not in ("", None) else rating
        reviews = int(check.get("reviews") or reviews or 0)
        photos = int(check.get("photos") or 0)
        hours = bool(check.get("hours")) or hours
    d.rating, d.reviews = rating, reviews
    d.photos = photos if d.google_known else None
    d.has_hours = hours if d.google_known else (hours or None)

    # ---- situação e porte
    status = g(lead, "business_status")
    d.is_open = not (status and status != "OPERATIONAL")
    cats = set(g(lead, "categories") or [])
    d.out_of_niche = bool(cats and niche.checks_category and not niche.matches(cats)
                          and any(not c.startswith("osm:") for c in cats))
    d.is_franchise = is_franchise(g(lead, "name"), franchise_names)
    if d.is_franchise:
        add(Signal("franquia", "porte", "Porte", "Franquia ou rede", "atencao", 0,
                   "Parece franquia ou rede: a decisão de contratar site não costuma ser do dono local."))
    if not d.is_open:
        add(Signal("fechado", "porte", "Situação", "Fechado", "ruim", 0, "Consta como fechado: não vale abordar."))

    # ---- site
    kind, sstatus, platform, issues = site_kind_of(lead, extra_platforms)
    d.site_kind, d.site_status, d.platform, d.site_issues = kind, sstatus, platform, issues
    site_table = {
        "none": ("Sem site", "ruim", 40, "Não tem site: quem pesquisa no Google não acha uma página do negócio.", 0),
        "social": (f"Só {platform or 'rede social'}", "ruim", 34,
                   f"Depende só de {platform or 'rede social'}: não aparece em buscas como '{niche.term or 'o serviço'} perto de mim'.", 20),
        "platform": (f"Página no {platform}" if platform else "Página de plataforma", "ruim", 32,
                     f"O 'site' é uma página dentro do {platform or 'serviço de terceiros'}: o cliente fica na plataforma, não com o negócio.", 25),
        "own_down": ("Site fora do ar", "ruim", 30, "Tem endereço próprio, mas o site não abre.", 15),
        "own_nohttps": ("Site sem HTTPS", "atencao", 24, "Site próprio sem cadeado: o navegador avisa 'não seguro'.", 40),
        "own_weak": ("Site com problemas", "atencao", 18, "Site próprio com pontos fracos: " + " ".join(issues), 55),
        "own_ok": ("Site próprio", "bom", 4, "Já tem site próprio com HTTPS.", 100),
    }
    val, tone, weight, phrase, health = site_table[kind]
    add(Signal("site", "site", "Site", val, tone, weight, phrase))
    d.dims["site"] = health
    sc = g(lead, "site_check") or {}
    if sc.get("analyzed"):
        d.site_has = list(sc.get("has") or [])
        d.site_missing = list(sc.get("missing") or [])
        if d.site_missing and kind.startswith("own"):
            add(Signal("site_falta", "site", "Na página inicial", f"Faltam {len(d.site_missing)} itens", "atencao", 0,
                       "Falta na página inicial: " + ", ".join(d.site_missing) + "."))
    ps = g(lead, "pagespeed_score")
    if ps is not None:
        add(Signal("pagespeed", "site", "PageSpeed (celular)", f"{ps}/100", "bom" if ps >= 90 else "atencao" if ps >= 50 else "ruim",
                   0, f"Nota {ps} de 100 no teste de velocidade do Google para celular."))

    # ---- contato
    phone = g(lead, "phone")
    d.has_phone = bool(phone_digits(phone))
    d.phone_kind = phone_type(phone) if d.has_phone else None
    if d.phone_kind == "mobile":
        add(Signal("contato", "contato", "Contato", "Celular", "bom", 20, "Tem celular: provavelmente atende pelo WhatsApp."))
        d.dims["contato"] = 100
    elif d.has_phone:
        add(Signal("contato", "contato", "Contato", "Telefone fixo", "atencao", 10,
                   "Só telefone fixo: o primeiro contato precisa ser por ligação."))
        d.dims["contato"] = 55
    else:
        txt = ("Sem telefone no cadastro: confira no Google Maps." if d.from_osm
               else "Sem telefone no perfil: não há contato direto.")
        add(Signal("contato", "contato", "Contato", "Sem telefone", "desconhecido" if d.from_osm else "ruim", 0, txt))
        d.dims["contato"] = None if d.from_osm else 0

    # ---- Google Meu Negócio e reputação
    if not d.google_known:
        add(Signal("google", "google", "Perfil no Google", "Não conferido", "desconhecido", 0,
                   "Veio do OpenStreetMap: confira o perfil no Google Maps (clique no nome) e marque o que viu."))
        add(Signal("reputacao", "reputacao", "Reputação", "Não conferida", "desconhecido", 10,
                   "O OpenStreetMap não traz nota nem avaliações."))
        d.dims["google"] = None
        d.dims["reputacao"] = None
        return d
    if d.on_google is False:
        add(Signal("google", "google", "Perfil no Google", "Não aparece", "ruim", 15,
                   "Você conferiu: o negócio não aparece no Google Maps."))
        add(Signal("reputacao", "reputacao", "Reputação", "Sem avaliações", "ruim", 4, "Sem perfil no Google não há avaliações."))
        d.dims["google"] = 0
        d.dims["reputacao"] = 0
        return d

    gpoints = 0
    gap = 0
    if photos >= MIN_PHOTOS:
        add(Signal("fotos", "google", "Fotos", str(photos), "bom", 0, f"{photos} fotos no perfil."))
        gpoints += 25
    else:
        add(Signal("fotos", "google", "Fotos", str(photos), "atencao", 4,
                   f"Só {photos} foto(s) no perfil: perfil com poucas fotos recebe menos cliques." if photos else
                   "Nenhuma foto no perfil do Google."))
        gap += 4
    if hours:
        add(Signal("horario", "google", "Horário", "Preenchido", "bom", 0, "Horário de funcionamento preenchido."))
        gpoints += 20
    else:
        add(Signal("horario", "google", "Horário", "Sem horário", "atencao", 4,
                   "Sem horário no perfil: o Google mostra 'horário não informado'."))
        gap += 4
    if d.has_phone:
        gpoints += 15
    if sstatus == "own":
        add(Signal("site_perfil", "google", "Site no perfil", "Ligado", "bom", 0, "O perfil aponta para um site próprio."))
        gpoints += 20
    else:
        add(Signal("site_perfil", "google", "Site no perfil", "Sem site próprio", "atencao", 3,
                   "O botão 'Site' do perfil não leva a um site próprio."))
        gap += 3
    if rating is not None:
        gpoints += 20

    # reputação
    strong = rating is not None and rating >= limits.min_rating and reviews >= limits.min_reviews
    d.reputation_strong = strong
    if rating is None:
        add(Signal("reputacao", "reputacao", "Reputação", "Sem nota", "atencao", 6,
                   "Ainda sem nota no Google: negócio novo ou perfil pouco usado."))
        d.dims["reputacao"] = 10
        vivo = 6
    else:
        volume = min(reviews / max(limits.min_reviews * 4, 1), 1.0)
        d.dims["reputacao"] = round(min(100, (rating / 5) * 60 + volume * 40))
        if strong:
            vivo = 10 + round(15 * volume)
            add(Signal("reputacao", "reputacao", "Reputação", f"{stars(rating)}★ · {reviews} avaliações", "bom", vivo,
                       f"Nota {stars(rating)} com {reviews} avaliações: negócio vivo e bem falado."))
        elif reviews < limits.min_reviews:
            vivo = 6 + round(4 * reviews / max(limits.min_reviews, 1))
            add(Signal("reputacao", "reputacao", "Reputação", f"{stars(rating)}★ · {reviews} avaliações", "atencao", vivo,
                       f"Poucas avaliações ({reviews}; o mínimo para {niche.plural} é {limits.min_reviews})."))
        else:
            vivo = 5
            add(Signal("reputacao", "reputacao", "Reputação", f"{stars(rating)}★ · {reviews} avaliações", "atencao", vivo,
                       f"Nota {stars(rating)}, abaixo de {stars(limits.min_rating)}."))
        if reviews < limits.min_reviews:
            add(Signal("poucas_avaliacoes", "google", "Avaliações", str(reviews), "atencao", 4,
                       f"Menos de {limits.min_reviews} avaliações: dá para crescer pedindo a cada cliente."))
            gap += 4
        elif rating < UPSELL_RATING:
            add(Signal("nota_baixa", "google", "Nota", stars(rating), "atencao", 3,
                       f"Nota {stars(rating)}: responder avaliações e pedir novas ajuda a subir."))
            gap += 3
    d.dims["google"] = min(100, gpoints)
    return d
