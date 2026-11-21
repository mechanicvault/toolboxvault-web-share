"""General CSV/XLSX importer (inventory module, 2026-10-19).

Pins: suggested mappings from header synonyms; the parse-tolerance
table (dates / money / ints / bools); dry-run classification
(ok / warning / error / blank) with NOTHING written; duplicate
detection against the existing vault and within the file, with the
skip toggle honored both ways; the entitlement cap respected when
enforcement is on (dry-run prediction AND confirm behavior);
dealer names matched (never created silently — smart matching,
2026-10-19, has its own suite in test_importer_matching.py);
sessions owner-scoped (foreign id = 404) and expiring; upload
rejections; inventory-gate 403 for a dealer-only account.
"""

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.billing import entitlements
from app.modules.core import models as core_models
from app.modules.dealers import service as dealers_service
from app.modules.inventory import importer, models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Import User",
        password_hash="not-a-real-hash",
        account_types=account_types,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def mechanic(db):
    return _make_user(db, "TV-M-000301", "imp-mech@example.com", [MECHANIC])


@pytest.fixture()
def other_mechanic(db):
    return _make_user(db, "TV-M-000302", "imp-other@example.com", [MECHANIC])


@pytest.fixture()
def dealer_only(db):
    return _make_user(db, "TV-D-000303", "imp-dealer@example.com", [DEALER])


def _upload(client, user, filename, data: bytes, kind="tool", content_type=None):
    return client.post(
        "/api/inventory/import/upload",
        files={
            "file": (
                filename,
                io.BytesIO(data),
                content_type
                or ("text/csv" if filename.endswith(".csv") else "application/octet-stream"),
            )
        },
        data={"kind": kind},
        headers=auth_headers(user),
    )


def _dry_run(
    client, user, session_id, mapping, kind="tool", skip_duplicates=True,
    resolutions=None,
):
    return client.post(
        f"/api/inventory/import/{session_id}/dry-run",
        json={
            "kind": kind,
            "mapping": mapping,
            "skip_duplicates": skip_duplicates,
            "resolutions": resolutions or {},
        },
        headers=auth_headers(user),
    )


def _confirm(
    client, user, session_id, mapping, kind="tool", skip_duplicates=True,
    resolutions=None,
):
    return client.post(
        f"/api/inventory/import/{session_id}/confirm",
        json={
            "kind": kind,
            "mapping": mapping,
            "skip_duplicates": skip_duplicates,
            "resolutions": resolutions or {},
        },
        headers=auth_headers(user),
    )


def _create_all(*values):
    """Smart matching (2026-10-19): 'use as a new value' answers
    for a batch of raw values in one field."""
    return {value: {"action": "create"} for value in values}


def _tool_count(client, user):
    response = client.get("/api/inventory", headers=auth_headers(user))
    assert response.status_code == 200
    return len(response.json())


# -- mapping suggestions ---------------------------------------------------


def test_suggest_mapping_covers_synonyms(db, mechanic):
    fields = importer.field_catalog(db, mechanic.id, "tool")
    headers = ["Item Name", "S/N", "Part #", "Price", "Dealer", "Qty", "Bought"]
    suggestions = importer.suggest_mapping(headers, fields)
    assert suggestions == {
        0: "name",
        1: "serial_numbers",
        2: "model_numbers",
        3: "purchase_price",
        4: "dealer_name",
        5: "quantity",
        6: "purchase_date",
    }


def test_suggest_mapping_never_assigns_a_single_value_field_twice(db, mechanic):
    fields = importer.field_catalog(db, mechanic.id, "tool")
    suggestions = importer.suggest_mapping(["Name", "Item Name"], fields)
    assert list(suggestions.values()) == ["name"]


def test_suggest_mapping_offers_a_multi_field_for_both_columns(db, mechanic):
    """A file's "Model" + "Model Number" columns (or the serial
    pair) both belong in the one list field — suggestions propose
    it for both (import multi-column merge, 2026-10-25)."""
    fields = importer.field_catalog(db, mechanic.id, "tool")
    suggestions = importer.suggest_mapping(["Serial", "Serial Number"], fields)
    assert suggestions == {0: "serial_numbers", 1: "serial_numbers"}
    suggestions = importer.suggest_mapping(["Model", "Model Number"], fields)
    assert suggestions == {0: "model_numbers", 1: "model_numbers"}


