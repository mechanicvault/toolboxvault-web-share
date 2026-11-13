"""Wave 4 — the UPC field's plumbing: both asset kinds carry it
end to end (create -> detail payload), the account export
includes it, and the importer maps a barcode column onto it.
"""

import io
import json
import uuid
import zipfile

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Upc User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000461", "upc@example.com")


def test_tool_upc_roundtrip(client, owner):
    resp = client.post(
        "/api/inventory",
        json={
            "name": "Impact",
            "brand": "Milwaukee",
            "model": "2967-20",
            "upc": "045242593143",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["upc"] == "045242593143"
    detail = client.get(
        f"/api/inventory/{resp.json()['id']}", headers=auth_headers(owner)
    )
    assert detail.json()["upc"] == "045242593143"
    # And it's editable.
    put = client.put(
        f"/api/inventory/{resp.json()['id']}",
        json={"upc": "045242000000"},
        headers=auth_headers(owner),
    )
    assert put.status_code == 200
    assert put.json()["upc"] == "045242000000"


def test_battery_upc_roundtrip(client, owner):
    resp = client.post(
        "/api/inventory/batteries",
        json={
            "name": "M18 battery",
            "brand": "Milwaukee",
            "model": "48-11-1850",
            "upc": "045242351129",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["upc"] == "045242351129"


def test_export_carries_upc(client, owner):
    client.post(
        "/api/inventory",
        json={
            "name": "Impact",
            "brand": "Milwaukee",
            "model": "2967-20",
            "upc": "045242593143",
        },
        headers=auth_headers(owner),
    )
    resp = client.get("/api/core/export", headers=auth_headers(owner))
    assert resp.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    tools = json.loads(archive.read("tools.json"))
    assert tools[0]["upc"] == "045242593143"


def test_importer_maps_barcode_column_to_upc(client, owner):
    csv_data = (
        b"Item Name,Brand,Model,Barcode\n"
        b"Impact Driver,Milwaukee,2853-20,045242597943\n"
    )
    upload = client.post(
        "/api/inventory/import/upload",
        files={"file": ("tools.csv", io.BytesIO(csv_data), "text/csv")},
        data={"kind": "tool"},
        headers=auth_headers(owner),
    )
    assert upload.status_code == 201, upload.text
    session_id = upload.json()["session_id"]
    # The field catalog's SYNONYMS already know "Barcode" -> upc;
    # the explicit mapping below is the manual route to the same
    # field (index -> field key, the importer's wire shape).
    assert upload.json()["suggested_mapping"]["3"] == "upc"
    mapping = {"0": "name", "1": "brand", "2": "model_numbers", "3": "upc"}
    # Smart matching asks once per brand value; "create" = use as-is.
    resolutions = {"brand": {"Milwaukee": {"action": "create"}}}
    dry = client.post(
        f"/api/inventory/import/{session_id}/dry-run",
        json={
            "kind": "tool",
            "mapping": mapping,
            "skip_duplicates": True,
            "resolutions": resolutions,
        },
        headers=auth_headers(owner),
    )
    assert dry.status_code == 200, dry.text
    confirm = client.post(
        f"/api/inventory/import/{session_id}/confirm",
        json={
            "kind": "tool",
            "mapping": mapping,
            "skip_duplicates": True,
            "resolutions": resolutions,
        },
        headers=auth_headers(owner),
    )
    assert confirm.status_code == 200, confirm.text
    listing = client.get("/api/inventory", headers=auth_headers(owner))
    created = [t for t in listing.json() if t["name"] == "Impact Driver"]
    assert created and created[0]["upc"] == "045242597943"
