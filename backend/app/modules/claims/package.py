"""Claim package PDF (claims module, wave 3, 2026-10-20).

ONE document an owner can hand an insurer: the claim summary,
the targeted items with their snapshotted values + photos, the
evidence list, the police block, and the communications log —
rendered reports-style (fpdf2, the Prepared-For furniture the
reports module established).

Per-line toggles rule the item section: a line the owner
excluded (claim_lines.include_in_package) does NOT appear —
the package total is the included lines' total, and the
document says how many lines were left out, so a reader never
mistakes a partial package for a complete one.
"""

import io
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core import docframe
from app.core.storage import storage
from app.modules.claims import models, service
from app.modules.core import models as core_models
from app.modules.core import money


# Ryan's warranty status words (2026-11-05), as the package
# prints them — the same labels the screens carry (claims
# overhaul, 2026-11-06). A warranty claim's closed layer prints
# beside its status: closing never rewrites the status itself.
_WARRANTY_STATUS_TEXT = {
    models.STATUS_NOT_REPORTED: "Broken, not reported",
    models.STATUS_REPORTED: "Broken, Reported",
    models.STATUS_WAITING_ON_AGENT: "Waiting on agent",
    models.STATUS_WAITING_ON_PARTS: "Waiting on replacement parts",
    models.STATUS_IN_REPAIR: "Tool sent in for repairs",
    models.STATUS_AGENT_HAS_TOOL: "Agent has tool",
    models.STATUS_COMPLETED: "Repaired",
    models.STATUS_BACKORDERED: "Backordered",
}


def _status_text(claim: models.Claim) -> str:
    if claim.kind == models.KIND_WARRANTY:
        text = _WARRANTY_STATUS_TEXT.get(
            claim.status, claim.status.replace("_", " ")
        )
        if claim.closed_at is not None:
            text = f"{text} (closed)"
        return text
    return claim.status.replace("_", " ")


def _safe(text: str) -> str:
    """fpdf2's core fonts render through the encoding set on the
    document (build_package sets cp1252 / WinAnsi): fold anything
    outside it to a stand-in rather than failing the render.
    cp1252 carries the € / £ / ¥ signs the money formatter emits
    — under the old latin-1 fold an EUR owner's amounts printed
    as "?300.00" while the screen showed "€300.00". Symbols with
    no cp1252 glyph (₹, ₩, ₪, ₺, zł) still fold; printing those
    takes an embedded Unicode font."""
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def _photo_png(photo: dict | None, cache: dict) -> tuple[bytes, int, int] | None:
    """Fetch + normalize an attachment photo for embedding (the
    reports renderer's approach): PIL-decoded, thumbnailed,
    re-encoded as PNG. A missing/unreadable object degrades to
    None — the placeholder — never an error."""
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
        image.thumbnail((240, 240))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        result = (buffer.getvalue(), image.size[0], image.size[1])
    except Exception:
        result = None
    cache[key] = result
    return result


def _first_photo(record) -> dict | None:
    for item in (record.attachments or []) if record is not None else []:
        if isinstance(item, dict) and item.get("kind") == "photo":
            return item
    return None


