"""Convert markdown to DOCX or PDF.

DOCX: pure python-docx, no external binaries.
PDF:  markdown -> HTML -> weasyprint (needs system Cairo/Pango on Windows;
      install via `pip install weasyprint` — usually works if VC++ redist present).
"""
import io
import re


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def to_docx(markdown: str) -> bytes:
    from docx import Document  # python-docx

    doc = Document()
    lines = markdown.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("#### "):
            doc.add_heading(line[5:].strip(), level=4)
        elif line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
        elif line.startswith("|"):
            # Collect consecutive table lines, skip separator rows
            table_lines: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[-| :]+\|$", lines[i]):
                    table_lines.append(lines[i])
                i += 1
            i -= 1  # outer loop will increment

            if table_lines:
                rows = [
                    [c.strip() for c in row.split("|")[1:-1]]
                    for row in table_lines
                ]
                n_cols = max(len(r) for r in rows)
                tbl = doc.add_table(rows=len(rows), cols=n_cols)
                tbl.style = "Table Grid"
                for r_idx, row in enumerate(rows):
                    for c_idx in range(n_cols):
                        txt = row[c_idx] if c_idx < len(row) else ""
                        txt = re.sub(r"\*\*(.+?)\*\*", r"\1", txt)
                        txt = re.sub(r"\*(.+?)\*", r"\1", txt)
                        tbl.rows[r_idx].cells[c_idx].text = txt
        elif line.startswith("- ") or line.startswith("* "):
            p = doc.add_paragraph(style="List Bullet")
            _runs(p, line[2:].strip())
        elif re.match(r"^\d+\.\s", line):
            p = doc.add_paragraph(style="List Number")
            _runs(p, re.sub(r"^\d+\.\s+", "", line))
        elif line.strip() in ("---", "***", "___"):
            doc.add_paragraph("─" * 60)
        elif line.startswith("> "):
            doc.add_paragraph(line[2:].strip())
        elif line.strip():
            p = doc.add_paragraph()
            _runs(p, line)

        i += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _runs(paragraph, text: str) -> None:
    """Parse **bold**, *italic*, `code` and add styled runs."""
    pattern = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`")
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            paragraph.add_run(text[last : m.start()])
        if m.group(1):
            paragraph.add_run(m.group(1)).bold = True
        elif m.group(2):
            paragraph.add_run(m.group(2)).italic = True
        elif m.group(3):
            r = paragraph.add_run(m.group(3))
            r.font.name = "Courier New"
        last = m.end()
    if last < len(text):
        paragraph.add_run(text[last:])


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_PDF_CSS = """
body  { font-family: Georgia, serif; font-size: 11pt; line-height: 1.65; margin: 2.2cm; }
h1    { font-size: 18pt; margin-top: 22pt; margin-bottom: 6pt; }
h2    { font-size: 14pt; margin-top: 18pt; margin-bottom: 4pt; }
h3    { font-size: 12pt; margin-top: 14pt; margin-bottom: 2pt; }
h4    { font-size: 11pt; margin-top: 10pt; }
p     { margin: 0 0 8pt; }
table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 9pt; }
th, td{ border: 1px solid #aaa; padding: 4pt 6pt; }
th    { background: #f0f0f0; font-weight: bold; }
code  { font-family: "Courier New", monospace; font-size: 9pt;
        background: #f5f5f5; padding: 1pt 3pt; border-radius: 2pt; }
blockquote { border-left: 3pt solid #ccc; margin: 8pt 0; padding-left: 10pt; color: #555; }
ul, ol{ margin: 0 0 8pt 18pt; }
li    { margin-bottom: 3pt; }
"""


def to_pdf(markdown: str) -> bytes:
    import markdown as md_lib  # Markdown (PyPI)
    import weasyprint

    html_body = md_lib.markdown(markdown, extensions=["tables", "fenced_code"])
    html = (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        f"<style>{_PDF_CSS}</style>"
        f"</head><body>{html_body}</body></html>"
    )
    return weasyprint.HTML(string=html).write_pdf()
