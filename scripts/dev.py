"""Atalhos da v3 (funcionam no Windows, sem make):

  python scripts/dev.py run                 sobe a app em http://localhost:8000
  python scripts/dev.py test [args]         testes de unidade e integração
  python scripts/dev.py e2e [args]          testes no navegador (Playwright) e acessibilidade
  python scripts/dev.py seed                põe os leads FICTÍCIOS de demonstração no banco
  python scripts/dev.py smoke               sobe a app num banco temporário e confere as telas
  python scripts/dev.py import-v1 [arquivo] importa o banco do protótipo (padrão: ../data/prospeccao.db)
  python scripts/dev.py backup              copia o banco agora para data/backups
  python scripts/dev.py publish             publica data/previews no Cloudflare Pages (precisa do wrangler)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def sh(*args: str, **env_extra: str) -> int:
    env = {**os.environ, "PYTHONPATH": str(BACKEND), **env_extra}
    return subprocess.call(list(args), cwd=ROOT, env=env)


def py_code(code: str, *args: str) -> int:
    return sh(sys.executable, "-c", code, *args)


def publish() -> int:
    """Publica as amostras (pasta data/previews) no Cloudflare Pages. Nada além das amostras sai do PC."""
    sys.path.insert(0, str(BACKEND))
    from app.config import get_settings

    s = get_settings()
    folder = s.previews_path
    if not folder.is_dir() or not any(p.is_dir() for p in folder.iterdir()):
        print("Nenhuma amostra para publicar. Gere uma amostra num lead primeiro.")
        return 1
    project = s.cloudflare_pages_project
    if not project:
        print("Falta CLOUDFLARE_PAGES_PROJECT no .env (o nome do projeto no Cloudflare Pages).\n"
              "Passo a passo: docs/v3/publicar-amostras.md")
        return 1
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("Não achei o npx. Instale o Node.js (nodejs.org) e rode de novo.")
        return 1
    # nenhuma amostra deve aparecer no Google
    (folder / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n", encoding="utf-8")
    (folder / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (folder / "index.html").write_text(
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="robots" content="noindex, nofollow">'
        "<title>Amostras</title><p>Amostras de demonstração.</p></html>", encoding="utf-8")
    print(f"Publicando {folder} no projeto {project}...")
    code = subprocess.call([npx, "wrangler", "pages", "deploy", str(folder), "--project-name", project,
                            "--branch", "main", "--commit-dirty=true"], cwd=ROOT)
    if code == 0 and not s.previews_public_url:
        print(f"Pronto. Agora preencha no .env: PREVIEWS_PUBLIC_URL=https://{project}.pages.dev  e reinicie a app.")
    return code


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    rest = sys.argv[2:]
    py = sys.executable
    if cmd == "run":
        host = os.environ.get("HOST", "127.0.0.1")
        return sh(py, "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND), "--host", host,
                  "--port", os.environ.get("PORT", "8000"), "--reload", "--reload-dir", str(BACKEND))
    if cmd == "test":
        return sh(py, "-m", "pytest", "-q", str(BACKEND / "tests"), "--ignore", str(BACKEND / "tests" / "e2e"), *rest)
    if cmd == "e2e":
        return sh(py, "-m", "pytest", "-q", str(BACKEND / "tests" / "e2e"), *rest)
    if cmd == "seed":
        return sh(py, "-m", "app.seed")
    if cmd == "smoke":
        return sh(py, str(ROOT / "scripts" / "smoke.py"))
    if cmd == "import-v1":
        src = rest[0] if rest else str(ROOT.parent / "data" / "prospeccao.db")
        return py_code(
            "import sys, json\n"
            "from pathlib import Path\n"
            "from app.config import get_settings\n"
            "from app.db import init_engine, new_session\n"
            "from app.services import app_settings, importer\n"
            "init_engine(); db = new_session(); s = get_settings(); src = Path(sys.argv[1])\n"
            "stats = importer.import_v1(db, app_settings.load_ctx(db), src, src.parent / 'previews', s.previews_path, s.base_url)\n"
            "print('Importação concluída:', json.dumps(stats, ensure_ascii=False))\n", src)
    if cmd == "backup":
        return py_code(
            "from app.config import get_settings\n"
            "from app.services import backup\n"
            "s = get_settings(); d = backup.backup_now(s.database_path, s.backups_path, 'manual')\n"
            "print('Backup salvo em', d) if d else print('Sem banco para copiar ainda.')\n")
    if cmd == "publish":
        return publish()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