def build_package(db: Session, owner: core_models.User, claim: models.Claim) -> bytes:
    """Render the package for one of the owner's claims."""
    currency = money.normalize_currency(owner.currency)
    lines = [r for r in service._lines(db, claim.id) if r.include_in_package]
    all_lines = service._lines(db, claim.id)
    excluded = len(all_lines) - len(lines)
    evidence = service._evidence_rows(db, claim.id)
    comms = service._comm_rows(db, claim.id)
    total = sum((r.amount or Decimal("0")) for r in lines)

    # The shared document frame (core.docframe): the model's
    # header on page 1, its wordmark footer on every page —
    # this package previously had no footer at all.
    pdf = docframe.framed_pdf_class()(orientation="P", unit="mm", format="A4")
    pdf.frame_chrome = docframe.chrome_for(owner)
    pdf.frame_when = date.today()
    # WinAnsi so the owner's currency signs (€/£/¥) print as
    # themselves — see _safe. Amounts stay the owner's, always.
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(14, 14, 14)
    cache: dict = {}

    def heading(text: str) -> None:
        pdf.set_font("helvetica", "B", 11)
        pdf.set_fill_color(228, 228, 228)
        pdf.cell(0, 7, _safe(text), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

    def row_line() -> None:
        """The faint grey hairline under a body row (report
        layout standard, element 6), the pen restored after."""
        y = pdf.get_y()
        pdf.set_draw_color(*docframe.ROW_LINE)
        pdf.set_line_width(docframe.ROW_LINE_WIDTH)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.set_xy(pdf.l_margin, y)

    def total_bar(text: str) -> None:
        """The bottom navy totals bar (standard element 7): a
        SHORT bar hugging its text — "TOTAL: {amount}" in white
        bold — anchored at the right margin. Never full width;
        the full-width band is the element-4 banner's alone."""
        pdf.set_font("helvetica", "B", 10)
        bar_w = pdf.get_string_width(text) + 8
        if pdf.get_y() + 7 > pdf.page_break_trigger:
            pdf.add_page()
        bar_y = pdf.get_y()
        usable = pdf.w - pdf.l_margin - pdf.r_margin
        bar_x = pdf.l_margin + usable - bar_w
        pdf.set_fill_color(*docframe.NAVY)
        pdf.rect(bar_x, bar_y, bar_w, 7, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(bar_x, bar_y)
        pdf.cell(bar_w - 4, 7, text, align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, bar_y + 7)

    def line_row(label: str, value: str) -> None:
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(42, 5, _safe(label))
        pdf.set_font("helvetica", "", 9)
        pdf.cell(0, 5, _safe(value), new_x="LMARGIN", new_y="NEXT")

    pdf.add_page()
    # The frame's top replaces the old brand-line header; the
    # prepared-for facts are the owner's profile, as everywhere.
    pdf.frame_header(
        f"Claim package — {claim.claim_number}",
        {
            "name": owner.name or "",
            "email": owner.email or "",
            "phone": owner.phone or "",
            "address": owner.postal_address or "",
        },
    )
    pdf.ln(2)

    # The navy banner (report layout standard, element 4 —
    # Ryan, 2026-11-06): every report carries one. The
    # package's headline facts: the claim and its standing
    # flowing from the left in regular white, the package
    # total parked at the right end in bold white — the
    # statement banner's own shape.
    band_y = pdf.get_y()
    band_usable = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_fill_color(*docframe.NAVY)
    pdf.rect(pdf.l_margin, band_y, band_usable, 7.5, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "", 10)
    flow = _safe(f"CLAIM {claim.claim_number} · {_status_text(claim).upper()}")
    pdf.set_xy(pdf.l_margin, band_y)
    pdf.cell(pdf.get_string_width(flow) + 0.5, 7.5, flow)
    pdf.set_font("helvetica", "B", 10)
    parked = _safe(
        f"PACKAGE TOTAL {money.format_money(total, currency)}"
    )
    pdf.set_xy(pdf.l_margin, band_y)
    pdf.cell(band_usable, 7.5, parked, align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, band_y + 7.5)
    pdf.ln(2)

    heading("Claim summary")
    line_row("Status", _status_text(claim))
    line_row("Insurer", claim.insurer_name or "—")
    line_row("Policy number", claim.policy_number or "—")
    if claim.agent_name:
        line_row(
            "Agent",
            " · ".join(
                p
                for p in (claim.agent_name, claim.agent_phone, claim.agent_email)
                if p
            ),
        )
    line_row("Incident", claim.incident_type.replace("_", " "))
    if claim.incident_date:
        line_row("Incident date", claim.incident_date.isoformat())
    if claim.description:
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(42, 5, "Description")
        pdf.set_font("helvetica", "", 9)
        pdf.multi_cell(0, 5, _safe(claim.description))
    # The package total is NOT a summary line any more: as a
    # label/value row its long value ran off the page's right
    # edge (the frame lane's flagged defect). It now prints
    # where the standard puts totals — the banner above, and
    # the short navy TOTAL bar closing the items below.
    pdf.ln(2)

    heading("Items claimed")
    if not lines:
        pdf.set_font("helvetica", "", 9)
        pdf.cell(
            0, 5, "No items are included in this package.",
            new_x="LMARGIN", new_y="NEXT",
        )
    for row in lines:
        if pdf.get_y() > 250:
            pdf.add_page()
        y0 = pdf.get_y()
        record = None
        try:
            record = service._resolve_target(db, owner.id, row.target_kind, row.target_id)
        except service.ClaimsError:
            record = None
        normalized = _photo_png(_first_photo(record), cache)
        if normalized is not None:
            png_bytes, px_w, px_h = normalized
            scale = min(22 / px_w, 22 / px_h)
            pdf.image(
                io.BytesIO(png_bytes), x=14, y=y0, w=px_w * scale, h=px_h * scale
            )
        pdf.set_xy(40, y0)
        pdf.set_font("helvetica", "B", 9.5)
        name = row.target_name or "(unnamed item)"
        if row.set_name and row.target_kind == "piece":
            name = f"{row.set_name} — {name}"
        pdf.cell(95, 5.5, _safe(name))
        pdf.set_font("helvetica", "", 9.5)
        amount = (
            money.format_money(row.amount, currency)
            if row.amount is not None
            else "—"
        )
        pdf.cell(0, 5.5, _safe(amount), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(40)
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(90, 90, 90)
        basis = {
            # "purchase" is the live basis (owner ruling,
            # 2026-11-06); replacement/MSRP labels remain so a
            # line priced before the ruling still prints honestly.
            "purchase": "purchase cost",
            "replacement": "replacement value",
            "msrp": "MSRP",
            "entered": "owner-entered value",
        }.get(row.value_basis, row.value_basis)
        detail = f"{row.target_kind} · {basis}"
        if row.target_kind == "set":
            detail += " · addons included" if row.include_addons else " · addons not included"
        if row.target_kind == "piece":
            # Both numbers ride the printed package too (Ryan
            # 2026-10-25): the piece's own part number, and the
            # set's model number it came from.
            if row.target_part_number:
                detail += f" · part {row.target_part_number}"
            if row.set_model_number:
                detail += f" · set model {row.set_model_number}"
        pdf.cell(0, 4.5, _safe(detail), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_y(max(y0 + 24, pdf.get_y() + 1))
        row_line()
    pdf.ln(1)
    # The items close with the standard's totals bar (element
    # 7): "TOTAL:" + the amount on a short navy bar. The count
    # line that used to ride the summary's total keeps its
    # facts as its own line under the bar — a reader still
    # learns how many lines the owner left out, so a partial
    # package never reads as a complete one.
    total_bar(_safe(f"TOTAL: {money.format_money(total, currency)}"))
    pdf.set_font("helvetica", "", 8.5)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(
        0, 4.5,
        _safe(
            f"({len(lines)} item{'s' if len(lines) != 1 else ''}"
            + (f", {excluded} excluded by the owner)" if excluded else ")")
        ),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)

    heading("Evidence")
    if not evidence:
        pdf.set_font("helvetica", "", 9)
        pdf.cell(0, 5, "No evidence attached.", new_x="LMARGIN", new_y="NEXT")
    for row in evidence:
        view = service.evidence_view(db, owner.id, row)
        pdf.set_font("helvetica", "", 9)
        state = "on file" if view["available"] else "no longer available"
        pdf.cell(
            0, 5,
            _safe(
                f"• {view['filename'] or '(unnamed)'} — {row.kind}, "
                f"{'uploaded to this claim' if row.source == 'upload' else 'from the item record'} ({state})"
            ),
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(2)

    heading("Police report")
    if claim.police_report_number or claim.police_department:
        line_row("Report number", claim.police_report_number or "—")
        line_row("Department", claim.police_department or "—")
        if claim.police_report_date:
            line_row("Report date", claim.police_report_date.isoformat())
    else:
        pdf.set_font("helvetica", "", 9)
        pdf.cell(
            0, 5, "No police report recorded for this claim.",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(2)

    heading("Communications log")
    if not comms:
        pdf.set_font("helvetica", "", 9)
        pdf.cell(0, 5, "No communications logged.", new_x="LMARGIN", new_y="NEXT")
    for entry in comms:
        pdf.set_font("helvetica", "B", 9)
        when = entry.occurred_at.strftime("%Y-%m-%d") if entry.occurred_at else ""
        pdf.cell(
            0, 5,
            _safe(f"{when} · {entry.channel} · {entry.contact or ''}"),
            new_x="LMARGIN", new_y="NEXT",
        )
        if entry.summary:
            pdf.set_font("helvetica", "", 9)
            pdf.multi_cell(0, 4.5, _safe(entry.summary))
        # Each log entry is a dated record row — the faint
        # hairline closes it like every other body row.
        pdf.ln(1.2)
        row_line()
        pdf.ln(1.2)

    return bytes(pdf.output())
