"""IA opcional (seção 4.10, itens 7 e 12): reescrever mensagem e analisar conversa colada.

Tenta mais de um provedor gratuito em sequência (Gemini, depois Groq). Se todos falharem, ou
se a IA estiver desligada, volta para o modelo fixo. Chaves só no .env. O texto sempre aparece
para o Samuel editar e copiar; nada é enviado. Só vão para a IA dados públicos do negócio e
o perfil do vendedor (e a conversa que o Samuel colar, no caso da análise).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

TIMEOUT = 25.0


@dataclass
class AIConfig:
    enabled: bool = False
    gemini_key: str = ""
    groq_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.gemini_key or self.groq_key)

    def __repr__(self) -> str:  # nunca mostra as chaves
        return f"<AIConfig enabled={self.enabled} gemini={'sim' if self.gemini_key else 'não'} groq={'sim' if self.groq_key else 'não'}>"


def config_from(settings, enabled: bool) -> AIConfig:
    return AIConfig(enabled=enabled, gemini_key=settings.gemini_api_key.get_secret_value(),
                    groq_key=settings.groq_api_key.get_secret_value(), gemini_model=settings.gemini_model,
                    groq_model=settings.groq_model)


def _gemini(prompt: str, cfg: AIConfig, client: httpx.Client) -> str:
    r = client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent",
        headers={"x-goog-api-key": cfg.gemini_key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.7}}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq(prompt: str, cfg: AIConfig, client: httpx.Client) -> str:
    r = client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg.groq_key}", "Content-Type": "application/json"},
        json={"model": cfg.groq_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def complete(prompt: str, cfg: AIConfig, client: httpx.Client | None = None) -> tuple[str | None, str | None]:
    """(texto, provedor) ou (None, None) se a IA está desligada ou todos falharam."""
    if not cfg.available:
        return None, None
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        for name, key, fn in (("Gemini", cfg.gemini_key, _gemini), ("Groq", cfg.groq_key, _groq)):
            if not key:
                continue
            try:
                text = (fn(prompt, cfg, client) or "").strip()
                if text:
                    return text, name
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
                continue
        return None, None
    finally:
        if own:
            client.close()


def rewrite_prompt(base_text: str, facts: dict, seller: dict, channel: str) -> str:
    return (
        "Você reescreve mensagens de prospecção em português do Brasil para um vendedor autônomo.\n"
        f"Vendedor: {seller.get('name')}, de {seller.get('city')}. O que faz: {seller.get('what')}. "
        f"Tom de voz: {seller.get('tone')}.\n"
        f"Canal: {channel}. Dados reais do negócio (não invente outros): {json.dumps(facts, ensure_ascii=False)}\n\n"
        "Reescreva a mensagem abaixo deixando-a natural e curta, sem jargão, sem promessas de resultado, sem "
        "emojis em excesso e sem inventar fatos. Mantenha qualquer link exatamente como está. "
        "Responda só com a mensagem pronta.\n\nMENSAGEM:\n" + base_text)


def rewrite(base_text: str, facts: dict, seller: dict, channel: str, cfg: AIConfig,
            client: httpx.Client | None = None) -> tuple[str, str | None]:
    """Devolve (texto, provedor). Sem IA ou com falha: (modelo fixo, None)."""
    text, provider = complete(rewrite_prompt(base_text, facts, seller, channel), cfg, client)
    if not text:
        return base_text, None
    links = re.findall(r"https?://\S+", base_text)
    if any(link not in text for link in links):  # a IA mexeu no link: não dá para confiar
        return base_text, None
    return text.strip().strip('"'), provider


# --------------------------------------------------------------------------- conversa colada
INTEREST = {"alto": "Interesse alto", "medio": "Interesse médio", "baixo": "Interesse baixo", "nenhum": "Sem interesse"}
_POS = ("quanto", "valor", "preço", "preco", "orçamento", "orcamento", "como funciona", "gostei", "interess",
        "quero", "pode mandar", "manda", "prazo", "fechar", "vamos", "pix", "contrato", "top", "legal", "show")
_NEG = ("não tenho interesse", "nao tenho interesse", "sem interesse", "não quero", "nao quero", "já tenho", "ja tenho",
        "não preciso", "nao preciso", "pare", "não me mande", "nao me mande", "bloque", "obrigado, mas")
_STOP = ("pare de", "não me mande", "nao me mande", "não entre em contato", "nao entre em contato", "vou denunciar",
         "me tira", "remov")


def analyze_conversation_rules(text: str) -> dict:
    """Sem IA: leitura simples por palavras-chave. Serve de reserva quando a IA falha."""
    low = (text or "").lower()
    pos = sum(low.count(w) for w in _POS)
    neg = sum(low.count(w) for w in _NEG)
    stop = any(w in low for w in _STOP)
    asked_price = any(w in low for w in ("quanto", "valor", "preço", "preco", "orçamento", "orcamento"))
    if stop:
        return {"interest": "nenhum", "stage": "DESCARTADO", "do_not_contact": True, "by": None,
                "summary": "A pessoa pediu para não receber mais mensagens.",
                "reply": "Sem problema, não vou mais entrar em contato. Desculpe o incômodo e sucesso para vocês!"}
    if neg > pos:
        return {"interest": "baixo", "stage": "PERDIDO", "do_not_contact": False, "by": None,
                "summary": "A conversa indica que não há interesse agora.",
                "reply": "Entendi, obrigado pelo retorno! Se um dia fizer sentido, é só me chamar. Sucesso para vocês!"}
    if asked_price:
        return {"interest": "alto", "stage": "PROPOSTA", "do_not_contact": False, "by": None,
                "summary": "Perguntaram sobre valor ou orçamento: é hora de mandar a proposta.",
                "reply": "Que bom que gostaram! Vou te mandar a proposta com valores e prazo. Posso enviar por aqui mesmo?"}
    if pos:
        return {"interest": "medio", "stage": "CONVERSA", "do_not_contact": False, "by": None,
                "summary": "Responderam com sinais de interesse, ainda sem falar de valor.",
                "reply": "Legal! Quer que eu ajuste a amostra com as fotos e os serviços de vocês para verem como fica?"}
    return {"interest": "medio" if low.strip() else "baixo", "stage": "CONVERSA" if low.strip() else None,
            "do_not_contact": False, "by": None,
            "summary": "Não deu para medir o interesse só pelo texto." if low.strip() else "Cole a conversa para analisar.",
            "reply": "Faz sentido para vocês darmos uma olhada na amostra juntos? Leva 5 minutos."}


def analyze_conversation(text: str, facts: dict, seller: dict, cfg: AIConfig,
                         client: httpx.Client | None = None) -> dict:
    """Resumo, interesse, próxima resposta e etapa sugerida. Nada é lido do WhatsApp: o Samuel cola."""
    base = analyze_conversation_rules(text)
    if not (text or "").strip() or not cfg.available:
        return base
    prompt = (
        "Analise a conversa de WhatsApp abaixo entre um vendedor de sites e um negócio local. "
        f"Vendedor: {seller.get('name')} ({seller.get('what')}), tom {seller.get('tone')}. "
        f"Negócio: {json.dumps(facts, ensure_ascii=False)}.\n"
        "Responda SÓ com JSON, nestas chaves: summary (2 frases), interest (alto|medio|baixo|nenhum), "
        "reply (próxima resposta sugerida, curta, em português do Brasil), "
        "stage (uma de: CONVERSA, PROPOSTA, FECHADO, PERDIDO, SEM_RESPOSTA, DESCARTADO), "
        "do_not_contact (true se a pessoa pediu para parar).\n\nCONVERSA:\n" + text[:6000])
    raw, provider = complete(prompt, cfg, client)
    if not raw:
        return base
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        return base
    if not isinstance(data, dict) or data.get("interest") not in INTEREST or not data.get("reply"):
        return base
    stage = data.get("stage") if data.get("stage") in ("CONVERSA", "PROPOSTA", "FECHADO", "PERDIDO", "SEM_RESPOSTA", "DESCARTADO") else base["stage"]
    return {"interest": data["interest"], "stage": stage, "do_not_contact": bool(data.get("do_not_contact")) or base["do_not_contact"],
            "summary": str(data.get("summary") or base["summary"])[:600], "reply": str(data["reply"])[:1200], "by": provider}
