from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from typing import Literal

from sqlalchemy import text

from crewai_demo.db import get_engine, get_db_settings


ALLOWED_TABLES = {
    "insumos",
    "recetas",
    "productos_terminados",
    "presupuesto_ventas_kilos",
    "ventas",
}


@dataclass(frozen=True)
class ChatResult:
    session_id: str
    usuario_pregunta: str
    ia_respuesta: str
    query_generada: str
    report_format: Literal["md", "pdf", ""] = ""
    report_download_path: str = ""
    report_md: str = ""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        # keep precision reasonably; float is fine for UI/LLM summaries
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(val) for k, val in v.items()}
    return str(v)


def _dumps_jsonable(obj: Any) -> str:
    return json.dumps(_jsonable(obj), ensure_ascii=False)


_GREET_RE = re.compile(r"^\s*(hola|buenas|buenos dias|buen día|buenas tardes|buenas noches|hey|hi)\s*[!.]*\s*$", re.I)
_YES_RE = re.compile(r"^\s*(si|sí|dale|ok|okay|de una|confirmo|confirmar|y|yes)\s*[!.]*\s*$", re.I)
_NO_RE = re.compile(r"^\s*(no|nop|mejor no|cancelar|cancela|dejalo|déjalo)\s*[!.]*\s*$", re.I)

# In-memory session state (good enough for single-process demo).
_PENDING_REPORT_CONFIRMATION: set[str] = set()


def _wants_report(msg: str) -> bool:
    s = (msg or "").lower()
    keys = [
        "reporte",
        "informe",
        "report",
        "pdf",
        ".pdf",
        "markdown",
        ".md",
        "descargar",
        "exportar",
        "resumen de la conversacion",
        "resumen de la conversación",
    ]
    return any(k in s for k in keys)


def _is_db_related(msg: str) -> bool:
    s = (msg or "").lower()
    # table names + common business intents
    keys = [
        "insumo",
        "insumos",
        "receta",
        "recetas",
        "producto",
        "productos",
        "productos terminados",
        "productos_terminados",
        "presupuesto",
        "presupuesto_ventas_kilos",
        "kilos",
        "ventas",
        "venta",
        "cliente",
        "top",
        "stock",
        "costo",
        "precio",
        "cantidad",
        "kg",
        "anio",
        "año",
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return any(k in s for k in keys)


def _should_skip_db_query(msg: str) -> bool:
    m = (msg or "").strip()
    if not m:
        return True
    if _GREET_RE.match(m):
        return True
    # too short / ambiguous prompts are better handled with a clarification
    if len(m) < 4:
        return True
    return False


def _fallback_answer_for_short_message(msg: str) -> str:
    m = (msg or "").strip().lower()
    if _GREET_RE.match(m):
        return (
            "Hola. Puedo ayudarte con datos de insumos, recetas, productos terminados y ventas.\n"
            "Por ejemplo: “top 5 clientes por ventas”, “stock de X”, “ventas del último mes”, “receta del producto Y”."
        )
    return "¿Podés darme un poco más de detalle? Ej: “ventas del último mes”, “top 5 clientes”, “stock de cacao”."


def generate_conversational_answer(usuario_pregunta: str) -> str:
    prompt = (
        "Sos un asistente conversacional para Chocolart. Respondé en español, amable y útil.\n"
        "Si el usuario no pregunta por datos concretos, conversá normalmente y ofrecé ejemplos.\n"
        "Si el usuario pregunta por datos, sugerí cómo formularlo (top N, rango de fechas, producto, cliente, etc.).\n\n"
        f"Usuario: {usuario_pregunta}\n\n"
        "Return JSON: {\"answer\": \"...\"}"
    )
    data = _llm_json(prompt)
    ans = str(data.get("answer") or "").strip()
    return ans or _fallback_answer_for_short_message(usuario_pregunta)


def _ask_report_confirmation() -> str:
    return "¿Querés que genere un informe de esta conversación? Respondé **sí** o **no**. (Podés pedirlo en .md o .pdf)"


def _report_download_path(session_id: str, fmt: str) -> str:
    return f"/api/chat/report/{session_id}.{fmt}"


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
    # rough table extraction: words after FROM/JOIN
    tables = set(re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_]+)", s))
    if not tables:
        return False
    return tables.issubset(ALLOWED_TABLES)


def _ensure_limit(sql: str, limit: int = 50) -> str:
    s = sql.strip()
    if re.search(r"\blimit\s+\d+\b", s, flags=re.IGNORECASE):
        return s
    return f"{s}\nLIMIT {int(limit)}"


