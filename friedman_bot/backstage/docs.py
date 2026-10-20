"""
Сейф материалов и готовые документы.

  • extract_text — текст из загруженного файла (PDF через pdftotext, DOCX —
    прямо из XML, текстовые форматы как есть), чтобы агенты читали CV, statement
    и портфолио без повторной загрузки.
  • to_docx — markdown документа → настоящий .docx (без внешних библиотек:
    минимальный набор XML внутри zip).
  • to_html — страница для чтения и печати (печать → «Сохранить как PDF»).
"""

import html
import io
import re
import subprocess
import tempfile
import zipfile


def extract_text(name, mime, raw: bytes) -> str:
    n = name.lower()
    try:
        if mime == "application/pdf" or n.endswith(".pdf"):
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(raw)
                f.flush()
                p = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=60)
                return p.stdout.decode("utf-8", "replace")
        if n.endswith(".docx"):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return html.unescape(re.sub(r"<[^>]+>", "", xml))
        if mime.startswith("text/") or n.endswith((".txt", ".md", ".csv", ".json")):
            return raw.decode("utf-8", "replace")
    except Exception:
        return ""
    return ""


# ─── markdown → DOCX ─────────────────────────────────────────────────────────

def _runs(text):
    """**жирный** и *курсив* → w:r; остальное — обычный текст."""
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*\n]+\*)", text):
        if not part:
            continue
        rpr = ""
        if part.startswith("**") and part.endswith("**"):
            part, rpr = part[2:-2], "<w:b/>"
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            part, rpr = part[1:-1], "<w:i/>"
        part = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", part)
        out.append(f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{html.escape(part)}</w:t></w:r>')
    return "".join(out)


def _para(text, size=None, bold=False, space_after=120, indent=0):
    ppr = f'<w:spacing w:after="{space_after}"/>' + (f'<w:ind w:left="{indent}"/>' if indent else "")
    runs = _runs(text)
    if size or bold:
        extra = (f'<w:sz w:val="{size}"/>' if size else "") + ("<w:b/>" if bold else "")
        runs = runs.replace("<w:rPr>", f"<w:rPr>{extra}")
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


def _table_rows(lines):
    """Строки markdown-таблицы → список списков ячеек (строку-разделитель |---| пропускаем)."""
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _docx_table(lines):
    b = '<w:top w:val="single" w:sz="4" w:color="BBBBBB"/><w:left w:val="single" w:sz="4" w:color="BBBBBB"/>' \
        '<w:bottom w:val="single" w:sz="4" w:color="BBBBBB"/><w:right w:val="single" w:sz="4" w:color="BBBBBB"/>' \
        '<w:insideH w:val="single" w:sz="4" w:color="BBBBBB"/><w:insideV w:val="single" w:sz="4" w:color="BBBBBB"/>'
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{b}</w:tblBorders></w:tblPr>']
    for i, row in enumerate(_table_rows(lines)):
        out.append("<w:tr>" + "".join(
            f"<w:tc>{_para(c, bold=(i == 0), space_after=40)}</w:tc>" for c in row) + "</w:tr>")
    out.append("</w:tbl>" + _para("", space_after=60))
    return "".join(out)


def _blocks(markdown):
    """Строки, но подряд идущие строки таблицы склеены в один блок ("table", [...])."""
    buf = []
    for line in markdown.splitlines() + [""]:
        if line.strip().startswith("|"):
            buf.append(line)
            continue
        if buf:
            yield ("table", buf)
            buf = []
        yield ("line", line)


def to_docx(markdown: str) -> bytes:
    body = []
    for typ, line in _blocks(markdown):
        if typ == "table":
            body.append(_docx_table(line))
            continue
        s = line.rstrip()
        if not s.strip():
            continue
        if s.startswith("# "):
            body.append(_para(s[2:], size=36, bold=True, space_after=200))
        elif s.startswith("## "):
            body.append(_para(s[3:], size=28, bold=True, space_after=140))
        elif s.startswith("### "):
            body.append(_para(s[4:], size=24, bold=True))
        elif re.match(r"^\s*[-*•]\s+", s):
            body.append(_para("• " + re.sub(r"^\s*[-*•]\s+", "", s), indent=360, space_after=60))
        elif re.match(r"^\s*\d+[.)]\s+", s):
            body.append(_para(s.strip(), indent=360, space_after=60))
        else:
            body.append(_para(s))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(body) +
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1300" w:right="1300" w:bottom="1300" '
           'w:left="1300" w:header="700" w:footer="700" w:gutter="0"/></w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults>'
              '<w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
              '<w:sz w:val="22"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault></w:docDefaults></w:styles>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
             '</Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", drels)
    return buf.getvalue()


# ─── markdown → HTML для печати ──────────────────────────────────────────────

def _inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(^|[\s(])\*([^*\n]+)\*", r"\1<i>\2</i>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(markdown: str) -> str:
    out, lst = [], None
    for typ, line in _blocks(markdown):
        if typ == "table":
            if lst:
                out.append(f"</{lst}>")
                lst = None
            rows = _table_rows(line)
            out.append("<table>" + "".join(
                "<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{_inline(c)}</{'th' if i == 0 else 'td'}>" for c in row) + "</tr>"
                for i, row in enumerate(rows)) + "</table>")
            continue
        s = line.rstrip()
        m_ul = re.match(r"^\s*[-*•]\s+(.*)", s)
        m_ol = re.match(r"^\s*\d+[.)]\s+(.*)", s)
        kind = "ul" if m_ul else "ol" if m_ol else None
        if lst and kind != lst:
            out.append(f"</{lst}>")
            lst = None
        if kind:
            if not lst:
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{_inline((m_ul or m_ol).group(1))}</li>")
        elif s.startswith("### "):
            out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{_inline(s[2:])}</h1>")
        elif s.strip():
            out.append(f"<p>{_inline(s)}</p>")
    if lst:
        out.append(f"</{lst}>")
    return "\n".join(out)


def to_html(title, markdown, labels):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
 body{{margin:0;background:#f3efe8;font:16px/1.6 Georgia,'Times New Roman',serif;color:#1f1d1b}}
 .bar{{position:sticky;top:0;display:flex;gap:8px;justify-content:flex-end;padding:10px 16px;background:#f3efe8}}
 .bar a,.bar button{{font:600 14px Inter,system-ui,sans-serif;border:0;border-radius:10px;padding:9px 14px;cursor:pointer;
   background:#e0573a;color:#fff;text-decoration:none}}
 .bar .ghost{{background:transparent;color:#6b665e}}
 .page{{max-width:760px;margin:0 auto 40px;background:#fff;padding:56px 64px;box-shadow:0 10px 40px -20px rgba(0,0,0,.3)}}
 h1{{font-size:26px;line-height:1.2;margin:0 0 18px}}
 table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}} td,th{{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}}
 th{{background:#f5f1ea}} h2{{font-size:19px;margin:26px 0 8px}} h3{{font-size:16px;margin:18px 0 6px}}
 @media (max-width:640px){{.page{{padding:28px 20px}}}}
 @media print{{.bar{{display:none}} body{{background:#fff}} .page{{box-shadow:none;margin:0;max-width:none;padding:0}}}}
</style></head><body>
<div class="bar"><a class="ghost" href="../workspace">{html.escape(labels['back'])}</a>
<a href="{labels['docx']}">{html.escape(labels['download'])}</a><button onclick="print()">{html.escape(labels['print'])}</button></div>
<div class="page">{md_to_html(markdown)}</div></body></html>"""
