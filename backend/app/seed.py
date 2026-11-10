"""python scripts/dev.py seed: põe no banco os negócios FICTÍCIOS de demonstração (idempotente).

Os fictícios ficam marcados (is_mock) e escondidos das telas, a não ser com PLACES_PROVIDER=mock
ou marcando "Mostrar fictícios" nos filtros."""
from .config import get_settings
from .db import init_engine, new_session
from .services import app_settings, lead_service
from .services.providers.mock import MockProvider, mock_niches
from . import catalog


def main() -> dict:
    init_engine()
    db = new_session()
    try:
        ctx = app_settings.load_ctx(db)
        cat = catalog.niches()
        total = {"total": 0, "created": 0, "updated": 0, "by_niche": {}}
        for key in mock_niches():
            r = lead_service.run_search(db, get_settings(), ctx, cat.label(key), "Belo Horizonte", None,
                                        provider=MockProvider())
            for k in ("total", "created", "updated"):
                total[k] += r[k]
            total["by_niche"][cat.label(key)] = r["total"]
        print(f"Seed ok: {total['total']} leads fictícios ({total['created']} novos, {total['updated']} atualizados) "
              f"em {len(total['by_niche'])} nichos.")
        return total
    finally:
        db.close()


if __name__ == "__main__":
    main()
