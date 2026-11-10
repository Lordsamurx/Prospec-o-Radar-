"""Telefone, site, CSV e tags."""
import pytest

from app.services import normalize as n


@pytest.mark.parametrize("raw,kind", [("(31) 98888-1111", "mobile"), ("+55 31 98888-1111", "mobile"),
                                      ("31 3222-1111", "landline"), ("0800 123 4567", None), ("", None),
                                      (None, None), ("abc", None)])
def test_phone_type(raw, kind):
    assert n.phone_type(raw) == kind


def test_phone_digits_drops_country_code_and_formats():
    assert n.phone_digits("+55 (31) 98888-1111") == "31988881111"
    assert n.format_phone("31988881111") == "(31) 98888-1111"


def test_whatsapp_link_only_for_mobile_and_encodes_text():
    assert n.whatsapp_link("(31) 3222-1111") is None
    link = n.whatsapp_link("(31) 98888-1111", "Olá, tudo bem?")
    assert link.startswith("https://wa.me/5531988881111?text=") and " " not in link


@pytest.mark.parametrize("url,status,platform", [
    (None, "none", None), ("", "none", None),
    ("https://www.instagram.com/salao", "social", "Instagram"), ("https://facebook.com/x", "social", "Facebook"),
    ("https://linktr.ee/salao", "social", "Linktree"), ("https://salao.booksy.com/x", "platform", "Booksy"), ("https://www.ifood.com.br/delivery/x", "platform", "iFood"),
    ("https://salaoteste.com.br", "own", None)])
def test_classify_site(url, status, platform):
    got_status, got_platform = n.classify_site(url)
    assert got_status == status
    if platform:
        assert got_platform == platform


def test_classify_site_extra_platform_from_settings():
    assert n.classify_site("https://meuapp.com.br/loja", {"meuapp.com.br": "Meu App"}) == ("platform", "Meu App")


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "ftp://x.com", "//evil.com"])
def test_safe_url_rejects_dangerous_schemes(url):
    assert n.safe_url(url) is None


@pytest.mark.parametrize("value", ["=SOMA(A1)", "+55", "-1", "@cmd", "\t=1"])
def test_csv_cell_blocks_formula(value):
    assert n.csv_cell(value).startswith("'")


def test_csv_cell_keeps_normal_text_and_stars_use_comma():
    assert n.csv_cell("Salão") == "Salão"
    assert n.stars(4.5) == "4,5"


def test_clean_tag():
    assert n.clean_tag("  #Quente!! ") == "quente"
