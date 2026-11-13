"""Tool Expansion (owner spec 2026-10-25): known addons for the
tools and sets a user already owns, learned across all users by
model-number matching.

Pins:
  - set-to-set: the same set model on both sides → the source's
    ADDON pieces (rows + attached tools) I don't own are suggested
    to me, tied to my set — core pieces are not (they came WITH
    the set; membership is their flavor);
  - membership: a model number I own showing up as a piece inside
    someone else's set → that set's other pieces are suggested,
    tied to my item (standalone tool, battery, or set);
  - never suggest a model number the viewer already owns anywhere
    (standalone, pieces, attached — all of it);
  - PRIVACY: the payload carries only the suggested piece's name
    + model number and the viewer's own item — a recursive walk
    finds no owner identity, no serials, no prices, no photos, no
    notes, and no source user's id/email anywhere in the values;
  - the pool is the catalog's pool: contribution OFF feeds
    nothing, effective immediately (derived at read time);
  - dismissal is per user + per item; a report hides the match
    for the reporter at once, and at 3 DISTINCT reporters the
    match dies for everyone (a repeat report from one user counts
    once);
  - the module doorway matches its groups (mechanic + shop;
    dealer-only and group-less accounts get module_unavailable).
"""

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, types, *, contribute=True):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Expansion User",
        password_hash="not-a-real-hash",
        account_types=types,
        catalog_contribute=contribute,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def source(db):
    return _make_user(db, "TV-M-001001", "source@example.com", [MECHANIC])


@pytest.fixture()
def viewer(db):
    return _make_user(db, "TV-M-001002", "viewer@example.com", [MECHANIC])


@pytest.fixture()
def third(db):
    # A mechanic+shop UNION account: inventory itself seeds
    # mechanic-only (shop access rides the union), and the union
    # must still see the module exactly once.
    return _make_user(db, "TV-S-001003", "third@example.com", [MECHANIC, SHOP])


@pytest.fixture()
def fourth(db):
    return _make_user(db, "TV-M-001004", "fourth@example.com", [MECHANIC])


def _add_tool(client, user, **overrides):
    payload = {"name": "Plain tool", "brand": "Acme", "model": "AT-1"}
    payload.update(overrides)
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_set(client, user, *, name="Socket set", model="SS-100", pieces=()):
    return _add_tool(
        client,
        user,
        name=name,
        model=model,
        is_set=True,
        pieces=list(pieces),
    )


def _piece(kind, name, part_number):
    return {"kind": kind, "name": name, "part_number": part_number}


def _addons(prefix, count, start=1):
    return [
        _piece("addon", f"{prefix} socket {n}", f"{prefix}-{n}")
        for n in range(start, start + count)
    ]


def _suggestions(client, user, **params):
    resp = client.get(
        "/api/tool-expansion/suggestions",
        params=params,
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _suggested_models(payload):
    return {
        s["suggested_model"]
        for group in payload["groups"]
        for s in group["suggestions"]
    }


def _seed_socket_world(client, source):
    """The owner's example: source owns the 10-piece socket set
    (model SS-100) plus 5 addon sockets for it."""
    _add_set(
        client,
        source,
        pieces=[
            *[_piece("core", f"Core socket {n}", f"C-{n}") for n in range(1, 11)],
            *_addons("AD", 5),
        ],
    )


# -- the two flavors ---------------------------------------------------------


def test_set_to_set_suggests_source_addons(client, source, viewer):
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)  # same set model, no addons recorded

    payload = _suggestions(client, viewer)
    assert payload["total"] == 5
    assert _suggested_models(payload) == {f"ad-{n}" for n in range(1, 6)}
    group = payload["groups"][0]
    assert group["item"]["id"] == mine["id"]
    assert group["item"]["is_set"] is True
    first = group["suggestions"][0]
    assert first["name"] == "AD socket 1"
    assert first["model_number"] == "AD-1"
    assert first["anchor_model"] == "ss-100"


