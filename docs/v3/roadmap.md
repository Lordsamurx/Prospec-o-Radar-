# Roadmap da v3 "Radar"

## Feito (10/11/2026)
- Fases 1 a 10 do prompt: base, catálogo de 12 setores e 118 nichos, Raio-X, nota, perfil, oportunidade, recomendação de serviços, estratégia, funil novo com cadência, Hoje, sessão de prospecção, amostras (5 modelos), mensagens (4 canais), proposta e diagnóstico imprimíveis, Serviços por categoria, métricas, busca em lote e no mapa, checagem do site, IA opcional, importação do protótipo, backup.

## Falta decidir (Samuel)
1. **Preços dos serviços.** O catálogo está sem preço ("a definir"). Preencha em Serviços.
2. **Amostras no Cloudflare Pages.** Criar a conta e seguir `publicar-amostras.md`.
3. **Banco em `C:\dev\prospeccao-data\radar.db`.** Já configurado no `v3/.env`. Confirmar que a pasta pode ficar ali.
4. **Limites por nicho** (nota e avaliações mínimas). Os padrões vêm do catálogo; ajuste em Configurações.
5. **Google pago ou não.** Hoje roda com OpenStreetMap. Para o Google: pré-pagamento de R$ 200 no Google Cloud e `PLACES_PROVIDER=google`.
6. **Repositório no GitHub** (sugestão: `prospeccao-radar`, privado) para guardar a v3.

## Próximos passos sugeridos
- Rodar a v3 no Windows e importar o banco do protótipo (`python scripts/dev.py import-v1`).
- Construir a imagem Docker num PC com Docker (não deu no ambiente de nuvem).
- Testar com a primeira chave real de IA (Gemini grátis).

## Log
- 2026-11-10 · v3 "Radar" criada na pasta `v3/` (o protótipo da raiz não foi alterado). 332 testes de unidade e integração e 87 no navegador (Playwright + axe) passando no ambiente de nuvem. Importação testada com uma cópia do banco real (107 leads, 208 eventos, 4 amostras). Docker não construído (Docker Hub recusou a imagem base). Google, Overpass, Cloudflare e IA reais não testados.
- 2026-11-10 · Código publicado no GitHub (Lordsamurx/prospec-o-radar-, branch main), sem .env e sem banco. Decisões do Samuel: preços ainda a definir; Cloudflare depois (já tem conta); limites por nicho ficam no padrão; Google só depois de testar a plataforma.
- 2026-11-10 · Docker construído e rodando no PC do Samuel (telas 200). Cloudflare: `scripts/publicar-amostras.ps1` publica as amostras de `RADAR_DATA_DIR\previews` sem precisar de Python; `publicar-amostras.md` refeito para quem usa Docker.
