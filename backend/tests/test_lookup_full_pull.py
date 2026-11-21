"""Row 199: the lookup pulls absolutely everything the source
pages state that the system has a field for — the barcode, the
whole photo gallery, the specification pairs, the stated
warranty — and the search walk keeps reading further pages to
fill the first page's gaps. Every value is page-supported or
it is dropped; nothing is invented."""

import json

import pytest

from app.modules.billing import ai_service, entitlements
from app.modules.catalog import grounded, lookup


@pytest.fixture()
def seeker(db):
    import uuid as _uuid

    from app.modules.core import models as core_models

    user = core_models.User(
        id=_uuid.uuid4(),
        account_number="TV-M-000713",
        email="full-pull@example.com",
        password_hash="not-a-real-hash",
        name="Full Pull",
        account_types=["mechanic"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _configure_ai(db, monkeypatch):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "PULL_TEST_AI_KEY")
    monkeypatch.setenv("PULL_TEST_AI_KEY", "test-key")
    db.commit()


def _chat_transport(payload):
    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            return {"output": []}
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return transport


_FULL_PAGE = """
<html><head>
<title>13-Piece ADV Torx Bit Socket Set SABCTX13VA</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",
 "brand":"Matco Tools","model":"SABCTX13VA","gtin13":"0123456789058",
 "offers":{"price":169.95},
 "image":["https://example.com/main.jpg","https://example.com/rail.jpg",
          "https://example.com/case.jpg"],
 "additionalProperty":[
   {"@type":"PropertyValue","name":"Drive Size","value":"1/2 in"},
   {"@type":"PropertyValue","name":"Weight","value":"0.3 lbs"},
   {"@type":"PropertyValue","name":"Finish","value":"Chrome"}]}
</script>
</head><body><h1>SABCTX13VA</h1><p>A 13 piece set.</p></body></html>
"""


def test_structured_full_pull(db):
    page = grounded.parse_page(_FULL_PAGE, "https://example.com/p")
    fields, ai_used, _kit, extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    assert fields["upc"] == "0123456789058"
    assert extras["specs"] == {
        "Drive Size": "1/2 in",
        "Weight": "0.3 lbs",
        "Finish": "Chrome",
    }
    # The whole gallery rides the parsed page, headline first.
    assert page["images"] == [
        "https://example.com/main.jpg",
        "https://example.com/rail.jpg",
        "https://example.com/case.jpg",
    ]
    result = grounded._result(page, fields, ai_used, _kit, extras)
    assert result["photos"] == page["images"]
    assert result["specs"]["Weight"] == "0.3 lbs"


def test_warranty_term_from_description(db):
    html = """
    <html><head><title>Heavy Duty Ratchet AFR68</title>
    <script type="application/ld+json">
    {"@type":"Product","name":"Heavy Duty Ratchet","brand":"Matco Tools",
     "model":"AFR68",
     "description":"A heavy duty ratchet for daily shop use, backed by a 2 year warranty against defects in materials and workmanship."}
    </script></head><body><h1>AFR68</h1></body></html>
    """
    page = grounded.parse_page(html, "https://example.com/p")
    _fields, _ai, _kit, extras = grounded.extract_fields(db, page, "Matco", "AFR68")
    assert extras["warranty_type"] == "term"
    assert extras["warranty_months"] == 24
    assert "warranty" in extras["warranty_terms"].lower()


_AI_PAGE = """
<html><head><title>SABCTX13VA 13-Piece ADV Torx Bit Socket Set</title></head>
<body><h1>SABCTX13VA 13-Piece ADV Torx Bit Socket Set</h1>
<p>Includes sizes T8 through T60 on a nylon rail. Specifications:
Drive Size 1/2 in, Finish Chrome, Weight 0.3 lbs. LIFETIME
WARRANTY. Sockets are guaranteed for a lifetime of use.</p>
</body></html>
"""


def test_ai_specs_and_lifetime_warranty(db, monkeypatch):
    _configure_ai(db, monkeypatch)
    payload = {
        "name": "13-Piece ADV Torx Bit Socket Set",
        "specs": {
            "Drive Size": "1/2 in",
            "Finish": "Chrome",
            "Teleportation": "Instant",
        },
        "warranty": "Lifetime warranty",
    }
    monkeypatch.setattr(ai_service, "_transport", _chat_transport(payload))
    page = grounded.parse_page(_AI_PAGE, "https://example.com/p")
    _fields, ai_used, _kit, extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    assert ai_used is True
    # The invented spec (name and value nowhere on the page) is
    # dropped; the stated ones survive.
    assert extras["specs"] == {"Drive Size": "1/2 in", "Finish": "Chrome"}
    assert extras["warranty_type"] == "lifetime"
    assert "warranty_months" not in extras


_ANCHOR_PAGE = """
<html><head><title>13-Piece ADV Torx Bit Socket Set</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",
 "brand":"Matco Tools","model":"SABCTX13VA","offers":{"price":169.95}}
</script></head><body><h1>SABCTX13VA</h1></body></html>
"""

_CONTENTS_PAGE = """
<html><head><title>SABCTX13VA set at Tool Barn</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",
 "brand":"Matco Tools","model":"SABCTX13VA","gtin13":"0123456789058",
 "additionalProperty":[
   {"@type":"PropertyValue","name":"Drive Size","value":"1/2 in"}],
 "hasPart":[
   {"@type":"Product","name":"T8 Torx Bit Socket","sku":"SABCT8","offers":{"price":11.99},"image":"https://example.com/t8.jpg"},
   {"@type":"Product","name":"T60 Torx Bit Socket","sku":"SABCT60","offers":{"price":16.99}}]}
</script></head><body><h1>SABCTX13VA</h1></body></html>
"""

_VARIANT_PAGE = """
<html><head><title>SABCTX13VAK kit</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set with Case",
 "brand":"Matco Tools","model":"SABCTX13VAK","offers":{"price":219.95},
 "hasPart":[
   {"@type":"Product","name":"Variant Piece","sku":"VAR1","offers":{"price":9.99}}]}
</script></head><body><h1>SABCTX13VAK</h1></body></html>
"""

_PAWN_PAGE = """
<html><head><title>SABCTX13VA set at Pawn Barn</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",
 "brand":"Matco Tools","model":"SABCTX13VA","offers":{"price":59.99},
 "additionalProperty":[
   {"@type":"PropertyValue","name":"Drive Size","value":"1/2 in"}],
 "hasPart":[
   {"@type":"Product","name":"T8 Torx Bit Socket"},
   {"@type":"Product","name":"T10 Torx Bit Socket"},
   {"@type":"Product","name":"T60 Torx Bit Socket"}]}
</script></head><body><h1>SABCTX13VA</h1></body></html>
"""

_PAGES = {
    "https://maker.example.com/set": _ANCHOR_PAGE,
    "https://barn.example.com/set": _CONTENTS_PAGE,
    "https://maker.example.com/kit": _VARIANT_PAGE,
    "https://pawn.example.com/set": _PAWN_PAGE,
}


def _stub_walk(monkeypatch, urls):
    monkeypatch.setattr(grounded, "search_configured", lambda db: True)
    monkeypatch.setattr(
        grounded,
        "search_pages",
        lambda db, query, count=5, model="": [{"url": u} for u in urls],
    )
    monkeypatch.setattr(
        grounded,
        "fetch_product_page",
        lambda url, allow_render=True: grounded.parse_page(_PAGES[url], url),
    )


_OTHER_PAGE = """
<html><head><title>Generic Wrench Set GW100</title>
<script type="application/ld+json">
{"@type":"Product","name":"Generic Wrench Set","brand":"Other",
 "model":"GW100","offers":{"price":39.95}}
</script></head><body><h1>GW100</h1></body></html>
"""


def test_walk_answers_inside_its_time_budget(db, monkeypatch):
    # Row 214: with the time budget already spent, the walk
    # fetches nothing and answers with what it holds (here:
    # nothing) instead of running past the edge timeout the
    # way the live SX126TR full import did, twice.
    _stub_walk(monkeypatch, ["https://maker.example.com/set"])
    monkeypatch.setattr(grounded, "_WALK_BUDGET_SECONDS", -1.0)
    result = grounded.grounded_product(db, brand="Matco", model="SABCTX13VA")
    assert result is None


def test_clean_miss_hunts_with_fallback_queries(db, monkeypatch):
    # Row 214: the first search surfaces only a page about a
    # different product (the live SABCTX13VA search-miss
    # shape) — the walk must ask the search differently and
    # walk what comes back before answering a miss.
    pages = dict(_PAGES)
    pages["https://other.example.com/wrench"] = _OTHER_PAGE
    queries: list[str] = []

    def search(db_, query, count=5, model=""):
        queries.append(query)
        if query == "Matco SABCTX13VA":
            return [{"url": "https://other.example.com/wrench"}]
        return [{"url": "https://maker.example.com/set"}]

    monkeypatch.setattr(grounded, "search_configured", lambda db: True)
    monkeypatch.setattr(grounded, "search_pages", search)
    monkeypatch.setattr(
        grounded,
        "fetch_product_page",
        lambda url, allow_render=True: grounded.parse_page(pages[url], url),
    )
    result = grounded.grounded_product(db, brand="Matco", model="SABCTX13VA")
    assert result is not None
    assert result["source_url"] == "https://maker.example.com/set"
    assert result["fields"]["msrp"] == 169.95
    # The primary query went first; a differently-worded
    # fallback followed it.
    assert queries[0] == "Matco SABCTX13VA"
    assert len(queries) >= 2


def test_merge_walk_fills_anchor_gaps(db, monkeypatch):
    _stub_walk(
        monkeypatch,
        ["https://maker.example.com/set", "https://barn.example.com/set"],
    )
    result = grounded.grounded_product(db, brand="Matco", model="SABCTX13VA")
    assert result is not None
    # Identity + price from the anchor (first exact page).
    assert result["fields"]["name"].startswith("13-Piece")
    assert result["fields"]["msrp"] == 169.95
    assert result["source_url"] == "https://maker.example.com/set"
    # Gaps filled from the second page: contents, specs, barcode.
    assert [p["model"] for p in result["pieces"]] == ["SABCT8", "SABCT60"]
    assert result["pieces"][0]["image_url"] == "https://example.com/t8.jpg"
    assert result["specs"] == {"Drive Size": "1/2 in"}
    assert result["fields"]["upc"] == "0123456789058"


def test_priced_pieces_enrich_a_names_only_anchor(db, monkeypatch):
    # The live failure of 2026-11-20: a resale listing named
    # the set's pieces but priced none of them, and the walk
    # settled for the names. The maker's page further down
    # the queue prices two of the three — those part numbers,
    # prices and photos must fold into the listed pieces, and
    # the piece the maker never priced stays listed, honestly
    # bare, instead of the whole list being swapped or stalled.
    _stub_walk(
        monkeypatch,
        ["https://pawn.example.com/set", "https://barn.example.com/set"],
    )
    result = grounded.grounded_product(db, brand="Matco", model="SABCTX13VA")
    assert result is not None
    # The listing page anchors: identity and source stay its own.
    assert result["source_url"] == "https://pawn.example.com/set"
    pieces = result["pieces"]
    assert [p["name"] for p in pieces] == [
        "T8 Torx Bit Socket",
        "T10 Torx Bit Socket",
        "T60 Torx Bit Socket",
    ]
    by_name = {p["name"]: p for p in pieces}
    assert by_name["T8 Torx Bit Socket"]["model"] == "SABCT8"
    assert by_name["T8 Torx Bit Socket"]["msrp"] == 11.99
    assert by_name["T8 Torx Bit Socket"]["image_url"] == "https://example.com/t8.jpg"
    assert by_name["T60 Torx Bit Socket"]["model"] == "SABCT60"
    assert by_name["T60 Torx Bit Socket"]["msrp"] == 16.99
    assert "model" not in by_name["T10 Torx Bit Socket"]


def test_result_complete_requires_priced_pieces():
    fields = {key: "x" for key in grounded._FIELDS}
    fields["name"] = "13-Piece ADV Torx Bit Socket Set"
    result = {
        "fields": fields,
        "specs": {"Drive Size": "1/2 in"},
        "pieces": [{"name": "T8 Torx Bit Socket"}],
    }
    # A set whose contents are bare names is not complete:
    # the walk keeps hunting for the priced pieces.
    assert grounded._result_complete(result) is False
    result["pieces"] = [
        {"name": "T8 Torx Bit Socket", "model": "SABCT8", "msrp": 11.99}
    ]
    assert grounded._result_complete(result) is True


def test_merge_enriches_names_only_pieces():
    primary = {
        "fields": {},
        "pieces": [{"name": "T8 Torx Bit Socket"}, {"name": "T10 Torx Bit Socket"}],
        "specs": {},
        "photos": [],
        "ai_used": False,
    }
    other = {
        "fields": {},
        "pieces": [
            {
                "name": "T8 Torx Bit Socket",
                "model": "SABCT8",
                "msrp": 11.99,
                "image_url": "https://example.com/t8.jpg",
            }
        ],
        "specs": {},
        "photos": [],
        "ai_used": False,
    }
    grounded._merge_into(primary, other, "SABCTX13VA")
    assert primary["pieces"][0]["model"] == "SABCT8"
    assert primary["pieces"][0]["msrp"] == 11.99
    assert primary["pieces"][0]["image_url"] == "https://example.com/t8.jpg"
    assert primary["pieces"][1] == {"name": "T10 Torx Bit Socket"}


def test_variant_never_fills_anchor_gaps(db, monkeypatch):
    _stub_walk(
        monkeypatch,
        ["https://maker.example.com/set", "https://maker.example.com/kit"],
    )
    result = grounded.grounded_product(db, brand="Matco", model="SABCTX13VA")
    assert result is not None
    assert result["fields"]["model"] == "SABCTX13VA"
    # The variant kit's contents describe the variant — they
    # never leak into the exact model's answer.
    assert result["pieces"] == []


def test_chain_carries_full_pull(db, seeker, monkeypatch):
    def fake_grounded(db_, *, brand="", model="", link="", quick=False):
        return {
            "fields": {"name": "13-Piece ADV Torx Bit Socket Set"},
            "image_url": "https://example.com/main.jpg",
            "source_name": "Matco Tools",
            "source_url": "https://example.com/sabctx13va",
            "ai_used": False,
            "pieces": [],
            "piece_count": 13,
            "photos": ["https://example.com/main.jpg", "https://example.com/rail.jpg"],
            "specs": {"Drive Size": "1/2 in"},
            "warranty_type": "lifetime",
            "warranty_months": None,
            "warranty_terms": "Lifetime warranty",
        }

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    result = lookup.run_lookup(db, seeker.id, brand="Matco", model="SABCTX13VA")
    assert result["photos"] == [
        "https://example.com/main.jpg",
        "https://example.com/rail.jpg",
    ]
    assert result["specs"] == {"Drive Size": "1/2 in"}
    assert result["warranty_type"] == "lifetime"
    assert result["warranty_terms"] == "Lifetime warranty"
