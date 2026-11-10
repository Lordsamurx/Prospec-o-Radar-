"""App FastAPI da v3 "Radar". Rodar: python scripts/dev.py run."""
import base64
import json
import logging
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import catalog
from .config import APP_DIR, get_settings
from .db import get_db, init_engine
from .models import Lead
from .routers import funnel, leads, outreach, proposals, search, services, sites, today
from .routers import settings as settings_router
from .services import backup
from .web import is_htmx, render, wants_json

log = logging.getLogger("radar")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    catalog.niches()  # valida os catálogos ao iniciar: erro de cadastro aparece já
    init_engine()
    s.previews_path.mkdir(parents=True, exist_ok=True)
    if s.auto_backup and s.database_path is not None:
        try:  # backup automático ao iniciar (guarda os últimos 7)
            backup.backup_now(s.database_path, s.backups_path, "auto")
        except Exception:  # backup nunca impede a app de subir
            log.warning("Backup automático falhou.", exc_info=True)
    yield


app = FastAPI(title="Radar · Prospecção de Clientes", version="3.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
for r in (today.router, search.router, leads.router, funnel.router, services.router, sites.router, outreach.router,
          proposals.router, settings_router.router):
    app.include_router(r)

# Caminhos abertos mesmo com senha: o teste de saúde da hospedagem e as amostras de site,
# que vão no link da mensagem para o dono do negócio ver.
PUBLIC_PREFIXES = ("/health", "/previews/")
UNSAFE = ("POST", "PATCH", "PUT", "DELETE")


def _password_ok(header: str | None, user: str, password: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        got_user, _, got_pass = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except Exception:
        return False
    return secrets.compare_digest(got_user.encode(), user.encode()) and secrets.compare_digest(
        got_pass.encode(), password.encode())


@app.middleware("http")
async def security(request: Request, call_next):
    """Senha (se APP_PASSWORD estiver preenchida), proteção CSRF e cabeçalhos de segurança."""
    settings = get_settings()
    password = settings.app_password.get_secret_value()
    path = request.url.path
    public = path == "/health" or path.startswith("/previews/")
    if password and not public:
        if not _password_ok(request.headers.get("authorization"), settings.app_user, password):
            return Response("Acesso restrito.", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Radar", charset="UTF-8"'})
    if request.method in UNSAFE:
        origin = request.headers.get("origin")
        if (origin and urlparse(origin).netloc != request.headers.get("host")) or \
                request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not path.startswith("/previews/"):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if password or path.startswith("/previews/"):
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if wants_json(request) or is_htmx(request) or request.method != "GET":
        headers = ({"HX-Trigger": json.dumps({"toast-error": str(exc.detail)}), "HX-Reswap": "none"}
                   if is_htmx(request) else None)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)
    from .db import new_session

    db = new_session()
    try:
        return render(request, "error.html", {"code": exc.status_code, "message": exc.detail}, exc.status_code, db=db)
    finally:
        db.close()


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "Dados inválidos."}, status_code=422)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": app.version, "provider": get_settings().places_provider,
            "leads": db.scalar(select(func.count()).select_from(Lead)) or 0}


@app.get("/funnel", include_in_schema=False)
def old_funnel():
    return RedirectResponse("/funil", status_code=307)
