"""Generate the Downloads page's document assets (lane:
downloads-documents, owner order 2026-11-08).

The Documents tab hands out nine files. Eight are generated
here; the ninth — the free tool inventory sheet — is NOT: its
bytes are the production capture of the sheet the old page
served (golden-inventory-sheet.xlsx in the lane evidence,
sha256 dff2396c…), packaged verbatim as files/tool-inventory.xlsx
so the catalog serves the very file the old page handed out.

Run with the backend venv from backend/:
    .venv/bin/python -m app.modules.downloads.generate_assets

Outputs land in files/ next to this module. The spreadsheets
carry WORKING formulas (verified by a headless LibreOffice
recalculation in the lane proof); the PDFs wear the shared
document frame (app.core.docframe — wordmark footer, navy
report palette), Letter portrait, built to be printed and
written on.

Layout sweep (lane downloads-doc-sweep, owner order
2026-11-08): every form's page count must be EARNED — no
signature orphaned on its own page, no mostly-empty final
page. One-page forms end on page one; two-page forms balance
their sections and fill genuine open space with a notes area
or a working table. The intake form was audited and already
fills its page; it is unchanged.
"""

import io
from datetime import date
from pathlib import Path

from PIL import Image as PILImage

FILES_DIR = Path(__file__).resolve().parent / "files"
_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK = _ASSETS / "wordmark-transparent.png"

NAVY_HEX = "002B5C"
NAVY = (0, 43, 92)


# ------------------------------------------------------------------
# Spreadsheets (openpyxl)
# ------------------------------------------------------------------

def _xl_wordmark():
    from openpyxl.drawing.image import Image as XLImage

    with PILImage.open(_WORDMARK) as master:
        derivative = master.copy()
        derivative.thumbnail((840, 840))
        buffer = io.BytesIO()
        derivative.save(buffer, format="PNG")
        buffer.seek(0)
    logo = XLImage(buffer)
    logo.width = 336
    logo.height = 50
    return logo


def _xl_styles():
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color="B9C2CC")
    return {
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "title_fill": PatternFill("solid", fgColor=NAVY_HEX),
        "title_font": Font(name="Calibri", size=14, bold=True, color="FFFFFF"),
        "band_fill": PatternFill("solid", fgColor=NAVY_HEX),
        "band_font": Font(name="Calibri", size=11, bold=True, color="FFFFFF"),
        "input_fill": PatternFill("solid", fgColor="DCE6F1"),
        "result_fill": PatternFill("solid", fgColor="F2F2F2"),
        "label_font": Font(name="Calibri", size=11),
        "result_font": Font(name="Calibri", size=11, bold=True, color=NAVY_HEX),
        "hint_font": Font(name="Calibri", size=10, italic=True, color="5A6B84"),
        "note_font": Font(name="Calibri", size=10, color="334155"),
        "money": '"$"#,##0.00',
        "hours": "0.00",
        "pct": "0%",
    }


