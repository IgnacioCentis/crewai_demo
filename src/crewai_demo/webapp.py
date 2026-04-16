"""Local web UI to run the crew with custom inputs and stream execution logs."""

from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import re
import sys
import threading
import traceback
import warnings
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

_PENDING_REPORT_CONFIRMATION: set[str] = set()
_YES_RE = re.compile(
    r"^\s*(si|sí|dale|ok|okay|de una|confirmo|confirmar|y|yes)\s*[!.]*\s*$",
    re.I,
)
_NO_RE = re.compile(
    r"^\s*(no|nop|mejor no|cancelar|cancela|dejalo|déjalo)\s*[!.]*\s*$",
    re.I,
)


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


def _ask_report_confirmation() -> str:
    return (
        "¿Querés que genere un informe de esta conversación? Respondé **sí** o **no**. "
        "Si confirmás, genero **.md** y **.pdf** en la carpeta output del proyecto."
    )


def _report_download_path(session_id: str, fmt: str) -> str:
    return f"/api/chat/report/{session_id}.{fmt}"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _web_dir() -> Path:
    return _project_root() / "web"


def _output_dir() -> Path:
    p = _project_root() / "output"
    p.mkdir(parents=True, exist_ok=True)
    return p


class RunPayload(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    current_year: str = Field(..., min_length=1, max_length=10)


class ChatPayload(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)


class ReportPayload(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=128)
    format: str = Field("md", pattern="^(md|pdf)$")


class _QueueStream(io.TextIOBase):
    def __init__(self, q: queue.Queue[str | None]) -> None:
        self._q = q

    def write(self, s: str) -> int:
        if s:
            self._q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


def _run_crew_blocking(inputs: dict[str, str], log_q: queue.Queue[str | None]) -> dict[str, Any]:
    root = _project_root()
    os.chdir(root)
    load_dotenv(root / ".env")

    result: dict[str, Any] = {"ok": False, "final_output": "", "report_md": "", "error": ""}
    old_out, old_err = sys.stdout, sys.stderr
    stream = _QueueStream(log_q)
    try:
        from crewai_demo.crew import ChocolartAssistant
        from crewai_demo.tools.db_query_tool import reset_last_executed_sql

        sys.stdout = stream
        sys.stderr = stream
        reset_last_executed_sql()
        topic = inputs.get("topic", "").strip()
        year = inputs.get("current_year", "").strip()
        crew_inputs = {
            "session_id": "stream_demo",
            "message": f"{topic} (contexto: año {year})",
            "conversation_history": "[]",
        }
        crew_result = ChocolartAssistant().crew().kickoff(inputs=crew_inputs)
        result["ok"] = True
        result["final_output"] = str(crew_result) if crew_result is not None else ""
    except Exception as e:
        result["error"] = f"{e}\n{traceback.format_exc()}"
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        log_q.put(None)

    result["report_md"] = ""
    return result


def _run_chat_crew(session_id: str, message: str, conversation_history_json: str) -> str:
    root = _project_root()
    os.chdir(root)
    load_dotenv(root / ".env")
    from crewai_demo.crew import ChocolartAssistant
    from crewai_demo.tools.db_query_tool import reset_last_executed_sql

    reset_last_executed_sql()
    out = ChocolartAssistant().crew().kickoff(
        inputs={
            "session_id": session_id,
            "message": message,
            "conversation_history": conversation_history_json,
        }
    )
    return str(out) if out is not None else ""


def _run_report_crew(session_id: str, conversation_history_json: str) -> str:
    root = _project_root()
    os.chdir(root)
    load_dotenv(root / ".env")
    from crewai_demo.crew import ChocolartInformes

    out = ChocolartInformes().crew().kickoff(
        inputs={
            "session_id": session_id,
            "conversation_history": conversation_history_json,
        }
    )
    return str(out) if out is not None else ""


app = FastAPI(title="CrewAI Demo UI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/db/health")
async def db_health() -> dict[str, Any]:
    try:
        from crewai_demo.db import check_db_connection

        return check_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(payload: ChatPayload) -> dict[str, Any]:
    try:
        from crewai_demo.historico import dumps_jsonable, get_history, insert_historico_chat_ai
        from crewai_demo.output_reports import write_md_and_pdf
        from crewai_demo.tools.db_query_tool import get_last_executed_sql

        session_id = payload.session_id.strip()
        msg = payload.message.strip()

        if session_id in _PENDING_REPORT_CONFIRMATION:
            if _YES_RE.match(msg):
                _PENDING_REPORT_CONFIRMATION.discard(session_id)
                hist = get_history(session_id, limit=200)
                hist_json = dumps_jsonable(list(reversed(hist)))
                md = _run_report_crew(session_id, hist_json).strip()
                write_md_and_pdf(session_id, md or "# Informe\n\n(vacío)")
                answer = (
                    "Listo. Generé el informe en **Markdown** y **PDF** en la carpeta `output` "
                    f"(`{session_id}.md` y `{session_id}.pdf`). Podés descargarlos desde la pestaña **Informe**."
                )
                insert_historico_chat_ai(
                    session_id=session_id,
                    usuario_pregunta=payload.message,
                    ia_respuesta=answer,
                    query_generada="",
                )
                return {
                    "ok": True,
                    "session_id": session_id,
                    "ia_respuesta": answer,
                    "usuario_pregunta": payload.message,
                    "query_generada": "",
                    "report_format": "md",
                    "report_download_path": _report_download_path(session_id, "md"),
                    "report_md": md,
                }
            if _NO_RE.match(msg):
                _PENDING_REPORT_CONFIRMATION.discard(session_id)
                answer = "Perfecto, no genero informe. Si más adelante lo necesitás, pedime un informe o reporte."
                insert_historico_chat_ai(
                    session_id=session_id,
                    usuario_pregunta=payload.message,
                    ia_respuesta=answer,
                    query_generada="",
                )
                return {
                    "ok": True,
                    "session_id": session_id,
                    "ia_respuesta": answer,
                    "usuario_pregunta": payload.message,
                    "query_generada": "",
                    "report_format": "",
                    "report_download_path": "",
                    "report_md": "",
                }
            answer = _ask_report_confirmation()
            insert_historico_chat_ai(
                session_id=session_id,
                usuario_pregunta=payload.message,
                ia_respuesta=answer,
                query_generada="",
            )
            return {
                "ok": True,
                "session_id": session_id,
                "ia_respuesta": answer,
                "usuario_pregunta": payload.message,
                "query_generada": "",
                "report_format": "",
                "report_download_path": "",
                "report_md": "",
            }

        if _wants_report(msg):
            _PENDING_REPORT_CONFIRMATION.add(session_id)
            answer = _ask_report_confirmation()
            insert_historico_chat_ai(
                session_id=session_id,
                usuario_pregunta=payload.message,
                ia_respuesta=answer,
                query_generada="",
            )
            return {
                "ok": True,
                "session_id": session_id,
                "ia_respuesta": answer,
                "usuario_pregunta": payload.message,
                "query_generada": "",
                "report_format": "",
                "report_download_path": "",
                "report_md": "",
            }

        hist = get_history(session_id, limit=20)
        hist_json = dumps_jsonable(list(reversed(hist)))
        answer = _run_chat_crew(session_id, msg, hist_json).strip()
        sql = get_last_executed_sql()
        insert_historico_chat_ai(
            session_id=session_id,
            usuario_pregunta=payload.message,
            ia_respuesta=answer,
            query_generada=sql,
        )
        return {
            "ok": True,
            "session_id": session_id,
            "ia_respuesta": answer,
            "usuario_pregunta": payload.message,
            "query_generada": sql,
            "report_format": "",
            "report_download_path": "",
            "report_md": "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/history")
async def chat_history(session_id: str, limit: int = 200) -> dict[str, Any]:
    try:
        from crewai_demo.historico import get_history

        return {"ok": True, "session_id": session_id, "items": get_history(session_id=session_id, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/report")
async def chat_report(payload: ReportPayload) -> dict[str, Any]:
    try:
        from crewai_demo.historico import dumps_jsonable, get_history
        from crewai_demo.output_reports import write_md_and_pdf

        hist = get_history(payload.session_id, limit=200)
        hist_json = dumps_jsonable(list(reversed(hist)))
        md = _run_report_crew(payload.session_id, hist_json).strip()
        write_md_and_pdf(payload.session_id, md or "# Informe\n\n(vacío)")
        if payload.format == "pdf":
            return {"ok": True, "format": "pdf", "download_path": _report_download_path(payload.session_id, "pdf")}
        return {
            "ok": True,
            "format": "md",
            "download_path": _report_download_path(payload.session_id, "md"),
            "md": md,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/report/{filename}")
async def download_report(filename: str) -> FileResponse:
    try:
        if not re.match(r"^[a-zA-Z0-9_-]+\.(md|pdf)$", filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        base = _output_dir()
        target = (base / filename).resolve()
        try:
            target.relative_to(base.resolve())
        except ValueError:
            raise HTTPException(status_code=404)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Report not found")
        return FileResponse(target)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def index() -> FileResponse:
    path = _web_dir() / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Frontend not found. Run from crewai_demo project root.")
    return FileResponse(path)


@app.get("/assets/{filename:path}")
async def assets(filename: str) -> FileResponse:
    base = _web_dir() / "assets"
    target = (base / filename).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=404)
    if not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target)


@app.post("/api/run/stream")
async def run_stream(payload: RunPayload) -> StreamingResponse:
    log_q: queue.Queue[str | None] = queue.Queue()
    result_holder: dict[str, Any] = {}

    def worker() -> None:
        result_holder["data"] = _run_crew_blocking(
            {"topic": payload.topic.strip(), "current_year": payload.current_year.strip()},
            log_q,
        )

    threading.Thread(target=worker, daemon=True).start()
    loop = asyncio.get_event_loop()

    async def gen():
        while True:
            chunk = await loop.run_in_executor(None, log_q.get)
            if chunk is None:
                break
            yield f"data: {json.dumps({'type': 'log', 'text': chunk}, ensure_ascii=False)}\n\n"
        data = result_holder.get("data") or {}
        yield f"data: {json.dumps({'type': 'result', **data}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def run_server() -> None:
    import uvicorn

    host = os.environ.get("CREW_UI_HOST", "127.0.0.1")
    raw_port = os.environ.get("CREW_UI_PORT") or os.environ.get("PORT") or "8765"
    try:
        port = int(raw_port)
    except ValueError:
        port = 8765

    uvicorn.run("crewai_demo.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
