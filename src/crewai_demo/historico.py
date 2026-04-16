from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from crewai_demo.db import get_db_settings, get_engine


def _jsonable(v: Any) -> Any:
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


def dumps_jsonable(obj: Any) -> str:
    return json.dumps(_jsonable(obj), ensure_ascii=False)


def insert_historico_chat_ai(session_id: str, usuario_pregunta: str, ia_respuesta: str, query_generada: str) -> None:
    engine = get_engine()
    db_name = get_db_settings().database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    with engine.connect() as conn:
        cols = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :db
                  AND table_name = 'historico_chat_ai'
                """
            ),
            {"db": db_name},
        ).fetchall()
        colset = {c[0] for c in cols}

        payload: dict[str, Any] = {}
        if "session_id" in colset:
            payload["session_id"] = session_id
        if "ia_respuesta" in colset:
            payload["ia_respuesta"] = ia_respuesta
        if "usuario_pregunta" in colset:
            payload["usuario_pregunta"] = usuario_pregunta
        if "query_generada" in colset:
            payload["query_generada"] = query_generada
        if "tipo_pregunta" in colset:
            payload["tipo_pregunta"] = 0

        if not payload:
            return

        columns = ", ".join(f"`{k}`" for k in payload.keys())
        values = ", ".join(f":{k}" for k in payload.keys())
        conn.execute(text(f"INSERT INTO `historico_chat_ai` ({columns}) VALUES ({values})"), payload)
        conn.commit()


def get_history(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    engine = get_engine()
    db_name = get_db_settings().database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    with engine.connect() as conn:
        cols_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :db
                  AND table_name = 'historico_chat_ai'
                """
            ),
            {"db": db_name},
        ).fetchall()
        colset = {c[0] for c in cols_rows}
        if "fecha_registro" in colset:
            order = "`fecha_registro` DESC"
        elif "created_at" in colset:
            order = "`created_at` DESC"
        elif "id" in colset:
            order = "`id` DESC"
        else:
            order = "`session_id` DESC"

        res = conn.execute(
            text(
                f"""
                SELECT *
                FROM historico_chat_ai
                WHERE session_id = :sid
                ORDER BY {order}
                LIMIT :lim
                """
            ),
            {"sid": session_id, "lim": int(limit)},
        )
        cols = list(res.keys())
        rows = res.fetchall()
        return [{cols[i]: _jsonable(r[i]) for i in range(len(cols))} for r in rows]
