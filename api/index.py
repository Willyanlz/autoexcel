import os
import io
import re
import json
import base64
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import openpyxl
from copy import copy

# Lazy-load lightweight OCR lib (rapidocr – ONNX-based, ~100MB vs PyTorch ~2GB)
_ocr_engine = None
def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine

OCR_AVAILABLE = False
OCR_IMPORT_ERROR = ""
try:
    import rapidocr_onnxruntime
    OCR_AVAILABLE = True
except Exception as e:
    import traceback
    OCR_IMPORT_ERROR = str(e) + "\n" + traceback.format_exc()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CURRENCY_FMT = '#,##0.00" "[$R$-pt-BR]'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_dim_from_header(cell_val: str) -> str | None:
    m = re.search(r'(\d+)(?:[,.](?:\d+))?\s*[xX×]\s*(\d+)(?:[,.](?:\d+))?', cell_val)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}"
    return None


def set_price_cell(ws, row, col, value):
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = CURRENCY_FMT


def scan_excel_formats(ws):
    formats = {}
    current_format = None
    for r in range(1, ws.max_row + 1):
        cell_val = str(ws.cell(row=r, column=1).value or "").strip().upper()
        dim = extract_dim_from_header(cell_val)
        if dim is not None:
            current_format = cell_val
            if current_format not in formats:
                formats[current_format] = []
            continue
        if current_format is None:
            continue
        num_code = re.sub(r'\D', '', cell_val)
        if num_code and len(num_code) >= 4:
            formats[current_format].append(cell_val.strip())
    return formats


# ---------------------------------------------------------------------------
# OCR Simple (easyocr – offline, no API)
# ---------------------------------------------------------------------------

def extract_products_ocr(image_bytes: bytes):
    """Use rapidocr (ONNX) to read text, then parse product codes grouped by size."""
    engine = get_ocr_engine()
    result, _ = engine(image_bytes)

    # rapidocr returns list of [box, text, score] or None
    if not result:
        return []

    # Calculate center Y, min X, and height for each item
    items = []
    for box, text, score in result:
        y_center = sum(pt[1] for pt in box) / 4.0
        x_min = min(pt[0] for pt in box)
        h = max(pt[1] for pt in box) - min(pt[1] for pt in box)
        items.append({"text": text, "y": y_center, "x": x_min, "h": h})
        
    # Sort by Y first
    items.sort(key=lambda item: item["y"])
    
    # Group by Y with dynamic tolerance
    lines_reconstructed = []
    current_line = []
    current_y = None
    
    for item in items:
        if current_y is None:
            current_y = item["y"]
            current_line.append(item)
        else:
            # Tolerance is 40% of the box's height, prevents merging different lines
            tolerance = max(item["h"] * 0.4, 4)
            if abs(item["y"] - current_y) < tolerance:
                current_line.append(item)
                current_y = sum(i["y"] for i in current_line) / len(current_line)
            else:
                current_line.sort(key=lambda i: i["x"])
                lines_reconstructed.append(" ".join(i["text"] for i in current_line))
                current_line = [item]
                current_y = item["y"]
            
    if current_line:
        current_line.sort(key=lambda i: i["x"])
        lines_reconstructed.append(" ".join(i["text"] for i in current_line))

    lines = lines_reconstructed

    products = []
    current_size = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Detect size headers like "Tamanho: 32,00 x 58,00" or "32 x 58"
        size_match = re.search(
            r'(\d+)[,.]?\d*\s*[xX×]\s*(\d+)[,.]?\d*',
            line
        )
        if size_match and ('tamanho' in line.lower() or len(line) < 40):
            d1, d2 = size_match.group(1), size_match.group(2)
            current_size = f"{d1},{'00'} x {d2},00"
            continue
            
        # Ignore sub-totals
        if 'sub-total' in line.lower() or 'sub total' in line.lower():
            continue

        # Remove sequential number at the start
        # e.g., "1 MAC518009A PISO VANCOUVER..." -> "MAC518009A PISO VANCOUVER..."
        cleaned_line = re.sub(r'^\s*\d+\s+', '', line).strip()
        
        if len(cleaned_line) > 5 and 'tamanho' not in cleaned_line.lower() and 'sub-total' not in cleaned_line.lower():
            products.append({
                "tamanho": current_size or "DESCONHECIDO",
                "codigo": cleaned_line
            })

    return products


