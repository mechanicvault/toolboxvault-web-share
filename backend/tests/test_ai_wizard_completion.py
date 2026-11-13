"""AI wizard completion lane (2026-11-07) — the entry-system
build on Ryan's doctrine: every path into item entry (type it,
look it up, PHOTO it), facts verified before use, no dead ends.

Pins:
  - VISION rides the existing AI seam: an image becomes the
    provider's native image parts (OpenAI image_url data URL;
    Anthropic base64 image block), and a text-only call keeps
    its exact old request shape;
  - POST /catalog/identify-photo: a photo of the tool or its
    label -> the identify contract (source-labeled fields)
    PLUS the model's stated confidence; the bytes are
    byte-sniffed (a declared mime is never trusted), capped,
    and refused with 422 when they aren't a usable photo;
  - metering rides ai.identify_price (default 0 = free) with
    charge-after-success: an answer with no usable fields, a
    provider failure, and an unreadable photo all charge 0;
  - the dark seam answers 503 {code: ai_not_configured}, the
    established contract;
  - ENTRY AI IS CORE (Job 4): a plain mechanic holds NO
    ai_assistant entitlement (the module is assigned to no
    group) and the entry surfaces — lookup, identify,
    identify-photo — all still answer. The repurposed module
    gates nothing and is sold as nothing: its copy says the
    header assistant is a future add-on and entry help is
    always included;
  - DESCRIPTION joins the lookup vocabulary (Job 3) under the
    same grounding discipline: a structured page record's
    description and the page's own meta description are
    page-supported by construction; an AI-read description the
    page does NOT support is dropped like any invented value;
  - the manual pattern table stays Milwaukee-only (Job 5):
    no other brand's pattern could be probe-verified as
    composable from the model alone, so none is guessed at.
"""

import base64
import json
import uuid

import pytest

from app.modules.billing import ai_manifest, ai_service, entitlements, wallet
from app.modules.catalog import grounded, lookup, manuals
from app.modules.core import models as core_models, module_control
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

# A minimal-but-real PNG header (the byte sniff is what the
# service reads; the provider is stubbed, so the body past the
# header is never decoded here).
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Wizard User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def seeker(db):
    return _make_user(db, "TV-M-000711", "wizard@example.com")


def _configure_ai(db, monkeypatch, provider="openai", price_identify=None):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, provider)
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "WIZARD_TEST_AI_KEY")
    monkeypatch.setenv("WIZARD_TEST_AI_KEY", "sk-test-not-real")
    if price_identify is not None:
        entitlements.set_setting(
            db, ai_service.PRICE_KEYS["identify"], price_identify
        )
    db.commit()


def _chat_transport(payload, record=None):
    """OpenAI chat stub: replies with `payload` as JSON; when
    `record` (a list) is given, every request body is kept so
    the test can inspect exactly what the seam sent."""

    def transport(url, headers, body, timeout=None):
        if record is not None:
            record.append((url, body))
        if url.endswith("/responses"):
            return {"output": []}
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return transport


def _post_photo(client, user, data: bytes):
    return client.post(
        "/api/catalog/identify-photo",
        json={"image_base64": base64.b64encode(data).decode("ascii")},
        headers=auth_headers(user),
    )


# -- the seam: vision request construction ------------------------------------


def test_seam_openai_image_parts(db, monkeypatch):
    _configure_ai(db, monkeypatch, provider="openai")
    record = []
    monkeypatch.setattr(
        ai_service, "_transport", _chat_transport({"ok": True}, record)
    )
    out = ai_service.complete_json(
        db, "What is this?", image=("image/png", "QUJD")
    )
    assert out == {"ok": True}
    _, body = record[0]
    content = body["messages"][-1]["content"]
    assert content == [
        {"type": "text", "text": "What is this?"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,QUJD"},
        },
    ]


def test_seam_anthropic_image_block_and_text_scan(db, monkeypatch):
    _configure_ai(db, monkeypatch, provider="anthropic")

    def transport(url, headers, body, timeout=None):
        transport.body = body
        # A non-text block first: the reply reader takes the
        # first block that carries text, not position 0 blindly.
        return {
            "content": [
                {"type": "thinking", "thinking": "…"},
                {"type": "text", "text": '{"ok": true}'},
            ]
        }

    monkeypatch.setattr(ai_service, "_transport", transport)
    out = ai_service.complete_json(
        db, "What is this?", image=("image/jpeg", "REVG")
    )
    assert out == {"ok": True}
    content = transport.body["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": "What is this?"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "REVG",
            },
        },
    ]