# -- parse tolerance ---------------------------------------------------------


def test_parse_tolerance_table():
    assert str(importer._parse_date("2024-01-05")) == "2024-01-05"
    assert str(importer._parse_date("01/05/2024")) == "2024-01-05"
    assert str(importer._parse_date("5 Jan 2024")) == "2024-01-05"
    assert str(importer._parse_date("January 5, 2024")) == "2024-01-05"
    assert str(importer._parse_money("$1,234.50")) == "1234.50"
    assert str(importer._parse_money("€ 99")) == "99.00"
    assert importer._parse_int("3.0") == 3
    assert importer._parse_int("1,000") == 1000
    for raw in ("yes", "TRUE", "1", "On"):
        assert importer._parse_bool(raw) is True
    for raw in ("no", "false", "0", "OFF"):
        assert importer._parse_bool(raw) is False
    with pytest.raises(ValueError):
        importer._parse_money("not money")
    with pytest.raises(ValueError):
        importer._parse_date("next Tuesday")


# -- upload + preview + session scoping -------------------------------------

CSV_BASIC = (
    "Name,Brand,Serial\n"
    "Wrench,Snap-on,S1\n"
    "Hammer,Estwing,H9\n"
)


def test_upload_preview_and_fields(client, mechanic):
    response = _upload(client, mechanic, "tools.csv", CSV_BASIC.encode())
    assert response.status_code == 201
    body = response.json()
    assert body["headers"] == ["Name", "Brand", "Serial"]
    assert body["row_count"] == 2
    assert body["sample_rows"][0] == ["Wrench", "Snap-on", "S1"]
    assert body["suggested_mapping"] == {
        "0": "name",
        "1": "brand",
        "2": "serial_numbers",
    }
    keys = {f["key"] for f in body["fields"]}
    assert {"size", "consumable"} <= keys  # tool-only fields


def test_foreign_session_is_404(client, mechanic, other_mechanic):
    session_id = _upload(
        client, mechanic, "tools.csv", CSV_BASIC.encode()
    ).json()["session_id"]
    response = _dry_run(
        client, other_mechanic, session_id, {"0": "name", "2": "serial_numbers"}
    )
    assert response.status_code == 404
    response = client.delete(
        f"/api/inventory/import/{session_id}", headers=auth_headers(other_mechanic)
    )
    assert response.status_code == 404


def test_expired_session_is_410(client, mechanic, db):
    session_id = _upload(
        client, mechanic, "tools.csv", CSV_BASIC.encode()
    ).json()["session_id"]
    session = db.get(inventory_models.ImportSession, uuid.UUID(session_id))
    session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    response = _dry_run(client, mechanic, session_id, {"0": "name"})
    assert response.status_code == 410


def test_dealer_only_account_gets_module_403(client, dealer_only):
    response = _upload(client, dealer_only, "tools.csv", CSV_BASIC.encode())
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "module_unavailable"


# -- upload rejections ---------------------------------------------------------


def test_upload_rejections(client, mechanic):
    response = _upload(client, mechanic, "notes.txt", b"Name\nWrench\n")
    assert response.status_code == 400
    assert ".csv and .xlsx" in response.json()["detail"]

    response = _upload(client, mechanic, "empty.csv", b"")
    assert response.status_code == 400

    too_many = "Name\n" + "".join(f"Tool {i}\n" for i in range(2001))
    response = _upload(client, mechanic, "big.csv", too_many.encode())
    assert response.status_code == 400
    assert "2,000 rows" in response.json()["detail"]


def test_header_only_file_imports_nothing(client, mechanic):
    session_id = _upload(
        client, mechanic, "tools.csv", b"Name,Brand\n"
    ).json()["session_id"]
    dry = _dry_run(client, mechanic, session_id, {"0": "name", "1": "brand"})
    assert dry.status_code == 200
    assert dry.json()["total_rows"] == 0
    summary = _confirm(client, mechanic, session_id, {"0": "name", "1": "brand"})
    assert summary.status_code == 200
    assert summary.json()["imported"] == 0


