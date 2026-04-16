from __future__ import annotations

import json
import re
from contextvars import ContextVar
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from sqlalchemy import text

from crewai_demo.db import get_engine

ALLOWED_TABLES = frozenset(
    {
        "insumos",
        "recetas",
        "productos_terminados",
        "presupuesto_ventas_kilos",
        "ventas",
    }
)

_last_executed_sql: ContextVar[str] = ContextVar("last_executed_sql", default="")


def reset_last_executed_sql() -> None:
    _last_executed_sql.set("")


def get_last_executed_sql() -> str:
    return _last_executed_sql.get()


def _jsonable(v: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal

    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(val) for k, val in v.items()}
    return str(v)


def _is_safe_select(sql: str) -> bool:
    s = sql.strip().lower()
    if not s.startswith("select"):
        return False
    if ";" in s:
        return False
    banned = ["insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "create ", "grant ", "revoke "]
    if any(b in s for b in banned):
        return False
    return True


def _mentions_only_allowed_tables(sql: str) -> bool:
    s = sql.lower()
    tables = set(re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_]+)", s))
    if not tables:
        return False
    return tables.issubset(ALLOWED_TABLES)


def _ensure_limit(sql: str, limit: int = 50) -> str:
    s = sql.strip()
    if re.search(r"\blimit\s+\d+\b", s, flags=re.IGNORECASE):
        return s
    return f"{s}\nLIMIT {int(limit)}"


class DatabaseQueryInput(BaseModel):
    sql: str = Field(..., description="Una sola sentencia SELECT de MySQL sobre tablas permitidas.")


class DatabaseAnalyticsTool(BaseTool):
    name: str = "consulta_mysql_analytics"
    description: str = (
        "Ejecuta una consulta SELECT en MySQL para analizar datos de Chocolart. "
        "Solo se permiten estas tablas: insumos, recetas, productos_terminados, "
        "presupuesto_ventas_kilos, ventas. Prohibido INSERT/UPDATE/DELETE u otras sentencias. "
        "Devuelve filas como JSON (lista de objetos). Si la pregunta no requiere datos, no uses esta herramienta."
    )
    args_schema: Type[BaseModel] = DatabaseQueryInput

    def _run(self, sql: str) -> str:
        raw = (sql or "").strip()
        if not _is_safe_select(raw):
            return json.dumps({"error": "Solo se permiten consultas SELECT seguras."}, ensure_ascii=False)
        if not _mentions_only_allowed_tables(raw):
            return json.dumps({"error": "Solo se pueden consultar las tablas de negocio permitidas."}, ensure_ascii=False)
        bounded = _ensure_limit(raw, 50)
        engine = get_engine()
        try:
            with engine.connect() as conn:
                res = conn.execute(text(bounded))
                cols = list(res.keys())
                rows: list[dict[str, Any]] = []
                for row in res.fetchall():
                    rows.append({cols[i]: _jsonable(row[i]) for i in range(len(cols))})
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        _last_executed_sql.set(bounded)
        return json.dumps({"rows": rows, "row_count": len(rows)}, ensure_ascii=False)