def test_seam_text_only_shape_unchanged(db, monkeypatch):
    _configure_ai(db, monkeypatch, provider="openai")
    record = []
    monkeypatch.setattr(
        ai_service, "_transport", _chat_transport({"ok": True}, record)
    )
    ai_service.complete_json(db, "Plain prompt")
    _, body = record[0]
    assert body["messages"][-1] == {"role": "user", "content": "Plain prompt"}


# -- identify-photo: the route -------------------------------------------------


def test_identify_photo_happy_path_with_confidence(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {
                "name": "M18 FUEL 1/2 in Impact Wrench",
                "brand": "Milwaukee",
                "model": "2767-20",
                "category": "Impact Wrenches",
                "confidence": "high",
            }
        ),
    )
    resp = _post_photo(client, seeker, PNG_BYTES)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fields"]["brand"] == {
        "value": "Milwaukee",
        "source": "ai",
        "detail": "AI suggestion — check it",
    }
    assert body["fields"]["model"]["value"] == "2767-20"
    assert body["confidence"] == "high"
    assert body["ai_charged"] == 0  # prices default to 0 = free


def test_identify_photo_jpeg_and_name_echo_dropped(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {
                # The "name" merely restates the reply's own
                # model — dropped, like identify()'s rule.
                "name": "2767-20",
                "brand": "Milwaukee",
                "model": "2767-20",
                "category": "",
                "confidence": "medium",
            }
        ),
    )
    resp = _post_photo(client, seeker, JPEG_BYTES)
    assert resp.status_code == 200
    body = resp.json()
    assert "name" not in body["fields"]
    assert body["partial"] is True
    assert body["confidence"] == "medium"


def test_identify_photo_empty_answer_charges_nothing(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch, price_identify=5)
    wallet.credit(
        db, seeker.id, amount=10, bucket="banked", reason="test", ref="t"
    )
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {"name": "", "brand": "", "model": "", "category": "",
             "confidence": "low"}
        ),
    )
    resp = _post_photo(client, seeker, PNG_BYTES)
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"] == {}
    assert body["ai_charged"] == 0
    assert wallet.wallet_view(db, seeker.id)["banked_balance"] == 10


def test_identify_photo_charges_after_success_only(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch, price_identify=5)
    wallet.credit(
        db, seeker.id, amount=10, bucket="banked", reason="test", ref="t"
    )
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {"name": "Impact Wrench", "brand": "Milwaukee",
             "model": "2767-20", "category": "", "confidence": "high"}
        ),
    )
    resp = _post_photo(client, seeker, PNG_BYTES)
    assert resp.status_code == 200
    assert resp.json()["ai_charged"] == 5
    assert wallet.wallet_view(db, seeker.id)["banked_balance"] == 5


def test_identify_photo_provider_failure_is_502_and_free(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch, price_identify=5)
    wallet.credit(
        db, seeker.id, amount=10, bucket="banked", reason="test", ref="t"
    )

    def broken(url, headers, body, timeout=None):
        raise ai_service.AiProviderError("provider down")

    monkeypatch.setattr(ai_service, "_transport", broken)
    resp = _post_photo(client, seeker, PNG_BYTES)
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "ai_provider_error"
    assert wallet.wallet_view(db, seeker.id)["banked_balance"] == 10


