"""Reports module — the dataset engine, saved configs, exports.

Covers the rules the module was specified with:
  - rows = tools + batteries unified, money per unit × quantity;
  - the ENTITLEMENT ACTIVE SET governs (inactive assets vanish
    from reports when enforcement is on — the shared machinery,
    never a private query);
  - sets modes (summary / with_core / full) and the money rule
    that keeps the modes' grand totals in agreement;
  - filters, grouping + subtotals, sorting, pagination;
  - saved config CRUD with cross-user 404s + the built-in presets;
  - CSV/XLSX parse-back equality with the on-screen data, PDF
    magic bytes + pages, email through the outbox seam;
  - module off (or unassigned) → 403 module_unavailable.
"""

import csv
import io
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.billing import entitlements
from app.modules.borrowing import models as borrowing_models
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.reports import models as reports_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
SHOP = "shop_company"
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
    return _make_user(db, "TV-M-000301", "reports@example.com", [MECHANIC], "Rae Reports")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000302", "reports-other@example.com", [MECHANIC], "Otto Other")


@pytest.fixture()
def dealer_user(db):
    return _make_user(db, "TV-D-000303", "reports-dealer@example.com", [DEALER], "Dee Dealer")


@pytest.fixture()
def operator(db):
    user = _make_user(db, "TV-M-000304", "reports-op@example.com", [MECHANIC], "Op Erator")
    user.is_operator = True
    db.commit()
    db.refresh(user)
    return user


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=name,
        brand=overrides.pop("brand", "Snap-on"),
        model=overrides.pop("model", "CT9075"),
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name="M18 5.0 pack", **overrides):
    battery = inventory_models.Battery(
        owner_id=owner.id, name=name, brand="Milwaukee", **overrides
    )
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


