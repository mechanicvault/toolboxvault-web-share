"""Reports fixes (Ryan, 2026-11-07, from hands-on testing of
the redesigned page):

  - Job 4: the seeded "Open truck accounts" quick report is a
    FULL LEDGER for each OPEN account (statement shape, running
    balances), not a by-agent summary — and a template seeded
    BEFORE the fix (settings carry only its format) produces
    the new output, because templates store type + settings and
    generation flows through the dataset.
  - Job 2/3 seam: a saved template runs in the format the
    caller picks at run time, and only in a format the type
    honestly supports — the catalog's format matrix is the
    promise. (Every type carries PDF + CSV + XLSX since the
    admin-door lane built the activity XLSX producer,
    completing Ryan's 2026-11-07 "PDF or excel" order; the
    matrix test below pins the completed matrix.)
  - The dealer-accounts report (the other surface over the
    same ledger sections) keeps its behavior: every account,
    closed included.
"""

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.reports import activity, catalog, library
from app.modules.reports import models as reports_models
from app.modules.truck_accounts import models as truck_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="Rae Reports"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000411", "fixes@example.com")


class _FakeStorage:
    """Dict-backed object store (the redesign tests' pattern)."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def object_key(self, owner_id, item_id, kind, filename, collection="tools"):
        return f"{owner_id}/{collection}/{item_id}/{kind}/{filename}"

    def put_bytes(self, key, data, content_type):
        self.objects[key] = bytes(data)
        return storage_module.StoredObject(
            key=key, size_bytes=len(data), content_type=content_type
        )

    def fetch(self, key):
        if key not in self.objects:
            raise storage_module.StorageError("missing")
        return self.objects[key]

    def delete(self, key):
        self.objects.pop(key, None)

    def presigned_get_url(self, key, expires_in=3600):
        return f"https://files.test/get/{key}"


@pytest.fixture()
def fake_storage(monkeypatch):
    fake = _FakeStorage()
    for name in ("object_key", "put_bytes", "fetch", "delete", "presigned_get_url"):
        monkeypatch.setattr(storage_module.storage, name, getattr(fake, name))
    return fake


def _company_with_agent(db, owner, agent_name="Austin"):
    company = dealer_models.DealerCompany(name="Mac Tools")
    db.add(company)
    db.flush()
    agent = dealer_models.PrivateAgent(
        id=uuid.uuid4(), owner_id=owner.id, company_id=company.id, name=agent_name
    )
    db.add(agent)
    db.commit()
    return company, agent


def _truck_account(db, owner, company, agent, status, entries):
    account = truck_models.TruckAccount(
        dealer_company_id=company.id,
        dealer_company_name=company.name,
        private_agent_id=agent.id if agent else None,
        agent_name_snapshot=agent.name if agent else "",
        customer_user_id=owner.id,
        customer_email=owner.email,
        customer_name=owner.name,
        status=status,
        payment_cadence="weekly",
        invite_token=f"tok-{uuid.uuid4().hex}",
    )
    db.add(account)
    db.flush()
    for kind, amount, when in entries:
        db.add(
            truck_models.TruckEntry(
                account_id=account.id,
                kind=kind,
                amount=Decimal(amount),
                entry_date=when,
                source="manual",
            )
        )
    db.commit()
    db.refresh(account)
    return account


# -- Job 4: the dataset -------------------------------------------------


def test_open_truck_accounts_running_balances_per_open_account(db, owner):
    company, austin = _company_with_agent(db, owner)
    _truck_account(
        db, owner, company, austin, "active",
        [
            ("charge", "75.00", date(2026, 6, 1)),
            ("charge", "50.00", date(2026, 6, 8)),
            ("payment", "-25.00", date(2026, 6, 15)),
        ],
    )
    _truck_account(
        db, owner, company, austin, "closed",
        [("charge", "999.00", date(2026, 5, 1))],
    )

    report = activity.build_open_truck_accounts(db, owner)
    assert report["kind"] == "open_truck_accounts"
    assert report["ledger_table"] is True
    assert len(report["sections"]) == 1
    section = report["sections"][0]
    rows = section["rows"]
    assert [r["item"] for r in rows] == ["Charge", "Charge", "Payment"]
    assert [r["date"] for r in rows] == ["2026-06-01", "2026-06-08", "2026-06-15"]
    # Running balances step down the ledger, and the last one
    # ties to both the section total and the banner total —
    # the amount owed on the account.
    assert [r["balance"] for r in rows] == ["75.00", "125.00", "100.00"]
    assert section["total"] == "100.00"
    assert report["totals"][0]["amount"] == "100.00"
    assert report["totals"][0]["park"] == "right"


def test_dealer_accounts_still_covers_closed_accounts(db, owner):
    """The shared section builder didn't move the dedicated
    dealer-accounts report: it still ledgers EVERY account the
    owner is a party to, closed included (its labels carry the
    status)."""
    company, austin = _company_with_agent(db, owner)
    _truck_account(
        db, owner, company, austin, "active",
        [("charge", "75.00", date(2026, 6, 1))],
    )
    _truck_account(
        db, owner, company, austin, "closed",
        [("charge", "999.00", date(2026, 5, 1))],
    )
    report = activity.build_dealer_accounts(db, owner)
    assert len(report["sections"]) == 2
    assert {s["total"] for s in report["sections"]} == {"75.00", "999.00"}


def test_seeded_truck_template_produces_the_full_ledger(
    client, db, owner, fake_storage
):
    """Flow-through: the default template was seeded with the
    pre-fix settings shape ({"format": "pdf"} — settings never
    carried the report's shape). Running THAT row must produce
    the full-ledger document, in CSV (text-checkable) and PDF
    alike."""
    company, austin = _company_with_agent(db, owner)
    _truck_account(
        db, owner, company, austin, "active",
        [
            ("charge", "75.00", date(2026, 6, 1)),
            ("payment", "-25.00", date(2026, 6, 15)),
        ],
    )
    _truck_account(
        db, owner, company, austin, "closed",
        [("charge", "999.00", date(2026, 5, 1))],
    )

    templates = library.list_templates(db, owner)
    truck = next(r for r in templates if r.report_type == "open_truck_accounts")
    assert truck.is_default
    assert truck.settings == {"format": "pdf"}

    csv_bytes = library.generate_bytes(
        db, owner, "open_truck_accounts", dict(truck.settings), "csv"
    )
    text = csv_bytes.decode("utf-8")
    assert "2026-06-01" in text and "2026-06-15" in text
    assert "75.00" in text and "-25.00" in text
    # The closed account's charge never reaches the document.
    assert "999" not in text

    resp = client.post(
        f"/api/reports/templates/{truck.id}/run",
        json={},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert entry["format"] == "pdf"
    stored = fake_storage.objects[
        db.get(reports_models.GeneratedReport, uuid.UUID(entry["id"])).storage_key
    ]
    assert stored.startswith(b"%PDF")


# -- Job 1 companion: the viewer's "Email this file" ---------------------


def test_history_email_endpoint_owner_scoped_and_recorded(
    client, db, owner, fake_storage
):
    """The generation viewer carries the same Email action a
    document on a tool offers: POST /reports/history/{id}/email
    with the entry's own key sends the stored file through the
    notifications seam (outbox row, attachment note and all).
    Another user's entry is a 404-shaped refusal; a key that
    isn't the entry's file is a 422; a bad recipient is a 422."""
    me = owner
    other = _make_user(db, "TV-M-000412", "fixes-other@example.com", "Other")
    generated = client.post(
        "/api/reports/generate",
        json={"report_type": "open_truck_accounts", "format": "pdf"},
        headers=auth_headers(me),
    )
    assert generated.status_code == 201, generated.text
    entry = generated.json()
    view = client.get(
        f"/api/reports/history/{entry['id']}/view", headers=auth_headers(me)
    ).json()["attachment"]

    refused = client.post(
        f"/api/reports/history/{entry['id']}/email",
        json={"key": view["key"], "recipient": "crew@example.com"},
        headers=auth_headers(other),
    )
    assert refused.status_code == 404, refused.text

    wrong_key = client.post(
        f"/api/reports/history/{entry['id']}/email",
        json={"key": "someone/else.pdf", "recipient": "crew@example.com"},
        headers=auth_headers(me),
    )
    assert wrong_key.status_code == 422, wrong_key.text

    bad_recipient = client.post(
        f"/api/reports/history/{entry['id']}/email",
        json={"key": view["key"], "recipient": "not-an-email"},
        headers=auth_headers(me),
    )
    assert bad_recipient.status_code == 422, bad_recipient.text

    sent = client.post(
        f"/api/reports/history/{entry['id']}/email",
        json={"key": view["key"], "recipient": "crew@example.com"},
        headers=auth_headers(me),
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["sent"] is True
    assert body["kind"] == "report"
    assert body["recipient"] == "crew@example.com"
    assert body["filename"].endswith(".pdf")

    outbox = db.query(core_models.EmailOutbox).all()
    assert len(outbox) == 1
    assert outbox[0].recipient == "crew@example.com"
    assert outbox[0].kind == "attachment_share"
    assert "Attachment:" in outbox[0].body


# -- Jobs 2/3: format at run time, honestly ------------------------------


def test_catalog_format_matrix_is_the_honest_one():
    # Every type has a real producer for all three formats
    # (the activity XLSX renderer completed the matrix —
    # admin-door lane, 2026-11-07).
    for key, spec in catalog.TYPES.items():
        assert spec["formats"] == ("pdf", "csv", "xlsx"), key


def test_template_run_takes_the_callers_format(client, db, owner, fake_storage):
    _company_with_agent(db, owner)
    created = client.post(
        "/api/reports/templates",
        json={
            "report_type": "inventory",
            "name": "My inventory",
            "settings": {"format": "pdf"},
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    for fmt in ("xlsx", "csv", "pdf"):
        resp = client.post(
            f"/api/reports/templates/{template_id}/run",
            json={"format": fmt},
            headers=auth_headers(owner),
        )
        assert resp.status_code == 201, (fmt, resp.text)
        assert resp.json()["format"] == fmt

    # Excel on a ledger type is a real rendition now (the
    # activity XLSX producer): the run succeeds and stores an
    # actual spreadsheet.
    created = client.post(
        "/api/reports/templates",
        json={
            "report_type": "open_claims",
            "name": "Claims",
            "settings": {"format": "pdf"},
        },
        headers=auth_headers(owner),
    )
    claims_id = created.json()["id"]
    resp = client.post(
        f"/api/reports/templates/{claims_id}/run",
        json={"format": "xlsx"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["format"] == "xlsx"

    # A format with no producer anywhere is still refused,
    # never faked.
    resp = client.post(
        f"/api/reports/templates/{claims_id}/run",
        json={"format": "docx"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


# -- Excel for every report (admin-door lane, 2026-11-07) ----------------
#
# Ryan's order was "run these reports in PDF or excel formats"
# for the whole catalog. The activity XLSX producer
# (activity.render_activity_xlsx) is the missing rendition:
# these tests pin that every catalog type generates a REAL
# spreadsheet through the public generation seam, and that the
# spreadsheet's sections / rows / totals match the CSV's.


def _sheet_rows(data: bytes):
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    return [[cell.value for cell in row] for row in ws.iter_rows()]


def test_every_catalog_type_generates_a_real_xlsx(db, owner):
    for key in catalog.TYPES:
        data = library.generate_bytes(db, owner, key, {}, "xlsx")
        assert data[:2] == b"PK", key  # a real OOXML zip
        rows = _sheet_rows(data)
        assert rows[0][0].startswith("Toolbox Vault — "), key
        if key != "inventory":
            # The activity sheets share one flat-table header;
            # inventory's sheet carries its own column labels.
            assert any(r and r[0] == "Section" for r in rows), key


def test_truck_ledger_xlsx_carries_running_balances(db, owner):
    company, austin = _company_with_agent(db, owner)
    _truck_account(
        db, owner, company, austin, "active",
        [
            ("charge", "75.00", date(2026, 6, 1)),
            ("charge", "50.00", date(2026, 6, 8)),
            ("payment", "-25.00", date(2026, 6, 15)),
        ],
    )
    _truck_account(
        db, owner, company, austin, "closed",
        [("charge", "999.00", date(2026, 5, 1))],
    )

    rows = _sheet_rows(
        library.generate_bytes(db, owner, "open_truck_accounts", {}, "xlsx")
    )
    header = next(r for r in rows if r and r[0] == "Section")
    assert header[:7] == [
        "Section", "Date", "Type", "Name", "Amount", "Balance", "Currency",
    ]
    data = [r for r in rows if r and r[1] in ("2026-06-01", "2026-06-08", "2026-06-15")]
    assert [r[4] for r in data] == [Decimal("75.00"), Decimal("50.00"), Decimal("-25.00")]
    # The running balances step down the sheet, and the section
    # total lands in the BALANCE column, tied to the last one.
    assert [r[5] for r in data] == [Decimal("75.00"), Decimal("125.00"), Decimal("100.00")]
    total_row = next(r for r in rows if r and str(r[0]).endswith(" total"))
    assert total_row[5] == Decimal("100.00")
    # The closed account never reaches the sheet.
    assert all("999" not in str(c) for r in rows for c in r if c is not None)


def test_activity_xlsx_matches_the_csv_rows_and_totals():
    """Same dataset dict through both data renderers: the
    spreadsheet's data region (rows + section totals) equals
    the CSV's, cell for cell, money compared as numbers."""
    report = {
        "kind": "sales",
        "title": "Sales",
        "subtitle": "",
        "prepared_for": {"name": "Rae", "email": "rae@example.com", "phone": ""},
        "currency": "USD",
        "totals": [{"label": "Total sold", "amount": "125.50"}],
        "sections": [
            {
                "key": "sold",
                "label": "Sold items",
                "rows": [
                    {"date": "2026-03-04", "item": "Wrench", "detail": "Sold", "amount": "75.00"},
                    {"date": "2026-03-09", "item": "Driver", "detail": "Sold", "amount": "50.50"},
                ],
                "total": "125.50",
                "count": 2,
            },
            {
                "key": "reversed",
                "label": "Reversals",
                "rows": [],
                "total": "0.00",
                "count": 0,
            },
        ],
    }
    csv_text = activity.render_activity_csv(report, None).decode("utf-8")
    csv_rows = [
        [c.strip() for c in line.split(",")]
        for line in csv_text.splitlines()
        if line and not line.startswith("#")
    ]
    sheet = _sheet_rows(activity.render_activity_xlsx(report, None))
    header_at = next(i for i, r in enumerate(sheet) if r and r[0] == "Section")
    sheet_data = sheet[header_at + 1 :]

    def norm(rows):
        # Money cells compare as NUMBERS: "75.00" (CSV text),
        # Decimal("75.00") (as written) and 75 (as a spreadsheet
        # reads an integral number back) are one fact.
        out = []
        for r in rows:
            cells = []
            for c in r:
                if c is None:
                    cells.append("")
                    continue
                try:
                    cells.append(Decimal(str(c)))
                except Exception:
                    cells.append(str(c))
            out.append(cells)
        return out

    assert norm(sheet_data) == norm(csv_rows[1:])


def test_seeded_default_rows_never_claim_a_saved_format(db, owner):
    """Sweep fix 05-F6, the existing-account half: the seven
    defaults are seeded ONCE per user with their description
    stored on the row, so a composer-only fix never reaches an
    account that already exists. Simulate a pre-fix seed by
    rewriting a default row's stored words to the old text, then
    read it back the way the Reports page does: the serialized
    description is recomposed from the current catalog and the
    "Saved as PDF." claim is gone. A user's own template keeps
    its saved words untouched."""
    templates = library.list_templates(db, owner)
    row = next(r for r in templates if r.report_type == "inventory")
    assert row.is_default
    row.description = row.description + " Saved as PDF."
    db.commit()

    view = library.serialize_template(row, owner)
    assert "Saved as" not in view["description"]
    assert view["description"] == catalog.default_description(
        "inventory", row.settings, owner
    )
    # Without the owner, serialization is the stored row verbatim
    # (the create-template response path keeps its contract).
    assert library.serialize_template(row)["description"].endswith(
        "Saved as PDF."
    )

    own = library.create_template(
        db,
        owner,
        report_type="inventory",
        name="Mine",
        description="My own words. Saved as PDF.",
        area="quick",
        settings={"format": "pdf"},
    )
    assert not own.is_default
    assert library.serialize_template(own, owner)["description"] == (
        "My own words. Saved as PDF."
    )