def test_identify_photo_refuses_non_photos(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    monkeypatch.setattr(
        ai_service, "_transport", _chat_transport({"name": "x"})
    )
    resp = _post_photo(client, seeker, b"this is not a photo at all")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "photo_unreadable"
    # Not even valid base64.
    resp = client.post(
        "/api/catalog/identify-photo",
        json={"image_base64": "!!! not base64 !!!"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "photo_unreadable"


def test_identify_photo_oversized_refused_before_any_call(db, seeker):
    big = PNG_BYTES + b"\x00" * lookup._PHOTO_ID_MAX_BYTES
    with pytest.raises(lookup.PhotoUnreadable):
        lookup.identify_photo(db, seeker.id, big)


def test_identify_photo_dark_seam_is_503(client, seeker):
    resp = _post_photo(client, seeker, PNG_BYTES)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ai_not_configured"


# -- Job 4: entry AI is core, never behind the add-on --------------------------


def test_entry_ai_works_without_ai_assistant_entitlement(
    client, db, seeker, monkeypatch
):
    # The premise: a plain mechanic holds no ai_assistant
    # entitlement — the module is assigned to no group.
    assert (
        module_control.effective_for_user(
            db, "ai_assistant", seeker.account_types
        )
        is False
    )
    _configure_ai(db, monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {"name": "Impact Wrench", "brand": "Milwaukee",
             "model": "2767-20", "category": "", "confidence": "high"}
        ),
    )
    # …and every entry surface still answers for that mechanic.
    assert _post_photo(client, seeker, PNG_BYTES).status_code == 200
    resp = client.post(
        "/api/catalog/identify",
        json={"text": "milwaukee impact wrench 2767-20"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200
    resp = client.get(
        "/api/catalog/ai-status", headers=auth_headers(seeker)
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is True


def test_ai_assistant_module_repurposed_honestly():
    manifest = ai_manifest.manifest
    # Still registered, still assigned to nobody by default
    # (the future header ask bar's gate — nothing to sell or
    # block on until that feature exists)…
    assert manifest.name == "ai_assistant"
    assert manifest.default_groups == ()
    # …and its copy no longer dresses entry help up as the
    # add-on's contents: entry AI is "always included".
    assert "always included" in manifest.description
    assert "coming later" in manifest.description.lower()


# -- Job 3: description under the grounding discipline -------------------------

_JSONLD_PAGE = """
<html><head>
<title>Milwaukee 2767-20 M18 FUEL Impact Wrench</title>
<script type="application/ld+json">
{"@type": "Product",
 "name": "M18 FUEL 1/2 in High Torque Impact Wrench",
 "brand": {"@type": "Brand", "name": "Milwaukee"},
 "model": "2767-20",
 "description": "The M18 FUEL high torque impact wrench delivers 1000 ft-lbs of fastening torque in a compact cordless design."}
</script>
</head><body><h1>2767-20</h1></body></html>
"""

_META_PAGE = """
<html><head>
<title>Some Tool Page</title>
<meta name="description" content="A compact cordless impact wrench with 1000 ft-lbs of torque for heavy fastening work." />
</head><body><h1>2767-20</h1></body></html>
"""


def test_grounded_description_from_structured_record(db):
    page = grounded.parse_page(_JSONLD_PAGE, "https://example.com/p")
    fields, ai_used = grounded.extract_fields(db, page, "Milwaukee", "2767-20")
    assert ai_used is False  # seam dark: structured pass only
    assert fields["description"].startswith("The M18 FUEL high torque")
    assert fields["name"].startswith("M18 FUEL")


def test_grounded_description_from_meta_fallback(db):
    page = grounded.parse_page(_META_PAGE, "https://example.com/p")
    fields, _ = grounded.extract_fields(db, page, "", "")
    assert fields == {
        "description": (
            "A compact cordless impact wrench with 1000 ft-lbs of "
            "torque for heavy fastening work."
        )
    }


def test_grounded_ai_read_description_must_be_page_supported(
    db, monkeypatch
):
    _configure_ai(db, monkeypatch)
    page = grounded.parse_page(_JSONLD_PAGE, "https://example.com/p")
    # Wipe the structured description: the AI pass is the only
    # way a description could now arrive, and what it proposes
    # is NOT on the page — it must be dropped, not admitted.
    page["candidates"] = [
        {k: v for k, v in c.items() if k != "description"}
        for c in page["candidates"]
    ]
    page["meta_description"] = ""
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _chat_transport(
            {
                "description": (
                    "Forged from vibranium by dwarven smiths under "
                    "a blood moon, guaranteed to loosen any bolt "
                    "in the nine realms forever."
                )
            }
        ),
    )
    fields, ai_used = grounded.extract_fields(db, page, "Milwaukee", "2767-20")
    assert ai_used is True
    assert "description" not in fields


def test_chain_fills_description_from_grounded_page(db, seeker, monkeypatch):
    def fake_grounded(db_, *, brand="", model="", link=""):
        return {
            "fields": {
                "name": "M18 FUEL Impact Wrench",
                "description": "Delivers 1000 ft-lbs of fastening torque.",
            },
            "image_url": None,
            "source_name": "Milwaukee Tool",
            "source_url": "https://example.com/2767-20",
            "ai_used": False,
        }

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    result = lookup.run_lookup(db, seeker.id, brand="Milwaukee", model="2767-20")
    assert result["fields"]["description"] == {
        "value": "Delivers 1000 ft-lbs of fastening torque.",
        "source": "web",
        "detail": "Milwaukee Tool",
    }


# -- Job 5: the pattern table stays verified-only -------------------------------


def test_manual_patterns_verified_brands_only():
    assert manuals._pattern_urls("Milwaukee", "2767-20") == [
        "https://d3cacd5apmg13r.cloudfront.net/userfiles/ad/documents/"
        "milwaukee_2767_20_user_manual.pdf"
    ]
    # Probed 2026-11-07 and NOT composable from the model
    # alone (opaque document ids / dated portal paths), so
    # they stay on the search + mining tiers — no guesses.
    for brand, model in (
        ("DeWalt", "DCF891B"),
        ("Makita", "XDT16"),
        ("Bosch", "GSB18V-535C"),
        ("Ryobi", "PCL206"),
        ("Klein", "32500"),
        ("Snap-on", "QD3R250"),
    ):
        assert manuals._pattern_urls(brand, model) == []
