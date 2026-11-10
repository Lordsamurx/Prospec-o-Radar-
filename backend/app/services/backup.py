"""Backup do banco SQLite: um clique, ao iniciar e uma vez por dia; guarda os últimos 7 automáticos."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .timeutil import to_local, utcnow

KEEP_AUTO = 7
KEEP_MANUAL = 30


def backup_now(db_path: Path | None, backups_dir: Path, kind: str = "manual", now: datetime | None = None) -> Path | None:
    """Copia o banco com a API de backup do SQLite (segura com o app aberto)."""
    if db_path is None or not db_path.is_file():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = to_local(now or utcnow()).strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"radar-{kind}-{stamp}.db"
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    prune(backups_dir)
    return dest


def list_backups(backups_dir: Path) -> list[dict]:
    if not backups_dir.is_dir():
        return []
    out = []
    for p in sorted(backups_dir.glob("radar-*.db"), key=lambda x: x.stat().st_mtime, reverse=True):
        out.append({"name": p.name, "kind": "auto" if "-auto-" in p.name else "manual", "size_kb": round(p.stat().st_size / 1024),
                    "at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).replace(tzinfo=None)})
    return out


def prune(backups_dir: Path) -> None:
    """Mantém os 7 automáticos e os 30 manuais mais novos. Os mais antigos passam por backups/_lixeira (últimos 20) antes de sair de vez."""
    for kind, keep in (("auto", KEEP_AUTO), ("manual", KEEP_MANUAL)):
        files = sorted(backups_dir.glob(f"radar-{kind}-*.db"), key=lambda x: x.name, reverse=True)
        for old in files[keep:]:
            trash = backups_dir / "_lixeira"
            trash.mkdir(exist_ok=True)
            for stale in sorted(trash.glob("radar-*.db"), key=lambda x: x.name, reverse=True)[20:]:
                stale.unlink(missing_ok=True)
            old.replace(trash / old.name)


def auto_backup_due(backups_dir: Path, now: datetime | None = None) -> bool:
    now = now or utcnow()
    autos = [b for b in list_backups(backups_dir) if b["kind"] == "auto"]
    return not autos or autos[0]["at"] < now - timedelta(hours=24)
