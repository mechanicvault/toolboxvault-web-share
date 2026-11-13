"""Reports ALIGNMENT pass (2026-10-19) — output aligned with
Ryan's app inventory report (the format benchmark):

  - the PHOTO column: each item's first photo rides the row (the
    screen thumbnail URL), renders as the filename value for
    CSV, embeds in PDF + XLSX; no photo → photo is None and every
    surface shows a placeholder, never a broken image;
  - the TOP SUMMARY BLOCK: items · units (quantity-aware) ·
    total value over the FULL filtered set, assets only;
  - the PREPARED-FOR header: name + email always; the optional
    profile phone + postal address render when set and are
    ABSENT when unset;
  - the built-in "Inventory Report (app style)" preset: portrait,
    the app's columns in order, row numbers on, closing totals;
  - ROW NUMBERS across groups, computed pre-pagination;
  - saved configs store the display options and configs written
    before the options bag existed read with legacy defaults;
  - the app-style PDF is a valid PORTRAIT document.
"""

import io
import uuid
from decimal import Decimal

import pytest
from PIL import Image

from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.reports import exports as reports_exports
from app.modules.reports import models as reports_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _png_bytes(color=(200, 40, 40), size=(24, 18)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _make_user(db, account_number, email, name, **overrides):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        **overrides,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000401", "align@example.com", "Al Align")


PHOTO = {
    "key": "users/x/tools/proof.png",
    "filename": "proof.png",
    "kind": "photo",
    "content_type": "image/png",
    "size_bytes": 100,
}


def _tool(db, owner, name, attachments=None, **overrides):
    tool = inventory_models.Tool(
        owner_id=owner.id,
        name=name,
        brand=overrides.pop("brand", "Snap-on"),
        model=overrides.pop("model", "CT9075"),
        attachments=attachments if attachments is not None else [],
        **overrides,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name, **overrides):
    battery = inventory_models.Battery(
        owner_id=owner.id, name=name, brand="Milwaukee",
        attachments=[], **overrides,
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


# -- summary block -----------------------------------------------------------------


def test_summary_counts_assets_and_units_over_full_set(client, owner, db):
    _tool(db, owner, "Wrench A", purchase_price=Decimal("100.00"), quantity=3,
          replacement_cost=Decimal("150.00"))
    _tool(db, owner, "Wrench B", purchase_price=Decimal("10.00"), quantity=1)
    _battery(db, owner, "Pack", purchase_price=Decimal("80.00"), quantity=2)
    report = _run(client, owner, columns=["name", "quantity"])
    # 3 assets; units 3 + 1 + 2; value 300 + 10 + 160.
    assert report["summary"] == {
        "items": 3,
        "units": 6,
        "price_total": "470.00",
        "replacement": "450.00",
    }
    # The summary agrees with the grand totals — one value basis.
    assert report["summary"]["price_total"] == report["totals"]["price_total"]


def test_summary_respects_the_filter(client, owner, db):
    _tool(db, owner, "Kept wrench", category="Hand",
          purchase_price=Decimal("100.00"), quantity=3)
    _tool(db, owner, "Dropped driver", category="Power",
          purchase_price=Decimal("999.00"), quantity=9)
    report = _run(
        client, owner, columns=["name"], filters={"category": "Hand"}
    )
    assert report["summary"]["items"] == 1
    assert report["summary"]["units"] == 3
    assert report["summary"]["price_total"] == "300.00"


def test_summary_set_modes_keep_one_money_story(client, owner, db):
    """Items/units count the ASSET in every sets mode — member
    rows itemize, they don't multiply the summary."""
    set_tool = _tool(db, owner, "Socket set", is_set=True,
                     purchase_price=Decimal("200"), quantity=2)
    db.add(
        inventory_models.SetPiece(
            set_id=set_tool.id, owner_id=owner.id, kind="core",
            name="10mm socket", part_number="S10", status="present",
        )
    )
    db.add(
        inventory_models.SetPiece(
            set_id=set_tool.id, owner_id=owner.id, kind="addon",
            name="Extension", part_number="E1", status="present",
            price=Decimal("30"),
        )
    )
    db.commit()
    for mode in ("summary", "with_core", "full"):
        report = _run(client, owner, columns=["name"], sets_mode=mode)
        assert report["summary"]["items"] == 1, mode
        assert report["summary"]["units"] == 2, mode
        # The set valued whole: its own price extends by quantity
        # (200 × 2); piece prices are per-piece (the engine's
        # pinned math — pieces are physical singles).
        assert report["summary"]["price_total"] == "430.00", mode


def test_summary_can_be_switched_off(client, owner, db):
    _tool(db, owner, "Wrench", purchase_price=Decimal("5.00"))
    report = _run(client, owner, columns=["name"], show_summary=False)
    assert report["options"]["show_summary"] is False
    response = client.post(
        "/api/reports/export/csv",
        json={"columns": ["name"], "show_summary": False},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert "# Summary" not in response.text
    assert "# Toolbox Vault" not in response.text
    assert response.text.splitlines()[0] == "Name"


# -- photo column --------------------------------------------------------------------


def test_photo_column_payload_and_placeholder(client, owner, db):
    _tool(db, owner, "Photographed", attachments=[PHOTO])
    _tool(db, owner, "Bare")
    report = _run(client, owner, columns=["photo", "name"])
    rows = {r["values"]["name"]: r for r in _all_rows(report)}
    photo_row = rows["Photographed"]
    assert photo_row["photo"]["filename"] == "proof.png"
    assert photo_row["photo"]["key"] == PHOTO["key"]
    assert photo_row["photo"]["url"]  # a (presigned) URL for the screen
    # The column VALUE is the filename — CSV's cell.
    assert photo_row["values"]["photo"] == "proof.png"
    bare = rows["Bare"]
    assert bare["photo"] is None
    assert bare["values"]["photo"] is None


def test_photo_column_set_photo_is_the_sets_own(client, owner, db):
    set_tool = _tool(db, owner, "Socket set", is_set=True, attachments=[PHOTO])
    db.add(
        inventory_models.SetPiece(
            set_id=set_tool.id, owner_id=owner.id, kind="core",
            name="10mm socket", part_number="S10", status="present",
        )
    )
    db.commit()
    report = _run(
        client, owner, columns=["photo", "name"], sets_mode="with_core"
    )
    rows = _all_rows(report)
    set_row = next(r for r in rows if r["row_type"] == "asset")
    piece_row = next(r for r in rows if r["row_type"] == "core_piece")
    assert set_row["photo"]["filename"] == "proof.png"
    assert piece_row["photo"] is None  # pieces have no photos of their own


def test_csv_photo_cell_is_the_filename(client, owner, db):
    _tool(db, owner, "Photographed", attachments=[PHOTO])
    _tool(db, owner, "Bare")
    response = client.post(
        "/api/reports/export/csv",
        json={"columns": ["photo", "name"]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    lines = [l for l in response.text.splitlines() if "Photographed" in l or ",Bare" in l]
    assert any("proof.png" in l for l in lines)
    bare_line = next(l for l in lines if l.endswith(",Bare") or ",Bare" in l)
    assert bare_line.startswith(",")  # empty photo cell, no broken reference


def test_pdf_embeds_the_photo(monkeypatch, client, owner, db):
    _tool(db, owner, "Photographed", attachments=[PHOTO])
    monkeypatch.setattr(
        reports_exports.storage, "fetch", lambda key: _png_bytes()
    )
    response = client.post(
        "/api/reports/export/pdf",
        json={"columns": ["photo", "name", "price_total"]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"
    assert b"/Subtype /Image" in response.content


def test_pdf_photo_fetch_failure_degrades_to_placeholder(
    monkeypatch, client, owner, db
):
    _tool(db, owner, "Photographed", attachments=[PHOTO])

    def boom(key):
        raise RuntimeError("object gone")

    monkeypatch.setattr(reports_exports.storage, "fetch", boom)
    response = client.post(
        "/api/reports/export/pdf",
        json={"columns": ["photo", "name"]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"


def test_xlsx_embeds_the_photo(monkeypatch, client, owner, db):
    from openpyxl import load_workbook

    _tool(db, owner, "Photographed", attachments=[PHOTO])
    monkeypatch.setattr(
        reports_exports.storage, "fetch", lambda key: _png_bytes()
    )
    response = client.post(
        "/api/reports/export/xlsx",
        json={"columns": ["photo", "name"]},
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    wb = load_workbook(io.BytesIO(response.content))
    assert len(wb.active._images) == 1


# -- prepared-for ---------------------------------------------------------------------


def test_prepared_for_absent_fields_stay_absent(client, owner, db):
    _tool(db, owner, "Wrench")
    report = _run(client, owner, columns=["name"])
    assert report["prepared_for"] == {
        "name": "Al Align",
        "email": "align@example.com",
        "phone": "",
        "address": "",
    }


def test_prepared_for_with_profile_contact_details(client, owner, db):
    owner.phone = "(555) 010-1234"
    owner.postal_address = "21925 Haven Rd\nLittle Falls, MN 56345"
    db.commit()
    _tool(db, owner, "Wrench")
    report = _run(client, owner, columns=["name"])
    assert report["prepared_for"]["phone"] == "(555) 010-1234"
    assert "Little Falls" in report["prepared_for"]["address"]
    response = client.post(
        "/api/reports/export/csv",
        json={"columns": ["name"]},
        headers=auth_headers(owner),
    )
    # Parse (don't string-match): the writer quotes the comment
    # cell because the address contains commas.
    import csv as csv_mod

    parsed = list(csv_mod.reader(io.StringIO(response.text)))
    prepared_line = next(
        r[0] for r in parsed if r and r[0].startswith("# Prepared for:")
    )
    assert "Al Align" in prepared_line
    assert "(555) 010-1234" in prepared_line
    assert "21925 Haven Rd Little Falls, MN 56345" in prepared_line


def test_profile_patch_round_trips_report_contact_details(client, owner):
    headers = auth_headers(owner)
    response = client.patch(
        "/api/core/me",
        json={"phone": "555-0100", "postal_address": "PO Box 9"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["phone"] == "555-0100"
    assert body["postal_address"] == "PO Box 9"
    me = client.get("/api/core/me", headers=headers).json()
    assert me["phone"] == "555-0100"
    # Clearing back to unset works — the fields render absent again.
    response = client.patch(
        "/api/core/me", json={"phone": "", "postal_address": ""}, headers=headers
    )
    assert response.json()["phone"] == ""


# -- row numbers ------------------------------------------------------------------------


def test_row_numbers_run_across_groups(client, owner, db):
    _tool(db, owner, "Bravo", category="B-cat")
    _tool(db, owner, "Alpha", category="A-cat")
    _tool(db, owner, "Charlie", category="A-cat")
    report = _run(
        client,
        owner,
        columns=["name"],
        grouping="category",
        sort={"key": "name", "direction": "asc"},
        show_row_numbers=True,
    )
    numbers = [r["number"] for r in _all_rows(report)]
    assert numbers == [1, 2, 3]
    names = [r["values"]["name"] for r in _all_rows(report)]
    assert names == ["Alpha", "Charlie", "Bravo"]  # groups in order


def test_row_numbers_off_by_default(client, owner, db):
    _tool(db, owner, "Wrench")
    report = _run(client, owner, columns=["name"])
    assert report["options"]["show_row_numbers"] is False
    assert _all_rows(report)[0]["number"] is None


# -- the app-style preset ------------------------------------------------------------------


def test_app_style_preset_shape(client, owner, db):
    _tool(db, owner, "Wrench", purchase_price=Decimal("25.00"), quantity=2)
    listing = client.get("/api/reports/configs", headers=auth_headers(owner)).json()
    preset = next(p for p in listing["presets"] if p["id"] == "preset-app-style")
    assert preset["name"] == "Inventory Report (app style)"
    spec = preset["spec"]
    assert spec["columns"] == [
        "photo", "name", "quantity", "brand", "models", "price_total",
    ]
    assert spec["orientation"] == "portrait"
    assert spec["show_row_numbers"] is True
    assert spec["sets_mode"] == "with_core"
    # It runs: numbers assigned, totals closing the document.
    report = _run(client, owner, **spec)
    assert [c["key"] for c in report["columns"]] == spec["columns"]
    assert _all_rows(report)[0]["number"] == 1
    assert report["summary"]["price_total"] == "50.00"


def test_app_style_preset_pdf_is_portrait(client, owner, db):
    _tool(db, owner, "Wrench", purchase_price=Decimal("25.00"))
    listing = client.get("/api/reports/configs", headers=auth_headers(owner)).json()
    spec = next(p for p in listing["presets"] if p["id"] == "preset-app-style")["spec"]
    response = client.post(
        "/api/reports/export/pdf", json=spec, headers=auth_headers(owner)
    )
    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"
    # A4 portrait MediaBox (points): 595.28 × 841.89.
    assert b"595.28 841.89" in response.content
    # The default landscape document is the transpose.
    response = client.post(
        "/api/reports/export/pdf",
        json={"columns": ["name"]},
        headers=auth_headers(owner),
    )
    assert b"841.89 595.28" in response.content


# -- saved-config options ---------------------------------------------------------------------


def test_config_round_trips_display_options(client, owner):
    headers = auth_headers(owner)
    spec = {
        "columns": ["photo", "name"],
        "show_row_numbers": True,
        "show_summary": False,
        "orientation": "portrait",
    }
    created = client.post(
        "/api/reports/configs",
        json={"name": "App look", "spec": spec},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    got = created.json()["spec"]
    assert got["show_row_numbers"] is True
    assert got["show_summary"] is False
    assert got["orientation"] == "portrait"


def test_legacy_config_without_options_reads_defaults(client, owner, db):
    """A config row written before the options bag existed
    (options = {}) must behave exactly as it did: no row numbers,
    summary on, landscape."""
    config = reports_models.ReportConfig(
        owner_id=owner.id,
        name="Legacy",
        columns=["name"],
        filters={},
        grouping="none",
        sets_mode="summary",
        sort={"key": "name", "direction": "asc"},
        options={},
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    listing = client.get("/api/reports/configs", headers=auth_headers(owner)).json()
    mine = next(c for c in listing["saved"] if c["id"] == str(config.id))
    assert mine["spec"]["show_row_numbers"] is False
    assert mine["spec"]["show_summary"] is True
    assert mine["spec"]["orientation"] == "landscape"
    report = _run(client, owner, **mine["spec"])
    assert report["options"] == {
        "show_row_numbers": False,
        "show_summary": True,
        "orientation": "landscape",
    }