def _run(client, user, **spec):
    response = client.post("/api/reports/run", json=spec, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


def _all_rows(report):
    return [row for group in report["groups"] for row in group["rows"]]


def _by_name(report):
    return {row["values"]["name"]: row for row in _all_rows(report)}


# -- dataset & math ---------------------------------------------------------------


def test_run_unifies_tools_and_batteries_with_qty_math(client, owner, db):
    _tool(db, owner, purchase_price=Decimal("100.00"), quantity=3,
          replacement_cost=Decimal("150.00"))
    _battery(db, owner, purchase_price=Decimal("80.00"), quantity=2)
    report = _run(client, owner, columns=["name", "kind", "quantity", "price_each", "price_total", "replacement"])
    rows = _by_name(report)
    assert set(rows) == {"Impact wrench", "M18 5.0 pack"}
    # Price Each × quantity — the app's money rule.
    assert rows["Impact wrench"]["values"]["price_total"] == "300.00"
    assert rows["Impact wrench"]["values"]["replacement"] == "450.00"
    assert rows["Impact wrench"]["values"]["kind"] == "Tool"
    assert rows["M18 5.0 pack"]["values"]["kind"] == "Battery"
    assert rows["M18 5.0 pack"]["values"]["price_total"] == "160.00"
    assert report["totals"]["price_total"] == "460.00"
    assert report["total_rows"] == 2


def test_warranty_column_speaks_for_tools_and_batteries(client, owner, db):
    # Since the maintenance build (2026-10-19) tools carry warranty
    # terms too, and ONE shared computation speaks for both kinds:
    # a tool with no warranty data reads "Unknown", exactly like a
    # battery would (this assertion used to pin a "—" for tools —
    # from when tools had no warranty clock at all).
    _battery(db, owner, purchase_date=date.today() - timedelta(days=10),
             warranty_months=24)
    _tool(db, owner)
    _tool(db, owner, name="Covered drill",
          purchase_date=date.today() - timedelta(days=10), warranty_months=24)
    report = _run(client, owner, columns=["name", "warranty"])
    rows = _by_name(report)
    assert rows["M18 5.0 pack"]["display"]["warranty"] == "In warranty"
    assert rows["Impact wrench"]["display"]["warranty"] == "Unknown"
    assert rows["Covered drill"]["display"]["warranty"] == "In warranty"


def test_filters(client, owner, db):
    _tool(db, owner, name="Red wrench", category="Hand tools", condition="Good",
          purchase_price=Decimal("50"), purchase_date=date(2024, 3, 1))
    _tool(db, owner, name="Blue drill", category="Power tools", condition="Worn",
          purchase_price=Decimal("500"), purchase_date=date(2025, 6, 1))
    _battery(db, owner, name="Old pack", category="Power tools",
             purchase_price=Decimal("40"), purchase_date=date(2020, 1, 1),
             warranty_months=12)

    assert set(_by_name(_run(client, owner, filters={"q": "red"}))) == {"Red wrench"}
    assert set(_by_name(_run(client, owner, filters={"kind": "battery"}))) == {"Old pack"}
    assert set(_by_name(_run(client, owner, filters={"category": "Power tools"}))) == {"Blue drill", "Old pack"}
    # Package B retired the condition filter entirely: a filter
    # dict still carrying the key loads fine and simply doesn't
    # narrow (saved configs keep running, never error).
    assert set(_by_name(_run(client, owner, filters={"condition": "Worn"}))) == {
        "Red wrench", "Blue drill", "Old pack"
    }
    assert set(_by_name(_run(client, owner, filters={"min_price": "100"}))) == {"Blue drill"}
    assert set(_by_name(_run(client, owner, filters={"max_price": "60"}))) == {"Red wrench", "Old pack"}
    assert set(_by_name(_run(client, owner, filters={"date_from": "2025-01-01"}))) == {"Blue drill"}
    assert set(_by_name(_run(client, owner, filters={"date_to": "2021-01-01"}))) == {"Old pack"}
    # Warranty filter matches computed states (both kinds since
    # the maintenance build; the undated tools read "unknown").
    assert set(_by_name(_run(client, owner, filters={"warranty": "expired"}))) == {"Old pack"}


def test_grouping_subtotals_and_sorting(client, owner, db):
    _tool(db, owner, name="A tool", category="Power", purchase_price=Decimal("100"), quantity=2)
    _tool(db, owner, name="B tool", category="Power", purchase_price=Decimal("50"))
    _tool(db, owner, name="C tool", category="Hand", purchase_price=Decimal("25"))
    report = _run(client, owner, columns=["name", "price_total"], grouping="category",
                  sort={"key": "price_total", "direction": "desc"})
    groups = {g["label"]: g for g in report["groups"]}
    assert groups["Power"]["subtotal"]["count"] == 2
    assert groups["Power"]["subtotal"]["price_total"] == "250.00"
    assert groups["Hand"]["subtotal"]["price_total"] == "25.00"
    # Sorted within the group: the qty-2 tool first.
    assert groups["Power"]["rows"][0]["values"]["name"] == "A tool"
    assert report["totals"]["price_total"] == "275.00"


def test_pagination(client, owner, db):
    for i in range(3):
        _tool(db, owner, name=f"Tool {i}")
    page1 = _run(client, owner, page=1, page_size=2)
    page2 = _run(client, owner, page=2, page_size=2)
    assert page1["pages"] == 2 and page1["total_rows"] == 3
    assert len(_all_rows(page1)) == 2 and len(_all_rows(page2)) == 1


def test_checked_out_status_and_filter(client, owner, db):
    out_tool = _tool(db, owner, name="Out tool")
    _tool(db, owner, name="Home tool")
    db.add(borrowing_models.Checkout(
        owner_id=owner.id, item_kind="tool", item_id=out_tool.id,
        borrower_name="Pat", state="checked_out",
    ))
    db.commit()
    report = _run(client, owner, columns=["name", "status"])
    rows = _by_name(report)
    assert rows["Out tool"]["values"]["status"] == "Checked out"
    assert rows["Home tool"]["values"]["status"] == "Active"
    only = _run(client, owner, columns=["name"], filters={"only_checked_out": True})
    assert set(_by_name(only)) == {"Out tool"}


def test_custom_field_column(client, owner, db):
    definition = inventory_models.FieldDefinition(
        owner_id=owner.id, name="torque_spec", label="Torque spec",
        field_type="text", item_type="tool", sort_order=0,
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)
    _tool(db, owner, custom_data={str(definition.id): "120 Nm"})
    report = _run(client, owner, columns=["name", f"cf:{definition.id}"])
    rows = _by_name(report)
    assert rows["Impact wrench"]["values"][f"cf:{definition.id}"] == "120 Nm"


# -- sets modes ---------------------------------------------------------------------


def _make_set(db, owner):
    """A set worth $200 own + $30 addon piece + $40 attached tool,
    with one core piece carrying no price."""
    addon_tool = _tool(db, owner, name="Addon driver", purchase_price=Decimal("40"))
    set_tool = _tool(db, owner, name="Socket set", is_set=True,
                     purchase_price=Decimal("200"))
    core = inventory_models.SetPiece(
        set_id=set_tool.id, owner_id=owner.id, kind="core", name="10mm socket",
        part_number="S10", status="present",
    )
    addon = inventory_models.SetPiece(
        set_id=set_tool.id, owner_id=owner.id, kind="addon", name="Extension bar",
        part_number="EXT1", status="present", price=Decimal("30"),
    )
    db.add_all([core, addon])
    addon_tool.attached_to_set_id = set_tool.id
    db.commit()
    return set_tool


def test_sets_summary_mode(client, owner, db):
    _make_set(db, owner)
    report = _run(client, owner, columns=["name", "price_total", "set"], sets_mode="summary")
    rows = _all_rows(report)
    # One row: the set, valued whole (200 own + 30 addon + 40 attached).
    assert len(rows) == 1
    assert rows[0]["values"]["price_total"] == "270.00"
    assert rows[0]["values"]["set"] == "Set: Socket set"
    assert report["totals"]["price_total"] == "270.00"


def test_sets_with_core_mode(client, owner, db):
    _make_set(db, owner)
    report = _run(client, owner, columns=["name", "price_total", "set"], sets_mode="with_core")
    rows = _by_name(report)
    assert set(rows) == {"Socket set", "10mm socket"}
    core = rows["10mm socket"]
    assert core["row_type"] == "core_piece"
    # This core piece has no price recorded — the cell reads "in set".
    assert core["display"]["price_total"] == "in set"
    assert core["values"]["set"] == "Piece of: Socket set"
    # Totals still agree with summary mode (the set row carries all).
    assert report["totals"]["price_total"] == "270.00"


def test_sets_full_mode(client, owner, db):
    _make_set(db, owner)
    report = _run(client, owner, columns=["name", "price_total", "set"], sets_mode="full")
    rows = _by_name(report)
    assert set(rows) == {"Socket set", "10mm socket", "Extension bar", "Addon driver"}
    # The set row now carries only its own price; members carry theirs.
    assert rows["Socket set"]["values"]["price_total"] == "200.00"
    assert rows["Extension bar"]["values"]["price_total"] == "30.00"
    assert rows["Addon driver"]["values"]["price_total"] == "40.00"
    assert rows["10mm socket"]["display"]["price_total"] == "in set"
    # Same money, itemized: grand totals agree across modes.
    assert report["totals"]["price_total"] == "270.00"


def test_priced_core_piece_shows_its_price_and_never_totals(client, owner, db):
    """Owner 2026-10-25: a core piece with its own recorded price
    shows that price on its piece row (deep modes) — and the price
    joins NO total anywhere: the set row and the grand totals are
    exactly the unpriced run's numbers."""
    set_tool = _make_set(db, owner)
    piece = inventory_models.SetPiece(
        set_id=set_tool.id, owner_id=owner.id, kind="core", name="12mm socket",
        part_number="S12", status="present", price=Decimal("12"),
    )
    db.add(piece)
    db.commit()

    summary = _run(client, owner, columns=["name", "price_total", "set"], sets_mode="summary")
    assert summary["totals"]["price_total"] == "270.00"

    for mode in ("with_core", "full"):
        report = _run(
            client, owner,
            columns=["name", "models", "price_each", "price_total", "set"],
            sets_mode=mode,
        )
        rows = _by_name(report)
        priced = rows["12mm socket"]
        assert priced["row_type"] == "core_piece"
        # The piece's model number and its own price are on the row.
        assert priced["values"]["models"] == "S12"
        assert priced["values"]["price_total"] == "12.00"
        assert priced["display"]["price_total"] != "in set"
        assert "$12.00" in priced["display"]["price_total"]
        # The unpriced core piece still reads "in set".
        assert rows["10mm socket"]["display"]["price_total"] == "in set"
        # No rollup: grand total is the unpriced run's number.
        assert report["totals"]["price_total"] == "270.00", mode


def test_only_sets_filter(client, owner, db):
    _make_set(db, owner)
    _tool(db, owner, name="Loose tool")
    report = _run(client, owner, columns=["name"], filters={"only_sets": True})
    assert set(_by_name(report)) == {"Socket set"}


def test_text_search_finds_set_by_piece_part_number(client, owner, db):
    _make_set(db, owner)
    _tool(db, owner, name="Loose tool")
    report = _run(client, owner, columns=["name"], filters={"q": "S10"})
    assert set(_by_name(report)) == {"Socket set"}


# -- active set (the A1 rule) --------------------------------------------------------


def test_inactive_assets_vanish_when_enforcement_on(client, owner, db):
    # Free plan cap is 20: the 21st-newest tool holds no active slot.
    for i in range(21):
        _tool(db, owner, name=f"Tool {i:02d}")
    report = _run(client, owner, columns=["name"])
    assert report["total_rows"] == 21  # enforcement OFF: everything
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)
    report = _run(client, owner, columns=["name"])
    assert report["total_rows"] == 20
    # Exactly one asset lost its active slot (timestamps tie at
    # fixture speed, so WHICH one is the machinery's tie-break —
    # the count and the exclusion are the rule under test).
    assert len(set(_by_name(report))) == 20


