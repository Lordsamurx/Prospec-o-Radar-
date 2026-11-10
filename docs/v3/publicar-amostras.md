# Publicar as amostras no Cloudflare Pages

As amostras ficam no seu PC (`data/previews`). Para o dono do negócio abrir o link, elas precisam estar na internet.
O Cloudflare Pages é grátis. Só as amostras saem do PC. O banco e os leads ficam com você.

> Não testado de verdade ainda: falta a sua conta no Cloudflare.

## Uma vez só
1. Crie uma conta grátis em https://dash.cloudflare.com/sign-up.
2. Instale o Node.js LTS em https://nodejs.org (precisa para o comando `npx`).
3. No terminal, dentro da pasta `v3`, faça login: `npx wrangler login` (abre o navegador).
4. Crie o projeto: `npx wrangler pages project create amostras-samuel --production-branch main`.
   Troque `amostras-samuel` por um nome só seu. Ele vira o endereço: `https://amostras-samuel.pages.dev`.
5. No arquivo `v3/.env`, acrescente:
   ```
   CLOUDFLARE_PAGES_PROJECT=amostras-samuel
   PREVIEWS_PUBLIC_URL=https://amostras-samuel.pages.dev
   ```
6. Reinicie a app.

## Sempre que gerar amostras novas
```
python scripts/dev.py publish
```
O comando põe `noindex` em tudo (nenhuma amostra aparece no Google) e envia a pasta.
Depois disso, o link que vai na mensagem já é o público. A tela avisa quando o link ainda é local.

## Tirar uma amostra do ar
Exclua o lead (LGPD) ou apague a pasta da amostra em `data/previews` (mova para `_lixeira`) e rode `publish` de novo.
