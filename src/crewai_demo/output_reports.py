from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def report_md_path(session_id: str) -> Path:
    return project_root() / "output" / f"{session_id}.md"


def report_pdf_path(session_id: str) -> Path:
    return project_root() / "output" / f"{session_id}.pdf"


def write_markdown(session_id: str, markdown: str) -> Path:
    path = report_md_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def write_pdf_from_markdown(session_id: str, md: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    paths = report_pdf_path(session_id)
    paths.parent.mkdir(parents=True, exist_ok=True)
    width, height = A4
    c = canvas.Canvas(str(paths), pagesize=A4)

    try:
        font_path = str((project_root() / "web" / "assets" / "DejaVuSans.ttf").resolve())
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
        while len(line) > 120:
            c.drawString(x, y, line[:120])
            line = line[120:]
            y -= line_h
        c.drawString(x, y, line)
        y -= line_h

    c.save()
    return paths


def write_md_and_pdf(session_id: str, markdown: str) -> tuple[Path, Path]:
    md_path = write_markdown(session_id, markdown)
    pdf_path = write_pdf_from_markdown(session_id, markdown)
    return md_path, pdf_path
