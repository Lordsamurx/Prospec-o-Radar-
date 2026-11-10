"""Sobe o servidor de verdade num banco temporário (dados fictícios) e confere as telas principais."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = os.environ.get("SMOKE_PORT", "8765")
BASE = f"http://127.0.0.1:{PORT}"
tmp = Path(tempfile.mkdtemp(prefix="radar-smoke-"))
env = {
    **os.environ,
    "PYTHONPATH": str(ROOT / "backend"),
    "DATABASE_URL": f"sqlite:///{(tmp / 'smoke.db').as_posix()}",
    "PREVIEWS_DIR": str(tmp / "previews"),
    "BACKUPS_DIR": str(tmp / "backups"),
    "PLACES_PROVIDER": "mock",
    "APP_PASSWORD": "",
    "RADAR_NO_PARENT_ENV": "1",
}
subprocess.check_call([sys.executable, "-m", "app.seed"], cwd=ROOT, env=env)
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
                         "--port", PORT, "--log-level", "warning"], cwd=ROOT, env=env)
ok = True
try:
    for _ in range(60):
        try:
            httpx.get(f"{BASE}/health", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.25)
    r = httpx.get(f"{BASE}/health", timeout=5)
    print("GET /health ->", r.status_code, r.json())
    ok &= r.status_code == 200 and r.json()["status"] == "ok"
    for path in ("/", "/leads", "/leads?view=mapa", "/buscas", "/funil", "/servicos", "/metricas", "/config", "/ajuda",
                 "/sessao"):
        resp = httpx.get(BASE + path, timeout=10)
        print(f"GET {path} -> {resp.status_code} ({len(resp.text)} bytes)")
        ok &= resp.status_code == 200 and "Radar" in resp.text
    j = httpx.get(f"{BASE}/leads?format=json&site=sem&score=A", timeout=10)
    print("GET /leads?format=json&site=sem&score=A ->", j.status_code, "total", j.json()["total"])
    ok &= j.status_code == 200 and j.json()["total"] > 0
    lead_id = j.json()["leads"][0]["id"]
    s = httpx.post(f"{BASE}/leads/{lead_id}/site?format=json", timeout=10)
    print("POST /leads/{id}/site ->", s.status_code, s.json().get("local_url"))
    p = httpx.get(BASE + s.json()["local_url"], timeout=10)
    print("GET amostra ->", p.status_code, "noindex" in p.text)
    ok &= s.status_code == 200 and p.status_code == 200 and "noindex" in p.text
    print("SMOKE OK" if ok else "SMOKE FALHOU")
    sys.exit(0 if ok else 1)
finally:
    proc.terminate()
    proc.wait(timeout=10)
