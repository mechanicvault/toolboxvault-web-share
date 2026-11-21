"""Agent card import (vCard -> PRIVATE dealer agents) — agent
card import lane, 2026-11-07.

Pins the shipped shape:
  - import creates the caller's own PRIVATE agent records
    only — never a platform/registered agent, never a claimed
    or verified state; registered agents still come into being
    only through signup + the code-claim flow;
  - preview is stateless and creates nothing: one row per
    readable card, the dealer the card's ORG suggests (exact
    name match against the companies the caller can see, raw
    or personal name), likely duplicates scoped PER DEALER
    (same collapsed name AND a shared phone or email with a
    private record under that dealer), unreadable cards as
    soft errors;
  - field mapping mirrors the export: first phone/email take
    the record's fields, extras ride in the notes as labeled
    lines, the NOTE's "Route area:" line comes back OUT into
    the record's location;
  - confirm creates exactly the handed rows through the
    ordinary private-agent create path, skipping failures;
  - an imported record confers NO flyer posting rights (the
    flyer gate's answer for a private-agent spot).
"""

import uuid

import pytest

from app.core import vcard
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.flyers import models as flyer_models
from app.modules.flyers import service as flyers_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, name):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(
        db, "TV-M-004201", "agent-cards-owner@example.com", [MECHANIC], "Olive Owner"
    )


@pytest.fixture()
def vera(db):
    return _make_user(
        db, "TV-M-004202", "agent-cards-vera@example.com", [MECHANIC], "Vera Second"
    )


