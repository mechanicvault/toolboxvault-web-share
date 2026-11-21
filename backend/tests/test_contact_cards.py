"""Contact cards (vCard import/export) — contact cards lane,
2026-11-07.

Pins the shipped shape:
  - the format library (app.core.vcard) builds 3.0 cards phone
    apps accept and parses the messy real world back: folded
    lines, quoted-printable 2.1 cards, grouped properties,
    tel:/mailto: values, a card with no name -> a soft error
    entry, a missing END:VCARD recovered;
  - borrower export (one + all) rides the owner's own rows; the
    free-text contact field splits into real TEL/EMAIL lines
    and any descriptive remainder survives in the NOTE;
  - import NEVER writes blind: preview parses + flags likely
    duplicates (same name AND a shared phone or email) and the
    confirm creates exactly the rows it is handed;
  - roster agent export (private + platform) mirrors the agent
    record view's authorization — not on the roster, no card.
"""

import uuid

import pytest

from app.core import vcard
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
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
        db, "TV-M-004101", "cards-owner@example.com", [MECHANIC], "Olive Owner"
    )


@pytest.fixture()
def stranger(db):
    return _make_user(
        db, "TV-M-004102", "cards-stranger@example.com", [MECHANIC], "Sue Stranger"
    )


def _borrower(client, user, name, contact="", notes=""):
    resp = client.post(
        "/api/borrowing/borrowers",
        json={"name": name, "contact": contact, "notes": notes},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# -- the format library ---------------------------------------------------------


def test_build_parse_round_trip():
    text = vcard.build_vcard(
        name="Neighbor Nate",
        phones=["612-428-0000"],
        emails=["nate@example.com"],
        org="Matco Tools",
        note="Has the big jack stands.\nSecond line, with comma",
    )
    assert text.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
    assert "FN:Neighbor Nate" in text
    cards, total = vcard.parse_vcf(text.encode())
    assert total == 1
    card = cards[0]
    assert card["name"] == "Neighbor Nate"
    assert card["phones"] == ["612-428-0000"]
    assert card["emails"] == ["nate@example.com"]
    assert card["org"] == "Matco Tools"
    assert card["note"] == "Has the big jack stands.\nSecond line, with comma"


def test_parse_messy_real_world_file():
    """2.1 quoted-printable + folded FN + grouped email +
    tel: URI + a nameless card + a missing END:VCARD."""
    raw = (
        "BEGIN:VCARD\r\n"
        "VERSION:2.1\r\n"
        "N;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:Garc=C3=ADa;Jos=C3=A9\r\n"
        "FN;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:Jos=C3=A9 Garc=C3=ADa\r\n"
        "item1.EMAIL;TYPE=INTERNET:jose@example.com\r\n"
        "TEL;TYPE=CELL:tel:+1-612-555-0142\r\n"
        "END:VCARD\r\n"
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        "FN:Folded Name That Goes On And On And On And On And On And On And\n"
        "  On Some More\n"
        "TEL:612-555-0117\n"
        "END:VCARD\n"
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        "TEL:612-555-0100\n"
        "END:VCARD\n"
        "BEGIN:VCARD\n"
        "VERSION:4.0\n"
        "FN:No End Card\n"
        "EMAIL:mailto:noend@example.com\n"
    ).encode("utf-8")
    cards, total = vcard.parse_vcf(raw)
    assert total == 4
    assert cards[0]["name"] == "José García"
    assert cards[0]["emails"] == ["jose@example.com"]
    assert cards[0]["phones"] == ["+1-612-555-0142"]
    assert cards[1]["name"].startswith("Folded Name")
    assert "On Some More" in cards[1]["name"]
    assert cards[2].get("error") == "no_name"
    assert cards[3]["name"] == "No End Card"
    assert cards[3]["emails"] == ["noend@example.com"]


def test_split_contact_text():
    phones, emails, leftover = vcard.split_contact_text(
        "612-428-0000, nate@example.com"
    )
    assert phones == ["612-428-0000"]
    assert emails == ["nate@example.com"]
    assert leftover == ""
    phones, emails, leftover = vcard.split_contact_text("the guy at the marina")
    assert phones == [] and emails == []
    assert leftover == "the guy at the marina"
    phones, emails, leftover = vcard.split_contact_text("")
    assert phones == [] and emails == [] and leftover == ""


# -- borrower export --------------------------------------------------------------


def test_export_all_and_one(client, owner, stranger):
    nate = _borrower(
        client, owner, "Neighbor Nate", "612-428-0000, nate@example.com",
        "Has the big jack stands.",
    )
    _borrower(client, owner, "Marina Mike", "the guy at the marina")

    resp = client.get(
        "/api/borrowing/borrowers/export.vcf", headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/vcard")
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.text
    assert body.count("BEGIN:VCARD") == 2
    assert "FN:Neighbor Nate" in body
    assert "TEL;TYPE=CELL:612-428-0000" in body
    assert "EMAIL;TYPE=INTERNET:nate@example.com" in body
    # The descriptive contact text survives in the note, not dropped.
    assert "the guy at the marina" in body

    resp = client.get(
        f"/api/borrowing/borrowers/{nate['id']}/export.vcf",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.text.count("BEGIN:VCARD") == 1
    assert "neighbor-nate.vcf" in resp.headers["content-disposition"]

    # Someone else's contact is not exportable.
    resp = client.get(
        f"/api/borrowing/borrowers/{nate['id']}/export.vcf",
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 404


MESSY_VCF = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "FN:Neighbor Nate\r\n"
    "TEL;TYPE=CELL:612-428-0000\r\n"
    "EMAIL:nate@example.com\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "FN:Cousin Carla\r\n"
    "TEL:218-555-0139\r\n"
    "ORG:Carla's Upholstery\r\n"
    "NOTE:Does seat work.\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "TEL:218-555-0100\r\n"
    "END:VCARD\r\n"
).encode("utf-8")


def _preview(client, user, data: bytes):
    return client.post(
        "/api/borrowing/borrowers/import/preview",
        files={"file": ("contacts.vcf", data, "text/vcard")},
        headers=auth_headers(user),
    )


def test_import_preview_flags_duplicates_and_errors(client, owner):
    _borrower(client, owner, "Neighbor Nate", "612-428-0000")
    resp = _preview(client, owner, MESSY_VCF)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_cards"] == 3
    rows = {r["name"]: r for r in body["rows"]}
    assert rows["Neighbor Nate"]["duplicate"] is True
    assert rows["Neighbor Nate"]["duplicate_of"] == "Neighbor Nate"
    assert rows["Cousin Carla"]["duplicate"] is False
    # The card's ORG has no book field: preserved in the notes.
    assert "Organization: Carla's Upholstery" in rows["Cousin Carla"]["notes"]
    assert len(body["errors"]) == 1
    assert "no name" in body["errors"][0]["message"]
    # Preview created nothing.
    book = client.get(
        "/api/borrowing/borrowers", headers=auth_headers(owner)
    ).json()
    assert len(book) == 1


def test_import_confirm_creates_only_confirmed_rows(client, owner):
    preview = _preview(client, owner, MESSY_VCF).json()
    chosen = [
        {"name": r["name"], "contact": r["contact"], "notes": r["notes"]}
        for r in preview["rows"]
        if r["name"] == "Cousin Carla"
    ]
    resp = client.post(
        "/api/borrowing/borrowers/import",
        json={"contacts": chosen},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["count"] == 1
    book = client.get(
        "/api/borrowing/borrowers", headers=auth_headers(owner)
    ).json()
    assert [c["name"] for c in book] == ["Cousin Carla"]
    assert book[0]["contact"] == "218-555-0139"
    # Round trip: exporting the book reproduces the card.
    body = client.get(
        "/api/borrowing/borrowers/export.vcf", headers=auth_headers(owner)
    ).text
    cards, total = vcard.parse_vcf(body.encode())
    assert total == 1
    assert cards[0]["name"] == "Cousin Carla"
    assert cards[0]["phones"] == ["218-555-0139"]


def test_import_rejects_cardless_file(client, owner):
    resp = _preview(client, owner, b"just some text, no cards here")
    assert resp.status_code == 422
    assert "doesn't contain any contact cards" in resp.json()["detail"]


def test_import_preview_duplicate_needs_name_and_a_shared_channel(
    client, owner
):
    """Same name alone is NOT a duplicate — a shared phone or
    email must also match (the spec's rule)."""
    _borrower(client, owner, "Sam Smith", "218-555-0101")
    other = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Sam Smith\nTEL:218-555-9999\nEND:VCARD\n"
    ).encode()
    body = _preview(client, owner, other).json()
    assert body["rows"][0]["duplicate"] is False


# -- agent export -----------------------------------------------------------------


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_export_private_agent_card(client, owner, stranger, company):
    resp = client.post(
        "/api/dealers/agents/private",
        json={
            "company_id": str(company.id),
            "name": "Austin",
            "phone": "320-555-0147",
            "email": "austin@matco.example",
            "notes": "Tuesday truck.",
            "location": "Brainerd / Baxter area",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    agent_id = resp.json()["id"]

    resp = client.get(
        f"/api/dealers/companies/{company.id}/roster/agent/export.vcf",
        params={"kind": "private", "ref_id": agent_id},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert "FN:Austin" in resp.text
    assert "TEL;TYPE=CELL:320-555-0147" in resp.text
    assert "EMAIL;TYPE=INTERNET:austin@matco.example" in resp.text
    assert "ORG:Matco Tools" in resp.text
    assert "Tuesday truck." in resp.text
    assert "Route area: Brainerd / Baxter area" in resp.text

    # Not on the stranger's roster -> no card.
    resp = client.get(
        f"/api/dealers/companies/{company.id}/roster/agent/export.vcf",
        params={"kind": "private", "ref_id": agent_id},
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 404


def test_export_platform_agent_card(client, db, owner, company):
    agent = _make_user(
        db, "TV-D-004103", "andy-cards@example.com", [DEALER], "Andy Agent"
    )
    db.add(
        dealer_models.AgentProfile(
            user_id=agent.id,
            display_name="Andy Agent",
            phone="612-555-0100",
            contact_email="andy@matco.example",
            service_area="Central Minnesota",
        )
    )
    db.add(
        dealer_models.PreferredAgent(
            user_id=owner.id,
            company_id=company.id,
            agent_user_id=agent.id,
            is_preferred=True,
        )
    )
    db.commit()

    resp = client.get(
        f"/api/dealers/companies/{company.id}/roster/agent/export.vcf",
        params={"kind": "platform", "ref_id": str(agent.id)},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert "FN:Andy Agent" in resp.text
    assert "TEL;TYPE=CELL:612-555-0100" in resp.text
    assert "EMAIL;TYPE=INTERNET:andy@matco.example" in resp.text
    assert "ORG:Matco Tools" in resp.text
    assert "Route area: Central Minnesota" in resp.text
