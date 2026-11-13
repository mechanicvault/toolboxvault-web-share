"""Tabular rendering for the ADMIN report datasets (admin
lane, owner 2026-11-06).

The activity renderer is ledger-shaped (date / item / detail /
amount) — honest for a member's money trail, wrong for admin
datasets, which are counts and text (members by tier, items per
member, plans, monthly revenue). Admin datasets therefore
carry a tabular shape:

    {
        "title": str,
        "subtitle": str,               # may be ""
        "banner": [str, ...],          # headline facts for the navy band
        "sections": [
            {
                "label": str,
                "columns": [str, ...],
                "rows": [[str, ...], ...],
                "total": str | None,   # a ready "TOTAL: ..." line
            },
        ],
    }

PDF rides the SAME uniform frame as every report (core/
docframe: header box, wordmark footer, page numbers) and the
report layout standard's elements — navy banner carrying the
headline facts, light-grey column banners, faint grey hairline
after every body row, a short navy totals bar hugging its text
per section. CSV and XLSX are data files (no visual frame):
title, then per section a label row, the column row, the data
rows and the total line.
"""

import csv
import io
import re
from datetime import date

from app.core import docframe
from app.modules.core import models as core_models

_NUMERIC = re.compile(r"^-?\$?[\d,]+(\.\d+)?%?$|^-$")


def _safe(text) -> str:
    return docframe._safe(text)