# -- saved configs + presets ------------------------------------------------------------


def test_config_crud_and_cross_user_404(client, owner, other, db):
    _tool(db, owner)
    payload = {
        "name": "My valuation",
        "spec": {"columns": ["name", "price_total"], "grouping": "category",
                 "sets_mode": "full", "sort": {"key": "name", "direction": "asc"}},
    }
    created = client.post("/api/reports/configs", json=payload, headers=auth_headers(owner))
    assert created.status_code == 201, created.text
    config_id = created.json()["id"]
    assert created.json()["spec"]["grouping"] == "category"

    listing = client.get("/api/reports/configs", headers=auth_headers(owner)).json()
    assert [c["name"] for c in listing["saved"]] == ["My valuation"]
    preset_names = {p["name"] for p in listing["presets"]}
    # The app-style preset joined the built-ins in the reports
    # alignment pass (2026-10-19).
    assert preset_names == {
        "Full inventory valuation",
        "Tax — purchases by year",
        "Inventory Report (app style)",
    }
    assert all(p["builtin"] for p in listing["presets"])

    # Cross-user: reads as missing everywhere, never a leak.
    assert client.get(f"/api/reports/configs/{config_id}", headers=auth_headers(other)).status_code == 404
    assert client.put(f"/api/reports/configs/{config_id}", json=payload, headers=auth_headers(other)).status_code == 404
    assert client.delete(f"/api/reports/configs/{config_id}", headers=auth_headers(other)).status_code == 404
    assert client.get("/api/reports/configs", headers=auth_headers(other)).json()["saved"] == []

    renamed = client.put(
        f"/api/reports/configs/{config_id}",
        json={"name": "Renamed", "spec": payload["spec"]},
        headers=auth_headers(owner),
    )
    assert renamed.json()["name"] == "Renamed"
    assert client.delete(f"/api/reports/configs/{config_id}", headers=auth_headers(owner)).status_code == 204
    assert db.query(reports_models.ReportConfig).count() == 0