@pytest.fixture()
def matco(db):
    row = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def snapon(db):
    row = dealer_models.DealerCompany(name="Snap-on", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _create_agent(client, user, company_id, name, **fields):
    resp = client.post(
        "/api/dealers/agents/private",
        json={"company_id": str(company_id), "name": name, **fields},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _preview(client, user, data: bytes):
    return client.post(
        "/api/dealers/agents/import/preview",
        files={"file": ("agents.vcf", data, "text/vcard")},
        headers=auth_headers(user),
    )


def _confirm(client, user, rows):
    return client.post(
        "/api/dealers/agents/import",
        json={"agents": rows},
        headers=auth_headers(user),
    )


def _my_agents(client, user):
    resp = client.get("/api/dealers/agents/private", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- round trip -------------------------------------------------------------------


def test_round_trip_export_then_import_for_another_user(
    client, owner, vera, matco
):
    """Owner exports Austin's card (route area, notes, phone,
    email, ORG); Vera imports it — every field lands where it
    started, under the suggested dealer, as HER private record."""
    agent = _create_agent(
        client,
        owner,
        matco.id,
        "Austin",
        phone="320-555-0147",
        email="austin@matco.example",
        notes="Tuesday truck.",
        location="Brainerd / Baxter area",
    )
    resp = client.get(
        f"/api/dealers/companies/{matco.id}/roster/agent/export.vcf",
        params={"kind": "private", "ref_id": agent["id"]},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    card_bytes = resp.text.encode()

    parsed, total = vcard.parse_vcf(card_bytes)
    assert total == 1 and parsed[0]["org"] == "Matco Tools"

    preview = _preview(client, vera, card_bytes)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total_cards"] == 1 and body["errors"] == []
    row = body["rows"][0]
    assert row["name"] == "Austin"
    assert row["phone"] == "320-555-0147"
    assert row["email"] == "austin@matco.example"
    assert row["location"] == "Brainerd / Baxter area"
    assert row["notes"] == "Tuesday truck."
    assert row["suggested_company_id"] == str(matco.id)
    assert row["suggested_company_name"] == "Matco Tools"
    assert row["duplicate"] is False
    # The preview created nothing for anyone.
    assert _my_agents(client, vera) == []
    assert len(_my_agents(client, owner)) == 1

    resp = _confirm(
        client,
        vera,
        [
            {
                "name": row["name"],
                "company_id": row["suggested_company_id"],
                "phone": row["phone"],
                "email": row["email"],
                "location": row["location"],
                "notes": row["notes"],
            }
        ],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["count"] == 1
    mine = _my_agents(client, vera)
    assert len(mine) == 1
    record = mine[0]
    assert record["name"] == "Austin"
    assert record["phone"] == "320-555-0147"
    assert record["email"] == "austin@matco.example"
    assert record["notes"] == "Tuesday truck."
    assert record["location"] == "Brainerd / Baxter area"
    assert record["company_id"] == str(matco.id)
    # A plain private record: no link, no claim, no platform state.
    assert record["linked_account_number"] is None
    assert record["claimed_by_name"] is None
    assert record["link_source"] is None
    assert record["archived"] is False


def test_phone_contacts_card_without_org_or_note(client, vera, snapon):
    """A phone-contacts-style card (no ORG, no NOTE) previews
    with no suggestion and empty location/notes; the owner's
    dealer pick is what the record lands under."""
    data = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Sam Route\r\n"
        "TEL;TYPE=CELL:218-555-0139\r\nEMAIL:sam@example.com\r\nEND:VCARD\r\n"
    ).encode()
    body = _preview(client, vera, data).json()
    row = body["rows"][0]
    assert row["org"] == ""
    assert row["suggested_company_id"] is None
    assert row["location"] == "" and row["notes"] == ""
    resp = _confirm(
        client,
        vera,
        [
            {
                "name": row["name"],
                "company_id": str(snapon.id),
                "phone": row["phone"],
                "email": row["email"],
                "location": row["location"],
                "notes": row["notes"],
            }
        ],
    )
    assert resp.status_code == 201, resp.text
    record = _my_agents(client, vera)[0]
    assert record["company_id"] == str(snapon.id)
    assert record["phone"] == "218-555-0139"
    assert record["email"] == "sam@example.com"


# -- dealer suggestion --------------------------------------------------------------


def test_suggestion_matches_case_and_whitespace(client, vera, matco):
    data = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Pat\nORG:  MATCO   TOOLS \nEND:VCARD\n"
    ).encode()
    row = _preview(client, vera, data).json()["rows"][0]
    assert row["suggested_company_id"] == str(matco.id)


def test_suggestion_matches_the_users_own_name_for_the_dealer(
    client, db, vera, matco
):
    """A card exported under the user's PERSONAL name for the
    dealer still matches — as does the raw directory name."""
    db.add(
        dealer_models.DealerCompanyPersonalEdit(
            user_id=vera.id, company_id=matco.id, name="My Matco"
        )
    )
    db.commit()
    for org in ("My Matco", "Matco Tools"):
        data = (
            f"BEGIN:VCARD\nVERSION:3.0\nFN:Pat\nORG:{org}\nEND:VCARD\n"
        ).encode()
        row = _preview(client, vera, data).json()["rows"][0]
        assert row["suggested_company_id"] == str(matco.id), org
        assert row["suggested_company_name"] == "My Matco"


def test_suggestion_prefers_a_roster_company_on_a_name_tie(
    client, db, vera, matco
):
    """Two visible companies with the same name: the one the
    user already has an agent with wins the suggestion."""
    twin = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(twin)
    db.commit()
    db.refresh(twin)
    _create_agent(client, vera, twin.id, "Existing Agent")
    data = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Pat\nORG:Matco Tools\nEND:VCARD\n"
    ).encode()
    row = _preview(client, vera, data).json()["rows"][0]
    assert row["suggested_company_id"] == str(twin.id)


def test_no_org_match_suggests_nothing(client, vera, matco):
    data = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Pat\nORG:Unknown Outfit\nEND:VCARD\n"
    ).encode()
    row = _preview(client, vera, data).json()["rows"][0]
    assert row["suggested_company_id"] is None
    assert row["org"] == "Unknown Outfit"


# -- duplicates, scoped per dealer ---------------------------------------------------


def test_duplicates_are_scoped_per_dealer(client, owner, matco, snapon):
    _create_agent(
        client, owner, matco.id, "Austin",
        phone="320-555-0147", email="austin@matco.example",
    )
    file = (
        # Same name + phone, card says Snap-on: NOT a duplicate
        # (the match lives under Matco) — but the per-dealer
        # list names Matco so a dealer change re-flags it.
        "BEGIN:VCARD\nVERSION:3.0\nFN:Austin\nTEL:320-555-0147\n"
        "ORG:Snap-on\nEND:VCARD\n"
        # Same name + phone, card says Matco: duplicate.
        "BEGIN:VCARD\nVERSION:3.0\nFN:Austin\nTEL:+1 320 555 0147\n"
        "ORG:Matco Tools\nEND:VCARD\n"
        # Same name only (different phone + email): not a duplicate.
        "BEGIN:VCARD\nVERSION:3.0\nFN:Austin\nTEL:218-555-0100\n"
        "EMAIL:other@example.com\nORG:Matco Tools\nEND:VCARD\n"
        # Shared email alone (different phone): duplicate.
        "BEGIN:VCARD\nVERSION:3.0\nFN:Austin\nTEL:218-555-9999\n"
        "EMAIL:AUSTIN@matco.example\nORG:Matco Tools\nEND:VCARD\n"
    ).encode()
    body = _preview(client, owner, file).json()
    rows = body["rows"]
    assert len(rows) == 4
    assert rows[0]["duplicate"] is False
    assert [(d["company_id"], d["duplicate_of"]) for d in rows[0]["duplicates"]] == [
        (str(matco.id), "Austin")
    ]
    assert rows[1]["duplicate"] is True
    assert rows[1]["duplicate_of"] == "Austin"
    assert rows[2]["duplicate"] is False and rows[2]["duplicates"] == []
    assert rows[3]["duplicate"] is True


def test_import_never_touches_a_platform_agent(client, db, vera, matco):
    """A connected platform agent with the same name + phone is
    NOT a duplicate (the check reads the private book only),
    and importing creates a separate private record — the
    platform profile and the existing connection stand."""
    andy = _make_user(
        db, "TV-D-004203", "andy-import@example.com", [DEALER], "Andy Agent"
    )
    db.add(
        dealer_models.AgentProfile(
            user_id=andy.id,
            display_name="Andy Agent",
            phone="612-555-0100",
            contact_email="andy@matco.example",
            service_area="Central Minnesota",
        )
    )
    db.add(
        dealer_models.PreferredAgent(
            user_id=vera.id,
            company_id=matco.id,
            agent_user_id=andy.id,
            is_preferred=True,
        )
    )
    db.commit()

    data = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Andy Agent\nTEL:612-555-0100\n"
        "ORG:Matco Tools\nEND:VCARD\n"
    ).encode()
    row = _preview(client, vera, data).json()["rows"][0]
    assert row["duplicate"] is False and row["duplicates"] == []

    resp = _confirm(
        client,
        vera,
        [
            {
                "name": "Andy Agent",
                "company_id": str(matco.id),
                "phone": "612-555-0100",
                "email": "",
                "location": "",
                "notes": "",
            }
        ],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["count"] == 1
    record = _my_agents(client, vera)[0]
    assert record["linked_account_number"] is None
    assert record["link_source"] is None
    # The platform side stands exactly as it was.
    assert db.query(dealer_models.AgentProfile).count() == 1
    platform_rows = (
        db.query(dealer_models.PreferredAgent)
        .filter(dealer_models.PreferredAgent.agent_user_id == andy.id)
        .all()
    )
    assert len(platform_rows) == 1 and platform_rows[0].is_preferred is True


# -- field mapping -------------------------------------------------------------------


def test_note_route_area_comes_out_and_extras_are_labeled(
    client, vera, matco
):
    data = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Multi Mike\r\n"
        "TEL;TYPE=CELL:612-555-0111\r\nTEL;TYPE=WORK:612-555-0112\r\n"
        "EMAIL:mike@example.com\r\nEMAIL;TYPE=WORK:mike2@example.com\r\n"
        "ORG:Matco Tools\r\n"
        "NOTE:First line.\\n\\nRoute area: North metro\r\n"
        "END:VCARD\r\n"
    ).encode()
    row = _preview(client, vera, data).json()["rows"][0]
    assert row["phone"] == "612-555-0111"
    assert row["email"] == "mike@example.com"
    assert row["location"] == "North metro"
    assert row["notes"].startswith("First line.")
    assert "Other phone: 612-555-0112" in row["notes"]
    assert "Other email: mike2@example.com" in row["notes"]
    assert "Route area" not in row["notes"]

    resp = _confirm(
        client,
        vera,
        [
            {
                "name": row["name"],
                "company_id": str(matco.id),
                "phone": row["phone"],
                "email": row["email"],
                "location": row["location"],
                "notes": row["notes"],
            }
        ],
    )
    assert resp.status_code == 201, resp.text
    record = _my_agents(client, vera)[0]
    assert record["location"] == "North metro"
    assert "Other phone: 612-555-0112" in record["notes"]


