"""Report renderers: CSV, XLSX, PDF, and email delivery.

Every renderer consumes service.build_report's structure — the
same columns, groups, subtotals and display strings the screen
shows — so a downloaded file can never disagree with the table it
was downloaded from. CSV/XLSX carry PLAIN values (money as bare
numbers, dates ISO) so spreadsheets can do math on them; the PDF
carries the formatted display strings, like the screen.

REPORTS ALIGNMENT (2026-10-19 — Ryan's app report is the format
benchmark):
  - Every output opens with the app's furniture when the summary
    option is on: the PREPARED FOR line + the summary (items ·
    units · total value over the FULL filtered set). In CSV these
    are `#` comment lines above the column header (the file
    already carries ## group markers, so it was never a bare
    data grid); in XLSX they are bold rows above the header.
  - The PHOTO column: screen shows the thumbnail; PDF and XLSX
    embed the item's first photo; CSV carries the photo's
    FILENAME (a name is stable, where a presigned URL expires —
    and the file stays self-describing). No photo → empty cell /
    placeholder, never a broken image. Photo BYTES are fetched
    per render through the storage seam and normalized with PIL;
    a missing object degrades to the placeholder, never an error.
  - ROW NUMBERS (the app's "#") prepend a display column in
    every renderer when the option is on; group/subtotal/total
    rows leave it blank and carry their label as before.
  - The PDF heads with the app's layout spirit: brand block left
    (TOOLBOX VAULT + title + prepared date), PREPARED FOR block
    right (unset profile fields simply absent), the summary band
    under both, then the table. Orientation comes from the spec
    (the app-style preset is portrait).

PDF is generated server-side with fpdf2 (pure Python, pinned):
a repeating column header, group + subtotal rows, and the
Toolbox Vault footer on every page.
"""

import csv
import io
import re
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core import docframe, notifications
from app.core.storage import storage
from app.modules.core import models as core_models
from app.modules.core import money as core_money
from app.modules.reports import service

MIME_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}

EXTENSIONS = {"csv": "csv", "xlsx": "xlsx", "pdf": "pdf"}


def _plain_value(column: dict, row: dict):
    """The machine-readable cell: money/dates/numbers as values,
    everything else as the raw string. An UNPRICED core piece's
    price cells read "in set" (there is no number — the price lives
    on the set); a priced core piece exports its own number."""
    display = row["display"].get(column["key"], "")
    if display == "in set":
        return "in set"
    raw = row["values"].get(column["key"])
    if raw is None:
        return ""
    if column["type"] == "money":
        return Decimal(str(raw))
    if column["type"] == "number":
        return int(raw)
    return raw


def _flat_rows(report: dict):
    """Yield (kind, payload) in display order: group markers, data
    rows, subtotal rows, and the grand total — the shared skeleton
    CSV and XLSX are both written from."""
    grouped = report["grouping"] != "none"
    for group in report["groups"]:
        if grouped:
            yield "group", group
        for row in group["rows"]:
            yield "row", row
        if grouped:
            yield "subtotal", group
    yield "total", report["totals"]


# The row-number pseudo-column (the app's "#"): a display overlay
# the renderers prepend when the option is on — never a data
# column, so it is not in the report's column list.
_NUMBER_COLUMN = {"key": "#", "label": "#", "type": "number"}


def _display_columns(report: dict) -> list[dict]:
    columns = list(report["columns"])
    if (report.get("options") or {}).get("show_row_numbers"):
        return [_NUMBER_COLUMN, *columns]
    return columns


def _prepared_for_line(report: dict) -> str:
    """One-line Prepared-For for the CSV/XLSX header blocks:
    "Prepared for: Name · email · phone · address" — fields the
    owner hasn't set are simply absent (no dangling separators)."""
    prepared = report.get("prepared_for") or {}
    parts = [prepared.get("name") or "", prepared.get("email") or ""]
    if prepared.get("phone"):
        parts.append(prepared["phone"])
    if prepared.get("address"):
        parts.append(" ".join(prepared["address"].split()))
    parts = [p for p in parts if p]
    return "Prepared for: " + " · ".join(parts) if parts else ""


