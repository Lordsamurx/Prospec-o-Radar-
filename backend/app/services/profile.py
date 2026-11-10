"""Perfil digital do lead (seção 4.3, camada 2): um rótulo com motivo. Função pura."""
from .diagnose import Diagnostico

ORDER = ["bem_avaliado_sem_site", "invisivel", "so_rede_social", "preso_plataforma", "site_datado", "bem_resolvido"]
COLORS = {
    "invisivel": "muted", "bem_avaliado_sem_site": "accent", "so_rede_social": "pink",
    "preso_plataforma": "orange", "site_datado": "yellow", "bem_resolvido": "blue",
}


def profile(d: Diagnostico) -> tuple[str, str]:
    """(chave, motivo)."""
    k = d.site_kind
    if k == "own_ok":
        return "bem_resolvido", "Site e presença em ordem: a venda aqui é melhoria (avaliações, SEO local, conteúdo)."
    if k in ("own_nohttps", "own_down", "own_weak"):
        return "site_datado", "Tem site próprio, mas fraco: " + (" ".join(d.site_issues) or "precisa de reforma.")
    if k == "platform":
        return "preso_plataforma", f"A presença dele é uma página no {d.platform or 'serviço de terceiros'}."
    if k == "social":
        return "so_rede_social", f"Depende de {d.platform or 'rede social'} para ser encontrado."
    if d.reputation_strong:
        return "bem_avaliado_sem_site", "Google forte e nenhum site: reputação pronta, falta a vitrine."
    if not d.google_known:
        return "invisivel", "Sem site e sem dados do Google ainda (confira no Maps)."
    return "invisivel", "Sem site e com Google fraco ou inexistente."
