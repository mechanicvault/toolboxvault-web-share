"""PDF currency fold (2026-10-27): the document generators print
money through fpdf2 core fonts, whose text fold must run through
cp1252 (WinAnsi) — the encoding the documents set — not latin-1.

The defect (same family as the claims package fix): latin-1 has
no € glyph, so an EUR amount folded to "?300.00" in the printed
document while the screen showed "€300.00". Pins, per generator
(reports exports, reports activity, inventory poster): a document
carrying a € amount AND a £ amount renders with the real glyphs
in the extracted PDF text and never "?<amount>".

Symbols with no cp1252 glyph (₹, ₩, ₪, ₺, zł) still fold to "?" —
printing those takes an embedded Unicode font (separate decision,
deliberately not pinned here either way).
"""

import re
import uuid
import zlib
from decimal import Decimal

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.inventory import poster
from app.modules.reports import activity
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _pdf_text(pdf_bytes: bytes) -> str:
    """The document's text layer: decompress the content streams
    and read them as cp1252 (fpdf2's core-font encoding) — the
    claims-package helper, verbatim."""
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        raw = match.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        chunks.append(raw.decode("cp1252", errors="ignore"))
    return "\n".join(chunks)


def _make_user(db, account_number, email, *, currency):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Olivia Owner",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        currency=currency,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(
        owner_id=owner.id, name=name, attachments=[], **overrides
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


# -- reports exports -------------------------------------------------------------


def _exports_pdf(client, owner):
    response = client.post(
        "/api/reports/export/pdf",
        json={"columns": ["name", "price_total"]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    return response.content


def test_reports_export_pdf_prints_euro_amount(client, db):
    owner = _make_user(db, "TV-M-000901", "fold-eur@example.com", currency="EUR")
    _tool(db, owner, purchase_price=Decimal("300.00"), quantity=1)
    text = _pdf_text(_exports_pdf(client, owner))
    assert "€300.00" in text
    assert "?300.00" not in text


def test_reports_export_pdf_prints_pound_amount(client, db):
    owner = _make_user(db, "TV-M-000902", "fold-gbp@example.com", currency="GBP")
    _tool(db, owner, purchase_price=Decimal("300.00"), quantity=1)
    text = _pdf_text(_exports_pdf(client, owner))
    assert "£300.00" in text
    assert "?300.00" not in text


# -- reports activity ------------------------------------------------------------


def _activity_report(currency: str) -> dict:
    return {
        "title": "Year-End Ledger",
        "subtitle": "Jan 1, 2026 - Dec 31, 2026",
        "prepared_for": {"name": "Olivia Owner", "email": "o@example.com"},
        "currency": currency,
        "totals": [{"label": "Purchases", "amount": "300.00"}],
        "sections": [
            {
                "label": "Purchases",
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


def test_activity_pdf_prints_euro_amount(db):
    owner = _make_user(db, "TV-M-000903", "fold-act-eur@example.com", currency="EUR")
    text = _pdf_text(activity.render_activity_pdf(_activity_report("EUR"), owner))
    assert "€300.00" in text
    assert "?300.00" not in text


def test_activity_pdf_prints_pound_amount(db):
    owner = _make_user(db, "TV-M-000904", "fold-act-gbp@example.com", currency="GBP")
    text = _pdf_text(activity.render_activity_pdf(_activity_report("GBP"), owner))
    assert "£300.00" in text
    assert "?300.00" not in text


# -- inventory poster --------------------------------------------------------------


def _poster_pdf(db, owner, tool):
    return poster.render_poster(
        db,
        owner,
        [{"item_kind": "tool", "item_id": tool.id, "price": Decimal("300.00")}],
    )


def test_poster_pdf_prints_euro_price(db):
    owner = _make_user(db, "TV-M-000905", "fold-poster-eur@example.com", currency="EUR")
    tool = _tool(db, owner)
    text = _pdf_text(_poster_pdf(db, owner, tool))
    assert "€300.00" in text
    assert "?300.00" not in text


def test_poster_pdf_prints_pound_price(db):
    owner = _make_user(db, "TV-M-000906", "fold-poster-gbp@example.com", currency="GBP")
    tool = _tool(db, owner)
    text = _pdf_text(_poster_pdf(db, owner, tool))
    assert "£300.00" in text
    assert "?300.00" not in text
