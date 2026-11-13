"""Activity reports (reports module, wave 3, 2026-10-20): the
year-end ledger and the repair-costs report.

WHY A DEDICATED KIND: the preset system renders INVENTORY ROWS
through column specs. Both of these reports are ledgers over
EVENTS in other modules' books — purchases (inventory records'
purchase facts), sales (the sold ledger), lost/stolen reports,
repair records, warranty service requests. No column spec over
inventory rows can express them, so they are their own report
kind with their own builder + renderers, riding the same
Prepared-For furniture and the owner's currency. The config
system stays coherent: presets remain what they are; activity
reports sit beside them on the Reports page.

HONEST LABELS: the year-end report is titled "Year-end
activity" and subtitled "For your records — give it to your tax
preparer." It is NOT tax advice and never claims to be a tax
document.

Money semantics (wave 3): amounts are in the OWNER's currency
and render through core's one formatter in the PDF; CSV carries
bare numbers + a currency column so spreadsheets stay honest.
"""

import csv
import io
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import docframe
from app.modules.core import models as core_models
from app.modules.core import money
from app.modules.inventory import sales as sales_service
from app.modules.inventory import service as inventory_service
from app.modules.claims import service as claims_service

YEAR_END_LABEL = "Year-end activity — for your records / give to your tax preparer"


def _money_str(value) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _purchase_cost_str(item) -> str | None:
    """An item's PURCHASE COST as a report amount: what the owner
    paid — per-unit purchase price x quantity, the claims module's
    settled money rule (owner ruling 2026-11-06: claim/report money
    is purchase cost only, never a replacement-cost basis). An item
    with no purchase price recorded contributes NO amount (None) —
    the replacement figure never silently stands in for it."""
    if item is None:
        return None
    price = getattr(item, "purchase_price", None)
    if price is None:
        return None
    return _money_str(Decimal(str(price)) * (getattr(item, "quantity", None) or 1))


def _section(key: str, label: str, rows: list[dict]) -> dict:
    total = sum(
        (Decimal(r["amount"]) for r in rows if r.get("amount") is not None),
        Decimal("0"),
    )
    rows.sort(key=lambda r: (r["date"] or "", r["item"]))
    return {
        "key": key,
        "label": label,
        "rows": rows,
        "total": _money_str(total),
        "count": len(rows),
    }


# -- the year-end ledger ------------------------------------------------------------


def _acquisition_facts(db: Session, owner_id, year: int) -> list[dict]:
    """What the owner actually acquired in `year` — one fact per
    acquisition event, shared by the year-end Acquired section
    and the tax worksheet's purchase sections.

    Source of truth is inventory's ACQUISITION LEDGER
    (models.AcquisitionRecord): what was acquired, recorded when
    it happened, so a later partial sale can never shrink it
    (the 2026-10-24 fix — this section used to read each item's
    CURRENT quantity, and a sale rewrote purchase history).
    Amounts are the ledger rows' snapshotted unit price × the
    quantity that event acquired; deleted items still appear,
    under their snapshot name.

    Items with NO ledger rows at all (rows are only written for
    priced acquisitions, and only through the inventory service)
    fall back to the item's own record — purchase_date + current
    quantity × price, the pre-ledger read. In production the
    0049 backfill + the service writers keep every priced item
    ledger-covered, so the fallback serves only rows created
    outside the service.
    """
    in_year = lambda d: d is not None and d.year == year  # noqa: E731

    facts: list[dict] = []
    ledger = inventory_service.list_acquisitions(db, owner_id)
    covered = {(row.item_kind, row.item_id) for row in ledger}
    for row in ledger:
        if row.unit_price is None or not in_year(row.acquired_on):
            continue
        qty = row.quantity_acquired or 1
        facts.append(
            {
                "date": row.acquired_on.isoformat(),
                "item": row.item_name,
                "brand": row.brand or "",
                "kind": row.item_kind,
                "qty": qty,
                "amount": _money_str(Decimal(str(row.unit_price)) * qty),
                "business_use": bool(row.business_use),
            }
        )
    for tool in inventory_service.list_tools(db, owner_id, include_attached=True):
        if ("tool", tool.id) in covered:
            continue
        if in_year(tool.purchase_date) and tool.purchase_price is not None:
            facts.append(
                {
                    "date": tool.purchase_date.isoformat(),
                    "item": tool.name,
                    "brand": tool.brand or "",
                    "kind": "tool",
                    "qty": tool.quantity or 1,
                    "amount": _money_str(
                        Decimal(str(tool.purchase_price)) * (tool.quantity or 1)
                    ),
                    "business_use": bool(tool.business_use),
                }
            )
    for battery in inventory_service.list_batteries(db, owner_id):
        if ("battery", battery.id) in covered:
            continue
        if in_year(battery.purchase_date) and battery.purchase_price is not None:
            facts.append(
                {
                    "date": battery.purchase_date.isoformat(),
                    "item": battery.name,
                    "brand": battery.brand or "",
                    "kind": "battery",
                    "qty": battery.quantity or 1,
                    "amount": _money_str(
                        Decimal(str(battery.purchase_price))
                        * (battery.quantity or 1)
                    ),
                    "business_use": bool(battery.business_use),
                }
            )
    return facts


