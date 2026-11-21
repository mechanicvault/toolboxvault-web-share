"""AI toolbox drawer autofill (owner spec, 2026-10-25).

Pins the honesty contract:
  - dark seam -> 503 {code: ai_not_configured} and the AI
    transport is never dialed;
  - a well-formed, sourced answer comes back with its count,
    its source, and its (cleaned) extra sections, and the
    wallet is charged once at the operator's drawer price,
    allowance first;
  - anything malformed, sourceless, out of range, or
    self-declared not-found is a plain found=false and charges
    NOTHING;
  - a found answer the wallet can't pay for -> 402
    {code: insufficient_credits};
  - a provider failure -> 502 {code: ai_provider_error};
  - the admin settings roundtrip covers the new price key.
"""

import json
import uuid

import pytest

from app.modules.billing import ai_service, entitlements, wallet
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
URL = "/api/inventory/location-tree/drawer-lookup"


def _make_user(db, account_number, email, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Drawer User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def seeker(db):
    return _make_user(db, "TV-M-000511", "drawers@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000519", "op-drawers@example.com", operator=True)


def _configure_ai(db, monkeypatch, price=None):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "DRAWER_TEST_AI_KEY")
    monkeypatch.setenv("DRAWER_TEST_AI_KEY", "sk-test-not-real")
    if price is not None:
        entitlements.set_setting(db, ai_service.PRICE_KEYS["drawer_lookup"], price)
    db.commit()


def _fake_transport(payload):
    """Chat stub for the recall path. Search calls (the
    grounded layer now rides the same AI door and always
    probes first) are answered with a citation-less Responses
    body — the search ran and found nothing to fetch — and
    recorded apart, so `calls` still counts recall dials."""

    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            transport.search_calls.append((url, body))
            return {"output": []}
        transport.calls.append((url, body))
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    transport.calls = []
    transport.search_calls = []
    return transport


def _lookup(client, user, query="Snap-on KRL1033"):
    return client.post(URL, json={"query": query}, headers=auth_headers(user))


def test_dark_seam_503_and_never_dialed(client, db, seeker, monkeypatch):
    called = []
    monkeypatch.setattr(
        ai_service, "_transport", lambda *a, **k: called.append(1) or {}
    )
    resp = _lookup(client, seeker)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ai_not_configured"
    assert called == []