def test_config_rejects_unknown_column(client, owner):
    response = client.post(
        "/api/reports/configs",
        json={"name": "Bad", "spec": {"columns": ["name", "nonsense"]}},
        headers=auth_headers(owner),
    )
    assert response.status_code == 422


def test_presets_run(client, owner, db):
    _tool(db, owner, category="Power", purchase_price=Decimal("100"),
          purchase_date=date(2025, 2, 1))
    listing = client.get("/api/reports/configs", headers=auth_headers(owner)).json()
    valuation = next(p for p in listing["presets"] if p["name"] == "Full inventory valuation")
    report = _run(client, owner, **valuation["spec"])
    assert report["groups"][0]["label"] == "Power"
    assert report["totals"]["price_total"] == "100.00"
    tax = next(p for p in listing["presets"] if p["name"] == "Tax — purchases by year")
    report = _run(client, owner, **tax["spec"])
    assert report["groups"][0]["label"] == "2025"


# -- exports ------------------------------------------------------------------------------


def _fixture_vault(db, owner):
    _tool(db, owner, name="Qty wrench", category="Hand", quantity=3,
          purchase_price=Decimal("100.00"), replacement_cost=Decimal("120.00"))
    _battery(db, owner, name="Pack", category="Power",
             purchase_price=Decimal("80.00"))


