"""Dealers near you (widget wave 2, 2026-11-10): the dashboard
widget's read — the viewer's OWN ZIP, from the postal address on
their profile, run through the Find local Agent search.

Honesty bar: no ZIP on file is a STATE (no_location), never an
empty list pretending nobody is near; a ZIP outside the bundled
centroid dataset is unknown_zip; results are exactly the
find-local search's (publicly listed + territory + VERIFIED
representation), flattened one row per (agent, company) with the
company's logo fields, nearest first, distances to the nearest
point of the agent's territory.

Dataset ground truth (bundled GeoNames centroids): Little Falls,
MN 56345 = (45.9811, -94.3604); Brainerd, MN 56401 = (46.3502,
-94.1), 28.38 mi away. A radius-10 territory centered on Brainerd
sits 18.38 mi from Little Falls.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"

LF_LAT, LF_LNG = 45.9811, -94.3604
BR_LAT, BR_LNG = 46.3502, -94.1


def _make_user(db, account_number, email, account_types, name="User", **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def mechanic(db):
    return _make_user(
        db, "TV-M-000801", "mech-near@example.com", (MECHANIC,),
        name="Mike Mechanic",
        postal_address="21925 Haven Rd\nLittle Falls, MN 56345",
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000800", "op-near@example.com", (MECHANIC,),
        name="Op Erator", is_operator=True,
    )


def _agent(db, number, email, name):
    return _make_user(db, number, email, (DEALER,), name=name)


def _directory_company(client, operator, name="Matco Tools"):
    resp = client.post(
        "/api/admin/dealer-companies",
        json={"name": name, "email": "", "website": "", "address": "",
              "phones": [], "notes": ""},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _represent(client, user, company_id, *, verify=False, operator=None):
    resp = client.post(
        "/api/dealers/profile/me/representations",
        json={"company_id": company_id},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    rep = resp.json()
    if verify:
        resp = client.put(
            f"/api/admin/dealer-representations/{rep['id']}/verify",
            json={"verified": True},
            headers=auth_headers(operator),
        )
        assert resp.status_code == 200, resp.text
    return rep


def _profile(client, user, **overrides):
    payload = {
        "display_name": "",
        "phone": "555-0100",
        "contact_email": "agent@truck.example",
        "service_area": "Central Minnesota",
        "bio": "",
    }
    payload.update(overrides)
    resp = client.put(
        "/api/dealers/profile/me", json=payload, headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _listed_radius_agent(
    client, user, company_id, *, operator=None, verify=True,
    center=(LF_LAT, LF_LNG), center_zip="56345", miles=25, **profile_kw
):
    _represent(client, user, company_id, verify=verify, operator=operator)
    _profile(
        client, user,
        area_type="radius", area_zip=center_zip,
        area_center_lat=center[0], area_center_lng=center[1],
        area_radius_miles=miles, publicly_listed=True,
        **profile_kw,
    )


def _near(client, viewer, **params):
    resp = client.get(
        "/api/dealers/near-you", params=params, headers=auth_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_location_is_a_state_not_an_empty_list(client, db):
    viewer = _make_user(
        db, "TV-M-000802", "noloc-near@example.com", (MECHANIC,),
        name="No Location",
    )
    body = _near(client, viewer)
    assert body["state"] == "no_location"
    assert body["zip"] is None
    assert body["point"] is None
    assert body["results"] == []
    # An address without any ZIP reads the same way.
    viewer.postal_address = "Somewhere in Minnesota"
    db.commit()
    assert _near(client, viewer)["state"] == "no_location"


def test_unknown_zip_is_its_own_state(client, db):
    viewer = _make_user(
        db, "TV-M-000803", "badzip-near@example.com", (MECHANIC,),
        name="Bad Zip", postal_address="1 Nowhere Ln\nNowhere, ZZ 00000",
    )
    body = _near(client, viewer)
    assert body["state"] == "unknown_zip"
    assert body["zip"] == "00000"
    assert body["results"] == []


def test_nearest_first_with_honest_distances_and_logo_fields(
    client, db, mechanic, operator
):
    matco = _directory_company(client, operator)
    andy = _agent(db, "TV-D-000801", "andy-near@example.com", "Andy Agent")
    _listed_radius_agent(client, andy, matco["id"], operator=operator)
    beth = _agent(db, "TV-D-000802", "beth-near@example.com", "Beth Agent")
    _listed_radius_agent(
        client, beth, matco["id"], operator=operator,
        center=(BR_LAT, BR_LNG), center_zip="56401", miles=10,
    )

    body = _near(client, mechanic)
    assert body["state"] == "ok"
    assert body["zip"] == "56345"
    assert body["point"]["display_name"] == "Little Falls, MN 56345"
    assert body["radius_miles"] == 50.0
    # Covers (0 mi) first, then the Brainerd territory at ~18.4 mi.
    assert [r["display_name"] for r in body["results"]] == [
        "Andy Agent", "Beth Agent",
    ]
    first, second = body["results"]
    assert first["covers_zip"] is True
    assert first["distance_miles"] == 0.0
    assert second["covers_zip"] is False
    assert second["distance_miles"] == pytest.approx(18.4, abs=0.15)
    # One row per (agent, company); the logo seat rides along.
    assert [c["company_name"] for c in first["companies"]] == ["Matco Tools"]
    company = first["companies"][0]
    assert company["company_id"] == matco["id"]
    assert company["logo_url"] is None  # no harvested logo on this record
    assert company["logo_tile"] is None
    assert company["connected"] is False

    # A tighter widget radius keeps the covering agent only.
    body = _near(client, mechanic, radius_miles=10)
    assert [r["display_name"] for r in body["results"]] == ["Andy Agent"]


def test_none_near_when_radius_excludes_everyone(client, db, mechanic, operator):
    matco = _directory_company(client, operator)
    beth = _agent(db, "TV-D-000802", "beth-near@example.com", "Beth Agent")
    _listed_radius_agent(
        client, beth, matco["id"], operator=operator,
        center=(BR_LAT, BR_LNG), center_zip="56401", miles=10,
    )
    body = _near(client, mechanic, radius_miles=10)
    assert body["state"] == "none_near"
    assert body["zip"] == "56345"
    assert body["results"] == []


def test_unverified_and_unlisted_agents_never_appear(
    client, db, mechanic, operator
):
    matco = _directory_company(client, operator)
    carl = _agent(db, "TV-D-000803", "carl-near@example.com", "Carl Agent")
    _listed_radius_agent(client, carl, matco["id"], verify=False)
    body = _near(client, mechanic)
    assert body["state"] == "none_near"
    assert body["results"] == []


def test_radius_bounds(client, mechanic):
    for bad in (0, 501):
        resp = client.get(
            "/api/dealers/near-you",
            params={"radius_miles": bad},
            headers=auth_headers(mechanic),
        )
        assert resp.status_code == 422, bad