def test_found_answer_charges_once_allowance_first(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch, price=2)
    wallet.credit(
        db, seeker.id, amount=1, bucket="allowance", reason="test", ref="t"
    )
    wallet.credit(db, seeker.id, amount=5, bucket="banked", reason="test", ref="t")
    transport = _fake_transport(
        {
            "found": True,
            "drawer_count": 13,
            "source": "Snap-on official product page — KRL1033",
            "extra_sections": ["Top till", "Top till", "", 42, " Side locker "],
        }
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = _lookup(client, seeker)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is True
    assert body["drawer_count"] == 13
    assert body["source"] == "Snap-on official product page — KRL1033"
    # Sections are cleaned: deduped, trimmed, strings only.
    assert body["extra_sections"] == ["Top till", "Side locker"]
    assert body["charged"] == 2
    assert len(transport.calls) == 1
    view = wallet.wallet_view(db, seeker.id)
    # Allowance (1) drained first, the rest (1) from banked.
    assert view["allowance_balance"] == 0
    assert view["banked_balance"] == 4


def test_action_model_override_reaches_the_provider(
    client, db, seeker, monkeypatch
):
    """The drawer action rides its own operator model when one
    is set (factual recall is where the mini site model declines
    or misremembers), and the site model when it is not."""
    _configure_ai(db, monkeypatch)
    payload = {
        "found": True,
        "drawer_count": 13,
        "source": "Snap-on official product page — KRL1033",
        "extra_sections": [],
    }
    entitlements.set_setting(
        db, ai_service.MODEL_KEYS["drawer_lookup"], "gpt-strong"
    )
    db.commit()
    transport = _fake_transport(payload)
    monkeypatch.setattr(ai_service, "_transport", transport)
    assert _lookup(client, seeker).status_code == 200
    assert transport.calls[0][1]["model"] == "gpt-strong"
    # Factual recall is pinned deterministic (temperature 0):
    # at the provider default the same box drew 13, 15, and 17
    # across calls; the seam default (no key at all) is pinned
    # by test_complete_without_temperature_omits_the_key.
    assert transport.calls[0][1]["temperature"] == 0

    entitlements.set_setting(db, ai_service.MODEL_KEYS["drawer_lookup"], "")
    db.commit()
    transport2 = _fake_transport(payload)
    monkeypatch.setattr(ai_service, "_transport", transport2)
    assert _lookup(client, seeker).status_code == 200
    assert transport2.calls[0][1]["model"] == "test-model"


def test_complete_without_temperature_omits_the_key(db, monkeypatch):
    """Every other AI consumer keeps the provider default: the
    seam adds no temperature key unless a caller asks for one."""
    _configure_ai(db, monkeypatch)
    transport = _fake_transport({})
    monkeypatch.setattr(ai_service, "_transport", transport)
    ai_service.complete(db, "hello")
    assert "temperature" not in transport.calls[0][1]


def test_not_found_reply_is_free(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch, price=2)
    wallet.credit(db, seeker.id, amount=5, bucket="banked", reason="test", ref="t")
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _fake_transport(
            {"found": False, "drawer_count": None, "source": "", "extra_sections": []}
        ),
    )
    resp = _lookup(client, seeker, query="Faketool XZ-9000")
    assert resp.status_code == 200
    body = resp.json()
    # The grounded-rework response shape (2026-10-25): a miss is
    # still a miss — no count, no source, no configurations, no
    # charge — now with the grounded/link flags riding along.
    assert body == {
        "found": False,
        "grounded": False,
        "drawer_count": None,
        "source": None,
        "source_url": None,
        "configurations": [],
        "extra_sections": [],
        "link_error": False,
        "charged": 0,
    }
    assert wallet.wallet_view(db, seeker.id)["total_balance"] == 5


@pytest.mark.parametrize(
    "payload",
    [
        # Sourceless: a count with no named source is a guess.
        {"found": True, "drawer_count": 13, "source": "", "extra_sections": []},
        {"found": True, "drawer_count": 13, "extra_sections": []},
        # Out-of-range counts are hallucinations, not specs.
        {"found": True, "drawer_count": 0, "source": "Some blog", "extra_sections": []},
        {
            "found": True,
            "drawer_count": 400,
            "source": "Some blog",
            "extra_sections": [],
        },
        # Wrong types never coerce into a find.
        {
            "found": True,
            "drawer_count": "13",
            "source": "Some blog",
            "extra_sections": [],
        },
        {
            "found": True,
            "drawer_count": True,
            "source": "Some blog",
            "extra_sections": [],
        },
        {
            "found": True,
            "drawer_count": 13.5,
            "source": "Some blog",
            "extra_sections": [],
        },
        # A truthy non-boolean found flag is not certainty.
        {
            "found": "yes",
            "drawer_count": 13,
            "source": "Some blog",
            "extra_sections": [],
        },
    ],
)
def test_malformed_or_sourceless_is_not_found_and_free(
    client, db, seeker, monkeypatch, payload
):
    _configure_ai(db, monkeypatch, price=2)
    wallet.credit(db, seeker.id, amount=5, bucket="banked", reason="test", ref="t")
    monkeypatch.setattr(ai_service, "_transport", _fake_transport(payload))
    resp = _lookup(client, seeker)
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["drawer_count"] is None
    assert body["charged"] == 0
    assert wallet.wallet_view(db, seeker.id)["total_balance"] == 5