def test_csv_export_matches_screen(client, owner, db):
    _fixture_vault(db, owner)
    spec = {"columns": ["name", "kind", "quantity", "price_total", "replacement"],
            "grouping": "category", "sort": {"key": "name", "direction": "asc"}}
    screen = _run(client, owner, **spec)
    response = client.post("/api/reports/export/csv", json=spec, headers=auth_headers(owner))
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    parsed = list(csv.reader(io.StringIO(response.text)))
    # Reports alignment (2026-10-19): the file opens with the
    # app format's header — `#` comment lines (title, Prepared
    # For, summary) above the column header row.
    header_at = next(
        i for i, r in enumerate(parsed) if r and r[0] == "Name"
    )
    comments = [r[0] for r in parsed[:header_at]]
    assert any(c.startswith("# Prepared for: Rae Reports") for c in comments)
    assert any(c.startswith("# Summary: 2 items · 4 units") for c in comments)
    assert parsed[header_at] == ["Name", "Kind", "Qty", "Price total", "Replacement (total)"]
    data_rows = [r for r in parsed[header_at + 1:] if r and not r[0].startswith("##")
                 and not r[0].startswith("Subtotal") and not r[0].startswith("Total")]
    screen_rows = {
        (r["values"]["name"], r["values"]["kind"], str(r["values"]["quantity"]),
         r["values"]["price_total"] or "", r["values"]["replacement"] or "")
        for r in _all_rows(screen)
    }
    assert {tuple(r) for r in data_rows} == screen_rows
    total_row = next(r for r in parsed if r and r[0].startswith("Total"))
    assert Decimal(total_row[3]) == Decimal("380.00")
    assert Decimal(total_row[4]) == Decimal("360.00")


def test_xlsx_export_matches_screen(client, owner, db):
    from openpyxl import load_workbook

    _fixture_vault(db, owner)
    spec = {"columns": ["name", "quantity", "price_total"],
            "sort": {"key": "name", "direction": "asc"}}
    screen = _run(client, owner, **spec)
    response = client.post("/api/reports/export/xlsx", json=spec, headers=auth_headers(owner))
    assert response.status_code == 200
    wb = load_workbook(io.BytesIO(response.content))
    ws = wb.active
    rows = [[c.value for c in row] for row in ws.iter_rows()]
    # Reports alignment (2026-10-19): bold header-block rows
    # (title / Prepared For / summary) sit above the column header.
    header_at = next(i for i, r in enumerate(rows) if r and r[0] == "Name")
    assert any(
        str(r[0]).startswith("Prepared for: Rae Reports") for r in rows[:header_at] if r
    )
    assert rows[header_at] == ["Name", "Qty", "Price total"]
    data = {r[0]: r for r in rows[header_at + 1:] if r[0] and not str(r[0]).startswith("Total")}
    for screen_row in _all_rows(screen):
        values = screen_row["values"]
        assert data[values["name"]][1] == values["quantity"]
        assert Decimal(str(data[values["name"]][2])) == Decimal(values["price_total"])


