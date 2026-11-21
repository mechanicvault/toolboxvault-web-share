"""Page layouts (owner directive 2026-10-17): each user arranges the
blocks on each page — which show, in what order — and the layout is
stored per account, server-side.

The server is a deliberately dumb store: block keys are opaque (the
page registries live in the frontend), so these tests pin the storage
contract — owner scoping, wholesale replace, dedupe by key (first
wins), the 50-block cap, and "no row = empty list = client defaults".
"""

import pytest

from app.modules.core import models as core_models
from app.modules.core import service
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _layouts_table(db):
    # The shared conftest creates only the long-standing tables; this
    # module's table is created here so the fixture list stays put.
    core_models.UserPageLayout.__table__.create(
        bind=db.get_bind(), checkfirst=True
    )


def _blocks(*pairs: tuple[str, bool]) -> list[dict]:
    return [{"key": k, "visible": v} for k, v in pairs]


# -- auth + defaults ----------------------------------------------------------


def test_get_layout_requires_auth(client):
    assert client.get("/api/core/layouts/home").status_code == 401


def test_put_layout_requires_auth(client):
    resp = client.put("/api/core/layouts/home", json={"blocks": []})
    assert resp.status_code == 401


def test_get_layout_default_is_empty_blocks(client, user_a):
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_a))
    assert resp.status_code == 200
    # Empty blocks = never customized; the client renders page defaults.
    assert resp.json() == {"page_key": "home", "blocks": []}


def test_bad_page_key_is_422(client, user_a):
    resp = client.get("/api/core/layouts/BadKey", headers=auth_headers(user_a))
    assert resp.status_code == 422


# -- round trip ----------------------------------------------------------------


def test_put_get_round_trip_preserves_order_and_visibility(client, user_a):
    saved = _blocks(("modules", True), ("overview", False), ("notifications", True))
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": saved}, headers=auth_headers(user_a)
    )
    assert resp.status_code == 200
    assert resp.json() == {"page_key": "home", "blocks": saved}

    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_a))
    assert resp.json() == {"page_key": "home", "blocks": saved}


def test_put_replaces_wholesale(client, user_a):
    headers = auth_headers(user_a)
    client.put(
        "/api/core/layouts/home",
        json={"blocks": _blocks(("overview", True), ("modules", True))},
        headers=headers,
    )
    client.put(
        "/api/core/layouts/home",
        json={"blocks": _blocks(("notifications", True))},
        headers=headers,
    )
    resp = client.get("/api/core/layouts/home", headers=headers)
    assert resp.json()["blocks"] == _blocks(("notifications", True))


def test_pages_are_independent(client, user_a):
    headers = auth_headers(user_a)
    client.put(
        "/api/core/layouts/home", json={"blocks": _blocks(("a", True))}, headers=headers
    )
    client.put(
        "/api/core/layouts/inventory",
        json={"blocks": _blocks(("b", False))},
        headers=headers,
    )
    assert client.get("/api/core/layouts/home", headers=headers).json()["blocks"] == _blocks(("a", True))
    assert client.get("/api/core/layouts/inventory", headers=headers).json()["blocks"] == _blocks(("b", False))


# -- owner scoping --------------------------------------------------------------


def test_layout_is_owner_scoped(client, user_a, user_b):
    client.put(
        "/api/core/layouts/home",
        json={"blocks": _blocks(("overview", False))},
        headers=auth_headers(user_a),
    )
    # B never customized: default, not A's layout.
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_b))
    assert resp.json()["blocks"] == []

    client.put(
        "/api/core/layouts/home",
        json={"blocks": _blocks(("modules", False))},
        headers=auth_headers(user_b),
    )
    # B's save does not touch A's.
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_a))
    assert resp.json()["blocks"] == _blocks(("overview", False))


# -- dedupe + cap -----------------------------------------------------------------


def test_put_dedupes_by_key_first_wins(client, user_a):
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": _blocks(("a", True), ("a", False), ("b", True))},
        headers=auth_headers(user_a),
    )
    assert resp.json()["blocks"] == _blocks(("a", True), ("b", True))


