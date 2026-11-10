"""Catálogos: carregamento, validação e resolução de nicho."""
import pytest

from app import catalog


def test_catalog_has_12_sectors_and_100_plus_niches():
    cat = catalog.niches()
    assert len(cat.sectors) == 12
    assert len(cat.niches) >= 100
    assert {"salao", "barbearia", "estetica", "dentista", "petshop", "oficina", "restaurante", "academia"} <= set(cat.by_key)


def test_every_niche_inherits_sector_fields():
    cat = catalog.niches()
    for n in cat.all:
        assert n.sector in cat.sector_by_key
        assert n.template in catalog.OFFER_TEMPLATES
        assert n.default_offer in catalog.services()
        assert n.tagline and n.cta and "{name}" in n.wa_message
        assert len(n.services) >= 3


def test_services_catalog_has_14_services():
    s = catalog.services()
    assert len(s) == 14
    assert {"landing", "institucional", "cardapio", "agendamento", "links", "gmn_otimizacao", "manutencao"} <= set(s)
    assert s["manutencao"].recurring is True


def test_resolve_by_alias_without_accent_and_unknown_goes_to_other():
    cat = catalog.niches()
    assert cat.resolve("Salão de Beleza").key == "salao"
    assert cat.resolve("salao de beleza em savassi").key == "salao"
    assert cat.resolve("pizzaria").sector == "alimentacao"
    assert cat.resolve("xyz inexistente").key == "outro"


def test_niche_missing_required_field_fails(tmp_path):
    bad = tmp_path / "niches.yaml"
    bad.write_text(
        "sectors:\n  - key: beleza\n    label: Beleza\n    color: '#e0569b'\n    icon: x\n    template: landing\n"
        "    default_offer: landing\n    offers: [landing]\n    pitch: p\n    tagline: t\n    cta: c\n"
        "    wa_message: 'oi {name}'\n    services: [[a, b, c], [a, b, c], [a, b, c]]\n"
        "niches:\n  - key: semlabel\n    sector: beleza\n", encoding="utf-8")
    with pytest.raises(catalog.CatalogError):
        catalog.load_niches(bad)


def test_niche_with_unknown_sector_or_offer_fails(tmp_path):
    bad = tmp_path / "niches.yaml"
    bad.write_text(
        "sectors:\n  - key: beleza\n    label: Beleza\n    color: '#e0569b'\n    icon: x\n    template: landing\n"
        "    default_offer: naoexiste\n    offers: [landing]\n    pitch: p\n    tagline: t\n    cta: c\n"
        "    wa_message: 'oi {name}'\n    services: [[a, b, c], [a, b, c], [a, b, c]]\nniches: []\n", encoding="utf-8")
    with pytest.raises(catalog.CatalogError):
        catalog.load_niches(bad)


def test_service_with_bad_price_fails(tmp_path):
    bad = tmp_path / "services.yaml"
    bad.write_text("services:\n  - key: x\n    name: X\n    short: s\n    description: d\n    price_min: abc\n", encoding="utf-8")
    with pytest.raises(catalog.CatalogError):
        catalog.load_services(bad)


def test_price_text_formats_brl():
    assert catalog.price_text(None, None) == "preço a definir"
    assert "1.500" in catalog.price_text(1500, 1500)
    assert "mês" in catalog.price_text(100, 100, recurring=True)
