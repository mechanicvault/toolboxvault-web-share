"""Account groups (owner directive 2026-10-17, multi-select as
corrected): the account number carries the letters of ALL the
account's groups in canonical order (M, S, D, I); setting/changing
the set re-segments the number with the digits preserved; access
checks are unions over the set.

The 2026-10-17 "signup forces a non-empty group SET" rule was
superseded by the onboarding design (owner 2026-10-31, built
2026-11-07): signup is just an account, the set starts empty, and
the pick is the setup wizard's step 1. What survives of the old
contract: a set that IS sent is validated exactly as before
(unknown groups and non-self-serve groups are 422), and the
account-type EDITOR still refuses an empty set. The onboarding
behavior itself is pinned in test_onboarding.py.

Signup over HTTP needs Postgres nextval(), so — like the rest of the
suite — account creation is covered at the service level with the
allocator stubbed, while everything past creation (the endpoint,
/me, the gate dependency) runs over real HTTP on SQLite.
"""

import itertools
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.deps import CurrentUser, require_account_type
from app.modules.core import schemas, service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
DEALER = "tool_dealer"
INSURANCE = "insurance"


@pytest.fixture()
def allocator(monkeypatch):
    """Stub the sequence allocator with an incrementing plain number."""
    counter = itertools.count(100)
    monkeypatch.setattr(
        service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(db, email: str, account_types: list[str]):
    return service.create_user(db, email, "Group User", "some-password", account_types)


# -- the pick (moved to the wizard, 2026-11-07) -------------------------------


def test_signup_schema_no_longer_requires_a_group_set():
    # Onboarding: signup is just an account. Missing AND empty
    # sets both validate now — the wizard's step 1 makes the pick.
    req = schemas.SignupRequest(
        email="a@example.com", name="A", password="secret1",
    )
    assert req.account_types == []
    req = schemas.SignupRequest(
        email="a@example.com", name="A", password="secret1", account_types=[],
    )
    assert req.account_types == []


def test_signup_schema_rejects_an_unknown_group():
    with pytest.raises(ValidationError):
        schemas.SignupRequest(
            email="a@example.com",
            name="A",
            password="secret1",
            account_types=["wizard"],
            country="US", currency="USD", locale="en",
        )


def test_signup_http_invalid_group_set_is_422(client):
    base = {
        "email": "http@example.com", "name": "H", "password": "secret1",
        "country": "US", "currency": "USD", "locale": "en",
    }
    # A set that IS sent is still validated at the door: an
    # unknown group never reaches account creation.
    assert (
        client.post(
            "/api/core/signup", json={**base, "account_types": ["wizard"]}
        ).status_code
        == 422
    )


# -- the number reflects the set ----------------------------------------------


@pytest.mark.parametrize(
    ("account_types", "segment"),
    [
        ([MECHANIC], "M"),
        ([SHOP], "S"),
        ([DEALER], "D"),
        ([INSURANCE], "I"),
        ([DEALER, MECHANIC], "MD"),  # sent out of order; stored canonical
        ([INSURANCE, DEALER, SHOP, MECHANIC], "MSDI"),
    ],
)
def test_signup_number_carries_all_group_letters(db, allocator, account_types, segment):
    user = _signup(db, f"{segment}@example.com", account_types)
    assert user.account_number.startswith(f"TV-{segment}-")
    assert user.account_types == service.canonical_order(account_types)


def test_format_account_number_helper():
    assert service.format_account_number("000123", []) == "TV-000123"
    assert service.format_account_number("000123", [SHOP]) == "TV-S-000123"
    assert service.format_account_number("000123", [DEALER, MECHANIC]) == "TV-MD-000123"


def test_oauth_user_starts_with_an_empty_set_and_plain_number(db, allocator):
    user = service.create_oauth_user(db, "oauth-groups@example.com", "O")
    assert user.account_types == []
    assert "-" not in user.account_number.removeprefix("TV-")


# -- set / change via the endpoint --------------------------------------------


def test_account_type_endpoint_sets_groups_number_never_changes(client, user_a):
    # user_a predates groups: plain number, empty set.
    assert user_a.account_number == "TV-000001"
    response = client.post(
        "/api/core/account-type",
        json={"account_types": [DEALER, MECHANIC]},
        headers=auth_headers(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["account_types"] == [MECHANIC, DEALER]  # canonical order
    # Sweep fix 10-F12: the number signup told the user to keep
    # NEVER changes — the first pick does not re-segment it.
    assert body["account_number"] == "TV-000001"


def test_account_type_endpoint_change_keeps_the_same_number(client, user_a):
    client.post(
        "/api/core/account-type",
        json={"account_types": [DEALER, MECHANIC]},
        headers=auth_headers(user_a),
    )
    response = client.post(
        "/api/core/account-type",
        json={"account_types": [SHOP]},
        headers=auth_headers(user_a),
    )
    assert response.status_code == 200
    assert response.json()["account_types"] == [SHOP]
    # A later group change does not rewrite the number either.
    assert response.json()["account_number"] == "TV-000001"


# -- insurance: off the self-serve list (owner directive 2026-10-31) ---------
#
# The group stays in the system — the service layer (the operator's
# provisioning path) accepts the full vocabulary, an operator-assigned
# insurance group survives self-serve edits, and insurer surfaces keep
# working. Only the self-serve PICKS (signup, choose-group, Settings)
# no longer offer it.


def test_signup_schema_rejects_insurance():
    base = {
        "email": "a@example.com",
        "name": "A",
        "password": "secret1",
        "country": "US",
        "currency": "USD",
        "locale": "en",
    }
    with pytest.raises(ValidationError):
        schemas.SignupRequest(**base, account_types=[INSURANCE])
    with pytest.raises(ValidationError):
        schemas.SignupRequest(**base, account_types=[MECHANIC, INSURANCE])


def test_signup_http_insurance_is_422(client):
    base = {
        "email": "http-ins@example.com",
        "name": "H",
        "password": "secret1",
        "country": "US",
        "currency": "USD",
        "locale": "en",
    }
    assert (
        client.post(
            "/api/core/signup", json={**base, "account_types": [INSURANCE]}
        ).status_code
        == 422
    )


def test_account_type_endpoint_cannot_add_insurance(client, user_a):
    response = client.post(
        "/api/core/account-type",
        json={"account_types": [MECHANIC, INSURANCE]},
        headers=auth_headers(user_a),
    )
    assert response.status_code == 200
    # Insurance is silently NOT granted; the pickable group lands.
    assert response.json()["account_types"] == [MECHANIC]
    # The number never changes (10-F12): user_a was born plain.
    assert response.json()["account_number"] == "TV-000001"
    # A set with no pickable group at all is still refused.
    assert (
        client.post(
            "/api/core/account-type",
            json={"account_types": [INSURANCE]},
            headers=auth_headers(user_a),
        ).status_code
        == 422
    )


def test_service_still_provisions_insurance(db, allocator):
    # The operator path: service.create_user takes the full vocabulary.
    user = _signup(db, "provisioned-insurer@example.com", [INSURANCE])
    assert user.account_types == [INSURANCE]
    assert "-I-" in user.account_number


def test_operator_assigned_insurance_survives_self_serve_edits(
    client, db, allocator
):
    insurer = _signup(db, "op-insurer@example.com", [INSURANCE])
    # The insurer adds a pickable group self-serve: insurance is kept.
    response = client.post(
        "/api/core/account-type",
        json={"account_types": [DEALER]},
        headers=auth_headers(insurer),
    )
    assert response.status_code == 200
    assert response.json()["account_types"] == [DEALER, INSURANCE]
    # The number never changes (10-F12): born TV-I-…, stays TV-I-…
    # even though the group set grew a dealer.
    assert response.json()["account_number"] == insurer.account_number
    assert response.json()["account_number"].startswith("TV-I-")
    # ...and a later self-serve save can't drop it either.
    response = client.post(
        "/api/core/account-type",
        json={"account_types": [INSURANCE]},
        headers=auth_headers(insurer),
    )
    assert response.status_code == 200
    assert response.json()["account_types"] == [INSURANCE]


def test_provisioned_insurer_signs_in_and_uses_insurer_surfaces(
    client, db, allocator
):
    # Control proof: an operator-provisioned insurer account works
    # end to end — password sign-in, /me carries the group, and the
    # insurer profile surface answers.
    service.create_user(
        db,
        "control-insurer@example.com",
        "Ina Insurer",
        "insurer-password",
        [INSURANCE],
    )
    login = client.post(
        "/api/core/login",
        json={"email": "control-insurer@example.com", "password": "insurer-password"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/core/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["account_types"] == [INSURANCE]
    put = client.put(
        "/api/core/insurance",
        json={"insurer_company": "Acme Mutual", "agent_name": "Ina Insurer"},
        headers=headers,
    )
    assert put.status_code == 200
    assert put.json()["has_profile"] is True
    assert put.json()["insurer_company"] == "Acme Mutual"


def test_account_type_endpoint_rejects_empty_and_unknown(client, user_a):
    assert (
        client.post(
            "/api/core/account-type",
            json={"account_types": []},
            headers=auth_headers(user_a),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/core/account-type",
            json={"account_types": ["wizard"]},
            headers=auth_headers(user_a),
        ).status_code
        == 422
    )


def test_account_type_endpoint_requires_auth(client):
    assert (
        client.post("/api/core/account-type", json={"account_types": [DEALER]}).status_code
        == 401
    )


def test_service_refuses_an_empty_set(db, user_a):
    with pytest.raises(ValueError):
        service.set_account_types(db, user_a, [])


# -- /me exposure ---------------------------------------------------------------


def test_me_exposes_the_group_set(client, user_a):
    me = client.get("/api/core/me", headers=auth_headers(user_a))
    assert me.status_code == 200
    assert me.json()["account_types"] == []
    client.post(
        "/api/core/account-type",
        json={"account_types": [SHOP]},
        headers=auth_headers(user_a),
    )
    me = client.get("/api/core/me", headers=auth_headers(user_a))
    assert me.json()["account_types"] == [SHOP]
    # The number never changes (10-F12).
    assert me.json()["account_number"] == "TV-000001"


# -- the gate dependency (union semantics) ---------------------------------------


def _principal(account_types: tuple[str, ...]) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        account_number="TV-MD-000009",
        email="gate@example.com",
        name="Gate",
        email_verified=True,
        created_at=datetime.now(timezone.utc),
        account_types=account_types,
    )


def test_require_account_type_passes_on_any_match():
    gate = require_account_type(DEALER)
    principal = _principal((MECHANIC, DEALER))
    assert gate(user=principal) is principal


def test_require_account_type_union_across_named_groups():
    gate = require_account_type(DEALER, INSURANCE)
    assert gate(user=_principal((INSURANCE,))) is not None


def test_require_account_type_rejects_non_members_and_unpicked():
    gate = require_account_type(DEALER)
    for principal in (_principal((MECHANIC,)), _principal(())):
        with pytest.raises(Exception) as excinfo:
            gate(user=principal)
        assert getattr(excinfo.value, "status_code", None) == 403


def test_require_account_type_rejects_unknown_group_names():
    with pytest.raises(ValueError):
        require_account_type("wizard")