def build_paycheck_calculator(path: Path) -> None:
    from openpyxl import Workbook

    s = _xl_styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "Paycheck Calculator"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.column_dimensions["A"].width = 47
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 44

    ws.merge_cells("A1:C1")
    c = ws["A1"]
    c.value = "MECHANIC PAYCHECK & OVERTIME CALCULATOR"
    c.font = s["title_font"]
    c.fill = s["title_fill"]
    ws.row_dimensions[1].height = 26
    ws.merge_cells("A2:C2")
    ws["A2"] = (
        "Toolbox Vault — free download. The blue cells are yours to change; "
        "the grey boxes do the math."
    )
    ws["A2"].font = s["hint_font"]

    def band(row: int, text: str) -> None:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        cell = ws.cell(row=row, column=1, value=text)
        cell.font = s["band_font"]
        cell.fill = s["band_fill"]

    def input_row(row: int, label: str, value, fmt: str, hint: str = "") -> None:
        lab = ws.cell(row=row, column=1, value=label)
        lab.font = s["label_font"]
        val = ws.cell(row=row, column=2, value=value)
        val.number_format = fmt
        val.fill = s["input_fill"]
        val.border = s["border"]
        if hint:
            h = ws.cell(row=row, column=3, value=hint)
            h.font = s["hint_font"]

    def result_row(row: int, label: str, formula: str, fmt: str, bold=False) -> None:
        lab = ws.cell(row=row, column=1, value=label)
        lab.font = s["result_font"] if bold else s["label_font"]
        val = ws.cell(row=row, column=2)
        val.value = formula
        val.number_format = fmt
        val.fill = s["result_fill"]
        val.border = s["border"]
        val.font = s["result_font"]

    band(4, "YOUR NUMBERS")
    input_row(5, "Hourly pay rate", 32.00, s["money"], "What the shop pays you per hour")
    input_row(6, "Regular hours (per week)", 40, s["hours"])
    input_row(7, "Overtime hours (per week)", 6, s["hours"], "Hours past 40 in the week")
    input_row(8, "Overtime multiplier", 1.5, "0.00", "1.5 is time-and-a-half")
    input_row(9, "Double-time hours (per week)", 0, s["hours"])
    input_row(10, "Double-time multiplier", 2, "0.00", "2 is double time")

    band(12, "YOUR PAY — GROSS, BEFORE TAXES AND DEDUCTIONS")
    result_row(13, "Regular pay (weekly)", "=B5*B6", s["money"])
    result_row(14, "Overtime pay (weekly)", "=B5*B7*B8", s["money"])
    result_row(15, "Double-time pay (weekly)", "=B5*B9*B10", s["money"])
    result_row(16, "GROSS PAY — WEEKLY", "=SUM(B13:B15)", s["money"], bold=True)
    result_row(17, "Gross pay — biweekly (2 weeks)", "=B16*2", s["money"])
    result_row(18, "Gross pay — yearly (52 weeks)", "=B16*52", s["money"])
    result_row(
        19,
        "Blended hourly rate (gross ÷ all hours worked)",
        '=IF((B6+B7+B9)=0,"",B16/(B6+B7+B9))',
        s["money"],
    )

    ws.merge_cells("A21:C21")
    ws["A21"] = (
        "Gross pay is before taxes, benefits, and deductions — your take-home "
        "will be lower. Flat-rate techs: pair this with the Flat-Rate Hours Tracker."
    )
    ws["A21"].font = s["note_font"]
    ws.add_image(_xl_wordmark(), "A23")
    # Print setup (layout sweep): the calculator is a one-page
    # sheet by nature — it prints on exactly one page, with
    # taller rows so a printout is writable instead of huddling
    # at the top of the page. The print area runs past the
    # wordmark's anchor row: the image is ~2.5 rows tall and a
    # print area ending at its anchor row clips it.
    ws.sheet_format.defaultRowHeight = 18
    ws.row_dimensions[1].height = 30
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.print_area = "A1:C26"
    wb.save(path)