def _summary_line(report: dict, currency: str = "USD") -> str:
    summary = report.get("summary") or {}
    return (
        f"Summary: {summary.get('items', 0)} items · "
        f"{summary.get('units', 0)} units · "
        f"Total value {core_money.format_money(Decimal(summary.get('price_total', '0')), currency)} · "
        f"Replacement {core_money.format_money(Decimal(summary.get('replacement', '0')), currency)}"
    )


def _show_summary(report: dict) -> bool:
    return bool((report.get("options") or {}).get("show_summary", True))


def _subtotal_cells(display_columns: list[dict], label: str, subtotal: dict) -> list:
    """Label under the name column (else the first data column);
    money under its columns; the "#" cell stays blank."""
    label_index = next(
        (i for i, c in enumerate(display_columns) if c["key"] == "name"),
        next((i for i, c in enumerate(display_columns) if c["key"] != "#"), 0),
    )
    cells = []
    for index, column in enumerate(display_columns):
        if index == label_index:
            cells.append(f"{label} ({subtotal['count']} items)")
        elif column["key"] == "price_total":
            cells.append(Decimal(subtotal["price_total"]))
        elif column["key"] == "replacement":
            cells.append(Decimal(subtotal["replacement"]))
        else:
            cells.append("")
    return cells


def _row_cells(display_columns: list[dict], row: dict) -> list:
    """One data row over the display columns. The photo column's
    plain value IS its filename (the CSV/XLSX decision — a stable
    name, never an expiring URL); the "#" cell is the row number."""
    cells = []
    for column in display_columns:
        if column["key"] == "#":
            cells.append(row.get("number") or "")
            continue
        value = _plain_value(column, row)
        cells.append(format(value, "f") if isinstance(value, Decimal) else value)
    return cells


def render_csv(report: dict, title: str = "Inventory report", currency: str = "USD") -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    display = _display_columns(report)
    if _show_summary(report):
        writer.writerow([f"# Toolbox Vault — {title}"])
        prepared_line = _prepared_for_line(report)
        if prepared_line:
            writer.writerow([f"# {prepared_line}"])
        writer.writerow([f"# {_summary_line(report, currency)}"])
    writer.writerow([c["label"] for c in display])
    for kind, payload in _flat_rows(report):
        if kind == "group":
            writer.writerow([f"## {payload['label']}"] + [""] * (len(display) - 1))
        elif kind == "row":
            cells = _row_cells(display, payload)
            writer.writerow([str(c) for c in cells])
        elif kind == "subtotal":
            writer.writerow(
                _subtotal_cells(display, f"Subtotal — {payload['label']}", payload["subtotal"])
            )
        else:  # total
            writer.writerow(_subtotal_cells(display, "Total", payload))
    return buffer.getvalue().encode("utf-8")


def _photo_png(photo: dict | None, cache: dict) -> tuple[bytes, int, int] | None:
    """Fetch + normalize a row's photo for embedding: PIL-decoded,
    thumbnailed, re-encoded as PNG (one form every renderer can
    embed regardless of the source format — JPEG/PNG/WebP).
    Returns (png bytes, px width, px height) or None — a missing
    or unreadable object degrades to the placeholder, never an
    error. Cached per render by storage key."""
    if not photo:
        return None
    key = photo.get("key")
    if not key:
        return None
    if key in cache:
        return cache[key]
    result = None
    try:
        from PIL import Image

        raw = storage.fetch(key)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((192, 192))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        result = (buffer.getvalue(), image.size[0], image.size[1])
    except Exception:
        result = None
    cache[key] = result
    return result


