# AutoExcel V2 📊✈️

O **AutoExcel V2** é uma ferramenta inteligente de automação projetada para extrair dados de tabelas de preços em arquivos PDF e imagens (através de Inteligência Artificial com visão computacional) e inseri-los automaticamente em planilhas Excel estruturadas para clientes.

---

## 🚀 Funcionalidades

- **Parser Inteligente de PDFs**: Extrai de forma eficiente produtos, dimensões, preços e metadados diretamente de PDFs de tabelas de preços.
- **Extração com IA (OCR Avançado)**: Processa fotos/imagens de tabelas de fabricantes usando modelos multimodais de visão computacional da OpenAI ou Google Gemini via OpenRouter para mapear códigos de produtos a suas respectivas variantes.
- **Validação Cruzada de Dimensões**: Associa automaticamente as variantes corretas com base no formato/dimensão do produto definido na planilha.
- **Interface Intuitiva**: Interface moderna estilo *Glassmorphism* com zonas de drag-and-drop para fácil envio de arquivos.
- **Resolução de Ambiguidades**: Caso um código possua múltiplas variantes possíveis no PDF, a ferramenta exibe uma tela de revisão amigável para que o usuário escolha a variante correta antes de exportar o arquivo final.
- **Cache Inteligente**: Salva os resultados das imagens localmente em banco de dados SQLite (`mapping_images.db`) para evitar chamadas de API repetidas para as mesmas fotos.

---

## 🛠️ Requisitos de Arquivos

Para que o processo de cruzamento de dados funcione perfeitamente, os três arquivos devem ser enviados de forma obrigatória:

1. **PDF de Preços**: Documento contendo as dimensões dos pisos (ex: `32 x 58`) e os valores correspondentes em formato de moeda (`R$ 12,70`).
2. **Imagens das Tabelas**: Fotos ou prints das tabelas técnicas que descrevem qual código de produto corresponde a qual variante (ex: o código `60112` é da variante `ESML`).
3. **Planilha Base (.xlsx)**: A planilha do cliente contendo os códigos dos produtos que você deseja preencher na **Coluna A**, organizados sob seus respectivos cabeçalhos de formato (ex: `FORMATO 32X58`).

---

## ⚙️ Configuração da IA

A extração de dados a partir das imagens requer uma chave de API para processar a visão computacional:
1. Acesse o **AutoExcel V2** no seu navegador.
2. Clique no ícone de **engrenagem (⚙️)** no topo superior esquerdo.
3. Insira sua **OpenRouter API Key**.
4. Configure o modelo desejado (Recomendado: `google/gemini-2.5-flash` ou `openai/gpt-4o-mini`).
5. Clique em **Salvar Configurações**.

---

## 📦 Como Instalar e Rodar Localmente

### 1. Clonar o Repositório
```bash
git clone https://github.com/Willyanlz/autoexcel.git
cd autoexcel
```

### 2. Criar e Ativar Ambiente Virtual (Recomendado)
```bash
# No Windows
python -m venv .venv
.venv\Scripts\activate
```

### 3. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 4. Configurar Variáveis de Ambiente
Crie um arquivo `.env` na raiz do projeto com a seguinte variável (opcional caso prefira configurar diretamente na interface):
```env
OPENROUTER_API_KEY=sua_chave_aqui
```

### 5. Executar o Servidor de Desenvolvimento
```bash
uvicorn api.index:app --reload
```
Acesse `http://127.0.0.1:8000` no seu navegador.

---

## 🚀 Como Utilizar o Sistema

1. Faça o upload do **PDF contendo os Preços**.
2. Selecione as **Imagens dos Produtos** (tabelas de variantes).
3. Selecione a **Planilha Excel Base** contendo os códigos que deseja preencher na coluna A.
4. Clique em **Processar e Cruzar Dados**.
5. Se não houver divergências, a planilha final editada será baixada imediatamente.
6. Caso encontre alguma inconsistência ou múltiplas opções de preço, uma tela de **Revisão Necessária** abrirá para que você selecione a variante correta manualmente de maneira simplificada antes de baixar o documento.
