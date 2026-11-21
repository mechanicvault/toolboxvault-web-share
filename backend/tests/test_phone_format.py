"""Phone display format — the backend twin (phones-pdf lane,
2026-11-12).

The owner standard: every phone number a user READS renders
"111-222-3333". The frontend's formatPhone covers the screens;
these pins cover the server-rendered documents through the ONE
backend formatter (app.core.phones.format_phone), whose rule
mirrors the frontend's exactly:

- clean 10-digit US numbers (any punctuation) and 11-digit
  leading-1 numbers render "111-222-3333";
- anything else (7-digit locals, extensions, international,
  lettered values) returns byte-identical to stored — the
  formatter can never mangle a number it doesn't recognize;
- None/empty render "".

Document proofs read the generated PDFs' own text: the
inspection sheet's shop header and the shared document frame's
Prepared-For box (owner phone + a party phone) print a
raw-stored number formatted.
"""

import warnings
from datetime import date

import pypdfium2 as pdfium
import pytest

from app.core import docframe
from app.core.phones import format_phone
from app.modules.downloads import inspection


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        # Clean US numbers, every punctuation dress.
        ("1112223333", "111-222-3333"),
        ("(111) 222-3333", "111-222-3333"),
        ("111.222.3333", "111-222-3333"),
        ("111 222 3333", "111-222-3333"),
        ("111-222-3333", "111-222-3333"),
        (" 1112223333 ", "111-222-3333"),
        # Country-code dress: the leading 1 drops.
        ("+1 111 222 3333", "111-222-3333"),
        ("1-111-222-3333", "111-222-3333"),
        ("+11112223333", "111-222-3333"),
        # Never mangle: passthrough, byte-identical.
        ("5550142", "5550142"),  # 7-digit local
        ("555-0142", "555-0142"),
        ("+44 20 7946 0958", "+44 20 7946 0958"),  # international
        ("01112223333", "01112223333"),  # 11 digits, no leading 1
        ("111-222-3333 ext 5", "111-222-3333 ext 5"),  # letters
        ("call 1112223333", "call 1112223333"),
        ("+", "+"),
        # Absent values render empty.
        ("", ""),
        (None, ""),
    ],
)
def test_format_phone_rule(stored, expected):
    assert format_phone(stored) == expected


def _pdf_text(content: bytes) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = pdfium.PdfDocument(content)
        return "\n".join(
            page.get_textpage().get_text_range() for page in doc
        )


def test_inspection_pdf_prints_shop_phone_formatted():
    content = inspection.build_inspection_pdf(
        selected=set(),
        shop_name="Format Test Shop",
        shop_phone="1112223333",
    )
    text = _pdf_text(content)
    assert "111-222-3333" in text
    assert "1112223333" not in text


def _framed_header_pdf(prepared_for, parties=None) -> bytes:
    cls = docframe.framed_pdf_class()
    pdf = cls(orientation="P", unit="mm", format="Letter")
    pdf.frame_chrome = docframe.CHROME["en"]
    pdf.frame_when = date.today()
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.frame_header("Format test document", prepared_for, parties)
    return bytes(pdf.output())


def test_frame_header_prints_prepared_for_phone_formatted():
    content = _framed_header_pdf(
        {"name": "Olivia Owner", "phone": "(111) 222-3333"}
    )
    text = _pdf_text(content)
    assert "111-222-3333" in text
    assert "(111) 222-3333" not in text


def test_frame_header_prints_party_phone_formatted():
    content = _framed_header_pdf(
        {"name": "Olivia Owner"},
        parties={"dealer": {"name": "Dealer Co", "phone": "1112223333"}},
    )
    text = _pdf_text(content)
    assert "111-222-3333" in text
    assert "1112223333" not in text


def test_frame_header_leaves_unrecognized_phone_untouched():
    content = _framed_header_pdf(
        {"name": "Olivia Owner", "phone": "+44 20 7946 0958"}
    )
    assert "+44 20 7946 0958" in _pdf_text(content)
