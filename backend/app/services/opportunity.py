"""Índice de oportunidade 0–100 (seção 4.3, camada 3). Função pura, com detalhamento.

Quanto mais falta presença digital e mais vivo o negócio, maior; mais a facilidade de contato.
Serve para ordenar a lista dentro da mesma nota.
"""
from dataclasses import dataclass

from .diagnose import Diagnostico

CAPS = {"site": 40, "vida": 25, "contato": 20, "google": 15}


@dataclass(frozen=True)
class Parcel:
    key: str
    label: str
    points: int
    cap: int
    why: str


def opportunity(d: Diagnostico, do_not_contact: bool = False) -> tuple[int, list[Parcel]]:
    site = d.signal("site")
    rep = d.signal("reputacao")
    contato = d.signal("contato")
    site_pts = min(CAPS["site"], site.weight if site else 0)
    vida_pts = min(CAPS["vida"], rep.weight if rep else 0)
    contato_pts = min(CAPS["contato"], contato.weight if contato else 0)
    gaps = [s for s in d.by_dimension("google") if s.weight and s.key != "google"]
    g_extra = d.signal("google")
    google_pts = min(CAPS["google"], sum(s.weight for s in gaps) + (g_extra.weight if g_extra else 0))
    parts = [
        Parcel("site", "Falta de site", site_pts, CAPS["site"], site.phrase if site else ""),
        Parcel("vida", "Negócio vivo", vida_pts, CAPS["vida"], rep.phrase if rep else ""),
        Parcel("contato", "Facilidade de contato", contato_pts, CAPS["contato"], contato.phrase if contato else ""),
        Parcel("google", "Melhorias no Google", google_pts, CAPS["google"],
               "; ".join(s.label.lower() for s in gaps) or "Sem pontos fracos conhecidos no perfil."),
    ]
    total = sum(p.points for p in parts)
    if do_not_contact or not d.is_open or d.out_of_niche:
        motivo = "Não contatar." if do_not_contact else "Fechado." if not d.is_open else "Fora do nicho."
        return 0, parts + [Parcel("zerado", "Zerado", -total, 0, motivo)]
    if d.is_franchise:
        cut = total - round(total * 0.4)
        parts.append(Parcel("franquia", "Franquia ou rede", -cut, 0, "A decisão não é do dono local."))
        total -= cut
    return max(0, min(100, total)), parts
