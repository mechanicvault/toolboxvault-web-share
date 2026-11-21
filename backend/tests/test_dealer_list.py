"""My dealer list (owner directive, 2026-10-31): per-user
customization of the PREFILLED dealer pick list.

The list is an overlay on the live directory, never a copy:
removals are remembered per directory entry (so a brand the
operator adds later appears on its own), additions are templates
that mint the user's private company the first time they're
picked, and NO list edit ever touches a dealer record — hiding
is not deleting, and removing an entry leaves any company it
created standing.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="List User", is_operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        is_operator=is_operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user_a(db):
    return _make_user(db, "TV-M-000501", "a@example.com")


@pytest.fixture()
def user_b(db):
    return _make_user(db, "TV-M-000502", "b@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000500", "op@example.com", is_operator=True)


def _directory_company(client, operator, name, **overrides):
    payload = {
        "name": name,
        "email": "",
        "website": "",
        "address": "",
        "phones": [],
        "notes": "",
    }
    payload.update(overrides)
    resp = client.post(
        "/api/admin/dealer-companies", json=payload, headers=auth_headers(operator)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _private_company(client, user, name="My Local Co", **overrides):
    payload = {
        "name": name,
        "email": "",
        "website": "",
        "address": "",
        "phones": [],
        "notes": "",
    }
    payload.update(overrides)
    resp = client.post(
        "/api/dealers/companies", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _pick_list(client, user):
    resp = client.get("/api/dealers/pick-list", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pick_names(client, user):
    return [c["name"] for c in _pick_list(client, user)["companies"]]


def _hide(client, user, company_id):
    return client.post(
        "/api/dealers/directory-hidden",
        json={"company_id": company_id},
        headers=auth_headers(user),
    )


def _entry_payload(name="Johnson Tool Supply", **overrides):
    payload = {
        "name": name,
        "kind": "retailer",
        "email": "sales@johnson.example",
        "website": "https://johnson.example",
        "address": "12 Industrial Pkwy",
        "phones": [{"label": "Customer Service", "number": "555-0100"}],
        "notes": "Tuesday truck",
    }
    payload.update(overrides)
    return payload


def test_pick_list_defaults_to_directory_plus_mine(client, user_a, operator):
    _directory_company(client, operator, "Alpha Tools")
    _directory_company(client, operator, "Beta Tools")
    _private_company(client, user_a, "A's Own Co")

    body = _pick_list(client, user_a)
    names = [c["name"] for c in body["companies"]]
    assert names == ["Alpha Tools", "Beta Tools", "A's Own Co"]
    assert body["entries"] == []


def test_hide_is_per_user_and_records_untouched(client, user_a, user_b, operator):
    alpha = _directory_company(client, operator, "Alpha Tools")
    beta = _directory_company(client, operator, "Beta Tools")
    _directory_company(client, operator, "Gamma Tools")

    resp = _hide(client, user_a, alpha["id"])
    assert resp.status_code == 200, resp.text
    resp = _hide(client, user_a, beta["id"])
    assert resp.status_code == 200, resp.text

    # Gone from A's pick list, still present for B.
    assert _pick_names(client, user_a) == ["Gamma Tools"]
    assert _pick_names(client, user_b) == ["Alpha Tools", "Beta Tools", "Gamma Tools"]

    # The full companies read (directory browse, filters, records)
    # is NOT the pick list: A still sees the brands there, and the
    # directory rows themselves stand for the operator.
    listed = client.get("/api/dealers/companies", headers=auth_headers(user_a))
    assert [c["name"] for c in listed.json()] == [
        "Alpha Tools",
        "Beta Tools",
        "Gamma Tools",
    ]
    detail = client.get(
        f"/api/dealers/companies/{alpha['id']}", headers=auth_headers(user_a)
    )
    assert detail.status_code == 200

    # Management view shows the full directory with A's flags.
    settings = client.get(
        "/api/dealers/list-settings", headers=auth_headers(user_a)
    ).json()
    flags = {row["company"]["name"]: row["hidden"] for row in settings["directory"]}
    assert flags == {"Alpha Tools": True, "Beta Tools": True, "Gamma Tools": False}
    settings_b = client.get(
        "/api/dealers/list-settings", headers=auth_headers(user_b)
    ).json()
    assert all(not row["hidden"] for row in settings_b["directory"])


def test_hide_idempotent_unhide_restores(client, user_a, operator):
    alpha = _directory_company(client, operator, "Alpha Tools")
    assert _hide(client, user_a, alpha["id"]).status_code == 200
    assert _hide(client, user_a, alpha["id"]).status_code == 200
    assert _pick_names(client, user_a) == []

    resp = client.delete(
        f"/api/dealers/directory-hidden/{alpha['id']}",
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    assert _pick_names(client, user_a) == ["Alpha Tools"]
    # Unhiding what isn't hidden is a no-op, not an error.
    resp = client.delete(
        f"/api/dealers/directory-hidden/{alpha['id']}",
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200


def test_hide_refuses_private_and_missing_companies(client, user_a, operator):
    mine = _private_company(client, user_a)
    assert _hide(client, user_a, mine["id"]).status_code == 404
    assert _hide(client, user_a, str(uuid.uuid4())).status_code == 404


def test_new_directory_brand_appears_for_users(client, user_a, operator):
    alpha = _directory_company(client, operator, "Alpha Tools")
    _hide(client, user_a, alpha["id"])
    # The operator adds a brand AFTER A customized: A's removals
    # are remembered per entry, so the new brand shows up alone.
    _directory_company(client, operator, "Delta Tools")
    assert _pick_names(client, user_a) == ["Delta Tools"]


def test_custom_entry_pick_creates_dealer_prefilled(client, user_a, user_b):
    resp = client.post(
        "/api/dealers/list-entries",
        json=_entry_payload(),
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert entry["created_company_id"] is None

    # In A's pick list as an entry; invisible to B everywhere.
    assert [e["name"] for e in _pick_list(client, user_a)["entries"]] == [
        "Johnson Tool Supply"
    ]
    assert _pick_list(client, user_b)["entries"] == []

    # Picking it mints A's private company, prefilled as designed.
    resp = client.post(
        f"/api/dealers/list-entries/{entry['id']}/use",
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    company = resp.json()
    assert company["name"] == "Johnson Tool Supply"
    assert company["is_directory"] is False
    assert company["is_mine"] is True
    assert company["kind"] == "retailer"
    assert company["email"] == "sales@johnson.example"
    assert company["website"] == "https://johnson.example"
    assert company["address"] == "12 Industrial Pkwy"
    assert company["phones"] == [
        {"label": "Customer Service", "number": "555-0100"}
    ]
    assert company["notes"] == "Tuesday truck"

    # The entry is spent: out of the pick entries, its company in
    # the pick companies, and a second pick returns the SAME
    # company (no duplicate dealer is ever minted).
    after = _pick_list(client, user_a)
    assert after["entries"] == []
    assert [c["name"] for c in after["companies"]] == ["Johnson Tool Supply"]
    resp = client.post(
        f"/api/dealers/list-entries/{entry['id']}/use",
        headers=auth_headers(user_a),
    )
    assert resp.json()["id"] == company["id"]
    listed = client.get("/api/dealers/companies", headers=auth_headers(user_a))
    assert len(listed.json()) == 1

    # Settings still shows the entry, marked with its company.
    settings = client.get(
        "/api/dealers/list-settings", headers=auth_headers(user_a)
    ).json()
    assert settings["entries"][0]["created_company_id"] == company["id"]
    assert settings["entries"][0]["created_company_name"] == "Johnson Tool Supply"


def test_entry_crud_is_owner_only(client, user_a, user_b):
    entry = client.post(
        "/api/dealers/list-entries",
        json=_entry_payload(),
        headers=auth_headers(user_a),
    ).json()
    for method, url in [
        ("PUT", f"/api/dealers/list-entries/{entry['id']}"),
        ("DELETE", f"/api/dealers/list-entries/{entry['id']}"),
        ("POST", f"/api/dealers/list-entries/{entry['id']}/use"),
    ]:
        resp = client.request(
            method,
            url,
            json=_entry_payload("Hijack Co") if method == "PUT" else None,
            headers=auth_headers(user_b),
        )
        assert resp.status_code == 404, (method, resp.text)
    # A can still edit it (name change rides through).
    resp = client.put(
        f"/api/dealers/list-entries/{entry['id']}",
        json=_entry_payload("Johnson Tool Supply LLC"),
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Johnson Tool Supply LLC"


def test_spent_entry_cannot_be_edited_but_removal_keeps_company(
    client, user_a
):
    entry = client.post(
        "/api/dealers/list-entries",
        json=_entry_payload(),
        headers=auth_headers(user_a),
    ).json()
    company = client.post(
        f"/api/dealers/list-entries/{entry['id']}/use",
        headers=auth_headers(user_a),
    ).json()

    resp = client.put(
        f"/api/dealers/list-entries/{entry['id']}",
        json=_entry_payload("Renamed"),
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text

    resp = client.delete(
        f"/api/dealers/list-entries/{entry['id']}", headers=auth_headers(user_a)
    )
    assert resp.status_code == 204, resp.text
    # The company the entry created is a dealer record: untouched.
    listed = client.get("/api/dealers/companies", headers=auth_headers(user_a))
    assert [c["id"] for c in listed.json()] == [company["id"]]


def test_restore_defaults_returns_full_list(client, user_a, user_b, operator):
    alpha = _directory_company(client, operator, "Alpha Tools")
    beta = _directory_company(client, operator, "Beta Tools")
    _hide(client, user_a, alpha["id"])
    spent = client.post(
        "/api/dealers/list-entries",
        json=_entry_payload("Spent Co"),
        headers=auth_headers(user_a),
    ).json()
    company = client.post(
        f"/api/dealers/list-entries/{spent['id']}/use",
        headers=auth_headers(user_a),
    ).json()
    client.post(
        "/api/dealers/list-entries",
        json=_entry_payload("Fresh Co"),
        headers=auth_headers(user_a),
    )
    _hide(client, user_b, beta["id"])

    resp = client.post(
        "/api/dealers/list-restore", headers=auth_headers(user_a)
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["hidden_removed"] == 1
    assert result["entries_removed"] == 2
    assert all(not row["hidden"] for row in result["settings"]["directory"])
    assert result["settings"]["entries"] == []

    # A's pick list is the full directory again; the company a
    # spent entry created SURVIVES the restore (it's a record);
    # B's own customization is untouched.
    assert _pick_names(client, user_a) == [
        "Alpha Tools",
        "Beta Tools",
        "Spent Co",
    ]
    assert _pick_names(client, user_b) == ["Alpha Tools"]
    detail = client.get(
        f"/api/dealers/companies/{company['id']}", headers=auth_headers(user_a)
    )
    assert detail.status_code == 200


def test_list_edits_never_touch_existing_records(client, user_a, operator):
    alpha = _directory_company(client, operator, "Alpha Tools")
    mine = _private_company(client, user_a, "A's Own Co", email="own@example.com")
    tool = client.post(
        "/api/inventory",
        json={"name": "Wrench", "dealer_company_id": alpha["id"]},
        headers=auth_headers(user_a),
    )
    assert tool.status_code == 201, tool.text

    _hide(client, user_a, alpha["id"])
    client.post(
        "/api/dealers/list-restore", headers=auth_headers(user_a)
    )

    listed = client.get("/api/dealers/companies", headers=auth_headers(user_a))
    by_name = {c["name"]: c for c in listed.json()}
    assert by_name["A's Own Co"]["email"] == "own@example.com"
    assert by_name["Alpha Tools"]["id"] == alpha["id"]
    tool_after = client.get(
        f"/api/inventory/{tool.json()['id']}", headers=auth_headers(user_a)
    )
    assert tool_after.status_code == 200, tool_after.text
    assert tool_after.json()["dealer_company_id"] == alpha["id"]
