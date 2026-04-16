from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crewai_demo.chat import _dumps_jsonable, get_history, _llm_json  # noqa: SLF001


@dataclass(frozen=True)
class ReportFiles:
    md_path: Path
    pdf_path: Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _reports_dir() -> Path:
    p = _project_root() / "output" / "chat_reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def report_paths(session_id: str) -> ReportFiles:
    base = _reports_dir() / session_id
    return ReportFiles(md_path=base.with_suffix(".md"), pdf_path=base.with_suffix(".pdf"))


def generate_markdown_report(session_id: str) -> str:
    items = get_history(session_id=session_id, limit=200)
    # Keep only relevant fields if present
    compact: list[dict[str, Any]] = []
    for it in reversed(items):
        compact.append(
            {
                "usuario_pregunta": it.get("usuario_pregunta"),
                "ia_respuesta": it.get("ia_respuesta"),
                "query_generada": it.get("query_generada"),
                "fecha_registro": it.get("fecha_registro") or it.get("created_at") or it.get("fecha") or it.get("created"),
            }
        )

    prompt = (
        "Sos un analista y redactor. Generá un informe en Markdown sobre la conversación.\n"
        "Objetivo: resumir necesidades del usuario, hallazgos en datos, y próximos pasos.\n"
        "Incluí secciones:\n"
        "- Resumen ejecutivo\n"
        "- Preguntas del usuario (bullet points)\n"
        "- Respuestas y hallazgos (bullet points)\n"
        "- Queries ejecutadas (si existen)\n"
        "- Recomendaciones\n\n"
        f"Conversación (JSON): {_dumps_jsonable(compact)}\n\n"
        "Return JSON: {\"md\": \"...markdown...\"}"
    )
    data = _llm_json(prompt)
    md = str(data.get("md") or "").strip()
    if not md:
        md = "# Informe\n\nNo se pudo generar el informe."
    paths = report_paths(session_id)
    paths.md_path.write_text(md, encoding="utf-8")
    return md


def generate_pdf_from_markdown(session_id: str, md: str | None = None) -> Path:
    """
    Minimal PDF export (plain text rendering).
    """
    if md is None:
        paths = report_paths(session_id)
        md = paths.md_path.read_text(encoding="utf-8", errors="replace") if paths.md_path.is_file() else ""

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    paths = report_paths(session_id)
    width, height = A4
    c = canvas.Canvas(str(paths.pdf_path), pagesize=A4)

    # Try a unicode-capable font if available; fall back to default.
    try:
        font_path = str((_project_root() / "web" / "assets" / "DejaVuSans.ttf").resolve())
        pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
        c.setFont("DejaVuSans", 10)
    except Exception:
        c.setFont("Helvetica", 10)

    x = 40
    y = height - 50
    line_h = 14
    for raw in (md or "").splitlines():
        line = raw.rstrip("\n")
        if y < 60:
            c.showPage()
            y = height - 50
            try:
                c.setFont("DejaVuSans", 10)
            except Exception:
                c.setFont("Helvetica", 10)
        # crude wrapping
        while len(line) > 120:
            c.drawString(x, y, line[:120])
            line = line[120:]
            y -= line_h
        c.drawString(x, y, line)
        y -= line_h

    c.save()
    return paths.pdf_path

