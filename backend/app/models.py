"""Tabelas da v3 (snake_case, em inglês). Datas em UTC sem fuso; a tela mostra Brasília."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Funil da v3 (seção 4.7), na ordem do kanban
STATUSES = ["NOVO", "ANALISADO", "AMOSTRA", "ABORDADO", "FOLLOWUP", "CONVERSA", "PROPOSTA", "FECHADO",
            "PRODUCAO", "ENTREGUE", "SEM_RESPOSTA", "PERDIDO", "DESCARTADO"]
STATUS_LABELS = {
    "NOVO": "Novo", "ANALISADO": "Analisado", "AMOSTRA": "Amostra pronta", "ABORDADO": "Abordado",
    "FOLLOWUP": "Follow-up", "CONVERSA": "Em conversa", "PROPOSTA": "Proposta enviada", "FECHADO": "Fechado",
    "PRODUCAO": "Em produção", "ENTREGUE": "Entregue", "SEM_RESPOSTA": "Sem resposta", "PERDIDO": "Perdido",
    "DESCARTADO": "Descartado",
}
# Mapa do protótipo -> v3 (usado pelo import-v1)
V1_STATUS_MAP = {
    "ACHADO": "NOVO", "QUALIFICADO": "ANALISADO", "SITE_GERADO": "AMOSTRA", "ABORDADO": "ABORDADO",
    "RESPONDEU": "CONVERSA", "PROPOSTA": "PROPOSTA", "FECHADO": "FECHADO", "SEM_RESPOSTA": "SEM_RESPOSTA",
    "PERDIDO": "PERDIDO", "DESCARTADO": "DESCARTADO",
}
PRE_SAMPLE = {"NOVO", "ANALISADO"}
PRE_CONTACT = {"NOVO", "ANALISADO", "AMOSTRA"}
WAITING_REPLY = {"ABORDADO", "FOLLOWUP"}
CONTACTED = {"ABORDADO", "FOLLOWUP", "CONVERSA", "PROPOSTA", "FECHADO", "PRODUCAO", "ENTREGUE", "SEM_RESPOSTA",
             "PERDIDO"}
WON = {"FECHADO", "PRODUCAO", "ENTREGUE"}
CLOSED_STAGES = {"ENTREGUE", "SEM_RESPOSTA", "PERDIDO", "DESCARTADO"}
SCORES = ["A", "B", "C", "DESCARTE"]
LOST_REASONS = {"preco": "Preço", "fornecedor": "Já tem fornecedor", "sem_interesse": "Sem interesse",
                "sem_retorno": "Sem retorno", "outro": "Outro"}
PROFILES = {
    "invisivel": ("Invisível", "👻"),
    "bem_avaliado_sem_site": ("Bem avaliado, sem site", "⭐"),
    "so_rede_social": ("Só rede social", "📱"),
    "preso_plataforma": ("Preso em plataforma", "🔗"),
    "site_datado": ("Site datado", "🕸️"),
    "bem_resolvido": ("Bem resolvido", "✅"),
}


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    niche: Mapped[str] = mapped_column(String(120))  # texto digitado
    niche_key: Mapped[str | None] = mapped_column(String(40))
    location_text: Mapped[str] = mapped_column(String(200))
    radius_m: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Float)  # pino do mapa, se houver
    lng: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(20), default="osm")
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)  # US$
    cached_from_id: Mapped[int | None] = mapped_column(Integer)  # busca repetida que veio do cache
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SearchJob(Base):
    """Fila de buscas em lote (bairros, linhas de texto ou pinos). Respeita a cota do dia."""

    __tablename__ = "search_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    niche: Mapped[str] = mapped_column(String(120))
    location_text: Mapped[str] = mapped_column(String(200))
    radius_m: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="pendente", index=True)  # pendente|feita|erro|cancelada
    search_id: Mapped[int | None] = mapped_column(ForeignKey("searches.id"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    niche: Mapped[str | None] = mapped_column(String(40), index=True)
    sector: Mapped[str | None] = mapped_column(String(40), index=True)
    address: Mapped[str | None] = mapped_column(String(300))
    neighborhood: Mapped[str | None] = mapped_column(String(120), index=True)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_type: Mapped[str | None] = mapped_column(String(10))  # mobile | landline
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    website_url: Mapped[str | None] = mapped_column(String(400))
    site_status: Mapped[str] = mapped_column(String(10), default="none", index=True)  # none|social|platform|own
    site_kind: Mapped[str] = mapped_column(String(16), default="none")  # + own_ok|own_nohttps|own_down|own_weak
    site_platform: Mapped[str | None] = mapped_column(String(60))
    site_check: Mapped[dict | None] = mapped_column(JSON)  # resultado da checagem/análise do site
    pagespeed_score: Mapped[int | None] = mapped_column(Integer)
    maps_url: Mapped[str | None] = mapped_column(String(400))
    rating: Mapped[float | None] = mapped_column(Float)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    opening_hours: Mapped[str | None] = mapped_column(Text)
    photos_count: Mapped[int] = mapped_column(Integer, default=0)
    business_status: Mapped[str | None] = mapped_column(String(30))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    gmb_check: Mapped[dict | None] = mapped_column(JSON)  # o que o Samuel conferiu no Maps (leads do OSM)

    # origem do dado (LGPD)
    source_provider: Mapped[str] = mapped_column(String(20), default="osm")
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    search_id: Mapped[int | None] = mapped_column(ForeignKey("searches.id"))

    # classificação
    score: Mapped[str | None] = mapped_column(String(10), index=True)
    score_reason: Mapped[str | None] = mapped_column(Text)
    score_auto: Mapped[str | None] = mapped_column(String(10))
    score_manual: Mapped[str | None] = mapped_column(String(10))
    profile: Mapped[str | None] = mapped_column(String(30), index=True)
    opportunity: Mapped[int] = mapped_column(Integer, default=0, index=True)
    rec_main: Mapped[str | None] = mapped_column(String(40), index=True)
    rec_keys: Mapped[str] = mapped_column(Text, default="")  # ",landing,manutencao," para filtrar com LIKE
    offered: Mapped[list] = mapped_column(JSON, default=list)  # serviços que o Samuel vai oferecer

    # funil
    status: Mapped[str] = mapped_column(String(20), default="NOVO", index=True)
    stage_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime)
    followup_step: Mapped[int] = mapped_column(Integer, default=0)  # follow-ups já marcados como enviados
    next_action: Mapped[str | None] = mapped_column(String(200))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    proposal_value: Mapped[float | None] = mapped_column(Float)
    recurring_value: Mapped[float | None] = mapped_column(Float)
    sold_services: Mapped[list] = mapped_column(JSON, default=list)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    tags: Mapped[str] = mapped_column(Text, default="")  # ",quente,indicacao,"
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    events: Mapped[list["LeadEvent"]] = relationship(
        back_populates="lead", order_by="LeadEvent.created_at.desc(), LeadEvent.id.desc()", cascade="all, delete-orphan")
    sites: Mapped[list["Site"]] = relationship(
        back_populates="lead", order_by="Site.created_at.desc(), Site.id.desc()", cascade="all, delete-orphan")
    drafts: Mapped[list["OutreachDraft"]] = relationship(
        back_populates="lead", order_by="OutreachDraft.created_at.desc(), OutreachDraft.id.desc()",
        cascade="all, delete-orphan")
    proposals: Mapped[list["Proposal"]] = relationship(
        back_populates="lead", order_by="Proposal.created_at.desc(), Proposal.id.desc()", cascade="all, delete-orphan")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def latest_site(self) -> "Site | None":
        return self.sites[0] if self.sites else None

    @property
    def tag_list(self) -> list[str]:
        return [t for t in (self.tags or "").split(",") if t]

    @property
    def rec_list(self) -> list[str]:
        return [t for t in (self.rec_keys or "").split(",") if t]

    @property
    def from_osm(self) -> bool:
        return (self.place_id or "").startswith("osm-")


class LeadEvent(Base):
    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))  # status|nota|abordagem|site|proposta|checagem|obs|import
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    lead: Mapped[Lead] = relationship(back_populates="events")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    template: Mapped[str] = mapped_column(String(50), default="landing")
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    preview_url: Mapped[str] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(20), default="preview")  # preview | publicado
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="sites")


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")  # whatsapp|instagram|email|ligacao
    kind: Mapped[str] = mapped_column(String(20), default="primeira")  # primeira|followup1|followup2|followup3
    text: Mapped[str] = mapped_column(Text)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)  # só o Samuel preenche ("Marquei como enviado")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="drafts")


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{key,name,price,recurring,deadline}]
    total: Mapped[float | None] = mapped_column(Float)
    monthly: Mapped[float | None] = mapped_column(Float)
    validity_days: Mapped[int] = mapped_column(Integer, default=7)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="proposals")


class Setting(Base):
    """Configurações editáveis na tela (franquias, meta, cadência, perfil do vendedor...)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ServiceOverride(Base):
    """O que o Samuel mudou num serviço pela tela (prevalece sobre services.yaml)."""

    __tablename__ = "service_overrides"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DeletionLog(Base):
    """LGPD: registro de que um lead foi excluído de vez, sem os dados dele."""

    __tablename__ = "deletion_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256: impede reimportar sem guardar o dado
    reason: Mapped[str | None] = mapped_column(String(200))
    source_provider: Mapped[str | None] = mapped_column(String(20))
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
