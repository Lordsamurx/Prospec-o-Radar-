# Radar · Prospecção de Clientes (v3)

Acha negócios locais, mostra o que falta na presença digital deles e ajuda você a abordar.
Tudo roda no seu PC. **A app nunca envia mensagem sozinha:** você copia, envia e marca "Marquei como enviado".

## Rodar no Windows (primeira vez)
Precisa do Python 3.11 ou mais novo (https://www.python.org, marque "Add to PATH").

Abra o PowerShell na pasta `v3`:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/dev.py run
```
Abra http://localhost:8000.

Nas próximas vezes:
```powershell
.venv\Scripts\activate
python scripts/dev.py run
```

## Configuração (`v3/.env`)
Copie `.env.example` para `.env` se ainda não existir. O mais importante:
- `DATABASE_URL=sqlite:///C:/dev/prospeccao-data/radar.db` (banco **fora do OneDrive**).
- `PLACES_PROVIDER=osm` (grátis). `google` só com chave e faturamento. `mock` mostra só fictícios.
- `PREVIEWS_PUBLIC_URL` e `CLOUDFLARE_PAGES_PROJECT` para mandar amostras pela internet (`docs/v3/publicar-amostras.md`).
- `GEMINI_API_KEY` / `GROQ_API_KEY`: opcionais, para a IA deixar a mensagem mais natural.

Chaves ficam **só** no `.env`. Nunca no código, nos docs ou no chat.
O que não estiver no `v3/.env`, a v3 busca no `.env` do protótipo, apenas estas chaves: chave do Google, provedor, limite diário, usuário, senha e `BASE_URL`.

## Comandos
| Comando | O que faz |
|---------|-----------|
| `python scripts/dev.py run` | Sobe a app em http://localhost:8000 |
| `python scripts/dev.py import-v1` | Traz os leads do protótipo (`../data/prospeccao.db`). Só lê o banco antigo. Rodar de novo não duplica |
| `python scripts/dev.py seed` | Põe 72 negócios **fictícios** para testar (ficam escondidos fora do modo demonstração) |
| `python scripts/dev.py backup` | Copia o banco para `data/backups` (também é automático, 1 por dia, guarda 7) |
| `python scripts/dev.py publish` | Publica as amostras no Cloudflare Pages |
| `python scripts/dev.py test` | Testes de unidade e integração |
| `python scripts/dev.py e2e` | Testes no navegador e de acessibilidade (precisa `pip install playwright` e `python -m playwright install chromium`) |
| `python scripts/dev.py smoke` | Sobe a app num banco temporário e confere as telas |

Docker (opcional): `docker compose up --build`.

## Telas
- **Hoje:** o próximo passo, follow-ups do dia, leads prontos para abordar, meta da semana.
- **Leads:** lista ou mapa, filtros (Nicho, Site, Nota e "Mais filtros"), ações em lote. Clique no nome abre o Google Maps. "Detalhes" abre o painel com Raio-X, serviços sugeridos, como abordar, amostra, mensagem, etapa, tags e histórico.
- **Buscas:** nova busca (texto ou pino no mapa), busca em lote com fila, histórico e cota do dia.
- **Funil:** contagem por etapa e kanban (arraste ou use o seletor do cartão).
- **Serviços:** o que você vende, preço editável e quais nichos mais precisam de cada serviço.
- **Métricas:** conversão por etapa, nicho e serviço; faturamento do mês.
- **Sessão (modo foco):** um lead por vez, mensagem pronta, "Marquei como enviado" e próximo.
- **Configurações:** franquias, meta, cadência, seu perfil de vendedor, limites por nicho, plataformas, IA, análise de site, backup.

Atalhos: `Ctrl K` paleta · `J`/`K` anda na lista · `Enter` abre · `A`/`B`/`C` dá nota · `E` muda a etapa · `/` busca · `?` ajuda.

## Regras que a app segue
- Não envia mensagem. Não faz scraping do Google Maps nem de outros sites.
- Dados só da Places API (New), do OpenStreetMap ou digitados por você.
- Google: no máximo 30 requisições por dia, contadas no servidor e travadas antes da chamada.
- "Não contatar" some de todas as telas e bloqueia amostra e mensagem. "Excluir de vez" apaga o lead (LGPD) e impede que ele volte.
- Checagem do site do lead: uma visita à página que o próprio negócio publicou, sem seguir links.

## Documentação
- `docs/v3/arquitetura.md` — decisões e mapa do código.
- `docs/v3/paridade.md` — tudo o que o protótipo fazia, com o teste que cobre.
- `docs/v3/publicar-amostras.md` · `docs/v3/publicar-render.md`.
- `docs/v3/roadmap.md` — o que falta decidir e o `## Log`.
