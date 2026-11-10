# Publica as amostras no Cloudflare Pages (para quem roda a v3 no Docker).
# Não precisa de Python. Precisa do Node.js (nodejs.org) e de "npx wrangler login" feito uma vez.
# Uso, no PowerShell dentro da pasta v3:
#   powershell -ExecutionPolicy Bypass -File scripts\publicar-amostras.ps1
# Só a pasta de amostras sai do PC. O banco e os leads ficam com você.

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $raiz ".env"

function Ler-Env($nome) {
    if (-not (Test-Path $envFile)) { return "" }
    foreach ($linha in Get-Content $envFile -Encoding UTF8) {
        $l = $linha.Trim()
        if ($l.StartsWith("#") -or -not $l.Contains("=")) { continue }
        $k, $v = $l.Split("=", 2)
        if ($k.Trim() -eq $nome) { return $v.Trim().Trim('"').Trim("'") }
    }
    return ""
}

$projeto = Ler-Env "CLOUDFLARE_PAGES_PROJECT"
if (-not $projeto) {
    Write-Host "Falta CLOUDFLARE_PAGES_PROJECT no v3\.env (o nome do projeto no Cloudflare Pages)."
    Write-Host "Passo a passo: docs\v3\publicar-amostras.md"
    exit 1
}

$dados = Ler-Env "RADAR_DATA_DIR"
if (-not $dados) { $dados = Join-Path $raiz "data" }
$pasta = Join-Path $dados "previews"
if (-not (Test-Path $pasta) -or -not (Get-ChildItem $pasta -Directory -ErrorAction SilentlyContinue)) {
    Write-Host "Nenhuma amostra em $pasta. Gere uma amostra num lead primeiro."
    exit 1
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Host "Não achei o npx. Instale o Node.js LTS (nodejs.org), feche e abra o PowerShell e rode de novo."
    exit 1
}

# Nenhuma amostra deve aparecer no Google.
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $pasta "_headers"), "/*`n  X-Robots-Tag: noindex, nofollow`n", $utf8)
[IO.File]::WriteAllText((Join-Path $pasta "robots.txt"), "User-agent: *`nDisallow: /`n", $utf8)
[IO.File]::WriteAllText((Join-Path $pasta "index.html"), '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="robots" content="noindex, nofollow"><title>Amostras</title><p>Amostras de demonstração.</p></html>', $utf8)

Write-Host "Publicando $pasta no projeto $projeto..."
& npx wrangler pages deploy $pasta --project-name $projeto --branch main --commit-dirty=true
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Ler-Env "PREVIEWS_PUBLIC_URL")) {
    Write-Host "Pronto. Agora acrescente no v3\.env: PREVIEWS_PUBLIC_URL=https://$projeto.pages.dev"
    Write-Host "e reinicie a app: docker compose up -d --force-recreate"
}
