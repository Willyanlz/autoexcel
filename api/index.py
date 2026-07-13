import os
import io
import re
import json
import hashlib
import sqlite3
import base64
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import pdfplumber
import openpyxl
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI

import tempfile

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use system temp directory for database to allow write permissions in serverless (e.g. Vercel)
DB_PATH = os.path.join(tempfile.gettempdir(), "mapping_images.db")
LLM_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CURRENCY_FMT = 'R$ #.##0,00'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS image_cache (hash TEXT PRIMARY KEY, json_data TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS manual_mapping (codigo TEXT PRIMARY KEY, price REAL, m2 REAL)''')
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_image_hash(image_bytes):
    return hashlib.md5(image_bytes).hexdigest()


def is_formato_header(cell_val: str) -> bool:
    """Detect all FORMATO-style header rows in the template."""
    up = cell_val.strip().upper()
    return up.startswith("FORMATO") or up.startswith("PISO") is False and re.search(r'\d+\s*[xX×]\s*\d+', up) is not None and len(up) < 40


def extract_dim_from_header(header: str) -> str | None:
    """Extract normalized dimension from a FORMATO header.
    
    'FORMATO 32X58'          → '32x58'
    'FORMATO RT 31,5 X 56,9' → '31x56'
    'FORMATO PO I AC 90,5 X 90,5' → '90x90'
    'FORMATO RT 18x113'      → '18x113'
    """
    m = re.search(r'(\d+)(?:[,.](?:\d+))?\s*[xX×]\s*(\d+)(?:[,.](?:\d+))?', header)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}"
    return None


def set_price_cell(ws, row, col, value):
    """Write a price value and apply R$ currency formatting."""
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = '#,##0.00" "[$R$-pt-BR]'


# ---------------------------------------------------------------------------
# LLM image extraction
# ---------------------------------------------------------------------------

async def extract_from_image_via_llm(image_bytes: bytes, mime_type: str, api_key: str, model: str):
    """Returns (products_list, error_string_or_None)."""
    if not api_key:
        api_key = OPENROUTER_API_KEY
    if not api_key:
        return [], "OpenRouter API Key não informada. Configure na engrenagem no topo da tela."
    
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    
    base64_img = base64.b64encode(image_bytes).decode('utf-8')
    data_uri = f"data:{mime_type};base64,{base64_img}"
    
    prompt = """Você é um assistente de extração de dados. Extraia as informações da imagem da tabela de produtos.
A imagem contém blocos de produtos separados por 'Tamanho' (ex: Tamanho: 32,00 x 58,00). 
Sob cada tamanho, há uma lista de produtos. Cada linha tem um ID, um Código (ex: 60112A), e um Nome do Produto (ex: PISO ESML. 60112).
Identifique a "tag de variante" a partir do nome do produto. As tags podem ser HD, ESML, RT, PR, IMPERMEÁVEL, POLIDO, ACETINADO, RELEVO, SD, etc. Se não houver, use "NORMAL".

Retorne EXATAMENTE UM JSON ARRAY com este formato:
[
  {"tamanho": "32,00 x 58,00", "codigo": "60112A", "nome_produto": "PISO ESML. 60112", "tag_variante": "ESML"}
]
Não adicione markdown (como ```json) ou qualquer outro texto. Apenas o array JSON puro.
"""
    try:
        response = await client.chat.completions.create(
            model=model or LLM_MODEL,
            max_tokens=8000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_uri
                            }
                        }
                    ]
                }
            ]
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
        return json.loads(content), None
    except Exception as e:
        err_msg = str(e)
        print(f"LLM Extraction error: {err_msg}")
        return [], err_msg

# ---------------------------------------------------------------------------
# PDF parsing – indexed by normalised dimension
# ---------------------------------------------------------------------------

def parse_pdf(pdf_bytes):
    """Returns dict[dim_key] → list of candidate products from PDF."""
    candidates_by_dim = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                match = re.search(
                    r'([\wÀ-ú\s\(\)\-\.]*?)'     # variant prefix (may be empty)
                    r'(\d{2,3})\s*[xX]\s*(\d{2,3})'  # dimensions
                    r'.*?R\$\s*(\d+,\d{2})'        # price
                    r'(?:\s+(\d+,\d{2}))?',         # m²/palete (optional)
                    line
                )
                if match:
                    variant_raw = match.group(1).strip()
                    dim1 = match.group(2)
                    dim2 = match.group(3)
                    price = float(match.group(4).replace(',', '.'))
                    m2_str = match.group(5)
                    m2 = round(float(m2_str.replace(',', '.')), 2) if m2_str else None
                    
                    dim_key = f"{int(dim1)}x{int(dim2)}"
                    desc = f"{variant_raw} {dim_key}".strip()
                    
                    candidates_by_dim.setdefault(dim_key, []).append({
                        "desc": desc, 
                        "price": price, 
                        "dim": dim_key, 
                        "variant_raw": variant_raw.upper(),
                        "m2": m2
                    })
    return candidates_by_dim


# ---------------------------------------------------------------------------
# Main processing endpoint
# ---------------------------------------------------------------------------

@app.post("/api/process")
async def process_files(
    pdf: UploadFile = File(...), 
    excel: UploadFile = File(None),
    images: List[UploadFile] = File([]),
    api_key: str = Form(""),
    llm_model: str = Form("")
):
    pdf_bytes = await pdf.read()
    candidates_by_dim = parse_pdf(pdf_bytes)

    # ---- Collect warnings for the frontend ----
    warnings = []

    # ---- Process images via Cache -> LLM (Parallel execution) ----
    all_products = []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Read files and hash them
    image_hashes = []
    for img in images:
        img_bytes = await img.read()
        if not img_bytes:
            continue
        img_hash = get_image_hash(img_bytes)
        image_hashes.append((img_hash, img.filename, img.content_type, img_bytes))
    
    # 2. Check cache and identify which ones need processing
    images_to_process = []
    tasks = []
    
    for img_hash, filename, content_type, img_bytes in image_hashes:
        c.execute("SELECT json_data FROM image_cache WHERE hash = ?", (img_hash,))
        row = c.fetchone()
        if row:
            products = json.loads(row[0])
            all_products.extend(products)
        else:
            images_to_process.append((img_hash, filename, content_type, img_bytes))
            tasks.append(extract_from_image_via_llm(img_bytes, content_type, api_key, llm_model))
            
    # 3. Request LLM extractions concurrently if any
    if tasks:
        results = await asyncio.gather(*tasks)
        for (img_hash, filename, content_type, img_bytes), (products, err) in zip(images_to_process, results):
            if err:
                warnings.append(f"Imagem ({filename}): falha na extração via IA — {err}")
            if products:
                c.execute("INSERT OR REPLACE INTO image_cache (hash, json_data) VALUES (?, ?)", (img_hash, json.dumps(products)))
                all_products.extend(products)
        conn.commit()
        
    # ---- Manual mappings from SQLite ----
    c.execute("SELECT codigo, price, m2 FROM manual_mapping")
    manual_mappings = {row[0]: {"price": row[1], "m2": row[2]} for row in c.fetchall()}
    conn.close()

    # ---- Build product lookup by numeric code ----
    product_map = {}
    for p in all_products:
        code = str(p.get("codigo", "")).strip()
        num_code = re.sub(r'\D', '', code)
        if num_code:
            product_map[num_code] = p

    ambiguous = []
    success_count = 0
    pending_count = 0
    
    # ---- Load workbook ----
    if excel:
        excel_bytes = await excel.read()
        if not excel_bytes:
            raise HTTPException(
                status_code=400, 
                detail="O arquivo Excel enviado está vazio. Envie a planilha com os códigos de produto preenchidos."
            )
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    else:
        raise HTTPException(
            status_code=400, 
            detail="A Planilha Excel com códigos de produto é obrigatória. Envie o arquivo .xlsx com os códigos preenchidos na coluna A."
        )
        
    ws = wb.active

    # ---- Iterate rows and fill data ----
    current_dim = None
    current_opts = []
    total_codes_found = 0
    
    for r in range(1, ws.max_row + 1):
        cell_val = str(ws.cell(row=r, column=1).value or "").strip().upper()
        
        # Detect FORMATO header → extract dimension to find PDF candidates
        dim = extract_dim_from_header(cell_val)
        if dim is not None:
            current_dim = dim
            current_opts = candidates_by_dim.get(current_dim, [])
            continue
        
        # Skip empty / title rows
        num_code = re.sub(r'\D', '', cell_val)
        if not num_code or len(num_code) < 4:
            continue

        total_codes_found += 1

        # ---------- Try manual mapping first ----------
        if num_code in manual_mappings:
            set_price_cell(ws, r, 2, manual_mappings[num_code]["price"])
            success_count += 1
            continue
        
        # ---------- Try image-based matching ----------
        prod_info = product_map.get(num_code)
        if not prod_info:
            # No image data for this code
            if len(current_opts) == 1:
                set_price_cell(ws, r, 2, current_opts[0]["price"])
                success_count += 1
            elif len(current_opts) > 1:
                ambiguous.append({
                    "row": r,
                    "codigo": cell_val,
                    "nome": "NOME DESCONHECIDO (Envie imagem)",
                    "opcoes": current_opts
                })
                pending_count += 1
            continue
        
        tag = str(prod_info.get("tag_variante", "")).upper()
        
        # Cross-reference tag with PDF candidates for this dimension
        matched_opts = []
        for opt in current_opts:
            if tag and tag != "NORMAL" and tag in opt["variant_raw"]:
                matched_opts.append(opt)
            elif (tag == "NORMAL" or not tag) and (not opt["variant_raw"] or opt["variant_raw"] == "NORMAL"):
                matched_opts.append(opt)
        
        if len(matched_opts) == 1:
            set_price_cell(ws, r, 2, matched_opts[0]["price"])
            success_count += 1
        elif len(matched_opts) == 0 and len(current_opts) == 1:
            set_price_cell(ws, r, 2, current_opts[0]["price"])
            success_count += 1
        else:
            ambiguous.append({
                "row": r,
                "codigo": cell_val,
                "nome": prod_info.get("nome_produto"),
                "opcoes": current_opts if len(matched_opts) == 0 else matched_opts
            })
            pending_count += 1

    # ---- Add diagnostic warnings ----
    if total_codes_found == 0:
        warnings.append("Nenhum código de produto encontrado na planilha Excel. Verifique se os códigos estão na coluna A.")
    if len(candidates_by_dim) == 0:
        warnings.append("Nenhum produto encontrado no PDF. Verifique se o PDF contém tabela de preços com dimensões e valores R$.")
    if images and not all_products:
        warnings.append("Nenhum produto extraído das imagens. Verifique se o modelo de IA suporta visão (imagens). Modelos recomendados: google/gemini-2.5-flash, openai/gpt-4o-mini.")

    # ---- Serialize workbook ----
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    b64_excel = base64.b64encode(out.read()).decode('utf-8')

    return JSONResponse(content={
        "success": True,
        "success_count": success_count,
        "pending_count": pending_count,
        "total_codes": total_codes_found,
        "pdf_dimensions": len(candidates_by_dim),
        "image_products": len(all_products),
        "ambiguous": ambiguous,
        "warnings": warnings,
        "excel_base64": b64_excel
    })


# ---------------------------------------------------------------------------
# Resolve ambiguities endpoint
# ---------------------------------------------------------------------------

class MappingResolution(BaseModel):
    codigo: str
    price: float
    m2: float
    row: int

class ResolveRequest(BaseModel):
    resolutions: List[MappingResolution]
    excel_base64: str

@app.post("/api/resolve")
async def resolve_ambiguities(req: ResolveRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for res in req.resolutions:
        num_code = re.sub(r'\D', '', res.codigo)
        if num_code:
            c.execute("INSERT OR REPLACE INTO manual_mapping (codigo, price, m2) VALUES (?, ?, ?)", 
                      (num_code, res.price, res.m2))
    conn.commit()
    conn.close()

    excel_bytes = base64.b64decode(req.excel_base64)
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    ws = wb.active
    
    for res in req.resolutions:
        set_price_cell(ws, res.row, 2, res.price)
            
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    
    return Response(
        content=out.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Tabela_Final.xlsx"}
    )

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
public_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
app.mount("/", StaticFiles(directory=public_path, html=True), name="public")