def test_put_caps_at_fifty_blocks(client, user_a):
    many = [{"key": f"block-{i}", "visible": True} for i in range(60)]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": many}, headers=auth_headers(user_a)
    )
    stored = resp.json()["blocks"]
    assert len(stored) == service.MAX_LAYOUT_BLOCKS == 50
    assert stored[0]["key"] == "block-0"
    assert stored[-1]["key"] == "block-49"


def test_put_rejects_malformed_blocks(client, user_a):
    headers = auth_headers(user_a)
    # Missing key.
    assert (
        client.put(
            "/api/core/layouts/home", json={"blocks": [{"visible": True}]}, headers=headers
        ).status_code
        == 422
    )
    # Empty key.
    assert (
        client.put(
            "/api/core/layouts/home",
            json={"blocks": [{"key": "", "visible": True}]},
            headers=headers,
        ).status_code
        == 422
    )
    # Blocks not a list.
    assert (
        client.put(
            "/api/core/layouts/home", json={"blocks": "overview"}, headers=headers
        ).status_code
        == 422
    )


# -- service level ------------------------------------------------------------------


def test_service_get_is_none_before_first_save(db, user_a):
    assert service.get_page_layout(db, user_a.id, "home") is None
    stored = service.save_page_layout(db, user_a.id, "home", _blocks(("x", False)))
    assert stored == _blocks(("x", False))
    assert service.get_page_layout(db, user_a.id, "home") == stored


# -- hidden stats (owner review round 1, 2026-10-19) ---------------------------
# The overview block's per-stat show/hide choices ride inside its
# layout entry as `hidden_stats`. Absent = nothing hidden, and the
# field must not appear in payloads at all (older clients/tests
# compare block dicts exactly).


def test_hidden_stats_round_trip(client, user_a):
    headers = auth_headers(user_a)
    blocks = [
        {
            "key": "overview",
            "visible": True,
            "hidden_stats": ["inventory.total_items", "claims.open_claims"],
        },
        {"key": "modules", "visible": True},
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=headers)
    assert resp.json()["blocks"] == blocks


def test_hidden_stats_omitted_when_never_set(client, user_a):
    headers = auth_headers(user_a)
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "overview", "visible": True}]},
        headers=headers,
    )
    assert resp.json()["blocks"] == [{"key": "overview", "visible": True}]
    assert "hidden_stats" not in resp.json()["blocks"][0]


def test_hidden_stats_sanitized_by_service(db, user_a):
    stored = service.save_page_layout(
        db,
        user_a.id,
        "home",
        [
            {
                "key": "overview",
                "visible": True,
                # Duplicates collapse, non-strings and empties drop.
                "hidden_stats": ["a.b", "a.b", "", 7, None, "c.d"],
            },
            # An empty list stores nothing (the field stays absent).
            {"key": "modules", "visible": True, "hidden_stats": []},
        ],
    )
    assert stored == [
        {"key": "overview", "visible": True, "hidden_stats": ["a.b", "c.d"]},
        {"key": "modules", "visible": True},
    ]


def test_hidden_stats_item_too_long_is_422(client, user_a):
    resp = client.put(
        "/api/core/layouts/home",
        json={
            "blocks": [
                {"key": "overview", "visible": True, "hidden_stats": ["x" * 101]}
            ]
        },
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422


# -- per-stat order (Home + Header program, 2026-10-24) -----------------------
# The overview block's per-stat display ORDER rides its layout
# entry as `order`, under the same contract as hidden_stats:
# opaque keys, sanitized by the service, absent when never set.


def test_order_round_trip(client, user_a):
    headers = auth_headers(user_a)
    blocks = [
        {
            "key": "overview",
            "visible": True,
            "order": ["claims.open_claims", "inventory.total_items"],
        },
        {"key": "widget:borrowing", "visible": False},
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=headers)
    assert resp.json()["blocks"] == blocks


def test_order_omitted_when_never_set(client, user_a):
    headers = auth_headers(user_a)
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "overview", "visible": True}]},
        headers=headers,
    )
    assert resp.json()["blocks"] == [{"key": "overview", "visible": True}]
    assert "order" not in resp.json()["blocks"][0]


