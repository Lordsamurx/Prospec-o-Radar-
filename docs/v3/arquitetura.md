# Arquitetura da v3 "Radar"

## ADR-001: app local em Python, sem etapa de build

**Status:** Aceito · **Data:** 10/11/2026 · **Quem decide:** Samuel

### Contexto
- Uma pessoa usa, no próprio PC com Windows. Volume pequeno (centenas a poucos milhares de leads).
- O protótipo já era FastAPI + SQLite + HTMX e funcionava. O Samuel não é programador: instalar e atualizar precisa ser simples.
- Regras duras: nada é enviado sozinho, sem scraping, chaves só no `.env`, 30 buscas/dia no Google.

### Decisão
- **Servidor:** Python 3.11+, FastAPI, SQLAlchemy 2 e SQLite (migrações simples próprias em `db.py`).
- **Telas:** Jinja2 + HTMX + um `app.js` próprio. Alpine fica disponível, mas quase não é usado. Sem Node, sem build.
- **Mapa:** Leaflet com os blocos do OpenStreetMap (arquivos do Leaflet guardados em `static/vendor`).
- **Regras de negócio em funções puras** (`services/diagnose, scoring, profile, opportunity, recommend, strategy, funnel`). Recebem dados e devolvem resultado. Fácil de testar, sem banco e sem rede.
- **Catálogos em YAML** (`catalog/niches.yaml`, `services.yaml`, `platforms.yaml`), validados ao iniciar.
- **Fonte de dados por provedor** (`services/providers`): `osm` (padrão, grátis), `google` (só com chave e `PLACES_PROVIDER=google`), `mock` (fictícios).
- **Mesma rota, três formatos:** página inteira, fragmento HTMX ou JSON (`?format=json`).
- **IA opcional** (Gemini, depois Groq). Se falhar, usa o texto fixo. A IA nunca envia nada.
- **Amostras** são HTML estático em `data/previews/`, publicadas no Cloudflare Pages com `scripts/dev.py publish`.
- **Banco fora do OneDrive:** `DATABASE_URL=sqlite:///C:/dev/prospeccao-data/radar.db`. O OneDrive pode corromper um SQLite aberto.

### Opções consideradas
| Opção | Complexidade | Custo | Prós | Contras |
|-------|--------------|-------|------|---------|
| **A. FastAPI + HTMX (escolhida)** | Baixa | Zero | Igual ao protótipo; um processo; roda com `python scripts/dev.py run` | Interações muito ricas exigem JS à mão |
| B. FastAPI + React/Vite | Média | Zero | Ecossistema de componentes | Exige Node e build; duas pastas para manter |
| C. Planilha + automações | Baixa | Zero | Familiar | Não atende diagnóstico, funil, amostras nem regras de segurança |

### Consequências
- Mais fácil: instalar, testar (332 testes rodam em ~70 s), copiar o banco, fazer backup.
- Mais difícil: uso por várias pessoas ao mesmo tempo (SQLite e um processo). Não é objetivo.
- Rever se: virar SaaS ou equipe. Aí trocar SQLite por Postgres e pôr login de verdade.

## Mapa do código

```
v3/
  backend/app/
    main.py            app, senha (Basic), CSRF por Origin, cabeçalhos
    config.py          configurações do .env (lê do .env do protótipo só chaves permitidas)
    models.py          tabelas (leads, lead_events, searches, search_jobs, sites, outreach_drafts, proposals...)
    routers/           hoje, busca, leads, funil, serviços, amostras, mensagens, propostas, configurações
    services/          regras de negócio (funções puras) e acesso a provedores
    catalog/           nichos, setores, serviços e plataformas em YAML
    templates/         telas Jinja2; partials/ são os pedaços que o HTMX troca
    static/            css (tokens.css + app.css), js/app.js, fontes, vendor (htmx, alpine, leaflet)
  templates-site/      os 5 modelos de amostra (landing, institucional, cardápio, agendamento, links)
  scripts/dev.py       run | test | e2e | seed | smoke | import-v1 | backup | publish
  backend/tests/       unidade e integração; e2e/ no navegador com axe
```

## Fluxo principal
1. **Busca** (`POST /buscas`) → provedor → `upsert_place` (pelo `place_id`) → `refresh` calcula Raio-X, nota, perfil, oportunidade e recomendação e grava no lead.
2. **Lista** (`GET /leads`) filtra no banco com os campos já calculados.
3. **Drawer** (`GET /leads/{id}`) recalcula o Raio-X na hora (`insight`) para mostrar os sinais.
4. **Amostra** (`POST /leads/{id}/site`) gera HTML em `data/previews/<slug>/` e move a etapa para "Amostra pronta".
5. **Mensagem** (`POST /leads/{id}/outreach`) cria rascunho. O Samuel copia e envia. `POST /outreach/{id}/sent` só registra.
6. **Funil** guarda cada mudança em `lead_events` e agenda a próxima ação (cadência +3/+5/+7).

## Segurança
- Senha opcional (`APP_PASSWORD`). Abertos: `/health` e `/previews/...`.
- CSRF: ações recusadas quando a origem é outro site.
- Checagem do site do lead: uma visita, sem seguir links, nunca para endereço interno (bloqueia `localhost`, rede local e nomes que resolvem para ela), página lida até 600 KB e não guardada.
- Chaves só no `.env`. Nunca aparecem em tela, JSON, log ou erro (há teste para isso).
- CSV: células que começam com `= + - @` ganham um apóstrofo.

## Revisão de código (10/11/2026)
Feita com a skill de revisão. Sem problema crítico encontrado.
- Consultas todas pelo SQLAlchemy com parâmetros. As duas exceções usam nomes fixos no código.
- HTML escapado pelo Jinja; o JS monta textos com `textContent`.
- Corrigido na revisão: métricas contavam leads "não contatar"; página muito grande não era cortada na análise; proposta salva mostrava serviços que o Samuel tinha tirado; ordem do histórico; foco do teclado com "reduzir movimento".
- Fica para depois: `refresh_all` recalcula todos os leads quando muda uma configuração. Rápido até alguns milhares de leads.

## Acessibilidade (revisão WCAG 2.1 AA, 10/11/2026)
- **Automático:** axe (WCAG 2.0/2.1 A e AA) sem violações nas 10 telas, no painel do lead, na proposta, no diagnóstico e nas 5 amostras; temas claro e escuro; computador (1366 px) e celular (390 px, equivale a zoom de 350%).
- **Teclado:** link "pular para o conteúdo" é o primeiro Tab; foco visível; painel do lead prende o foco e devolve ao fechar (inclusive com "reduzir movimento"); paleta `Ctrl K` com setas; kanban tem seletor no cartão além de arrastar.
- **Leitor de tela:** avisos (toasts) em região `aria-live`; resultado da busca, fila e painel com `aria-live`; erros de busca com `role="alert"`.
- **Toque:** caixas de marcar e botões com pelo menos 24 px; principais com 44 px.
- **Corrigido nesta revisão:** nome acessível do botão da paleta não batia com o texto visível; faixa de etapas do funil rolava sem receber foco; funil e Serviços passavam da largura da tela no celular; barra de ações em lote não aparecia; caixas de marcar com 18 px.
- **Não testado:** leitor de tela de verdade (NVDA no Windows). Vale um teste rápido.