def render_xlsx(report: dict, title: str = "Inventory report", currency: str = "USD") -> bytes:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    display = _display_columns(report)
    bold = Font(bold=True)
    if _show_summary(report):
        ws.append([f"Toolbox Vault — {title}"])
        ws[ws.max_row][0].font = bold
        prepared_line = _prepared_for_line(report)
        if prepared_line:
            ws.append([prepared_line])
            ws[ws.max_row][0].font = bold
        ws.append([_summary_line(report, currency)])
        ws[ws.max_row][0].font = bold
        ws.append([])
    header_row = ws.max_row + 1
    ws.append([c["label"] for c in display])
    for cell in ws[header_row]:
        cell.font = bold

    photo_index = next(
        (i for i, c in enumerate(display) if c["key"] == "photo"), None
    )
    photo_cache: dict = {}
    pending_images: list[tuple[int, dict]] = []
    for kind, payload in _flat_rows(report):
        if kind == "group":
            ws.append([f"## {payload['label']}"] + [""] * (len(display) - 1))
            ws[ws.max_row][0].font = bold
        elif kind == "row":
            ws.append(_row_cells(display, payload))
            if photo_index is not None and payload.get("photo"):
                pending_images.append((ws.max_row, payload["photo"]))
        elif kind == "subtotal":
            ws.append(
                _subtotal_cells(display, f"Subtotal — {payload['label']}", payload["subtotal"])
            )
            for cell in ws[ws.max_row]:
                cell.font = bold
        else:
            ws.append(_subtotal_cells(display, "Total", payload))
            for cell in ws[ws.max_row]:
                cell.font = bold

    if photo_index is not None:
        letter = get_column_letter(photo_index + 1)
        for row_number, photo in pending_images:
            normalized = _photo_png(photo, photo_cache)
            if normalized is None:
                continue  # filename text stays in the cell
            png_bytes, px_w, px_h = normalized
            image = XLImage(io.BytesIO(png_bytes))
            scale = min(44 / px_w, 33 / px_h)
            image.width = max(1, int(px_w * scale))
            image.height = max(1, int(px_h * scale))
            ws.add_image(image, f"{letter}{row_number}")
            # The picture carries the cell now; the filename text
            # would just peek out from behind it.
            ws.cell(row=row_number, column=photo_index + 1).value = None
            ws.row_dimensions[row_number].height = 27  # ≈ the 33px image
    for column_cells in ws.columns:
        width = max(len(str(c.value or "")) for c in column_cells) + 2
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(width, 10), 42)
    if photo_index is not None:
        # The photo column sizes to its thumbnails, not its text.
        ws.column_dimensions[get_column_letter(photo_index + 1)].width = 9
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# -- PDF -------------------------------------------------------------------------

_TYPE_WEIGHTS = {"text": 1.7, "money": 1.35, "number": 0.75, "date": 1.15}
_PHOTO_WIDTH_MM = 16.0  # the photo column is a picture box, not text
_NUMBER_WIDTH_MM = 9.0  # the "#" column
_PHOTO_ROW_MM = 13.0  # row height when a photo column is present
_TEXT_ROW_MM = 5.5