def render_tabular_pdf(doc: dict, owner: core_models.User) -> bytes:
    pdf = docframe.framed_pdf_class()(orientation="P", unit="mm", format="A4")
    pdf.frame_chrome = docframe.chrome_for(owner)
    pdf.frame_when = date.today()
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(14, 14, 14)
    pdf.add_page()
    from app.modules.reports import service as report_service

    pdf.frame_header(
        doc["title"], report_service.prepared_for_of(owner), None
    )
    pdf.ln(2)
    if (doc.get("subtitle") or "").strip():
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(90, 90, 90)
        # A WRAPPING cell, not a single-line one: the subtitle
        # is a sentence (counting definitions, recording
        # riders), and the old single-line cell cut it off
        # mid-word on the printed page — CSV/XLSX always
        # printed it whole (pdf-subtitle-wrap lane, 2026-11-07).
        # A subtitle that fits on one line renders exactly as
        # before (same line, same 5mm advance); a longer one
        # takes the lines it needs and everything below it
        # shifts by exactly that added height.
        pdf.multi_cell(
            0, 5, _safe(doc["subtitle"]),
            align="L", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    usable = pdf.w - pdf.l_margin - pdf.r_margin

    # Element 4: the navy banner with the headline facts.
    banner = [b for b in (doc.get("banner") or []) if str(b).strip()]
    if banner:
        band_y = pdf.get_y()
        pdf.set_fill_color(*docframe.NAVY)
        pdf.rect(pdf.l_margin, band_y, usable, 7.5, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "", 10)
        pdf.set_xy(pdf.l_margin + 2, band_y)
        pdf.cell(usable - 4, 7.5, _safe("   ·   ".join(banner)))
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, band_y + 7.5)
        pdf.ln(3)

    def _row_line() -> None:
        y = pdf.get_y()
        pdf.set_draw_color(*docframe.ROW_LINE)
        pdf.set_line_width(docframe.ROW_LINE_WIDTH)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_xy(pdf.l_margin, y)

    def _total_bar(text: str) -> None:
        """Element 7: a SHORT navy bar hugging its text,
        anchored at the right margin."""
        pdf.set_font("helvetica", "B", 10)
        bar_w = pdf.get_string_width(_safe(text)) + 8
        if pdf.get_y() + 7 > pdf.page_break_trigger:
            pdf.add_page()
        bar_y = pdf.get_y()
        bar_x = pdf.l_margin + usable - bar_w
        pdf.set_fill_color(*docframe.NAVY)
        pdf.rect(bar_x, bar_y, bar_w, 7, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(bar_x, bar_y)
        pdf.cell(bar_w - 4, 7, _safe(text), align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, bar_y + 7)

    for section in doc["sections"]:
        columns = [str(c) for c in section["columns"]]
        rows = [[str(c) for c in row] for row in section["rows"]]
        count = max(len(columns), 1)
        # First column wider (it names the row); the rest share.
        first_w = usable * (0.34 if count > 2 else 0.5)
        rest_w = (usable - first_w) / (count - 1) if count > 1 else 0
        widths = [first_w] + [rest_w] * (count - 1)
        # Right-align a column when most of its values are numbers.
        aligns = []
        for j in range(count):
            values = [r[j] for r in rows if j < len(r) and r[j] not in ("", "-")]
            numeric = sum(1 for v in values if _NUMERIC.match(v))
            aligns.append("R" if values and numeric * 2 >= len(values) else "L")

        if pdf.get_y() + 20 > pdf.page_break_trigger:
            pdf.add_page()
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(
            0, 6, _safe(section["label"]), new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(1)
        # Element 5: the light-grey column banner.
        pdf.set_font("helvetica", "B", 9.5)
        pdf.set_fill_color(240, 240, 240)
        y = pdf.get_y()
        x = pdf.l_margin
        for j, head in enumerate(columns):
            pdf.set_xy(x, y)
            pdf.cell(widths[j], 6.5, _safe(head), fill=True, align=aligns[j])
            x += widths[j]
        pdf.set_xy(pdf.l_margin, y + 6.5)
        _row_line()
        pdf.set_font("helvetica", "", 9.5)
        if not rows:
            pdf.cell(
                0, 6, "—", new_x="LMARGIN", new_y="NEXT"
            )
        for row in rows:
            if pdf.get_y() + 6 > pdf.page_break_trigger:
                pdf.add_page()
            y = pdf.get_y()
            x = pdf.l_margin
            for j in range(count):
                pdf.set_xy(x, y)
                pdf.cell(
                    widths[j],
                    6,
                    _safe(row[j] if j < len(row) else ""),
                    align=aligns[j],
                )
                x += widths[j]
            pdf.set_xy(pdf.l_margin, y + 6)
            _row_line()
        if section.get("total"):
            pdf.ln(1.5)
            _total_bar(section["total"])
        pdf.ln(4)

    return bytes(pdf.output())


def render_tabular_csv(doc: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([doc["title"]])
    if (doc.get("subtitle") or "").strip():
        writer.writerow([doc["subtitle"]])
    for fact in doc.get("banner") or []:
        writer.writerow([fact])
    for section in doc["sections"]:
        writer.writerow([])
        writer.writerow([section["label"]])
        writer.writerow(section["columns"])
        writer.writerows(section["rows"])
        if section.get("total"):
            writer.writerow([section["total"]])
    return buf.getvalue().encode("utf-8-sig")


def render_tabular_xlsx(doc: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.append([doc["title"]])
    ws["A1"].font = Font(bold=True, size=13)
    if (doc.get("subtitle") or "").strip():
        ws.append([doc["subtitle"]])
    for fact in doc.get("banner") or []:
        ws.append([fact])
    bold = Font(bold=True)
    for section in doc["sections"]:
        ws.append([])
        label_row = ws.max_row + 1
        ws.append([section["label"]])
        ws.cell(row=label_row, column=1).font = Font(bold=True, size=12)
        head_row = ws.max_row + 1
        ws.append(section["columns"])
        for cell in ws[head_row]:
            cell.font = bold
        for row in section["rows"]:
            ws.append(row)
        if section.get("total"):
            total_row = ws.max_row + 1
            ws.append([section["total"]])
            ws.cell(row=total_row, column=1).font = bold
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def render_tabular(doc: dict, fmt: str, owner: core_models.User) -> bytes:
    if fmt == "pdf":
        return render_tabular_pdf(doc, owner)
    if fmt == "xlsx":
        return render_tabular_xlsx(doc)
    return render_tabular_csv(doc)
