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

        def _normalize_rows(raw_data: Any, raw_headers: Any) -> tuple[list[str], list[dict[str, Any]]]:
            cols: list[str] = []
            rows: list[dict[str, Any]] = []

            if isinstance(raw_headers, list):
                cols = [str(h).strip() for h in raw_headers if str(h).strip()]
            elif isinstance(raw_headers, tuple):
                cols = [str(h).strip() for h in list(raw_headers) if str(h).strip()]

            if raw_data is None:
                return cols, rows

            if isinstance(raw_data, dict):
                if not cols:
                    cols = [str(k) for k in raw_data.keys()]
                rows.append({k: raw_data.get(k, "") for k in cols})
                return cols, rows

            if isinstance(raw_data, (list, tuple)):
                data_list = list(raw_data)
                if not data_list:
                    return cols, rows

                first = data_list[0]
                if isinstance(first, dict):
                    if not cols:
                        ordered_keys = []
                        for item in data_list:
                            if isinstance(item, dict):
                                for key in item.keys():
                                    s_key = str(key)
                                    if s_key not in ordered_keys:
                                        ordered_keys.append(s_key)
                        cols = ordered_keys
                    for item in data_list:
                        if isinstance(item, dict):
                            rows.append({k: item.get(k, "") for k in cols})
                        else:
                            rows.append({cols[0]: str(item) if cols else str(item)})
                    return cols, rows

                if isinstance(first, (list, tuple)):
                    matrix = [list(r) for r in data_list]
                    width = max(len(r) for r in matrix) if matrix else 0
                    if not cols:
                        cols = [f"Sütun{i+1}" for i in range(width)]
                    for row_values in matrix:
                        padded = list(row_values) + [""] * max(0, len(cols) - len(row_values))
                        rows.append({col: padded[idx] if idx < len(padded) else "" for idx, col in enumerate(cols)})
                    return cols, rows

                # list/tuple of scalar values -> single column
                if not cols:
                    cols = ["Veri"]
                for item in data_list:
                    rows.append({cols[0]: item})
                return cols, rows

            # scalar fallback
            if not cols:
                cols = ["Veri"]
            rows.append({cols[0]: raw_data})
            return cols, rows

        def _write():
            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name

            cols, rows = _normalize_rows(data, headers)
            if not cols or not rows:
                return False, 0

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
            return True, len(rows)

        loop = asyncio.get_event_loop()
        wrote, row_count = await loop.run_in_executor(None, _write)
        if not wrote:
            return {"success": False, "error": "Yazılacak veri bulunamadı (data boş)."}

        # Post-check validation
        if not file_path.exists():
            return {"success": False, "error": "WRITE_FAILED: Dosya diskte bulunamadı.", "error_code": "FILE_NOT_FOUND"}
        
        file_size = file_path.stat().st_size
        if file_size < 1000: # Minimum xlsx structure size
            return {
                "success": False, 
                "error": f"WRITE_POSTCHECK_FAILED: Excel dosyası boyutu şüpheli şekilde küçük ({file_size} bytes).",
                "error_code": "WRITE_POSTCHECK_FAILED"
            }

        return {"success": True, "path": str(file_path), "row_count": row_count, "size_bytes": file_size}
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
