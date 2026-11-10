"""Filtros da lista de leads (docs/09 + v3). Função pura: recebe filtros, devolve a query.

Não faz HTTP nem abre sessão; quem executa é o router (ou o teste).
"""
from datetime import datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import Select, and_, case, func, not_, or_, select

from .. import catalog
from ..models import PROFILES, STATUS_LABELS, WAITING_REPLY, Lead
from ..schemas import FilterParams
from . import geo
from .timeutil import utcnow

SCORE_ORDER = case((Lead.score == "A", 0), (Lead.score == "B", 1), (Lead.score == "C", 2), else_=3)
NO_SITE = ("none", "social", "platform")


def build_query(f: FilterParams, franchise_names: list[str] | None = None,
                default_center: tuple[float, float] = (-19.9191, -43.9386), now: datetime | None = None,
                center: tuple[float, float] | None = None, stale_days: int = 30) -> Select:
    """`center` (opcional) substitui o centro do raio; o router manda a média dos leads
    do bairro quando ele não está na tabela de bairros."""
    now = now or utcnow()
    conds = [Lead.do_not_contact.is_(False)]  # não contatar: sempre escondido
    if not f.show_archived:
        conds.append(Lead.archived.is_(False))
    if not f.show_mock:
        conds.append(Lead.is_mock.is_(False))  # fictícios escondidos por padrão

    if f.niche:
        conds.append(Lead.niche.in_(f.niche))
    if f.sector:
        conds.append(Lead.sector.in_(f.sector))

    if f.city:
        conds.append(func.lower(Lead.city) == f.city.strip().lower())
    if f.radius_km:
        if center:
            lat, lng = center
        elif f.neighborhood and geo.known(f.neighborhood):
            lat, lng = geo.center_of(geo.find_in_text(f.neighborhood)[0])
        else:
            lat, lng = default_center
        lat0, lat1, lng0, lng1 = geo.bounding_box(lat, lng, f.radius_km)
        conds += [Lead.lat.between(lat0, lat1), Lead.lng.between(lng0, lng1)]
    elif f.neighborhood:
        conds.append(func.lower(Lead.neighborhood) == f.neighborhood.strip().lower())

    if f.site == "sem":
        conds.append(Lead.site_status.in_(NO_SITE))
    elif f.site == "com":
        conds.append(Lead.site_status == "own")
    if f.site_status:
        conds.append(Lead.site_status.in_(f.site_status))

    if f.min_rating is not None:
        conds.append(Lead.rating >= f.min_rating)
    if f.min_reviews is not None:
        conds.append(Lead.reviews_count >= f.min_reviews)
    if f.max_reviews is not None:
        conds.append(Lead.reviews_count <= f.max_reviews)

    if f.has_phone == "yes":
        conds.append(and_(Lead.phone.is_not(None), Lead.phone != ""))
    elif f.has_phone == "no":
        conds.append(or_(Lead.phone.is_(None), Lead.phone == ""))
    if f.phone_type:
        conds.append(Lead.phone_type == f.phone_type)

    if f.operational_only:
        conds.append(Lead.business_status == "OPERATIONAL")
    if f.min_photos is not None:
        conds.append(Lead.photos_count >= f.min_photos)
    if f.has_hours == "yes":
        conds.append(and_(Lead.opening_hours.is_not(None), Lead.opening_hours != ""))
    elif f.has_hours == "no":
        conds.append(or_(Lead.opening_hours.is_(None), Lead.opening_hours == ""))

    if f.status:
        conds.append(Lead.status.in_([s.upper() for s in f.status]))
    if f.never_contacted:
        conds.append(Lead.contacted_at.is_(None))
    if f.no_reply_days is not None:
        cutoff = now - timedelta(days=f.no_reply_days)
        conds += [Lead.status.in_([*WAITING_REPLY, "SEM_RESPOSTA"]), Lead.contacted_at <= cutoff]
    if f.overdue:
        conds += [Lead.next_action_at.is_not(None), Lead.next_action_at <= now]

    if f.score:
        conds.append(Lead.score.in_(f.score))
    if f.profile:
        conds.append(Lead.profile.in_(f.profile))
    if f.service:
        conds.append(or_(*[Lead.rec_keys.like(f"%,{k},%") for k in f.service]))
    if f.tag:
        conds.append(or_(*[Lead.tags.like(f"%,{t.lower()},%") for t in f.tag]))
    if f.stale:
        conds += [Lead.source_provider == "google", Lead.fetched_at < now - timedelta(days=stale_days)]

    if f.hide_franchises and franchise_names:
        for name in franchise_names:
            conds.append(not_(func.lower(Lead.name).contains(name.lower())))

    if f.q:
        like = f"%{f.q.strip().lower()}%"
        conds.append(or_(func.lower(Lead.name).like(like), func.lower(Lead.neighborhood).like(like),
                         Lead.tags.like(like), func.lower(Lead.notes).like(like)))

    q = select(Lead).where(and_(*conds))
    order = {
        "score": [SCORE_ORDER, Lead.opportunity.desc(), Lead.reviews_count.desc()],
        "opportunity": [Lead.opportunity.desc(), SCORE_ORDER],
        "reviews": [Lead.reviews_count.desc()],
        "rating": [Lead.rating.desc().nulls_last(), Lead.reviews_count.desc()],
        "newest": [Lead.created_at.desc(), Lead.id.desc()],
        "next_action": [Lead.next_action_at.asc().nulls_last(), SCORE_ORDER],
    }[f.sort]
    return q.order_by(*order, Lead.id)


