"""Row 195: the wizard lookup reads a set's contents off the
product page — pieces (name / part number / own price / photo),
the stated piece count — and a piece seeded with a photo URL
gets that photo attached at save. Every value is page-supported
or it is dropped; nothing is invented."""

import json

import pytest

from app.modules.billing import ai_service, entitlements
from app.modules.catalog import grounded, lookup
from app.modules.inventory import service as inventory_service
from app.modules.inventory import schemas as inventory_schemas


@pytest.fixture()
def seeker(db):
    import uuid as _uuid

    from app.modules.core import models as core_models

    user = core_models.User(
        id=_uuid.uuid4(),
        account_number="TV-M-000712",
        email="kit-seeker@example.com",
        password_hash="not-a-real-hash",
        name="Kit Seeker",
        account_types=["mechanic"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _configure_ai(db, monkeypatch):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "KIT_TEST_AI_KEY")
    monkeypatch.setenv("KIT_TEST_AI_KEY", "test-key")
    db.commit()


def _chat_transport(payload):
    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            return {"output": []}
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return transport


_SET_PAGE = """
<html><head>
<title>13-Piece ADV Torx Bit Socket Set SABCTX13VA</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",
 "brand":"Matco Tools","model":"SABCTX13VA",
 "offers":{"price":189.95},
 "hasPart":[
   {"@type":"Product","name":"T8 Torx Bit Socket 1/4 in drive","sku":"SABCT8","offers":{"price":11.99},"image":"https://example.com/t8.jpg"},
   {"@type":"Product","name":"T10 Torx Bit Socket 1/4 in drive","sku":"SABCT10","offers":{"price":11.99}},
   {"@type":"Product","name":"T60 Torx Bit Socket 1/2 in drive","sku":"SABCT60"}]}
</script>
</head><body><h1>SABCTX13VA</h1><p>A 13 piece set.</p></body></html>
"""

_SINGLE_PAGE = """
<html><head>
<title>Stubby Ratchet</title>
<script type="application/ld+json">
{"@type":"Product","name":"Stubby Ratchet","brand":"Matco Tools","model":"AFR68"}
</script>
</head><body><h1>AFR68</h1></body></html>
"""

_TEXT_SET_PAGE = """
<html><head><title>SABCTX13VA 13-Piece ADV Torx Bit Socket Set</title></head>
<body><h1>SABCTX13VA 13-Piece ADV Torx Bit Socket Set</h1>
<p>Set includes: T8 Torx Bit Socket SABCT8 $11.99, T10 Torx Bit
Socket SABCT10, and a nylon storage rail. 13 pieces in all.</p>
</body></html>
"""


def test_structured_pieces_and_count(db):
    page = grounded.parse_page(_SET_PAGE, "https://example.com/p")
    fields, ai_used, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    assert ai_used is False
    assert fields["name"].startswith("13-Piece")
    assert kit["piece_count"] == 13
    assert len(kit["pieces"]) == 3
    first = kit["pieces"][0]
    assert first["name"].startswith("T8 Torx")
    assert first["model"] == "SABCT8"
    assert first["msrp"] == 11.99
    assert first["image_url"] == "https://example.com/t8.jpg"
    assert "msrp" not in kit["pieces"][2]


def test_single_tool_has_no_kit(db):
    page = grounded.parse_page(_SINGLE_PAGE, "https://example.com/p")
    _fields, _ai, kit, _extras = grounded.extract_fields(db, page, "Matco", "AFR68")
    assert kit["pieces"] == []
    assert kit["piece_count"] is None


def test_ai_pieces_are_validated_against_the_page(db, monkeypatch):
    _configure_ai(db, monkeypatch)
    page = grounded.parse_page(_TEXT_SET_PAGE, "https://example.com/p")
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {
                "name": "SABCTX13VA 13-Piece ADV Torx Bit Socket Set",
                "piece_count": 13,
                "pieces": [
                    {
                        "name": "T8 Torx Bit Socket",
                        "model": "SABCT8",
                        "msrp": 11.99,
                    },
                    {"name": "T10 Torx Bit Socket", "model": "SABCT10"},
                    # Not on the page at all — must be dropped.
                    {"name": "Unobtainium Wrench", "model": "ZZZ999"},
                    # On the page, but this price is not — the
                    # piece stays, the price goes.
                    {"name": "nylon storage rail", "msrp": 450.0},
                ],
            }
        ),
    )
    fields, ai_used, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    assert ai_used is True
    assert kit["piece_count"] == 13
    names = [p["name"] for p in kit["pieces"]]
    assert "T8 Torx Bit Socket" in names
    assert "T10 Torx Bit Socket" in names
    assert "Unobtainium Wrench" not in names
    rail = next(p for p in kit["pieces"] if "rail" in p["name"])
    assert "msrp" not in rail
    t8 = next(p for p in kit["pieces"] if p["name"].startswith("T8"))
    assert t8["msrp"] == 11.99


