"""Checagem e análise do site do lead (seção 4.10, itens 3 e 4).

Regras: só a página que o próprio negócio publicou, UMA visita por lead, com limite de tempo e
de tamanho, sem seguir links e sem guardar o conteúdo. Só segue redirecionamento (até 3).
Nunca visita endereço interno (localhost, rede local). A leitura do HTML (viewport, construtor,
o que tem e o que falta) só acontece com a análise ligada em Configurações; desligada, usa
só a resposta (abriu? HTTPS?).
"""
from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

from .. import catalog
from .normalize import classify_site

TIMEOUT = 8.0
SLOW_MS = 4000
MAX_BYTES = 600_000
MAX_REDIRECTS = 3
USER_AGENT = "ProspeccaoRadar/3.0 (checagem unica do site publicado pelo negocio)"
ITEMS = {"whatsapp": "botão de WhatsApp", "telefone": "telefone clicável", "email": "e-mail", "mapa": "mapa",
         "fotos": "fotos", "descricao": "descrição para o Google", "icone": "ícone do site"}


def is_public_host(host: str, resolver: Callable[[str], list[str]] | None = None) -> bool:
    """False para localhost, IP interno ou nome que resolve para rede interna."""
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return False
    try:
        addrs = (resolver or _resolve)(host)
    except OSError:
        return True  # não resolveu: a visita vai falhar e marcar "fora do ar"
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _resolve(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        return list({i[4][0] for i in socket.getaddrinfo(host, None)})


def analyze_html(html: str) -> dict:
    """O que a página inicial tem e o que falta. Só olha o HTML recebido; não segue link nenhum."""
    low = html.lower()
    has = {
        "whatsapp": bool(re.search(r"wa\.me/|api\.whatsapp\.com|whatsapp://|web\.whatsapp\.com/send", low)),
        "telefone": "tel:" in low,
        "email": "mailto:" in low,
        "mapa": bool(re.search(r"google\.[a-z.]+/maps|maps\.google|goo\.gl/maps|maps\.app\.goo\.gl|openstreetmap\.org|<iframe[^>]+maps", low)),
        "fotos": len(re.findall(r"<img\b", low)) >= 3,
        "descricao": bool(re.search(r"<meta[^>]+name=[\"']description[\"'][^>]*content=[\"'][^\"']{20,}", low)
                          or re.search(r"<meta[^>]+content=[\"'][^\"']{20,}[\"'][^>]*name=[\"']description[\"']", low)),
        "icone": bool(re.search(r"<link[^>]+rel=[\"'][^\"']*icon", low)),
    }
    builder = None
    for name, needles in catalog.platforms().builders.items():
        if any(n.lower() in low for n in needles):
            builder = name
            break
    return {
        "viewport": bool(re.search(r"<meta[^>]+name=[\"']viewport[\"']", low)),
        "builder": builder,
        "has": [ITEMS[k] for k, v in has.items() if v],
        "missing": [ITEMS[k] for k, v in has.items() if not v],
    }


def check_site(url: str, client: httpx.Client | None = None, analyze: bool = False,
               resolver: Callable[[str], list[str]] | None = None, clock: Callable[[], float] = time.monotonic,
               extra_platforms: dict[str, str] | None = None) -> dict:
    """Uma visita à URL. Devolve o dicionário gravado em lead.site_check."""
    out: dict = {"checked": True, "analyzed": False, "url": url}
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
    current = url
    try:
        start = clock()
        resp = None
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return {**out, "down": True, "reason": "Endereço inválido."}
            if not is_public_host(parsed.hostname, resolver):
                return {**out, "checked": False, "skipped": True, "reason": "Endereço interno: não visitado."}
            try:
                with client.stream("GET", current) as r:
                    resp = r
                    body = b""
                    if analyze and r.status_code == 200:
                        for chunk in r.iter_bytes():
                            body += chunk
                            if len(body) >= MAX_BYTES:
                                break
                        body = body[:MAX_BYTES]
            except httpx.ConnectError as exc:
                cert = isinstance(exc.__cause__, ssl.SSLError) or "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper()
                return {**out, "down": not cert, "bad_cert": cert, "https": False if cert else None,
                        "reason": "Certificado de segurança inválido." if cert else "O site não respondeu."}
            except httpx.TimeoutException:
                return {**out, "down": True, "reason": f"Não respondeu em {TIMEOUT:.0f} segundos."}
            except httpx.HTTPError as exc:
                return {**out, "down": True, "reason": f"Erro ao abrir ({type(exc).__name__})."}
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                current = urljoin(current, resp.headers["location"])
                continue
            break
        else:
            return {**out, "down": True, "reason": "Redirecionamentos demais."}
        elapsed = round((clock() - start) * 1000)
        assert resp is not None
        final = urlparse(current)
        out.update(status=resp.status_code, elapsed_ms=elapsed, https=final.scheme == "https",
                   final_host=final.hostname, down=resp.status_code >= 400 and resp.status_code not in (401, 403, 405, 429),
                   slow=elapsed > SLOW_MS)
        status, platform = classify_site(current, extra_platforms)
        if status in ("social", "platform") and classify_site(url, extra_platforms)[0] == "own":
            out["platform_page"] = platform or True
        if out["down"]:
            out["reason"] = f"O site respondeu com erro {resp.status_code}."
            return out
        if analyze and resp.status_code == 200 and "html" in resp.headers.get("content-type", "html"):
            try:
                html = body.decode(resp.encoding or "utf-8", errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            out.update(analyze_html(html), analyzed=True)
        return out
    finally:
        if own_client:
            client.close()


PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def pagespeed(url: str, api_key: str = "", client: httpx.Client | None = None) -> int | None:
    """Nota de desempenho (0–100, celular) do Google PageSpeed Insights. API oficial e pública."""
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if api_key:
        params["key"] = api_key
    try:
        r = (client or httpx).get(PAGESPEED_URL, params=params, timeout=60)
        if r.status_code != 200:
            return None
        score = r.json()["lighthouseResult"]["categories"]["performance"]["score"]
        return round(float(score) * 100)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None
