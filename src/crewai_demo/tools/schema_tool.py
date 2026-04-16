from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from sqlalchemy import text

from crewai_demo.db import get_db_settings, get_engine
from crewai_demo.tools.db_allowed import ALLOWED_TABLES

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
_USER_SCHEMA_PATH = _CONFIG_DIR / "db_schema.yaml"

_introspection_cache: dict[str, Any] | None = None
_introspection_cache_ts: float = 0.0
_CACHE_TTL_SEC = 120.0


def _try_load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_tables_arg(tables: str) -> frozenset[str]:
    s = (tables or "").strip().lower()
    if not s or s == "all":
        return ALLOWED_TABLES
    names = {t.strip() for t in s.split(",") if t.strip()}
    unknown = names - ALLOWED_TABLES
    if unknown:
        raise ValueError(f"Tablas no permitidas: {', '.join(sorted(unknown))}")
    return frozenset(names)


def _introspect_columns(tables: frozenset[str]) -> dict[str, list[dict[str, Any]]]:
    engine = get_engine()
    db_name = get_db_settings().database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not tables:
        return {}
    where = " OR ".join([f"table_name = :t{i}" for i, _ in enumerate(sorted(tables))])
    q = text(
        f"""
        SELECT table_name, column_name, data_type, column_type, is_nullable, column_comment
        FROM information_schema.columns
        WHERE table_schema = :db
          AND ({where})
        ORDER BY table_name, ordinal_position
        """
    )
    params: dict[str, Any] = {"db": db_name}
    for i, t in enumerate(sorted(tables)):
        params[f"t{i}"] = t
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in sorted(tables)}
    with engine.connect() as conn:
        rows = conn.execute(q, params).fetchall()
    for table_name, column_name, data_type, column_type, is_nullable, column_comment in rows:
        if table_name not in out:
            continue
        out[table_name].append(
            {
                "name": column_name,
                "data_type": data_type,
                "column_type": column_type,
                "is_nullable": is_nullable,
                "comment": column_comment or "",
            }
        )
    return out


def _get_introspection_cached(tables: frozenset[str]) -> dict[str, list[dict[str, Any]]]:
    global _introspection_cache, _introspection_cache_ts
    now = time.monotonic()
    if _introspection_cache is not None and (now - _introspection_cache_ts) < _CACHE_TTL_SEC:
        return {t: list(_introspection_cache.get(t, [])) for t in tables}
    full = _introspect_columns(ALLOWED_TABLES)
    _introspection_cache = full
    _introspection_cache_ts = now
    return {t: list(full.get(t, [])) for t in tables}


def _normalize_user_columns(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    if len(raw) == 0:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"name": item, "type": "", "description": ""})
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("column") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "type": str(item.get("type") or item.get("data_type") or ""),
                    "description": str(item.get("description") or item.get("comment") or ""),
                }
            )
    return out


def _merge_schema(requested: frozenset[str]) -> dict[str, Any]:
    user_doc = _try_load_yaml(_USER_SCHEMA_PATH)
    user_tables = user_doc.get("tables") if isinstance(user_doc.get("tables"), dict) else {}

    introspected = _get_introspection_cached(requested)
    merged: dict[str, Any] = {"tables": {}}

    for table in sorted(requested):
        uentry = user_tables.get(table) if isinstance(user_tables.get(table), dict) else {}
        udesc = str(uentry.get("description") or "").strip()
        ucols = _normalize_user_columns(uentry.get("columns"))

        if ucols is not None and len(ucols) > 0:
            merged["tables"][table] = {
                "source": "db_schema.yaml",
                "description": udesc,
                "columns": ucols,
            }
            continue

        cols = introspected.get(table) or []
        merged["tables"][table] = {
            "source": "information_schema",
            "description": udesc,
            "columns": cols,
        }
    return merged


class SchemaQueryInput(BaseModel):
    tables: str = Field(
        "all",
        description='Lista separada por comas de tablas permitidas, o la palabra "all" para todas.',
    )


class DatabaseSchemaTool(BaseTool):
    name: str = "schema_mysql_chocolart"
    description: str = (
        "Devuelve el esquema (columnas y metadatos) de tablas de negocio permitidas en MySQL. "
        "Usala cuando necesites confirmar nombres de columnas, tipos o comentarios antes de armar un SELECT. "
        "No ejecuta consultas de negocio: solo describe estructura. "
        "Parámetro: tables = 'all' o por ejemplo 'ventas,insumos'."
    )
    args_schema: Type[BaseModel] = SchemaQueryInput

    def _run(self, tables: str = "all") -> str:
        try:
            requested = _parse_tables_arg(tables)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        try:
            payload = _merge_schema(requested)
            payload["allowed_tables"] = sorted(ALLOWED_TABLES)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps(payload, ensure_ascii=False)
