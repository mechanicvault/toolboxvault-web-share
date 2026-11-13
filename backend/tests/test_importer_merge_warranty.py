"""Importer: multi-column merge + dedupe, set fields, warranty
fields (import round, 2026-10-25).

Pins: a multi-value field (Model numbers / Serial numbers / Set
serials) accepts several source columns and merges them in column
order, deduped case/whitespace-insensitively (Ryan's file carries
IDENTICAL "Model" and "Model Number" columns — one clean copy of
each number must land); single-value fields still refuse a second
column, with the rule stated in the error; set serials materialize
as core pieces named "Piece 1", "Piece 2", … and imply the set;
the warranty term parser's table (plain number = months, "N years"
= 12xN, "N days" = N/30 months, "N weeks" = N*12/52 months,
"lifetime" = the lifetime type) for tools AND batteries.
"""

import io
import uuid

import pytest

from app.modules.core import models as core_models
from app.modules.inventory import importer
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


@pytest.fixture()
def mechanic(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000311",
        email="imp2-mech@example.com",
        name="Import User 2",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _upload(client, user, filename, data: bytes, kind="tool"):
    return client.post(
        "/api/inventory/import/upload",
        files={"file": (filename, io.BytesIO(data), "text/csv")},
        data={"kind": kind},
        headers=auth_headers(user),
    )


def _dry_run(client, user, session_id, mapping, kind="tool"):
    return client.post(
        f"/api/inventory/import/{session_id}/dry-run",
        json={"kind": kind, "mapping": mapping, "skip_duplicates": True, "resolutions": {}},
        headers=auth_headers(user),
    )


def _confirm(client, user, session_id, mapping, kind="tool"):
    return client.post(
        f"/api/inventory/import/{session_id}/confirm",
        json={"kind": kind, "mapping": mapping, "skip_duplicates": True, "resolutions": {}},
        headers=auth_headers(user),
    )


def _tools(client, user):
    return client.get("/api/inventory/search", headers=auth_headers(user)).json()


# -- multi-column merge + dedupe --------------------------------------


def test_ryan_case_duplicate_model_columns_land_one_copy(client, mechanic):
    data = (
        "Name,Model,Model Number\n"
        "Crows Foot,Matco RCFS40OE,Matco RCFS40OE\n"
    ).encode()
    body = _upload(client, mechanic, "ryan.csv", data).json()
    # Suggestions propose Model numbers for BOTH columns.
    assert body["suggested_mapping"] == {
        "0": "name",
        "1": "model_numbers",
        "2": "model_numbers",
    }
    mapping = {"0": "name", "1": "model_numbers", "2": "model_numbers"}
    dry = _dry_run(client, mechanic, body["session_id"], mapping).json()
    assert dry["rows"][0]["preview"]["models"] == ["Matco RCFS40OE"]
    summary = _confirm(client, mechanic, body["session_id"], mapping).json()
    assert summary["imported"] == 1
    tool = _tools(client, mechanic)[0]
    assert tool["model_numbers"] == ["Matco RCFS40OE"]
    assert tool["model"] == "Matco RCFS40OE"


def test_merge_is_in_column_order_and_dedupes_case_and_space(client, mechanic):
    data = (
        "Name,Model,Model Number\n"
        "Impact,2767-20,2767-20; 2760-20\n"
        "Wrench,ABC 1,abc 1 ; DEF 2\n"
    ).encode()
    body = _upload(client, mechanic, "merge.csv", data).json()
    mapping = {"0": "name", "1": "model_numbers", "2": "model_numbers"}
    dry = _dry_run(client, mechanic, body["session_id"], mapping).json()
    assert dry["rows"][0]["preview"]["models"] == ["2767-20", "2760-20"]
    # Case/whitespace lookalikes collapse to the first spelling.
    assert dry["rows"][1]["preview"]["models"] == ["ABC 1", "DEF 2"]
    summary = _confirm(client, mechanic, body["session_id"], mapping).json()
    assert summary["imported"] == 2
    by_name = {t["name"]: t for t in _tools(client, mechanic)}
    assert by_name["Impact"]["model_numbers"] == ["2767-20", "2760-20"]
    assert by_name["Wrench"]["model_numbers"] == ["ABC 1", "DEF 2"]


def test_single_value_field_still_refuses_a_second_column(client, mechanic):
    data = b"Name,Brand,Make\nWrench,Snap-on,Snap-on\n"
    body = _upload(client, mechanic, "dup.csv", data).json()
    mapping = {"0": "name", "1": "brand", "2": "brand"}
    response = _dry_run(client, mechanic, body["session_id"], mapping)
    assert response.status_code == 422
    assert "takes one column only" in response.json()["detail"]


# -- sets --------------------------------------------------------------


def test_set_serials_become_core_pieces_in_order(client, mechanic):
    data = (
        "Name,Is Set,Set Serials\n"
        "Socket Set,yes,S-10; S-11; S-12\n"
    ).encode()
    body = _upload(client, mechanic, "set.csv", data).json()
    mapping = {"0": "name", "1": "is_set", "2": "set_serials"}
    dry = _dry_run(client, mechanic, body["session_id"], mapping).json()
    assert dry["rows"][0]["preview"]["is_set"] is True
    assert dry["rows"][0]["preview"]["set_serials"] == ["S-10", "S-11", "S-12"]
    summary = _confirm(client, mechanic, body["session_id"], mapping).json()
    assert summary["imported"] == 1
    tool = _tools(client, mechanic)[0]
    assert tool["is_set"] is True
    pieces = tool["set"]["core_pieces"]
    assert [p["serial_number"] for p in pieces] == ["S-10", "S-11", "S-12"]
    assert [p["name"] for p in pieces] == ["Piece 1", "Piece 2", "Piece 3"]
    assert [p["sort_order"] for p in pieces] == [0, 1, 2]


def test_set_serials_alone_imply_a_set(client, mechanic):
    data = b"Name,Set Serials\nBit Kit,P-1; P-2\n"
    body = _upload(client, mechanic, "set2.csv", data).json()
    # Suggestions find the set-serials column without an is-set column.
    assert body["suggested_mapping"].get("1") == "set_serials"
    mapping = {"0": "name", "1": "set_serials"}
    summary = _confirm(client, mechanic, body["session_id"], mapping).json()
    assert summary["imported"] == 1
    tool = _tools(client, mechanic)[0]
    assert tool["is_set"] is True
    assert len(tool["set"]["core_pieces"]) == 2


# -- warranty ------------------------------------------------------------


def test_warranty_term_parsing_table():
    assert importer._parse_warranty_term("24") == (24, None)
    assert importer._parse_warranty_term("24.0") == (24, None)
    assert importer._parse_warranty_term("24 months") == (24, None)
    assert importer._parse_warranty_term("6 mo") == (6, None)
    assert importer._parse_warranty_term("2 years") == (24, None)
    assert importer._parse_warranty_term("1 yr") == (12, None)
    assert importer._parse_warranty_term("1.5 years") == (18, None)
    assert importer._parse_warranty_term("lifetime") == (None, "lifetime")
    assert importer._parse_warranty_term("Lifetime") == (None, "lifetime")
    for garbage in ("", "0", "abc", "two years", "-3", "1.5 months"):
        with pytest.raises(ValueError):
            importer._parse_warranty_term(garbage)


def test_warranty_term_word_forms_days_and_weeks():
    # Ryan 2026-11-06: teach the importer the word forms — "12 months"
    # already parsed; "90 days" (and weeks) are the newly-taught shapes.
    # Months/years neighbors pinned against their numeric equivalents.
    assert importer._parse_warranty_term("12 months") == (12, None)
    assert importer._parse_warranty_term("1 month") == (1, None)
    assert importer._parse_warranty_term("1 year") == (12, None)
    # Days: 30 days = 1 month.
    assert importer._parse_warranty_term("90 days") == (3, None)
    assert importer._parse_warranty_term("90 day") == (3, None)
    assert importer._parse_warranty_term("30 days") == (1, None)
    assert importer._parse_warranty_term("60 Days") == (2, None)
    assert importer._parse_warranty_term("90  days") == (3, None)
    assert importer._parse_warranty_term("90-day") == (3, None)
    # Weeks: 52 weeks = 12 months, so 13 weeks is a quarter.
    assert importer._parse_warranty_term("13 weeks") == (3, None)
    assert importer._parse_warranty_term("13 week") == (3, None)
    assert importer._parse_warranty_term("26 weeks") == (6, None)
    assert importer._parse_warranty_term("39 weeks") == (9, None)
    assert importer._parse_warranty_term("52 WEEKS") == (12, None)
    # The stored value is whole months: day/week terms that cannot
    # land on a whole month refuse (never rounded), near-miss units
    # never silently parse, and number-words stay unparseable.
    for garbage in (
        "12 moons",
        "90 dayz",
        "twelve months",
        "45 days",  # 1.5 months
        "10 days",
        "365 days",  # 12.166... months
        "1 day",
        "4 weeks",
        "1 week",
        "0 days",
    ):
        with pytest.raises(ValueError):
            importer._parse_warranty_term(garbage)


def test_warranty_fields_import_for_tools(client, mechanic):
    data = (
        "Name,Warranty,Warranty Provider,Warranty Contact,Warranty Terms\n"
        "Ratchet,2 years,Matco,555-0100,Full replacement\n"
        "Press,lifetime,ACME Press Co,claims@acme.example,Lifetime frame\n"
    ).encode()
    body = _upload(client, mechanic, "warranty.csv", data).json()
    mapping = {
        "0": "name",
        "1": "warranty_months",
        "2": "warranty_provider",
        "3": "warranty_contact",
        "4": "warranty_terms",
    }
    summary = _confirm(client, mechanic, body["session_id"], mapping).json()
    assert summary["imported"] == 2
    by_name = {t["name"]: t for t in _tools(client, mechanic)}
    ratchet = by_name["Ratchet"]
    assert ratchet["warranty_months"] == 24
    assert ratchet["warranty_provider"] == "Matco"
    assert ratchet["warranty_contact"] == "555-0100"
    assert ratchet["warranty_terms"] == "Full replacement"
    press = by_name["Press"]
    assert press["warranty_months"] is None
    assert press["warranty_type"] == "lifetime"
    assert press["warranty_status"] == "in_warranty"


def test_warranty_word_forms_import_end_to_end(client, mechanic):
    data = (
        "Name,Warranty\n"
        "Wrench,90 days\n"
        "Driver,13 weeks\n"
        "Saw,12 months\n"
    ).encode()
    body = _upload(client, mechanic, "wordforms.csv", data).json()
    mapping = {"0": "name", "1": "warranty_months"}
    summary = _confirm(client, mechanic, body["session_id"], mapping).json()
    assert summary["imported"] == 3
    by_name = {t["name"]: t for t in _tools(client, mechanic)}
    assert by_name["Wrench"]["warranty_months"] == 3
    assert by_name["Driver"]["warranty_months"] == 3
    assert by_name["Saw"]["warranty_months"] == 12


def test_warranty_fields_import_for_batteries(client, mechanic):
    data = (
        "Name,Warranty,Warranty Provider,Warranty Contact,Warranty Terms\n"
        "M18 Pack,lifetime,Milwaukee,800-555-0100,Prorated after year 2\n"
    ).encode()
    body = _upload(client, mechanic, "bwarranty.csv", data, kind="battery").json()
    keys = {f["key"] for f in body["fields"]}
    assert {
        "warranty_months",
        "warranty_provider",
        "warranty_contact",
        "warranty_terms",
    } <= keys
    mapping = {
        "0": "name",
        "1": "warranty_months",
        "2": "warranty_provider",
        "3": "warranty_contact",
        "4": "warranty_terms",
    }
    summary = _confirm(
        client, mechanic, body["session_id"], mapping, kind="battery"
    ).json()
    assert summary["imported"] == 1
    pack = client.get(
        "/api/inventory/batteries", headers=auth_headers(mechanic)
    ).json()[0]
    assert pack["warranty_months"] is None
    assert pack["warranty_type"] == "lifetime"
    assert pack["warranty_provider"] == "Milwaukee"
    assert pack["warranty_contact"] == "800-555-0100"
    assert pack["warranty_terms"] == "Prorated after year 2"
