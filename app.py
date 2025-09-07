# app.py (pydantic v2, WeasyPrint with base_url + stable downloads)
from fastapi import FastAPI, Response, Request, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, EmailStr, HttpUrl, model_validator
from typing import List, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
import tempfile, os, markdown2, base64, re, time
from datetime import datetime

API_KEY = os.getenv("REPORTDOC_API_KEY")

def require_api_key(x_api_key: str = Header(None)):
    if not API_KEY or x_api_key != API_KEY:
      raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# Detect WeasyPrint
WEASY_OK = True
try:
    from weasyprint import HTML  # import only; do NOT render here
except Exception:
    WEASY_OK = False
    # ReportLab fallback imports will be done only if needed

app = FastAPI(title="ReportDoc PDF Service", version="1.1")

# Absolute path so WeasyPrint can resolve assets/fonts
TEMPLATES_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"])
)

FILES_DIR = Path("files"); FILES_DIR.mkdir(exist_ok=True)

# ---------- Models ----------
class Owner(BaseModel):
    name: str
    email: EmailStr
class GSheet(BaseModel):
    subtitle: str
    url: HttpUrl
class Change(BaseModel):
    date: str
    change: str
class Payload(BaseModel):
    title: str
    media_team: str
    owner: Owner
    frequency: str = Field(pattern=r"^(daily|weekly|monthly)$")
    platforms: List[str] = []
    tools: List[str] = []
    automated: bool
    google_sheets: List[GSheet] = []
    bigquery_link: Optional[HttpUrl] = None
    report_link: HttpUrl
    adjustments: List[str] = []
    description: str
    notes: Optional[str] = None
    version: str = "1.0"
    changelog: List[Change] = []
    @model_validator(mode="after")
    def _rules(self):
        if self.automated and self.bigquery_link is None:
            raise ValueError("bigquery_link is required when automated=true")
        if not self.notes or not str(self.notes).strip():
            self.notes = f"For access issues, contact {self.owner.email}"
        return self

# ---------- Helpers ----------
def _render_html_and_md(payload: Payload, generated_at: str) -> tuple[str, str]:
    md_tpl = env.get_template("doc.md.j2")
    md_source = md_tpl.render(**payload.model_dump(), generated_at=generated_at)
    inner_html = markdown2.markdown(md_source, extras=["tables"])
    html_tpl = env.get_template("layout.html.j2")
    html = html_tpl.render(**payload.model_dump(), content=inner_html, generated_at=generated_at)
    return html, md_source

def _write_pdf(html: str, md_source: str, generated_at: str) -> bytes:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp_path = tmp.name
    try:
        if WEASY_OK:
            HTML(string=html, base_url=str(TEMPLATES_DIR.resolve())).write_pdf(tmp_path)
        else:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            width, height = A4
            c = canvas.Canvas(tmp_path, pagesize=A4)
            def draw_footer(page_num:int):
                c.setFont("Times-Roman", 9); c.setFillGray(0.4)
                c.drawRightString(width-40, 20, f"Generated: {generated_at}  •  Page {page_num}")
            page_num = 1
            text = c.beginText(40, height-40); text.setFont("Times-Roman", 11)
            for line in md_source.splitlines():
                if text.getY() < 40:
                    c.drawText(text); draw_footer(page_num); c.showPage()
                    page_num += 1
                    text = c.beginText(40, height-40); text.setFont("Times-Roman", 11)
                text.textLine(line)
            c.drawText(text); draw_footer(page_num); c.save()
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
    finally:
        try: os.unlink(tmp_path)
        except: pass
    return pdf_bytes

def _safe_filename(title: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "report"
    return f"{base}_{int(time.time())}.pdf"

# ---------- Routes ----------
@app.get("/ping")
def ping():
    return {"ok": True, "weasyprint": WEASY_OK}

@app.get("/file/{file_name}")
def download_file(file_name: str):
    path = FILES_DIR / file_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), media_type="application/pdf", filename=file_name)

@app.post("/render", response_class=Response, dependencies=[Depends(require_api_key)])
def render_pdf(payload: Payload):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html, md_source = _render_html_and_md(payload, generated_at)
    pdf_bytes = _write_pdf(html, md_source, generated_at)
    headers = {"Content-Disposition": f"attachment; filename={payload.title.replace(' ', '_')}.pdf"}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

@app.post("/render_b64", dependencies=[Depends(require_api_key)])
def render_pdf_base64(payload: Payload, request: Request):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html, md_source = _render_html_and_md(payload, generated_at)
    pdf_bytes = _write_pdf(html, md_source, generated_at)

    fname = _safe_filename(payload.title)
    (FILES_DIR / fname).write_bytes(pdf_bytes)

    base = str(request.base_url).rstrip("/")
    file_url = f"{base}/file/{fname}"
    return {
        "filename": f"{payload.title.replace(' ', '_')}.pdf",
        "mime": "application/pdf",
        "data": base64.b64encode(pdf_bytes).decode("ascii"),
        "file_url": file_url
    }
