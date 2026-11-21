"""Rebuild Phase 1 — the evidence layer.

Pins:
  - scrubbing blanks credential-named fields and cuts
    internal PRICE: tags before anything is stored or read;
  - the recorder keeps only JSON responses, summarizes the
    arrays inside them, and reads one back at a path;
  - the page map segments a page by generic signals only:
    a Set Details section and a Similar Products rail are
    found with their card counts, the stated piece count is
    read, and embedded structured product data is listed;
  - evidence persists keyed by brand + part number and reads
    back in order.
"""

import json

from app.modules.catalog import evidence


def test_scrub_blanks_credentials_and_price_tags():
    dirty = {
        "access_token": "abc123",
        "user": {"email": "a@b.c", "name": "Tech"},
        "cart_id": "42",
        "title": "Socket Set PRICE: 3 pricing",
        "items": [{"session": "s", "sku": "BUP10M6V", "price": 31.95}],
        "price": 499.95,
    }
    clean = evidence.scrub(dirty)
    assert clean["access_token"] == "[scrubbed]"
    assert clean["user"]["email"] == "[scrubbed]"
    assert clean["user"]["name"] == "Tech"
    assert clean["cart_id"] == "[scrubbed]"
    assert "PRICE:" not in clean["title"]
    assert clean["items"][0]["session"] == "[scrubbed]"
    assert clean["items"][0]["sku"] == "BUP10M6V"
    assert clean["price"] == 499.95


def test_recorder_summarizes_and_reads_back():
    recorder = evidence.ResponseRecorder()
    payload = {
        "payLoad": {
            "products": [
                {"sku": f"BUP{i}M6V", "price": 30.0 + i} for i in range(12)
            ]
        },
        "session_token": "should-not-survive",
    }
    recorder.offer(
        "https://example.com/arc/getProductsData",
        200,
        "application/json; charset=utf-8",
        json.dumps(payload),
    )
    recorder.offer(
        "https://example.com/page", 200, "text/html", "<html>nope</html>"
    )
    assert len(recorder.recordings) == 1
    (summary,) = recorder.summaries()
    assert summary["arrays"][0]["path"] == "$.payLoad.products"
    assert summary["arrays"][0]["count"] == 12
    assert "sku" in summary["arrays"][0]["keys"]
    items = recorder.data_at(
        "https://example.com/arc/getProductsData", "$.payLoad.products"
    )
    assert len(items) == 12
    assert items[0]["sku"] == "BUP0M6V"
    stored = recorder.recordings[0]["data"]
    assert stored["session_token"] == "[scrubbed]"


_PAGE = """
<html>
<head>
<title>SBUPM246V 24-Piece 3/8 Drive Socket Set</title>
<script type="application/ld+json">
{"@type": "Product", "name": "24-Piece Socket Set", "sku": "SBUPM246V",
 "offers": {"price": 499.95}, "image": "https://img.example/set.jpg"}
</script>
</head>
<body>
<main>
  <h1>24-Piece 3/8 Drive ADV Universal Impact Socket Set</h1>
  <section class="product-details">
    <h2>Set Details</h2>
    <div class="piece-grid">
      <div class="card"><a href="/p/bup10m6v">BUP10M6V socket</a> $31.95</div>
      <div class="card"><a href="/p/bup11m6v">BUP11M6V socket</a> $35.95</div>
      <div class="card"><a href="/p/bxp6v">BXP6V extension</a> $20.95</div>
    </div>
  </section>
  <aside class="rail">
    <h2>Similar Products</h2>
    <div class="card"><a href="/p/mt4779p">MT4779P impact wrench</a> $499.95</div>
    <div class="card"><a href="/p/saupm306v">SAUPM306V set</a> $599.95</div>
  </aside>
</main>
</body>
</html>
"""


def test_page_map_segments_by_generic_signals():
    page_map = evidence.build_page_map(_PAGE, recordings=[])
    assert page_map["stated_piece_count"] == 24
    assert page_map["jsonld_products"][0]["sku"] == "SBUPM246V"
    assert page_map["jsonld_products"][0]["has_price"] is True
    by_keyword = {s["keyword"]: s for s in page_map["sections"]}
    assert by_keyword["set details"]["card_count"] == 3
    assert "BUP10M6V" in by_keyword["set details"]["samples"][0]
    assert by_keyword["similar"]["card_count"] == 2
    assert "MT4779P" in by_keyword["similar"]["samples"][0]


_CHROME_PAGE = """
<html>
<head><title>SMUPM96TR Socket Set</title></head>
<body>
<header>
  <nav class="product-details-menu">
    <div class="card"><a href="/c/air">Air Hammers and tools</a> category</div>
    <div class="card"><a href="/c/body">Body Repair Tools</a> category</div>
  </nav>
</header>
<main>
  <section class="product-details">
    <h2>Set Details</h2>
    <div class="card"><a href="/p/s1">S1 socket piece</a> $10.00</div>
    <div class="card"><a href="/p/s2">S2 socket piece</a> $12.00</div>
  </section>
</main>
</body>
</html>
"""


def test_page_map_ignores_page_chrome():
    # Live evidence, 2026-11-20: a Mac set's map was eight
    # mega-menu "sections" and none of the product's own.
    page_map = evidence.build_page_map(_CHROME_PAGE, recordings=[])
    keywords = [s["keyword"] for s in page_map["sections"]]
    assert keywords == ["set details"]
    samples = page_map["sections"][0]["samples"]
    assert any("S1 socket" in sample for sample in samples)
    assert not any("Air Hammers" in sample for sample in samples)


def test_evidence_round_trip(db):
    evidence.store_evidence(
        db,
        brand="Matco Tools",
        model="SBUPM246V",
        url="https://www.matcotools.com/catalog/product/sbupm246v",
        kind="page_map",
        section=None,
        payload={"stated_piece_count": 24},
    )
    evidence.store_evidence(
        db,
        brand="Matco",
        model="sbupm246v",
        url="https://www.matcotools.com/arc/getProductsData",
        kind="data_response",
        section="$.payLoad.products",
        payload={"count": 12},
    )
    rows = evidence.evidence_for(db, brand="Matco Tools", model="SBUPM246V")
    assert [row["kind"] for row in rows] == ["page_map", "data_response"]
    assert rows[0]["payload"]["stated_piece_count"] == 24
    assert rows[1]["section"] == "$.payLoad.products"
    assert evidence.evidence_for(db, brand="Matco", model="OTHER") == []
