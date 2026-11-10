"""Testes no navegador (Playwright) e de acessibilidade (axe).

Rodar: python scripts/dev.py e2e
Precisa de: pip install playwright && python -m playwright install chromium
Sobe a app de verdade num banco temporário com dados FICTÍCIOS. Nenhuma chamada externa.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pw = pytest.importorskip("playwright.sync_api", reason="instale o playwright para rodar os testes no navegador")

ROOT = Path(__file__).resolve().parents[3]
AXE = (Path(__file__).resolve().parents[1] / "vendor" / "axe.min.js").read_text(encoding="utf-8")
VIEWPORTS = {"desktop": {"width": 1366, "height": 800}, "celular": {"width": 390, "height": 844}}
THEMES = ("dark", "light")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url(tmp_path_factory) -> str:
    tmp = tmp_path_factory.mktemp("radar-e2e")
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "RADAR_NO_PARENT_ENV": "1",
           "DATABASE_URL": f"sqlite:///{(tmp / 'e2e.db').as_posix()}", "PREVIEWS_DIR": str(tmp / "previews"),
           "BACKUPS_DIR": str(tmp / "backups"), "PLACES_PROVIDER": "mock", "APP_PASSWORD": "",
           "BASE_URL": f"http://127.0.0.1:{port}", "PREVIEWS_PUBLIC_URL": "", "GOOGLE_MAPS_API_KEY": "",
           "GEMINI_API_KEY": "", "GROQ_API_KEY": ""}
    subprocess.check_call([sys.executable, "-m", "app.seed"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
                             "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                if httpx.get(url + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise RuntimeError("a app não subiu para os testes no navegador")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with pw.sync_playwright() as p:
        exe = os.environ.get("RADAR_CHROMIUM") or None  # caminho de um Chromium já instalado, se quiser
        b = p.chromium.launch(executable_path=exe)
        yield b
        b.close()


@pytest.fixture()
def open_page(browser, base_url):
    """open_page(caminho, tela, tema) -> página pronta, sem depender de rede externa."""
    contexts = []

    def _open(path: str = "/", viewport: str = "desktop", theme: str = "dark"):
        ctx = browser.new_context(viewport=VIEWPORTS[viewport], locale="pt-BR", has_touch=viewport == "celular",
                                  is_mobile=viewport == "celular", permissions=["clipboard-read", "clipboard-write"],
                                  reduced_motion="reduce")
        contexts.append(ctx)
        ctx.add_init_script(f'try{{localStorage.setItem("radar-theme","{theme}")}}catch(e){{}}')
        # mapa: os blocos de imagem vêm de fora; nos testes ficam bloqueados (nada sai da máquina)
        ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base_url)
                  or route.request.url.startswith(("data:", "blob:")) else route.abort())
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(base_url + path)
        page.wait_for_load_state("networkidle")
        return page

    yield _open
    for c in contexts:
        c.close()


def axe_violations(page, context: str | None = None) -> list[str]:
    """Roda o axe (WCAG 2.1 A e AA) e devolve as violações em texto curto."""
    page.evaluate(AXE)
    result = page.evaluate(
        """async (sel) => await axe.run(sel || document, {runOnly: {type: "tag",
              values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}})""", context)
    out = []
    for v in result["violations"]:
        nodes = "; ".join(n["target"][0] if isinstance(n["target"][0], str) else str(n["target"][0]) for n in v["nodes"][:4])
        detail = v["nodes"][0].get("failureSummary", "").replace("\n", " ")[:200]
        out.append(f"{v['id']} ({v['impact']}): {nodes} :: {detail}")
    return out


def overflowing(page, root: str = "body") -> list[str]:
    """Elementos que passam da largura da tela sem estar dentro de uma área com rolagem própria."""
    return page.evaluate("""(root) => {
      const vw = document.documentElement.clientWidth, out = [];
      const base = document.querySelector(root);
      const limit = root === "body" ? vw : base.getBoundingClientRect().right;
      for (const e of base.querySelectorAll("*")) {
        const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
        if (r.width <= 1 || r.right <= limit + 1 || cs.position === "fixed" || cs.visibility === "hidden") continue;
        let a = e.parentElement, inside = false;
        while (a && a !== base) {
          const s = getComputedStyle(a);
          if (s.overflowX !== "visible" || s.position === "fixed") { inside = true; break; }
          a = a.parentElement;
        }
        if (!inside) out.push(e.tagName.toLowerCase() + "." + String(e.className).split(" ")[0] + " até " + Math.round(r.right) + "px");
      }
      return out.slice(0, 6);
    }""", root)