# -- dry run classification ---------------------------------------------------

CSV_MIXED = (
    "Name,Dealer,Price,Qty,Serial\n"
    "Good Wrench,Matco Tools,$45.00,2,GW-1\n"          # row 2: ok
    "Mystery Tool,No Such Dealer,not-a-price,,MT-9\n"  # row 3: warnings
    ",,,,\n"                                             # row 4: blank
    ",Matco Tools,10.00,1,\n"                            # row 5: error, no name
)


@pytest.fixture()
def matco(db):
    return dealers_service.create_company(
        db, owner_id=None, data={"name": "Matco Tools"}
    )


def test_dry_run_classification_and_no_writes(client, mechanic, matco):
    session_id = _upload(client, mechanic, "mixed.csv", CSV_MIXED.encode()).json()[
        "session_id"
    ]
    mapping = {
        "0": "name",
        "1": "dealer_name",
        "2": "purchase_price",
        "3": "quantity",
        "4": "serial_numbers",
    }
    # Smart matching (2026-10-19, Ryan-directed — supersedes the
    # old "report the unknown dealer and import untagged" pin):
    # "Matco Tools" matches the directory automatically, but
    # "No Such Dealer" is a question the importer must ASK. With
    # no answer the run REFUSES, naming the value.
    refused = _dry_run(client, mechanic, session_id, mapping)
    assert refused.status_code == 422
    assert "No Such Dealer" in refused.json()["detail"]
    # The user answers: leave that dealer unset for this import.
    resolutions = {"dealer_name": {"No Such Dealer": {"action": "unset"}}}
    response = _dry_run(client, mechanic, session_id, mapping, resolutions=resolutions)
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 4
    assert body["counts"] == {
        "ok": 1,
        "warning": 1,
        "error": 1,
        "blank": 1,
        "duplicates": 0,
    }
    rows = {row["row"]: row for row in body["rows"]}
    assert rows[2]["status"] == "ok"
    assert rows[3]["status"] == "warning"
    assert any("unrecognized amount" in m for m in rows[3]["messages"])
    assert rows[4]["status"] == "blank"
    assert rows[5]["status"] == "error"
    # A dry run writes NOTHING.
    assert _tool_count(client, mechanic) == 0
    assert body["cap"]["enforcement"] is False

    summary = _confirm(
        client, mechanic, session_id, mapping, resolutions=resolutions
    ).json()
    assert summary["imported"] == 2
    assert summary["errors"] == 1
    assert summary["error_rows"][0]["row"] == 5
    tools = client.get("/api/inventory", headers=auth_headers(mechanic)).json()
    by_name = {t["name"]: t for t in tools}
    assert by_name["Good Wrench"]["quantity"] == 2
    assert by_name["Good Wrench"]["dealer_company_name"] == "Matco Tools"
    assert str(by_name["Good Wrench"]["purchase_price"]) == "45.00"
    # The unknown dealer was answered "leave unset": the item
    # imports untagged, and no company was created behind the
    # user's back.
    assert by_name["Mystery Tool"]["dealer_company_id"] is None
    # The session was consumed by the confirm.
    assert _dry_run(client, mechanic, session_id, mapping).status_code == 404


def test_duplicate_mapping_and_missing_name_are_422(client, mechanic):
    session_id = _upload(client, mechanic, "tools.csv", CSV_BASIC.encode()).json()[
        "session_id"
    ]
    response = _dry_run(
        client, mechanic, session_id, {"0": "brand", "1": "brand"}
    )
    assert response.status_code == 422
    assert "both mapped" in response.json()["detail"]
    response = _dry_run(client, mechanic, session_id, {"1": "brand"})
    assert response.status_code == 422
    assert "Map a column to Name" in response.json()["detail"]


# -- duplicates -------------------------------------------------------------------


def _create_tool_via_api(client, user, **fields):
    payload = {"name": "Wrench", **fields}
    response = client.post(
        "/api/inventory", json=payload, headers=auth_headers(user)
    )
    assert response.status_code == 201
    return response.json()


