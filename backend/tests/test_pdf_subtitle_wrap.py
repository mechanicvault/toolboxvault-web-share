"""PDF subtitle wrap (pdf-subtitle-wrap lane, 2026-11-07).

The defect: both framed report renderers (reports/tabular.py
for the admin datasets, reports/activity.py for the member
reports) drew the report's subtitle as ONE single-line fpdf
cell, so any subtitle longer than the page's text width was
cut off mid-word on the printed PDF — the Site Overview's
counting definitions, the Accounting report's cancellation
rider, the AI Usage explanations, the tax worksheet's second
sentence. CSV/XLSX always printed the sentences whole; only
the PDF amputated them.

The fix draws the subtitle with a wrapping multi_cell in both
renderers. These pins read the rendered PDF's own content
stream (the currency-fold helper's method): every drawn text
line with its position, so a wrap is proven by the lines the
document actually carries — several lines, each inside the
usable width, 5mm apart, reconstructing the whole sentence —
never by the stream merely CONTAINING the text (the old cell
wrote the full string too; it just ran off the page).

The Accounting subtitle's ORDER is pinned too: the
cancellation lane front-loaded its rider/definition solely
because of this defect; with wrapping fixed the subtitle
reads in its natural order again (preamble, definition,
rider), sentences unchanged.
"""

import re
import uuid
import zlib

from app.modules.core import models as core_models
from app.modules.reports import activity, admin_reports, tabular

MECHANIC = "mechanic_technician"
USABLE_MM = 182.0  # A4 portrait width minus the renderers' 14mm margins
LINE_PITCH_PT = 5 * 72 / 25.4  # the subtitle's 5mm line height, in points


def _make_user(db, account_number, email, *, tier="normal"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Olivia Owner",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        currency="USD",
    )
    user.tier = tier
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _drawn_lines(pdf_bytes: bytes) -> list[tuple[float, float, str]]:
    """(x, y, text) for every text line the document draws, in
    emission order: fpdf2 emits each line as its own
    `BT x y Td ... (text) Tj` block in the content stream."""
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        raw = match.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        chunks.append(raw.decode("cp1252", errors="ignore"))
    lines = []
    pattern = re.compile(
        r"BT\s+([\d.]+)\s+([\d.]+)\s+Td\s+.*?\(((?:\\.|[^\\()])*)\)\s*Tj"
    )
    for match in pattern.finditer("\n".join(chunks)):
        text = (
            match.group(3)
            .replace("\\(", "(")
            .replace("\\)", ")")
            .replace("\\\\", "\\")
        )
        lines.append((float(match.group(1)), float(match.group(2)), text))
    return lines


def _subtitle_lines(pdf_bytes: bytes, folded: str) -> list[tuple[float, float, str]]:
    """The drawn lines that make up the (folded) subtitle, in
    order: each is an exact substring of the folded text, and
    together they must rebuild it."""
    out = []
    rest = folded
    for x, y, text in _drawn_lines(pdf_bytes):
        if text and rest.startswith(text):
            out.append((x, y, text))
            rest = rest[len(text):].lstrip()
            if not rest:
                break
    return out


def _width_mm(text: str, size: float = 9.0) -> float:
    from fpdf import FPDF

    pdf = FPDF(unit="mm")
    # The documents render through cp1252 (the em dashes and
    # currency signs are legal there); measure in the same
    # encoding or fpdf2 refuses the characters outright.
    pdf.core_fonts_encoding = "cp1252"
    pdf.add_page()
    pdf.set_font("helvetica", "", size)
    return pdf.get_string_width(text)


def _assert_wraps(pdf_bytes: bytes, folded: str) -> None:
    lines = _subtitle_lines(pdf_bytes, folded)
    assert len(lines) >= 2, "subtitle still drawn as a single line"
    rebuilt = " ".join(text for _, _, text in lines)
    assert rebuilt == " ".join(folded.split())
    for x, y, text in lines:
        assert _width_mm(text) <= USABLE_MM, f"line overflows: {text!r}"
    xs = {round(x, 1) for x, _, _ in lines}
    assert len(xs) == 1, "wrapped lines must share the left edge"
    ys = [y for _, y, _ in lines]
    for upper, lower in zip(ys, ys[1:]):
        assert abs((upper - lower) - LINE_PITCH_PT) < 0.6


