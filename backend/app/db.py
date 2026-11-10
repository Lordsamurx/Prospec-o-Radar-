"""Engine, sessão e migrações versionadas (SQLite).

Migração própria e simples: a tabela schema_migrations guarda as versões aplicadas.
Banco novo nasce na versão atual (create_all) e é carimbado; banco antigo recebe só o que falta.
Nunca apaga coluna nem tabela: o banco do Samuel não perde dados.
"""
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _add_column(conn: Connection, table: str, column: str, ddl: str) -> None:
    cols = {c["name"] for c in inspect(conn).get_columns(table)}
    if column not in cols:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _m2_site_pagespeed(conn: Connection) -> None:
    _add_column(conn, "leads", "pagespeed_score", "INTEGER")


# (versão, nome, função). A 1 é a linha de base criada por create_all.
MIGRATIONS: list[tuple[int, str, Callable[[Connection], None] | None]] = [
    (1, "linha de base da v3", None),
    (2, "leads.pagespeed_score", _m2_site_pagespeed),
]


def migrate(engine: Engine) -> list[int]:
    """Aplica o que falta e devolve as versões aplicadas agora."""
    applied_now: list[int] = []
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"))
        done = {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}
        fresh = not done and not inspect(conn).has_table("leads")
    from . import models  # noqa: F401  registra as tabelas

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for version, name, fn in MIGRATIONS:
            if version in done:
                continue
            if fn is not None and not fresh:
                fn(conn)
            conn.execute(text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (:v, :n, :t)"),
                         {"v": version, "n": name, "t": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            applied_now.append(version)
    return applied_now


def init_engine(url: str | None = None) -> Engine:
    """Cria (ou recria) o engine. Os testes chamam com um banco temporário."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    url = url or get_settings().resolved_database_url
    _engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(_engine, "connect")
    def _pragmas(dbapi_conn, _):  # pragma: no cover - detalhe do SQLite
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    migrate(_engine)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def new_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
    finally:
        db.close()
