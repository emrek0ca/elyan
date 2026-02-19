"""Excel Tools - Advanced Read, Write, and Analysis for .xlsx files"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Union, Optional
from utils.logger import get_logger
from security.validator import validate_path
from config.settings import HOME_DIR, DESKTOP
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

try:
    import pandas as pd  # Optional dependency
except Exception:  # pragma: no cover - environment dependent
    pd = None

logger = get_logger("office.excel")

# Maximum file size (20MB for advanced analysis)
MAX_FILE_SIZE = 20 * 1024 * 1024

async def read_excel(
    path: str,
    sheet_name: Union[str, int, None] = None,
    use_pandas: bool = True
) -> dict[str, Any]:
    """Read content from an Excel file with advanced options."""
    try:
        is_valid, error, _ = validate_path(path)
        if not is_valid: return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()
        if not file_path.exists(): return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        def _read():
            if use_pandas and pd is not None:
                df = pd.read_excel(str(file_path), sheet_name=sheet_name)
                if isinstance(df, dict):
                    result_data = {s: d.to_dict(orient='records') for s, d in df.items()}
                    summary = {s: f"{len(d)} satır, {len(d.columns)} sütun" for s, d in df.items()}
                else:
                    result_data = df.to_dict(orient='records')
                    summary = f"{len(df)} satır, {len(df.columns)} sütun"
                return result_data, summary, list(df.keys()) if isinstance(df, dict) else [sheet_name or "active"]
            wb = load_workbook(str(file_path), data_only=False)
            ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
            data = []
            for row in ws.iter_rows(values_only=True):
                data.append(list(row))
            return data, f"{len(data)} satır", wb.sheetnames

        loop = asyncio.get_event_loop()
        data, summary, sheets = await loop.run_in_executor(None, _read)

        return {
            "success": True,
            "path": str(file_path),
            "data": data,
            "summary": summary,
            "sheets": sheets,
            "row_count": len(data) if not isinstance(data, dict) else sum(len(v) for v in data.values())
        }
    except Exception as e:
        logger.error(f"Read Excel error: {e}")
        return {"success": False, "error": str(e)}

async def write_excel(
    path: str = None,
    data: Any = None,
    headers: Any = None,
    sheet_name: str = "Sheet1"
) -> dict[str, Any]:
    """Professional Excel writing with styling and formula support."""
    try:
        if not path: path = str(DESKTOP / "tablo.xlsx")
        file_path = Path(path).expanduser().resolve()
        if not file_path.suffix.lower() == ".xlsx": file_path = file_path.with_suffix(".xlsx")

        is_valid, error, _ = validate_path(str(file_path))
        if not is_valid: return {"success": False, "error": error}

        def _write():
            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name

            if not data: return False

            # Convert simple data to standardized format
            rows = []
            if isinstance(data, list):
                if data and isinstance(data[0], dict):
                    rows = data
                    cols = headers or list(data[0].keys())
                else:
                    cols = headers or [f"Sütun{i+1}" for i in range(len(data[0]))]
                    for r in data:
                        rows.append(dict(zip(cols, r)))
            
            # Write headers
            for c_idx, header in enumerate(cols, 1):
                cell = ws.cell(row=1, column=c_idx, value=header)
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
                cell.alignment = Alignment(horizontal='center')

            # Write data
            for r_idx, row_dict in enumerate(rows, 2):
                for c_idx, header in enumerate(cols, 1):
                    val = row_dict.get(header, "")
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    if isinstance(val, str) and val.startswith("="):
                        cell.value = val

            # Auto-adjust column widths
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except: pass
                ws.column_dimensions[column].width = min(max_length + 2, 50)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(str(file_path))
            return True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)
        return {"success": True, "path": str(file_path), "row_count": len(data) if isinstance(data, list) else 0}
    except Exception as e:
        logger.error(f"Write Excel error: {e}")
        return {"success": False, "error": str(e)}

async def analyze_excel_data(path: str, query: str) -> dict[str, Any]:
    """Perform complex data analysis using Pandas."""
    try:
        if pd is None:
            return {"success": False, "error": "Pandas kurulu değil. Gelişmiş analiz için 'pip install pandas' gerekli."}
        file_path = Path(path).expanduser().resolve()
        df = pd.read_excel(str(file_path))
        summary = {
            "columns": list(df.columns),
            "stats": df.describe().to_dict(),
            "null_counts": df.isnull().sum().to_dict()
        }
        return {"success": True, "analysis": summary}
    except Exception as e:
        return {"success": False, "error": str(e)}
