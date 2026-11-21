"""Dealer agent rework stage 3 (2026-11-05): Find local Agent —
ZIP + radius search over the stage-1/2026-10-20 service-area
machinery, and the connect that joins a found agent to the
roster.

Findability bar (the search AND the connect enforce the same):
a publicly listed agent profile WITH a defined service area AND
a VERIFIED representation — the card's companies are the verified
ones only, because those are the companies a connect attaches
to. Distance is measured to the NEAREST point of the agent's
territory (0 = the territory covers the ZIP itself).

Dataset ground truth (bundled GeoNames centroids): Little Falls,
MN 56345 = (45.9811, -94.3604); Brainerd, MN 56401 = (46.3502,
-94.1), 28.38 mi away. A radius-10 territory centered on Brainerd
therefore sits 18.38 mi from Little Falls; the Little Falls
polygon's nearest edge sits ~13.96 mi from Brainerd.
"""

import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"

LF_LAT, LF_LNG = 45.9811, -94.3604
BR_LAT, BR_LNG = 46.3502, -94.1
LF_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-94.62, 45.80],
            [-94.10, 45.84],
            [-94.14, 46.15],
            [-94.60, 46.10],
            [-94.62, 45.80],
        ]
    ],
}


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
        db, "TV-M-000701", "mech-s3@example.com", (MECHANIC,), name="Mike Mechanic"
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000700", "op-s3@example.com", (MECHANIC,),
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
    """A findable agent: representation (+ verified on request) and
    a listed radius territory."""
    _represent(client, user, company_id, verify=verify, operator=operator)
    _profile(
        client, user,
        area_type="radius", area_zip=center_zip,
        area_center_lat=center[0], area_center_lng=center[1],
        area_radius_miles=miles, publicly_listed=True,
        **profile_kw,
    )


