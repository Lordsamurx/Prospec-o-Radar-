"""Acessibilidade (axe, WCAG 2.1 AA) e layout: todas as telas, claro e escuro, desktop e celular."""
import httpx
import pytest

from conftest import THEMES, VIEWPORTS, axe_violations, overflowing

PAGES = ["/", "/leads", "/leads?view=mapa", "/buscas", "/funil", "/servicos", "/metricas", "/config", "/ajuda", "/sessao"]
SAMPLES = ["landing", "institucional", "cardapio", "agendamento", "links"]


def a_lead(base_url: str, **params) -> dict:
    return httpx.get(base_url + "/leads", params={"format": "json", **params}).json()["leads"][0]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("path", PAGES)
def test_tela_sem_violacao_de_acessibilidade(open_page, path, viewport, theme):
    page = open_page(path, viewport, theme)
    assert page.locator("html").get_attribute("data-theme") == theme
    assert axe_violations(page) == []
    assert page.errors == []


@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("path", PAGES)
def test_tela_nao_rola_para_o_lado(open_page, path, viewport):
    page = open_page(path, viewport)
    assert overflowing(page) == [], f"{path} tem conteúdo passando da largura da tela"


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
def test_drawer_acessivel(open_page, base_url, viewport, theme):
    lead = a_lead(base_url, site="sem", score="A")
    httpx.post(f"{base_url}/leads/{lead['id']}/site", params={"format": "json"})
    page = open_page(f"/leads/{lead['id']}", viewport, theme)
    page.locator("#dw-title").wait_for()
    page.get_by_role("button", name="Escrever rascunho").click()
    page.locator("#outreach-result textarea.msg").wait_for()
    assert axe_violations(page, "#drawer") == []
    assert overflowing(page, "#drawer-body") == []


@pytest.mark.parametrize("path_tpl", ["/leads/{id}/proposta", "/leads/{id}/diagnostico"])
def test_proposta_e_diagnostico_acessiveis(open_page, base_url, path_tpl):
    lead = a_lead(base_url, site="sem", score="A")
    page = open_page(path_tpl.format(id=lead["id"]), "desktop", "light")
    assert axe_violations(page) == []


@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("template", SAMPLES)
def test_amostra_acessivel_e_responsiva(open_page, base_url, template, viewport):
    lead = a_lead(base_url, site="sem")
    site = httpx.post(f"{base_url}/leads/{lead['id']}/site", params={"format": "json"}, json={"template": template}).json()
    page = open_page(site["local_url"], viewport)
    assert page.locator(".amostra").is_visible()
    assert axe_violations(page) == []
    over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1
    assert page.errors == []


@pytest.mark.parametrize("path", ["/", "/leads", "/funil"])
def test_alvos_de_toque_no_celular(open_page, path):
    """Botões e links de ação com pelo menos 24px (WCAG 2.2) no celular; os principais, 44px."""
    page = open_page(path, "celular")
    small = page.evaluate("""() => [...document.querySelectorAll('button, a.btn, .chip[href], input[type=checkbox]')]
        .filter(e => e.offsetParent !== null)
        .map(e => [e, e.getBoundingClientRect()])
        .filter(([e, r]) => r.width > 0 && (r.width < 24 || r.height < 24))
        .map(([e, r]) => (e.getAttribute('aria-label') || e.textContent.trim() || e.name).slice(0, 40) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height))""")
    assert small == []


def test_foco_visivel_e_pular_para_o_conteudo(open_page):
    page = open_page("/")
    page.keyboard.press("Tab")
    first = page.evaluate("document.activeElement.textContent.trim()")
    assert "conteúdo" in first.lower(), "o primeiro Tab é o link 'pular para o conteúdo'"
    page.keyboard.press("Tab")
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none"
