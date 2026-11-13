"""Gap wave 1 — inventory items 2, 3, 4, 5.

- Item 2 (structured warranty): provider/contact/terms/type
  round-trip on tools AND batteries; "lifetime" computes as
  permanently in-warranty with no end date; legacy months
  behavior is byte-identical for records that don't set the new
  fields; reports carry provider + type columns.
- Item 3 (category + tag managers): list with counts, create,
  rename cascading across BOTH kinds (case-variant spellings
  fold), merge, delete-detaches-never-deletes; tag palette
  validation + rename cascade.
- Item 4 (health check): the missing-data rules incl. the set
  piece serial rule; inactive (over-cap) items excluded.
- Item 5 (lost/stolen reports): create applies the standing and
  opens the record; one active report per item; edit; recover
  closes WITH history and flips standing back; reports module
  carries police # + reported date columns.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.inventory import service as inventory_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, account_types=(MECHANIC,), *, name="Wave Owner"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-001201", "w1owner@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-001202", "w1other@example.com")


def _tool(client, user, **payload):
    payload.setdefault("name", "Wave wrench")
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _battery(client, user, **payload):
    payload.setdefault("name", "Wave pack")
    resp = client.post(
        "/api/inventory/batteries", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# -- item 2: structured warranty ---------------------------------------------------


def test_warranty_details_round_trip_and_lifetime_computes(client, owner):
    tool = _tool(
        client,
        owner,
        warranty_provider="Snap-on Inc.",
        warranty_contact="Franchisee Dave, 555-0100",
        warranty_terms="Full replacement, no receipt needed",
        warranty_type="lifetime",
        # No purchase date, no months: a term warranty would read
        # "unknown" — lifetime must read in-warranty regardless.
    )
    assert tool["warranty_provider"] == "Snap-on Inc."
    assert tool["warranty_contact"] == "Franchisee Dave, 555-0100"
    assert tool["warranty_terms"] == "Full replacement, no receipt needed"
    assert tool["warranty_type"] == "lifetime"
    assert tool["warranty_status"] == "in_warranty"
    assert tool["warranty_end_date"] is None

    battery = _battery(
        client,
        owner,
        warranty_provider="Milwaukee Tool",
        warranty_type="lifetime",
    )
    assert battery["warranty_status"] == "in_warranty"
    assert battery["warranty_end_date"] is None
    assert battery["warranty_provider"] == "Milwaukee Tool"


def test_legacy_warranty_behavior_unchanged_without_new_fields(client, owner):
    # A term record from before the fields existed: months logic
    # exactly as the maintenance build left it.
    old = _tool(
        client,
        owner,
        name="Old drill",
        purchase_date=(date.today() - timedelta(days=800)).isoformat(),
        warranty_months=24,
    )
    assert old["warranty_type"] is None
    assert old["warranty_provider"] == ""
    assert old["warranty_status"] == "expired"

    limited = _tool(
        client,
        owner,
        name="Limited saw",
        purchase_date=(date.today() - timedelta(days=10)).isoformat(),
        warranty_months=12,
        warranty_type="limited",
    )
    assert limited["warranty_status"] == "in_warranty"
    assert limited["warranty_end_date"] is not None

    bad = client.post(
        "/api/inventory",
        json={"name": "Bad type", "warranty_type": "forever"},
        headers=auth_headers(owner),
    )
    assert bad.status_code == 422, bad.text


def test_reports_carry_warranty_provider_and_type(client, owner):
    _tool(
        client,
        owner,
        name="Covered",
        warranty_provider="Matco Tools",
        warranty_type="lifetime",
    )
    resp = client.post(
        "/api/reports/run",
        json={"columns": ["name", "warranty_provider", "warranty_type"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    rows = [r for g in resp.json()["groups"] for r in g["rows"]]
    row = next(r for r in rows if r["values"]["name"] == "Covered")
    assert row["values"]["warranty_provider"] == "Matco Tools"
    assert row["values"]["warranty_type"] == "Lifetime"


# -- item 3: categories + tags -----------------------------------------------------


def test_category_manager_lifecycle(client, owner, db):
    _tool(client, owner, name="A", category="Power Tools")
    _tool(client, owner, name="B", category="power tools")  # spelling variant
    _battery(client, owner, name="C", category="Power Tools")

    listed = client.get(
        "/api/inventory/categories", headers=auth_headers(owner)
    ).json()
    # Case variants fold into ONE category with all 3 items.
    assert len(listed) == 1
    assert listed[0]["item_count"] == 3

    # Create an empty category: it exists with zero items.
    created = client.post(
        "/api/inventory/categories",
        json={"name": "Hand Tools"},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    # Creating the same name in another case folds to the same row.
    dupe = client.post(
        "/api/inventory/categories",
        json={"name": "HAND tools"},
        headers=auth_headers(owner),
    )
    assert dupe.status_code == 201
    names = {
        c["name"]
        for c in client.get(
            "/api/inventory/categories", headers=auth_headers(owner)
        ).json()
    }
    assert names == {"Power Tools", "Hand Tools"}

    # Rename cascades onto every item of both kinds.
    renamed = client.post(
        "/api/inventory/categories/rename",
        json={"old_name": "power tools", "new_name": "Cordless"},
        headers=auth_headers(owner),
    )
    assert renamed.status_code == 200, renamed.text
    items = client.get("/api/inventory", headers=auth_headers(owner)).json()
    batteries = client.get(
        "/api/inventory/batteries", headers=auth_headers(owner)
    ).json()
    assert {t["category"] for t in items} == {"Cordless"}
    assert {b["category"] for b in batteries} == {"Cordless"}

    # Merging onto an existing name via rename is refused — the
    # merge verb is the honest path.
    refused = client.post(
        "/api/inventory/categories/rename",
        json={"old_name": "Cordless", "new_name": "Hand Tools"},
        headers=auth_headers(owner),
    )
    assert refused.status_code == 422, refused.text

    merged = client.post(
        "/api/inventory/categories/merge",
        json={"source_name": "Cordless", "target_name": "Hand Tools"},
        headers=auth_headers(owner),
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["moved"] == 3
    listed = client.get(
        "/api/inventory/categories", headers=auth_headers(owner)
    ).json()
    assert [(c["name"], c["item_count"]) for c in listed] == [("Hand Tools", 3)]

    # Delete detaches — the items survive, uncategorized.
    deleted = client.post(
        "/api/inventory/categories/delete",
        json={"name": "Hand Tools"},
        headers=auth_headers(owner),
    )
    assert deleted.json() == {"detached": 3}
    items = client.get("/api/inventory", headers=auth_headers(owner)).json()
    assert len(items) == 2  # tools A + B still here
    assert {t["category"] for t in items} == {""}


def test_category_manager_is_owner_scoped(client, owner, other):
    _tool(client, owner, name="Mine", category="Secret Cat")
    listed = client.get(
        "/api/inventory/categories", headers=auth_headers(other)
    ).json()
    assert listed == []
    foreign = client.post(
        "/api/inventory/categories/rename",
        json={"old_name": "Secret Cat", "new_name": "Stolen"},
        headers=auth_headers(other),
    )
    assert foreign.status_code == 422, foreign.text


# -- starred categories (owner spec 2026-10-24) -----------------------------------


def _create_categories(client, user, names):
    for name in names:
        resp = client.post(
            "/api/inventory/categories",
            json={"name": name},
            headers=auth_headers(user),
        )
        assert resp.status_code == 201, resp.text


def _star(client, user, name, starred=True):
    return client.post(
        "/api/inventory/categories/star",
        json={"name": name, "starred": starred},
        headers=auth_headers(user),
    )


def _listed(client, user):
    return client.get(
        "/api/inventory/categories", headers=auth_headers(user)
    ).json()


def test_category_star_round_trip(client, owner):
    _tool(client, owner, name="A", category="Power Tools")
    # Unstarred by default; the category lives only on the item.
    (row,) = _listed(client, owner)
    assert row["starred"] is False and row["registered"] is False

    starred = _star(client, owner, "power tools")  # any spelling
    assert starred.status_code == 200, starred.text
    assert starred.json()["starred"] is True
    # Starring registered the category so the flag has a row.
    (row,) = _listed(client, owner)
    assert row == {
        "name": "Power Tools",
        "item_count": 1,
        "registered": True,
        "starred": True,
        "star_capped": False,
        # Starter fields (2026-10-25): a user's own category.
        "preinstalled": False,
        "system_key": None,
    }

    unstarred = _star(client, owner, "Power Tools", starred=False)
    assert unstarred.status_code == 200
    assert unstarred.json()["starred"] is False
    (row,) = _listed(client, owner)
    assert row["starred"] is False

    # Starring a name that doesn't exist at all is a 422.
    missing = _star(client, owner, "No Such Category")
    assert missing.status_code == 422, missing.text


def test_category_star_cap_is_server_enforced(client, owner):
    names = [f"Cat {i:02d}" for i in range(12)]
    _create_categories(client, owner, names)
    for name in names[:5]:
        assert _star(client, owner, name).status_code == 200
    # The 6th star is refused with the machine-readable code
    # (cap cut from 10 to 5, owner spec 2026-10-25).
    refused = _star(client, owner, names[5])
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "star_limit_reached"
    assert sum(1 for c in _listed(client, owner) if c["starred"]) == 5
    # Re-starring an already-starred category at the cap is fine.
    assert _star(client, owner, names[0]).status_code == 200
    # Un-starring always succeeds — then the 6th fits.
    assert _star(client, owner, names[0], starred=False).status_code == 200
    assert _star(client, owner, names[5]).status_code == 200
    assert sum(1 for c in _listed(client, owner) if c["starred"]) == 5


def test_category_star_is_owner_scoped(client, owner, other):
    _create_categories(client, owner, ["Owner Cat"])
    _create_categories(client, other, ["Other Cat"])
    assert _star(client, owner, "Owner Cat").status_code == 200
    # The other owner sees none of it, and can't star a name
    # that only exists in someone else's vault.
    assert _listed(client, other)[0]["starred"] is False
    assert _star(client, other, "Owner Cat").status_code == 422
    assert _star(client, other, "Other Cat").status_code == 200
    assert _listed(client, other)[0]["starred"] is True
    # And the first owner's view is untouched by any of it.
    assert _listed(client, owner)[0]["starred"] is True


def test_category_can_be_born_starred(client, owner):
    born = client.post(
        "/api/inventory/categories",
        json={"name": "Born Starred", "starred": True},
        headers=auth_headers(owner),
    )
    assert born.status_code == 201, born.text
    assert born.json()["starred"] is True
    assert born.json()["star_capped"] is False

    # Fill the cap, then ask for one more born starred: the
    # category is still created — unstarred, with the signal.
    _create_categories(client, owner, [f"Filler {i}" for i in range(4)])
    for row in _listed(client, owner):
        if row["name"].startswith("Filler"):
            assert _star(client, owner, row["name"]).status_code == 200
    capped = client.post(
        "/api/inventory/categories",
        json={"name": "One Too Many", "starred": True},
        headers=auth_headers(owner),
    )
    assert capped.status_code == 201, capped.text
    assert capped.json()["starred"] is False
    assert capped.json()["star_capped"] is True
    # ...and creating unstarred at the cap works as always.
    plain = client.post(
        "/api/inventory/categories",
        json={"name": "Plain At Cap"},
        headers=auth_headers(owner),
    )
    assert plain.status_code == 201
    assert plain.json()["starred"] is False


def test_category_star_follows_rename_dies_with_delete_and_merge(
    client, owner
):
    _tool(client, owner, name="A", category="Power Tools")
    _create_categories(client, owner, ["Hand Tools"])
    assert _star(client, owner, "Power Tools").status_code == 200
    assert _star(client, owner, "Hand Tools").status_code == 200

    # Rename: the star moves to the new name with the row.
    renamed = client.post(
        "/api/inventory/categories/rename",
        json={"old_name": "Power Tools", "new_name": "Cordless"},
        headers=auth_headers(owner),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["starred"] is True
    by_name = {c["name"]: c for c in _listed(client, owner)}
    assert by_name["Cordless"]["starred"] is True

    # Merge: the source's star dies with it; the target keeps
    # its own (here: none).
    assert _star(client, owner, "Hand Tools", starred=False).status_code == 200
    merged = client.post(
        "/api/inventory/categories/merge",
        json={"source_name": "Cordless", "target_name": "Hand Tools"},
        headers=auth_headers(owner),
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["starred"] is False
    (row,) = _listed(client, owner)
    assert row["name"] == "Hand Tools" and row["starred"] is False

    # Delete: a starred category takes its star with it.
    assert _star(client, owner, "Hand Tools").status_code == 200
    deleted = client.post(
        "/api/inventory/categories/delete",
        json={"name": "Hand Tools"},
        headers=auth_headers(owner),
    )
    assert deleted.status_code == 200
    assert _listed(client, owner) == []


def test_tag_palette_and_rename_cascade(client, owner):
    tag = client.post(
        "/api/inventory/tags",
        json={"name": "truck kit", "color": "blue"},
        headers=auth_headers(owner),
    )
    assert tag.status_code == 201, tag.text
    assert tag.json()["color"] == "blue"

    bad = client.post(
        "/api/inventory/tags",
        json={"name": "neon", "color": "chartreuse"},
        headers=auth_headers(owner),
    )
    assert bad.status_code == 422, bad.text

    renamed = client.put(
        f"/api/inventory/tags/{tag.json()['id']}",
        json={"name": "rig kit", "color": "red"},
        headers=auth_headers(owner),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "rig kit"
    assert renamed.json()["color"] == "red"


# -- item 4: health check ------------------------------------------------------------


def test_health_check_flags_missing_claim_data(client, owner, db):
    complete = _tool(
        client,
        owner,
        name="Complete",
        model="M1",
        serial_number="S1",
        purchase_date="2026-01-15",
        attachments=None,
    )
    # Give the complete tool a photo directly (upload flow is
    # covered elsewhere; the check reads attachment kinds).
    row = db.get(inventory_models.Tool, uuid.UUID(complete["id"]))
    row.attachments = [{"kind": "photo", "key": "k", "filename": "p.jpg"}]
    db.commit()

    bare = _tool(client, owner, name="Bare")  # missing everything
    pack = _battery(client, owner, name="Bare pack", model="M18")
    # Identifier rule (owner ruling 2026-11-03): a model OR a
    # serial number satisfies the identifier a claim needs — a
    # serial-only tool is NOT flagged for the identifier.
    serial_only = _tool(
        client,
        owner,
        name="Serial only",
        serial_number="SONLY1",
        purchase_date="2026-03-01",
    )
    serial_row = db.get(inventory_models.Tool, uuid.UUID(serial_only["id"]))
    serial_row.attachments = [{"kind": "photo", "key": "k3", "filename": "s.jpg"}]
    db.commit()

    # A set whose present piece has no serial: surfaces under the
    # set by the piece rule.
    toolset = _tool(
        client,
        owner,
        name="Socket set",
        model="SET1",
        serial_number="SETSN",
        purchase_date="2026-02-01",
        is_set=True,
        pieces=[
            {"kind": "core", "name": "10mm socket", "part_number": "P10"},
            {
                "kind": "core",
                "name": "12mm socket",
                "part_number": "P12",
                "serial_number": "PS12",
            },
        ],
    )
    set_row = db.get(inventory_models.Tool, uuid.UUID(toolset["id"]))
    set_row.attachments = [{"kind": "photo", "key": "k2", "filename": "s.jpg"}]
    db.commit()

    result = client.get(
        "/api/inventory/health-check", headers=auth_headers(owner)
    ).json()
    by_name = {row["name"]: row for row in result["items"]}
    assert "Complete" not in by_name
    # "Bare" has NEITHER a model nor a serial number -> the one
    # identifier gap (the old separate model/serial gaps are gone).
    assert set(by_name["Bare"]["missing"]) == {
        "identifier", "photo", "purchase_date",
    }
    # "Bare pack" carries a model, so the identifier is satisfied
    # even with no serial number — only photo/date are missing.
    assert by_name["Bare pack"]["missing"] == ["photo", "purchase_date"]
    assert "Serial only" not in by_name
    assert by_name["Socket set"]["missing"] == []
    assert by_name["Socket set"]["pieces_missing_serial"] == ["10mm socket"]
    # The same piece rides along with its own id (2026-11-05):
    # the health check's Fix-it link lands on THAT piece's
    # serial field, so the payload must name the piece row.
    [piece_ref] = by_name["Socket set"]["pieces_missing"]
    assert piece_ref["name"] == "10mm socket"
    socket_row = db.scalars(
        select(inventory_models.SetPiece).where(
            inventory_models.SetPiece.set_id == uuid.UUID(toolset["id"]),
            inventory_models.SetPiece.name == "10mm socket",
        )
    ).one()
    assert piece_ref["id"] == str(socket_row.id)
    assert result["counts"]["piece_serial"] == 1
    assert result["counts"]["identifier"] == 1
    assert result["total"] == 3


def test_health_check_excludes_inactive_items(client, owner, db):
    from app.modules.billing import entitlements
    from app.modules.billing import models as billing_models

    # Seed the plan catalog with a 1-item free plan, then turn
    # enforcement on: only the newest item stays active; the
    # other two fall out of the active set and must NOT be
    # flagged (the reports rule).
    db.add(
        billing_models.Plan(
            plan_key="free", name="Free", item_limit=1,
            ai_monthly_credits=0, is_paid=False, sort_order=0,
        )
    )
    db.commit()
    for i in range(3):
        _tool(client, owner, name=f"T{i}")
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    result = client.get(
        "/api/inventory/health-check", headers=auth_headers(owner)
    ).json()
    assert result["total"] == 1


# -- item 5: lost/stolen reports -----------------------------------------------------


def test_loss_report_lifecycle(client, owner):
    tool = _tool(client, owner, name="Vanished drill")
    created = client.post(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        json={
            "standing": "stolen",
            "police_report_number": "26-1042",
            "police_department": "Little Falls PD",
            "insurer_name": "Acme Mutual",
            "claim_number": "CLM-9",
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    report = created.json()
    assert report["status"] == "active"
    assert report["standing"] == "stolen"
    assert report["reported_date"] is not None

    # The standing moved with the report.
    after = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert after["standing"] == "stolen"

    # One active report per item.
    second = client.post(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        json={"standing": "lost"},
        headers=auth_headers(owner),
    )
    assert second.status_code == 422, second.text

    # Edit the paper trail.
    edited = client.put(
        f"/api/inventory/loss-reports/{report['id']}",
        json={"notes": "Seen near the river landing."},
        headers=auth_headers(owner),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["notes"] == "Seen near the river landing."

    # Recover: standing back, report CLOSED but kept as history.
    recovered = client.post(
        f"/api/inventory/loss-reports/{report['id']}/recover",
        json={},
        headers=auth_headers(owner),
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "recovered"
    assert recovered.json()["recovered_date"] is not None
    after = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert after["standing"] == "in_service"
    history = client.get(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        headers=auth_headers(owner),
    ).json()
    assert len(history) == 1 and history[0]["status"] == "recovered"

    # A fresh incident can open a fresh report.
    again = client.post(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        json={"standing": "lost"},
        headers=auth_headers(owner),
    )
    assert again.status_code == 201, again.text


def test_loss_report_owner_scoped_and_battery(client, owner, other):
    pack = _battery(client, owner, name="Gone pack")
    created = client.post(
        f"/api/inventory/battery/{pack['id']}/loss-reports",
        json={"standing": "lost", "police_report_number": "26-77"},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    foreign = client.get(
        f"/api/inventory/battery/{pack['id']}/loss-reports",
        headers=auth_headers(other),
    )
    assert foreign.status_code == 404, foreign.text


def test_reports_carry_loss_columns(client, owner):
    tool = _tool(client, owner, name="Stolen saw")
    client.post(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        json={
            "standing": "stolen",
            "police_report_number": "26-555",
            "reported_date": "2026-10-19",
        },
        headers=auth_headers(owner),
    )
    resp = client.post(
        "/api/reports/run",
        json={"columns": ["name", "police_report_number", "loss_reported_date"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    rows = [r for g in resp.json()["groups"] for r in g["rows"]]
    row = next(r for r in rows if r["values"]["name"] == "Stolen saw")
    assert row["values"]["police_report_number"] == "26-555"
    assert row["values"]["loss_reported_date"] == "2026-10-19"


def test_journal_registers_wave1_entities():
    from app.modules.core import journal

    registered = {spec.entity_type for spec in journal._SPECS}
    for entity_type in ("inventory_category", "loss_report", "borrower_contact"):
        assert entity_type in registered