def test_order_sanitized_by_service(db, user_a):
    stored = service.save_page_layout(
        db,
        user_a.id,
        "home",
        [
            {
                "key": "overview",
                "visible": True,
                "order": ["a.b", "a.b", "", 7, None, "c.d"],
            },
            {"key": "modules", "visible": True, "order": []},
        ],
    )
    assert stored[0]["order"] == ["a.b", "c.d"]
    assert "order" not in stored[1]


# -- Home panel pseudo-entry extras (Phase C, 2026-10-24) ---------------------
# The Home side panel's customization rides the SAME home layout
# payload as a pseudo-entry {key: "panel", visible: True} carrying
# `panel_hidden` + `panel_order`, under the same contract as the
# other extras: opaque keys, sanitized, absent when never set.


def test_panel_extras_round_trip(client, user_a):
    headers = auth_headers(user_a)
    blocks = [
        {"key": "overview", "visible": True},
        {
            "key": "panel",
            "visible": True,
            "panel_hidden": ["utility"],
            "panel_order": ["stats", "account", "utility"],
        },
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=headers)
    assert resp.json()["blocks"] == blocks


def test_panel_extras_omitted_when_never_set(client, user_a):
    headers = auth_headers(user_a)
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "panel", "visible": True}]},
        headers=headers,
    )
    assert resp.json()["blocks"] == [{"key": "panel", "visible": True}]
    assert "panel_hidden" not in resp.json()["blocks"][0]
    assert "panel_order" not in resp.json()["blocks"][0]


def test_panel_extras_sanitized_by_service(db, user_a):
    stored = service.save_page_layout(
        db,
        user_a.id,
        "home",
        [
            {
                "key": "panel",
                "visible": True,
                "panel_hidden": ["utility", "utility", "", 7, None],
                "panel_order": ["stats", "stats", "", "account"],
            },
            {"key": "overview", "visible": True, "panel_hidden": []},
        ],
    )
    assert stored[0]["panel_hidden"] == ["utility"]
    assert stored[0]["panel_order"] == ["stats", "account"]
    assert "panel_hidden" not in stored[1]


def test_panel_stat_order_round_trip_and_empty_is_kept(client, user_a):
    # Phase 3: the stat pick list round-trips — and an EMPTY
    # list is a real saved choice (the user removed every row),
    # not "never customized".
    headers = auth_headers(user_a)
    blocks = [
        {"key": "overview", "visible": True},
        {
            "key": "panel",
            "visible": True,
            "panel_stat_order": ["support.open_tickets", "inventory.total_items"],
        },
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=headers)
    assert resp.json()["blocks"] == blocks

    emptied = [
        {"key": "overview", "visible": True},
        {"key": "panel", "visible": True, "panel_stat_order": []},
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": emptied}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["blocks"][1]["panel_stat_order"] == []
    resp = client.get("/api/core/layouts/home", headers=headers)
    assert resp.json()["blocks"][1]["panel_stat_order"] == []


def test_panel_stat_order_omitted_when_never_set(client, user_a):
    headers = auth_headers(user_a)
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "panel", "visible": True}]},
        headers=headers,
    )
    assert "panel_stat_order" not in resp.json()["blocks"][0]


def test_panel_stat_order_sanitized_by_service(db, user_a):
    stored = service.save_page_layout(
        db,
        user_a.id,
        "home",
        [
            {
                "key": "panel",
                "visible": True,
                "panel_stat_order": [
                    "support.open_tickets",
                    "support.open_tickets",
                    "",
                    7,
                    None,
                    "claims.open_claims",
                ],
            }
        ],
    )
    assert stored[0]["panel_stat_order"] == [
        "support.open_tickets",
        "claims.open_claims",
    ]


