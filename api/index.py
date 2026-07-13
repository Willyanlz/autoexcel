import os
import io
import re
import json
import base64
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import openpyxl

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_dim_from_header(cell_val: str) -> str | None:
    """Extract normalized dimension from a FORMATO header."""
    m = re.search(r'(\d+)(?:[,.](?:\d+))?\s*[xX×]\s*(\d+)(?:[,.](?:\d+))?', cell_val)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}"
    return None

def set_price_cell(ws, row, col, value):
    """Write a price value and apply R$ currency formatting."""
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = '#,##0.00" "[$R$-pt-BR]'

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/extract-formats")
async def extract_formats(excel: UploadFile = File(...)):
    """Reads Excel and returns a list of unique FORMATOS."""
    try:
        excel_bytes = await excel.read()
        if not excel_bytes:
            return JSONResponse(status_code=400, content={"error": "Arquivo Excel vazio."})
            
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = wb.active
        
        unique_formats = set()
        
        for r in range(1, ws.max_row + 1):
            cell_val = str(ws.cell(row=r, column=1).value or "").strip().upper()
            
            # Identify formats
            dim = extract_dim_from_header(cell_val)
            if dim is not None:
                unique_formats.add(cell_val) # Save the whole name, like "FORMATO 58x58" or "RETIFICADO 31x56"
                
        # Sort alphabetically
        formats_list = sorted(list(unique_formats))
        
        return {"formats": formats_list}
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "detail": traceback.format_exc()}
        )


@app.post("/api/process-manual")
async def process_manual(
    excel: UploadFile = File(...),
    mapping_json: str = Form("{}")
):
    """
    mapping_json format:
    {
      "FORMATO 58x58": { "price": 12.70, "extra": 3.00 },
      ...
    }
    """
    try:
        mapping = json.loads(mapping_json)
        
        excel_bytes = await excel.read()
        if not excel_bytes:
            raise HTTPException(status_code=400, detail="Arquivo Excel vazio.")
            
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        
        current_format = None
        current_price = None
        current_extra = None
        
        success_count = 0
        total_codes = 0
        
        for r in range(1, ws.max_row + 1):
            cell_val = str(ws.cell(row=r, column=1).value or "").strip().upper()
            
            # Check if this row is a header
            dim = extract_dim_from_header(cell_val)
            if dim is not None:
                current_format = cell_val
                if current_format in mapping:
                    current_price = mapping[current_format].get("price")
                    current_extra = mapping[current_format].get("extra")
                else:
                    current_price = None
                    current_extra = None
                continue
                
            # If it's not a header, check if it's a product code (minimum 4 digits)
            num_code = re.sub(r'\D', '', cell_val)
            if not num_code or len(num_code) < 4:
                continue
                
            total_codes += 1
            
            # Fill the row based on the current active format
            if current_price is not None and current_extra is not None:
                # Column 2: Base Price
                set_price_cell(ws, r, 2, float(current_price))
                # Column 3: Fractioned Price (Base + Extra)
                set_price_cell(ws, r, 3, float(current_price) + float(current_extra))
                success_count += 1
            else:
                # Format not mapped, leave empty or mark
                ws.cell(row=r, column=2, value="PREENCHA")
                ws.cell(row=r, column=3, value="PREENCHA")

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