# -- preview honesty + confirm discipline ----------------------------------------------


def test_preview_errors_and_creates_nothing(client, owner, matco):
    _create_agent(client, owner, matco.id, "Existing")
    data = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Good Card\nEND:VCARD\n"
        "BEGIN:VCARD\nVERSION:3.0\nTEL:218-555-0100\nEND:VCARD\n"
    ).encode()
    body = _preview(client, owner, data).json()
    assert body["total_cards"] == 2
    assert [r["name"] for r in body["rows"]] == ["Good Card"]
    assert len(body["errors"]) == 1
    assert "no name" in body["errors"][0]["message"]
    assert len(_my_agents(client, owner)) == 1


def test_preview_rejects_a_cardless_file(client, owner):
    resp = _preview(client, owner, b"just some text, no cards here")
    assert resp.status_code == 422
    assert "doesn't contain any contact cards" in resp.json()["detail"]


def test_confirm_skips_rows_for_companies_the_user_cant_see(
    client, db, owner, vera, matco
):
    """A row naming someone else's private company fails the
    ordinary create path's visibility rule and is skipped —
    the good row beside it still lands."""
    hidden = dealer_models.DealerCompany(
        name="Owner's Private Co", is_directory=False, owner_id=owner.id
    )
    db.add(hidden)
    db.commit()
    db.refresh(hidden)
    resp = _confirm(
        client,
        vera,
        [
            {
                "name": "Sneaky Row",
                "company_id": str(hidden.id),
                "phone": "",
                "email": "",
                "location": "",
                "notes": "",
            },
            {
                "name": "Good Row",
                "company_id": str(matco.id),
                "phone": "",
                "email": "",
                "location": "",
                "notes": "",
            },
        ],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["count"] == 1
    mine = _my_agents(client, vera)
    assert [a["name"] for a in mine] == ["Good Row"]
    assert mine[0]["company_id"] == str(matco.id)


# -- the flyer gate ---------------------------------------------------------------------


def test_imported_agent_confers_no_flyer_posting_rights(
    client, db, owner, matco
):
    data = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Imported Ian\nTEL:612-555-0177\n"
        "ORG:Matco Tools\nEND:VCARD\n"
    ).encode()
    row = _preview(client, owner, data).json()["rows"][0]
    resp = _confirm(
        client,
        owner,
        [
            {
                "name": row["name"],
                "company_id": row["suggested_company_id"],
                "phone": row["phone"],
                "email": row["email"],
                "location": row["location"],
                "notes": row["notes"],
            }
        ],
    )
    assert resp.status_code == 201, resp.text
    imported = _my_agents(client, owner)[0]

    source = flyer_models.FlyerSource(
        kind=flyer_models.KIND_AGENT,
        company_id=matco.id,
        private_agent_id=uuid.UUID(imported["id"]),
        agent_user_id=None,
    )
    owner_row = db.get(core_models.User, owner.id)
    assert flyers_service.can_post_source(db, owner_row, source) is False
    with pytest.raises(flyers_service.FlyerError):
        flyers_service._assert_postable_shape(
            db,
            owner_row,
            kind=flyer_models.KIND_AGENT,
            company_id=matco.id,
            agent_user_id=None,
            private_agent_id=uuid.UUID(imported["id"]),
        )
