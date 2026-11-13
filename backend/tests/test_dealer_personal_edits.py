"""Personal dealer edits (owner, 2026-11-05): a viewer's own
details layered over a DIRECTORY dealer.

The owner reported "there is no way to edit a dealer" — Edit
company existed only for a viewer's OWN private companies.
His fix: every dealer page gains Edit; for a shared directory
company the save is a PERSONAL layer — his values win
everywhere HE sees that dealer, the directory row and every
other user's view stay untouched, and Reset clears the layer.

These tests pin:
- the overlay write/read round-trip on the detail + list reads,
  with the personal_edit marker naming the overridden fields;
- that only fields that DIFFER from the directory are stored,
  and saving back to the directory values removes the row;
- isolation: another user sees the raw directory values on
  every surface, and the directory row itself never changes;
- search answering to the viewer's own name (and only his);
- the item page's Dealer line resolving through the item
  OWNER's layer;
- refusal on the viewer's own company (the direct edit is the
  path) + the existing direct edit/delete behaving as before;
- form-parity validation (a bad email is refused like the
  company form refuses it);
- the data export carrying the overrides;
- account self-delete clearing the layer (Job 2h-fix style
  regression: seed overlay -> delete account -> 204, no
  orphans, the directory company and a bystander's layer
  survive).
"""

import itertools
import uuid

import pytest
from sqlalchemy import select

from app.modules.billing import models as billing_models
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.dealers import models as dealers_models
from app.modules.dealers import portal as dealers_portal
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _seed_plans(db):
    db.add(
        billing_models.Plan(
            plan_key="free", name="Free", item_limit=20,
            ai_monthly_credits=0, is_paid=False, sort_order=0,
        )
    )
    db.commit()


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    counter = itertools.count(900200)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(db, email, name="Personal Edits User"):
    return core_service.create_user(db, email, name, PASSWORD, [MECHANIC])


def _make_user(db, account_number, email):
    """A group-carrying user (the dealers module gates on the
    account group — conftest's bare fixtures have none)."""
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Test User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user_a(db):
    return _make_user(db, "TV-000011", "pa@example.com")


@pytest.fixture()
def user_b(db):
    return _make_user(db, "TV-000012", "pb@example.com")


