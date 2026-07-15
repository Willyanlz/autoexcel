"""Funções auxiliares para manipulação de planilhas Excel."""

import re

CURRENCY_FMT = '#,##0.00" "[$R$-pt-BR]'


def extract_dim_from_header(cell_val: str) -> str | None:
    """Extrai dimensão no formato 'LARGURAxALTURA' de um cabeçalho de formato."""
    m = re.search(r'(\d+)(?:[,.](?:\d+))?\s*[xX×]\s*(\d+)(?:[,.](?:\d+))?', cell_val)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}"
    return None


def set_price_cell(ws, row, col, value):
    """Define valor de preço em uma célula com formatação de moeda."""
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = CURRENCY_FMT


def scan_excel_formats(ws):
    """Escaneia a planilha e retorna um dict {cabeçalho: [códigos]} agrupado por formato."""
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