def build_flat_rate_tracker(path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    s = _xl_styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "Flat Rate Log"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    widths = {"A": 13, "B": 11, "C": 54, "D": 15, "E": 13, "F": 13, "G": 14}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    ws.merge_cells("A1:G1")
    c = ws["A1"]
    c.value = "FLAT-RATE HOURS TRACKER"
    c.font = s["title_font"]
    c.fill = s["title_fill"]
    ws.row_dimensions[1].height = 26

    lab = ws.cell(row=2, column=1, value="Your flat-rate pay ($ per flagged hour)")
    lab.font = s["label_font"]
    rate = ws.cell(row=2, column=2, value=45.00)
    rate.number_format = s["money"]
    rate.fill = s["input_fill"]
    rate.border = s["border"]
    hint = ws.cell(row=2, column=4, value="The Earned column pays Flagged hrs × this rate.")
    hint.font = s["hint_font"]

    headers = [
        "Date",
        "RO #",
        "Job / repair description",
        "Flagged hrs (book)",
        "Actual hrs",
        "Efficiency %",
        "Earned $",
    ]
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col, value=text)
        cell.font = s["band_font"]
        cell.fill = s["band_fill"]
        cell.border = s["border"]

    first, last = 5, 34
    input_cols = (1, 2, 3, 4, 5)
    for row in range(first, last + 1):
        for col in input_cols:
            cell = ws.cell(row=row, column=col)
            cell.border = s["border"]
            if col in (4, 5):
                cell.fill = s["input_fill"]
                cell.number_format = s["hours"]
            if col == 1:
                cell.number_format = "mm/dd/yyyy"
        eff = ws.cell(row=row, column=6)
        eff.value = f'=IF(OR(D{row}="",E{row}="",E{row}=0),"",D{row}/E{row})'
        eff.number_format = s["pct"]
        eff.border = s["border"]
        earned = ws.cell(row=row, column=7)
        earned.value = f'=IF(D{row}="","",D{row}*$B$2)'
        earned.number_format = s["money"]
        earned.border = s["border"]

    # One grey example row (same convention as the inventory sheet).
    example_font = Font(name="Calibri", size=11, italic=True, color="808080")
    example = [date(2026, 11, 3), "10452", "Front brake pads + rotors — example, delete this row", 2.4, 1.9]
    for col, value in enumerate(example, start=1):
        cell = ws.cell(row=first, column=col)
        cell.value = value
        cell.font = example_font

    total_row = last + 1
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=3)
    lab = ws.cell(row=total_row, column=1, value="TOTALS")
    lab.font = s["band_font"]
    lab.fill = s["band_fill"]
    for col, formula, fmt in (
        (4, f"=SUM(D{first}:D{last})", s["hours"]),
        (5, f"=SUM(E{first}:E{last})", s["hours"]),
        (6, f'=IF(E{total_row}=0,"",D{total_row}/E{total_row})', s["pct"]),
        (7, f"=SUM(G{first}:G{last})", s["money"]),
    ):
        cell = ws.cell(row=total_row, column=col)
        cell.value = formula
        cell.number_format = fmt
        cell.fill = s["band_fill"]
        cell.font = s["band_font"]
        cell.border = s["border"]

    note_row = total_row + 2
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=7)
    ws.cell(row=note_row, column=1).value = (
        "Efficiency = flagged hrs ÷ actual hrs. Over 100% means you beat the book time. "
        "Toolbox Vault — free download."
    )
    ws.cell(row=note_row, column=1).font = s["note_font"]
    ws.add_image(_xl_wordmark(), f"A{note_row + 2}")
    # Print setup (layout sweep): one landscape page, fitted —
    # the log, its totals and the wordmark fill the sheet with
    # no empty tail. The print area runs three rows past the
    # wordmark's anchor row so the image prints whole.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.print_area = f"A1:G{note_row + 5}"
    wb.save(path)


# ------------------------------------------------------------------
# PDF forms (fpdf2 on the shared document frame)
# ------------------------------------------------------------------

def _pdf(title: str):
    from app.core import docframe

    cls = docframe.framed_pdf_class()
    pdf = cls(orientation="P", unit="mm", format="Letter")
    pdf.frame_chrome = docframe.CHROME["en"]
    pdf.frame_when = date.today()
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.frame_header(title, None)
    pdf.ln(4)
    return pdf


def _safe(text: str) -> str:
    from app.core.docframe import _safe as fold

    return fold(text)


def _section(pdf, title: str) -> None:
    if pdf.get_y() > 248:
        pdf.add_page()
    pdf.set_font("helvetica", "B", 11)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 7, _safe(f"  {title}"), new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2.2)


def _field(pdf, label: str, line_w: float, label_w: float = 30) -> None:
    """A labeled write-in line."""
    y = pdf.get_y()
    pdf.set_font("helvetica", "", 9.5)
    pdf.cell(label_w, 5.5, _safe(label))
    x = pdf.get_x()
    pdf.set_draw_color(150, 158, 168)
    pdf.line(x, y + 5.2, x + line_w, y + 5.2)
    pdf.set_xy(x + line_w + 4, y)
    pdf.set_draw_color(0, 0, 0)


