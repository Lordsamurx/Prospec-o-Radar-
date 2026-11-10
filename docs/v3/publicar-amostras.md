# Publicar as amostras no Cloudflare Pages

As amostras ficam no seu PC (`C:\dev\prospeccao-data\previews` no Docker, ou `data/previews`).
Para o dono do negócio abrir o link, elas precisam estar na internet.
O Cloudflare Pages é grátis. Só as amostras saem do PC. O banco e os leads ficam com você.

## Uma vez só
1. Conta no Cloudflare: https://dash.cloudflare.com (grátis).
2. Instale o Node.js LTS em https://nodejs.org. Depois feche e abra o PowerShell.
3. No PowerShell, dentro da pasta `v3`, faça login (abre o navegador, clique em "Allow"):
   `npx wrangler login`
4. Crie o projeto das amostras:
   `npx wrangler pages project create radar-amostras --production-branch main`
   O nome vira o endereço. Se `radar-amostras` já existir no Cloudflare, use outro (ex.: `radar-amostras-sv`).
   O endereço certo aparece no fim do comando e no painel (Workers e Pages).
5. No arquivo `v3/.env`, acrescente (com o nome e o endereço do passo 4):
   ```
   CLOUDFLARE_PAGES_PROJECT=radar-amostras
   PREVIEWS_PUBLIC_URL=https://radar-amostras.pages.dev
   ```
6. Reinicie a app: `docker compose up -d --force-recreate`.

## Sempre que gerar amostras novas
No Docker (sem Python no Windows):
```
powershell -ExecutionPolicy Bypass -File scripts\publicar-amostras.ps1
```
Rodando com Python (sem Docker): `python scripts/dev.py publish`.

Os dois põem `noindex` em tudo (nenhuma amostra aparece no Google) e enviam só a pasta de amostras.
Depois disso, o link que vai na mensagem já é o público. A tela avisa quando o link ainda é local.

## Tirar uma amostra do ar
Exclua o lead (LGPD) ou mova a pasta da amostra para `_lixeira` e publique de novo.
