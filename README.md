# AutoExcel - Preenchimento Dinâmico de Planilhas

Sistema simples, determinístico e ultrarrápido para mapear preços de formatos em planilhas Excel.

## Como funciona
1. Você faz o upload da sua planilha Excel (`.xlsx`).
2. O sistema lê todos os `FORMATOS` ou `TIPOS` descritos nas linhas azuis/cabeçalhos.
3. Você insere manualmente o preço base e o acréscimo para a versão fracionada de cada formato. (Seu navegador lembra dos últimos preços que você digitou!).
4. Clique em Gerar e o sistema preenche todas as linhas de produtos correspondentes com precisão 100% matemática, e faz o download instantâneo do Excel.

## Rodando Localmente
Instale as dependências:
```bash
pip install -r requirements.txt
```

Inicie o servidor localmente:
```bash
python run.py
```
A interface estará disponível em `http://127.0.0.1:8000`

## Vercel Deployment
Esse sistema foi reestruturado para ser 100% compatível com a arquitetura serverless da Vercel (sem IA demorada e sem banco de dados SQLite volátil).
Basta realizar o push para a branch `master` e a Vercel fará o deploy automático em 2-3 segundos.
O comando executado pela Vercel é: `pip install -r requirements.txt` e o run é `uvicorn api.index:app`.
