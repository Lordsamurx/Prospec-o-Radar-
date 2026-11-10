# Publicar a app no Render (opcional)

Use só se quiser abrir a app fora do seu PC. Para uso no PC, não precisa.

> Não testado de verdade: falta o repositório no GitHub e a conta no Render.

1. Suba a pasta `v3` para um repositório **privado** no GitHub (o `.env` e o banco não vão: estão no `.gitignore`).
2. Em https://render.com, crie uma conta e escolha **New > Blueprint**. Aponte para o repositório. O Render lê o `render.yaml`.
3. Na tela, preencha:
   - `APP_PASSWORD`: obrigatória. Uma senha forte. Sem ela, qualquer um abre a app.
   - `BASE_URL`: o endereço que o Render der (ex.: `https://radar-prospeccao.onrender.com`).
   - `GOOGLE_MAPS_API_KEY` e `GEMINI_API_KEY`: opcionais.
4. Ao abrir, o navegador pede usuário (`samuel`) e senha. `/health` e as amostras ficam abertos.

## Cuidados
- No plano grátis o disco **não é permanente**: o banco pode sumir ao reiniciar. Baixe backup em Configurações.
- O plano grátis dorme sem uso. O primeiro acesso demora uns 30 segundos.
- As amostras servidas pelo Render também funcionam como link público, com `noindex`.
