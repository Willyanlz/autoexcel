"""Extração de produtos de imagens via IA (OpenRouter)."""

import json
import base64
from api.errors import humanize_error


async def extract_from_image_via_ai(image_bytes: bytes, mime_type: str, api_key: str, model: str):
    """Envia imagem para OpenRouter e retorna (lista_de_produtos, erro_ou_None)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    base64_img = base64.b64encode(image_bytes).decode('utf-8')
    data_uri = f"data:{mime_type};base64,{base64_img}"

    prompt = """Você é um assistente de extração de dados de planilhas/imagens.
Extraia as informações da imagem de produtos. A imagem contém blocos separados por 'Tamanho' (ex: Tamanho: 32,00 x 58,00).
Sob cada tamanho, há uma lista de produtos.

Preciso que você extraia a identificação de cada produto (código e nome), seguindo EXATAMENTE este padrão de conversão:
- Se for "1 I60112A PISO ESML. 60112", extraia "I60112A PISO ESML. 60112"
- Se for "2 IN1531 PISO ESML. 60072", extraia "IN1531 PISO ESML. 60072"
- Se for "1 MAC518009A PISO VANCOUVER MAC 518.009", extraia "MAC518009A PISO VANCOUVER MAC 518.009"
- Se for "1 MRT250008A PISO ESML. RT 250.008", extraia "MRT250008A PISO ESML. RT 250.008"

Regras gerais:
1. Ignore apenas o número sequencial no início da linha (ex: 1, 2, 3) e o espaço logo após.
2. Extraia e mantenha todo o restante da linha (o código de sistema e a descrição completa).

Retorne EXATAMENTE UM JSON ARRAY com este formato:
[
  {"tamanho": "32,00 x 58,00", "codigo": "I60112A PISO ESML. 60112"},
  {"tamanho": "18,00 x 113,00 RT", "codigo": "MAC518009A PISO VANCOUVER MAC 518.009"}
]
Não adicione markdown (como ```json). Apenas o array JSON puro.
"""
    try:
        response = await client.chat.completions.create(
            model=model or "google/gemini-2.5-flash",
            max_tokens=6000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}}
                    ]
                }
            ]
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip()), None
    except Exception as e:
        return [], humanize_error(str(e))