def build_year_end(
    db: Session, owner: core_models.User, year: int
) -> dict:
    """One calendar year of asset activity, from the owning
    modules' own books (the same facts the per-item Asset
    History feed shows, gathered year-wide):

    - acquired: the acquisition ledger — what was actually
      acquired in the year (see _acquisition_facts; sales never
      shrink it);
    - sold: the sold ledger (sales add, reversals subtract);
    - lost_stolen: lost/stolen reports filed in the year, valued
      at the item's purchase cost where it's still resolvable;
    - repairs: warranty claims with a recorded repair cost,
      dated by completion (falling back to the report date);
    - warranty_repairs: warranty service requests sent in the
      year (their linked repair's cost when one was recorded).
    """
    owner_id = owner.id
    in_year = lambda d: d is not None and d.year == year  # noqa: E731

    acquired: list[dict] = [
        {
            "date": fact["date"],
            "item": fact["item"],
            "detail": (
                f"{fact['brand']} · qty {fact['qty']}".strip(" ·")
                if fact["kind"] == "tool"
                else f"{fact['brand']} · battery".strip(" ·")
            ),
            "amount": fact["amount"],
        }
        for fact in _acquisition_facts(db, owner_id, year)
    ]

    sold: list[dict] = []
    for row in sales_service.list_sales(db, owner_id, limit=100000):
        if not in_year(row.sold_on):
            continue
        amount = Decimal(str(row.sale_price))
        if row.kind == "reversal":
            amount = -amount
        sold.append(
            {
                "date": row.sold_on.isoformat(),
                "item": row.item_name,
                "detail": (
                    "Sale reversal"
                    if row.kind == "reversal"
                    else f"Sold{f' to {row.buyer_name}' if row.buyer_name else ''}"
                ),
                "amount": _money_str(amount),
            }
        )

    lost: list[dict] = []
    for report in inventory_service.list_all_loss_reports(db, owner_id):
        if not in_year(report.reported_date):
            continue
        item = None
        if report.item_kind == "tool":
            item = inventory_service.get_tool(db, owner_id, report.item_id)
        elif report.item_kind == "battery":
            item = inventory_service.get_battery(db, owner_id, report.item_id)
        name = getattr(item, "name", "") or "Item"
        lost.append(
            {
                "date": report.reported_date.isoformat(),
                "item": name,
                "detail": (
                    f"{report.standing.capitalize()} reported"
                    + (
                        f" · police #{report.police_report_number}"
                        if report.police_report_number
                        else ""
                    )
                    + (
                        f" · recovered {report.recovered_date.isoformat()}"
                        if report.recovered_date
                        else ""
                    )
                ),
                "amount": _purchase_cost_str(item),
            }
        )

    repair_views = claims_service.repair_cost_rows(db, owner_id)
    repair_cost_by_id = {
        str(r["id"]): r for r in repair_views if r.get("repair_cost") is not None
    }
    repairs: list[dict] = []
    for view in repair_views:
        if view.get("repair_cost") is None:
            continue
        when = view.get("completed_at") or view.get("reported_at")
        when_date = when.date() if isinstance(when, datetime) else when
        if not in_year(when_date):
            continue
        repairs.append(
            {
                "date": when_date.isoformat() if when_date else "",
                "item": view["item_name"],
                "detail": view.get("problem") or view.get("status") or "",
                "amount": _money_str(view["repair_cost"]),
            }
        )

    from app.modules.dealers import models as dealer_models

    warranty: list[dict] = []
    requests = db.scalars(
        select(dealer_models.WarrantyServiceRequest).where(
            dealer_models.WarrantyServiceRequest.requester_id == owner_id
        )
    ).all()
    for request in requests:
        created = request.created_at
        created_date = created.date() if isinstance(created, datetime) else created
        if not in_year(created_date):
            continue
        linked = repair_cost_by_id.get(str(request.claim_id))
        warranty.append(
            {
                "date": created_date.isoformat() if created_date else "",
                "item": request.item_name,
                "detail": (
                    f"Warranty service via {request.company_name or 'dealer'}"
                    f" · {request.status}"
                ),
                "amount": _money_str(linked["repair_cost"]) if linked else None,
            }
        )

    sections = [
        _section("acquired", "Acquired", acquired),
        _section("sold", "Sold", sold),
        _section("lost_stolen", "Lost / stolen", lost),
        _section("repairs", "Repairs", repairs),
        _section("warranty_repairs", "Warranty repairs", warranty),
    ]
    totals = [
        {"label": "Total acquired value", "amount": sections[0]["total"]},
        {"label": "Total sales", "amount": sections[1]["total"]},
        {"label": "Total repair spend", "amount": sections[3]["total"]},
    ]
    return {
        "kind": "year_end",
        "year": year,
        "title": f"Year-end activity — {year}",
        "subtitle": YEAR_END_LABEL,
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": {
            "name": owner.name or "",
            "email": owner.email or "",
            "phone": owner.phone or "",
            "address": owner.postal_address or "",
        },
        "sections": sections,
        "totals": totals,
    }


# -- repair costs ------------------------------------------------------------------------


