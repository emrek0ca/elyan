"""
Elyan Data Tools — CSV/JSON/Parquet analysis, statistics, pivot tables

pandas-powered data analysis with graceful fallback.
"""

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("data_tools")


async def read_csv(file_path: str, limit: int = 100) -> Dict[str, Any]:
    """Read a CSV file and return structured data."""
    try:
        rows = []
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for i, row in enumerate(reader):
                if i >= limit:
                    break
                rows.append(dict(row))
        return {
            "success": True,
            "headers": headers,
            "rows": rows,
            "total_returned": len(rows),
            "limited": len(rows) >= limit,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def read_json(file_path: str) -> Dict[str, Any]:
    """Read a JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "success": True,
            "data": data,
            "type": type(data).__name__,
            "size": len(data) if isinstance(data, (list, dict)) else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def analyze_data(file_path: str) -> Dict[str, Any]:
    """Analyze a data file (CSV/JSON) and return statistics."""
    try:
        import pandas as pd
        ext = Path(file_path).suffix.lower()

        if ext == ".csv":
            df = pd.read_csv(file_path)
        elif ext == ".json":
            df = pd.read_json(file_path)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        elif ext == ".parquet":
            df = pd.read_parquet(file_path)
        else:
            return {"success": False, "error": f"Unsupported file: {ext}"}

        stats = {
            "shape": {"rows": df.shape[0], "columns": df.shape[1]},
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "missing": {col: int(count) for col, count in df.isnull().sum().items() if count > 0},
            "numeric_summary": {},
        }

        numeric_cols = df.select_dtypes(include=["number"]).columns
        for col in numeric_cols:
            stats["numeric_summary"][col] = {
                "mean": round(float(df[col].mean()), 4),
                "median": round(float(df[col].median()), 4),
                "std": round(float(df[col].std()), 4),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
            }

        return {"success": True, "analysis": stats}

    except ImportError:
        return {"success": False, "error": "pandas not installed. Run: pip install pandas"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def data_query(file_path: str, query: str) -> Dict[str, Any]:
    """Run a pandas query on a data file."""
    try:
        import pandas as pd
        ext = Path(file_path).suffix.lower()

        if ext == ".csv":
            df = pd.read_csv(file_path)
        elif ext == ".json":
            df = pd.read_json(file_path)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        else:
            return {"success": False, "error": f"Unsupported: {ext}"}

        result = df.query(query)
        return {
            "success": True,
            "rows": result.head(100).to_dict("records"),
            "total_matches": len(result),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
