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
from pypdf import PdfReader
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
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS manual_mapping (codigo TEXT PRIMARY KEY, price REAL, m2 REAL)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not initialize database: {e}")

try:
    init_db()
except Exception as e:
    print(f"Warning: init_db failed at module level: {e}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_image_hash(image_bytes):
    return hashlib.md5(image_bytes).hexdigest()


def is_formato_header(cell_val: str) -> bool:
    """Detect all FORMATO-style header rows in the template."""
    up = cell_val.strip().upper()
    return up.startswith("FORMATO") or up.startswith("PISO") is False and re.search(r'\d+\s*[xX×]\s*\d+', up) is not None and len(up) < 40


def extract_dim_from_header(cell_val: str) -> str | None:
    """Extract normalized dimension from a FORMATO header.
    
    'FORMATO 32X58'          → '32x58'
    'FORMATO RT 31,5 X 56,9' → '31x56'
    'FORMATO PO I AC 90,5 X 90,5' → '90x90'
    'FORMATO RT 18x113'      → '18x113'
    """
    m = re.search(r'(\d+)(?:[,.](?:\d+))?\s*[xX×]\s*(\d+)(?:[,.](?:\d+))?', cell_val)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}"
    return None


def set_price_cell(ws, row, col, value):
    """Write a price value and apply R$ currency formatting."""
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = '#,##0.00" "[$R$-pt-BR]'


def find_dimension_for_row(ws, row):
    for r in range(row, 0, -1):
        val = str(ws.cell(row=r, column=1).value or "").strip().upper()
        dim = extract_dim_from_header(val)
        if dim is not None:
            return dim
    return None


def get_fracionado_adicional(dim_key: str) -> float:
    if not dim_key:
        return 2.0  # default
    m = re.findall(r'\d+', dim_key)
    if len(m) >= 2:
        d1, d2 = int(m[0]), int(m[1])
        if (d1 == 56 and d2 == 113) or (d1 == 113 and d2 == 56):
            return 4.0
        elif max(d1, d2) <= 58:
            return 2.0
        else:
            return 3.0
    return 2.0


def fill_price_and_fracionado(ws, row, price, dim_key=None):
    set_price_cell(ws, row, 2, price)
    if dim_key is None:
        dim_key = find_dimension_for_row(ws, row)
    adicional = get_fracionado_adicional(dim_key)
    set_price_cell(ws, row, 3, price + adicional)


