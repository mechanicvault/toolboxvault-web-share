"""Wave 3 — insurer accounts + directory.

Ryan's scope ruling: directory + profiles + pick-your-insurer,
NOT direct claim filing. Pins:

- the directory starts EMPTY (no invented seed data) and is
  operator-CRUD'd with audit rows, mirroring the dealer
  directory; regular users can read it but never write it;
- insurance-group users hold an Insurer Profile (affiliation):
  pick a directory company + role; UNVERIFIED until an operator
  verifies (audit rows on the flip); changing company resets
  verification;
- My Insurance gains pick-from-directory: the link fills the
  free-text name (editable after), free text remains the
  fallback, the link exports in insurance.json and dies cleanly
  (SET NULL) when the directory row is deleted;
- HARD PIN 1: picking a company alone shares NOTHING — the
  policyholders view lists only users who ALSO enabled tier
  sharing toward the insurance group;
- HARD PIN 2: an UNVERIFIED affiliation sees no policyholder
  view at all.
"""

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
INSURANCE = "insurance"


def _make_user(db, account_number, email, account_types, name="User", operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-000401", "ins-op@example.com", [MECHANIC], "Op", operator=True
    )


@pytest.fixture()
def insurer(db):
    return _make_user(
        db, "TV-I-000402", "ins-agent@example.com", [INSURANCE], "Ina Insurer"
    )


@pytest.fixture()
def holder(db):
    return _make_user(
        db, "TV-M-000403", "ins-holder@example.com", [MECHANIC], "Hank Holder"
    )


