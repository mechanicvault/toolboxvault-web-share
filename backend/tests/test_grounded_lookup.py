"""Grounded lookups + identify hardening (owner fix, 2026-10-25).

The Lookup Truth Audit proved the AI-only chain echoes inputs,
invents wrong tools, and re-rolls per retry. These tests pin the
fix:

  - AI values that merely echo the user's typing never count
    as found content (and charge nothing when nothing else
    survives);
  - lookup + identify run at temperature 0 (determinism);
  - an identify/lookup result with details but no real name is
    `partial`, never a dressed-up full hit;
  - the grounded layer reads facts off a fetched product page
    (the AI provider's web search via the AI seam, or a
    pasted link): structured page data first, AI-read values
    only when the page supports them;
  - a pasted link that can't be read answers link_error and
    the chain does NOT fall back to an AI guess;
  - the photo endpoint returns a real page photo's bytes and
    refuses anything that isn't a photo.
"""

import base64
import json
import uuid

import pytest

from app.modules.billing import ai_service, entitlements, wallet
from app.modules.catalog import grounded, lookup, manuals
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Grounded User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def seeker(db):
    return _make_user(db, "TV-M-000611", "grounded@example.com")


def _configure_ai(db, monkeypatch, price_lookup=None):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "GROUND_TEST_AI_KEY")
    monkeypatch.setenv("GROUND_TEST_AI_KEY", "sk-test-not-real")
    if price_lookup is not None:
        entitlements.set_setting(db, ai_service.PRICE_KEYS["lookup"], price_lookup)
    db.commit()


def _stub_public_dns(monkeypatch):
    monkeypatch.setattr(manuals, "_host_ips", lambda host: ["93.184.216.34"])


def _responses_payload(results):
    """A Responses-API body whose message cites `results`
    ([{url, title}]) — the shape ai_service.web_search reads."""
    annotations = [
        {
            "type": "url_citation",
            "url": result.get("url", ""),
            "title": result.get("title", ""),
        }
        for result in results
    ]
    return {
        "output": [
            {"type": "web_search_call", "action": {"type": "search", "queries": ["t"]}},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Found it.",
                        "annotations": annotations,
                    }
                ],
            },
        ]
    }


def _ai_transport(payloads, search_results=None):
    """AI stub for BOTH seam endpoints: /responses (the web
    search) replays the canned citations; chat completions
    reply with the payload whose marker appears in the prompt
    (extraction prompts quote the page title; chain prompts
    name the brand), else the first payload."""

    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            transport.search_calls.append(body)
            return _responses_payload(search_results or [])
        prompt = body["messages"][-1]["content"]
        transport.calls.append(body)
        for marker, payload in payloads:
            if marker in prompt:
                return {
                    "choices": [
                        {"message": {"content": json.dumps(payload)}}
                    ]
                }
        return {"choices": [{"message": {"content": json.dumps(payloads[0][1])}}]}

    transport.calls = []
    transport.search_calls = []
    return transport


def _stub_pages(monkeypatch, pages):
    def fetch(url):
        if url in pages:
            return pages[url]
        raise grounded.PageFetchError("Couldn't reach that page.")

    monkeypatch.setattr(grounded, "_fetch_html", fetch)


# A trimmed Matco-style page: the product record rides the
# embedded page payload (the __NEXT_DATA__ pattern), exactly
# like the real SPRB4A page.
MATCO_PAGE = """
<html><head>
<title>4 PIECE TOP TORQUE II PRECISION SCREWDRIVER SET - BLUE SPRB4A | Matco Tools</title>
<meta property="og:site_name" content="Matco Tools" />
</head><body>
<h1>4 PIECE TOP TORQUE II PRECISION SCREWDRIVER SET - BLUE</h1>
<p>Top Torque II handle technology with more turning power.</p>
<script id="__NEXT_DATA__" type="application/json">
{"props": {"pageProps": {"data": {"payLoad": {"products": [
  {"displayName": "4 PIECE TOP TORQUE II PRECISION SCREWDRIVER SET - BLUE",
   "modelCode": "SPRB4A",
   "skus": {"SPRB4A": {
      "skuId": "SPRB4A",
      "displayName": "4 PIECE TOP TORQUE II PRECISION SCREWDRIVER SET - BLUE",
      "media": {"largeImg": "https://images.example.com/sprb4a-1500.jpg"},
      "skuDetails": {"price": {"listPrice": {"price": "$64.95"}}}
   }}}
]}}}}}
</script>
</body></html>
"""

