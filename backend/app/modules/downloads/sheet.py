"""Free tool-inventory sheet generation (server-side, openpyxl).

The workbook the /downloads page hands out:

- "Start Here" cover: the REAL Toolbox Vault wordmark as an embedded
  image (assets/wordmark-transparent.png — byte-identical to the
  brand master; never the corner-plate app-icon badge, never typed
  text), how-to lines, an optional BLANK "Prepared for" layout the
  visitor fills in at home (we never ask for or prefill personal
  data), and a totals block whose values point at the My Tools
  dashboard boxes. The cover is sheet-protected with only the
  fill-in cells unlocked, so the branding and instructions stay
  put while the visitor's own lines stay writable.
- "My Tools": a dashboard BAND sits above the data — the same real
  wordmark image, a row of live totals boxes (tools / quantity /
  purchase value / replacement value, each present only when its
  column was chosen), an orange rule — then the header row carrying
  the chosen field labels VERBATIM from the inventory importer's
  tool catalog. The website importer locates that header row when
  a sheet is uploaded, so a filled sheet still imports straight
  into Toolbox Vault. Band + header stay frozen while data
  scrolls; auto-filter on the header row; one grey example row.

FIELD_CATALOG mirrors importer._COMMON_FIELDS + importer._TOOL_FIELDS
for kind="tool"; a test pins the two together so they cannot drift.
"""

import io
from pathlib import Path

from PIL import Image as PILImage
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter

_WORDMARK = Path(__file__).parent / "assets" / "wordmark-transparent.png"

# (key, label) — labels verbatim from the importer catalog, in order.
FIELD_CATALOG: list[tuple[str, str]] = [
    ("name", "Name"),
    ("brand", "Brand"),
    ("model_numbers", "Model numbers"),
    ("serial_numbers", "Serial numbers"),
    ("upc", "UPC / barcode"),
    ("category", "Category"),
    ("condition", "Condition"),
    ("location", "Location"),
    ("dealer_name", "Dealer name"),
    ("quantity", "Quantity"),
    ("purchase_price", "Purchase price (each)"),
    ("msrp", "MSRP"),
    ("replacement_cost", "Replacement cost"),
    ("purchase_date", "Purchase date"),
    ("warranty_months", "Warranty term"),
    ("warranty_provider", "Warranty provider"),
    ("warranty_contact", "Warranty contact"),
    ("warranty_terms", "Warranty terms"),
    ("tags", "Tags"),
    ("notes", "Notes / description"),
    ("size", "Size"),
    ("consumable", "Consumable"),
    ("is_set", "Is a set"),
    ("set_serials", "Set serials"),
    ("rebuy_store", "Re-buy store"),
    ("rebuy_url", "Re-buy website"),
    ("rebuy_sku", "Re-buy SKU"),
    ("rebuy_notes", "Re-buy notes"),
]

_LABELS = dict(FIELD_CATALOG)
_ORDER = {key: i for i, (key, _label) in enumerate(FIELD_CATALOG)}

_STARTER = [
    "name",
    "brand",
    "model_numbers",
    "serial_numbers",
    "category",
    "location",
    "quantity",
]
PRESETS: dict[str, list[str]] = {
    "generic": [
        "name",
        "brand",
        "model_numbers",
        "serial_numbers",
        "category",
        "condition",
        "location",
        "dealer_name",
        "quantity",
        "purchase_price",
        "replacement_cost",
        "purchase_date",
        "notes",
    ],
    "starter": list(_STARTER),
    "insurance": _STARTER
    + ["purchase_price", "replacement_cost", "purchase_date", "dealer_name", "notes"],
    "everything": [key for key, _label in FIELD_CATALOG],
}

_EXAMPLES: dict[str, object] = {
    "name": "Ratchet — example, delete this row",
    "brand": "Example brand",
    "model_numbers": "ABC-123",
    "serial_numbers": "SN123456",
    "upc": "012345678905",
    "category": "Wrenches & sockets",
    "condition": "Good",
    "location": "Top drawer",
    "dealer_name": "Tool truck",
    "quantity": 1,
    "purchase_price": 89.99,
    "msrp": 119.99,
    "replacement_cost": 119.99,
    "purchase_date": "2024-01-15",
    "size": '1/2" drive',
    "notes": "Example row — delete it and add your own tools.",
}

_WIDTHS: dict[str, int] = {
    "name": 30,
    "notes": 42,
    "model_numbers": 20,
    "serial_numbers": 20,
    "set_serials": 20,
    "quantity": 10,
    "purchase_price": 16,
    "msrp": 14,
    "replacement_cost": 17,
    "warranty_terms": 24,
    "rebuy_url": 24,
}
_MONEY_KEYS = {"purchase_price", "msrp", "replacement_cost"}

