"""Negócios FICTÍCIOS de BH, de vários setores, para testar sem gastar nada.

Tudo inventado: nomes, ruas ("Rua Fictícia ..."), sites em .example e telefones de teste
(celular (31) 99999-0xxx, fixo (31) 3999-9xxx). Os 40 primeiros são os do protótipo, com os
mesmos place_id (mock-001 a mock-040). O "Pet Shop Patas Fictícias" está de propósito no nicho
salão: é o caso de categoria fora do nicho que a nota descarta.
"""
from urllib.parse import quote

from ... import catalog
from ...schemas import PlaceDTO
from .. import geo
from ..normalize import slugify
from .base import PlacesProvider

# nome | bairro | fone (m=celular, l=fixo, -=sem) | site | nota | avaliações | status | horário | fotos | categoria | nicho
ROWS = """
Espaço Lumi Cabelos|Savassi|m|none|4.8|132|OP|y|24|hair_salon|salao
Salão Dona Flor|Funcionários|m|ig|4.6|88|OP|y|15|beauty_salon|salao
Studio Aurora Beauty|Lourdes|m|https|4.9|210|OP|y|40|beauty_salon|salao
Cabelo & Cia Exemplo|Centro|l|none|4.2|45|OP|y|8|hair_salon|salao
Atelier Mel Unhas|Savassi|m|none|4.7|9|OP|y|5|nail_salon|salao
Barbearia Raízes Fictícia|Santa Efigênia|m|none|4.5|67|OP|y|19|barber_shop|barbearia
Clínica Pura Estética Fictícia|Floresta|m|linktree|4.3|31|OP|n|6|skin_care_clinic|estetica
Rede Fictícia Bela Cor Savassi|Savassi|l|https|4.1|520|OP|y|60|beauty_salon|salao
Rede Fictícia Bela Cor Buritis|Buritis|l|https|3.9|300|OP|y|33|beauty_salon|salao
Odonto Encanto do Sion|Sion|m|none|4.4|22|OP|y|11|dentist|dentista
Espaço Jade Estética|Sion|m|http|4.6|54|OP|y|14|spa|estetica
Pet Shop Primavera|Prado|m|none|3.6|40|OP|y|7|pet_store|petshop
Studio Cachos de Ouro|Castelo|m|fb|4.8|19|OP|n|9|hair_salon|salao
Restaurante Lírio Branco|Pampulha|m|none|4.9|76|CLOSED_PERMANENTLY|y|12|restaurant|restaurante
Navalha & Tesoura Exemplo|Barro Preto|m|ig|4.7|140|OP|y|30|barber_shop|barbearia
Nail Bar Pétala|Lourdes|m|none|4.5|16|OP|y|10|nail_salon|salao
Oficina Vitória Régia|Cidade Nova|l|none|4.0|15|OP|y|3|car_repair|oficina
Academia Maré Fictícia|Buritis|m|none|4.3|28|CLOSED_TEMPORARILY|y|6|gym|academia
Studio Íris Make|Savassi|m|ig|4.9|61|OP|y|22|beauty_salon|salao
Salão Sem Contato Exemplo|Centro|-|none|4.4|33|OP|n|2|beauty_salon|salao
Pet Shop Patas Fictícias|Floresta|m|none|4.6|90|OP|y|20|pet_store|salao
Clínica Odontológica Girassol|Santo Agostinho|m|none|4.6|49|OP|y|13|dental_clinic|dentista
Barbearia Bom Jesus Exemplo|Santa Efigênia|l|none|4.1|8|OP|n|1|barber_shop|barbearia
Espaço Anis Sobrancelhas|Funcionários|m|linktree|4.8|102|OP|y|27|beauty_salon|salao
Restaurante Alfazema|Castelo|m|none|4.7|150|OP|y|35|brazilian_restaurant|restaurante
Studio Bambu Pilates|Pampulha|m|https|4.5|80|OP|y|20|gym|academia
Auto Center Estrela do Prado|Prado|m|none|4.2|300|OP|y|18|car_repair|oficina
Ateliê Tranças Fictícias|Barro Preto|m|ig|4.9|37|OP|y|16|hair_salon|salao
Pet Camomila Banho e Tosa|Cidade Nova|m|none|4.0|14|OP|y|4|pet_care|petshop
Barbearia Ônix|Lourdes|l|http|3.8|25|OP|y|9|barber_shop|barbearia
Espaço Violeta Estética|Sion|m|none|4.6|71|OP|n|0|beauty_salon|estetica
Lanchonete Canela|Centro|m|fb|4.1|12|OP|y|5|meal_takeaway|lanchonete
Dentista Brisa Exemplo|Santo Agostinho|l|none|4.5|58|OP|y|14|dentist|dentista
Salão Orquídea|Floresta|m|none|4.8|205|OP|y|31|beauty_salon|salao
Academia Âmbar Fit|Savassi|m|https|4.4|44|OP|y|12|gym|academia
Mecânica Jasmim|Buritis|m|none|4.3|19|OP|y|8|car_repair|oficina
Esmalteria Coral|Funcionários|m|ig|4.2|6|OP|y|3|nail_salon|salao
Pet Shop Hortelã|Castelo|m|none|2.9|18|OP|y|4|pet_store|petshop
Clínica Safira Estética|Pampulha|m|none|-|0|OP|n|0|spa|estetica
Odonto Magnólia|Santa Efigênia|m|none|4.6|95|OP|y|21|dentist|dentista
Pizzaria Manjericão Fictícia|Savassi|m|ifood|4.6|320|OP|y|28|pizza_restaurant|pizzaria
Hamburgueria Brasa Exemplo|Lourdes|m|ig|4.7|210|OP|y|34|hamburger_restaurant|hamburgueria
Marmitaria Tempero de Casa|Centro|m|none|4.5|64|OP|y|6|meal_takeaway|marmitaria
Cafeteria Grão Fictício|Funcionários|m|https|4.8|412|OP|y|52|cafe|cafeteria
Açaí do Vale Exemplo|Buritis|m|ifood|4.3|88|OP|n|4|ice_cream_shop|acaiteria
Padaria Trigo Dourado|Prado|l|none|4.4|180|OP|y|12|bakery|padaria
Doceria Flor de Açúcar|Sion|m|linktree|4.9|47|OP|y|18|dessert_shop|doceria
Studio Navalha Booksy Exemplo|Floresta|m|booksy|4.8|95|OP|y|22|barber_shop|barbearia
Espaço Trinks Exemplo Beleza|Castelo|m|trinks|4.5|38|OP|y|9|beauty_salon|salao
Clínica Vet Quatro Patas Fictícia|Sion|m|none|4.7|133|OP|y|17|veterinary_care|veterinaria
Hotel Pet Latido Feliz|Pampulha|m|ig|4.9|58|OP|y|25|pet_boarding_service|hotel_pet
Fisio Movimento Exemplo|Santo Agostinho|m|none|4.9|41|OP|y|8|physiotherapist|fisioterapia
Ótica Visão Clara Fictícia|Centro|l|http|4.0|27|OP|y|6|store|otica
Lava-Jato Espuma Exemplo|Cidade Nova|m|none|4.4|73|OP|n|3|car_wash|lava_jato
Borracharia Roda Viva|Barro Preto|l|none|4.6|51|OP|y|2|tire_shop|borracharia
Chaveiro Chave Mestra Fictício|Centro|m|none|4.8|66|OP|y|4|locksmith|chaveiro
Vidraçaria Cristal Exemplo|Prado|m|wix|4.2|18|OP|y|7|store|vidracaria
Elétrica Luz Certa Fictícia|Buritis|m|none|5.0|12|OP|n|1|electrician|eletricista
Pilates Corpo em Linha|Lourdes|m|ig|5.0|36|OP|y|14|gym|pilates
CT Tatame Fictício Jiu-Jitsu|Castelo|m|none|4.9|84|OP|y|19|gym|artes_marciais
Idiomas Ponte Exemplo|Savassi|m|https|4.6|72|OP|y|16|school|idiomas
Autoescola Volante Fictícia|Floresta|l|none|4.1|140|OP|y|5|school|autoescola
Advocacia Souza & Exemplo|Funcionários|l|none|4.9|23|OP|y|3|lawyer|advocacia
Contábil Balanço Fictício|Santo Agostinho|m|gsites|4.7|31|OP|y|2|accounting|contabilidade
Imobiliária Chave na Mão Exemplo|Savassi|m|https|4.3|96|OP|y|30|real_estate_agency|imobiliaria
Boutique Linho Fictícia|Lourdes|m|ig|4.8|29|OP|y|21|clothing_store|loja_roupas
Floricultura Jardim Exemplo|Sion|m|none|4.7|110|OP|y|26|florist|floricultura
Celulares Sinal Fictício|Centro|m|fb|4.0|44|OP|y|8|cell_phone_store|loja_celulares
Buffet Festa Boa Exemplo|Pampulha|m|none|4.6|57|OP|y|40|catering_service|buffet
Pousada Serra Fictícia|Pampulha|m|booking|4.5|230|OP|y|48|lodging|pousada
Fotógrafa Luz Natural Exemplo|Santa Efigênia|m|ig|5.0|19|OP|n|35|store|fotografo
Tattoo Tinta Fictícia|Savassi|m|ig|4.9|160|OP|y|44|body_art_service|tatuagem
"""