def build_repair_costs(
    db: Session,
    owner: core_models.User,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Every repair with a recorded cost in the period (default:
    all time), with the period total — the repair-costs report."""
    rows: list[dict] = []
    for view in claims_service.repair_cost_rows(db, owner.id):
        if view.get("repair_cost") is None:
            continue
        when = view.get("completed_at") or view.get("reported_at")
        when_date = when.date() if isinstance(when, datetime) else when
        if start is not None and (when_date is None or when_date < start):
            continue
        if end is not None and (when_date is None or when_date > end):
            continue
        rows.append(
            {
                "date": when_date.isoformat() if when_date else "",
                "item": view["item_name"],
                "detail": " · ".join(
                    p
                    for p in (
                        view.get("problem") or "",
                        f"sent to {view['sent_to']}" if view.get("sent_to") else "",
                        view.get("status") or "",
                    )
                    if p
                ),
                "amount": _money_str(view["repair_cost"]),
            }
        )
    section = _section("repair_costs", "Repairs with recorded costs", rows)
    label = "Repair costs"
    if start or end:
        label += f" — {start.isoformat() if start else '…'} to {end.isoformat() if end else '…'}"
    return {
        "kind": "repair_costs",
        "title": label,
        "subtitle": "Items with repair costs in the period, from your claims.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": {
            "name": owner.name or "",
            "email": owner.email or "",
            "phone": owner.phone or "",
            "address": owner.postal_address or "",
        },
        "sections": [section],
        "totals": [{"label": "Total repair spend", "amount": section["total"]}],
    }


# -- renderers ------------------------------------------------------------------------------

# Report chrome by locale (audit A17): headers, the prepared-for
# line, the nothing-recorded line, the total suffix. Resolved
# from the OWNER's locale (preference -> country -> English).
_CHROME = {
    "en": {
        "prepared_for": "Prepared for",
        "prepared_on": "Prepared {when} for",
        "nothing": "Nothing recorded.",
        "total": "total",
        "headers": ["Section", "Date", "Item", "Detail", "Amount", "Currency"],
        "ledger_headers": ["Date", "Type", "Name", "Amount", "Balance"],
        "table_headers": ["Date", "Item", "Detail", "Amount"],
    },
    "es": {
        "prepared_for": "Preparado para",
        "prepared_on": "Preparado el {when} para",
        "nothing": "Sin registros.",
        "total": "total",
        "headers": ["Sección", "Fecha", "Artículo", "Detalle", "Importe", "Moneda"],
        "ledger_headers": ["Fecha", "Tipo", "Nombre", "Importe", "Saldo"],
        "table_headers": ["Fecha", "Artículo", "Detalle", "Importe"],
    },
}


def _chrome_for(owner) -> dict:
    from app.core.i18n import resolve_locale

    return _CHROME[resolve_locale(owner)]



def render_activity_csv(report: dict, owner=None) -> bytes:
    chrome = _chrome_for(owner) if owner is not None else _CHROME["en"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"# Toolbox Vault — {report['title']}"])
    if (report.get("subtitle") or "").strip():
        writer.writerow([f"# {report['subtitle']}"])
    prepared = report.get("prepared_for") or {}
    parts = [prepared.get("name") or "", prepared.get("email") or ""]
    if prepared.get("phone"):
        parts.append(prepared["phone"])
    writer.writerow(["# " + chrome["prepared_for"] + ": " + " · ".join(p for p in parts if p)])
    for total in report["totals"]:
        writer.writerow([f"# {total['label']}: {total['amount']} {report['currency']}"])
    writer.writerow(chrome["headers"])
    for section in report["sections"]:
        for row in section["rows"]:
            writer.writerow(
                [
                    section["label"],
                    row["date"],
                    row["item"],
                    row["detail"],
                    row["amount"] if row["amount"] is not None else "",
                    report["currency"],
                ]
            )
        writer.writerow(
            [f"{section['label']} {chrome['total']}", "", "", "", section["total"], report["currency"]]
        )
    return buffer.getvalue().encode("utf-8")


def render_activity_xlsx(report: dict, owner=None) -> bytes:
    """The activity dataset as a spreadsheet (2026-11-07): the
    CSV's data in spreadsheet dress — the same sections, rows
    and totals, with money as bare numbers so the sheet can do
    math (the inventory XLSX discipline, exports.render_xlsx).
    A spreadsheet is a data file (Report Layout Standard), so
    there is no navy frame: title / prepared-for / totals ride
    as bold furniture rows over one flat table, the skeleton
    render_activity_csv writes. ONE deliberate widening over
    the CSV: a ledger dataset keeps its BALANCE column here,
    as its PDF does — the CSV drops it, and the running balance
    is the ledger's own fifth fact. A ledger section's total
    is its closing balance, so its total row lands in the
    BALANCE column, where the PDF's total ties to the last
    row's balance."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    chrome = _chrome_for(owner) if owner is not None else _CHROME["en"]
    ledger = bool(report.get("ledger_table"))
    currency = report["currency"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    bold = Font(bold=True)

    def furniture(values: list) -> None:
        ws.append(values)
        for cell in ws[ws.max_row]:
            cell.font = bold

    furniture([f"Toolbox Vault — {report['title']}"])
    if (report.get("subtitle") or "").strip():
        ws.append([report["subtitle"]])
    prepared = report.get("prepared_for") or {}
    parts = [prepared.get("name") or "", prepared.get("email") or ""]
    if prepared.get("phone"):
        parts.append(prepared["phone"])
    furniture(
        [chrome["prepared_for"] + ": " + " · ".join(p for p in parts if p)]
    )
    for total in report["totals"]:
        furniture([f"{total['label']}: {total['amount']} {currency}"])

    if ledger:
        headers = [
            chrome["headers"][0],
            *chrome["ledger_headers"],
            chrome["headers"][5],
        ]
    else:
        headers = list(chrome["headers"])
    furniture(headers)
    ncols = len(headers)

    def money_cell(value):
        return Decimal(str(value)) if value is not None else ""

    for section in report["sections"]:
        for row in section["rows"]:
            if ledger:
                ws.append(
                    [
                        section["label"],
                        row["date"],
                        row["item"],
                        row["detail"],
                        money_cell(row["amount"]),
                        money_cell(row.get("balance")),
                        currency,
                    ]
                )
            else:
                ws.append(
                    [
                        section["label"],
                        row["date"],
                        row["item"],
                        row["detail"],
                        money_cell(row["amount"]),
                        currency,
                    ]
                )
        total_row = [""] * ncols
        total_row[0] = f"{section['label']} {chrome['total']}"
        total_row[5 if ledger else 4] = Decimal(str(section["total"]))
        total_row[ncols - 1] = currency
        furniture(total_row)

    for column_cells in ws.columns:
        width = max(len(str(c.value or "")) for c in column_cells) + 2
        ws.column_dimensions[column_cells[0].column_letter].width = min(
            max(width, 10), 42
        )
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _safe(text: str) -> str:
    """fpdf2's core fonts render through the encoding set on the
    document (render_activity_pdf sets cp1252 / WinAnsi): fold
    anything outside it to a stand-in rather than failing the
    render. cp1252 carries the € / £ / ¥ signs the money
    formatter emits — under the old latin-1 fold an EUR owner's
    amounts printed as "?300.00" while the screen showed
    "€300.00". Symbols with no cp1252 glyph (₹, ₩, ₪, ₺, zł)
    still fold; printing those takes an embedded Unicode font."""
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def render_activity_pdf(report: dict, owner: core_models.User) -> bytes:
    chrome = _chrome_for(owner)

    currency = report["currency"]
    # The shared document frame (core.docframe): the model's
    # header on page 1, its wordmark footer on every page —
    # this renderer previously had no footer at all.
    pdf = docframe.framed_pdf_class()(orientation="P", unit="mm", format="A4")
    pdf.frame_chrome = docframe.chrome_for(owner)
    pdf.frame_when = date.today()
    # WinAnsi so the owner's currency signs (€/£/¥) print as
    # themselves — see _safe. Amounts stay the owner's, always.
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(14, 14, 14)
    pdf.add_page()
    pdf.frame_header(
        report["title"],
        report.get("prepared_for") or {},
        report.get("parties"),
    )
    pdf.ln(2)
    # The subtitle is body, not frame: it carries this report's
    # own facts (the tax honesty label), so it stays as the
    # first body line, as before. A report with nothing to say
    # there (the truck statement — its summary line retired by
    # the owner's 2026-11-06 markup) prints no line at all.
    # It WRAPS (multi_cell): the single-line cell it replaces
    # cut long subtitles off mid-word — the tax worksheet's
    # second sentence never reached the printed page — the
    # same defect the tabular renderer carried, fixed in the
    # same lane (pdf-subtitle-wrap, 2026-11-07). One-line
    # subtitles render exactly as before.
    if (report.get("subtitle") or "").strip():
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(
            0, 5, _safe(report["subtitle"]),
            align="L", new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # The navy banner (report layout standard, element 4 —
    # Ryan, 2026-11-06): EVERY report carries one, full width,
    # a navy ground with white lettering — the report's own
    # headline totals read from the LEFT in regular white, and
    # a balance total (flagged "park": "right" by the dataset)
    # sits at the band's RIGHT end in bold white: position +
    # weight carry its emphasis after red-on-navy was rejected
    # as unreadable. (The datasets' "totals_band" flag is
    # history now — the banner is unconditional.)
    band_y = pdf.get_y()
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_fill_color(*docframe.NAVY)
    pdf.rect(pdf.l_margin, band_y, usable, 7.5, style="F")
    pdf.set_text_color(255, 255, 255)

    def _segment(total: dict) -> str:
        return _safe(
            f"{total['label'].upper()} "
            f"{money.format_money(Decimal(total['amount']), currency)}"
        )

    flow = [t for t in report["totals"] if t.get("park") != "right"]
    parked = [t for t in report["totals"] if t.get("park") == "right"]
    pdf.set_font("helvetica", "", 10)
    run_x = pdf.l_margin
    for i, total in enumerate(flow):
        if i:
            sep = "  ·  "
            pdf.set_xy(run_x, band_y)
            pdf.cell(pdf.get_string_width(sep), 7.5, sep)
            run_x += pdf.get_string_width(sep)
        segment = _segment(total)
        pdf.set_xy(run_x, band_y)
        pdf.cell(pdf.get_string_width(segment) + 0.5, 7.5, segment)
        run_x += pdf.get_string_width(segment)
    if parked:
        # Right-aligned in a cell ending at the band's
        # right edge: the cell's own right margin insets
        # the text inside the navy.
        pdf.set_font("helvetica", "B", 10)
        text = "  ·  ".join(_segment(t) for t in parked)
        pdf.set_xy(run_x, band_y)
        pdf.cell(usable - (run_x - pdf.l_margin), 7.5, text, align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, band_y + 7.5)
    pdf.ln(2)

    def _row_line() -> None:
        """The faint grey hairline under a body row (standard
        element 6): drawn at the cursor's current height across
        the table's width, then the pen is restored — the frame
        and the bands draw their own rules at their own weights."""
        y = pdf.get_y()
        pdf.set_draw_color(*docframe.ROW_LINE)
        pdf.set_line_width(docframe.ROW_LINE_WIDTH)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_xy(pdf.l_margin, y)

    def _total_bar(text: str) -> None:
        """The bottom navy totals bar (standard element 7): a
        SHORT bar hugging its text — "TOTAL: {amount}" in white
        bold — anchored at the right margin so the amount lands
        where the table's amount column ends. Never full width;
        the full-width band is the element-4 banner's alone."""
        pdf.set_font("helvetica", "B", 10)
        bar_w = pdf.get_string_width(text) + 8
        if pdf.get_y() + 7 > pdf.page_break_trigger:
            pdf.add_page()
        bar_y = pdf.get_y()
        bar_x = pdf.l_margin + usable - bar_w
        pdf.set_fill_color(*docframe.NAVY)
        pdf.rect(bar_x, bar_y, bar_w, 7, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(bar_x, bar_y)
        pdf.cell(bar_w - 4, 7, text, align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, bar_y + 7)

    # The truck ledger table (owner markup, 2026-11-06): the
    # section band's job becomes a real header row — DATE ·
    # TYPE · NAME · AMOUNT · BALANCE (the running balance is
    # the website ledger's own fifth column, Ryan 2026-11-06
    # 22:34) — and the NAME column WRAPS instead of truncating
    # mid-word. Column geometry over the usable 182mm: date 24,
    # type 26, name 72, amount 30 (right), balance 30 (right).
    ledger = bool(report.get("ledger_table"))
    ledger_cols = (24, 26, 72, 30, 30)

    def ledger_header() -> None:
        pdf.set_font("helvetica", "B", 9.5)
        pdf.set_fill_color(240, 240, 240)
        heads = chrome["ledger_headers"]
        x = pdf.l_margin
        for j, w in enumerate(ledger_cols):
            pdf.set_xy(x, pdf.get_y())
            pdf.cell(
                w, 6.5, _safe(heads[j]),
                fill=True,
                align="R" if j >= len(ledger_cols) - 2 else "L",
            )
            x += w
        pdf.set_xy(pdf.l_margin, pdf.get_y() + 6.5)
        _row_line()

    # The activity tables' grey banner header (standard
    # element 5): the same dress as the ledger header — light
    # grey band, bold labels, every column named — over the
    # plain table's own geometry (date 24, item 62, detail 62,
    # amount 34 right-aligned, the row cells' own widths).
    table_cols = (24, 62, 62, 34)

    def table_header() -> None:
        pdf.set_font("helvetica", "B", 9.5)
        pdf.set_fill_color(240, 240, 240)
        heads = chrome["table_headers"]
        x = pdf.l_margin
        y = pdf.get_y()
        for j, w in enumerate(table_cols):
            pdf.set_xy(x, y)
            pdf.cell(
                w, 6.5, _safe(heads[j]),
                fill=True,
                align="R" if j == len(table_cols) - 1 else "L",
            )
            x += w
        pdf.set_xy(pdf.l_margin, y + 6.5)
        _row_line()

    for section in report["sections"]:
        if report.get("section_band") is not False:
            pdf.set_font("helvetica", "B", 11)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(
                0, 7,
                _safe(f"{section['label']} ({section['count']})"),
                fill=True, new_x="LMARGIN", new_y="NEXT",
            )
        if ledger:
            ledger_header()
        elif section["rows"]:
            # A header names the columns only over rows that
            # exist; an empty section keeps its lone
            # nothing-recorded line, headerless.
            table_header()
        if not section["rows"]:
            pdf.set_font("helvetica", "", 9)
            pdf.cell(0, 5, _safe(chrome["nothing"]), new_x="LMARGIN", new_y="NEXT")
        for row in section["rows"]:
            amount = (
                money.format_money(Decimal(row["amount"]), currency)
                if row["amount"] is not None
                else "—"
            )
            if ledger:
                pdf.set_font("helvetica", "", 9)
                detail = _safe(row["detail"])
                name_lines = pdf.multi_cell(
                    ledger_cols[2], 5.5, detail, dry_run=True, output="LINES"
                )
                row_h = max(5.5, 5.5 * len(name_lines))
                if pdf.get_y() + row_h > 262:
                    pdf.add_page()
                    ledger_header()
                y0 = pdf.get_y()
                x0 = pdf.l_margin
                pdf.set_xy(x0, y0)
                pdf.cell(ledger_cols[0], 5.5, _safe(row["date"]))
                pdf.set_xy(x0 + ledger_cols[0], y0)
                pdf.cell(ledger_cols[1], 5.5, _safe(row["item"]))
                pdf.set_xy(x0 + ledger_cols[0] + ledger_cols[1], y0)
                pdf.multi_cell(ledger_cols[2], 5.5, detail)
                pdf.set_xy(
                    x0 + ledger_cols[0] + ledger_cols[1] + ledger_cols[2], y0
                )
                pdf.cell(ledger_cols[3], 5.5, _safe(amount), align="R")
                # The running BALANCE (the row's own field, put
                # there by both ledger dataset builders): the
                # balance as it stood after this entry — the
                # last row's ties to the banner's parked balance.
                balance = (
                    money.format_money(Decimal(row["balance"]), currency)
                    if row.get("balance") is not None
                    else "—"
                )
                pdf.set_xy(
                    x0
                    + ledger_cols[0]
                    + ledger_cols[1]
                    + ledger_cols[2]
                    + ledger_cols[3],
                    y0,
                )
                pdf.cell(ledger_cols[4], 5.5, _safe(balance), align="R")
                pdf.set_xy(x0, y0 + row_h)
                _row_line()
                continue
            if pdf.get_y() > 262:
                pdf.add_page()
                table_header()
            pdf.set_font("helvetica", "", 9)
            pdf.cell(24, 5.5, _safe(row["date"]))
            pdf.cell(62, 5.5, _safe(row["item"][:44]))
            pdf.cell(62, 5.5, _safe(row["detail"][:52]))
            pdf.cell(0, 5.5, _safe(amount), align="R", new_x="LMARGIN", new_y="NEXT")
            _row_line()
        # The section's closing total (standard element 7 +
        # Ryan's wording, 2026-11-06): just "TOTAL:" + the
        # amount on a SHORT navy bar — the section band above
        # already names whose total it is, and the old
        # "{label} total:" line (full-width band or plain bold
        # text) is retired on every report this renderer draws.
        _total_bar(
            _safe(
                f"{chrome['total'].upper()}: "
                f"{money.format_money(Decimal(section['total']), currency)}"
            )
        )
        pdf.ln(2)
    return bytes(pdf.output())


def render_activity(report: dict, fmt: str, owner: core_models.User) -> bytes:
    if fmt == "csv":
        return render_activity_csv(report, owner)
    if fmt == "xlsx":
        return render_activity_xlsx(report, owner)
    return render_activity_pdf(report, owner)


# -- A13/A14 dedicated kinds (audit, 2026-10-22) -----------------------------------
#
# Five more first-class kinds on the same builder/renderer
# contract (on-screen + CSV + PDF + the shared activity email):
# sales, dealer accounts (truck ledger), checked-out, lost/
# stolen, warranty claims — plus the Tax / Section 179
# worksheet. Every dataset comes through the owning module's
# own read surface (services / export_rows), never a private
# table reach, except the warranty requests — the year-end
# builder set that precedent (dealers keeps no list surface
# for a requester's own requests).


def _prepared_for(owner: core_models.User) -> dict:
    return {
        "name": owner.name or "",
        "email": owner.email or "",
        "phone": owner.phone or "",
        "address": owner.postal_address or "",
    }


def _in_period(when: date | None, start: date | None, end: date | None) -> bool:
    if start is not None and (when is None or when < start):
        return False
    if end is not None and (when is None or when > end):
        return False
    return True


def _period_label(base: str, start: date | None, end: date | None) -> str:
    if start or end:
        return (
            f"{base} — {start.isoformat() if start else '…'} "
            f"to {end.isoformat() if end else '…'}"
        )
    return base


def build_sales(
    db: Session,
    owner: core_models.User,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """The sold ledger as its own report: every sale + reversal
    in the period, net total included."""
    rows: list[dict] = []
    for row in sales_service.list_sales(db, owner.id, limit=100000):
        if not _in_period(row.sold_on, start, end):
            continue
        amount = Decimal(str(row.sale_price))
        if row.kind == "reversal":
            amount = -amount
        rows.append(
            {
                "date": row.sold_on.isoformat(),
                "item": row.item_name,
                "detail": (
                    "Sale reversal"
                    if row.kind == "reversal"
                    else f"Sold{f' to {row.buyer_name}' if row.buyer_name else ''}"
                    f" · qty {row.quantity_sold}"
                ),
                "amount": _money_str(amount),
            }
        )
    section = _section("sales", "Sales", rows)
    return {
        "kind": "sales",
        "title": _period_label("Sales", start, end),
        "subtitle": "Everything you sold in the period, from your sold ledger — reversals subtract.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": [section],
        "totals": [{"label": "Net sales", "amount": section["total"]}],
    }


def _truck_ledger_section(account: dict) -> tuple[dict, Decimal]:
    """One truck account's FULL-LEDGER section (the statement
    shape): every entry in ledger order, each row carrying its
    running balance. Returns (section, current balance). Shared
    by the dealer-accounts report (every account the owner is a
    party to) and the open-truck-accounts quick report (open
    accounts only) so the two documents can never disagree
    about what a ledger says."""
    from app.modules.truck_accounts import service as truck_service

    rows = []
    running = Decimal("0")
    for entry in account["entries"]:
        # Entry amounts are stored SIGNED in the ledger
        # (charges +, payments -, adjustments as entered) —
        # the export ships them as-is and so does this
        # report. The NAME cell is the clean name only
        # (name rule, Ryan 2026-11-06 — the item-then-note
        # composition is retired), and each row carries its
        # running balance for the ledger table's BALANCE
        # column, exactly like the single-account statement.
        running += Decimal(str(entry["amount"]))
        rows.append(
            {
                "date": entry["entry_date"],
                "item": entry["kind"].capitalize(),
                "detail": truck_service.report_entry_name(
                    entry.get("item_name"), entry.get("note")
                ),
                "amount": _money_str(entry["amount"]),
                "balance": str(running),
            }
        )
    label = (
        f"{account['dealer_name'] or 'Dealer'} — "
        f"{account['customer_name'] or 'Customer'} "
        f"(you: {account['my_role']}, {account['status']})"
    )
    # Stage 2: the statement says when an account is behind
    # — missed payments are a fact of the account, shown on
    # its statement like everywhere else they surface.
    schedule = account.get("schedule") or {}
    if schedule.get("missed_payments"):
        label += (
            f" · {schedule['missed_payments']} payment(s) missed, "
            f"{schedule['amount_past_due']} past due"
        )
    # The highest credit limit rides the section label like
    # the missed state does (truck page fixes, 2026-11-06):
    # the peak balance this account ever stood at.
    highest = Decimal(str(account.get("highest_balance") or "0"))
    if highest > 0:
        label += f" · highest credit limit {_money_str(highest)}"
    # The section dict is built by hand, not via _section:
    # rows ride in LEDGER ORDER (the export's order) so the
    # running balances read down the account the way they
    # happened — _section would re-sort within a date and
    # scramble the balances (the statement builder's rule).
    # The section total is the same sum _section computed:
    # the ledger's whole movement, which is also the last
    # row's running balance.
    section = {
        "key": f"account-{account['id']}",
        "label": label,
        "rows": rows,
        "total": _money_str(running),
        "count": len(rows),
    }
    return section, Decimal(str(account["balance"]))


def build_dealer_accounts(db: Session, owner: core_models.User) -> dict:
    """The truck-account ledger, one section per account the
    owner is a party to (either role — the export is role-shaped
    already). Charges add, payments subtract; the total line is
    the sum of current balances."""
    from app.modules.truck_accounts import service as truck_service

    sections = []
    balance_total = Decimal("0")
    for account in truck_service.export_rows(db, owner.id):
        section, balance = _truck_ledger_section(account)
        sections.append(section)
        balance_total += balance
    if not sections:
        sections = [_section("accounts", "Truck accounts", [])]
    return {
        "kind": "dealer_account",
        "title": "Dealer accounts — truck ledger",
        # The same truck-ledger presentation as the single
        # statement (owner markup, 2026-11-06): navy totals
        # band + the DATE/TYPE/NAME/AMOUNT/BALANCE ledger table
        # with a wrapping NAME column. The section bands STAY here —
        # each section is a different account and the band is
        # what names it (agent, role, credit limit ride it).
        # The one total IS a balance, so it parks at the
        # band's right end in bold white like the statement's
        # (report standard, 2026-11-06).
        "totals_band": "navy",
        "ledger_table": True,
        "subtitle": "Every charge and payment on your truck accounts. Charges add, payments subtract; section totals are the ledger movement, the line below is today's balance.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": sections,
        "totals": [
            {
                "label": "Total balance (all accounts)",
                "amount": _money_str(balance_total),
                "park": "right",
            }
        ],
    }


def build_checked_out(db: Session, owner: core_models.User) -> dict:
    """What's out right now: items I've lent and items I hold,
    valued at replacement cost where the item still resolves."""
    from app.modules.borrowing import service as borrowing_service

    lent: list[dict] = []
    held: list[dict] = []
    for view in borrowing_service.export_rows(db, owner.id):
        if view.get("state") != "checked_out":
            continue
        item = None
        if view["item_kind"] == "tool":
            item = inventory_service.get_tool(db, owner.id, view["item_id"])
        elif view["item_kind"] == "battery":
            item = inventory_service.get_battery(db, owner.id, view["item_id"])
        value = getattr(item, "replacement_cost", None)

        def _day(v) -> str:
            if v is None:
                return ""
            if isinstance(v, datetime):
                return v.date().isoformat()
            return str(v)[:10]

        due = _day(view.get("due_at"))
        out_since = _day(view.get("checked_out_at"))
        mine = view["owner_id"] == owner.id
        row = {
            "date": due or out_since,
            "item": view["item_name"],
            "detail": (
                f"{'Borrowed by' if mine else 'Held from'} "
                f"{view['borrower_name'] if mine else view['owner_name']}"
                f" · out since {out_since}"
                + (f" · due {due}" if due else " · no due date")
            ),
            "amount": _money_str(value) if value is not None else None,
        }
        (lent if mine else held).append(row)
    lent_section = _section("lent_out", "Lent out", lent)
    held_section = _section("borrowed", "Borrowed by me", held)
    return {
        "kind": "checked_out",
        "title": "Checked out — right now",
        "subtitle": "Items currently out on a lend, valued at replacement cost where it's recorded. Held items are other people's property in your hands.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": [lent_section, held_section],
        "totals": [
            {"label": "Replacement value lent out", "amount": lent_section["total"]},
            {"label": "Replacement value I hold", "amount": held_section["total"]},
        ],
    }


def build_lost_stolen(
    db: Session,
    owner: core_models.User,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Loss reports in the period: still-out and recovered in
    separate sections so the total never mixes the two. Amounts
    are PURCHASE COST (owner ruling 2026-11-06: report money is
    what the owner paid — never a replacement-cost basis)."""
    still_out: list[dict] = []
    recovered: list[dict] = []
    for report in inventory_service.list_all_loss_reports(db, owner.id):
        if not _in_period(report.reported_date, start, end):
            continue
        item = None
        if report.item_kind == "tool":
            item = inventory_service.get_tool(db, owner.id, report.item_id)
        elif report.item_kind == "battery":
            item = inventory_service.get_battery(db, owner.id, report.item_id)
        row = {
            "date": report.reported_date.isoformat() if report.reported_date else "",
            "item": getattr(item, "name", "") or "Item",
            "detail": (
                f"{report.standing.capitalize()} reported"
                + (
                    f" · police #{report.police_report_number}"
                    if report.police_report_number
                    else ""
                )
                + (
                    f" · recovered {report.recovered_date.isoformat()}"
                    if report.recovered_date
                    else ""
                )
            ),
            "amount": _purchase_cost_str(item),
        }
        (recovered if report.recovered_date else still_out).append(row)
    out_section = _section("still_out", "Still out", still_out)
    back_section = _section("recovered", "Recovered", recovered)
    return {
        "kind": "lost_stolen",
        "title": _period_label("Lost / stolen", start, end),
        "subtitle": "Your lost/stolen reports in the period, valued at purchase cost where it's recorded.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": [out_section, back_section],
        "totals": [
            {"label": "Purchase cost still out", "amount": out_section["total"]}
        ],
    }


def build_warranty_claims(
    db: Session,
    owner: core_models.User,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Warranty service requests I sent, with the linked claim's
    repair cost where one was recorded (the year-end rule)."""
    from app.modules.dealers import models as dealer_models

    repair_views = claims_service.repair_cost_rows(db, owner.id)
    repair_cost_by_id = {
        str(r["id"]): r for r in repair_views if r.get("repair_cost") is not None
    }
    rows: list[dict] = []
    requests = db.scalars(
        select(dealer_models.WarrantyServiceRequest).where(
            dealer_models.WarrantyServiceRequest.requester_id == owner.id
        )
    ).all()
    for request in requests:
        created = request.created_at
        created_date = created.date() if isinstance(created, datetime) else created
        if not _in_period(created_date, start, end):
            continue
        linked = repair_cost_by_id.get(str(request.claim_id))
        rows.append(
            {
                "date": created_date.isoformat() if created_date else "",
                "item": request.item_name,
                "detail": (
                    f"Via {request.company_name or 'dealer'} · {request.status}"
                    + (f" · {request.problem}" if request.problem else "")
                ),
                "amount": _money_str(linked["repair_cost"]) if linked else None,
            }
        )
    section = _section("warranty_claims", "Warranty service requests", rows)
    return {
        "kind": "warranty_claims",
        "title": _period_label("Warranty claims", start, end),
        "subtitle": "Warranty service requests you sent to dealers in the period. Amounts are the linked claims' repair costs, where one was recorded.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": [section],
        "totals": [{"label": "Linked repair costs", "amount": section["total"]}],
    }


TAX_LABEL = (
    "Tax / Section 179 worksheet — for your records / give to your "
    "tax preparer. This is NOT tax advice."
)


def build_tax_year(db: Session, owner: core_models.User, year: int) -> dict:
    """The accountant worksheet (audit A14): one year of
    purchases split by the business-use flag (the Section 179
    question is about business property), plus the year's
    disposals. 'Placed in service' rides the purchase date —
    the only in-service date the data carries — and the
    subtitle says exactly that.

    Purchases ride the ACQUISITION LEDGER (see
    _acquisition_facts), split by the business-use flag as it
    stood at acquisition time: the same 2026-10-24 fix as the
    year-end Acquired section — a partial sale must not shrink
    what was placed in service that year."""
    owner_id = owner.id
    in_year = lambda d: d is not None and d.year == year  # noqa: E731

    business: list[dict] = []
    other: list[dict] = []
    for fact in _acquisition_facts(db, owner_id, year):
        if fact["kind"] == "tool":
            detail = (
                f"{fact['brand']} · qty {fact['qty']} · "
                "placed in service (purchase date)"
            ).strip(" ·")
        else:
            detail = (
                f"{fact['brand']} · battery · qty {fact['qty']} · "
                "placed in service (purchase date)"
            ).strip(" ·")
        row = {
            "date": fact["date"],
            "item": fact["item"],
            "detail": detail,
            "amount": fact["amount"],
        }
        (business if fact["business_use"] else other).append(row)

    disposals: list[dict] = []
    for row in sales_service.list_sales(db, owner_id, limit=100000):
        if not in_year(row.sold_on):
            continue
        amount = Decimal(str(row.sale_price))
        if row.kind == "reversal":
            amount = -amount
        disposals.append(
            {
                "date": row.sold_on.isoformat(),
                "item": row.item_name,
                "detail": (
                    "Sale reversal"
                    if row.kind == "reversal"
                    else f"Disposed — sold{f' to {row.buyer_name}' if row.buyer_name else ''}"
                ),
                "amount": _money_str(amount),
            }
        )
    for report in inventory_service.list_all_loss_reports(db, owner_id):
        if not in_year(report.reported_date):
            continue
        item = None
        if report.item_kind == "tool":
            item = inventory_service.get_tool(db, owner_id, report.item_id)
        elif report.item_kind == "battery":
            item = inventory_service.get_battery(db, owner_id, report.item_id)
        disposals.append(
            {
                "date": report.reported_date.isoformat(),
                "item": getattr(item, "name", "") or "Item",
                "detail": f"Disposed — {report.standing} (reported)",
                # A disposal carries the item's basis — its
                # PURCHASE COST, like every lost/stolen figure
                # (owner ruling 2026-11-06).
                "amount": _purchase_cost_str(item),
            }
        )

    business_section = _section(
        "business_purchases", f"Business purchases placed in service — {year}", business
    )
    other_section = _section("other_purchases", f"Other purchases — {year}", other)
    disposal_section = _section("disposals", f"Disposals — {year}", disposals)
    return {
        "kind": "tax_year",
        "year": year,
        "title": f"Tax / Section 179 worksheet — {year}",
        "subtitle": TAX_LABEL
        + " Business-use items ride the flag on each record; placed-in-service dates are your purchase dates.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": [business_section, other_section, disposal_section],
        "totals": [
            {"label": "Business purchases", "amount": business_section["total"]},
            {"label": "Other purchases", "amount": other_section["total"]},
            {"label": "Disposals (as recorded)", "amount": disposal_section["total"]},
        ],
    }


# -- the redesign's two new kinds (Reports page, 2026-11-06) ----------------------
#
# Open repair claims and open truck accounts: the saved-report
# defaults Ryan named for the redesigned page. Both ride the
# same builder/renderer contract as every other activity kind.

# Ryan's warranty status words, in the chrome locales — the
# same labels the claim package prints and the screens carry.
_WARRANTY_STATUS_TEXT = {
    "en": {
        "not_reported": "Broken, not reported",
        "reported": "Broken, Reported",
        "waiting_on_agent": "Waiting on agent",
        "waiting_on_parts": "Waiting on replacement parts",
        "in_repair": "Tool sent in for repairs",
        "agent_has_tool": "Agent has tool",
        "completed": "Repaired",
        "backordered": "Backordered",
    },
    "es": {
        "not_reported": "Roto, no reportado",
        "reported": "Roto, reportado",
        "waiting_on_agent": "Esperando al agente",
        "waiting_on_parts": "Esperando repuestos",
        "in_repair": "Herramienta enviada a reparar",
        "agent_has_tool": "El agente tiene la herramienta",
        "completed": "Reparado",
        "backordered": "En espera de stock",
    },
}


def build_open_claims(db: Session, owner: core_models.User) -> dict:
    """Every OPEN repair claim (warranty kind, still current by
    the claims service's own rule — the same rule the Repairs &
    Maintenance page reads), grouped by ladder status. A row's
    amount is the claim's claimed value (its lines' total); a
    recorded repair cost rides the detail text instead, so the
    section totals never mix two kinds of money."""
    from app.core.i18n import resolve_locale
    from app.modules.claims import models as claim_models

    labels = _WARRANTY_STATUS_TEXT[resolve_locale(owner)]
    claims = claims_service.list_claims(
        db, owner, kind=claim_models.KIND_WARRANTY
    )
    by_status: dict[str, list[dict]] = {}
    for claim in claims:
        # The claims service's own currency rule (current = in
        # flight for its kind, not shelved) — the report never
        # re-derives it.
        if not claims_service._is_current(claim):
            continue
        view = claims_service.claim_summary(db, claim, owner.currency)
        when = view.get("reported_at") or view.get("created_at")
        when_date = when.date() if isinstance(when, datetime) else when
        detail_parts = [view.get("claim_number") or ""]
        if view.get("description"):
            detail_parts.append(view["description"])
        via = view.get("warranty_agent_name") or view.get("dealer_name")
        if via:
            detail_parts.append(f"via {via}")
        if view.get("repair_sent_to"):
            detail_parts.append(f"sent to {view['repair_sent_to']}")
        if view.get("repair_cost") is not None:
            detail_parts.append(
                f"repair cost {_money_str(view['repair_cost'])}"
            )
        row = {
            "date": when_date.isoformat() if when_date else "",
            "item": view.get("first_item_name") or view.get("claim_number") or "Claim",
            "detail": " · ".join(p for p in detail_parts if p),
            "amount": _money_str(view.get("total_amount")),
        }
        by_status.setdefault(claim.status, []).append(row)
    sections = [
        _section(
            f"status-{status}",
            labels.get(status, status.replace("_", " ")),
            by_status[status],
        )
        for status in claim_models.WARRANTY_STATUSES
        if status in by_status
    ]
    if not sections:
        sections = [_section("open_claims", "Open repair claims", [])]
    grand = sum(
        (Decimal(s["total"]) for s in sections), Decimal("0")
    )
    return {
        "kind": "open_claims",
        "title": "Open repair claims",
        "subtitle": "Every repair claim still open, grouped by where it stands. Amounts are the claimed values; a recorded repair cost is named in the detail.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": sections,
        "totals": [
            {"label": "Total claimed value", "amount": _money_str(grand)}
        ],
    }


def build_open_truck_accounts(db: Session, owner: core_models.User) -> dict:
    """Every OPEN truck account's FULL LEDGER (Ryan, 2026-11-07:
    the quick report is the ledgers, not a summary) — one
    section per open account in the settled statement shape
    (DATE · TYPE · NAME · AMOUNT · BALANCE, each account's last
    running balance tying to what is owed on it). Closed
    accounts are history and stay out; invited accounts are
    open and ride along, as they did in the summary shape this
    replaces. The sections are the dealer-accounts report's own
    ledger sections, filtered to open accounts."""
    from app.modules.truck_accounts import service as truck_service

    sections = []
    balance_total = Decimal("0")
    for account in truck_service.export_rows(db, owner.id):
        if account["status"] == "closed":
            continue
        section, balance = _truck_ledger_section(account)
        sections.append(section)
        balance_total += balance
    if not sections:
        sections = [_section("accounts", "Open truck accounts", [])]
    return {
        "kind": "open_truck_accounts",
        "title": "Open truck accounts",
        # The statement presentation, like the dealer-accounts
        # report: navy totals band + the ledger table; the
        # section bands stay — each section is a different
        # account and the band is what names it.
        "totals_band": "navy",
        "ledger_table": True,
        "subtitle": "The full ledger of every open truck account — every charge and payment, with the running balance on each account. Closed accounts aren't included.",
        "currency": money.normalize_currency(owner.currency),
        "prepared_for": _prepared_for(owner),
        "sections": sections,
        "totals": [
            {
                "label": "Total balance (all accounts)",
                "amount": _money_str(balance_total),
                "park": "right",
            }
        ],
    }


# Kind dispatch for the shared surfaces (email today; anything
# else that needs "build by name" tomorrow).
ACTIVITY_BUILDERS = {
    "year_end": lambda db, owner, year=None, start=None, end=None: build_year_end(
        db, owner, year or date.today().year
    ),
    "repair_costs": lambda db, owner, year=None, start=None, end=None: build_repair_costs(
        db, owner, start=start, end=end
    ),
    "sales": lambda db, owner, year=None, start=None, end=None: build_sales(
        db, owner, start=start, end=end
    ),
    "dealer_account": lambda db, owner, year=None, start=None, end=None: build_dealer_accounts(
        db, owner
    ),
    "checked_out": lambda db, owner, year=None, start=None, end=None: build_checked_out(
        db, owner
    ),
    "lost_stolen": lambda db, owner, year=None, start=None, end=None: build_lost_stolen(
        db, owner, start=start, end=end
    ),
    "warranty_claims": lambda db, owner, year=None, start=None, end=None: build_warranty_claims(
        db, owner, start=start, end=end
    ),
    "tax_year": lambda db, owner, year=None, start=None, end=None: build_tax_year(
        db, owner, year or date.today().year
    ),
}