def get_fallback_candidate(opts):
    """Choose the best default candidate from the PDF candidates.
    Prefer standard pieces over special ones, and prefer candidates with a blank variant (pure size).
    """
    if not opts:
        return None
    # 1. Filter out special pieces
    std_candidates = [opt for opt in opts if not opt.get("is_especial", False)]
    if not std_candidates:
        std_candidates = opts
    
    # 2. Prefer candidate with empty variant (representing the plain base size, e.g. "32 x 58 R$ 12,70")
    blank_variants = [opt for opt in std_candidates if opt["variant_raw"] == ""]
    if len(blank_variants) == 1:
        return blank_variants[0]
    elif len(blank_variants) > 1:
        return sorted(blank_variants, key=lambda x: x["price"])[0]
        
    # 3. If no empty variant candidate exists, fallback to the lowest price option
    return sorted(std_candidates, key=lambda x: x["price"])[0]


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
Não adicione markdown (como ```json) or qualquer outro texto. Apenas o array JSON puro.
"""
    try:
        response = await client.chat.completions.create(
            model=model or LLM_MODEL,
            max_tokens=8000,
            timeout=7.0,  # 7-second limit to avoid Vercel 10s timeout
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
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for page in reader.pages:
        text = page.extract_text()
        if not text:
            continue
        is_especial = False
        for line in text.split('\n'):
            line_upper = line.upper()
            if "PEÇAS ESPECIAIS" in line_upper or "PEAS ESPECIAIS" in line_upper or "PECAS ESPECIAIS" in line_upper:
                is_especial = True
            
            match = re.search(
                r'([\wÀ-ú\s\(\)\-\.]*?)'         # variant prefix (may be empty)
                r'(\d{2,3})\s*[xX]\s*(\d{2,3})'  # dimensions
                r'(.*)',                        # the rest of the line
                line
            )
            if match:
                variant_raw = match.group(1).strip()
                dim1 = match.group(2)
                dim2 = match.group(3)
                rest = match.group(4)
                
                money_matches = re.findall(r'(\d+,\d{1,2})', rest)
                if not money_matches:
                    continue
                
                floats = [float(m.replace(',', '.')) for m in money_matches]
                price = min(floats)
                m2 = max(floats) if len(floats) > 1 else None
                
                dim_key = f"{int(dim1)}x{int(dim2)}"
                desc = f"{variant_raw} {dim_key}".strip()
                
                is_item_especial = is_especial or any(x in line_upper for x in ["RELEVO", "RODAPE", "RODAPÉ", "DEGRAU", "ESPECIAL"])
                
                candidates_by_dim.setdefault(dim_key, []).append({
                    "desc": desc, 
                    "price": price, 
                    "dim": dim_key, 
                    "variant_raw": variant_raw.upper(),
                    "m2": m2,
                    "is_especial": is_item_especial
                })
    return candidates_by_dim

# ---------------------------------------------------------------------------
# Image Extraction Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/extract-image")
async def extract_image(
    image: UploadFile = File(...),
    api_key: str = Form(""),
    llm_model: str = Form("")
):
    try:
        img_bytes = await image.read()
        if not img_bytes:
            return JSONResponse(status_code=400, content={"error": "Imagem vazia"})
        
        products, err = await extract_from_image_via_llm(img_bytes, image.content_type, api_key, llm_model)
        if err:
            return JSONResponse(status_code=500, content={"error": err})
            
        return {"products": products}
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "detail": traceback.format_exc()}
        )


# ---------------------------------------------------------------------------
# Main processing endpoint
# ---------------------------------------------------------------------------

@app.post("/api/process")
async def process_files(
    pdf: UploadFile = File(...), 
    excel: UploadFile = File(None),
    image_products_json: str = Form("[]")
):
  try:
    pdf_bytes = await pdf.read()
    candidates_by_dim = parse_pdf(pdf_bytes)

    # ---- Collect warnings for the frontend ----
    warnings = []

    # ---- Load products list extracted from frontend ----
    try:
        all_products = json.loads(image_products_json)
    except Exception as e:
        all_products = []
        warnings.append(f"Erro ao decodificar produtos das imagens: {e}")

    # ---- Manual mappings from SQLite ----
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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

    # ---- Build image products index by normalized dimension ----
    image_products_by_dim = {}
    for p in all_products:
        tamanho = str(p.get("tamanho", ""))
        dim_match = re.search(r'(\d+)(?:[,.](?:\d+))?\s*[xX×]\s*(\d+)(?:[,.](?:\d+))?', tamanho)
        if dim_match:
            dim_key = f"{int(dim_match.group(1))}x{int(dim_match.group(2))}"
            image_products_by_dim.setdefault(dim_key, []).append(p)
    
    # Deduplicate products by codigo within each dimension
    for dk in image_products_by_dim:
        seen = set()
        unique = []
        for p in image_products_by_dim[dk]:
            code = p.get("codigo", "")
            if code and code not in seen:
                seen.add(code)
                unique.append(p)
        image_products_by_dim[dk] = unique

    # ---- Phase A: Insert image products into empty FORMATO sections ----
    # 1. Find all FORMATO header rows and their dimensions
    formato_rows = []
    for r in range(1, ws.max_row + 1):
        val = str(ws.cell(row=r, column=1).value or "").strip().upper()
        dim = extract_dim_from_header(val)
        if dim is not None:
            formato_rows.append((r, dim))

    # 2. Check which sections are empty (no product codes between headers)
    sections_to_fill = []
    for i, (hrow, dim) in enumerate(formato_rows):
        next_hrow = formato_rows[i + 1][0] if i + 1 < len(formato_rows) else ws.max_row + 1
        has_codes = False
        for r in range(hrow + 1, min(next_hrow, hrow + 50)):  # limit lookahead
            cv = str(ws.cell(row=r, column=1).value or "").strip()
            nc = re.sub(r'\D', '', cv)
            if nc and len(nc) >= 4:
                has_codes = True
                break
        if not has_codes and dim in image_products_by_dim:
            sections_to_fill.append((hrow, dim))

    # 3. Insert products bottom-to-top to preserve row indices
    for hrow, dim in reversed(sections_to_fill):
        prods = image_products_by_dim[dim]
        insert_at = hrow + 1
        count = len(prods)
        if count == 0:
            continue

        # Read physical properties and style objects from the first row after header (template row)
        phys = {}
        styles = {}
        from copy import copy
        for col in range(1, min(ws.max_column + 1, 20)):
            cell = ws.cell(row=insert_at, column=col)
            if col >= 3 and cell.value is not None:
                phys[col] = cell.value
            
            # Copy all cell styling attributes
            styles[col] = {
                "font": copy(cell.font) if cell.font else None,
                "fill": copy(cell.fill) if cell.fill else None,
                "border": copy(cell.border) if cell.border else None,
                "alignment": copy(cell.alignment) if cell.alignment else None,
                "number_format": cell.number_format
            }

        # First product reuses the existing row; insert additional rows below it
        if count > 1:
            ws.insert_rows(insert_at + 1, count - 1)

        # Write product codes and apply styles into the rows
        row_height = ws.row_dimensions[insert_at].height
        for idx, prod in enumerate(prods):
            r = insert_at + idx
            
            # Copy row height
            if row_height is not None:
                ws.row_dimensions[r].height = row_height
                
            code = prod.get("codigo", "")
            ws.cell(row=r, column=1, value=code)
            
            # Copy physical properties (values) to newly inserted rows
            if idx > 0:
                for col, v in phys.items():
                    ws.cell(row=r, column=col, value=v)
                    
            # Apply styles to all cells in the current row
            for col in range(1, min(ws.max_column + 1, 20)):
                dst_cell = ws.cell(row=r, column=col)
                style = styles.get(col)
                if style:
                    if style["font"]: dst_cell.font = style["font"]
                    if style["fill"]: dst_cell.fill = style["fill"]
                    if style["border"]: dst_cell.border = style["border"]
                    if style["alignment"]: dst_cell.alignment = style["alignment"]
                    if style["number_format"]: dst_cell.number_format = style["number_format"]

    # ---- Iterate rows and fill data (prices from PDF) ----
    current_dim = None
    current_opts = []
    total_codes_found = 0
    
    for r in range(1, ws.max_row + 1):
        cell_val = str(ws.cell(row=r, column=1).value or "").strip().upper()
        
        # Detect FORMATO header → extract dimension to find PDF candidates
        dim = extract_dim_from_header(cell_val)
        if dim is not None:
            # Fuzzy match to closest dimension in candidates_by_dim if not exact match
            if dim not in candidates_by_dim and candidates_by_dim:
                w, h = map(int, dim.split('x'))
                best_match = None
                best_dist = 999
                for pdf_dim in candidates_by_dim.keys():
                    try:
                        pw, ph = map(int, pdf_dim.split('x'))
                    except ValueError:
                        continue
                    dist = min(
                        abs(w - pw) + abs(h - ph),
                        abs(w - ph) + abs(h - pw)
                    )
                    if dist < best_dist and dist <= 3:
                        best_dist = dist
                        best_match = pdf_dim
                if best_match:
                    dim = best_match

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
            fill_price_and_fracionado(ws, r, manual_mappings[num_code]["price"], current_dim)
            if manual_mappings[num_code]["m2"]:
                ws.cell(row=r, column=9, value=manual_mappings[num_code]["m2"])
            success_count += 1
            continue
        
        # ---------- Try image-based matching ----------
        prod_info = product_map.get(num_code)
        if not prod_info:
            # No image data for this code
            if len(current_opts) == 1:
                fill_price_and_fracionado(ws, r, current_opts[0]["price"], current_dim)
                if current_opts[0]["m2"]:
                    ws.cell(row=r, column=9, value=current_opts[0]["m2"])
                success_count += 1
            elif len(current_opts) > 1:
                # Use our fallback logic to get the base size price (e.g. 12,70 for 32x58)
                chosen_opt = get_fallback_candidate(current_opts)
                if chosen_opt:
                    fill_price_and_fracionado(ws, r, chosen_opt["price"], current_dim)
                    if chosen_opt["m2"]:
                        ws.cell(row=r, column=9, value=chosen_opt["m2"])
                    success_count += 1
                else:
                    ws.cell(row=r, column=2, value="PREENCHA")
            else:
                ws.cell(row=r, column=2, value="PREENCHA")
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
            fill_price_and_fracionado(ws, r, matched_opts[0]["price"], current_dim)
            if matched_opts[0]["m2"]:
                ws.cell(row=r, column=9, value=matched_opts[0]["m2"])
            success_count += 1
        elif len(matched_opts) == 0 and len(current_opts) == 1:
            fill_price_and_fracionado(ws, r, current_opts[0]["price"], current_dim)
            if current_opts[0]["m2"]:
                ws.cell(row=r, column=9, value=current_opts[0]["m2"])
            success_count += 1
        else:
            # Ambiguity exists even with tags or no tags match, pick fallback candidate
            opts_to_use = matched_opts if matched_opts else current_opts
            chosen_opt = get_fallback_candidate(opts_to_use)
            if chosen_opt:
                fill_price_and_fracionado(ws, r, chosen_opt["price"], current_dim)
                if chosen_opt["m2"]:
                    ws.cell(row=r, column=9, value=chosen_opt["m2"])
                success_count += 1
            else:
                ws.cell(row=r, column=2, value="PREENCHA")

    # ---- Add diagnostic warnings ----
    if total_codes_found == 0:
        warnings.append("Nenhum código de produto encontrado na planilha Excel. Verifique se os códigos estão na coluna A.")
    if len(candidates_by_dim) == 0:
        warnings.append("Nenhum produto encontrado no PDF. Verifique se o PDF contém tabela de preços com dimensões e valores R$.")
    if not all_products:
        warnings.append("Nenhum produto extraído das imagens. Verifique as configurações da API Key e se o modelo suporta visão.")
    if len(ambiguous) > 0:
        warnings.append(f"Existem {len(ambiguous)} itens com preços não encontrados ou ambíguos. Eles foram marcados como 'PREENCHA' na planilha para você completar manualmente.")

    # ---- Serialize workbook ----
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    b64_excel = base64.b64encode(out.read()).decode('utf-8')

    return JSONResponse(content={
        "success": True,
        "success_count": success_count,
        "pending_count": 0,  # Always 0 to allow direct download without resolution UI
        "total_codes": total_codes_found,
        "pdf_dimensions": len(candidates_by_dim),
        "image_products": len(all_products),
        "ambiguous": ambiguous,
        "warnings": warnings,
        "excel_base64": b64_excel
    })
  except HTTPException:
      raise
  except Exception as e:
      import traceback
      error_detail = traceback.format_exc()
      print(f"Process endpoint error: {error_detail}")
      return JSONResponse(
          status_code=500,
          content={"success": False, "error": f"Erro interno: {str(e)}", "detail": error_detail}
      )


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
        fill_price_and_fracionado(ws, res.row, res.price, None)
        if res.m2:
            ws.cell(row=res.row, column=9, value=res.m2)
            
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    
    return Response(
        content=out.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Tabela_Final.xlsx"}
    )

# ---------------------------------------------------------------------------
# Static frontend (only mount when running locally, Vercel handles static via routes)
# ---------------------------------------------------------------------------
try:
    public_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
    if os.path.isdir(public_path):
        app.mount("/", StaticFiles(directory=public_path, html=True), name="public")
    else:
        print(f"Warning: public directory not found at {public_path}, skipping StaticFiles mount")
except Exception as e:
    print(f"Warning: Could not mount static files: {e}")