def _search(client, viewer, **params):
    resp = client.get(
        "/api/dealers/find-local-agent", params=params,
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _names(body):
    return [r["display_name"] for r in body["results"]]


# -- the search ------------------------------------------------------------------


def test_covers_first_then_nearest_distance(client, db, mechanic, operator):
    matco = _directory_company(client, operator)
    andy = _agent(db, "TV-D-000701", "andy-s3@example.com", "Andy Agent")
    _represent(client, andy, matco["id"], verify=True, operator=operator)
    _profile(
        client, andy, area_type="polygon", area_polygon=LF_POLYGON,
        publicly_listed=True,
    )
    beth = _agent(db, "TV-D-000702", "beth-s3@example.com", "Beth Agent")
    _listed_radius_agent(
        client, beth, matco["id"], operator=operator,
        center=(BR_LAT, BR_LNG), center_zip="56401", miles=10,
        display_name="Beth Agent",
    )

    body = _search(client, mechanic, zip_code="56345", radius_miles=25)
    assert body["zip"] == "56345"
    assert body["point"]["display_name"] == "Little Falls, MN 56345"
    # Covers (0 mi) first, then the Brainerd territory at ~18.4 mi.
    assert _names(body) == ["Andy Agent", "Beth Agent"]
    assert body["results"][0]["covers_zip"] is True
    assert body["results"][0]["distance_miles"] == 0.0
    assert body["results"][1]["covers_zip"] is False
    assert body["results"][1]["distance_miles"] == pytest.approx(18.4, abs=0.15)
    # The card carries only verified companies + the connection state.
    card = body["results"][0]
    assert [c["company_name"] for c in card["companies"]] == ["Matco Tools"]
    assert card["companies"][0]["connected"] is False
    assert card["phone"] == "555-0100"  # published contact rides along

    # A tighter radius keeps the covering agent, drops the far one.
    body = _search(client, mechanic, zip_code="56345", radius_miles=15)
    assert _names(body) == ["Andy Agent"]


def test_polygon_distance_from_outside(client, db, mechanic, operator):
    matco = _directory_company(client, operator)
    andy = _agent(db, "TV-D-000701", "andy-s3@example.com", "Andy Agent")
    _represent(client, andy, matco["id"], verify=True, operator=operator)
    _profile(
        client, andy, area_type="polygon", area_polygon=LF_POLYGON,
        publicly_listed=True,
    )
    # Brainerd sits ~13.96 mi from the polygon's nearest edge.
    body = _search(client, mechanic, zip_code="56401", radius_miles=25)
    assert _names(body) == ["Andy Agent"]
    assert body["results"][0]["distance_miles"] == pytest.approx(14.0, abs=0.3)
    body = _search(client, mechanic, zip_code="56401", radius_miles=10)
    assert body["results"] == []


def test_verified_rep_is_the_findability_bar(client, db, mechanic, operator):
    matco = _directory_company(client, operator)
    carl = _agent(db, "TV-D-000703", "carl-s3@example.com", "Carl Agent")
    _listed_radius_agent(client, carl, matco["id"], verify=False)
    # Listed + area, but the representation is unverified: invisible.
    assert _search(client, mechanic, zip_code="56345", radius_miles=25)["results"] == []
    assert _search(
        client, mechanic, zip_code="56345", radius_miles=25,
        company_id=matco["id"],
    )["results"] == []
    rep = (
        db.query(dealer_models.CompanyRepresentation)
        .filter_by(agent_user_id=carl.id, company_id=uuid.UUID(matco["id"]))
        .one()
    )
    resp = client.put(
        f"/api/admin/dealer-representations/{rep.id}/verify",
        json={"verified": True}, headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text
    body = _search(client, mechanic, zip_code="56345", radius_miles=25)
    assert _names(body) == ["Carl Agent"]


def test_scoped_search_needs_that_companys_verified_rep(
    client, db, mechanic, operator
):
    matco = _directory_company(client, operator)
    snap = _directory_company(client, operator, "Snap-on")
    andy = _agent(db, "TV-D-000701", "andy-s3@example.com", "Andy Agent")
    _listed_radius_agent(client, andy, matco["id"], operator=operator)
    body = _search(
        client, mechanic, zip_code="56345", radius_miles=25,
        company_id=snap["id"],
    )
    assert body["results"] == []
    body = _search(
        client, mechanic, zip_code="56345", radius_miles=25,
        company_id=matco["id"],
    )
    assert _names(body) == ["Andy Agent"]
    assert [c["company_name"] for c in body["results"][0]["companies"]] == [
        "Matco Tools"
    ]


def test_unlisted_and_arealess_profiles_never_appear(
    client, db, mechanic, operator
):
    matco = _directory_company(client, operator)
    dana = _agent(db, "TV-D-000704", "dana-s3@example.com", "Dana Agent")
    _represent(client, dana, matco["id"], verify=True, operator=operator)
    _profile(
        client, dana, area_type="radius", area_zip="56345",
        area_center_lat=LF_LAT, area_center_lng=LF_LNG,
        area_radius_miles=25, publicly_listed=False,
    )
    # A listed-in-the-table profile with NO area (the portal refuses
    # this state through the API; the search must still skip it).
    erin = _agent(db, "TV-D-000705", "erin-s3@example.com", "Erin Agent")
    _represent(client, erin, matco["id"], verify=True, operator=operator)
    db.add(
        dealer_models.AgentProfile(
            user_id=erin.id, display_name="Erin Agent",
            service_area="Central Minnesota", publicly_listed=True,
        )
    )
    db.commit()
    body = _search(client, mechanic, zip_code="56345", radius_miles=25)
    assert body["results"] == []


def test_viewer_never_finds_themselves(client, db, mechanic, operator):
    matco = _directory_company(client, operator)
    selfy = _agent(db, "TV-D-000706", "selfy-s3@example.com", "Selfy Searcher")
    _listed_radius_agent(client, selfy, matco["id"], operator=operator)
    # His own listing is real (another searcher sees it) but his
    # own search skips it — connecting to yourself is refused
    # everywhere, so listing yourself would be noise.
    body = _search(client, selfy, zip_code="56345", radius_miles=25)
    assert body["results"] == []
    body = _search(client, mechanic, zip_code="56345", radius_miles=25)
    assert _names(body) == ["Selfy Searcher"]


def test_unknown_zip_and_radius_bounds(client, mechanic):
    resp = client.get(
        "/api/dealers/find-local-agent", params={"zip_code": "00000"},
        headers=auth_headers(mechanic),
    )
    assert resp.status_code == 422
    assert "couldn't find that zip" in resp.json()["detail"].lower()
    for bad in (0, 501):
        resp = client.get(
            "/api/dealers/find-local-agent",
            params={"zip_code": "56345", "radius_miles": bad},
            headers=auth_headers(mechanic),
        )
        assert resp.status_code == 422, bad


# -- the connect -------------------------------------------------------------------


def _connect(client, viewer, company_id, agent_user_id):
    return client.post(
        "/api/dealers/find-local-agent/connect",
        json={"company_id": company_id, "agent_user_id": str(agent_user_id)},
        headers=auth_headers(viewer),
    )


def test_connect_joins_roster_flagged_first_and_idempotent(
    client, db, mechanic, operator
):
    matco = _directory_company(client, operator)
    andy = _agent(db, "TV-D-000701", "andy-s3@example.com", "Andy Agent")
    _listed_radius_agent(client, andy, matco["id"], operator=operator)

    resp = _connect(client, mechanic, matco["id"], andy.id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] is True
    # The user's FIRST agent for the company takes the flag.
    assert body["preferred"]["is_preferred"] is True
    assert body["preferred"]["agent_user_id"] == str(andy.id)

    # The roster (the Listed-agents read) shows him as a platform
    # connection, and the search now reports him connected.
    roster = client.get(
        f"/api/dealers/companies/{matco['id']}/roster",
        headers=auth_headers(mechanic),
    ).json()
    platform = [e for e in roster if e["kind"] == "platform"]
    assert [e["agent_user_id"] for e in platform] == [str(andy.id)]
    assert platform[0]["is_preferred"] is True
    card = _search(client, mechanic, zip_code="56345", radius_miles=25)["results"][0]
    assert card["companies"][0]["connected"] is True
    assert card["companies"][0]["is_preferred"] is True

    # Re-connecting changes nothing: same row, created False.
    resp = _connect(client, mechanic, matco["id"], andy.id)
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] is False
    rows = (
        db.query(dealer_models.PreferredAgent)
        .filter_by(user_id=mechanic.id, agent_user_id=andy.id)
        .all()
    )
    assert len(rows) == 1


def test_connect_second_agent_is_a_plain_connection(
    client, db, mechanic, operator
):
    matco = _directory_company(client, operator)
    andy = _agent(db, "TV-D-000701", "andy-s3@example.com", "Andy Agent")
    _listed_radius_agent(client, andy, matco["id"], operator=operator)
    beth = _agent(db, "TV-D-000702", "beth-s3@example.com", "Beth Agent")
    _listed_radius_agent(client, beth, matco["id"], operator=operator)
    assert _connect(client, mechanic, matco["id"], andy.id).status_code == 201
    resp = _connect(client, mechanic, matco["id"], beth.id)
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] is True
    assert resp.json()["preferred"]["is_preferred"] is False


def test_connect_refusals(client, db, mechanic, operator):
    matco = _directory_company(client, operator)
    carl = _agent(db, "TV-D-000703", "carl-s3@example.com", "Carl Agent")
    _listed_radius_agent(client, carl, matco["id"], verify=False)
    # Unverified rep — the search never showed him; the door refuses.
    resp = _connect(client, mechanic, matco["id"], carl.id)
    assert resp.status_code == 422
    assert "verified rep" in resp.json()["detail"]
    # Self-connect.
    resp = _connect(client, mechanic, matco["id"], mechanic.id)
    assert resp.status_code == 422
    # A company that isn't in the directory.
    resp = _connect(client, mechanic, str(uuid.uuid4()), carl.id)
    assert resp.status_code == 422
    # An agent who was never listed.
    dana = _agent(db, "TV-D-000704", "dana-s3@example.com", "Dana Agent")
    _represent(client, dana, matco["id"], verify=True, operator=operator)
    resp = _connect(client, mechanic, matco["id"], dana.id)
    assert resp.status_code == 422
    assert "listed for local search" in resp.json()["detail"]