def test_duplicate_skip_on_and_off(client, mechanic):
    _create_tool_via_api(client, mechanic, serial_number="S1")
    data = b"Name,Serial\nWrench,S1\nScrewdriver,SD-2\n"
    mapping = {"0": "name", "1": "serial_numbers"}

    session_id = _upload(client, mechanic, "dups.csv", data).json()["session_id"]
    dry = _dry_run(client, mechanic, session_id, mapping).json()
    rows = {row["row"]: row for row in dry["rows"]}
    assert rows[2]["duplicate"] is True
    assert rows[2]["status"] == "warning"
    assert rows[3]["duplicate"] is False
    assert dry["counts"]["duplicates"] == 1
    assert dry["importable"] == 1  # the duplicate is skipped by default

    summary = _confirm(client, mechanic, session_id, mapping).json()
    assert summary["imported"] == 1
    assert summary["skipped_duplicates"] == 1

    session_id = _upload(client, mechanic, "dups.csv", data).json()["session_id"]
    summary = _confirm(
        client, mechanic, session_id, mapping, skip_duplicates=False
    ).json()
    assert summary["imported"] == 2
    assert summary["skipped_duplicates"] == 0
    names = [
        t["name"]
        for t in client.get("/api/inventory", headers=auth_headers(mechanic)).json()
    ]
    assert names.count("Wrench") == 2


def test_duplicate_within_the_file(client, mechanic):
    data = b"Name,Serial\nPliers,P-1\nPliers,P-1\n"
    session_id = _upload(client, mechanic, "dups.csv", data).json()["session_id"]
    dry = _dry_run(
        client, mechanic, session_id, {"0": "name", "1": "serial_numbers"}
    ).json()
    rows = {row["row"]: row for row in dry["rows"]}
    assert rows[2]["duplicate"] is False
    assert rows[3]["duplicate"] is True
    assert any("row 2 in this file" in m for m in rows[3]["messages"])


# -- entitlement cap -----------------------------------------------------------------


def test_cap_with_enforcement_on(client, mechanic, db):
    for i in range(19):
        db.add(
            inventory_models.Tool(owner_id=mechanic.id, name=f"Fixture {i:02d}")
        )
    db.commit()
    entitlements.set_setting(db, entitlements.ENFORCEMENT_KEY, True)

    data = b"Name\nNew A\nNew B\nNew C\n"
    session_id = _upload(client, mechanic, "cap.csv", data).json()["session_id"]
    dry = _dry_run(client, mechanic, session_id, {"0": "name"}).json()
    assert dry["cap"]["enforcement"] is True
    assert dry["cap"]["limit"] == 20
    assert dry["cap"]["current_count"] == 19
    assert dry["cap"]["remaining"] == 1
    assert dry["cap"]["would_exceed"] == 2

    summary = _confirm(client, mechanic, session_id, {"0": "name"}).json()
    assert summary["imported"] == 1
    assert summary["skipped_over_cap"] == 2
    assert summary["over_cap_rows"] == [3, 4]
    assert _tool_count(client, mechanic) == 20


# -- end-to-end: CSV with quantity, multi-serial, tags -------------------------

CSV_FULL = (
    "Name,Brand,Serial Numbers,Qty,Price Each,Tags,Purchase Date,Consumable\n"
    "Torque Wrench,Snap-on,TW-1; TW-2,3,$120.50,\"shop, calibrated\",01/15/2024,no\n"
    "Ratchet,GearWrench,GW-88,1,45.00,shop,2023-11-02,no\n"
    "Impact Socket Set,Ingersoll,\"IR-10, IR-11\",2,89.99,,5 Jan 2024,no\n"
    "Grease Gun,Lincoln,LG-7,1,32.25,,2024-02-29,no\n"
    "Shop Towels,Generic,ST-100,10,1.50,consumables,,yes\n"
    ",NoName,XX-1,1,9.99,,,\n"
)


