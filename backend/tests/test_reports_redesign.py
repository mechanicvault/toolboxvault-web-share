"""Reports page redesign (2026-11-06): the type catalog, saved
templates with seed-once defaults, generation through the
library seam, and the History.

Pinned rules:
  - the catalog carries each type once, with its home area —
    tax_179 IS the Section 179 worksheet (the older tax_year
    builder's document); there is no second, identical type;
  - the first templates read seeds exactly the seven defaults
    (4 quick / 3 accounting); a deleted default never comes
    back; another user's templates are invisible;
  - generating stores the real file + a History row whose size
    matches the stored bytes; preview stores nothing;
  - a saved template runs against today's data, and a year-kind
    template takes its year at run time;
  - the two new datasets: open repair claims (warranty, current
    only) and open truck accounts (full ledger per open account
    — Ryan's 2026-11-07 shape, superseding the grouped-by-agent
    summary this file first pinned);
  - account deletion takes templates, history rows, the seed
    marker, and the stored files with it.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core import storage as storage_module
from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
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
    return _make_user(db, "TV-M-000401", "redesign@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000402", "redesign-other@example.com", "Otto Other")


class _FakeStorage:
    """Dict-backed object store (the flyers tests' pattern)."""

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


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=name,
        brand="DeWalt",
        model="DCF891B",
        serial_number="SN-1",
        purchase_price=Decimal("200"),
        quantity=1,
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


# -- catalog --------------------------------------------------------------------


def test_catalog_carries_each_type_once_with_home_areas(client, owner):
    resp = client.get("/api/reports/catalog", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    types = {t["key"]: t for t in resp.json()["types"]}
    assert set(types) == {
        "inventory", "open_claims", "open_truck_accounts", "checked_out",
        "lost_stolen", "warranty_claims", "year_end", "repair_costs",
        "sales", "tax_179",
    }
    # tax_179 is the one Section 179 type — no duplicate tax_year.
    assert "tax_year" not in types
    assert types["tax_179"]["home_area"] == "accounting"
    assert types["sales"]["home_area"] == "accounting"
    assert types["year_end"]["home_area"] == "accounting"
    assert types["repair_costs"]["home_area"] == "accounting"
    for key in ("inventory", "open_claims", "open_truck_accounts",
                "checked_out", "lost_stolen", "warranty_claims"):
        assert types[key]["home_area"] == "quick", key
    assert types["inventory"]["formats"] == ["pdf", "csv", "xlsx"]
    assert types["year_end"]["settings"] == "year"


# -- templates + seeding -----------------------------------------------------------


def test_first_read_seeds_the_seven_defaults(client, db, owner):
    resp = client.get("/api/reports/templates", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    templates = resp.json()["templates"]
    assert len(templates) == 7
    quick = [t for t in templates if t["area"] == "quick"]
    accounting = [t for t in templates if t["area"] == "accounting"]
    assert [t["report_type"] for t in quick] == [
        "inventory", "open_claims", "open_truck_accounts", "checked_out",
    ]
    assert [t["report_type"] for t in accounting] == [
        "year_end", "repair_costs", "tax_179",
    ]
    assert all(t["is_default"] for t in templates)
    assert all(t["name"] and t["description"] for t in templates)
    # A second read adds nothing.
    again = client.get("/api/reports/templates", headers=auth_headers(owner))
    assert len(again.json()["templates"]) == 7


def test_deleted_default_never_resurrects(client, db, owner):
    templates = client.get(
        "/api/reports/templates", headers=auth_headers(owner)
    ).json()["templates"]
    victim = next(t for t in templates if t["report_type"] == "tax_179")
    resp = client.delete(
        f"/api/reports/templates/{victim['id']}", headers=auth_headers(owner)
    )
    assert resp.status_code == 204, resp.text
    after = client.get(
        "/api/reports/templates", headers=auth_headers(owner)
    ).json()["templates"]
    assert len(after) == 6
    assert all(t["report_type"] != "tax_179" for t in after)
    # …and the type itself is still in the wizard's catalog.
    types = client.get(
        "/api/reports/catalog", headers=auth_headers(owner)
    ).json()["types"]
    assert any(t["key"] == "tax_179" for t in types)


def test_create_template_composes_missing_name_and_description(client, owner):
    resp = client.post(
        "/api/reports/templates",
        json={"report_type": "sales", "settings": {"format": "csv"}},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Home area pre-answer: sales is an accounting type.
    assert body["area"] == "accounting"
    assert body["name"]
    # Sweep fix 05-F6: the composed description no longer claims
    # a saved format — a saved row runs in whichever of its
    # PDF/CSV/XLSX buttons the user picks, so the old "Saved as
    # CSV." suffix (this assertion's previous shape) was the
    # contradiction itself. The words are the catalog's body for
    # the type, nothing appended.
    assert "Saved as" not in body["description"]
    assert body["description"] == catalog.default_description(
        "sales", {"format": "csv"}, owner
    )


def test_create_template_keeps_user_words_and_area_choice(client, owner):
    resp = client.post(
        "/api/reports/templates",
        json={
            "report_type": "inventory",
            "name": "Insurance list",
            "description": "For the insurance company, yearly.",
            "area": "accounting",
            "settings": {"format": "pdf"},
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Insurance list"
    assert body["description"] == "For the insurance company, yearly."
    assert body["area"] == "accounting"
    assert body["is_default"] is False


def test_templates_are_owner_scoped(client, owner, other):
    mine = client.post(
        "/api/reports/templates",
        json={"report_type": "sales", "name": "Mine"},
        headers=auth_headers(owner),
    ).json()
    resp = client.delete(
        f"/api/reports/templates/{mine['id']}", headers=auth_headers(other)
    )
    assert resp.status_code == 404
    theirs = client.get(
        "/api/reports/templates", headers=auth_headers(other)
    ).json()["templates"]
    assert all(t["name"] != "Mine" for t in theirs)


def test_unknown_type_and_bad_settings_are_422(client, owner):
    resp = client.post(
        "/api/reports/templates",
        json={"report_type": "nope"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/reports/templates",
        json={"report_type": "year_end", "settings": {"year": "abc"}},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/reports/templates",
        json={"report_type": "year_end", "area": "sideways"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_describe_prefills_save_step(client, owner):
    resp = client.post(
        "/api/reports/describe",
        json={"report_type": "year_end", "settings": {"year": 2026, "format": "pdf"}},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "2026" in body["name"]
    assert "2026" in body["description"]


# -- generation + history -----------------------------------------------------------


def test_generate_inventory_pdf_records_history(client, db, owner, fake_storage):
    _tool(db, owner)
    resp = client.post(
        "/api/reports/generate",
        json={"report_type": "inventory", "settings": {}, "format": "pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["format"] == "pdf"
    assert row["report_type"] == "inventory"
    assert row["size_bytes"] > 0
    stored = fake_storage.objects[
        db.get(reports_models.GeneratedReport, uuid.UUID(row["id"])).storage_key
    ]
    assert len(stored) == row["size_bytes"]
    assert stored[:5] == b"%PDF-"

    history = client.get(
        "/api/reports/history", headers=auth_headers(owner)
    ).json()["entries"]
    assert [e["id"] for e in history] == [row["id"]]

    download = client.get(
        f"/api/reports/history/{row['id']}/download",
        headers=auth_headers(owner),
    )
    assert download.status_code == 200
    assert download.content == stored

    view = client.get(
        f"/api/reports/history/{row['id']}/view", headers=auth_headers(owner)
    ).json()["attachment"]
    assert view["content_type"] == "application/pdf"
    assert view["size_bytes"] == row["size_bytes"]
    assert view["url"].startswith("https://files.test/get/")


def test_preview_stores_nothing(client, db, owner, fake_storage):
    _tool(db, owner)
    resp = client.post(
        "/api/reports/preview",
        json={"report_type": "inventory", "settings": {}, "format": "pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.content[:5] == b"%PDF-"
    assert fake_storage.objects == {}
    assert db.query(reports_models.GeneratedReport).count() == 0


def test_history_filters_and_delete(client, db, owner, fake_storage):
    _tool(db, owner)
    first = client.post(
        "/api/reports/generate",
        json={"report_type": "inventory", "settings": {}, "format": "pdf"},
        headers=auth_headers(owner),
    ).json()
    second = client.post(
        "/api/reports/generate",
        json={"report_type": "inventory", "settings": {}, "format": "csv"},
        headers=auth_headers(owner),
    ).json()
    only_csv = client.get(
        "/api/reports/history?format=csv", headers=auth_headers(owner)
    ).json()["entries"]
    assert [e["id"] for e in only_csv] == [second["id"]]
    by_name = client.get(
        "/api/reports/history?q=inventory", headers=auth_headers(owner)
    ).json()["entries"]
    assert len(by_name) == 2
    none = client.get(
        "/api/reports/history?q=zzz-no-match", headers=auth_headers(owner)
    ).json()["entries"]
    assert none == []

    key = db.get(reports_models.GeneratedReport, uuid.UUID(first["id"])).storage_key
    resp = client.delete(
        f"/api/reports/history/{first['id']}", headers=auth_headers(owner)
    )
    assert resp.status_code == 204
    assert key not in fake_storage.objects
    remaining = client.get(
        "/api/reports/history", headers=auth_headers(owner)
    ).json()["entries"]
    assert [e["id"] for e in remaining] == [second["id"]]


def test_template_run_takes_year_at_run_time(client, db, owner, fake_storage):
    templates = client.get(
        "/api/reports/templates", headers=auth_headers(owner)
    ).json()["templates"]
    year_end = next(t for t in templates if t["report_type"] == "year_end")
    resp = client.post(
        f"/api/reports/templates/{year_end['id']}/run",
        json={"year": 2024},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["template_id"] == year_end["id"]
    assert row["settings"]["year"] == 2024
    assert "2024" in row["name"]
    # Deleting the template keeps the history row (link nulled).
    client.delete(
        f"/api/reports/templates/{year_end['id']}", headers=auth_headers(owner)
    )
    kept = db.get(reports_models.GeneratedReport, uuid.UUID(row["id"]))
    assert kept is not None and kept.template_id is None


def test_generate_refuses_format_the_type_cannot_make(client, owner):
    # Every catalog type makes pdf/csv/xlsx since the activity
    # XLSX producer landed (admin-door lane, 2026-11-07); the
    # refusal now guards formats with no producer anywhere.
    resp = client.post(
        "/api/reports/generate",
        json={"report_type": "sales", "settings": {}, "format": "docx"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


# -- the new datasets ---------------------------------------------------------------


def _warranty_claim(db, owner, number, status, amount="450.00", **overrides):
    claim = claims_models.Claim(
        owner_id=owner.id,
        claim_number=number,
        claim_year=2026,
        number_seq=int(number.rsplit("-", 1)[1]),
        kind="warranty_repair",
        status=status,
        description=overrides.pop("description", "Cracked housing"),
        reported_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        **overrides,
    )
    db.add(claim)
    db.flush()
    db.add(
        claims_models.ClaimLine(
            owner_id=owner.id,
            claim_id=claim.id,
            target_kind="tool",
            target_id=uuid.uuid4(),
            target_name="Torque wrench",
            value_basis="entered",
            amount=Decimal(amount),
        )
    )
    db.commit()
    db.refresh(claim)
    return claim


def test_open_claims_dataset_counts_only_current_warranty(db, owner):
    _warranty_claim(db, owner, "CL-2026-001", "reported")
    _warranty_claim(db, owner, "CL-2026-002", "backordered", amount="100.00")
    _warranty_claim(db, owner, "CL-2026-003", "completed")  # Repaired = history
    closed = _warranty_claim(db, owner, "CL-2026-004", "reported")
    closed.closed_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    db.commit()
    disaster = claims_models.Claim(
        owner_id=owner.id, claim_number="DC-2026-001", claim_year=2026,
        number_seq=1, kind="insurance_disaster", status="filed",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db.add(disaster)
    db.commit()

    report = activity.build_open_claims(db, owner)
    assert report["kind"] == "open_claims"
    labels = [s["label"] for s in report["sections"]]
    assert labels == ["Broken, Reported", "Backordered"]
    rows = [r for s in report["sections"] for r in s["rows"]]
    assert len(rows) == 2
    assert rows[0]["item"] == "Torque wrench"
    assert "CL-2026-001" in rows[0]["detail"]
    assert report["totals"][0]["amount"] == "550.00"


def _truck_account(db, owner, company, agent, status, balance):
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
    db.add(
        truck_models.TruckEntry(
            account_id=account.id,
            kind="charge",
            amount=Decimal(balance),
            entry_date=date(2026, 6, 1),
            source="manual",
        )
    )
    db.commit()
    db.refresh(account)
    return account


def test_open_truck_accounts_dataset_is_full_ledger_per_open_account(db, owner):
    """Ryan, 2026-11-07: the quick report is a FULL LEDGER for
    each open account — one section per account (not a summary
    grouped by agent), the ledger table shape, closed accounts
    excluded."""
    company = dealer_models.DealerCompany(name="Mac Tools")
    db.add(company)
    db.flush()
    austin = dealer_models.PrivateAgent(
        id=uuid.uuid4(), owner_id=owner.id, company_id=company.id, name="Austin"
    )
    matt = dealer_models.PrivateAgent(
        id=uuid.uuid4(), owner_id=owner.id, company_id=company.id, name="Matt"
    )
    db.add_all([austin, matt])
    db.commit()
    _truck_account(db, owner, company, austin, "active", "225.00")
    _truck_account(db, owner, company, matt, "active", "80.00")
    _truck_account(db, owner, company, austin, "closed", "999.00")

    report = activity.build_open_truck_accounts(db, owner)
    assert report["ledger_table"] is True
    # One section per OPEN account; the closed account (and its
    # 999.00) is nowhere in the document.
    assert len(report["sections"]) == 2
    assert {s["total"] for s in report["sections"]} == {"225.00", "80.00"}
    for section in report["sections"]:
        assert section["count"] == 1
        row = section["rows"][0]
        assert row["item"] == "Charge"
        # The running balance on the last (only) row ties to
        # the section total — the amount owed on that account.
        assert row["balance"] == section["total"]
    amounts = [r["amount"] for s in report["sections"] for r in s["rows"]]
    assert "999.00" not in amounts
    assert report["totals"][0]["amount"] == "305.00"
    assert report["totals"][0]["park"] == "right"


def test_generate_open_claims_and_truck_pdfs(client, db, owner, fake_storage):
    _warranty_claim(db, owner, "CL-2026-001", "reported")
    for report_type in ("open_claims", "open_truck_accounts", "tax_179"):
        resp = client.post(
            "/api/reports/generate",
            json={
                "report_type": report_type,
                "settings": {"year": 2026},
                "format": "pdf",
            },
            headers=auth_headers(owner),
        )
        assert resp.status_code == 201, (report_type, resp.text)
        assert resp.json()["size_bytes"] > 0


# -- account deletion -----------------------------------------------------------------


def test_account_delete_takes_the_library_with_it(client, db, owner, fake_storage):
    _tool(db, owner)
    client.get("/api/reports/templates", headers=auth_headers(owner))
    row = client.post(
        "/api/reports/generate",
        json={"report_type": "inventory", "settings": {}, "format": "pdf"},
        headers=auth_headers(owner),
    ).json()
    key = db.get(reports_models.GeneratedReport, uuid.UUID(row["id"])).storage_key
    assert key in fake_storage.objects
    assert db.query(reports_models.ReportTemplate).count() == 7

    core_service.delete_account(db, owner)
    assert db.query(reports_models.ReportTemplate).count() == 0
    assert db.query(reports_models.GeneratedReport).count() == 0
    assert db.query(reports_models.ReportTemplateSeed).count() == 0
    assert fake_storage.objects == {}


# -- settings validation ----------------------------------------------------------------


def test_validate_settings_shapes():
    assert library.validate_settings("year_end", {"year": "2026"}) == {"year": 2026}
    assert library.validate_settings("repair_costs", {}) == {}
    assert library.validate_settings(
        "sales", {"start": "2026-01-01", "end": "2026-12-31"}
    ) == {"start": "2026-01-01", "end": "2026-12-31"}
    with pytest.raises(library.ReportError):
        library.validate_settings("sales", {"start": "2026-12-31", "end": "2026-01-01"})
    with pytest.raises(library.ReportError):
        library.validate_settings("inventory", {"grouping": "nope"})
    with pytest.raises(library.ReportError):
        library.validate_settings("inventory", {"format": "docx"})
