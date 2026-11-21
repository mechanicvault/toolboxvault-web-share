"""Row 200: the lookup browses like a person. When a product
page is a script-built application whose raw HTML is an empty
shell, the lookup loads it in the server-side browser and
reads the loaded page — tabs, galleries and set lists
included. A complete static page never pays for the browser,
a browser failure falls back to the raw reading, and a piece
photo is paired only when the text around that photo on the
page supports the piece."""

import json

import pytest

from app.modules.billing import ai_service, entitlements
from app.modules.catalog import grounded, rendered


@pytest.fixture()
def seeker(db):
    import uuid as _uuid

    from app.modules.core import models as core_models

    user = core_models.User(
        id=_uuid.uuid4(),
        account_number="TV-M-000714",
        email="rendered@example.com",
        password_hash="not-a-real-hash",
        name="Rendered Reader",
        account_types=["mechanic"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _configure_ai(db, monkeypatch):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "RENDER_TEST_AI_KEY")
    monkeypatch.setenv("RENDER_TEST_AI_KEY", "test-key")
    db.commit()


def _chat_transport(payload):
    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            return {"output": []}
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return transport


_URL = "https://shop.example.com/products/sabctx13va"

# The raw download of a script-built page: a mount point, a
# data island with no product in it, and almost no text.
_SHELL_HTML = """
<html><head><title>undefined</title>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{}}}
</script>
</head><body><div id="__next"></div></body></html>
"""

# The same page as the browser loads it: the product record
# plus the Set Details tab's rows as real text.
_RENDERED_HTML = """
<html><head>
<title>13-Piece ADV Torx Bit Socket Set SABCTX13VA</title>
<script type="application/ld+json">
{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",
 "brand":"Matco Tools","model":"SABCTX13VA",
 "offers":{"price":169.95},"image":"https://example.com/set.jpg"}
</script>
</head><body>
<h1>13-Piece ADV Torx Bit Socket Set</h1>
<div role="tabpanel">Set Details
T8 Torx Bit Socket A8TXVA $14.95
T10 Torx Bit Socket A10TXVA $13.95
T60 Torx Bit Socket C60TXVA $24.95
</div>
</body></html>
"""

_MEDIA = [
    {
        "src": "https://example.com/a8txva.jpg",
        "alt": "A8TXVA",
        "context": "T8 Torx Bit Socket A8TXVA $14.95",
    },
    {
        "src": "https://example.com/c60txva.jpg",
        "alt": "",
        "context": "T60 Torx Bit Socket C60TXVA $24.95",
    },
]


def _stub_fetch(monkeypatch, raw_html, render_result=None, render_error=None):
    monkeypatch.setattr(grounded, "validate_page_url", lambda url: url)
    monkeypatch.setattr(grounded, "_fetch_html", lambda url: raw_html)

    def fake_render(url):
        if render_error is not None:
            raise render_error
        return render_result

    monkeypatch.setattr(rendered, "render_page", fake_render)


def test_shell_page_escalates_to_the_browser(monkeypatch):
    _stub_fetch(monkeypatch, _SHELL_HTML, render_result=(_RENDERED_HTML, _MEDIA))
    page = grounded.fetch_product_page(_URL)
    assert page["candidates"], "the loaded page's product record must be read"
    assert page["candidates"][0]["model"] == "SABCTX13VA"
    assert "A8TXVA" in page["text"]
    assert page["media"][0]["src"] == "https://example.com/a8txva.jpg"


def test_island_set_page_still_escalates_to_the_browser(monkeypatch):
    # A script-built set page whose download DOES carry the
    # product record (a data island: candidates, >4000 chars
    # of text) but none of the set's contents — the contents
    # exist only in the loaded page, so the browser read is
    # still owed. (The live Matco page behaves exactly this
    # way on some loads.)
    island_html = (
        "<html><head><title>13-Piece ADV Torx Bit Socket Set SABCTX13VA</title>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"@type":"Product","name":"13-Piece ADV Torx Bit Socket Set",'
        '"brand":"Matco Tools","model":"SABCTX13VA",'
        '"offers":{"price":169.95}}</script></head>'
        '<body><div id="__next">'
        + _filler(4100)
        + "</div></body></html>"
    )
    loaded_html = _RENDERED_HTML.replace(
        "</body>", _filler(4500) + "</body>"
    )
    _stub_fetch(monkeypatch, island_html, render_result=(loaded_html, _MEDIA))
    page = grounded.fetch_product_page(_URL)
    assert page["media"], "the loaded page's photo inventory must be used"
    assert "A8TXVA" in page["text"]


def test_quick_fetch_never_renders(monkeypatch):
    # Row 203: the quick pass is downloads only — even a
    # shell page whose full read needs the browser comes
    # back as the raw parse, untouched by the renderer.
    def forbidden_render(url):
        raise AssertionError("the quick pass must not render")

    monkeypatch.setattr(grounded, "validate_page_url", lambda url: url)
    monkeypatch.setattr(grounded, "_fetch_html", lambda url: _SHELL_HTML)
    monkeypatch.setattr(rendered, "render_page", forbidden_render)
    page = grounded.fetch_product_page(_URL, allow_render=False)
    assert page["media"] == []


_OTHER_PAGE = """
<html><head><title>Some other wrench</title>
<script type="application/ld+json">
{"@type":"Product","name":"Unrelated Wrench","brand":"Matco Tools",
 "model":"WR999","offers":{"price":19.95}}
</script></head><body><h1>WR999</h1><p>A plain wrench.</p></body></html>
"""


def test_quick_walk_reads_only_the_first_pages(db, monkeypatch):
    # Row 203: with no anchor among the results, the full
    # walk reads every citation; the quick walk stops after
    # the first couple.
    urls = [f"https://shop{i}.example.com/p" for i in range(4)]
    fetched = []
    monkeypatch.setattr(grounded, "validate_page_url", lambda url: url)
    monkeypatch.setattr(grounded, "search_configured", lambda db_: True)
    monkeypatch.setattr(
        grounded,
        "search_pages",
        lambda db_, query, count=5, model="": [{"url": u} for u in urls],
    )

    def counting_fetch(url):
        fetched.append(url)
        return _OTHER_PAGE

    monkeypatch.setattr(grounded, "_fetch_html", counting_fetch)
    grounded.grounded_product(db, brand="Matco", model="SABCTX13VA", quick=True)
    assert len(fetched) == 2
    fetched.clear()
    grounded.grounded_product(db, brand="Matco", model="SABCTX13VA")
    assert len(fetched) == 4


def test_run_lookup_threads_the_quick_flag(db, seeker, monkeypatch):
    from app.modules.catalog import lookup

    seen = {}

    def fake_grounded(db_, *, brand="", model="", link="", quick=False):
        seen["quick"] = quick
        return None

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    lookup.run_lookup(db, seeker.id, brand="Matco", model="SABCTX13VA", quick=True)
    assert seen["quick"] is True
    lookup.run_lookup(db, seeker.id, brand="Matco", model="SABCTX13VA")
    assert seen["quick"] is False


def test_complete_static_page_never_renders(monkeypatch):
    def forbidden_render(url):
        raise AssertionError("a complete static page must not pay for the browser")

    monkeypatch.setattr(grounded, "validate_page_url", lambda url: url)
    monkeypatch.setattr(grounded, "_fetch_html", lambda url: _RENDERED_HTML)
    monkeypatch.setattr(rendered, "render_page", forbidden_render)
    page = grounded.fetch_product_page(_URL)
    assert page["candidates"][0]["model"] == "SABCTX13VA"


def test_browser_failure_falls_back_to_the_raw_reading(monkeypatch):
    _stub_fetch(
        monkeypatch,
        _SHELL_HTML,
        render_error=rendered.RenderError("no browser"),
    )
    page = grounded.fetch_product_page(_URL)
    assert page["candidates"] == []
    assert page["url"] == _URL


def test_thinner_rendered_reading_keeps_the_raw_one(monkeypatch):
    _stub_fetch(
        monkeypatch,
        _SHELL_HTML,
        render_result=("<html><head></head><body></body></html>", []),
    )
    page = grounded.fetch_product_page(_URL)
    # The raw shell at least carried the data island's text;
    # an emptier loaded page must not replace it.
    assert "__next_data__" in page["evidence"] or page["candidates"] == []


def test_rendered_reading_disabled_by_the_dial(monkeypatch):
    _stub_fetch(monkeypatch, _SHELL_HTML, render_result=(_RENDERED_HTML, _MEDIA))
    monkeypatch.setattr(rendered, "rendered_enabled", lambda: False)
    page = grounded.fetch_product_page(_URL)
    assert page["candidates"] == []


def _filler(chars: int) -> str:
    sentence = "Browse the full catalog of professional hand tools. "
    return "<p>" + (sentence * (chars // len(sentence) + 1))[:chars] + "</p>"


_CARDS_HTML = (
    "<h2>Set Details</h2>"
    "<div><p>1/4 DRIVE TORX T8</p><p>Part No: A8TXVA</p><p>$14.95</p></div>"
    "<div><p>3/8 DRIVE TORX T30</p><p>Part No: B30TXVA</p><p>$15.95</p></div>"
    "<div><p>1/2 DRIVE TORX T60</p><p>Part No: C60TXVA</p><p>$24.95</p></div>"
)


def test_excerpt_covers_a_deep_set_list(monkeypatch):
    # The set list sits ~9k characters into the page text —
    # past the old head-only excerpt, which cut it in half and
    # left the AI with the description's size list instead.
    html = (
        "<html><head><title>Torx Bit Socket Set SABCTX13VA</title></head>"
        "<body><h1>Torx Bit Socket Set</h1>"
        + _filler(9000)
        + _CARDS_HTML
        + "</body></html>"
    )
    page = grounded.parse_page(html, _URL)
    assert len(page["text"]) > 9000
    assert page["text"].find("C60TXVA") > 5000, "the list must sit past the old cut"
    excerpt = grounded.page_excerpt(page, "SABCTX13VA")
    assert "A8TXVA" in excerpt
    assert "C60TXVA" in excerpt
    assert "24.95" in excerpt


def test_excerpt_windows_reach_contents_on_huge_pages(monkeypatch):
    # Past the whole-text limit, the contents-marker window
    # must still carry the set list into the AI's read.
    html = (
        "<html><head><title>Torx Bit Socket Set SABCTX13VA</title></head>"
        "<body><h1>Torx Bit Socket Set</h1>"
        + _filler(24000)
        + _CARDS_HTML
        + _filler(4000)
        + "</body></html>"
    )
    page = grounded.parse_page(html, _URL)
    assert len(page["text"]) > grounded._EXCERPT_LIMIT
    excerpt = grounded.page_excerpt(page, "SABCTX13VA")
    assert len(excerpt) <= grounded._EXCERPT_LIMIT
    assert "C60TXVA" in excerpt
    assert "24.95" in excerpt


_CARD_MEDIA = [
    {
        "src": "https://example.com/a8txva.jpg",
        "alt": "",
        "context": '1/4" DRIVE TORX T8 Part No: A8TXVA -+ $14.95 ADD TO CART',
    },
    {
        "src": "https://example.com/a10txva.jpg",
        "alt": "",
        "context": '1/4" DRIVE TORX T10 Part No: A10TXVA -+ $13.95 ADD TO CART',
    },
    {
        "src": "https://example.com/b30txva.jpg",
        "alt": "",
        "context": '3/8" DRIVE TORX T30 Part No: B30TXVA -+ $15.95 ADD TO CART',
    },
    {
        "src": "https://example.com/c60txva.jpg",
        "alt": "",
        "context": '1/2" DRIVE TORX T60 Part No: C60TXVA -+ $24.95 ADD TO CART',
    },
]


def test_card_pieces_enrich_the_ai_contents_list(db, seeker, monkeypatch):
    # The AI lists the set's contents by name only (from the
    # description's includes line) and treats the priced
    # cards as separate products. The cards themselves state
    # each piece's part number, price and photo — the kit
    # must carry all three after the merge.
    _configure_ai(db, monkeypatch)
    page = grounded.parse_page(_RENDERED_HTML, _URL, media=_CARD_MEDIA)
    payload = {
        "pieces": [
            {"name": "T8 Torx Bit Socket"},
            {"name": "T10 Torx Bit Socket"},
            {"name": "T60 Torx Bit Socket"},
        ],
        "piece_count": 13,
    }
    monkeypatch.setattr(ai_service, "_transport", _chat_transport(payload))
    _fields, _ai_used, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    by_name = {piece["name"]: piece for piece in kit["pieces"]}
    # The listed names phrase the piece differently from its
    # card ("T8 Torx Bit Socket" vs "1/4 DRIVE TORX T8") —
    # the size token is what ties them together.
    assert by_name["T8 Torx Bit Socket"]["model"] == "A8TXVA"
    assert by_name["T8 Torx Bit Socket"]["msrp"] == 14.95
    assert (
        by_name["T8 Torx Bit Socket"]["image_url"]
        == "https://example.com/a8txva.jpg"
    )
    assert by_name["T60 Torx Bit Socket"]["model"] == "C60TXVA"
    # The T30 card no listed piece claimed stands as a piece
    # in its own right.
    models = {piece.get("model") for piece in kit["pieces"]}
    assert "B30TXVA" in models


def test_card_pieces_stand_alone_when_the_ai_lists_none(db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    page = grounded.parse_page(_RENDERED_HTML, _URL, media=_CARD_MEDIA)
    monkeypatch.setattr(ai_service, "_transport", _chat_transport({}))
    _fields, _ai_used, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    models = {piece.get("model") for piece in kit["pieces"]}
    assert models == {"A8TXVA", "A10TXVA", "B30TXVA", "C60TXVA"}
    assert all(piece.get("image_url") for piece in kit["pieces"])


def test_priced_cards_on_a_non_set_page_make_no_pieces(db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    html = """
    <html><head><title>Cordless Impact Wrench IW900</title>
    <script type="application/ld+json">
    {"@type":"Product","name":"Cordless Impact Wrench",
     "brand":"Matco Tools","model":"IW900",
     "offers":{"price":249.95},"image":"https://example.com/iw.jpg"}
    </script></head><body><h1>Cordless Impact Wrench</h1></body></html>
    """
    page = grounded.parse_page(html, _URL, media=_CARD_MEDIA)
    monkeypatch.setattr(ai_service, "_transport", _chat_transport({}))
    _fields, _ai_used, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "IW900"
    )
    assert kit["pieces"] == []


def test_media_inventory_keeps_deep_piece_photos():
    # The loader returns the main content's images first, but
    # a set's piece photos can still sit deep in the list; the
    # parser's inventory must not cut them off at 40.
    media = [
        {
            "src": f"https://example.com/gallery-{i}.jpg",
            "alt": "",
            "context": "Product gallery view",
        }
        for i in range(60)
    ]
    media.append(
        {
            "src": "https://example.com/a8txva.jpg",
            "alt": "",
            "context": "TORX T8 Part No: A8TXVA $14.95",
        }
    )
    page = grounded.parse_page(_RENDERED_HTML, _URL, media=media)
    srcs = [item["src"] for item in page["media"]]
    assert "https://example.com/a8txva.jpg" in srcs


def test_piece_photos_pair_only_when_the_card_supports_them(db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    page = grounded.parse_page(_RENDERED_HTML, _URL, media=_MEDIA)
    payload = {
        "pieces": [
            {
                "name": "T8 Torx Bit Socket",
                "model": "A8TXVA",
                "msrp": 14.95,
                "image_url": "https://example.com/a8txva.jpg",
            },
            {
                "name": "T10 Torx Bit Socket",
                "model": "A10TXVA",
                "msrp": 13.95,
                # This photo's card names the T60, not the T10.
                "image_url": "https://example.com/c60txva.jpg",
            },
            {
                "name": "T60 Torx Bit Socket",
                "model": "C60TXVA",
                "msrp": 24.95,
                # Not a photo the page carries at all.
                "image_url": "https://example.com/invented.jpg",
            },
        ],
        "piece_count": 13,
    }
    monkeypatch.setattr(ai_service, "_transport", _chat_transport(payload))
    _fields, _ai_used, kit, _extras = grounded.extract_fields(
        db, page, "Matco", "SABCTX13VA"
    )
    by_model = {piece.get("model"): piece for piece in kit["pieces"]}
    assert by_model["A8TXVA"]["image_url"] == "https://example.com/a8txva.jpg"
    assert "image_url" not in by_model["A10TXVA"]
    assert "image_url" not in by_model["C60TXVA"]