def test_panel_extras_item_too_long_is_422(client, user_a):
    resp = client.put(
        "/api/core/layouts/home",
        json={
            "blocks": [
                {"key": "panel", "visible": True, "panel_order": ["x" * 101]}
            ]
        },
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422


def test_full_home_save_round_trips_every_field_and_stays_owner_scoped(
    client, user_a, user_b
):
    # Owner bug report, 2026-10-24: one real Home save carries
    # EVERY field family at once — widget visibility/order, the
    # overview block's hidden stats + stat order, and the panel
    # entry's hidden sections + section order + stat picks. The
    # per-field tests above pin each family alone; this pins
    # the combined payload byte-for-byte (a field dropped only
    # in combination is exactly the failure the owner saw) and
    # re-pins isolation against the full shape.
    headers_a = auth_headers(user_a)
    blocks = [
        {
            "key": "overview",
            "visible": True,
            "hidden_stats": ["replacement"],
            "order": ["tools", "value", "categories"],
        },
        {"key": "widget:inventory", "visible": False},
        {"key": "widget:borrowing", "visible": True},
        {
            "key": "panel",
            "visible": True,
            "panel_hidden": ["utility"],
            "panel_order": ["stats", "account"],
            "panel_stat_order": ["support.open_tickets", "claims.open"],
        },
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=headers_a
    )
    assert resp.status_code == 200
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=headers_a)
    assert resp.json()["blocks"] == blocks

    # The other account's Home is untouched: no row, defaults.
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_b))
    assert resp.json() == {"page_key": "home", "blocks": []}


# -- block size + settings (widget options Wave 1, 2026-11-02) -----------------
#
# Every Home block gains two framework extras: `size` (its grid
# width, a closed pair) and `settings` (the widget's own options
# bundle — a flat document of leaf values). The server stays a
# dumb, safe store: size is validated at the schema door, and
# settings pass the service's field-by-field sanitizer before
# anything is stored. Absent fields stay absent — a layout saved
# before this wave round-trips byte-identically.


def test_block_size_round_trips_and_absence_stays_absent(client, user_a):
    blocks = [
        {"key": "overview", "visible": True, "size": "half"},
        {"key": "widget:inventory", "visible": True, "size": "full"},
        {"key": "notifications", "visible": True},
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=auth_headers(user_a)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_a))
    assert resp.json()["blocks"] == blocks


def test_block_size_outside_the_pair_is_refused_at_the_door(client, user_a):
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "overview", "visible": True, "size": "third"}]},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_a))
    assert resp.json() == {"page_key": "home", "blocks": []}


def test_block_settings_round_trip_leaf_values(client, user_a):
    settings = {
        "show_button": True,
        "rows": 3,
        "ratio": 1.5,
        "label": "Shop",
        "hidden_sections": ["route", "payments"],
    }
    blocks = [{"key": "widget:claims", "visible": True, "settings": settings}]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=auth_headers(user_a)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocks"] == blocks
    resp = client.get("/api/core/layouts/home", headers=auth_headers(user_a))
    assert resp.json()["blocks"] == blocks


def test_block_settings_sanitizer_drops_junk_and_bounds_values(client, user_a):
    blocks = [
        {
            "key": "widget:claims",
            "visible": True,
            "settings": {
                # A nested document is not a leaf value, and
                # None is absence, not a value: both drop, and
                # with them the whole bundle (nothing survives,
                # so no settings key is stored at all).
                "nested": {"a": 1},
                "cleared": None,
            },
        },
        {
            "key": "widget:borrowing",
            "visible": True,
            "settings": {
                "long_label": "x" * 250,
                "names": ["a", 5, "a", "", "b"],
            },
        },
    ]
    resp = client.put(
        "/api/core/layouts/home", json={"blocks": blocks}, headers=auth_headers(user_a)
    )
    assert resp.status_code == 200, resp.text
    stored = resp.json()["blocks"]
    assert stored[0] == {"key": "widget:claims", "visible": True}
    assert stored[1]["settings"] == {"long_label": "x" * 200, "names": ["a", "b"]}


def test_block_settings_document_bounds_are_refused_at_the_door(client, user_a):
    too_many = {f"k{i}": i for i in range(33)}
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "overview", "visible": True, "settings": too_many}]},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text
    long_key = {"k" * 65: 1}
    resp = client.put(
        "/api/core/layouts/home",
        json={"blocks": [{"key": "overview", "visible": True, "settings": long_key}]},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text


def test_sanitize_block_settings_drops_non_finite_numbers():
    cleaned = service._sanitize_block_settings(
        {"nan": float("nan"), "inf": float("inf"), "ok": 2, "flag": True}
    )
    assert cleaned == {"ok": 2, "flag": True}
