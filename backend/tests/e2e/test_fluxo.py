"""Fluxo principal no navegador: busca -> lista -> drawer -> serviços -> amostra -> mensagem copiada -> kanban."""
import re

import httpx
import pytest

from conftest import VIEWPORTS


def fresh_lead(base_url: str) -> dict:
    r = httpx.get(base_url + "/leads", params={"format": "json", "site": "sem", "score": "A", "status": "ANALISADO"})
    return r.json()["leads"][0]


@pytest.mark.parametrize("viewport", list(VIEWPORTS))
def test_fluxo_completo(open_page, base_url, viewport):
    # 1. busca
    page = open_page("/buscas", viewport)
    page.fill("#search-niche", "barbearia")
    page.fill("#search-loc", "Belo Horizonte")
    page.get_by_role("button", name="Buscar", exact=True).click()
    result = page.locator("#search-result")
    result.get_by_text(re.compile(r"\d+ negócios? de Barbearia")).wait_for()
    assert "Dados fictícios" in result.inner_text()

    # 2. lista
    lead = fresh_lead(base_url)
    page.goto(f"{base_url}/leads?site=sem&score=A&status=ANALISADO")
    row_btn = page.locator(f'[data-open-lead="{lead["id"]}"]').first
    row_btn.scroll_into_view_if_needed()
    row_btn.click()

    # 3. drawer com diagnóstico e serviços sugeridos
    drawer = page.locator("#drawer")
    drawer.locator("#dw-title").wait_for()
    assert drawer.locator("#dw-title").inner_text() == lead["name"]
    assert drawer.get_by_role("heading", name="O que oferecer").is_visible()
    assert drawer.locator("#dw-h-rec ~ form .rec, section:has(#dw-h-rec) .rec").count() >= 1
    assert drawer.get_by_role("heading", name="Raio-X").count() == 1

    # 4. amostra
    drawer.get_by_role("button", name="Gerar amostra de site").click()
    page.locator("#site-result").get_by_text("Amostra pronta").wait_for()
    assert "Amostra pronta" in page.locator("#dw-status").inner_text()
    link = page.locator("#site-link").inner_text()
    sample = httpx.get(link)
    assert sample.status_code == 200 and "noindex" in sample.text and lead["name"] in sample.text.replace("&amp;", "&")

    # 5. mensagem: escrever, copiar e marcar como enviada (a app nunca envia)
    drawer.get_by_role("button", name="Escrever rascunho").click()
    box = page.locator("#outreach-result textarea.msg")
    box.wait_for()
    text = box.input_value()
    assert lead["name"] in text and link in text
    assert drawer.get_by_role("button", name="Enviar", exact=True).count() == 0
    page.locator("#outreach-result").get_by_role("button", name="Copiar").click()
    assert page.evaluate("navigator.clipboard.readText()") == text
    page.locator("#outreach-result").get_by_role("button", name="Marquei como enviado").click()
    page.locator("#dw-status", has_text="Abordado").wait_for()

    # 6. kanban
    page.goto(base_url + "/funil")
    card = page.locator(f'.kcol[data-status="ABORDADO"] .kcard[data-id="{lead["id"]}"]')
    assert card.count() == 1
    assert page.errors == []


def test_etapa_perdido_pede_motivo(open_page, base_url):
    lead = fresh_lead(base_url)
    page = open_page(f"/leads/{lead['id']}")
    page.locator("#dw-title").wait_for()
    page.select_option("#dw-stage", "PERDIDO")
    dialog = page.locator("#stage-dialog")
    dialog.wait_for(state="visible")
    page.select_option("#stage-reason", "preco")
    dialog.get_by_role("button", name="Salvar etapa").click()
    page.locator("#dw-status", has_text="Perdido").wait_for()
    d = httpx.get(f"{base_url}/leads/{lead['id']}", params={"format": "json"}).json()
    assert d["status"] == "PERDIDO" and "Preço" in d["events"][0]["note"]


def test_tema_claro_e_escuro_fica_guardado(open_page):
    page = open_page("/", theme="dark")
    html = page.locator("html")
    assert html.get_attribute("data-theme") == "dark"
    dark_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.locator("[data-theme-toggle]").click()
    assert html.get_attribute("data-theme") == "light"
    page.wait_for_function("bg => getComputedStyle(document.body).backgroundColor !== bg", arg=dark_bg)
    assert page.evaluate('localStorage.getItem("radar-theme")') == "light"


def test_teclado_lista_drawer_e_paleta(open_page):
    page = open_page("/leads")
    page.keyboard.press("j")
    page.keyboard.press("Enter")
    page.locator("#dw-title").wait_for()
    page.wait_for_function("document.getElementById('drawer').contains(document.activeElement)")  # foco entra no painel
    page.keyboard.press("Escape")
    page.locator("#drawer.on").wait_for(state="detached")
    assert page.evaluate("!document.getElementById('drawer').contains(document.activeElement)"), "foco volta para a lista"
    page.keyboard.press("Control+k")
    page.locator("#palette[open]").wait_for()
    page.keyboard.type("funil")
    page.locator("#palette-list li").first.wait_for()
    page.keyboard.press("Enter")
    page.wait_for_url("**/funil")
    assert page.errors == []


def test_filtros_atualizam_sem_recarregar(open_page):
    page = open_page("/leads")
    before = page.locator("[data-open-lead]").count()
    page.goto(page.url + "?site=sem")
    after = page.locator("[data-open-lead]").count()
    assert 0 < after < before


def test_selecao_em_lote_pelo_navegador(open_page, base_url):
    page = open_page("/leads?site=sem")
    boxes = page.locator('#results input[type="checkbox"][name="ids"]')
    boxes.nth(0).check()
    boxes.nth(1).check()
    bar = page.locator("#bulk")
    bar.wait_for(state="visible")
    assert "2" in bar.inner_text()