def test_set_to_set_via_attached_tool_addons(client, source, viewer):
    """A tool folded into the source's set is an addon piece too."""
    _add_set(client, source, pieces=[_piece("core", "Core socket 1", "C-1")])
    loose = _add_tool(client, source, name="Deep socket", model="DEEP-9")
    source_set = client.get(
        "/api/inventory", headers=auth_headers(source)
    ).json()
    set_id = next(t["id"] for t in source_set if t["is_set"])
    resp = client.put(
        f"/api/inventory/{set_id}",
        json={"attach_tool_ids": [loose["id"]]},
        headers=auth_headers(source),
    )
    assert resp.status_code == 200, resp.text

    _add_set(client, viewer)
    payload = _suggestions(client, viewer)
    assert _suggested_models(payload) == {"deep-9"}
    assert payload["groups"][0]["suggestions"][0]["name"] == "Deep socket"


def test_membership_from_standalone_tool(client, source, viewer):
    _add_set(
        client,
        source,
        model="MS-7",
        pieces=[
            _piece("core", "Ratchet", "M-1"),
            _piece("core", "Extension", "M-2"),
            _piece("addon", "Swivel", "M-3"),
        ],
    )
    mine = _add_tool(client, viewer, name="My ratchet", model="M-1")

    payload = _suggestions(client, viewer)
    assert _suggested_models(payload) == {"m-2", "m-3"}
    group = payload["groups"][0]
    assert group["item"]["id"] == mine["id"]
    assert group["suggestions"][0]["anchor_model"] == "m-1"


def test_membership_from_battery_and_set_piece(client, source, viewer):
    _add_set(
        client,
        source,
        model="PS-2",
        pieces=[
            _piece("core", "Pack A", "PB-1"),
            _piece("core", "Pack B", "PB-2"),
            _piece("addon", "Charger", "PB-3"),
        ],
    )
    battery = client.post(
        "/api/inventory/batteries",
        json={"name": "My pack", "model": "PB-1"},
        headers=auth_headers(viewer),
    )
    assert battery.status_code == 201, battery.text

    payload = _suggestions(client, viewer)
    assert _suggested_models(payload) == {"pb-2", "pb-3"}
    assert payload["groups"][0]["item"]["kind"] == "battery"


def test_never_suggests_what_viewer_owns(client, source, viewer):
    _seed_socket_world(client, source)
    # The viewer already has AD-1 as a hand-entered piece of his
    # set and AD-2 as a standalone tool: neither may be suggested,
    # however it would have arrived.
    _add_set(
        client,
        viewer,
        pieces=[_piece("addon", "My AD socket 1", "AD-1")],
    )
    _add_tool(client, viewer, name="Loose AD socket 2", model="AD-2")

    suggested = _suggested_models(_suggestions(client, viewer))
    assert "ad-1" not in suggested
    assert "ad-2" not in suggested
    assert {"ad-3", "ad-4", "ad-5"} <= suggested
    # The AD-1 piece would ALSO be a membership bridge into the
    # source's set — but the same set on both sides is set-to-set's
    # pair (addons only): the core pieces came WITH the viewer's
    # set and are never expansions of it.
    assert "c-1" not in suggested


def test_membership_bridge_into_a_different_set(client, source, viewer):
    """A piece of MY set living inside a DIFFERENT set of yours is
    a true membership bridge: that set's other pieces (core
    included) complete my picture and are suggested."""
    _add_set(
        client,
        source,
        model="OTHER-9",
        pieces=[
            _piece("core", "Shared widget", "W-1"),
            _piece("core", "Other core", "W-2"),
            _piece("addon", "Other addon", "W-3"),
        ],
    )
    _add_set(
        client,
        viewer,
        model="MINE-5",
        pieces=[_piece("core", "My shared widget", "W-1")],
    )
    payload = _suggestions(client, viewer)
    assert _suggested_models(payload) == {"w-2", "w-3"}


def test_matching_normalizes_like_the_importer(client, source, viewer):
    """Case, stray spaces and repeated internal spaces forgive;
    punctuation does NOT fold (the importer's rule for numbers)."""
    _add_set(
        client,
        source,
        model="KRL 1033",
        pieces=[_piece("addon", "Top till", "TT-1")],
    )
    _add_set(client, viewer, model="  krl   1033 ")
    payload = _suggestions(client, viewer)
    assert _suggested_models(payload) == {"tt-1"}


# -- privacy -------------------------------------------------------------------