# -- tabular renderer (admin reports) -------------------------------------------


def test_site_overview_subtitle_wraps_in_full(db):
    owner = _make_user(db, "TV-G-000901", "wrap-god@example.com", tier="god")
    doc = admin_reports.build_site_stats(db, owner, {})
    folded = tabular._safe(doc["subtitle"])
    assert '"Agent" counts registered agents only.' in folded
    _assert_wraps(tabular.render_tabular_pdf(doc, owner), folded)


def test_short_subtitle_stays_one_line(db):
    owner = _make_user(db, "TV-G-000902", "wrap-short@example.com", tier="god")
    doc = {
        "title": "User directory",
        "subtitle": "Every member account on the site.",
        "banner": ["MEMBERS 1"],
        "sections": [
            {
                "label": "Members",
                "columns": ["Name", "Account"],
                "rows": [["Olivia Owner", "TV-G-000902"]],
                "total": "TOTAL: 1 members",
            }
        ],
    }
    pdf_bytes = tabular.render_tabular_pdf(doc, owner)
    lines = _subtitle_lines(pdf_bytes, doc["subtitle"])
    assert len(lines) == 1
    assert lines[0][2] == doc["subtitle"]


# -- activity renderer (member reports) ------------------------------------------


def _activity_report(subtitle: str) -> dict:
    return {
        "title": "Tax / Section 179 worksheet - 2026",
        "subtitle": subtitle,
        "prepared_for": {"name": "Olivia Owner", "email": "o@example.com"},
        "currency": "USD",
        "totals": [{"label": "Business purchases", "amount": "300.00"}],
        "sections": [
            {
                "label": "Business purchases",
                "count": 1,
                "rows": [
                    {
                        "date": "2026-03-04",
                        "item": "Impact wrench",
                        "detail": "Snap-on",
                        "amount": "300.00",
                    }
                ],
                "total": "300.00",
            }
        ],
    }


def test_tax_subtitle_wraps_in_full(db):
    owner = _make_user(db, "TV-M-000903", "wrap-tax@example.com")
    subtitle = (
        activity.TAX_LABEL
        + " Business-use items ride the flag on each record; "
        "placed-in-service dates are your purchase dates."
    )
    pdf_bytes = activity.render_activity_pdf(_activity_report(subtitle), owner)
    _assert_wraps(pdf_bytes, subtitle)


def test_activity_short_subtitle_stays_one_line(db):
    owner = _make_user(db, "TV-M-000904", "wrap-repairs@example.com")
    subtitle = "Items with repair costs in the period, from your claims."
    pdf_bytes = activity.render_activity_pdf(_activity_report(subtitle), owner)
    lines = _subtitle_lines(pdf_bytes, subtitle)
    assert len(lines) == 1
    assert lines[0][2] == subtitle


# -- Accounting subtitle order (the retired front-loading) ------------------------


def test_accounting_subtitle_reads_in_natural_order(db):
    owner = _make_user(db, "TV-G-000905", "wrap-acct@example.com", tier="god")
    doc = admin_reports.build_accounting(
        db, owner, {"start": "2026-11-08", "end": "2026-11-30"}
    )
    subtitle = doc["subtitle"]
    assert subtitle.index("Every payment-related figure") < subtitle.index(
        "Cancellations: a subscription reaching"
    )
    assert "cover only the recorded part" not in subtitle


def test_accounting_rider_follows_the_definition(db):
    owner = _make_user(db, "TV-G-000906", "wrap-rider@example.com", tier="god")
    doc = admin_reports.build_accounting(
        db, owner, {"start": "2026-11-01", "end": "2026-11-07"}
    )
    subtitle = doc["subtitle"]
    assert subtitle.index("Every payment-related figure") < subtitle.index(
        "Cancellations: a subscription reaching"
    )
    assert subtitle.index("Cancellations: a subscription reaching") < (
        subtitle.index("Cancellations here cover only the recorded part")
    )