def test_pdf_export_magic_and_pages(client, owner, db):
    _fixture_vault(db, owner)
    response = client.post(
        "/api/reports/export/pdf",
        json={"columns": ["name", "price_total"], "grouping": "category"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"
    match = re.search(rb"/Count\s+(\d+)", response.content)
    assert match and int(match.group(1)) >= 1


# -- email -----------------------------------------------------------------------------------


def test_email_report_records_outbox_with_attachment(client, owner, db):
    _fixture_vault(db, owner)
    response = client.post(
        "/api/reports/email",
        json={"format": "csv", "report_name": "Valuation", "columns": ["name", "price_total"]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200, response.text
    assert response.json()["recipient"] == owner.email  # defaults to own email
    outbox = db.query(core_models.EmailOutbox).all()
    assert len(outbox) == 1
    assert outbox[0].kind == "report"
    assert outbox[0].recipient == owner.email
    assert "[Attachment: valuation.csv" in outbox[0].body


def test_email_report_custom_recipient(client, owner, db):
    response = client.post(
        "/api/reports/email",
        json={"format": "pdf", "recipient": "accountant@example.com"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["recipient"] == "accountant@example.com"
    assert response.json()["filename"].endswith(".pdf")


# -- module gates ------------------------------------------------------------------------------


def test_module_unassigned_group_gets_403(client, dealer_user):
    response = client.post("/api/reports/run", json={}, headers=auth_headers(dealer_user))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"


def test_module_globally_off_gets_403(client, owner, operator, db):
    assert _run(client, owner)["total_rows"] == 0
    client.put(
        "/api/admin/modules/reports/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    response = client.post("/api/reports/run", json={}, headers=auth_headers(owner))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"


def test_meta_catalog_includes_defaults(client, owner):
    meta = client.get("/api/reports/meta", headers=auth_headers(owner)).json()
    keys = {c["key"] for c in meta["columns"]}
    assert {"name", "price_total", "warranty", "set"} <= keys
    assert {m["key"] for m in meta["sets_modes"]} == {"summary", "with_core", "full"}
    assert owner.id  # fixture sanity
    assert uuid.UUID(str(owner.id))


def test_rebuy_columns_carry_tool_values_and_blank_for_batteries(client, owner, db):
    """Audit A7: the reports catalog's re-buy columns read the
    tool's own re-buy block; batteries (no such fields) read blank."""
    _tool(
        db,
        owner,
        consumable=True,
        rebuy_store="Fleet Farm",
        rebuy_url="https://www.fleetfarm.com",
        rebuy_sku="FF-009988",
        rebuy_notes="10-pack only",
    )
    _battery(db, owner)
    report = _run(
        client,
        owner,
        columns=["name", "rebuy_store", "rebuy_url", "rebuy_sku", "rebuy_notes"],
    )
    rows = _by_name(report)
    tool_row = rows["Impact wrench"]["values"]
    assert tool_row["rebuy_store"] == "Fleet Farm"
    assert tool_row["rebuy_url"] == "https://www.fleetfarm.com"
    assert tool_row["rebuy_sku"] == "FF-009988"
    assert tool_row["rebuy_notes"] == "10-pack only"
    battery_row = rows["M18 5.0 pack"]["values"]
    assert battery_row["rebuy_store"] == ""
    assert battery_row["rebuy_sku"] == ""
