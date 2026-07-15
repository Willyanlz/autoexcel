# AutoExcel — Mapeamento Dinâmico de Planilhas

Sistema web para preencher planilhas Excel com códigos de produto e preços automaticamente.  
Suporta **extração por IA** (OpenRouter) de códigos a partir de imagens/fotos.

🔗 **Acesse:** [autoexcel.vercel.app](https://autoexcel.vercel.app) (ou o link do seu deploy)

---

## 🚀 Como usar

### 1. Envie a planilha
- Formato obrigatório: `.xlsx`
- A planilha deve conter linhas de **cabeçalho de formato** (ex: `FORMATO 58X58`, `TIPO 32X58`)
- Abaixo de cada cabeçalho, os códigos dos produtos

### 2. (Opcional) Envie imagens
- Tire fotos ou prints da lista de produtos
- A **IA lê automaticamente** os códigos e encaixa nos formatos corretos
- Você precisa de uma **chave do OpenRouter** (gratuita para testes)

### 3. Ajuste e gere
- Edite códigos, adicione preços e acréscimos
- Clique em **"Gerar Planilha Final"** e o download é feito na hora

---

## 🔑 Como conseguir sua chave do OpenRouter

A extração por IA usa o [OpenRouter](https://openrouter.ai), que dá **US$ 1,00 grátis** ao criar conta.

1. Acesse **[openrouter.ai/keys](https://openrouter.ai/keys)**
2. Crie uma conta (Google ou e-mail) — leva 30 segundos
3. Clique em **"Create Key"**
4. Copie a chave (começa com `sk-or-...`)
5. Cole no campo **API Key** dentro do app
6. Deixe o modelo como `google/gemini-2.5-flash` (o mais barato)

> 💡 Com US$ 1,00 grátis você processa centenas de imagens!

---

## ✨ Funcionalidades

- ✅ Leitura automática de formatos da planilha
- ✅ Extração de códigos por **IA** (OpenRouter) a partir de imagens
- ✅ Preenchimento de preço base + acréscimo fracionado
- ✅ Salvamento automático dos últimos preços no navegador
- ✅ Interface moderna e responsiva
- ✅ 100% web — sem instalação, roda no navegador

---

## 🛠️ Tecnologias

- **Backend:** Python + FastAPI (serverless na Vercel)
- **Frontend:** HTML + CSS + JavaScript puro
- **IA:** OpenRouter (modelo: `google/gemini-2.5-flash`)
- **Planilhas:** openpyxl

---

## 📦 Deploy na Vercel

O projeto já está configurado para deploy automático na Vercel:

1. Faça push para a branch `master` do seu repositório GitHub
2. A Vercel detecta e faz o deploy automaticamente
3. Pronto! 🎉

Estrutura de arquivos:

```
├── api/
│   ├── __init__.py
│   ├── index.py        # Rotas da API
│   ├── ai.py           # Extração via IA (OpenRouter)
│   ├── errors.py       # Tradução de erros para pt-br
│   ├── excel.py        # Manipulação de planilhas
│   └── helpers.py      # Funções auxiliares
├── public/
│   ├── index.html      # Frontend
│   ├── script.js
│   └── style.css
├── requirements.txt
└── vercel.json
```

---

## 📄 Licença

MIT