def _field_row(pdf, fields: list[tuple[str, float, float]]) -> None:
    # Keep a field row together: a row that starts within the
    # last ~14mm would split its labels from their lines across
    # the page break.
    if pdf.get_y() > 250:
        pdf.add_page()
    x0 = pdf.l_margin
    for label, label_w, line_w in fields:
        _field(pdf, label, line_w, label_w)
    pdf.set_xy(x0, pdf.get_y() + 7.5)


def _write_lines(pdf, n: int, h: float = 7.0) -> None:
    pdf.set_draw_color(176, 184, 194)
    for _ in range(n):
        y = pdf.get_y() + h
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.set_y(y)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(2)


def _box(pdf, x: float, y: float, size: float = 3.8) -> None:
    pdf.set_draw_color(90, 100, 112)
    pdf.rect(x, y, size, size)
    pdf.set_draw_color(0, 0, 0)


def _check_item(pdf, label: str, options: tuple[str, ...] = ("OK", "Watch", "Fail")) -> None:
    """One inspection line: item text, then a checkbox per option."""
    if pdf.get_y() > 258:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_xy(pdf.l_margin, y)
    pdf.cell(104, 5.6, _safe(label))
    x = pdf.l_margin + 108
    pdf.set_font("helvetica", "", 8.5)
    for opt in options:
        _box(pdf, x, y + 0.9)
        pdf.set_xy(x + 5, y)
        pdf.cell(18, 5.6, _safe(opt))
        x += 25
    pdf.set_draw_color(215, 219, 224)
    pdf.line(pdf.l_margin, y + 6.4, pdf.w - pdf.r_margin, y + 6.4)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_y(y + 7.0)


def _check_line(pdf, label: str) -> None:
    """A single-checkbox line (yes/no style)."""
    if pdf.get_y() > 258:
        pdf.add_page()
    y = pdf.get_y()
    _box(pdf, pdf.l_margin, y + 0.9)
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_xy(pdf.l_margin + 6, y)
    pdf.cell(0, 5.6, _safe(label))
    pdf.set_y(y + 6.6)


def _table_head(pdf, cols: list[tuple[str, float]]) -> None:
    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    for text, w in cols:
        pdf.cell(w, 6, _safe(f" {text}"), border=0, fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)


def _table_rows(pdf, cols: list[tuple[str, float]], rows: int, h: float = 7.0) -> None:
    from app.core.docframe import ROW_LINE

    pdf.set_draw_color(*ROW_LINE)
    for _ in range(rows):
        y = pdf.get_y()
        pdf.set_xy(pdf.l_margin, y)
        for _text, w in cols:
            pdf.cell(w, h, "", border=0)
        pdf.line(pdf.l_margin, y + h, pdf.w - pdf.r_margin, y + h)
        pdf.set_y(y + h)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(1.5)


