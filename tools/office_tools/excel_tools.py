"""Excel Tools - Read and Write .xlsx files"""

import asyncio
from pathlib import Path
from typing import Any
from utils.logger import get_logger
from security.validator import validate_path
from config.settings import HOME_DIR, DESKTOP

logger = get_logger("office.excel")

# Maximum file size (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


async def read_excel(
    path: str,
    sheet_name: str = None,
    max_rows: int = 100
) -> dict[str, Any]:
    """Read content from an Excel file (.xlsx)

    Args:
        path: Path to the Excel file
        sheet_name: Specific sheet to read (default: active sheet)
        max_rows: Maximum rows to return (default 100)
    """
    try:
        # Validate path
        is_valid, error, _ = validate_path(path)
        if not is_valid:
            return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()

        if not file_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        if not file_path.suffix.lower() in [".xlsx", ".xls"]:
            return {"success": False, "error": "Sadece .xlsx dosyaları destekleniyor"}

        # Check file size
        if file_path.stat().st_size > MAX_FILE_SIZE:
            return {"success": False, "error": "Dosya çok büyük (max 10MB)"}

        try:
            from openpyxl import load_workbook
        except ImportError:
            return {"success": False, "error": "openpyxl kurulu değil. 'pip install openpyxl' çalıştırın."}

        def _read():
            wb = load_workbook(str(file_path), read_only=True, data_only=True)

            # Get sheet
            if sheet_name and sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                ws = wb.active

            # Read data
            data = []
            headers = []

            for i, row in enumerate(ws.iter_rows(max_row=max_rows + 1, values_only=True)):
                if i == 0:
                    # First row as headers
                    headers = [str(cell) if cell else f"Sütun{j+1}" for j, cell in enumerate(row)]
                else:
                    row_data = {}
                    for j, cell in enumerate(row):
                        if j < len(headers):
                            row_data[headers[j]] = cell
                    if any(v is not None for v in row_data.values()):
                        data.append(row_data)

            sheet_names = wb.sheetnames
            wb.close()

            return data, headers, sheet_names, ws.title

        loop = asyncio.get_event_loop()
        data, headers, sheet_names, active_sheet = await loop.run_in_executor(None, _read)

        # Format as text table
        text_output = ""
        if data:
            # Create simple text table
            text_output = " | ".join(headers) + "\n"
            text_output += "-" * len(text_output) + "\n"
            for row in data[:20]:  # Show first 20 rows in text
                row_vals = [str(row.get(h, ""))[:30] for h in headers]
                text_output += " | ".join(row_vals) + "\n"
            if len(data) > 20:
                text_output += f"... +{len(data) - 20} satır daha"

        logger.info(f"Read Excel file: {file_path.name}, {len(data)} rows")

        return {
            "success": True,
            "path": str(file_path),
            "filename": file_path.name,
            "sheet": active_sheet,
            "sheets": sheet_names,
            "headers": headers,
            "data": data,
            "row_count": len(data),
            "text_output": text_output
        }

    except Exception as e:
        logger.error(f"Read Excel error: {e}")
        return {"success": False, "error": str(e)}


async def write_excel(
    path: str = None,
    data: list = None,
    headers: list = None,
    sheet_name: str = "Sheet1"
) -> dict[str, Any]:
    """Create or write to an Excel file (.xlsx)

    Args:
        path: Path for the file (default: Desktop/tablo.xlsx)
        data: List of dictionaries or list of lists with row data
        headers: Column headers (required if data is list of lists)
        sheet_name: Name of the sheet
    """
    try:
        # Default path
        if not path:
            path = str(DESKTOP / "tablo.xlsx")

        # Ensure .xlsx extension
        file_path = Path(path).expanduser().resolve()
        if not file_path.suffix.lower() == ".xlsx":
            file_path = file_path.with_suffix(".xlsx")

        # Validate path
        is_valid, error, _ = validate_path(str(file_path))
        if not is_valid:
            return {"success": False, "error": error}

        if not data:
            return {"success": False, "error": "Veri sağlanmadı"}

        # headers=True → ilk satır header, geri kalan satırlar veri
        if headers is True:
            headers = list(data[0])
            data = data[1:]
        elif headers is False or headers is None:
            headers = None

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment
        except ImportError:
            return {"success": False, "error": "openpyxl kurulu değil. 'pip install openpyxl' çalıştırın."}

        def _write():
            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name

            # Determine headers
            if isinstance(data[0], dict):
                cols = headers or list(data[0].keys())
            else:
                cols = headers or [f"Sütun{i+1}" for i in range(len(data[0]))]

            # Write headers
            for col_idx, header in enumerate(cols, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')

            # Write data
            for row_idx, row_data in enumerate(data, 2):
                if isinstance(row_data, dict):
                    for col_idx, header in enumerate(cols, 1):
                        ws.cell(row=row_idx, column=col_idx, value=row_data.get(header, ""))
                else:
                    for col_idx, value in enumerate(row_data, 1):
                        ws.cell(row=row_idx, column=col_idx, value=value)

            # Auto-adjust column widths
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                ws.column_dimensions[column].width = min(max_length + 2, 50)

            # Create parent directory if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            wb.save(str(file_path))
            return True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)

        logger.info(f"Created Excel file: {file_path.name}, {len(data)} rows")

        return {
            "success": True,
            "path": str(file_path),
            "filename": file_path.name,
            "row_count": len(data),
            "sheet": sheet_name
        }

    except Exception as e:
        logger.error(f"Write Excel error: {e}")
        return {"success": False, "error": str(e)}