def _pdf_safe(text) -> str:
    """fpdf2's core fonts render through the encoding set on the
    document (_ReportPDF sets cp1252 / WinAnsi): map the
    typographic characters the display layer uses onto safe
    equivalents and fold anything still unrepresentable to a
    stand-in. cp1252 carries the € / £ / ¥ signs the money
    formatter emits — under the old latin-1 fold an EUR owner's
    amounts printed as "?300.00" while the screen showed
    "€300.00". Symbols with no cp1252 glyph (₹, ₩, ₪, ₺, zł)
    still fold; printing those takes an embedded Unicode font."""
    text = str(text)
    text = (
        text.replace("—", "-")
        .replace("–", "-")
        .replace("…", "...")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    return text.encode("cp1252", errors="replace").decode("cp1252")


class _ReportPDF:
    def __init__(self, report: dict, title: str, owner, currency: str = "USD"):
        self._currency = currency
        from fpdf import FPDF

        options = report.get("options") or {}
        self.portrait = options.get("orientation") == "portrait"
        self.show_summary = bool(options.get("show_summary", True))
        self.display = _display_columns(report)
        self.has_photo = any(c["key"] == "photo" for c in self.display)
        self.row_height = _PHOTO_ROW_MM if self.has_photo else _TEXT_ROW_MM
        self._photo_cache: dict = {}

        # The shared document frame (core.docframe): the model's
        # wordmark footer on every page, its header on page 1.
        class PDF(docframe.FramePDF, FPDF):
            pass

        pdf = PDF(orientation="P" if self.portrait else "L", unit="mm", format="A4")
        pdf.frame_chrome = docframe.chrome_for(owner)
        pdf.frame_when = date.today()
        # WinAnsi so the owner's currency signs (€/£/¥) print as
        # themselves — see _pdf_safe. Amounts stay the owner's.
        pdf.core_fonts_encoding = "cp1252"
        pdf.set_auto_page_break(auto=True, margin=16)
        pdf.set_margins(10, 10, 10)
        self.pdf = pdf
        self.report = report
        self.title = title
        self.usable = pdf.w - 20  # A4 minus the 10mm margins

        fixed = {}
        weights = []
        for i, column in enumerate(self.display):
            if column["key"] == "photo":
                fixed[i] = _PHOTO_WIDTH_MM
                weights.append(0.0)
            elif column["key"] == "#":
                fixed[i] = _NUMBER_WIDTH_MM
                weights.append(0.0)
            else:
                weights.append(_TYPE_WEIGHTS.get(column["type"], 1.4))
        # The name column always gets extra room.
        for i, c in enumerate(self.display):
            if c["key"] == "name":
                weights[i] = 3.0
        remaining = self.usable - sum(fixed.values())
        total_weight = sum(weights) or 1.0
        self.widths = [
            fixed[i] if i in fixed else w / total_weight * remaining
            for i, w in enumerate(weights)
        ]

    def _fit(self, text: str, width: float) -> str:
        pdf = self.pdf
        text = _pdf_safe(text)
        if pdf.get_string_width(text) <= width - 1.5:
            return text
        while text and pdf.get_string_width(text + "...") > width - 1.5:
            text = text[:-1]
        return text + "..."

    def _row_line(self) -> None:
        """The faint grey hairline at the cursor's current
        height (standard element 6), the pen restored after —
        this table's rows used to rule themselves in bold
        black; the standard retires that weight everywhere."""
        pdf = self.pdf
        y = pdf.get_y()
        pdf.set_draw_color(*docframe.ROW_LINE)
        pdf.set_line_width(docframe.ROW_LINE_WIDTH)
        pdf.line(pdf.l_margin, y, pdf.l_margin + self.usable, y)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_xy(pdf.l_margin, y)

    def _header_row(self) -> None:
        """The grey banner header (standard element 5): a
        light grey band naming every column. The old black
        grid (border=1) is gone — the band itself + the faint
        hairline under it do the header's work now."""
        pdf = self.pdf
        pdf.set_font("helvetica", "B", 7.5)
        pdf.set_fill_color(225, 225, 225)
        for column, width in zip(self.display, self.widths):
            pdf.cell(width, 6, self._fit(column["label"], width), border=0, fill=True)
        pdf.ln()
        self._row_line()

    def _document_header(self) -> None:
        """The shared frame's top (core.docframe — centered
        title, prepared date, the bordered PREPARED FOR box),
        then this report's summary under it as the standard's
        navy banner (element 4): the counts flow from the left
        in regular white, the total value parks at the right
        end in bold white — the statement banner's own shape."""
        pdf = self.pdf
        pdf.frame_header(self.title, self.report.get("prepared_for") or {})
        pdf.ln(2)

        if self.show_summary:
            summary = self.report.get("summary") or {}
            band_y = pdf.get_y()
            pdf.set_fill_color(*docframe.NAVY)
            pdf.rect(pdf.l_margin, band_y, self.usable, 7.5, style="F")
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("helvetica", "", 10)
            flow = _pdf_safe(
                f"TOTAL ITEMS {summary.get('items', 0)}"
                f"  ·  {summary.get('units', 0)} UNITS"
            )
            pdf.set_xy(pdf.l_margin, band_y)
            pdf.cell(pdf.get_string_width(flow) + 0.5, 7.5, flow)
            pdf.set_font("helvetica", "B", 10)
            parked = _pdf_safe(
                "TOTAL VALUE "
                + core_money.format_money(
                    Decimal(summary.get("price_total", "0")), self._currency
                )
            )
            pdf.set_xy(pdf.l_margin, band_y)
            pdf.cell(self.usable, 7.5, parked, align="R")
            pdf.set_text_color(0, 0, 0)
            pdf.set_xy(pdf.l_margin, band_y + 7.5)
            pdf.set_font("helvetica", "", 8)
            pdf.set_text_color(90, 90, 90)
            pdf.cell(
                0, 4.5,
                _pdf_safe(
                    f"Replacement value {core_money.format_money(Decimal(summary.get('replacement', '0')), self._currency)}"
                ),
                new_x="LMARGIN", new_y="NEXT",
            )
            pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    def _draw_row(self, cells: list[dict], bold: bool = False, fill: bool = False, navy: bool = False) -> None:
        """One table row. Cells are {"text": str} or
        {"photo": photo-dict | None} for the photo column.
        Every row rules itself with the faint grey hairline
        (the border="B" below, drawn in the standard's grey);
        a `navy` row is a totals row — navy ground, white bold
        lettering, its values still sitting in their columns."""
        pdf = self.pdf
        height = self.row_height
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()
            self._header_row()
        y0 = pdf.get_y()
        x = pdf.l_margin
        pdf.set_font("helvetica", "B" if (bold or navy) else "", 7.5)
        if navy:
            pdf.set_fill_color(*docframe.NAVY)
            pdf.set_text_color(255, 255, 255)
            fill = True
        elif fill:
            pdf.set_fill_color(240, 240, 240)
        pdf.set_draw_color(*docframe.ROW_LINE)
        pdf.set_line_width(docframe.ROW_LINE_WIDTH)
        for spec, width in zip(cells, self.widths):
            if "photo" in spec:
                pdf.set_xy(x, y0)
                pdf.cell(width, height, "", border="B", fill=fill)
                self._draw_photo(spec["photo"], x, y0, width, height)
            else:
                pdf.set_xy(x, y0)
                pdf.cell(width, height, self._fit(spec["text"], width), border="B", fill=fill)
            x += width
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, y0 + height)

    def _draw_photo(self, photo: dict | None, x: float, y0: float, width: float, height: float) -> None:
        pdf = self.pdf
        normalized = _photo_png(photo, self._photo_cache)
        if normalized is None:
            # The clean placeholder: a small grey note in the box,
            # never a broken image.
            pdf.set_xy(x + 0.5, y0 + height / 2 - 1.8)
            pdf.set_font("helvetica", "", 5.5)
            pdf.set_text_color(150, 150, 150)
            pdf.cell(width - 1, 3.6, "no photo", align="C")
            pdf.set_text_color(0, 0, 0)
            return
        png_bytes, px_w, px_h = normalized
        box_w, box_h = width - 2, height - 2
        scale = min(box_w / px_w, box_h / px_h)
        img_w, img_h = px_w * scale, px_h * scale
        pdf.image(
            io.BytesIO(png_bytes),
            x=x + (width - img_w) / 2,
            y=y0 + (height - img_h) / 2,
            w=img_w,
            h=img_h,
        )

    def render(self) -> bytes:
        pdf = self.pdf
        pdf.add_page()
        self._document_header()
        self._header_row()
        display = self.display
        grouped = self.report["grouping"] != "none"
        for group in self.report["groups"]:
            if grouped:
                subtotal = group["subtotal"]
                pdf.set_font("helvetica", "B", 7.5)
                pdf.set_fill_color(240, 240, 240)
                if pdf.get_y() + 6 > pdf.page_break_trigger:
                    pdf.add_page()
                    self._header_row()
                pdf.set_draw_color(*docframe.ROW_LINE)
                pdf.set_line_width(docframe.ROW_LINE_WIDTH)
                pdf.cell(
                    0, 6,
                    self._fit(
                        f"{group['label']} — {subtotal['count']} items · "
                        f"{core_money.format_money(Decimal(subtotal['price_total']), self._currency)}",
                        self.usable,
                    ),
                    border="B", fill=True, new_x="LMARGIN", new_y="NEXT",
                )
                pdf.set_draw_color(0, 0, 0)
                pdf.set_line_width(0.2)
            for row in group["rows"]:
                indent = "    " if row["row_type"] != "asset" else ""
                cells = []
                for column in display:
                    if column["key"] == "#":
                        cells.append({"text": str(row.get("number") or "")})
                    elif column["key"] == "photo":
                        cells.append({"photo": row.get("photo")})
                    else:
                        text = row["display"].get(column["key"], "")
                        if column["key"] == "name":
                            text = indent + text
                        cells.append({"text": text})
                self._draw_row(cells)
            if grouped:
                subtotal = group["subtotal"]
                cells = [
                    {
                        "text": (
                            # Totals rows read just "TOTAL:"
                            # (standard, Ryan 2026-11-06) — the
                            # group band above already names the
                            # group; the values sit in their
                            # columns on the navy ground.
                            "TOTAL:"
                            if c["key"] == "name"
                            else row_display_subtotal(c, subtotal, self._currency)
                        )
                    }
                    for c in display
                ]
                self._draw_row(cells, navy=True)
        totals = self.report["totals"]
        cells = [
            {
                "text": (
                    # "TOTAL:" + the values in their columns —
                    # the counts the old label restated ride
                    # the navy banner at the top now.
                    "TOTAL:"
                    if c["key"] == "name"
                    else row_display_subtotal(c, totals, self._currency)
                )
            }
            for c in display
        ]
        self._draw_row(cells, navy=True)
        return bytes(self.pdf.output())