# A DeWalt-style page: facts live in the title + visible text +
# og tags (the real DCF891B page's shape).
DEWALT_PAGE = """
<html><head>
<title>20V MAX XR 1/2-in Mid-Range Impact Wrench With Hog Ring Anvil (Tool Only)</title>
<meta property="og:image" content="https://assets.example.com/DCF891B_1.jpg" />
</head><body>
<p>Impact Wrenches</p>
<h1>DCF891B 20V MAX XR 1/2-in Mid-Range Impact Wrench With Hog Ring Anvil</h1>
<p>Drive size 1/2 in. Max torque 800 ft-lbs.</p>
</body></html>
"""


# -- hardening: echoes, determinism, partial -----------------------------------


def test_chain_ai_echo_only_is_a_miss_and_free(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch, price_lookup=3)
    wallet.credit(db, seeker.id, amount=10, bucket="banked", reason="test", ref="t")
    transport = _ai_transport([("", {"brand": "Matco", "model": "SPRB4A"})])
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Matco", "model": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"] == {}
    assert body["ai_charged"] == 0
    assert body["partial"] is False
    assert wallet.wallet_view(db, seeker.id)["banked_balance"] == 10


def test_chain_ai_echo_name_dropped_real_details_make_partial(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    transport = _ai_transport(
        [
            (
                "",
                {
                    "name": "Matco SPRB4A",
                    "category": "Screwdrivers",
                    "size": "4-piece set",
                },
            )
        ]
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Matco", "model": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert "name" not in body["fields"]
    assert body["fields"]["category"]["value"] == "Screwdrivers"
    assert body["partial"] is True


def test_lookup_and_identify_are_pinned_to_temperature_zero(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    transport = _ai_transport(
        [("", {"name": "Real Name Wrench", "category": "Wrenches", "size": "1/2 in"})]
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    client.get(
        "/api/catalog/lookup",
        params={"brand": "Acme", "model": "RW-1"},
        headers=auth_headers(seeker),
    )
    client.post(
        "/api/catalog/identify",
        json={"text": "a real name wrench made by acme"},
        headers=auth_headers(seeker),
    )
    assert len(transport.calls) == 2
    assert all(call["temperature"] == 0 for call in transport.calls)


def test_identify_name_that_restates_the_input_is_dropped(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    # The audit's echo: the AI hands the model number back as
    # the "name". Nothing real survives -> no fields, no charge.
    transport = _ai_transport(
        [("", {"name": "SPRB4A", "brand": "", "model": "SPRB4A", "category": ""})]
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.post(
        "/api/catalog/identify",
        json={"text": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"] == {}
    assert body["ai_charged"] == 0


def test_identify_without_a_name_is_partial(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    transport = _ai_transport(
        [("", {"name": "", "brand": "Fluke", "model": "17B+", "category": "Multimeters"})]
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.post(
        "/api/catalog/identify",
        json={"text": "yellow fluke multimeter, says 17B+ on it"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["partial"] is True
    assert body["fields"]["brand"]["value"] == "Fluke"


# -- grounded: search mode -------------------------------------------------------


def test_grounded_search_reads_the_product_page(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(
        monkeypatch, {"https://www.matcotools.com/catalog/product/sprb4a": MATCO_PAGE}
    )
    # The AI reader adds a category the page supports (its text
    # says "screwdriver set" in the name) — and tries one the
    # page never states, which the validator must drop.
    transport = _ai_transport(
        [
            (
                "TOP TORQUE",
                {"category": "Screwdriver set", "size": "glow in the dark"},
            )
        ],
        search_results=[
            {
                "title": "SPRB4A | Matco",
                "url": "https://www.matcotools.com/catalog/product/sprb4a",
            }
        ],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Matco", "model": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    fields = body["fields"]
    assert fields["name"] == {
        "value": "4 PIECE TOP TORQUE II PRECISION SCREWDRIVER SET - BLUE",
        "source": "web",
        "detail": "Matco Tools",
    }
    assert fields["model"]["value"] == "SPRB4A"
    assert fields["msrp"]["value"] == 64.95
    assert fields["category"]["value"] == "Screwdriver set"
    assert "size" not in fields  # invented -> unsupported -> dropped
    assert body["partial"] is False
    assert body["image_url"] == "https://images.example.com/sprb4a-1500.jpg"
    assert body["source_url"] == "https://www.matcotools.com/catalog/product/sprb4a"
    assert body["web_configured"] is True
    assert "web" in body["sources"]


def test_grounded_search_dark_ai_means_no_fake_grounding(
    client, db, seeker, monkeypatch
):
    """Search rides the AI seam: with the AI unconfigured the
    web layer is dark, nothing is dialed (no search call, no
    page fetch), and the answer says web_configured False —
    the honest 'isn't switched on' state. (The pre-2026-10-25
    shape of this test configured a separate Brave key; the
    one-vendor decision removed that leg entirely.)"""
    called = []
    monkeypatch.setattr(
        ai_service, "_transport", lambda *a, **k: called.append(1) or {}
    )
    monkeypatch.setattr(
        grounded, "_fetch_html", lambda url: called.append(2) or ""
    )
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Matco", "model": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert called == []  # nothing was dialed at all
    assert body["web_configured"] is False
    assert body["fields"] == {}
    assert all(f["source"] != "web" for f in body["fields"].values())


def test_grounded_control_case_specs_come_from_the_page_not_memory(
    client, db, seeker, monkeypatch
):
    """The DCF891 control: the old chain called it a 1/4-inch
    impact driver. Off the real page shape, the name carries
    1/2-in — and the AI's attempt to re-add the hallucinated
    1/4 in size is refused as unsupported by the page."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(
        monkeypatch, {"https://www.dewalt.com/product/dcf891b": DEWALT_PAGE}
    )
    transport = _ai_transport(
        [
            (
                "Mid-Range Impact Wrench",
                {
                    "name": "20V MAX XR 1/2-in Mid-Range Impact Wrench With Hog Ring Anvil (Tool Only)",
                    "brand": "DeWalt",
                    "category": "Impact Wrenches",
                    "size": "1/4 in drive",
                },
            )
        ],
        search_results=[
            {"title": "DCF891B", "url": "https://www.dewalt.com/product/dcf891b"}
        ],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "DeWalt", "model": "DCF891"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    fields = body["fields"]
    assert "Impact Wrench" in fields["name"]["value"]
    assert "1/2" in fields["name"]["value"]
    assert fields["category"]["value"] == "Impact Wrenches"
    assert "size" not in fields  # the 1/4 in hallucination is refused
    assert body["image_url"] == "https://assets.example.com/DCF891B_1.jpg"


# -- grounded: link mode ---------------------------------------------------------


def test_link_mode_reads_the_pasted_page_and_skips_search(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(
        monkeypatch, {"https://www.matcotools.com/catalog/product/sprb4a": MATCO_PAGE}
    )
    transport = _ai_transport([("TOP TORQUE", {"category": "Screwdriver set"})])
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={
            "brand": "Matco",
            "model": "SPRB4A",
            "link": "https://www.matcotools.com/catalog/product/sprb4a",
        },
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert transport.search_calls == []  # the link skips search entirely
    assert body["fields"]["name"]["source"] == "web"
    assert body["fields"]["name"]["value"].startswith("4 PIECE TOP TORQUE II")
    assert body["link_error"] is False


def test_link_mode_unreadable_page_never_falls_back_to_a_guess(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {})
    transport = _ai_transport([("", {"name": "Invented Name", "category": "Wrenches"})])
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={
            "brand": "Matco",
            "model": "SPRB4A",
            "link": "https://www.matcotools.com/gone",
        },
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["link_error"] is True
    assert body["fields"] == {}
    assert transport.calls == []  # no AI guess was even attempted


# -- photo endpoint ----------------------------------------------------------------

_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def test_fetch_photo_returns_real_bytes(client, db, seeker, monkeypatch):
    _stub_public_dns(monkeypatch)
    monkeypatch.setattr(
        manuals, "_download", lambda url: (_JPEG, "image/jpeg")
    )
    resp = client.post(
        "/api/catalog/fetch-photo",
        json={"url": "https://images.example.com/sprb4a-1500.jpg"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_type"] == "image/jpeg"
    assert body["filename"] == "sprb4a-1500.jpg"
    assert base64.b64decode(body["data_base64"]) == _JPEG


def test_fetch_photo_refuses_a_non_photo(client, db, seeker, monkeypatch):
    _stub_public_dns(monkeypatch)
    monkeypatch.setattr(
        manuals,
        "_download",
        lambda url: (b"<html>not a photo</html>", "text/html"),
    )
    resp = client.post(
        "/api/catalog/fetch-photo",
        json={"url": "https://images.example.com/not-a-photo"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "photo_unreadable"


def test_fetch_photo_refuses_a_private_address(client, db, seeker, monkeypatch):
    monkeypatch.setattr(manuals, "_host_ips", lambda host: ["192.168.1.10"])
    resp = client.post(
        "/api/catalog/fetch-photo",
        json={"url": "https://images.example.com/x.jpg"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "photo_unreadable"


# -- page-parser regressions (found live, 2026-10-25) ---------------------------


def test_embedded_product_found_behind_a_huge_navigation_tree():
    """Real store payloads bury the product record behind tens
    of thousands of navigation/category nodes (Matco's page
    does). The miner's walk budget must cover the whole
    payload — a shallow cap reads the page as product-less and
    the grounded lookup fails on exactly the pages it exists
    for."""
    filler = {
        f"cat{i}": {"name": f"Category {i}", "children": {"a": i, "b": [i, i + 1]}}
        for i in range(4000)
    }
    payload = json.dumps(
        {
            "props": {
                "pageProps": {
                    "categories": filler,
                    "products": [
                        {
                            "displayName": "4 PIECE TOP TORQUE II PRECISION "
                            "SCREWDRIVER SET - BLUE",
                            "modelCode": "SPRB4A",
                            "skus": {
                                "SPRB4A": {"skuDetails": {"price": 64.95}}
                            },
                        }
                    ],
                }
            }
        }
    )
    products = grounded._embedded_products(payload)
    assert len(products) == 1
    assert products[0]["model"] == "SPRB4A"
    assert products[0]["msrp"] == 64.95


def test_page_title_ignores_svg_icon_titles():
    """Inline SVG icons carry their own <title> children
    ("User", "Arrow left", …). Only the page's own title may
    name the product — the icon titles used to be glued onto
    it, polluting the extracted name's evidence."""
    html = (
        "<html><head><title>Real Product Name XYZ1 | Store</title></head>"
        "<body><svg><title>User</title><path d='M0 0'/></svg>"
        "<svg><title>Arrow left</title></svg>"
        "<h1>Real Product Name</h1></body></html>"
    )
    page = grounded.parse_page(html, "https://store.example.com/p/xyz1")
    assert page["title"] == "Real Product Name XYZ1 | Store"


def test_search_results_are_reduced_to_urls_only(db, seeker, monkeypatch):
    """Routing posture at the provider boundary: search
    payloads are transient routing. The pipe drops citation
    titles at the boundary — only URLs travel (tracking
    parameters stripped, https only, deduped) — so nothing
    downstream can store, return, or lean on the provider's
    text. Facts come from the fetched page plus its URL,
    never from the search answer."""
    _configure_ai(db, monkeypatch)
    transport = _ai_transport(
        [],
        search_results=[
            {
                "title": "SPRB4A - 4 Piece Top Torque II Set",
                "url": "https://www.matcotools.com/catalog/product/sprb4a?utm_source=openai",
            },
            {"title": "No URL entry", "description": "dropped"},
            {"url": "http://insecure.example.com/x", "title": "http dropped"},
            {
                "title": "Duplicate entry",
                "url": "https://www.matcotools.com/catalog/product/sprb4a",
            },
        ],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    results = grounded.search_pages(db, "Matco SPRB4A")
    assert results == [{"url": "https://www.matcotools.com/catalog/product/sprb4a"}]
    assert transport.search_calls  # the search really went through the seam


def test_search_ranking_walks_product_pages_before_search_pages(
    db, seeker, monkeypatch
):
    """Page-choice discipline: a catalog SEARCH page cited
    first still walks last — the manufacturer's product page
    is tried before it (the eval's SPRB4A run is the cautionary
    tale: the raw search answer stopped at the search page and
    missed the price on the product page)."""
    _configure_ai(db, monkeypatch)
    transport = _ai_transport(
        [],
        search_results=[
            {"title": "Search", "url": "https://www.matcotools.com/catalog/search?t=Product_Length_9"},
            {"title": "Retailer", "url": "https://www.toolstore.example.com/sprb4a"},
            {
                "title": "SPRB4A | Matco",
                "url": "https://www.matcotools.com/catalog/product/sprb4a",
            },
        ],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    results = grounded.search_pages(db, "Matco SPRB4A", count=5)
    assert [r["url"] for r in results] == [
        "https://www.matcotools.com/catalog/product/sprb4a",
        "https://www.toolstore.example.com/sprb4a",
        "https://www.matcotools.com/catalog/search?t=Product_Length_9",
    ]


# A Matco-style SEARCH page: it names the model, carries no
# product record of its own, and links the product page.
MATCO_SEARCH_PAGE = """
<html><head>
<title>Search results | Matco Tools</title>
<meta property="og:site_name" content="Matco Tools" />
</head><body>
<h1>Results for SPRB4A</h1>
<a href="/catalog/product/sprb4a/4-piece-top-torque-ii-precision-screwdriver-set-blue">SPRB4A screwdriver set</a>
</body></html>
"""


def test_search_walk_follows_a_listing_pages_product_link(
    client, db, seeker, monkeypatch
):
    """When the only citation is the catalog search page, the
    walk follows its same-host product link (the address
    carries the model) and reads the facts off the PRODUCT
    page — source, name, and price all name that page."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    search_url = "https://www.matcotools.com/catalog/search?t=Product_Length_9"
    product_url = (
        "https://www.matcotools.com/catalog/product/sprb4a/"
        "4-piece-top-torque-ii-precision-screwdriver-set-blue"
    )
    _stub_pages(
        monkeypatch, {search_url: MATCO_SEARCH_PAGE, product_url: MATCO_PAGE}
    )
    transport = _ai_transport(
        [("TOP TORQUE", {"category": "Screwdriver set"})],
        search_results=[{"title": "Search", "url": search_url}],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Matco", "model": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["source_url"] == product_url
    assert body["fields"]["name"]["value"].startswith("4 PIECE TOP TORQUE II")
    assert body["fields"]["msrp"]["value"] == 64.95


def test_listing_page_facts_come_from_records_not_the_ai_reader(
    client, db, seeker, monkeypatch
):
    """A listing/search page is read deterministically or not
    at all: its model-matched structured record may speak
    (name + price), but the AI reader never runs over text
    that mixes many products."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    search_url = "https://www.matcotools.com/catalog/search?t=Product_Length_9"
    _stub_pages(monkeypatch, {search_url: MATCO_PAGE})
    transport = _ai_transport(
        [("TOP TORQUE", {"category": "Screwdriver set"})],
        search_results=[{"title": "Search", "url": search_url}],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Matco", "model": "SPRB4A"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["name"]["source"] == "web"
    assert body["fields"]["msrp"]["value"] == 64.95
    assert "category" not in body["fields"]  # the AI reader never ran
    assert transport.calls == []


# -- C-08 (Deep Audit Round 2): variant substitution + brand code ---------------

# A DeWalt-style KIT page: structured data carries the kit model
# and the manufacturer CODE "DW" as the brand — the exact shape
# the live audit caught answering a typed bare-model lookup.
DEWALT_KIT_PAGE = """
<html><head>
<title>20V MAX* XR 1/2-in Mid-Range Impact Wrench Kit With Hog Ring Anvil</title>
<meta property="og:site_name" content="DEWALT" />
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product",
 "name": "20V MAX* XR 1/2-in Mid-Range Impact Wrench Kit With Hog Ring Anvil",
 "brand": {"@type": "Brand", "name": "DW"},
 "model": "DCF891P2", "category": "Impact Wrenches",
 "offers": {"@type": "Offer", "price": 399}}
</script>
</head><body><h1>DCF891P2 kit</h1></body></html>
"""

# The bare tool's own page (its address carries no model segment,
# so the URL ranking cannot save the walk — only the walk's
# exact-model preference can).
DEWALT_EXACT_PAGE = """
<html><head>
<title>20V MAX* XR 1/2-in Mid-Range Impact Wrench With Hog Ring Anvil</title>
<meta property="og:site_name" content="DEWALT" />
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product",
 "name": "20V MAX* XR 1/2-in Mid-Range Impact Wrench With Hog Ring Anvil",
 "brand": {"@type": "Brand", "name": "DW"},
 "model": "DCF891", "category": "Impact Wrenches",
 "offers": {"@type": "Offer", "price": 249}}
</script>
</head><body><h1>DCF891 bare tool</h1></body></html>
"""

DEWALT_BATTERY_PAGE = """
<html><head>
<title>20V MAX XR 5.0Ah Battery</title>
<meta property="og:site_name" content="DEWALT" />
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product",
 "name": "20V MAX XR 5.0Ah Battery",
 "brand": {"@type": "Brand", "name": "DW"},
 "model": "DCB205", "category": "Batteries",
 "offers": {"@type": "Offer", "price": 129}}
</script>
</head><body><h1>DCB205 battery</h1></body></html>
"""

KIT_URL = "https://www.dewalt.com/en-us/product/dcf891p2"
EXACT_URL = "https://www.dewalt.com/en-us/products/bare-tool-page"
BATTERY_URL = "https://www.dewalt.com/en-us/product/dcb205"


def test_walk_prefers_the_exact_model_page_over_a_variant(
    client, db, seeker, monkeypatch
):
    """C-08 (a): the kit page is cited FIRST and names a product,
    but its model is a variant of the typed one — the walk holds
    it as a fallback and the exact-model page wins."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {KIT_URL: DEWALT_KIT_PAGE, EXACT_URL: DEWALT_EXACT_PAGE})
    transport = _ai_transport(
        [("", {})],
        search_results=[
            {"title": "Kit", "url": KIT_URL},
            {"title": "Bare tool", "url": EXACT_URL},
        ],
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"model": "DCF891"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["model"]["value"] == "DCF891"
    assert body["fields"]["brand"]["value"] == "DeWalt"
    assert body["source_url"] == EXACT_URL
    assert body["model_mismatch"] is False
    assert "found_model" not in body  # None is excluded from the wire


def test_variant_only_result_is_flagged_and_brand_code_resolved(
    client, db, seeker, monkeypatch
):
    """C-08 (b)+(c): when only the variant page exists, it may
    answer — but the brand code resolves to the real brand and
    the result is FLAGGED with the page's model, never silent."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {KIT_URL: DEWALT_KIT_PAGE})
    transport = _ai_transport(
        [("", {})], search_results=[{"title": "Kit", "url": KIT_URL}]
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"model": "DCF891"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["model"]["value"] == "DCF891P2"
    assert body["fields"]["brand"]["value"] == "DeWalt"
    assert body["model_mismatch"] is True
    assert body["found_model"] == "DCF891P2"


def test_exact_model_with_brand_code_is_not_a_mismatch(
    client, db, seeker, monkeypatch
):
    """The DCB205 control: exact model, brand arrives as the
    code "DW" — brand resolves, no mismatch flag."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {BATTERY_URL: DEWALT_BATTERY_PAGE})
    transport = _ai_transport(
        [("", {})], search_results=[{"title": "Battery", "url": BATTERY_URL}]
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"model": "DCB205"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["model"]["value"] == "DCB205"
    assert body["fields"]["brand"]["value"] == "DeWalt"
    assert body["model_mismatch"] is False


def test_link_mode_variant_is_flagged_too(client, db, seeker, monkeypatch):
    """Paste-a-link is not exempt: the pasted page is a variant
    of the typed model, so the flag travels with the result."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {KIT_URL: DEWALT_KIT_PAGE})
    transport = _ai_transport([("", {})])
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"model": "DCF891", "link": KIT_URL},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["model"]["value"] == "DCF891P2"
    assert body["model_mismatch"] is True
    assert body["found_model"] == "DCF891P2"


def test_link_mode_exact_model_is_not_flagged(client, db, seeker, monkeypatch):
    """Paste-a-link with a matching model: unaffected — no flag."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {BATTERY_URL: DEWALT_BATTERY_PAGE})
    transport = _ai_transport([("", {})])
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.get(
        "/api/catalog/lookup",
        params={"model": "DCB205", "link": BATTERY_URL},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["model"]["value"] == "DCB205"
    assert body["fields"]["brand"]["value"] == "DeWalt"
    assert body["model_mismatch"] is False


def test_brand_code_alias_and_typed_brand_wins():
    from app.modules.catalog.normalize import canonical_brand, resolve_brand

    assert canonical_brand("DW") == "DeWalt"
    assert canonical_brand("DeWalt") == "DeWalt"
    assert canonical_brand("Matco") == "Matco"
    assert resolve_brand("DW") == "DeWalt"
    assert resolve_brand("DW", "DeWalt") == "DeWalt"
    # The user's own typing beats the code; a real brand name the
    # page states is never overridden by typing.
    assert resolve_brand("DW", "My Brand") == "My Brand"
    assert resolve_brand("Matco", "Other") == "Matco"


def test_ranking_walks_exact_model_urls_before_variant_urls():
    ranked = grounded.rank_candidate_urls(
        [
            "https://www.dewalt.com/en-us/product/dcf891p2",
            "https://www.dewalt.com/en-us/product/dcf891",
        ],
        "DeWalt DCF891",
        model="DCF891",
    )
    assert ranked == [
        "https://www.dewalt.com/en-us/product/dcf891",
        "https://www.dewalt.com/en-us/product/dcf891p2",
    ]