def _create_company(client, operator, name="Acme Mutual"):
    response = client.post(
        "/api/admin/insurer-companies",
        json={
            "name": name,
            "website": "https://acme.example",
            "phones": [{"label": "Claims", "number": "800-555-0100"}],
            "address": "1 Claims Way",
            "notes": "",
        },
        headers=auth_headers(operator),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _verify_affiliation(client, db, operator, insurer_user):
    rows = client.get(
        "/api/admin/insurer-affiliations", headers=auth_headers(operator)
    ).json()
    mine = next(r for r in rows if r["user_id"] == str(insurer_user.id))
    response = client.put(
        f"/api/admin/insurer-affiliations/{mine['id']}/verified",
        json={"verified": True},
        headers=auth_headers(operator),
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- directory -------------------------------------------------------------------


def test_directory_starts_empty_and_is_operator_curated(client, db, operator, holder):
    # Starts EMPTY — no seed data is invented.
    assert client.get(
        "/api/core/insurers/directory", headers=auth_headers(holder)
    ).json() == []
    # Regular users cannot write the directory.
    assert (
        client.post(
            "/api/admin/insurer-companies",
            json={"name": "Nope"},
            headers=auth_headers(holder),
        ).status_code
        == 403
    )
    company = _create_company(client, operator)
    assert company["phones"] == [{"label": "Claims", "number": "800-555-0100"}]
    listed = client.get(
        "/api/core/insurers/directory", headers=auth_headers(holder)
    ).json()
    assert [c["name"] for c in listed] == ["Acme Mutual"]

    updated = client.put(
        f"/api/admin/insurer-companies/{company['id']}",
        json={"name": "Acme Mutual Insurance", "phones": []},
        headers=auth_headers(operator),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Acme Mutual Insurance"

    actions = {
        row.action
        for row in db.scalars(select(core_models.AuditLog)).all()
    }
    assert "insurer_company.create" in actions
    assert "insurer_company.update" in actions

    deleted = client.delete(
        f"/api/admin/insurer-companies/{company['id']}",
        headers=auth_headers(operator),
    )
    assert deleted.status_code == 204
    assert client.get(
        "/api/core/insurers/directory", headers=auth_headers(holder)
    ).json() == []


# -- affiliation ---------------------------------------------------------------------


def test_affiliation_lifecycle_and_verification(client, db, operator, insurer, holder):
    company = _create_company(client, operator)
    # Only insurance-group accounts hold an insurer profile.
    refused = client.put(
        "/api/core/insurers/affiliation",
        json={"company_id": company["id"], "role_at_company": "Adjuster"},
        headers=auth_headers(holder),
    )
    assert refused.status_code == 422

    mine = client.put(
        "/api/core/insurers/affiliation",
        json={"company_id": company["id"], "role_at_company": "Claims adjuster"},
        headers=auth_headers(insurer),
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["verified"] is False
    assert mine.json()["company_name"] == "Acme Mutual"

    verified = _verify_affiliation(client, db, operator, insurer)
    assert verified["verified"] is True
    actions = {
        row.action for row in db.scalars(select(core_models.AuditLog)).all()
    }
    assert "insurer_affiliation.verify" in actions

    # Changing company resets verification (a fresh claim to review).
    other = _create_company(client, operator, name="Beacon Assurance")
    changed = client.put(
        "/api/core/insurers/affiliation",
        json={"company_id": other["id"], "role_at_company": "Agent"},
        headers=auth_headers(insurer),
    )
    assert changed.json()["verified"] is False


# -- pick-your-insurer on My Insurance ------------------------------------------------


def test_my_insurance_pick_from_directory(client, db, operator, holder):
    company = _create_company(client, operator)
    saved = client.put(
        "/api/core/insurance",
        json={"insurer_company_id": company["id"]},
        headers=auth_headers(holder),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    # Picking FILLS the name from the directory…
    assert body["insurer_company"] == "Acme Mutual"
    assert body["insurer_company_id"] == company["id"]
    assert body["insurer_company_name"] == "Acme Mutual"
    # …and the name stays editable afterwards (free text fallback intact).
    edited = client.put(
        "/api/core/insurance",
        json={
            "insurer_company_id": company["id"],
            "insurer_company": "Acme Mutual (my agent's office)",
        },
        headers=auth_headers(holder),
    )
    assert edited.json()["insurer_company"] == "Acme Mutual (my agent's office)"
    # Unlinking keeps the typed name.
    unlinked = client.put(
        "/api/core/insurance",
        json={"insurer_company_id": None, "insurer_company": "Typed By Hand Co"},
        headers=auth_headers(holder),
    )
    assert unlinked.json()["insurer_company_id"] is None
    assert unlinked.json()["insurer_company"] == "Typed By Hand Co"
    # A bogus company id is refused, not silently stored.
    bogus = client.put(
        "/api/core/insurance",
        json={"insurer_company_id": str(uuid.uuid4())},
        headers=auth_headers(holder),
    )
    assert bogus.status_code == 422


def test_insurance_export_carries_the_link_and_directory_delete_set_nulls(
    client, db, operator, holder
):
    company = _create_company(client, operator)
    client.put(
        "/api/core/insurance",
        json={"insurer_company_id": company["id"]},
        headers=auth_headers(holder),
    )
    exported = client.get("/api/core/export", headers=auth_headers(holder))
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        payload = json.loads(archive.read("insurance.json"))
    assert payload["profile"]["insurer_company_id"] == company["id"]
    assert payload["profile"]["insurer_company_name"] == "Acme Mutual"

    # Directory delete: the link SET NULLs; the typed name survives.
    client.delete(
        f"/api/admin/insurer-companies/{company['id']}",
        headers=auth_headers(operator),
    )
    profile = client.get("/api/core/insurance", headers=auth_headers(holder)).json()
    assert profile["insurer_company_id"] is None
    assert profile["insurer_company"] == "Acme Mutual"


# -- policyholders: the two hard pins ------------------------------------------------------


def _holder_shares(db, holder, *, enabled=True):
    tool = inventory_models.Tool(
        owner_id=holder.id, name="Holder wrench", brand="GearWrench",
        model="", serial_number="", purchase_price=120,
    )
    db.add(tool)
    db.flush()
    db.add(
        core_models.ShareConfig(
            owner_id=holder.id, recipient_group="insurance",
            enabled=enabled, fields=[],
        )
    )
    db.add(
        core_models.SharedItem(
            owner_id=holder.id, item_kind="tool", tool_id=tool.id,
            recipient_group="insurance",
        )
    )
    db.commit()
    return tool


def _affiliate(client, insurer, company, role="Adjuster"):
    return client.put(
        "/api/core/insurers/affiliation",
        json={"company_id": company["id"], "role_at_company": role},
        headers=auth_headers(insurer),
    )


def test_unverified_affiliation_sees_no_policyholders(client, db, operator, insurer, holder):
    company = _create_company(client, operator)
    _holder_shares(db, holder)
    client.put(
        "/api/core/insurance",
        json={"insurer_company_id": company["id"]},
        headers=auth_headers(holder),
    )
    _affiliate(client, insurer, company)
    # HARD PIN 2: affiliation exists but is UNVERIFIED → no view.
    response = client.get(
        "/api/core/insurers/policyholders", headers=auth_headers(insurer)
    )
    assert response.status_code == 422


def test_picking_a_company_alone_shares_nothing(client, db, operator, insurer, holder):
    company = _create_company(client, operator)
    tool = _holder_shares(db, holder, enabled=False)  # picked items, sharing OFF
    client.put(
        "/api/core/insurance",
        json={"insurer_company_id": company["id"]},
        headers=auth_headers(holder),
    )
    _affiliate(client, insurer, company)
    _verify_affiliation(client, db, operator, insurer)
    # HARD PIN 1: verified + picked, but sharing toward insurance
    # is OFF → the policyholder does not appear at all.
    listed = client.get(
        "/api/core/insurers/policyholders", headers=auth_headers(insurer)
    )
    assert listed.status_code == 200
    assert listed.json() == []
    preview = client.get(
        f"/api/core/insurers/policyholders/{holder.id}/preview",
        headers=auth_headers(insurer),
    )
    assert preview.status_code == 404

    # Turn sharing ON: the SAME machinery now serves the preview.
    config = db.scalars(
        select(core_models.ShareConfig).where(
            core_models.ShareConfig.owner_id == holder.id
        )
    ).first()
    config.enabled = True
    db.commit()
    listed = client.get(
        "/api/core/insurers/policyholders", headers=auth_headers(insurer)
    ).json()
    assert [(r["name"], r["item_count"]) for r in listed] == [("Hank Holder", 1)]
    preview = client.get(
        f"/api/core/insurers/policyholders/{holder.id}/preview",
        headers=auth_headers(insurer),
    )
    assert preview.status_code == 200
    assert [row["name"] for row in preview.json()] == ["Holder wrench"]
    assert tool is not None


def test_policyholders_only_from_the_picked_company(client, db, operator, insurer, holder):
    acme = _create_company(client, operator)
    beacon = _create_company(client, operator, name="Beacon Assurance")
    _holder_shares(db, holder)
    client.put(
        "/api/core/insurance",
        json={"insurer_company_id": beacon["id"]},  # holder picked BEACON
        headers=auth_headers(holder),
    )
    _affiliate(client, insurer, acme)  # insurer represents ACME
    _verify_affiliation(client, db, operator, insurer)
    listed = client.get(
        "/api/core/insurers/policyholders", headers=auth_headers(insurer)
    ).json()
    assert listed == []