_FORBIDDEN_KEYS = {
    "owner_id",
    "owner",
    "source",
    "source_id",
    "source_user_id",
    "user_id",
    "serial",
    "serial_number",
    "serial_numbers",
    "price",
    "purchase_price",
    "replacement_cost",
    "msrp",
    "photo",
    "photos",
    "attachments",
    "notes",
    "email",
    "contributor",
    "contributors",
    "dealer_company_id",
}


def _walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_payload_carries_no_source_identity(client, source, viewer):
    _seed_socket_world(client, source)
    _add_set(client, viewer)

    for path in ("/api/tool-expansion/suggestions", "/api/tool-expansion/summary"):
        resp = client.get(path, headers=auth_headers(viewer))
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert str(source.id) not in body
        assert source.email not in body
        for key, _value in _walk(resp.json()):
            assert key not in _FORBIDDEN_KEYS, f"{path} leaked key {key!r}"


# -- the pool -------------------------------------------------------------------


def test_opted_out_source_feeds_nothing(client, db, source, viewer):
    _seed_socket_world(client, source)
    _add_set(client, viewer)
    assert _suggestions(client, viewer)["total"] == 5

    source.catalog_contribute = False
    db.commit()
    assert _suggestions(client, viewer)["total"] == 0


def test_viewer_never_feeds_themselves(client, viewer):
    _seed_socket_world(client, viewer)
    assert _suggestions(client, viewer)["total"] == 0


# -- user controls ----------------------------------------------------------------


def test_dismiss_is_per_user_and_per_item(client, source, viewer, third):
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)
    _add_set(client, third)

    resp = client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": "tool",
            "anchor_id": mine["id"],
            "suggested_model": "ad-2",
        },
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 204, resp.text
    # Idempotent: the same dismissal again is the same state.
    resp = client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": "tool",
            "anchor_id": mine["id"],
            "suggested_model": "AD-2",
        },
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 204, resp.text

    assert _suggested_models(_suggestions(client, viewer)) == {
        "ad-1",
        "ad-3",
        "ad-4",
        "ad-5",
    }
    # The third user still sees all five.
    assert _suggestions(client, third)["total"] == 5


def test_dismiss_someone_elses_item_is_404(client, source, viewer):
    _seed_socket_world(client, source)
    theirs = _add_set(client, source, model="OTHER-1")
    resp = client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": "tool",
            "anchor_id": theirs["id"],
            "suggested_model": "ad-1",
        },
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 404, resp.text


def _seed_bad_match(client, source):
    _add_set(
        client,
        source,
        name="Bad set",
        model="BAD-1",
        pieces=[_piece("addon", "Junk add-on", "JUNK-9")],
    )


def _report(client, user, anchor_model="BAD-1", suggested_model="JUNK-9"):
    return client.post(
        "/api/tool-expansion/report",
        json={"anchor_model": anchor_model, "suggested_model": suggested_model},
        headers=auth_headers(user),
    )


def test_report_hides_for_reporter_and_kills_at_three_distinct(
    client, db, source, viewer, third, fourth
):
    _seed_bad_match(client, source)
    for user in (viewer, third, fourth):
        _add_set(client, user, name="Bad set", model="BAD-1")
        assert _suggested_models(_suggestions(client, user)) == {"junk-9"}

    # One reporter: hidden for the reporter, alive for the rest.
    assert _report(client, viewer).status_code == 204
    assert _suggestions(client, viewer)["total"] == 0
    assert _suggested_models(_suggestions(client, third)) == {"junk-9"}

    # The same reporter twice still counts ONCE.
    assert _report(client, viewer).status_code == 204
    assert _report(client, third).status_code == 204
    assert _suggested_models(_suggestions(client, fourth)) == {"junk-9"}

    # The third distinct reporter kills the match for everyone —
    # including a brand-new owner who never saw it.
    assert _report(client, fourth).status_code == 204
    assert _suggestions(client, fourth)["total"] == 0
    late = _make_user(db, "TV-M-001005", "late@example.com", [MECHANIC])
    _add_set(client, late, name="Bad set", model="BAD-1")
    assert _suggestions(client, late)["total"] == 0


# -- counts / summary / scoping ---------------------------------------------------


