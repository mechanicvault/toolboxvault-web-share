"""Rows 215 + 220 — brand data feeds (Mac Tools / Shopify).

Pins:
  - the feed parses the maker's own product JSON: the variant
    RETAIL price, photos, and the REFINER/EP spec facets;
  - the internal dealer PRICE: tags are never read — no dealer
    price level can appear anywhere in a feed result;
  - a variant whose SKU isn't the part sought is rejected (a
    handle collision never borrows a stranger's facts);
  - a set's contents come from the SKU list embedded under the
    page's own "Add items from this set" heading (a list under
    any other heading is ignored), and each piece's price and
    photo come from that piece's own feed record — a piece the
    feed doesn't know stays a bare part number;
  - the chain: a complete feed answer skips the web walk, is
    labeled source "feed", is recorded into the library, and
    fences off the AI supplement (row 213); an incomplete one
    (a set whose pieces came back unpriced) still walks; with
    the operator gate off, the chain behaves exactly as before.
"""

import uuid

import pytest

from app.modules.billing import entitlements
from app.modules.catalog import feeds, grounded, library, lookup
from app.modules.core import models as core_models


@pytest.fixture()
def seeker(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000512",
        email="feedseeker@example.com",
        name="Feed Seeker",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _product_json(sku, price, title, tags="", images=1):
    return {
        "product": {
            "title": title,
            "handle": sku.lower(),
            "body_html": title,
            "tags": tags,
            "variants": [{"sku": sku, "price": str(price)}],
            "images": [
                {"src": f"https://cdn.shopify.com/{sku}-{i}.jpg"}
                for i in range(images)
            ],
        }
    }


_SET_TAGS = (
    "EP:CountryOfOrigin|US, EP:ItemNum|SMUPM96TR, EP:Weight|0.925, "
    "PRICE:EP|111.45, PRICE:NA2|298.99, PRICE:STP|229.99, "
    "REFINER:Drive Type|6-PT., REFINER:Finish|Black-Oxide, "
    "REFINER:Type|Socket"
)

_SET_HTML = """
<html><body>
<script>const skus = "DECOY1, DECOY2";</script>
<h2>Add items from this set</h2>
<script>
  const skus = "MT14Y, MUP65.5MMR, MUP66MMR, MUP69MMR"
    .split(',').map(function(s) { return s.trim(); });
</script>
</body></html>
"""


def _stub_feed(monkeypatch, *, set_html=_SET_HTML, piece_prices=None):
    """Route the feed's transports to fixtures keyed by URL."""
    piece_prices = piece_prices or {}

    def fake_json(url):
        if url.endswith("/products/smupm96tr.json"):
            return _product_json(
                "SMUPM96TR",
                "459.99",
                '1/4" Drive Universal Impact Socket',
                tags=_SET_TAGS,
            )
        for sku, price in piece_prices.items():
            handles = feeds._handle_candidates(sku)
            if any(url.endswith(f"/products/{h}.json") for h in handles):
                return _product_json(sku, price, f"{sku} SOCKET")
        return None

    def fake_text(url):
        if url.endswith("/products/smupm96tr"):
            return set_html
        return None

    monkeypatch.setattr(feeds, "_fetch_json", fake_json)
    monkeypatch.setattr(feeds, "_fetch_text", fake_text)


def _enable_feed(db):
    entitlements.set_setting(db, feeds.MAC_FEED_ENABLED_KEY, True)
    db.commit()


# -- the parse ------------------------------------------------------------------


def test_feed_parse_retail_price_specs_and_no_dealer_prices():
    result = feeds._product_fields(
        _product_json(
            "SMUPM96TR",
            "459.99",
            '1/4" Drive Universal Impact Socket',
            tags=_SET_TAGS,
        ),
        "SMUPM96TR",
    )
    assert result is not None
    fields = result["fields"]
    assert fields["msrp"] == 459.99
    assert fields["name"] == '1/4" Drive Universal Impact Socket'
    assert fields["category"] == "Socket"
    specs = result["specs"]
    assert specs["Drive Type"] == "6-PT."
    assert specs["Country of Origin"] == "US"
    # No dealer price level appears ANYWHERE in the result:
    # not as a spec, not as the price, not in any string.
    dealer_levels = {"111.45", "298.99", "229.99", "111.45"}
    assert dealer_levels.isdisjoint(
        {str(value) for value in specs.values()}
    )
    assert "PRICE" not in " ".join(specs.keys())
    assert fields["msrp"] not in (111.45, 298.99, 229.99)


def test_feed_parse_rejects_a_strangers_variant():
    payload = _product_json("OTHER99", "10.00", "Some Other Tool")
    assert feeds._product_fields(payload, "SMUPM96TR") is None


def test_set_skus_come_from_the_headed_section_only():
    skus = feeds._set_skus_from_html(_SET_HTML)
    assert skus == ["MT14Y", "MUP65.5MMR", "MUP66MMR", "MUP69MMR"]
    assert feeds._set_skus_from_html("<p>nothing here</p>") == []


def test_mac_product_pieces_priced_from_their_own_records(monkeypatch):
    _stub_feed(
        monkeypatch,
        piece_prices={
            "MT14Y": "24.99",
            "MUP65.5MMR": "21.50",
            "MUP66MMR": "19.99",
            # MUP69MMR deliberately absent: the feed doesn't
            # know it, so it stays a bare part number.
        },
    )
    result = feeds.mac_product("SMUPM96TR")
    assert result is not None
    assert result["fields"]["msrp"] == 459.99
    assert result["source_name"] == "Mac Tools"
    pieces = {piece["model"]: piece for piece in result["pieces"]}
    assert set(pieces) == {"MT14Y", "MUP65.5MMR", "MUP66MMR", "MUP69MMR"}
    # The dotted part number resolved through its dashed handle.
    assert pieces["MUP65.5MMR"]["msrp"] == 21.50
    assert pieces["MUP65.5MMR"]["image_url"]
    assert pieces["MUP69MMR"]["msrp"] is None
    assert pieces["MUP69MMR"]["name"] == ""


def test_mac_product_miss_is_none(monkeypatch):
    monkeypatch.setattr(feeds, "_fetch_json", lambda url: None)
    monkeypatch.setattr(feeds, "_fetch_text", lambda url: None)
    assert feeds.mac_product("NOPE123") is None


# -- the chain --------------------------------------------------------------------


def _walk_must_not_run(db, **kwargs):
    raise AssertionError("the web walk ran on a complete feed answer")


def test_chain_feed_answers_and_skips_the_walk(db, seeker, monkeypatch):
    _enable_feed(db)
    _stub_feed(
        monkeypatch,
        piece_prices={
            "MT14Y": "24.99",
            "MUP65.5MMR": "21.50",
            "MUP66MMR": "19.99",
            "MUP69MMR": "18.25",
        },
    )
    monkeypatch.setattr(grounded, "grounded_product", _walk_must_not_run)
    monkeypatch.setattr(grounded, "search_configured", lambda db: True)
    result = lookup.run_lookup(
        db, seeker.id, brand="Mac Tools", model="SMUPM96TR"
    )
    assert result["fields"]["msrp"]["value"] == 459.99
    assert result["fields"]["msrp"]["source"] == "feed"
    assert result["fields"]["name"]["source"] == "feed"
    assert len(result["pieces"]) == 4
    assert all(piece["msrp"] for piece in result["pieces"])
    assert result["ai_charged"] == 0
    # The feed hit landed in the library for the next lookup.
    stored = library.library_result(
        db, brand="Mac Tools", model="SMUPM96TR"
    )
    assert stored is not None
    assert stored["fields"]["msrp"] == 459.99
    assert len(stored["pieces"]) == 4


def test_chain_feed_set_with_unpriced_pieces_still_walks(
    db, seeker, monkeypatch
):
    _enable_feed(db)
    _stub_feed(monkeypatch, piece_prices={})  # no piece records at all
    walked = []

    def fake_walk(db, **kwargs):
        walked.append(True)
        return {
            "fields": {
                "name": '1/4" Drive Universal Impact Socket',
                "brand": "Mac Tools",
                "model": "SMUPM96TR",
                "category": "Sockets",
            },
            "pieces": [],
            "piece_count": 9,
            "photos": [],
            "specs": {},
            "warranty_type": None,
            "warranty_months": None,
            "warranty_terms": None,
            "source_name": "Mac Tools",
            "source_url": "https://www.mactools.com/products/smupm96tr",
            "image_url": None,
            "ai_used": False,
        }

    monkeypatch.setattr(grounded, "grounded_product", fake_walk)
    monkeypatch.setattr(grounded, "search_configured", lambda db: True)
    result = lookup.run_lookup(
        db, seeker.id, brand="Mac Tools", model="SMUPM96TR"
    )
    # The walk ran (the feed's set had no priced pieces), and
    # its stated count — a fact only the walk carries here —
    # landed; the feed's retail price still stands.
    assert walked == [True]
    assert result["piece_count"] == 9
    assert result["fields"]["msrp"]["source"] == "feed"


def test_chain_feed_gate_off_behaves_as_before(db, seeker, monkeypatch):
    # The setting is never enabled here: the feed stays dark
    # and the walk decides, exactly as before row 220.
    def boom(url):
        raise AssertionError("feed transport ran while gated off")

    monkeypatch.setattr(feeds, "_fetch_json", boom)
    monkeypatch.setattr(feeds, "_fetch_text", boom)
    monkeypatch.setattr(grounded, "grounded_product", _walk_must_not_run)
    monkeypatch.setattr(grounded, "search_configured", lambda db: False)
    result = lookup.run_lookup(
        db, seeker.id, brand="Mac Tools", model="SMUPM96TR"
    )
    assert result["fields"] == {}


def test_chain_feed_never_fires_for_other_brands(db, seeker, monkeypatch):
    _enable_feed(db)

    def boom(url):
        raise AssertionError("feed transport ran for a non-Mac brand")

    monkeypatch.setattr(feeds, "_fetch_json", boom)
    monkeypatch.setattr(feeds, "_fetch_text", boom)
    monkeypatch.setattr(grounded, "grounded_product", _walk_must_not_run)
    monkeypatch.setattr(grounded, "search_configured", lambda db: False)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco Tools", model="SABCTX13VA"
    )
    assert result["fields"] == {}
