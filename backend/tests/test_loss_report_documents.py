"""Police-report documents (wizard + inventory fixes pack,
2026-10-25): a file uploaded through a lost/stolen report rides
the item's regular document machinery with the report's id
stamped on the attachment — it lives on the item's record, is
handed back grouped under its report by the reports list read,
and can never be tied to another item's (or another user's)
report.
"""

import uuid

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 32


def _make_user(db, account_number, email, account_types=(MECHANIC,)):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Doc Owner",
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-001301", "lrdowner@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-001302", "lrdother@example.com")


def _tool(client, user, name="Report drill"):
    resp = client.post(
        "/api/inventory",
        json={"name": name},
        headers=auth_headers(user),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _report(client, user, kind, item_id, standing="stolen"):
    resp = client.post(
        f"/api/inventory/{kind}/{item_id}/loss-reports",
        json={"standing": standing, "police_report_number": "26-1042"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _fake_storage(monkeypatch):
    monkeypatch.setattr(
        storage_module.storage,
        "presigned_put_url",
        lambda key, content_type, expires_in=900: f"https://files.test/{key}",
    )
    monkeypatch.setattr(
        storage_module.storage,
        "head",
        lambda k: storage_module.StoredObject(
            key=k, size_bytes=2048, content_type="application/pdf"
        ),
    )
    monkeypatch.setattr(
        storage_module.storage,
        "fetch_prefix",
        lambda k, length=512: PDF_BYTES,
    )
    monkeypatch.setattr(
        storage_module.storage,
        "delete",
        lambda k: None,
    )


def _attach(client, user, base, report_id, filename="police-report.pdf"):
    issued = client.post(
        f"{base}/upload-url",
        json={
            "filename": filename,
            "content_type": "application/pdf",
            "kind": "document",
            "size_bytes": 2048,
        },
        headers=auth_headers(user),
    )
    assert issued.status_code == 200, issued.text
    key = issued.json()["key"]
    return client.post(
        f"{base}/attachments",
        json={"key": key, "filename": filename, "loss_report_id": report_id},
        headers=auth_headers(user),
    )


def test_report_document_round_trip(client, owner, monkeypatch):
    _fake_storage(monkeypatch)
    tool = _tool(client, owner)
    report = _report(client, owner, "tool", tool["id"])
    # A fresh report carries no documents yet.
    listed = client.get(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        headers=auth_headers(owner),
    ).json()
    assert listed[0]["documents"] == []

    attached = _attach(client, owner, f"/api/inventory/{tool['id']}", report["id"])
    assert attached.status_code == 200, attached.text
    assert attached.json()["loss_report_id"] == report["id"]
    assert attached.json()["kind"] == "document"

    # The reports read hands the file back under its report, with
    # provenance + a minted read URL like every other document.
    listed = client.get(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        headers=auth_headers(owner),
    ).json()
    docs = listed[0]["documents"]
    assert len(docs) == 1
    assert docs[0]["filename"] == "police-report.pdf"
    assert docs[0]["uploaded_at"] is not None
    assert docs[0]["url"]

    # And it lives on the item's record with the same marker.
    item = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    marked = [a for a in item["attachments"] if a.get("loss_report_id")]
    assert len(marked) == 1 and marked[0]["loss_report_id"] == report["id"]

    # Deleting through the item's attachments removes it from the
    # report too (one record, two views of it).
    key = docs[0]["key"]
    deleted = client.delete(
        f"/api/inventory/{tool['id']}/attachments?key={key}",
        headers=auth_headers(owner),
    )
    assert deleted.status_code == 200, deleted.text
    listed = client.get(
        f"/api/inventory/tool/{tool['id']}/loss-reports",
        headers=auth_headers(owner),
    ).json()
    assert listed[0]["documents"] == []


def test_report_document_refuses_wrong_report(client, owner, other, monkeypatch):
    _fake_storage(monkeypatch)
    tool = _tool(client, owner)
    second_tool = _tool(client, owner, name="Other drill")
    report = _report(client, owner, "tool", tool["id"])
    foreign_tool_report = _report(client, owner, "tool", second_tool["id"], "lost")
    foreign_user = _tool(client, other, name="Not yours")
    foreign_user_report = _report(client, other, "tool", foreign_user["id"], "lost")

    base = f"/api/inventory/{tool['id']}"
    # A report belonging to a DIFFERENT item of the same owner.
    bad = _attach(client, owner, base, foreign_tool_report["id"])
    assert bad.status_code == 422, bad.text
    # Another user's report.
    bad = _attach(client, owner, base, foreign_user_report["id"])
    assert bad.status_code == 422, bad.text
    # A report that doesn't exist at all.
    bad = _attach(client, owner, base, str(uuid.uuid4()))
    assert bad.status_code == 422, bad.text
    # The right report still attaches cleanly.
    good = _attach(client, owner, base, report["id"])
    assert good.status_code == 200, good.text


def test_report_document_on_battery(client, owner, monkeypatch):
    _fake_storage(monkeypatch)
    created = client.post(
        "/api/inventory/batteries",
        json={"name": "Gone pack", "brand": "Milwaukee", "model": "48-11-1850"},
        headers=auth_headers(owner),
    )
    assert created.status_code in (200, 201), created.text
    pack = created.json()
    report = _report(client, owner, "battery", pack["id"], "lost")

    attached = _attach(
        client, owner, f"/api/inventory/batteries/{pack['id']}", report["id"]
    )
    assert attached.status_code == 200, attached.text
    assert f"/batteries/{pack['id']}/document/" in attached.json()["key"]

    listed = client.get(
        f"/api/inventory/battery/{pack['id']}/loss-reports",
        headers=auth_headers(owner),
    ).json()
    assert len(listed[0]["documents"]) == 1