# ---------------------------------------------------------------------------
# AI extraction (OpenRouter)
# ---------------------------------------------------------------------------

async def extract_from_image_via_ai(image_bytes: bytes, mime_type: str, api_key: str, model: str):
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
            max_tokens=8000,
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
        return [], str(e)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/capabilities")
async def capabilities():
    """Tell the frontend whether simple OCR is available."""
    return {"ocr_available": OCR_AVAILABLE}


@app.post("/api/analyze")
async def analyze(
    excel: UploadFile = File(...),
    images: List[UploadFile] = File(None),
    mode: str = Form("ocr"),
    api_key: str = Form(""),
    llm_model: str = Form("")
):
    try:
        excel_bytes = await excel.read()
        if not excel_bytes:
            return JSONResponse(status_code=400, content={"error": "Arquivo Excel vazio."})

        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = wb.active
        formats_with_codes = scan_excel_formats(ws)

        # Process images if provided
        ocr_products = []
        ocr_errors = []

        if images:
            for img_file in images:
                img_bytes = await img_file.read()
                if not img_bytes:
                    continue

                if mode == "ai" and api_key:
                    prods, err = await extract_from_image_via_ai(
                        img_bytes, img_file.content_type or "image/png", api_key, llm_model
                    )
                    if err:
                        ocr_errors.append(err)
                    ocr_products.extend(prods)
                elif mode == "ocr":
                    if not OCR_AVAILABLE:
                        ocr_errors.append(f"OCR simples indisponível. Erro interno: {OCR_IMPORT_ERROR[:200]}...")
                        continue
                    try:
                        prods = extract_products_ocr(img_bytes)
                        ocr_products.extend(prods)
                    except Exception as e:
                        ocr_errors.append(f"Erro OCR: {str(e)}")

        # Merge OCR products into formats
        for prod in ocr_products:
            tamanho = str(prod.get("tamanho", ""))
            codigo = str(prod.get("codigo", "")).strip()
            if not codigo:
                continue

            dim = extract_dim_from_header(tamanho)
            if dim is None:
                continue

            matched_format = None
            for fmt_header in formats_with_codes:
                fmt_dim = extract_dim_from_header(fmt_header)
                if fmt_dim == dim:
                    matched_format = fmt_header
                    break

            if matched_format and codigo not in formats_with_codes[matched_format]:
                formats_with_codes[matched_format].append(codigo)

        # Build response
        formats_list = []
        for fmt_header in sorted(formats_with_codes.keys()):
            formats_list.append({
                "header": fmt_header,
                "dim": extract_dim_from_header(fmt_header),
                "codes": formats_with_codes[fmt_header]
            })

        return {
            "formats": formats_list,
            "ocr_count": len(ocr_products),
            "ocr_errors": ocr_errors
        }

    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "detail": traceback.format_exc()}
        )