def test_counts_summary_and_scope_agree(client, source, viewer):
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)

    summary = client.get(
        "/api/tool-expansion/summary", headers=auth_headers(viewer)
    ).json()
    assert summary["count"] == 5
    assert summary["top"][0]["item_name"] == mine["name"]

    counts = client.get(
        "/api/tool-expansion/counts", headers=auth_headers(viewer)
    ).json()
    assert counts["counts"] == {f"tool:{mine['id']}": 5}

    scoped = _suggestions(client, viewer, kind="tool", item_id=mine["id"])
    assert scoped["total"] == 5
    other = _add_tool(client, viewer, name="Unrelated", model="ZZ-9")
    scoped = _suggestions(client, viewer, kind="tool", item_id=other["id"])
    assert scoped["total"] == 0
    assert scoped["groups"] == []


def test_empty_state_is_clean(client, viewer):
    payload = _suggestions(client, viewer)
    assert payload == {"total": 0, "groups": []}


def test_account_deletion_sweeps_expansion_rows(client, db, source, viewer):
    """My dismissal + report rows are my own paperwork: they go
    with the account (core's delete_account sweep)."""
    from app.modules.tool_expansion import models as expansion_models

    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)
    client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": "tool",
            "anchor_id": mine["id"],
            "suggested_model": "ad-1",
        },
        headers=auth_headers(viewer),
    )
    _report(client, viewer, anchor_model="SS-100", suggested_model="AD-1")
    assert db.query(expansion_models.ExpansionDismissal).count() == 1
    assert db.query(expansion_models.ExpansionReport).count() == 1

    resp = client.request(
        "DELETE",
        "/api/core/me",
        json={"confirmation": "DELETE"},
        headers=auth_headers(viewer),
    )
    assert resp.status_code in (200, 204), resp.text
    assert db.query(expansion_models.ExpansionDismissal).count() == 0
    assert db.query(expansion_models.ExpansionReport).count() == 0


# -- the doorway ---------------------------------------------------


def test_module_gate_matches_its_groups(client, db, viewer):
    dealer_only = _make_user(db, "TV-D-001006", "dealer@example.com", [DEALER])
    resp = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(dealer_only)
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "module_unavailable"

    groupless = _make_user(db, "TV-X-001007", "none@example.com", [])
    resp = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(groupless)
    )
    assert resp.status_code == 403, resp.text

    resp = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    )
    assert resp.status_code == 200, resp.text


# -- the archive (main tab layout lane 5, 2026-11-10) ---------------------------
#
# Ryan's model: "remove for me" is MOVE TO ARCHIVED MATCHES over
# the same dismissal ledger — the archive tab reads the ledger
# back, and un-archive deletes the row. The Report ledger stays
# a separate thing and never shows in the archive.


def _dismiss(client, user, anchor_id, suggested_model, anchor_kind="tool"):
    resp = client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": anchor_kind,
            "anchor_id": anchor_id,
            "suggested_model": suggested_model,
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 204, resp.text
    return resp


def _unarchive(client, user, anchor_id, suggested_model, anchor_kind="tool"):
    return client.post(
        "/api/tool-expansion/unarchive",
        json={
            "anchor_kind": anchor_kind,
            "anchor_id": anchor_id,
            "suggested_model": suggested_model,
        },
        headers=auth_headers(user),
    )


def _archived(client, user):
    resp = client.get("/api/tool-expansion/archived", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_archived_lists_the_ledger_and_unarchive_restores(client, source, viewer):
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)

    assert _archived(client, viewer) == {"total": 0, "entries": []}

    _dismiss(client, viewer, mine["id"], "ad-2")
    _dismiss(client, viewer, mine["id"], "ad-4")
    assert _suggested_models(_suggestions(client, viewer)) == {
        "ad-1",
        "ad-3",
        "ad-5",
    }

    payload = _archived(client, viewer)
    assert payload["total"] == 2
    by_model = {e["suggested_model"]: e for e in payload["entries"]}
    assert set(by_model) == {"ad-2", "ad-4"}
    entry = by_model["ad-2"]
    # Display resolves from the live pool exactly as the Matches
    # tab spells it.
    assert entry["name"] == "AD socket 2"
    assert entry["model_number"] == "AD-2"
    assert entry["item"]["id"] == mine["id"]
    assert entry["item"]["name"] == mine["name"]
    assert entry["restorable"] is True
    assert entry["archived_at"]

    # Bring one back: the row leaves the archive and the match
    # returns to the Matches read.
    resp = _unarchive(client, viewer, mine["id"], "AD-2")
    assert resp.status_code == 204, resp.text
    assert _archived(client, viewer)["total"] == 1
    assert _suggested_models(_suggestions(client, viewer)) == {
        "ad-1",
        "ad-2",
        "ad-3",
        "ad-5",
    }

    # A second un-archive of the same key: nothing left to bring
    # back — 404, not a silent no-op.
    resp = _unarchive(client, viewer, mine["id"], "ad-2")
    assert resp.status_code == 404, resp.text