def test_csv_end_to_end(client, mechanic):
    session_id = _upload(client, mechanic, "full.csv", CSV_FULL.encode()).json()[
        "session_id"
    ]
    mapping = {
        "0": "name",
        "1": "brand",
        "2": "serial_numbers",
        "3": "quantity",
        "4": "purchase_price",
        "5": "tags",
        "6": "purchase_date",
        "7": "consumable",
    }
    # Smart matching (2026-10-19): this vault starts EMPTY, so
    # every brand and tag in the file is a brand-new value the
    # Resolve step asks about once — the answers here are "use
    # them as new values" ("NoName" rides the error row; its value
    # still needs an answer).
    resolutions = {
        "brand": _create_all(
            "Snap-on", "GearWrench", "Ingersoll", "Lincoln", "Generic", "NoName"
        ),
        "tags": _create_all("shop", "calibrated", "consumables"),
    }
    dry = _dry_run(client, mechanic, session_id, mapping, resolutions=resolutions).json()
    assert dry["counts"]["ok"] == 5
    assert dry["counts"]["error"] == 1

    summary = _confirm(
        client, mechanic, session_id, mapping, resolutions=resolutions
    ).json()
    assert summary["imported"] == 5
    assert summary["errors"] == 1
    assert summary["error_rows"][0]["row"] == 7

    tools = client.get("/api/inventory", headers=auth_headers(mechanic)).json()
    assert len(tools) == 5
    by_name = {t["name"]: t for t in tools}
    torque = by_name["Torque Wrench"]
    assert torque["serial_numbers"] == ["TW-1", "TW-2"]
    assert torque["serial_number"] == "TW-1"  # primary = first entry
    assert torque["quantity"] == 3
    assert str(torque["purchase_price"]) == "120.50"
    assert torque["purchase_date"] == "2024-01-15"
    assert {tag["name"] for tag in torque["tags"]} == {"shop", "calibrated"}
    assert by_name["Impact Socket Set"]["serial_numbers"] == ["IR-10", "IR-11"]
    assert by_name["Impact Socket Set"]["purchase_date"] == "2024-01-05"
    assert by_name["Shop Towels"]["consumable"] is True
    # The session is gone after confirm.
    assert _dry_run(client, mechanic, session_id, mapping).status_code == 404


# -- end-to-end: XLSX ----------------------------------------------------------