def _schema_overview() -> dict[str, list[str]]:
    """
    Reads allowed tables/columns from information_schema for the current DB.
    """
    engine = get_engine()
    db_name = get_db_settings().database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    overview: dict[str, list[str]] = {t: [] for t in sorted(ALLOWED_TABLES)}
    # NOTE: Use explicit OR list to avoid dialect-specific IN expansion issues with text().
    where_tables = " OR ".join([f"table_name = :t{i}" for i, _ in enumerate(sorted(ALLOWED_TABLES))])
    q = text(
        f"""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = :db
          AND ({where_tables})
        ORDER BY table_name, ordinal_position
        """
    )
    params: dict[str, Any] = {"db": db_name}
    for i, t in enumerate(sorted(ALLOWED_TABLES)):
        params[f"t{i}"] = t
    with engine.connect() as conn:
        rows = conn.execute(q, params).fetchall()
    for table_name, column_name in rows:
        if table_name in overview:
            overview[table_name].append(column_name)
    return overview


def _llm_json(prompt: str) -> dict[str, Any]:
    """
    Uses litellm (pulled in by crewai) to call the configured model.
    """
    import os

    model = os.getenv("MODEL") or "gpt-4o-mini"
    try:
        from litellm import completion  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"litellm not available (install crewai deps). {e}")

    resp = completion(
        model=model,
        messages=[
            {"role": "system", "content": "Respond ONLY with valid JSON. No markdown, no extra text."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    content = resp["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except Exception as e:
        # try to salvage a JSON object embedded in text
        m = re.search(r"\{[\s\S]*\}", content or "")
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        raise RuntimeError(f"Model did not return JSON. content={content!r}. error={e}")


def generate_sql(usuario_pregunta: str) -> str:
    schema = _schema_overview()
    prompt = (
        "You are a senior data analyst. Generate ONE MySQL SELECT query to answer the user's question.\n"
        "Rules:\n"
        "- Output JSON with keys: sql\n"
        "- Only SELECT (no writes).\n"
        "- Only use these tables: " + ", ".join(sorted(ALLOWED_TABLES)) + "\n"
        "- Prefer selecting specific columns.\n"
        "- Add WHERE clauses that match the question.\n"
        "- Keep it simple and deterministic.\n\n"
        f"Schema (columns): {_dumps_jsonable(schema)}\n\n"
        f"User question (Spanish): {usuario_pregunta}\n"
    )
    data = _llm_json(prompt)
    sql = str(data.get("sql") or "").strip()
    if not sql:
        # one retry with a stricter instruction
        data2 = _llm_json(
            prompt
            + "\nIMPORTANT: Return JSON like {\"sql\": \"SELECT ...\"} and nothing else. "
            + "The SQL must include FROM and reference at least one allowed table."
        )
        sql = str(data2.get("sql") or "").strip()
    if not sql:
        raise RuntimeError("Model returned empty SQL")
    if not _is_safe_select(sql):
        raise RuntimeError("Generated SQL rejected: not a safe SELECT")
    if not _mentions_only_allowed_tables(sql):
        raise RuntimeError("Generated SQL rejected: uses non-allowed tables")
    return _ensure_limit(sql, 50)


def run_query(sql: str) -> list[dict[str, Any]]:
    engine = get_engine()
    with engine.connect() as conn:
        res = conn.execute(text(sql))
        cols = list(res.keys())
        out: list[dict[str, Any]] = []
        for row in res.fetchall():
            out.append({cols[i]: _jsonable(row[i]) for i in range(len(cols))})
        return out


def generate_answer(usuario_pregunta: str, rows: list[dict[str, Any]]) -> str:
    prompt = (
        "Eres un asistente para el negocio Chocolart. Responde en español, claro y breve.\n"
        "Si hay filas, sintetiza los hallazgos. Si no hay datos, explica que no se encontraron coincidencias.\n\n"
        f"Pregunta del usuario: {usuario_pregunta}\n"
        f"Filas (JSON): {_dumps_jsonable(rows)}\n"
    )
    data = _llm_json(f"{prompt}\n\nReturn JSON: {{\"answer\": \"...\"}}")
    ans = str(data.get("answer") or "").strip()
    return ans or "No encontré datos suficientes para responder con la información disponible."


def _insert_historico_chat_ai(session_id: str, usuario_pregunta: str, ia_respuesta: str, query_generada: str) -> None:
    """
    Inserts using the intersection of known columns to survive minor schema variations.
    """
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
        # Schema in provided dump uses `fecha_registro` with default CURRENT_TIMESTAMP.
        # If present and NOT defaulted, we provide it; otherwise we let MySQL default.
        if "fecha_registro" in colset:
            # leaving it out is ok; but include if column is NOT NULL without default in future variants
            pass
        if "tipo_pregunta" in colset:
            payload["tipo_pregunta"] = 0

        if not payload:
            return

        columns = ", ".join(f"`{k}`" for k in payload.keys())
        values = ", ".join(f":{k}" for k in payload.keys())
        conn.execute(text(f"INSERT INTO `historico_chat_ai` ({columns}) VALUES ({values})"), payload)
        conn.commit()


def chat(session_id: str, usuario_pregunta: str) -> ChatResult:
    msg = (usuario_pregunta or "").strip()

    # Handle pending report confirmation flow.
    if session_id in _PENDING_REPORT_CONFIRMATION:
        if _YES_RE.match(msg):
            _PENDING_REPORT_CONFIRMATION.discard(session_id)
            from crewai_demo.reporting import generate_markdown_report, generate_pdf_from_markdown

            want_pdf = "pdf" in msg.lower()
            md = generate_markdown_report(session_id)
            report_format: Literal["md", "pdf", ""] = "md"
            dl = _report_download_path(session_id, "md")
            if want_pdf:
                generate_pdf_from_markdown(session_id, md=md)
                report_format = "pdf"
                dl = _report_download_path(session_id, "pdf")

            answer = f"Listo. Generé el informe ({report_format}). Podés descargarlo desde la pestaña **Informe**."
            _insert_historico_chat_ai(
                session_id=session_id,
                usuario_pregunta=usuario_pregunta,
                ia_respuesta=answer,
                query_generada="",
            )
            return ChatResult(
                session_id=session_id,
                usuario_pregunta=usuario_pregunta,
                ia_respuesta=answer,
                query_generada="",
                report_format=report_format,
                report_download_path=dl,
                report_md=md if report_format == "md" else "",
            )
        if _NO_RE.match(msg):
            _PENDING_REPORT_CONFIRMATION.discard(session_id)
            answer = "Perfecto, no genero informe. Si más adelante lo necesitás, decime “haceme un reporte”."
            _insert_historico_chat_ai(
                session_id=session_id,
                usuario_pregunta=usuario_pregunta,
                ia_respuesta=answer,
                query_generada="",
            )
            return ChatResult(session_id=session_id, usuario_pregunta=usuario_pregunta, ia_respuesta=answer, query_generada="")

        answer = _ask_report_confirmation()
        _insert_historico_chat_ai(
            session_id=session_id,
            usuario_pregunta=usuario_pregunta,
            ia_respuesta=answer,
            query_generada="",
        )
        return ChatResult(session_id=session_id, usuario_pregunta=usuario_pregunta, ia_respuesta=answer, query_generada="")

    # Detect report intent and ask for confirmation.
    if _wants_report(msg):
        _PENDING_REPORT_CONFIRMATION.add(session_id)
        answer = _ask_report_confirmation()
        _insert_historico_chat_ai(
            session_id=session_id,
            usuario_pregunta=usuario_pregunta,
            ia_respuesta=answer,
            query_generada="",
        )
        return ChatResult(session_id=session_id, usuario_pregunta=usuario_pregunta, ia_respuesta=answer, query_generada="")

    if _should_skip_db_query(usuario_pregunta):
        answer = _fallback_answer_for_short_message(usuario_pregunta)
        sql = ""
        _insert_historico_chat_ai(
            session_id=session_id,
            usuario_pregunta=usuario_pregunta,
            ia_respuesta=answer,
            query_generada=sql,
        )
        return ChatResult(session_id=session_id, usuario_pregunta=usuario_pregunta, ia_respuesta=answer, query_generada=sql)

    # Route: DB if message looks DB-related, otherwise conversational.
    if not _is_db_related(msg):
        answer = generate_conversational_answer(msg)
        _insert_historico_chat_ai(
            session_id=session_id,
            usuario_pregunta=usuario_pregunta,
            ia_respuesta=answer,
            query_generada="",
        )
        return ChatResult(session_id=session_id, usuario_pregunta=usuario_pregunta, ia_respuesta=answer, query_generada="")

    sql = generate_sql(usuario_pregunta)
    rows = run_query(sql)
    answer = generate_answer(usuario_pregunta, rows)
    _insert_historico_chat_ai(
        session_id=session_id,
        usuario_pregunta=usuario_pregunta,
        ia_respuesta=answer,
        query_generada=sql,
    )
    return ChatResult(
        session_id=session_id,
        usuario_pregunta=usuario_pregunta,
        ia_respuesta=answer,
        query_generada=sql,
    )


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