def test_archive_is_per_user(client, source, viewer, third):
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)
    theirs = _add_set(client, third)

    _dismiss(client, viewer, mine["id"], "ad-1")
    _dismiss(client, third, theirs["id"], "ad-1")

    assert _archived(client, viewer)["total"] == 1
    assert _archived(client, third)["total"] == 1
    # The third user cannot reach into the viewer's archive.
    resp = _unarchive(client, third, mine["id"], "ad-1")
    assert resp.status_code == 404, resp.text
    assert _archived(client, viewer)["total"] == 1


def test_archived_tombstone_when_the_match_stops_generating(
    client, db, source, viewer
):
    """The source opts out of the pool: the archived row keeps
    the ledger's facts — the stored model key, no invented name —
    and is no longer restorable."""
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)
    _dismiss(client, viewer, mine["id"], "ad-3")
    assert _archived(client, viewer)["entries"][0]["name"] == "AD socket 3"

    source.catalog_contribute = False
    db.commit()

    payload = _archived(client, viewer)
    assert payload["total"] == 1
    entry = payload["entries"][0]
    assert entry["name"] == ""
    assert entry["model_number"] == "ad-3"  # the stored key, nothing dressed up
    assert entry["restorable"] is False
    # The anchor item is still the viewer's own and still named.
    assert entry["item"]["id"] == mine["id"]


def test_archived_tombstone_when_the_anchor_item_is_gone(client, source, viewer):
    _seed_socket_world(client, source)
    mine = _add_set(client, viewer)
    _dismiss(client, viewer, mine["id"], "ad-1")

    resp = client.delete(
        f"/api/inventory/{mine['id']}", headers=auth_headers(viewer)
    )
    assert resp.status_code == 204, resp.text

    payload = _archived(client, viewer)
    assert payload["total"] == 1
    entry = payload["entries"][0]
    assert entry["item"] is None
    assert entry["anchor_id"] == mine["id"]
    assert entry["restorable"] is False
    # The piece itself still resolves from the pool.
    assert entry["name"] == "AD socket 1"
    # Un-archiving a tombstone still works — the row is the
    # user's own paperwork even when its item is gone.
    assert _unarchive(client, viewer, mine["id"], "ad-1").status_code == 204
    assert _archived(client, viewer)["total"] == 0


def test_reports_never_enter_the_archive(client, source, viewer):
    """Report judges a MATCH in its own ledger; it is not an
    archive move and must not surface on the Archived tab."""
    _seed_bad_match(client, source)
    _add_set(client, viewer, name="Bad set", model="BAD-1")
    assert _report(client, viewer).status_code == 204
    assert _suggestions(client, viewer)["total"] == 0
    assert _archived(client, viewer) == {"total": 0, "entries": []}


def test_archived_is_not_restorable_when_the_match_is_killed(
    client, source, viewer, third, fourth
):
    """An archived pairing later killed by the community stays
    out even if un-archived — restorable says so up front."""
    _seed_bad_match(client, source)
    sets = {}
    for user in (viewer, third, fourth):
        sets[user.id] = _add_set(client, user, name="Bad set", model="BAD-1")
    _dismiss(client, viewer, sets[viewer.id]["id"], "junk-9")

    for user in (viewer, third, fourth):
        assert _report(client, user).status_code == 204

    entry = _archived(client, viewer)["entries"][0]
    assert entry["restorable"] is False
    assert _unarchive(client, viewer, sets[viewer.id]["id"], "junk-9").status_code == 204
    assert _suggestions(client, viewer)["total"] == 0