def count_query(q: Select) -> Select:
    return select(func.count()).select_from(q.order_by(None).subquery())


LABELS = {
    "niche": "Nicho", "sector": "Setor", "city": "Cidade", "neighborhood": "Bairro", "radius_km": "Raio",
    "site": "Site", "site_status": "Site", "min_rating": "Nota ≥", "min_reviews": "Avaliações ≥",
    "max_reviews": "Avaliações ≤", "has_phone": "Telefone", "phone_type": "Número",
    "operational_only": "Só funcionando", "min_photos": "Fotos ≥", "has_hours": "Horário", "status": "Etapa",
    "never_contacted": "Nunca abordado", "no_reply_days": "Sem resposta há", "score": "Nota do lead",
    "profile": "Perfil", "service": "Serviço recomendado", "tag": "Tag", "hide_franchises": "Sem franquias",
    "show_mock": "Mostrando fictícios", "show_archived": "Mostrando arquivados", "stale": "Dados desatualizados",
    "overdue": "Ação vencida", "q": "Busca",
}
VALUE_LABELS = {"none": "sem site", "social": "só rede social", "platform": "plataforma", "own": "site próprio",
                "mobile": "celular", "landline": "fixo", "yes": "tem", "no": "não tem", "sem": "sem site",
                "com": "com site"}
BAR_KEYS = ("niche", "site", "score")  # ficam na barra principal; o resto vai em "Mais filtros"


def chips(f: FilterParams, services: dict | None = None) -> list[dict]:
    """Um chip por valor ativo, com a querystring que o remove."""
    cat = catalog.niches()
    items = f.to_query()
    out = []
    for i, (key, value) in enumerate(items):
        if key == "sort":
            continue
        rest = items[:i] + items[i + 1:]
        if key in FilterParams.BOOL_FIELDS:
            text = LABELS[key]
        else:
            if key == "niche":
                shown = cat.label(value)
            elif key == "sector":
                shown = cat.sector_by_key[value].label if value in cat.sector_by_key else value
            elif key == "profile":
                shown = PROFILES.get(value, (value,))[0]
            elif key == "service":
                shown = services[value].name if services and value in services else value
            elif key == "status":
                shown = STATUS_LABELS.get(value.upper(), value)
            elif key == "radius_km":
                shown = f"{value} km"
            elif key == "no_reply_days":
                shown = f"{value} dias"
            else:
                shown = VALUE_LABELS.get(value, value)
            text = f"{LABELS.get(key, key)}: {shown}"
        out.append({"key": key, "value": value, "label": text, "remove_qs": urlencode(rest)})
    return out