def build_inspection_checklist(path: Path) -> None:
    pdf = _pdf("Vehicle Inspection Checklist")
    _field_row(pdf, [("Date", 14, 34), ("Customer", 20, 52), ("Phone", 14, 38)])
    _field_row(pdf, [("Vehicle", 16, 62), ("VIN", 10, 44), ("Mileage", 16, 26)])
    _field_row(pdf, [("License plate", 26, 34), ("Technician", 20, 52), ("RO #", 12, 30)])
    pdf.set_font("helvetica", "I", 9)
    pdf.cell(0, 5, _safe("Mark every line: OK = passes today · Watch = will need attention · Fail = needs work now."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    sections = [
        ("UNDER HOOD", [
            "Engine oil — level & condition", "Coolant — level & condition",
            "Brake fluid", "Power steering / washer fluid",
            "Belts — cracks, glaze, tension", "Hoses — leaks, swelling, soft spots",
            "Battery — terminals, hold-down, test result", "Air filter",
            "Visible leaks (oil / coolant / trans)",
        ]),
        ("TIRES, BRAKES & SUSPENSION", [
            "Tire tread — LF ____/32  RF ____/32  LR ____/32  RR ____/32",
            "Tire pressure — set to placard", "Tire wear pattern / alignment signs",
            "Front brake pads & rotors", "Rear brakes / drums",
            "Brake lines & hoses", "Shocks / struts — leaks, bounce",
            "Ball joints & tie rods", "Wheel bearings — play, noise",
        ]),
        ("LIGHTS, ELECTRICAL & SAFETY", [
            "Headlights / tail / brake / turn signals", "Horn & wipers / blades",
            "Warning lights on dash", "Seat belts",
            "Spare tire & jack present",
        ]),
        ("EXHAUST & UNDERSIDE", [
            "Exhaust — leaks, hangers, rust", "Frame / underbody damage",
            "CV boots & axles", "Differential / transfer case leaks",
        ]),
        ("ROAD TEST", [
            "Starts & idles clean", "Shifts / clutch engagement",
            "Braking — straight, no pull or pulsation", "Steering — center, no wander",
            "Noises — squeaks, clunks, hums", "A/C & heat output",
        ]),
    ]
    for title, items in sections:
        _section(pdf, title)
        for item in items:
            _check_item(pdf, item)
        pdf.ln(1.5)
    # Layout sweep: page 2 used to end at the halfway mark —
    # the notes block alone left a void under it. The page now
    # earns its length: a working table for the recommended
    # work, then a notes area sized to the rest of the page,
    # with the sign-off at the foot of a full page.
    _section(pdf, "RECOMMENDED WORK")
    rec_cols = [("Work needed", 112), ("Priority", 30), ("Est. cost", 44)]
    _table_head(pdf, rec_cols)
    _table_rows(pdf, rec_cols, 6)
    _section(pdf, "NOTES")
    _write_lines(pdf, 8)
    _field_row(pdf, [("Inspected by", 24, 60), ("Date", 12, 30)])
    pdf.output(str(path))


def build_prepurchase_form(path: Path) -> None:
    pdf = _pdf("Pre-Purchase Vehicle Inspection")
    _field_row(pdf, [("Buyer", 14, 56), ("Phone", 14, 40), ("Date", 12, 28)])
    _field_row(pdf, [("Seller", 14, 56), ("Asking price $", 26, 34), ("Mileage", 16, 28)])
    _field_row(pdf, [("Year / Make / Model", 34, 62), ("VIN", 10, 52)])
    _field_row(pdf, [("Title status", 22, 52), ("Title state", 20, 30), ("Lien?", 12, 20)])
    pdf.set_font("helvetica", "I", 9)
    pdf.cell(0, 5, _safe("Rate each area: Good / Fair / Poor. Any Poor or red flag belongs in the summary."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for title, items in [
        ("EXTERIOR & BODY", ["Paint & body panels — dents, rust, filler", "Panel gaps & paint match (accident signs)", "Glass & mirrors", "Lights & lenses", "Tires — match, tread, age"]),
        ("INTERIOR", ["Seats, belts & airbag light", "All switches, windows, locks", "A/C & heat", "Odors — smoke, mildew, coolant", "Electronics — radio, cluster, warnings"]),
        ("ENGINE & DRIVETRAIN", ["Cold start — smoke, noises", "Fluids — oil, coolant, trans (color & smell)", "Leaks", "Belts, hoses, mounts", "Transmission shifts — all gears", "4x4 / AWD engagement"]),
        ("UNDERBODY", ["Frame rails — bends, welds, rust", "Flood signs — mud lines, rust under seats", "Suspension & steering wear", "Brake lines & fuel lines", "Exhaust condition"]),
        ("ROAD TEST", ["Acceleration & power", "Braking — pull, pulsation, noise", "Highway — vibration, wander", "Turns — CV / bearing noise", "All gears incl. reverse"]),
    ]:
        _section(pdf, title)
        for item in items:
            _check_item(pdf, item, options=("Good", "Fair", "Poor"))
        pdf.ln(1.5)
    _section(pdf, "RED FLAGS — CHECK ANY THAT APPLY")
    for item in [
        "Odometer reading doesn't match wear or records",
        "Title is branded (salvage / rebuilt / flood) or missing",
        "VIN plates/tags don't match between dash, door, and title",
        "Seller won't allow an independent inspection or a cold start",
        "Fresh undercoating or paint hiding rust or damage",
        "Warning lights removed, taped over, or lit",
    ]:
        _check_line(pdf, item)
    pdf.ln(2)
    _section(pdf, "SUMMARY & RECOMMENDATION")
    _write_lines(pdf, 6)
    # Layout sweep: page 2 ended a third short. An estimate
    # table is real content on this form — what the findings
    # will cost — and it fills the page ahead of the verdict.
    _section(pdf, "ESTIMATED REPAIR COSTS")
    est_cols = [("Repair / concern", 130), ("Estimate", 56)]
    _table_head(pdf, est_cols)
    _table_rows(pdf, est_cols, 4)
    for opt in ["Buy at asking price", "Buy only at a lower price", "Walk away"]:
        _check_line(pdf, opt)
    pdf.ln(2)
    _field_row(pdf, [("Inspector", 20, 56), ("Signature", 20, 52), ("Date", 12, 26)])
    pdf.output(str(path))


def build_diagnostic_worksheet(path: Path) -> None:
    pdf = _pdf("Diagnostic Worksheet")
    _field_row(pdf, [("Date", 14, 32), ("Customer", 20, 54), ("Phone", 14, 38)])
    _field_row(pdf, [("Vehicle", 16, 62), ("VIN", 10, 44), ("Mileage", 16, 26)])
    _field_row(pdf, [("RO #", 12, 30), ("Technician", 20, 54), ("Advisor", 16, 40)])
    _section(pdf, "CUSTOMER CONCERN — IN THE CUSTOMER'S OWN WORDS")
    _write_lines(pdf, 3)
    _section(pdf, "WHEN DOES IT HAPPEN?")
    for item in [
        "Cold start only", "Hot / warmed up", "At idle", "Under load / accelerating",
        "At highway speed", "Turning / braking", "All the time", "Intermittent — no pattern yet",
    ]:
        _check_line(pdf, item)
    pdf.ln(2)
    _section(pdf, "CODES & DATA")
    _field_row(pdf, [("Codes found", 24, 120)])
    _field_row(pdf, [("Freeze-frame notes", 32, 112)])
    _section(pdf, "TESTS PERFORMED")
    cols = [("Test", 60), ("Expected", 42), ("Actual reading", 44), ("Result", 44)]
    _table_head(pdf, cols)
    _table_rows(pdf, cols, 8)
    # Layout sweep: the findings banner used to strand at the
    # foot of page 1 with its lines spilling onto a page 2 that
    # held nothing but the recommendation and the signature.
    # The worksheet is honestly two pages — so page 2 now opens
    # with the findings and carries the recommendation, a
    # parts & labor estimate, the approval, and a notes area:
    # both pages earn their count.
    pdf.add_page()
    _section(pdf, "FINDINGS & ROOT CAUSE")
    _write_lines(pdf, 6)
    _section(pdf, "RECOMMENDATION")
    _write_lines(pdf, 4)
    _section(pdf, "PARTS & LABOR ESTIMATE")
    est_cols = [("Part / item", 84), ("Part cost", 34), ("Labor hrs", 28), ("Labor cost", 40)]
    _table_head(pdf, est_cols)
    _table_rows(pdf, est_cols, 4)
    _field_row(pdf, [("Estimated cost $", 30, 30), ("Customer approved?", 32, 20), ("Tech signature", 28, 44)])
    _section(pdf, "NOTES")
    _write_lines(pdf, 8)
    pdf.output(str(path))


def build_electrical_worksheet(path: Path) -> None:
    pdf = _pdf("Electrical Diagnostic Worksheet")
    _field_row(pdf, [("Date", 14, 32), ("Customer", 20, 54), ("Phone", 14, 38)])
    _field_row(pdf, [("Vehicle", 16, 62), ("VIN", 10, 44), ("Mileage", 16, 26)])
    _field_row(pdf, [("RO #", 12, 30), ("Technician", 20, 54)])
    _section(pdf, "CIRCUIT / SYSTEM UNDER TEST")
    _write_lines(pdf, 2, h=6.6)
    _section(pdf, "BASELINE — BATTERY & CHARGING")
    _field_row(pdf, [("Battery voltage (resting)", 44, 24), ("Charging voltage", 32, 24), ("Battery test result", 34, 28)])
    _field_row(pdf, [("Parasitic draw (mA)", 36, 26), ("Spec / limit", 22, 30)])
    _section(pdf, "CHECKS — POWER, GROUND & VOLTAGE DROP")
    pdf.set_font("helvetica", "I", 9)
    pdf.cell(0, 5, _safe("Voltage drop: measure across the loaded circuit. Over 0.2 V on a power or ground leg is a fault."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    cols = [("Check point", 54), ("Expected", 30), ("Reading", 30), ("Drop + (V)", 24), ("Drop - (V)", 24), ("Result", 28)]
    _table_head(pdf, cols)
    # Layout sweep: this is a one-page worksheet, but the
    # signature row used to spill onto a page 2 of its own.
    # The checks table runs two rows shorter on a slightly
    # tighter row height (type size untouched) so the whole
    # form — signature included — ends on page one.
    _table_rows(pdf, cols, 6, h=6.6)
    _section(pdf, "VERIFICATION")
    for item in [
        "Power present at the component (loaded, not just key-on)",
        "Ground verified under load — voltage drop, not just continuity",
        "Connector pins — tension, corrosion, pushed-out terminals",
        "Wiggle test performed — fault changes with harness movement",
        "Known-good signal / swap test done where possible",
    ]:
        _check_line(pdf, item)
    pdf.ln(1)
    _section(pdf, "FINDINGS & REPAIR")
    _write_lines(pdf, 4, h=6.2)
    _field_row(pdf, [("Tech signature", 28, 56), ("Date", 12, 28)])
    pdf.output(str(path))


def build_intake_form(path: Path) -> None:
    pdf = _pdf("Customer Vehicle Intake Form")
    _section(pdf, "CUSTOMER")
    _field_row(pdf, [("Name", 14, 62), ("Phone", 14, 44), ("Alt phone", 20, 34)])
    _field_row(pdf, [("Email", 14, 66), ("Address", 16, 78)])
    _section(pdf, "VEHICLE")
    _field_row(pdf, [("Year / Make / Model", 34, 60), ("Color", 13, 30), ("Plate", 13, 28)])
    _field_row(pdf, [("VIN", 10, 62), ("Mileage in", 20, 26), ("Mileage out", 22, 26)])
    _field_row(pdf, [("Fuel level", 20, 20), ("Keys received", 26, 16), ("Valuables removed?", 36, 16)])
    _section(pdf, "REASON FOR VISIT — CUSTOMER'S WORDS")
    _write_lines(pdf, 4)
    _section(pdf, "SERVICE REQUESTED")
    for item in [
        "Diagnose the concern described above", "Oil & filter service",
        "Tire rotation / balance", "Brake inspection", "Alignment check",
        "State / safety inspection", "Other (describe below)",
    ]:
        _check_line(pdf, item)
    _write_lines(pdf, 2)
    _section(pdf, "AUTHORIZATION")
    pdf.set_font("helvetica", "", 9.5)
    pdf.multi_cell(0, 5, _safe(
        "I authorize the shop to perform the work checked above, together with the "
        "inspection and road testing needed to diagnose the vehicle. I understand "
        "estimates are given in good faith and that no work beyond the approved "
        "amount below will be performed without my okay."
    ))
    pdf.ln(2)
    _field_row(pdf, [("Approved up to $", 30, 28), ("Customer signature", 34, 52), ("Date", 12, 26)])
    _section(pdf, "SHOP USE")
    _field_row(pdf, [("RO #", 12, 26), ("Advisor", 16, 42), ("Promised", 20, 32), ("Tech", 12, 30)])
    pdf.output(str(path))


def build_torque_chart(path: Path) -> None:
    pdf = _pdf("Torque Conversion Chart")

    def table(title: str, rows: list[tuple[str, str, str]], heads: tuple[str, str, str]) -> None:
        _section(pdf, title)
        col_w = (pdf.w - pdf.l_margin - pdf.r_margin) / 3 - 0.1
        cols = [(heads[0], col_w), (heads[1], col_w), (heads[2], col_w)]
        _table_head(pdf, cols)
        from app.core.docframe import ROW_LINE

        pdf.set_draw_color(*ROW_LINE)
        shade = False
        for a, b, c in rows:
            y = pdf.get_y()
            if y > 252:
                pdf.add_page()
                y = pdf.get_y()
            pdf.set_xy(pdf.l_margin, y)
            if shade:
                pdf.set_fill_color(242, 245, 249)
            pdf.set_font("helvetica", "", 9.5)
            for text, w in ((a, col_w), (b, col_w), (c, col_w)):
                pdf.cell(w, 5.6, _safe(f" {text}"), border=0, fill=shade)
            pdf.line(pdf.l_margin, y + 5.6, pdf.w - pdf.r_margin, y + 5.6)
            pdf.set_y(y + 5.6)
            shade = not shade
        pdf.set_draw_color(0, 0, 0)
        pdf.ln(3)

    ftlb = list(range(5, 101, 5)) + list(range(110, 201, 10)) + [225, 250, 275, 300]
    rows = [
        (f"{v} ft-lb", f"{v * 12:,} in-lb", f"{v * 1.35582:,.1f} Nm")
        for v in ftlb
    ]
    table("FOOT-POUNDS TO INCH-POUNDS & NEWTON-METERS", rows, ("Foot-pounds", "Inch-pounds", "Newton-meters"))
    # Layout sweep: the first table fills page 1 exactly, and
    # the old position check let the second table's banner and
    # column header strand at the foot of page 1 with every
    # data row on page 2. The break is unconditional now, and
    # the range runs to 425 Nm so page 2 is full of chart
    # instead of ending a quarter short — sized so the math
    # note under the table keeps its seat on the same page
    # (any longer and the note spills to a third page).
    pdf.add_page()
    nm = list(range(5, 101, 5)) + list(range(110, 201, 10)) + [225, 250, 275, 300] + list(range(325, 426, 25))
    rows2 = [
        (f"{v} Nm", f"{v * 0.737562:,.1f} ft-lb", f"{v * 8.85075:,.0f} in-lb")
        for v in nm
    ]
    table("NEWTON-METERS TO FOOT-POUNDS & INCH-POUNDS", rows2, ("Newton-meters", "Foot-pounds", "Inch-pounds"))
    pdf.set_font("helvetica", "", 9.5)
    pdf.multi_cell(0, 5, _safe(
        "The math: ft-lb × 12 = in-lb · ft-lb × 1.35582 = Nm · Nm × 0.737562 = ft-lb · "
        "Nm × 8.85075 = in-lb. Values rounded for shop use — always follow the "
        "manufacturer's torque spec and sequence for the fastener in front of you."
    ))
    pdf.output(str(path))


BUILDERS = {
    "paycheck-overtime-calculator.xlsx": build_paycheck_calculator,
    "flat-rate-hours-tracker.xlsx": build_flat_rate_tracker,
    "vehicle-inspection-checklist.pdf": build_inspection_checklist,
    "pre-purchase-inspection-form.pdf": build_prepurchase_form,
    "diagnostic-worksheet.pdf": build_diagnostic_worksheet,
    "electrical-diagnostic-worksheet.pdf": build_electrical_worksheet,
    "customer-vehicle-intake-form.pdf": build_intake_form,
    "torque-conversion-chart.pdf": build_torque_chart,
}


def main() -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    for name, builder in BUILDERS.items():
        out = FILES_DIR / name
        builder(out)
        print(f"{name}: {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