def test_integral_float_count_is_accepted(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _fake_transport(
            {
                "found": True,
                "drawer_count": 7.0,
                "source": "Matco official catalog",
                "extra_sections": [],
            }
        ),
    )
    resp = _lookup(client, seeker, query="Matco JSC773")
    assert resp.status_code == 200
    assert resp.json()["drawer_count"] == 7


def test_found_but_broke_is_402(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch, price=3)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _fake_transport(
            {
                "found": True,
                "drawer_count": 13,
                "source": "Snap-on official product page — KRL1033",
                "extra_sections": [],
            }
        ),
    )
    resp = _lookup(client, seeker)
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == "insufficient_credits"


def test_provider_failure_is_502(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch, price=2)

    def boom(url, headers, body, timeout=None):
        raise ai_service.AiProviderError("down")

    monkeypatch.setattr(ai_service, "_transport", boom)
    resp = _lookup(client, seeker)
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "ai_provider_error"


def test_unparsable_reply_is_502(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)

    def garbage(url, headers, body, timeout=None):
        return {"choices": [{"message": {"content": "thirteen, probably"}}]}

    monkeypatch.setattr(ai_service, "_transport", garbage)
    resp = _lookup(client, seeker)
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "ai_provider_error"


def test_free_by_default_no_price_set(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)  # no price: operator default 0 = free
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _fake_transport(
            {
                "found": True,
                "drawer_count": 4,
                "source": "Craftsman product page",
                "extra_sections": [],
            }
        ),
    )
    resp = _lookup(client, seeker, query="Craftsman 4-drawer chest")
    assert resp.status_code == 200
    assert resp.json()["charged"] == 0


def test_admin_settings_roundtrip_drawer_price(client, db, operator):
    resp = client.put(
        "/api/admin/settings",
        json={"ai_price_drawer_lookup": 4},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ai"]["prices"]["drawer_lookup"] == 4
    assert ai_service.price_for(db, "drawer_lookup") == 4


# -- grounded rework (2026-10-25) ---------------------------------------------
# Configurations read off a REAL product page (the grounded
# pipe) beat AI recall; recall survives only as a single,
# unverified-flagged configuration. A pasted link reads that
# page and needs no search key; an unreadable link is an
# honest link_error, never a guess.

from app.modules.catalog import grounded, manuals  # noqa: E402

_MULTI_PAGE = """
<html><head><title>Acme TBX-9 Rolling Cabinet</title></head>
<body><h1>Acme TBX-9 Rolling Cabinet</h1>
<p>The TBX-9 is sold in two factory configurations: a 10 drawer
layout for tight bays, and a 19 drawer layout with a top till
for full shops.</p></body></html>
"""

_SINGLE_PAGE = """
<html><head><title>Acme 13 Drawer Roll Cab CR-13</title></head>
<body><h1>Acme CR-13</h1><p>A sturdy roll cab.</p></body></html>
"""


def _stub_public_dns(monkeypatch):
    monkeypatch.setattr(manuals, "_host_ips", lambda host: ["93.184.216.34"])


def _stub_pages(monkeypatch, pages):
    def fetch(url):
        if url in pages:
            return pages[url]
        raise grounded.PageFetchError("Couldn't reach that page.")

    monkeypatch.setattr(grounded, "_fetch_html", fetch)


def _config_transport(configs, search_results=None):
    """An AI stub for both seam endpoints: /responses (the web
    search — it rides the same AI door since the one-vendor
    decision) replays the canned citations; chat completions
    answer the configuration-extraction prompt with `configs`
    and anything else with a not-found."""

    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            transport.search_calls.append(body)
            annotations = [
                {
                    "type": "url_citation",
                    "url": result["url"],
                    "title": result.get("title", ""),
                }
                for result in (search_results or [])
            ]
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Found it.",
                                "annotations": annotations,
                            }
                        ],
                    }
                ]
            }
        prompt = body["messages"][-1]["content"]
        if "CONFIGURATIONS" in prompt:
            payload = {"configurations": configs}
        else:
            payload = {
                "found": False,
                "drawer_count": None,
                "source": "",
                "extra_sections": [],
            }
        transport.calls.append(body)
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    transport.calls = []
    transport.search_calls = []
    return transport


