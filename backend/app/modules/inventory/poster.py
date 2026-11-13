"""For-sale poster PDF (wave 2, 2026-10-20): one printable page
per item — photo, name, brand/model, the asking price, and the
seller's public contact line, with a QR code.

The QR target has one honest destination: there are NO public
item pages (an item link would leak nothing but a sign-in wall),
so the code points at the SELLER'S PUBLIC PROFILE
({app_base_url}/users/{id}) — the public surface that exists,
where the visitor can message the seller. When the item also
has a live marketplace listing, the caller passes its URL and
the QR points there instead.

Built with fpdf2 in the reports module's idiom (core fonts,
cp1252-safe text, PIL-normalized photos) — the same "reports
style" the rest of the platform prints in.
"""

import io
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.modules.core import models as core_models
from app.modules.inventory import service


def _pdf_safe(text) -> str:
    """fpdf2's core fonts render through the encoding set on the
    document (render_poster sets cp1252 / WinAnsi): map
    typographic characters down and fold anything still
    unrepresentable to a stand-in instead of crashing (reports
    exports' rule). cp1252 carries the € / £ / ¥ signs the money
    formatter emits — under the old latin-1 fold an EUR seller's
    price failed the render outright: the price cell bypassed
    this fold and fpdf2 raised on the € the screen showed as
    "€300.00". Symbols with no cp1252 glyph (₹, ₩, ₪, ₺, zł)
    still fold; printing those takes an embedded Unicode font."""
    return (
        str(text or "")
        .replace("—", "-")
        .replace("–", "-")
        .replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("·", "-")
        .encode("cp1252", "replace")
        .decode("cp1252")
    )


def _photo_png(record) -> tuple[bytes, int, int] | None:
    """The item's first photo, PIL-normalized to PNG (reports
    exports' approach) — None degrades to a placeholder box."""
    for entry in record.attachments or []:
        if not isinstance(entry, dict) or entry.get("kind") != "photo":
            continue
        key = entry.get("key")
        if not key:
            continue
        try:
            from PIL import Image

            raw = storage.fetch(key)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image.thumbnail((640, 640))
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            return buffer.getvalue(), image.size[0], image.size[1]
        except Exception:
            return None
    return None


def _qr_png(url: str) -> bytes | None:
    try:
        import qrcode

        img = qrcode.make(url)
        buffer = io.BytesIO()
        # qrcode.make returns a 1-bit (mode "1") image, and fpdf2
        # mis-embeds 1-bit PNGs: every row lands shifted, so the
        # printed code smears into diagonal streaks and no scanner
        # can read it (wave-review round, 2026-10-20 — reproduced
        # locally: mode "1" garbles, RGB/L embed cleanly). Convert
        # to RGB first, the same normalization _photo_png uses.
        img.convert("RGB").save(buffer, "PNG")
        return buffer.getvalue()
    except Exception:
        return None


def render_poster(
    db: Session,
    owner: core_models.User,
    picks: list[dict],
) -> bytes:
    """picks: [{item_kind, item_id, price, listing_url?}] — the
    items must be the owner's (foreign ids are refused by the
    route via the service getters before we get here; the
    renderer re-checks and skips anything missing)."""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="Letter")
    # WinAnsi so the seller's currency signs (€/£/¥) print as
    # themselves — see _pdf_safe. Amounts stay the seller's.
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=False)

    base = (settings.app_base_url or "").rstrip("/")
    profile_url = f"{base}/users/{owner.id}" if base else ""
    seller_line = owner.name or "Toolbox Vault member"
    contact_bits = []
    if getattr(owner, "public_area_label", ""):
        contact_bits.append(owner.public_area_label)
    if getattr(owner, "show_phone", False) and getattr(owner, "contact_phone", ""):
        contact_bits.append(owner.contact_phone)

    for pick in picks:
        kind = pick["item_kind"]
        record = (
            service.get_tool(db, owner.id, pick["item_id"])
            if kind == "tool"
            else service.get_battery(db, owner.id, pick["item_id"])
        )
        if record is None:
            continue
        pdf.add_page()
        # Header band.
        pdf.set_font("helvetica", "B", 13)
        pdf.set_xy(15, 12)
        pdf.cell(0, 7, "FOR SALE", ln=1)
        pdf.set_font("helvetica", "", 9)
        pdf.set_x(15)
        pdf.cell(0, 5, "Toolbox Vault", ln=1)

        # Photo (or placeholder), left column.
        photo = _photo_png(record)
        if photo is not None:
            png, px_w, px_h = photo
            scale = min(90 / px_w, 90 / px_h)
            w, h = px_w * scale, px_h * scale
            pdf.image(io.BytesIO(png), x=15, y=30, w=w, h=h)
        else:
            pdf.set_draw_color(160, 160, 160)
            pdf.rect(15, 30, 90, 90)
            pdf.set_font("helvetica", "", 10)
            pdf.set_xy(15, 70)
            pdf.cell(90, 6, "No photo", align="C")

        # Facts, right column.
        x = 115
        pdf.set_font("helvetica", "B", 20)
        pdf.set_xy(x, 32)
        pdf.multi_cell(85, 9, _pdf_safe(record.name))
        y = pdf.get_y() + 4
        pdf.set_font("helvetica", "", 12)
        brand_model = " ".join(
            part for part in (record.brand, record.model) if part
        )
        if brand_model:
            pdf.set_xy(x, y)
            pdf.multi_cell(85, 6, _pdf_safe(brand_model))
            y = pdf.get_y() + 2
        price = pick.get("price")
        pdf.set_font("helvetica", "B", 26)
        pdf.set_xy(x, y + 4)
        from app.modules.core import money as core_money

        price_text = (
            core_money.format_money(Decimal(price), owner.currency)
            if price is not None
            else "Make offer"
        )
        pdf.cell(85, 12, _pdf_safe(price_text), ln=1)

        # Seller line + QR along the bottom.
        pdf.set_font("helvetica", "", 12)
        pdf.set_xy(15, 215)
        pdf.cell(0, 6, _pdf_safe(f"Seller: {seller_line}"), ln=1)
        if contact_bits:
            pdf.set_x(15)
            pdf.cell(0, 6, _pdf_safe(" - ".join(contact_bits)), ln=1)
        target_url = pick.get("listing_url") or profile_url
        if target_url:
            qr = _qr_png(target_url)
            if qr is not None:
                pdf.image(io.BytesIO(qr), x=160, y=225, w=35, h=35)
                pdf.set_font("helvetica", "", 8)
                pdf.set_xy(140, 262)
                pdf.cell(75, 4, "Scan to reach the seller", align="C")

    return bytes(pdf.output())