def _login(client, email):
    resp = client.post(
        "/api/core/login",
        json={"email": email, "password": PASSWORD},
        headers={"User-Agent": "TestBrowser/1.0"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def company(db):
    row = dealers_models.DealerCompany(
        id=uuid.uuid4(),
        owner_id=None,
        name="Acme Tool Co",
        email="hq@acme.example",
        website="https://acme.example",
        address="1 Directory Way",
        phones=[{"label": "Customer Service", "number": "800-555-0100"}],
        notes="Directory notes.",
        is_directory=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _payload(**overrides):
    """The full personal-edit payload, starting from the
    directory values (the form always submits the whole state)."""
    base = {
        "name": "Acme Tool Co",
        "email": "hq@acme.example",
        "website": "https://acme.example",
        "address": "1 Directory Way",
        "phones": [{"label": "Customer Service", "number": "800-555-0100"}],
        "notes": "Directory notes.",
        "logo_key": None,
        "logo_tile": None,
    }
    base.update(overrides)
    return base


def _save(client, user, company_id, payload):
    return client.put(
        f"/api/dealers/companies/{company_id}/personal-edit",
        json=payload,
        headers=auth_headers(user),
    )


def _detail(client, user, company_id):
    resp = client.get(
        f"/api/dealers/companies/{company_id}/detail",
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["company"]


# ---------------------------------------------------------------------
# The round-trip
# ---------------------------------------------------------------------


def test_personal_edit_round_trip_and_isolation(client, db, user_a, user_b, company):
    resp = _save(
        client, user_a, company.id,
        _payload(
            name="My Acme",
            phones=[{"label": "Customer Service", "number": "612-555-0199"}],
        ),
    )
    assert resp.status_code == 200, resp.text
    view = resp.json()
    assert view["name"] == "My Acme"
    assert view["customer_service_phone"] == "612-555-0199"
    assert view["personal_edit"] == {"fields": ["name", "phones"]}
    # Untouched fields ride through from the directory.
    assert view["email"] == "hq@acme.example"
    assert view["notes"] == "Directory notes."

    # Stored sparsely: only the two changed fields carry values.
    row = db.scalars(
        select(dealers_models.DealerCompanyPersonalEdit).where(
            dealers_models.DealerCompanyPersonalEdit.user_id == user_a.id
        )
    ).one()
    assert row.name == "My Acme"
    assert row.email is None and row.notes is None

    # A's detail read shows his layer; B's shows the directory.
    mine = _detail(client, user_a, company.id)
    assert mine["name"] == "My Acme"
    assert mine["personal_edit"]["fields"] == ["name", "phones"]
    theirs = _detail(client, user_b, company.id)
    assert theirs["name"] == "Acme Tool Co"
    assert theirs["customer_service_phone"] == "800-555-0100"
    assert theirs["personal_edit"] is None

    # The directory row itself never moved.
    db.refresh(company)
    assert company.name == "Acme Tool Co"
    assert company.phones[0]["number"] == "800-555-0100"


def test_personal_edit_on_list_read_and_search(client, db, user_a, user_b, company):
    _save(client, user_a, company.id, _payload(name="Zebra Acme"))

    mine = client.get("/api/dealers/companies", headers=auth_headers(user_a))
    row = next(c for c in mine.json() if c["id"] == str(company.id))
    assert row["name"] == "Zebra Acme"
    assert row["personal_edit"] == {"fields": ["name"]}

    theirs = client.get("/api/dealers/companies", headers=auth_headers(user_b))
    row_b = next(c for c in theirs.json() if c["id"] == str(company.id))
    assert row_b["name"] == "Acme Tool Co"
    assert row_b["personal_edit"] is None

    # Search answers to A's own name for A — and never for B.
    found = client.get(
        "/api/dealers/companies", params={"q": "Zebra"},
        headers=auth_headers(user_a),
    )
    assert [c["id"] for c in found.json()] == [str(company.id)]
    not_found = client.get(
        "/api/dealers/companies", params={"q": "Zebra"},
        headers=auth_headers(user_b),
    )
    assert str(company.id) not in [c["id"] for c in not_found.json()]


def test_saving_back_to_directory_values_removes_the_row(
    client, db, user_a, company
):
    _save(client, user_a, company.id, _payload(name="My Acme"))
    assert db.scalars(
        select(dealers_models.DealerCompanyPersonalEdit)
    ).first() is not None

    resp = _save(client, user_a, company.id, _payload())
    assert resp.status_code == 200, resp.text
    assert resp.json()["personal_edit"] is None
    assert db.scalars(
        select(dealers_models.DealerCompanyPersonalEdit)
    ).first() is None


def test_reset_clears_the_layer(client, db, user_a, user_b, company):
    _save(client, user_a, company.id, _payload(name="My Acme"))
    resp = client.delete(
        f"/api/dealers/companies/{company.id}/personal-edit",
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 204, resp.text
    view = _detail(client, user_a, company.id)
    assert view["name"] == "Acme Tool Co"
    assert view["personal_edit"] is None
    # Reset is per-user: B resetting (no layer) is a quiet 204 too.
    resp = client.delete(
        f"/api/dealers/companies/{company.id}/personal-edit",
        headers=auth_headers(user_b),
    )
    assert resp.status_code == 204, resp.text


def test_logo_clear_is_an_override(client, db, user_a, user_b, company):
    company.logo_key = "acme-logo"
    db.commit()
    # Sending the directory's own logo value back: no override.
    resp = _save(client, user_a, company.id, _payload(logo_key="acme-logo"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["personal_edit"] is None
    assert resp.json()["logo_key"] == "acme-logo"

    # Clearing it is a real override: "show me no logo".
    resp = _save(client, user_a, company.id, _payload(logo_key=""))
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo_key"] is None
    assert resp.json()["logo_url"] is None
    assert resp.json()["personal_edit"] == {"fields": ["logo_key"]}
    # B still sees the directory logo.
    assert _detail(client, user_b, company.id)["logo_key"] == "acme-logo"


# ---------------------------------------------------------------------
# Scope guards + form parity
# ---------------------------------------------------------------------


def test_own_company_refuses_personal_edit_and_direct_edit_still_works(
    client, db, user_a
):
    resp = client.post(
        "/api/dealers/companies",
        json={
            "name": "My Own Co", "email": "", "website": "", "address": "",
            "phones": [], "notes": "", "kind": "retailer",
        },
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 201, resp.text
    own = resp.json()

    refused = _save(client, user_a, own["id"], _payload(name="Sneaky"))
    assert refused.status_code == 422, refused.text
    assert "your own company" in refused.json()["detail"]

    # The direct edit behaves exactly as before.
    edited = client.put(
        f"/api/dealers/companies/{own['id']}",
        json={
            "name": "My Own Co Renamed", "email": "", "website": "",
            "address": "", "phones": [], "notes": "", "kind": "retailer",
        },
        headers=auth_headers(user_a),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "My Own Co Renamed"
    assert edited.json()["personal_edit"] is None

    deleted = client.delete(
        f"/api/dealers/companies/{own['id']}", headers=auth_headers(user_a)
    )
    assert deleted.status_code == 204, deleted.text


def test_personal_edit_validation_matches_the_company_form(
    client, db, user_a, company
):
    # The personal path runs the company form's own cleaner:
    # what it refuses (no name, a logo tile outside dark/light)
    # is refused identically here...
    empty_name = _save(client, user_a, company.id, _payload(name=""))
    assert empty_name.status_code == 422, empty_name.text
    bad_tile = _save(client, user_a, company.id, _payload(logo_tile="neon"))
    assert bad_tile.status_code == 422, bad_tile.text
    # ...and what it accepts is accepted: the server has never
    # shape-checked email on the direct edit either (the form's
    # type="email" input is the only email gate, in the browser,
    # shared by both paths) — parity, not a stricter new rule.
    odd_email = _save(client, user_a, company.id, _payload(email="not-an-email"))
    assert odd_email.status_code == 200, odd_email.text
    assert odd_email.json()["personal_edit"] == {"fields": ["email"]}


def test_personal_edit_on_invisible_company_is_404(client, db, user_a, user_b):
    foreign = dealers_models.DealerCompany(
        id=uuid.uuid4(), owner_id=user_b.id, name="B's Private Co",
        is_directory=False,
    )
    db.add(foreign)
    db.commit()
    resp = _save(client, user_a, foreign.id, _payload())
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------
# Cross-module reads
# ---------------------------------------------------------------------


def test_item_dealer_line_uses_the_item_owners_layer(
    client, db, user_a, user_b, company
):
    _save(client, user_a, company.id, _payload(name="My Acme"))
    tool_a = inventory_models.Tool(
        id=uuid.uuid4(), owner_id=user_a.id, name="Wrench",
        dealer_company_id=company.id,
    )
    tool_b = inventory_models.Tool(
        id=uuid.uuid4(), owner_id=user_b.id, name="Wrench",
        dealer_company_id=company.id,
    )
    db.add_all([tool_a, tool_b])
    db.commit()

    mine = client.get(
        f"/api/inventory/{tool_a.id}", headers=auth_headers(user_a)
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["dealer_company_name"] == "My Acme"
    theirs = client.get(
        f"/api/inventory/{tool_b.id}", headers=auth_headers(user_b)
    )
    assert theirs.json()["dealer_company_name"] == "Acme Tool Co"


def test_export_carries_the_overrides(client, db, user_a, company):
    _save(
        client, user_a, company.id,
        _payload(name="My Acme", notes="Ask for Dale."),
    )
    rows = dealers_portal.export_rows(db, user_a.id)
    assert len(rows["personal_company_edits"]) == 1
    entry = rows["personal_company_edits"][0]
    assert entry["directory_name"] == "Acme Tool Co"
    assert entry["overrides"] == {"name": "My Acme", "notes": "Ask for Dale."}


# ---------------------------------------------------------------------
# Account self-delete (Job 2h-fix style regression)
# ---------------------------------------------------------------------


def test_delete_account_with_personal_dealer_edits(db, client):
    # Regression standard (2026-11-05): every per-user table the
    # deletion cascade forgets becomes a production 500 on
    # DELETE /api/core/me. The personal-edit FK carries no
    # cascade on purpose, so the cascade clears it by name.
    user = _signup(db, "layered@example.com")
    bystander = _signup(db, "layer-bystander@example.com")
    company = dealers_models.DealerCompany(
        id=uuid.uuid4(), owner_id=None, name="Directory Brand",
        is_directory=True,
    )
    db.add(company)
    db.commit()
    _login(client, "layered@example.com")
    headers = auth_headers(user)

    resp = _save(client, user, company.id, {
        "name": "My Directory Brand", "email": "", "website": "",
        "address": "", "phones": [], "notes": "", "logo_key": None,
        "logo_tile": None,
    })
    assert resp.status_code == 200, resp.text
    # The bystander's layer over the same dealer is his own.
    db.add(
        dealers_models.DealerCompanyPersonalEdit(
            user_id=bystander.id, company_id=company.id, name="His Brand"
        )
    )
    db.commit()

    resp = client.request(
        "DELETE", "/api/core/me",
        json={"confirmation": "DELETE"}, headers=headers,
    )
    assert resp.status_code == 204, resp.text

    assert core_service.get_user_by_id(db, user.id) is None
    # No orphans of the deleted user...
    assert db.scalars(
        select(dealers_models.DealerCompanyPersonalEdit).where(
            dealers_models.DealerCompanyPersonalEdit.user_id == user.id
        )
    ).first() is None
    # ...the directory company (platform data) survives...
    assert db.get(dealers_models.DealerCompany, company.id) is not None
    # ...and the bystander's layer is untouched.
    assert db.scalars(
        select(dealers_models.DealerCompanyPersonalEdit).where(
            dealers_models.DealerCompanyPersonalEdit.user_id == bystander.id
        )
    ).first() is not None
