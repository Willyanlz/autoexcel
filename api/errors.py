"""Tradução de erros da IA / sistema para mensagens amigáveis em pt-br."""


def humanize_error(msg: str) -> str:
    """Traduz erros comuns do OpenRouter/IA para mensagens em pt-br."""
    msg_lower = msg.lower()

    # 402 - Saldo insuficiente
    if '402' in msg or 'insufficient' in msg_lower or 'can only afford' in msg_lower or 'credits' in msg_lower:
        return "❌ Saldo insuficiente no OpenRouter. Recarregue seus créditos em openrouter.ai/settings/credits ou use um modelo mais barato."

    # 429 - Rate limit
    if '429' in msg or 'rate limit' in msg_lower or 'too many requests' in msg_lower:
        return "⚠️ Muitas requisições seguidas. Aguarde alguns segundos e tente novamente."

    # 401 - API Key inválida
    if '401' in msg or 'unauthorized' in msg_lower or 'invalid' in msg_lower and ('key' in msg_lower or 'auth' in msg_lower or 'api' in msg_lower):
        return "🔑 API Key inválida ou expirada. Verifique sua chave em openrouter.ai/keys"

    # 404 - Modelo não encontrado
    if '404' in msg or ('not found' in msg_lower and 'model' in msg_lower):
        return "🤖 Modelo não encontrado. Verifique o nome do modelo (ex: google/gemini-2.5-flash)."

    # 408 / timeout
    if '408' in msg or 'timeout' in msg_lower or 'timed out' in msg_lower:
        return "⏱️ A requisição excedeu o tempo limite. Tente com uma imagem menor ou outro modelo."

    # context_length / max_tokens
    if 'context_length' in msg_lower or 'context length' in msg_lower or 'max_tokens' in msg_lower or 'maximum context' in msg_lower or 'too long' in msg_lower:
        return "📏 A imagem é muito grande para este modelo. Tente com uma imagem menor ou outro modelo."

    # 503 - Indisponível
    if '503' in msg or 'unavailable' in msg_lower or 'temporarily' in msg_lower:
        return "🔧 O modelo selecionado está temporariamente indisponível. Tente novamente ou escolha outro modelo."

    # JSON parse error
    if 'json' in msg_lower and ('parse' in msg_lower or 'decode' in msg_lower or 'expect' in msg_lower):
        return "📄 A IA retornou uma resposta inesperada. Tente novamente."

    # Fallback: resume a mensagem original (máx 120 chars)
    short = msg[:120] + ('...' if len(msg) > 120 else '')
    return f"❌ Erro na IA: {short}"