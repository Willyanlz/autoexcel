import os
import io
import json
import asyncio
from typing import List

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import openpyxl

from api.helpers import scan_excel_formats
from api.errors import humanize_error
from api.ai import extract_from_image_via_ai
from api.excel import (
    merge_ai_products,
    build_formats_list,
    rebuild_product_rows,
    apply_prices,
    save_excel_to_base64,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/analyze")
async def analyze(
    excel: UploadFile = File(...),
    images: List[UploadFile] = File(None),
    api_key: str = Form(""),
    llm_model: str = Form(""),
):
    try:
        excel_bytes = await excel.read()
        if not excel_bytes:
            return JSONResponse(content={"error": "Arquivo Excel vazio."}, status_code=400)

        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = wb.active
        formats = scan_excel_formats(ws)

        ai_products, ai_errors = [], []

        if images:
            for img in images:
                data = await img.read()
                if not data:
                    continue
                if not api_key:
                    ai_errors.append("API Key não informada. Configure sua chave do OpenRouter.")
                    continue
                prods, err = await extract_from_image_via_ai(
                    data, img.content_type or "image/png", api_key, llm_model
                )
                if err:
                    ai_errors.append(err)
                ai_products.extend(prods)

        merge_ai_products(formats, ai_products)

        return {
            "formats": build_formats_list(formats),
            "ai_count": len(ai_products),
            "ai_errors": ai_errors,
        }

    except Exception as e:
        import traceback

        return JSONResponse(
            content={"error": humanize_error(str(e)), "detail": traceback.format_exc()}, status_code=500
        )


@app.post("/api/process")
async def process_manual(excel: UploadFile = File(...), mapping_json: str = Form("{}")):
    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError:
        return JSONResponse(
            content={"success": False, "error": "JSON inválido no mapeamento."}, status_code=400
        )

    try:
        data = await excel.read()
        if not data:
            return JSONResponse(content={"success": False, "error": "Arquivo Excel vazio."}, status_code=400)

        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active

        rebuild_product_rows(ws, mapping)
        ok, total = apply_prices(ws, mapping)

        return {
            "success": True,
            "success_count": ok,
            "total_codes": total,
            "excel_base64": save_excel_to_base64(wb),
        }

    except Exception as e:
        import traceback

        return JSONResponse(
            content={"success": False, "error": humanize_error(str(e)), "detail": traceback.format_exc()},
            status_code=500,
        )


# ── Static frontend ──────────────────────────────────────────────
import sys

try:
    if getattr(sys, "frozen", False):
        public_path = os.path.join(sys._MEIPASS, "public")
    else:
        public_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
    if os.path.isdir(public_path):
        app.mount("/", StaticFiles(directory=public_path, html=True), name="public")
except Exception as e:
    print(f"Warning: Could not mount static files: {e}")