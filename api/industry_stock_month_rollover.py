from __future__ import annotations

import copy
import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

from fastapi import HTTPException


_INSTALLED = False
_TZ = ZoneInfo("America/Recife")
_SLOT_KEYS = ("jun_26", "jul_26", "ago_26", "set_26")
_LEGACY_XLSX_HEADERS = ("JUN/26", "JUL/26", "AGO/26", "SET/26")
_MONTH_NAMES = ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
_FRONTEND_MARKER = "DISMEPE_STOCK_ROLLING_MONTHS_V2"


def _rolling_month_labels(now: datetime | None = None) -> list[str]:
    if now is None:
        current = datetime.now(_TZ)
    elif now.tzinfo is None:
        current = now.replace(tzinfo=_TZ)
    else:
        current = now.astimezone(_TZ)
    serial = current.year * 12 + (current.month - 1)
    labels: list[str] = []
    for offset in (-3, -2, -1, 0):
        value = serial + offset
        year, month0 = divmod(value, 12)
        labels.append(f"{_MONTH_NAMES[month0]}/{str(year)[-2:]}")
    return labels


def _remap_stock_months(payload: Any) -> Any:
    """Mantém os quatro slots físicos do Átrio e publica a janela móvel correta.

    O parser do PDF possui quatro posições fixas chamadas, por legado,
    jun_26/jul_26/ago_26/set_26. Esses nomes não representam mais meses
    absolutos: representam as quatro colunas físicas do relatório. Alterar os
    valores entre chaves causa a primeira coluna vazia e pode esconder a quarta.
    Portanto os valores permanecem intactos e somente os rótulos avançam.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("linhas"), list):
        return payload

    out = copy.deepcopy(payload)
    out["mesesVendas"] = _rolling_month_labels()
    out["mapaMesesCorrigidos"] = True
    out["layoutMeses"] = "ROLLING_4_MONTHS"
    out["camposMesesVendas"] = list(_SLOT_KEYS)
    return out


def _frontend_rolling_patch() -> str:
    return r"""