def row_display_subtotal(column: dict, subtotal: dict, currency: str = "USD") -> str:
    if column["key"] == "price_total":
        return core_money.format_money(Decimal(subtotal["price_total"]), currency)
    if column["key"] == "replacement":
        return core_money.format_money(Decimal(subtotal["replacement"]), currency)
    return ""


def render_pdf(report: dict, title: str, owner: core_models.User) -> bytes:
    return _ReportPDF(
        report, title, owner, core_money.normalize_currency(owner.currency)
    ).render()


# -- delivery ----------------------------------------------------------------------


def report_filename(report_name: str | None, fmt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (report_name or "inventory-report").lower()).strip("-")
    return f"{slug or 'inventory-report'}.{EXTENSIONS[fmt]}"


def render(report: dict, fmt: str, title: str, owner: core_models.User) -> bytes:
    currency = core_money.normalize_currency(owner.currency)
    if fmt == "csv":
        return render_csv(report, title, currency)
    if fmt == "xlsx":
        return render_xlsx(report, title, currency)
    return render_pdf(report, title, owner)


def email_report(
    db: Session,
    owner: core_models.User,
    spec,
    fmt: str,
    recipient: str | None,
    report_name: str | None,
    dealer_visible: bool = True,
) -> dict:
    """Generate the file and send it through the central email seam
    (dev mode logs + outbox-records until Resend is live)."""
    report = service.build_report(
        db,
        owner.id,
        spec,
        dealer_visible=dealer_visible,
        prepared_for=service.prepared_for_of(owner),
    )
    title = report_name or "Inventory report"
    content = render(report, fmt, title, owner)
    to = recipient or owner.email
    filename = report_filename(report_name, fmt)
    sent = notifications.send_email(
        db,
        to=to,
        subject=f"Toolbox Vault report — {title}",
        body=(
            f"Your Toolbox Vault report “{title}” is attached "
            f"({filename}).\n\n"
            f"It covers {report['total_rows']} items with a total "
            f"value of {core_money.format_money(Decimal(report['totals']['price_total']), core_money.normalize_currency(owner.currency))}.\n\n"
            "Generated with Toolbox Vault."
        ),
        kind=notifications.KIND_REPORT,
        attachment=(filename, content),
    )
    return {"sent": sent, "recipient": to, "filename": filename}
