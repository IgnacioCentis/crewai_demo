"""Local web UI to run the crew with custom inputs and stream execution logs."""

from __future__ import annotations

import asyncio
import io
import json
import os
import queue
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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _web_dir() -> Path:
    return _project_root() / "web"


def _report_path() -> Path:
    return _project_root() / "output" / "report.md"


class RunPayload(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    current_year: str = Field(..., min_length=1, max_length=10)


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
        from crewai_demo.crew import CrewaiDemo

        sys.stdout = stream
        sys.stderr = stream
        crew_result = CrewaiDemo().crew().kickoff(inputs=inputs)
        result["ok"] = True
        result["final_output"] = str(crew_result) if crew_result is not None else ""
    except Exception as e:
        result["error"] = f"{e}\n{traceback.format_exc()}"
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        log_q.put(None)

    rp = _report_path()
    if rp.is_file():
        try:
            result["report_md"] = rp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            result["report_md"] = ""
    return result


app = FastAPI(title="CrewAI Demo UI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    # 8080 suele fallar en Windows (WinError 10013) por exclusiones de Hyper-V / rangos reservados.
    host = os.environ.get("CREW_UI_HOST", "127.0.0.1")
    raw_port = os.environ.get("CREW_UI_PORT") or os.environ.get("PORT") or "8765"
    try:
        port = int(raw_port)
    except ValueError:
        port = 8765

    uvicorn.run("crewai_demo.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