HOURS = "seg: Fechado; ter–sex: 09:00–19:00; sáb: 08:00–17:00; dom: Fechado"


def _site(kind: str, slug: str) -> str | None:
    u = slug.replace("-", "")
    return {
        "none": None,
        "ig": f"https://instagram.com/{slug.replace('-', '_')}_ficticio",
        "fb": f"https://facebook.com/{slug}.ficticio",
        "linktree": f"https://linktr.ee/{u}ficticio",
        "https": f"https://{slug}.example",
        "http": f"http://{slug}.example",
        "ifood": f"https://www.ifood.com.br/delivery/belo-horizonte-mg/{slug}-ficticio",
        "booksy": f"https://booksy.com/pt-br/{u}-ficticio",
        "trinks": f"https://www.trinks.com/{slug}-ficticio",
        "wix": f"https://{u}ficticio.wixsite.com/site",
        "gsites": f"https://sites.google.com/view/{slug}-ficticio",
        "booking": f"https://www.booking.com/hotel/br/{slug}-ficticio.html",
    }[kind]


def mock_places() -> list[PlaceDTO]:
    out = []
    for i, line in enumerate(l for l in ROWS.strip().splitlines() if l.strip()):
        name, bairro, fone, site, nota, aval, status, hours, photos, cat, niche = line.split("|")
        n = i + 1
        slug = slugify(name)
        phone = {"m": f"(31) 99999-{n:04d}", "l": f"(31) 3999-9{n:03d}", "-": None}[fone]
        key = geo.find_in_text(bairro)[0]
        lat0, lng0 = geo.center_of(key)
        # espalha ~0–600 m em volta do centro do bairro, sempre igual
        lat = lat0 + ((n * 37) % 11 - 5) * 0.0011
        lng = lng0 + ((n * 53) % 11 - 5) * 0.0011
        out.append(PlaceDTO(
            place_id=f"mock-{n:03d}",
            niche_hint=niche,
            name=name,
            address=f"Rua Fictícia {name.split()[-1]}, {100 + n * 7} - {bairro}, Belo Horizonte - MG",
            neighborhood=bairro,
            city="Belo Horizonte",
            phone=phone,
            website_url=_site(site, slug),
            maps_url="https://www.google.com/maps/search/?api=1&query=" + quote(f"{name} {bairro} Belo Horizonte"),
            rating=None if nota == "-" else float(nota),
            reviews_count=int(aval),
            business_status="OPERATIONAL" if status == "OP" else status,
            opening_hours=HOURS if hours == "y" else None,
            photos_count=int(photos),
            categories=[cat, "point_of_interest", "establishment"],
            lat=round(lat, 6),
            lng=round(lng, 6),
        ))
    return out


def mock_niches() -> list[str]:
    """Nichos que têm pelo menos um negócio fictício, na ordem do catálogo."""
    have = {p.niche_hint for p in mock_places()}
    return [n.key for n in catalog.niches().niches if n.key in have]


class MockProvider(PlacesProvider):
    """Devolve só os fictícios do nicho buscado ("outro" = nenhum); filtra por bairro ou pino."""

    name = "mock"

    def search(self, niche, location, radius_m=None, center=None):
        self.last_requests_made = 0
        key = catalog.niches().resolve(niche).key
        places = [p for p in mock_places() if p.niche_hint == key]
        if center:
            r = (radius_m or 1500) / 1000
            return [p for p in places if geo.distance_km(center[0], center[1], p.lat, p.lng) <= r]
        bairros = {geo.display(b) for b in geo.find_in_text(location)}
        if bairros:
            places = [p for p in places if p.neighborhood in bairros]
        return places