@app.post("/api/process")
async def process_manual(
    excel: UploadFile = File(...),
    mapping_json: str = Form("{}")
):
    try:
        mapping = json.loads(mapping_json)

        excel_bytes = await excel.read()
        if not excel_bytes:
            raise HTTPException(status_code=400, detail="Arquivo Excel vazio.")

        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active

        # --- Phase 1: Rebuild product code rows ---
        formato_rows = []
        for r in range(1, ws.max_row + 1):
            val = str(ws.cell(row=r, column=1).value or "").strip().upper()
            dim = extract_dim_from_header(val)
            if dim is not None:
                formato_rows.append((r, val))

        for i in reversed(range(len(formato_rows))):
            hrow, header = formato_rows[i]
            if header not in mapping:
                continue

            user_codes = mapping[header].get("codes", [])
            if not user_codes:
                continue

            next_hrow = formato_rows[i + 1][0] if i + 1 < len(formato_rows) else ws.max_row + 1
            existing_code_rows = []
            for r in range(hrow + 1, next_hrow):
                cv = str(ws.cell(row=r, column=1).value or "").strip()
                nc = re.sub(r'\D', '', cv)
                if nc and len(nc) >= 4:
                    existing_code_rows.append(r)

            template_row = hrow + 1
            styles = {}
            for col in range(1, min(ws.max_column + 1, 20)):
                cell = ws.cell(row=template_row, column=col)
                styles[col] = {
                    "font": copy(cell.font) if cell.font else None,
                    "fill": copy(cell.fill) if cell.fill else None,
                    "border": copy(cell.border) if cell.border else None,
                    "alignment": copy(cell.alignment) if cell.alignment else None,
                    "number_format": cell.number_format
                }

            if not existing_code_rows:
                count = len(user_codes)
                ws.cell(row=template_row, column=1, value=user_codes[0])
                if count > 1:
                    ws.insert_rows(template_row + 1, count - 1)
                    for j in range(i + 1, len(formato_rows)):
                        formato_rows[j] = (formato_rows[j][0] + count - 1, formato_rows[j][1])
                for idx in range(1, count):
                    r = template_row + idx
                    ws.cell(row=r, column=1, value=user_codes[idx])
                    for col, style in styles.items():
                        dst = ws.cell(row=r, column=col)
                        if style.get("font"): dst.font = style["font"]
                        if style.get("fill"): dst.fill = style["fill"]
                        if style.get("border"): dst.border = style["border"]
                        if style.get("alignment"): dst.alignment = style["alignment"]
                        if style.get("number_format"): dst.number_format = style["number_format"]
            else:
                for idx, code_row in enumerate(existing_code_rows):
                    if idx < len(user_codes):
                        ws.cell(row=code_row, column=1, value=user_codes[idx])
                    else:
                        ws.cell(row=code_row, column=1, value="")

                extra = len(user_codes) - len(existing_code_rows)
                if extra > 0:
                    insert_at = existing_code_rows[-1] + 1
                    ws.insert_rows(insert_at, extra)
                    for idx in range(extra):
                        r = insert_at + idx
                        ws.cell(row=r, column=1, value=user_codes[len(existing_code_rows) + idx])
                        for col, style in styles.items():
                            dst = ws.cell(row=r, column=col)
                            if style.get("font"): dst.font = style["font"]
                            if style.get("fill"): dst.fill = style["fill"]
                            if style.get("border"): dst.border = style["border"]
                            if style.get("alignment"): dst.alignment = style["alignment"]
                            if style.get("number_format"): dst.number_format = style["number_format"]

        # --- Phase 2: Apply prices ---
        current_format = None
        current_price = None
        current_extra = None
        success_count = 0
        total_codes = 0

        for r in range(1, ws.max_row + 1):
            cell_val = str(ws.cell(row=r, column=1).value or "").strip().upper()

            dim = extract_dim_from_header(cell_val)
            if dim is not None:
                current_format = cell_val
                fmt_data = mapping.get(current_format, {})
                p = fmt_data.get("price")
                e = fmt_data.get("extra")
                if p is not None and e is not None and str(p) != "" and str(e) != "":
                    try:
                        current_price = float(p)
                        current_extra = float(e)
                    except (ValueError, TypeError):
                        current_price = None
                        current_extra = None
                else:
                    current_price = None
                    current_extra = None
                continue

            num_code = re.sub(r'\D', '', cell_val)
            if not num_code or len(num_code) < 4:
                continue

            total_codes += 1

            if current_price is not None and current_extra is not None:
                set_price_cell(ws, r, 2, current_price)
                set_price_cell(ws, r, 3, current_price + current_extra)
                success_count += 1

        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        b64_excel = base64.b64encode(out.read()).decode('utf-8')

        return JSONResponse(content={
            "success": True,
            "success_count": success_count,
            "total_codes": total_codes,
            "excel_base64": b64_excel
        })

    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "detail": traceback.format_exc()}
        )


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
import sys
try:
    if getattr(sys, 'frozen', False):
        public_path = os.path.join(sys._MEIPASS, "public")
    else:
        public_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
    if os.path.isdir(public_path):
        app.mount("/", StaticFiles(directory=public_path, html=True), name="public")
    else:
        print(f"Warning: public directory not found at {public_path}")
except Exception as e:
    print(f"Warning: Could not mount static files: {e}")