def test_ai_piece_count_must_be_supported(db, monkeypatch):
    _configure_ai(db, monkeypatch)
    page = grounded.parse_page(_TEXT_SET_PAGE, "https://example.com/p")
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport({"piece_count": 42, "pieces": []}),
    )
    _fields, _ai, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    # The page says 13 everywhere; 42 is invented — dropped, and
    # the deterministic read of the page's own words still lands.
    assert kit["piece_count"] == 13


def test_chain_carries_grounded_pieces(db, seeker, monkeypatch):
    def fake_grounded(db_, *, brand="", model="", link="", quick=False):
        return {
            "fields": {"name": "13-Piece ADV Torx Bit Socket Set"},
            "image_url": None,
            "source_name": "Matco Tools",
            "source_url": "https://example.com/sabctx13va",
            "ai_used": False,
            "pieces": [
                {"name": "T8 Torx Bit Socket", "model": "SABCT8", "msrp": 11.99}
            ],
            "piece_count": 13,
        }

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    result = lookup.run_lookup(db, seeker.id, brand="Matco", model="SABCTX13VA")
    assert result["piece_count"] == 13
    assert result["pieces"][0]["model"] == "SABCT8"


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_piece_photo_attaches_at_save(db, seeker, monkeypatch):
    monkeypatch.setattr(
        grounded,
        "fetch_photo",
        lambda url: (_PNG, "image/png", "t8.png"),
    )
    payload = inventory_schemas.ToolCreate(
        name="13-Piece ADV Torx Bit Socket Set",
        brand="Matco Tools",
        is_set=True,
        pieces=[
            inventory_schemas.SetPieceInline(
                kind="core",
                name="T8 Torx Bit Socket",
                part_number="SABCT8",
                price=11.99,
                photo_url="https://example.com/t8.jpg",
            ),
            inventory_schemas.SetPieceInline(
                kind="core", name="T10 Torx Bit Socket", part_number="SABCT10"
            ),
        ],
    )
    tool = inventory_service.create_tool(db, seeker.id, payload)
    db.commit()
    pieces = inventory_service._list_set_pieces(db, tool.id)
    by_part = {p.part_number: p for p in pieces}
    photos = [
        a for a in by_part["SABCT8"].attachments if a.get("kind") == "photo"
    ]
    assert len(photos) == 1
    assert photos[0]["content_type"] == "image/png"
    assert by_part["SABCT10"].attachments == []


def test_piece_photo_failure_never_fails_the_save(db, seeker, monkeypatch):
    def boom(url):
        raise grounded.PageFetchError("nope")

    monkeypatch.setattr(grounded, "fetch_photo", boom)
    payload = inventory_schemas.ToolCreate(
        name="13-Piece ADV Torx Bit Socket Set",
        is_set=True,
        pieces=[
            inventory_schemas.SetPieceInline(
                kind="core",
                name="T8 Torx Bit Socket",
                photo_url="https://example.com/t8.jpg",
            )
        ],
    )
    tool = inventory_service.create_tool(db, seeker.id, payload)
    db.commit()
    pieces = inventory_service._list_set_pieces(db, tool.id)
    assert len(pieces) == 1
    assert pieces[0].attachments == []


def test_single_piece_add_with_photo_url(db, seeker, monkeypatch):
    # Regression (gate chunk aa, 2026-11-19): add_set_piece dumped
    # the whole payload into the model — photo_url is not a column
    # and the constructor rejected it, breaking every single-piece
    # add (the audit-trail tests caught it).
    monkeypatch.setattr(
        grounded,
        "fetch_photo",
        lambda url: (_PNG, "image/png", "t8.png"),
    )
    tool = inventory_service.create_tool(
        db,
        seeker.id,
        inventory_schemas.ToolCreate(name="Socket set", is_set=True),
    )
    piece = inventory_service.add_set_piece(
        db,
        seeker.id,
        tool.id,
        inventory_schemas.SetPieceCreate(
            name="10mm socket", photo_url="https://example.com/10mm.jpg"
        ),
    )
    photos = [a for a in piece.attachments if a.get("kind") == "photo"]
    assert len(photos) == 1
    plain = inventory_service.add_set_piece(
        db,
        seeker.id,
        tool.id,
        inventory_schemas.SetPieceCreate(name="12mm socket"),
    )
    assert plain.attachments == []