def test_xlsx_end_to_end(client, mechanic):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Brand", "Price", "Purchase Date", "Qty"])
    sheet.append(["Drill", "DeWalt", 129.99, "2023-05-04", 1])
    sheet.append(["Saw", "Milwaukee", 199, "06/01/2024", 2])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = _upload(
        client,
        mechanic,
        "tools.xlsx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["file_format"] == "xlsx"
    assert body["row_count"] == 2
    assert body["sample_rows"][0][2] == "129.99"

    session_id = body["session_id"]
    mapping = {
        "0": "name",
        "1": "brand",
        "2": "purchase_price",
        "3": "purchase_date",
        "4": "quantity",
    }
    # Smart matching (2026-10-19): both brands are new to this
    # empty vault — answered once as "use as new".
    resolutions = {"brand": _create_all("DeWalt", "Milwaukee")}
    summary = _confirm(
        client, mechanic, session_id, mapping, resolutions=resolutions
    ).json()
    assert summary["imported"] == 2
    tools = client.get("/api/inventory", headers=auth_headers(mechanic)).json()
    by_name = {t["name"]: t for t in tools}
    assert by_name["Drill"]["purchase_date"] == "2023-05-04"
    assert by_name["Saw"]["purchase_date"] == "2024-06-01"
    assert by_name["Saw"]["quantity"] == 2


# -- batteries -------------------------------------------------------------------


def test_battery_import_with_multi_serial_warning(client, mechanic):
    data = (
        "Name,Platform,Serial,Voltage,Warranty,Price\n"
        "M18 Pack,M18,BAT-1; BAT-2,18,24,$79.00\n"
    ).encode()
    response = _upload(client, mechanic, "batteries.csv", data, kind="battery")
    assert response.status_code == 201
    body = response.json()
    keys = {f["key"] for f in body["fields"]}
    assert {"platform", "voltage", "capacity_ah", "chemistry", "warranty_months"} <= keys
    assert "consumable" not in keys

    session_id = body["session_id"]
    mapping = {
        "0": "name",
        "1": "platform",
        "2": "serial_numbers",
        "3": "voltage",
        "4": "warranty_months",
        "5": "purchase_price",
    }
    dry = _dry_run(client, mechanic, session_id, mapping, kind="battery").json()
    row = dry["rows"][0]
    assert row["status"] == "warning"
    assert any("kept 'BAT-1'" in m for m in row["messages"])

    summary = _confirm(
        client, mechanic, session_id, mapping, kind="battery"
    ).json()
    assert summary["imported"] == 1
    batteries = client.get(
        "/api/inventory/batteries", headers=auth_headers(mechanic)
    ).json()
    assert len(batteries) == 1
    pack = batteries[0]
    assert pack["platform"] == "M18"
    assert pack["serial_number"] == "BAT-1"
    assert str(pack["voltage"]) == "18.00"
    assert pack["warranty_months"] == 24


# -- header-row detection: banded sheets (2026-10-29) ---------------------------
#
# The free /downloads sheet carries a dashboard band (logo, totals
# boxes) above its labels, on a tab behind a cover sheet. The
# importer must find the real header row and treat the file exactly
# like the identical sheet without the band; files that name no
# columns anywhere keep the historic first-row behavior.


def _banded_generic_bytes():
    from app.modules.downloads import sheet as downloads_sheet

    keys = downloads_sheet.resolve_fields("generic", None)
    return downloads_sheet.build_sheet(keys), keys


def _unbanded_twin_bytes(banded: bytes):
    """The identical sheet with labels on row 1 and no band/cover:
    same labels, same first data row, lifted out of the banded
    workbook."""
    from openpyxl import Workbook, load_workbook

    from app.modules.downloads import sheet as downloads_sheet

    source = load_workbook(io.BytesIO(banded))["My Tools"]
    labels = [cell.value for cell in source[downloads_sheet.LABEL_ROW]]
    example = [
        cell.value for cell in source[downloads_sheet.FIRST_DATA_ROW]
    ]
    workbook = Workbook()
    twin = workbook.active
    twin.append(labels)
    twin.append(example)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_banded_sheet_upload_finds_labels(client, mechanic):
    from app.modules.downloads import sheet as downloads_sheet

    banded, keys = _banded_generic_bytes()
    body = _upload(client, mechanic, "toolbox-vault-sheet.xlsx", banded).json()
    assert body["file_format"] == "xlsx"
    assert body["headers"] == [downloads_sheet._LABELS[k] for k in keys]
    assert body["row_count"] == 1
    assert body["sample_rows"][0][0].startswith("Ratchet")

    # Suggestions land exactly as they do for the unbanded twin.
    twin_body = _upload(
        client, mechanic, "twin.xlsx", _unbanded_twin_bytes(banded)
    ).json()
    assert twin_body["headers"] == body["headers"]
    assert twin_body["suggested_mapping"] == body["suggested_mapping"]
    assert twin_body["row_count"] == body["row_count"]


def test_banded_and_unbanded_dry_run_agree(client, mechanic):
    banded, keys = _banded_generic_bytes()
    mapping = {str(i): key for i, key in enumerate(keys)}
    # The example row's matchable values are answered "leave unset"
    # identically for both files, so the runs must agree on
    # everything except the honest spreadsheet row numbers.
    resolutions = {
        "brand": {"Example brand": {"action": "unset"}},
        "category": {"Wrenches & sockets": {"action": "unset"}},
        "location": {"Top drawer": {"action": "unset"}},
        "dealer_name": {"Tool truck": {"action": "unset"}},
    }

    banded_body = _upload(client, mechanic, "banded.xlsx", banded).json()
    banded_run = _dry_run(
        client, mechanic, banded_body["session_id"], mapping,
        resolutions=resolutions,
    ).json()
    twin_body = _upload(
        client, mechanic, "twin.xlsx", _unbanded_twin_bytes(banded)
    ).json()
    twin_run = _dry_run(
        client, mechanic, twin_body["session_id"], mapping,
        resolutions=resolutions,
    ).json()

    assert banded_run["counts"] == twin_run["counts"]
    assert banded_run["importable"] == twin_run["importable"] == 1
    assert banded_run["total_rows"] == twin_run["total_rows"] == 1
    banded_row, twin_row = banded_run["rows"][0], twin_run["rows"][0]
    for key in ("status", "name", "messages", "duplicate", "preview"):
        assert banded_row[key] == twin_row[key], key
    # Row numbers name the rows the user sees: the band pushes the
    # example down to the first data row under the labels.
    from app.modules.downloads import sheet as downloads_sheet

    assert banded_row["row"] == downloads_sheet.FIRST_DATA_ROW
    assert twin_row["row"] == 2

    # And the banded file confirms into a real tool, values intact.
    summary = _confirm(
        client, mechanic, banded_body["session_id"], mapping,
        resolutions=resolutions,
    ).json()
    assert summary["imported"] == 1
    tools = client.get("/api/inventory", headers=auth_headers(mechanic)).json()
    assert len(tools) == 1
    ratchet = tools[0]
    assert ratchet["name"].startswith("Ratchet")
    assert str(ratchet["purchase_price"]) == "89.99"
    assert ratchet["quantity"] == 1


def test_parse_banded_single_sheet_skips_band_rows():
    from openpyxl import Workbook

    workbook = Workbook()
    ws = workbook.active
    ws.append(["MY SHOP INVENTORY", None, None])  # title band
    ws.append(["Name", None, None])  # a lone label must not qualify
    ws.append(["TOTAL TOOLS", 3, None])  # totals band
    ws.append([None, None, None])
    ws.append(["Name", "Brand", "Quantity"])  # the real header, row 5
    ws.append(["Wrench", "Acme", 2])
    ws.append(["Hammer", "", None])
    buffer = io.BytesIO()
    workbook.save(buffer)

    fmt, headers, rows, header_row = importer._parse_spreadsheet_full(
        "banded.xlsx", buffer.getvalue()
    )
    assert fmt == "xlsx"
    assert header_row == 5
    assert headers == ["Name", "Brand", "Quantity"]
    assert rows == [["Wrench", "Acme", "2"], ["Hammer", "", ""]]


def test_unrecognizable_xlsx_behaves_as_before(client, mechanic):
    from openpyxl import Workbook

    # Gibberish headers: no row qualifies, so row 1 is the header
    # row — the historic parse, with no suggestions to offer.
    workbook = Workbook()
    ws = workbook.active
    ws.append(["Foo", "Bar"])
    ws.append(["x", "y"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    body = _upload(client, mechanic, "gibberish.xlsx", buffer.getvalue()).json()
    assert body["headers"] == ["Foo", "Bar"]
    assert body["row_count"] == 1
    assert body["suggested_mapping"] == {}

    # Nothing resembling a header anywhere: the same refusal the
    # importer has always given.
    workbook = Workbook()
    ws = workbook.active
    ws.append([None, None])
    ws.append(["zzz", "qqq"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = _upload(client, mechanic, "noheader.xlsx", buffer.getvalue())
    assert response.status_code == 400
    assert "no header row" in response.json()["detail"]


# -- custom fields ------------------------------------------------------------------


def test_custom_field_mapping(client, mechanic):
    created = client.post(
        "/api/inventory/field-definitions",
        json={"name": "torque_spec", "label": "Torque Spec", "field_type": "text"},
        headers=auth_headers(mechanic),
    )
    assert created.status_code == 201
    definition_id = created.json()["id"]

    data = b"Name,Torque Spec\nWrench,120 ft-lb\n"
    body = _upload(client, mechanic, "cf.csv", data).json()
    assert body["suggested_mapping"].get("1") == f"cf:{definition_id}"

    session_id = body["session_id"]
    mapping = {"0": "name", "1": f"cf:{definition_id}"}
    summary = _confirm(client, mechanic, session_id, mapping).json()
    assert summary["imported"] == 1
    tool = client.get("/api/inventory", headers=auth_headers(mechanic)).json()[0]
    assert tool["custom_data"][definition_id] == "120 ft-lb"