_GUNMETAL = "232328"
_ORANGE = "FF6A00"
_LIGHT_LINE = "D8D8DE"
_UNLOCKED = Protection(locked=False)

# My Tools layout (2026-10-29, owner-approved dashboard band): the
# band occupies the top rows and the labels move down to LABEL_ROW;
# the importer finds them there (see importer._header_row_index).
LOGO_BAND_ROWS = 3  # rows 1..3: gunmetal band + wordmark image
BOX_LABEL_ROW = 4  # totals box titles
BOX_VALUE_ROW = 5  # totals box live formulas
RULE_ROW = 6  # orange rule
LABEL_ROW = 7  # the verbatim importer labels
FIRST_DATA_ROW = 8  # the grey example row lives here
DATA_ROWS = 1000  # totals formulas run FIRST_DATA_ROW..+DATA_ROWS-1
LAST_DATA_ROW = FIRST_DATA_ROW + DATA_ROWS - 1


def resolve_fields(preset: str, fields: list[str] | None) -> list[str]:
    """Chosen field keys in catalog order; "name" is always included
    (the importer requires it). Raises ValueError on bad input."""
    if fields:
        chosen = {key for key in fields if key in _LABELS}
        if not chosen:
            raise ValueError("Pick at least one field.")
        chosen.add("name")
        return sorted(chosen, key=_ORDER.__getitem__)
    if preset not in PRESETS:
        raise ValueError("Unknown sheet type.")
    return list(PRESETS[preset])


def _merged_line(ws, row: int, text: str, font: Font, height: float = 18) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = font
    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = height


def _wordmark_image() -> XLImage:
    """The real wordmark as a fresh embeddable image (840px-wide
    derivative of the PNG master — the site ships the same 840px
    derivative as wordmark-840.webp — displayed at 420x62 so it
    stays crisp). Each sheet needs its own image object."""
    with PILImage.open(_WORDMARK) as master:
        derivative = master.copy()
        derivative.thumbnail((840, 840))
        buffer = io.BytesIO()
        derivative.save(buffer, format="PNG")
        buffer.seek(0)
    logo = XLImage(buffer)
    logo.width = 420
    logo.height = 62
    return logo


def _totals_boxes(
    field_keys: list[str], col_of: dict[str, str]
) -> list[tuple[str, str, str, str]]:
    """The My Tools dashboard boxes for this field set:
    (cover_key, title, formula, number_format), in display order.
    A box appears only when its column was chosen. Blank quantity
    counts as 1 for a row that names a tool — the same arithmetic
    everywhere (quantity, purchase, replacement), expressed with
    SUMPRODUCT/COUNTA so it computes identically in Excel, Sheets
    and LibreOffice."""
    first, last = FIRST_DATA_ROW, LAST_DATA_ROW
    name = col_of["name"]
    name_rng = f"{name}{first}:{name}{last}"
    qty = col_of.get("quantity")
    price = col_of.get("purchase_price")
    repl = col_of.get("replacement_cost")
    q = '"'  # formula string literal quote

    def _value_formula(money_col: str) -> str:
        money = f"{money_col}{first}:{money_col}{last}"
        if not qty:
            # No Quantity column: the money column alone is the total.
            return f"=SUM({money})"
        qty_rng = f"{qty}{first}:{qty}{last}"
        named = f"({name_rng}<>{q}{q})"
        filled = f"({qty_rng}<>{q}{q})"
        blank = f"({qty_rng}={q}{q})"
        return (
            f"=SUMPRODUCT({named}*{filled}*{qty_rng}*{money})"
            f"+SUMPRODUCT({named}*{blank}*{money})"
        )

    boxes: list[tuple[str, str, str, str]] = [
        ("tools", "TOTAL TOOLS", f"=COUNTA({name_rng})", "#,##0")
    ]
    if qty:
        qty_rng = f"{qty}{first}:{qty}{last}"
        boxes.append(
            (
                "quantity",
                "TOTAL QUANTITY",
                f"=SUMPRODUCT(({name_rng}<>{q}{q})*({qty_rng}<>{q}{q})*{qty_rng})"
                f"+COUNTA({name_rng})"
                f"-SUMPRODUCT(({name_rng}<>{q}{q})*({qty_rng}<>{q}{q}))",
                "#,##0",
            )
        )
    if price:
        boxes.append(
            ("purchase", "TOTAL PURCHASE VALUE", _value_formula(price), "#,##0.00")
        )
    if repl:
        boxes.append(
            ("replacement", "TOTAL REPLACEMENT VALUE", _value_formula(repl), "#,##0.00")
        )
    return boxes