def test_recall_answer_is_flagged_unverified_with_one_configuration(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _fake_transport(
            {
                "found": True,
                "drawer_count": 13,
                "source": "Snap-on official product page — KRL1033",
                "extra_sections": ["Top till"],
            }
        ),
    )
    body = _lookup(client, seeker).json()
    assert body["found"] is True
    assert body["grounded"] is False  # recall: the UI labels it unverified
    assert body["source_url"] is None
    assert body["configurations"] == [
        {"drawer_count": 13, "extra_sections": ["Top till"]}
    ]


def test_grounded_multi_configuration_from_a_page(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch, price=2)
    _stub_public_dns(monkeypatch)
    wallet.credit(db, seeker.id, amount=5, bucket="banked", reason="test", ref="t")
    _stub_pages(monkeypatch, {"https://acme.example.com/tbx9": _MULTI_PAGE})
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _config_transport(
            [
                {"drawer_count": 10, "extra_sections": []},
                {"drawer_count": 19, "extra_sections": ["Top till"]},
                # Not on the page — the validator must drop it.
                {"drawer_count": 42, "extra_sections": []},
            ],
            search_results=[
                {"title": "TBX-9", "url": "https://acme.example.com/tbx9"}
            ],
        ),
    )
    resp = client.post(
        URL, json={"model": "Acme TBX-9"}, headers=auth_headers(seeker)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is True
    assert body["grounded"] is True
    assert body["source"] == "acme.example.com"
    assert body["source_url"] == "https://acme.example.com/tbx9"
    assert body["configurations"] == [
        {"drawer_count": 10, "extra_sections": []},
        {"drawer_count": 19, "extra_sections": ["Top till"]},
    ]
    # Several configurations: no single legacy count is picked.
    assert body["drawer_count"] is None
    assert body["charged"] == 2


def test_grounded_single_configuration_from_the_pages_own_title(
    client, db, seeker, monkeypatch
):
    """Even with nothing useful from the AI pass, a count the
    page states in the product's name is a grounded find."""
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {"https://acme.example.com/cr13": _SINGLE_PAGE})
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _config_transport(
            [],
            search_results=[
                {"title": "CR-13", "url": "https://acme.example.com/cr13"}
            ],
        ),
    )
    resp = client.post(
        URL, json={"model": "Acme CR-13"}, headers=auth_headers(seeker)
    )
    body = resp.json()
    assert body["found"] is True
    assert body["grounded"] is True
    assert body["drawer_count"] == 13
    assert body["configurations"] == [{"drawer_count": 13, "extra_sections": []}]


def test_link_mode_reads_the_pasted_page_without_any_search(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch)
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {"https://acme.example.com/tbx9": _MULTI_PAGE})
    monkeypatch.setattr(
        ai_service,
        "_transport",
        _config_transport(
            [
                {"drawer_count": 10, "extra_sections": []},
                {"drawer_count": 19, "extra_sections": ["Top till"]},
            ]
        ),
    )
    resp = client.post(
        URL,
        json={"model": "Acme TBX-9", "link": "https://acme.example.com/tbx9"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["found"] is True
    assert body["grounded"] is True
    assert [c["drawer_count"] for c in body["configurations"]] == [10, 19]


def test_unreadable_link_is_an_honest_link_error_and_free(
    client, db, seeker, monkeypatch
):
    _configure_ai(db, monkeypatch, price=2)
    wallet.credit(db, seeker.id, amount=5, bucket="banked", reason="test", ref="t")
    _stub_public_dns(monkeypatch)
    _stub_pages(monkeypatch, {})
    resp = client.post(
        URL,
        json={"model": "Acme TBX-9", "link": "https://acme.example.com/gone"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["link_error"] is True
    assert body["charged"] == 0
    assert wallet.wallet_view(db, seeker.id)["total_balance"] == 5