/* DISMEPE_STOCK_ROLLING_MONTHS_V2 */
function stockRollingMonthLabels(){
  const parts=new Intl.DateTimeFormat('en-US',{
    timeZone:'America/Recife',year:'numeric',month:'2-digit'
  }).formatToParts(new Date());
  const read=t=>Number(parts.find(p=>p.type===t)?.value);
  const names=['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ'];
  const serial=read('year')*12+(read('month')-1);
  return [-3,-2,-1,0].map(offset=>{
    const value=serial+offset;
    const year=Math.floor(value/12);
    const month=((value%12)+12)%12;
    return `${names[month]}/${String(year).slice(-2)}`;
  });
}
function updateStockRollingMonthHeaders(){
  const keys=['jun_26','jul_26','ago_26','set_26'];
  const labels=stockRollingMonthLabels();
  keys.forEach((key,index)=>{
    const head=document.querySelector(`th[data-stock-sort="${key}"] .sort-head`);
    if(!head)return;
    const arrow=head.querySelector('.sort-arrow')?.textContent||'↕';
    head.innerHTML=`${labels[index]} <span class="sort-arrow">${arrow}</span>`;
  });
}
"""


def _patch_frontend_file(path: Path) -> bool:
    try:
        html = path.read_text(encoding="utf-8")
    except Exception:
        return False

    if _FRONTEND_MARKER in html:
        return True

    needle = "function renderStock(){\n  const body=document.getElementById('stockBody');if(!body)return;"
    if needle not in html:
        return False

    replacement = (
        _frontend_rolling_patch().strip()
        + "\nfunction renderStock(){\n"
        + "  updateStockRollingMonthHeaders();\n"
        + "  const body=document.getElementById('stockBody');if(!body)return;"
    )
    patched = html.replace(needle, replacement, 1)

    try:
        temp = path.with_name(path.name + ".rolling-months.tmp")
        temp.write_text(patched, encoding="utf-8")
        temp.replace(path)
    except Exception:
        return False
    return True


def _rewrite_xlsx_month_headers(content: bytes) -> bytes:
    labels = _rolling_month_labels()
    source = io.BytesIO(content)
    output = io.BytesIO()

    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                for index, legacy in enumerate(_LEGACY_XLSX_HEADERS):
                    text = text.replace(legacy, f"__DISMEPE_MONTH_{index}__")
                for index, label in enumerate(labels):
                    text = text.replace(f"__DISMEPE_MONTH_{index}__", label)
                data = text.encode("utf-8")
            zout.writestr(item, data)
    return output.getvalue()


def _build_pdf_rolling(rows: list[dict[str, Any]], lab: str, generated_at: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Gerador de PDF indisponível no servidor.") from exc

    def safe(value: Any) -> str:
        return str(value or "").replace("\u2013", "-").replace("\u2014", "-")

    labels = _rolling_month_labels()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=7 * mm,
        leftMargin=7 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=f"Mapa de Estoque - {lab}",
        author="DISMEPE ONE INDÚSTRIAS",
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph("<b>DISMEPE ONE INDÚSTRIAS - MAPA DE ESTOQUE</b>", styles["Title"]),
        Paragraph(
            f"<b>Laboratório:</b> {xml_escape(safe(lab))} &nbsp;&nbsp; "
            f"<b>Atualizado:</b> {xml_escape(safe(generated_at))}",
            styles["BodyText"],
        ),
        Spacer(1, 5 * mm),
    ]

    headers = [
        "Laboratório", "Código", "Descrição", "Curva", "Preço", "Estoque",
        *labels, "Média", "EAN", "Est. até", "Últ. entrada",
    ]
    data: list[list[Any]] = [headers]
    for row in rows:
        data.append([
            safe(row.get("laboratorio") or row.get("fornecedor")),
            safe(row.get("codigo")),
            safe(row.get("descricao")),
            safe(row.get("curva")),
            safe(row.get("preco")),
            safe(row.get("estoque")),
            safe(row.get("jun_26")),
            safe(row.get("jul_26")),
            safe(row.get("ago_26")),
            safe(row.get("set_26")),
            safe(row.get("media")),
            safe(row.get("ean")),
            safe(row.get("est_ate")),
            safe(row.get("ultima_entrada")),
        ])

    col_widths = [
        26*mm, 15*mm, 78*mm, 11*mm, 13*mm, 15*mm,
        11*mm, 11*mm, 11*mm, 11*mm, 11*mm, 25*mm, 18*mm, 20*mm,
    ]
    body_style = ParagraphStyle(
        "StockBodyRollingV2",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=6.2,
        leading=8,
        wordWrap="CJK",
        splitLongWords=1,
    )
    head_style = ParagraphStyle(
        "StockHeadRollingV2",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    formatted = [
        [
            Paragraph(xml_escape(str(value or "")), head_style if row_index == 0 else body_style)
            for value in record
        ]
        for row_index, record in enumerate(data)
    ]
    table = Table(formatted, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#005548")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.2),
        ("LEADING", (0, 0), (-1, -1), 7.1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D7E4E0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def install_industry_stock_month_rollover() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from . import industries as industries_module
    except Exception:
        return

    original_load = getattr(industries_module, "_load_stock", None)
    if callable(original_load) and not getattr(original_load, "__dismepe_month_rollover__", False):
        async def wrapped_load_stock(*args, **kwargs):
            payload = await original_load(*args, **kwargs)
            return _remap_stock_months(payload)

        wrapped_load_stock.__dismepe_month_rollover__ = True
        wrapped_load_stock.__wrapped__ = original_load
        industries_module._load_stock = wrapped_load_stock

    original_xlsx = getattr(industries_module, "_build_xlsx", None)
    if callable(original_xlsx) and not getattr(original_xlsx, "__dismepe_rolling_months__", False):
        def wrapped_xlsx(*args, **kwargs):
            return _rewrite_xlsx_month_headers(original_xlsx(*args, **kwargs))

        wrapped_xlsx.__dismepe_rolling_months__ = True
        wrapped_xlsx.__wrapped__ = original_xlsx
        industries_module._build_xlsx = wrapped_xlsx

    if callable(getattr(industries_module, "_build_pdf", None)):
        _build_pdf_rolling.__dismepe_rolling_months__ = True
        industries_module._build_pdf = _build_pdf_rolling

    frontend_path = getattr(industries_module, "INDUSTRIES_FILE", None)
    if isinstance(frontend_path, Path):
        _patch_frontend_file(frontend_path)

    if hasattr(industries_module, "_STOCK_SNAPSHOT_CACHE"):
        industries_module._STOCK_SNAPSHOT_CACHE = None

    _INSTALLED = True