def build_sheet(field_keys: list[str], personal_header: bool = False) -> bytes:
    wb = Workbook()
    cover = wb.active
    cover.title = "Start Here"
    tools = wb.create_sheet("My Tools")

    # ------------------------------------------------------------------
    # My Tools tab (built first so the cover totals can point at it)
    # ------------------------------------------------------------------
    ncols = len(field_keys)
    last_col = get_column_letter(ncols)
    col_of = {key: get_column_letter(i + 1) for i, key in enumerate(field_keys)}
    for col, key in enumerate(field_keys, start=1):
        tools.column_dimensions[get_column_letter(col)].width = _WIDTHS.get(key, 18)

    # Dashboard band: gunmetal strip carrying the real wordmark,
    # exactly like the cover's banner.
    band_fill = PatternFill("solid", fgColor=_GUNMETAL)
    for row in range(1, LOGO_BAND_ROWS + 1):
        tools.row_dimensions[row].height = 22
        for col in range(1, ncols + 1):
            tools.cell(row=row, column=col).fill = band_fill
    band_logo = _wordmark_image()
    band_logo.anchor = "A1"
    tools.add_image(band_logo)

    # Totals boxes: label row over value row, each box an even share
    # of the sheet's columns (the last box takes the remainder).
    boxes = _totals_boxes(field_keys, col_of)
    box_cells: dict[str, str] = {}
    spans: list[int] = []
    remaining = ncols
    for i in range(len(boxes)):
        span = max(1, remaining // (len(boxes) - i))
        spans.append(span)
        remaining -= span
    thin = Side(style="thin", color=_LIGHT_LINE)
    box_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    tools.row_dimensions[BOX_LABEL_ROW].height = 18
    tools.row_dimensions[BOX_VALUE_ROW].height = 30
    col = 1
    for (box_key, title, formula, fmt), span in zip(boxes, spans):
        end = col + span - 1
        if span > 1:
            tools.merge_cells(
                start_row=BOX_LABEL_ROW, start_column=col,
                end_row=BOX_LABEL_ROW, end_column=end,
            )
            tools.merge_cells(
                start_row=BOX_VALUE_ROW, start_column=col,
                end_row=BOX_VALUE_ROW, end_column=end,
            )
        label_cell = tools.cell(row=BOX_LABEL_ROW, column=col, value=title)
        label_cell.font = Font(bold=True, size=10, color=_ORANGE)
        label_cell.fill = band_fill
        label_cell.alignment = Alignment(horizontal="center", vertical="center")
        value_cell = tools.cell(row=BOX_VALUE_ROW, column=col, value=formula)
        value_cell.font = Font(bold=True, size=16, color=_GUNMETAL)
        value_cell.number_format = fmt
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        for r in (BOX_LABEL_ROW, BOX_VALUE_ROW):
            for c in range(col, end + 1):
                cell = tools.cell(row=r, column=c)
                cell.border = box_border
                if r == BOX_LABEL_ROW:
                    cell.fill = band_fill
        box_cells[box_key] = f"{get_column_letter(col)}{BOX_VALUE_ROW}"
        col = end + 1

    # Orange rule between the band and the data.
    for col in range(1, ncols + 1):
        tools.cell(row=RULE_ROW, column=col).fill = PatternFill(
            "solid", fgColor=_ORANGE
        )
    tools.row_dimensions[RULE_ROW].height = 5

    # Header row: the chosen labels VERBATIM from the importer
    # catalog — the website importer locates this row on upload.
    header_fill = PatternFill("solid", fgColor=_GUNMETAL)
    for col, key in enumerate(field_keys, start=1):
        cell = tools.cell(row=LABEL_ROW, column=col, value=_LABELS[key])
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    tools.row_dimensions[LABEL_ROW].height = 30

    example_font = Font(color="808080", italic=True, size=11)
    for col, key in enumerate(field_keys, start=1):
        cell = tools.cell(row=FIRST_DATA_ROW, column=col, value=_EXAMPLES.get(key))
        cell.font = example_font
        if key in _MONEY_KEYS:
            cell.number_format = "#,##0.00"

    # Band + header stay put while the data scrolls.
    tools.freeze_panes = f"A{FIRST_DATA_ROW}"
    tools.auto_filter.ref = f"A{LABEL_ROW}:{last_col}{FIRST_DATA_ROW}"
    tools.print_title_rows = f"{LABEL_ROW}:{LABEL_ROW}"
    tools.sheet_properties.pageSetUpPr.fitToPage = True
    tools.page_setup.orientation = "landscape"
    tools.page_setup.fitToWidth = 1
    tools.page_setup.fitToHeight = 0
    tools.oddHeader.center.text = "TOOLBOX VAULT — Tool Inventory"
    tools.oddHeader.center.size = 11
    tools.oddFooter.center.text = "toolboxvault.com/downloads · Page &P of &N"
    tools.oddFooter.center.size = 9

    # ------------------------------------------------------------------
    # Start Here cover
    # ------------------------------------------------------------------
    for col in range(1, 9):
        cover.column_dimensions[get_column_letter(col)].width = 16
    banner_fill = PatternFill("solid", fgColor=_GUNMETAL)
    cover.merge_cells("A1:H5")
    for row in range(1, 6):
        cover.row_dimensions[row].height = 22
        for col in range(1, 9):
            cover.cell(row=row, column=col).fill = banner_fill
    logo = _wordmark_image()
    logo.anchor = "B2"
    cover.add_image(logo)

    _merged_line(cover, 7, "toolboxvault.com/downloads", Font(bold=True, size=12, color="C2410C"))
    _merged_line(cover, 8, "Free Tool Inventory Sheet — yours to keep", Font(size=11, color="3F3F46"))
    for col in range(1, 9):
        cover.cell(row=9, column=col).fill = PatternFill("solid", fgColor=_ORANGE)
    cover.row_dimensions[9].height = 5

    _merged_line(cover, 11, "TOOL INVENTORY", Font(bold=True, size=16, color=_GUNMETAL), 24)
    _merged_line(cover, 13, "HOW TO USE THIS SHEET", Font(bold=True, size=12, color="C2410C"))
    instructions = [
        "1.  One row per tool, on the My Tools tab.",
        "2.  Keep the header row exactly as it is — those headers are what Toolbox Vault reads when you import this file.",
        "3.  Fill in what you know. Serial numbers, prices and purchase dates are what an insurance claim needs.",
        "4.  The grey row is an example — delete it before you start.",
        "For some folks, this sheet is enough. Seriously. When you want more — photos, search, claims — it's built to import straight into Toolbox Vault.",
    ]
    row = 14
    for i, line in enumerate(instructions):
        # The two long lines need the extra height or wrapped text
        # clips in stricter renderers (LibreOffice print/PDF).
        _merged_line(cover, row, line, Font(size=11, color="27272A"), 42 if i in (1, 4) else 26)
        row += 1

    unlocked_cells: list[str] = []

    if personal_header:
        row += 1
        _merged_line(cover, row, "PREPARED FOR (OPTIONAL)", Font(bold=True, size=12, color="C2410C"))
        row += 1
        bottom = Border(bottom=Side(style="thin", color=_LIGHT_LINE))
        for label in ("Name", "Address", "City, State ZIP", "Phone", "Date"):
            cover.cell(row=row, column=2, value=label).font = Font(size=11, color="3F3F46")
            cover.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
            blank = cover.cell(row=row, column=3)
            blank.protection = _UNLOCKED
            blank.border = bottom
            unlocked_cells.append(f"C{row}")
            row += 1

    row += 1
    _merged_line(cover, row, "YOUR TOTALS", Font(bold=True, size=12, color="C2410C"))
    row += 1

    # The cover totals ARE the My Tools dashboard boxes — one
    # source of truth, so the two tabs can never disagree.
    def _box_ref(box_key: str) -> str | None:
        cell = box_cells.get(box_key)
        return f"='My Tools'!{cell}" if cell else None

    totals: list[tuple[str, str | None, str | None]] = [
        ("Total quantity", _box_ref("quantity"), "#,##0"),
        ("Total purchase value", _box_ref("purchase"), "#,##0.00"),
        ("Total replacement value", _box_ref("replacement"), "#,##0.00"),
    ]
    for label, formula, fmt in totals:
        cover.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        cover.cell(row=row, column=2, value=label).font = Font(size=11, color="3F3F46")
        value_cell = cover.cell(row=row, column=5, value=formula)
        value_cell.protection = _UNLOCKED
        if fmt:
            value_cell.number_format = fmt
        unlocked_cells.append(f"E{row}")
        row += 1

    # The cover prints on one landscape page — without fit-to-page
    # the wide merged layout clips at the paper edge.
    cover.sheet_properties.pageSetUpPr.fitToPage = True
    cover.page_setup.orientation = "landscape"
    cover.page_setup.fitToWidth = 1
    cover.page_setup.fitToHeight = 1

    cover.protection.sheet = True
    cover.protection.enable()

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
