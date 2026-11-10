# CLAUDE.md · v3 "Radar"

App de prospecção do Samuel (pt-BR). FastAPI + SQLAlchemy/SQLite + Jinja2/HTMX, sem build. Leia `README.md` e `docs/v3/arquitetura.md`.

## Regras duras (não mudam)
- Nunca enviar mensagem a um lead. Botões: "Copiar" e "Marquei como enviado". Nunca "Enviar".
- Sem scraping. Dados só da Places API (New), do OpenStreetMap (Overpass) ou digitados pelo Samuel. Checar se o site do próprio lead abre é permitido; ler a página inicial só com a análise ligada; nunca seguir links.
- Google: 30 requisições/dia, contadas no servidor, trava antes de chamar. OSM é o padrão.
- Chaves só no `.env`. Não ler, não imprimir, não pedir. Não mexer no `.env` nem no `.env.example` do protótipo.
- Não apagar arquivos: mover para `_lixeira/<data>-<motivo>/`.
- LGPD: só dados públicos de negócio. "Não contatar" esconde de tudo e bloqueia amostra e mensagem. Guardar a origem do dado.
- Dados fictícios sempre marcados (`is_mock`, `place_id` começando com `mock-`).
- Telas em português do Brasil, frases curtas.
- Toda mudança relevante: uma linha no `## Log` de `docs/v3/roadmap.md`.

## Trabalhar no código
- Regras de negócio são funções puras em `backend/app/services/`. Teste novo para cada regra.
- Toda rota responde HTML, fragmento HTMX e JSON (`?format=json`).
- Testes: `python scripts/dev.py test` (rápido) e `python scripts/dev.py e2e` (navegador + axe).
- Catálogos: `backend/app/catalog/*.yaml`. Nicho sem campo obrigatório quebra ao iniciar (de propósito).
