""" "View as visitor" previews (Sweep D5, 2026-11-12): the
owner-only preview fetches on print listings and dealer
pages. The honesty rule under test: a preview response is
the REAL non-owner data shape — byte-for-byte the payload a
signed-in member with no relationship to the record receives
from the ordinary read — produced by shaping the same
serializers with the visitor stand-in, never the owner's
payload with furniture hidden. The gates under test: only
the listing's publisher / the company's representatives may
preview; everyone else's preview request is a 403 (they
already read the visitor shape themselves). A preview is a
plain read: it moves no counter.
"""

import io
import struct
import uuid
from datetime import date, timedelta

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.flyers import service as flyer_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"
TODAY = date.today()


class _FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, data, content_type):
        self.objects[key] = data
        return storage_module.StoredObject(
            key=key, size_bytes=len(data), content_type=content_type
        )

    def fetch(self, key):
        if key not in self.objects:
            raise storage_module.ObjectNotFound(key)
        return self.objects[key]

    def head(self, key):
        if key not in self.objects:
            raise storage_module.ObjectNotFound(key)
        return storage_module.StoredObject(
            key=key, size_bytes=len(self.objects[key]), content_type=""
        )

    def delete(self, key):
        self.objects.pop(key, None)

    def presigned_put_url(self, key, content_type, expires_in=900):
        return f"https://files.test/put/{key}"

    def presigned_get_url(self, key, expires_in=3600):
        return f"https://files.test/get/{key}"


@pytest.fixture()
def fake_storage(monkeypatch):
    fake = _FakeStorage()
    for name in (
        "put_bytes",
        "fetch",
        "head",
        "delete",
        "presigned_put_url",
        "presigned_get_url",
    ):
        monkeypatch.setattr(storage_module.storage, name, getattr(fake, name))
    return fake


def _make_user(db, account_number, email, account_types, name="Preview User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# -- print listings -------------------------------------------------------


def _stl():
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 49 + b"\x00"


def _publish(client, user, title="Socket rail 10mm"):
    resp = client.post(
        "/api/prints/files",
        data={
            "title": title,
            "description": "A rail that holds ten sockets.",
            "category": "socket-wrench",
            "note": "First cut.",
        },
        files={"print_file": ("rail.stl", _stl(), "application/octet-stream")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp


def test_print_preview_matches_real_non_owner_view(client, db, fake_storage):
    publisher = _make_user(db, "TV-M-003001", "vp-pub@example.com", (MECHANIC,), "Pete Publisher")
    rater = _make_user(db, "TV-M-003002", "vp-rate@example.com", (MECHANIC,), "Rae Rater")
    stranger = _make_user(db, "TV-M-003003", "vp-str@example.com", (MECHANIC,), "Sam Stranger")

    body = _publish(client, publisher).json()
    file_id = body["id"]

    # The rater rates and comments; the publisher comments too —
    # viewer-shaped fields (my_rating, comment mine flags) now
    # differ per reader, which is exactly what the preview must
    # strip back to the no-relationship shape.
    rated = client.post(
        f"/api/prints/files/{file_id}/rate",
        json={"stars": 4},
        headers=auth_headers(rater),
    )
    assert rated.status_code == 200, rated.text
    for user, text in ((rater, "Holds great."), (publisher, "Thanks all.")):
        posted = client.post(
            f"/api/prints/files/{file_id}/comments",
            json={"body": text},
            headers=auth_headers(user),
        )
        assert posted.status_code == 201, posted.text

    preview = client.get(
        f"/api/prints/files/{file_id}",
        params={"as_visitor": "true"},
        headers=auth_headers(publisher),
    )
    assert preview.status_code == 200, preview.text
    real = client.get(f"/api/prints/files/{file_id}", headers=auth_headers(stranger))
    assert real.status_code == 200
    assert preview.json() == real.json()
    assert preview.json()["mine"] is False
    assert preview.json()["my_rating"] is None
    # The aggregate rating survives — it is every visitor's fact.
    assert preview.json()["rating"] == {"average": 4.0, "count": 1}

    preview_comments = client.get(
        f"/api/prints/files/{file_id}/comments",
        params={"as_visitor": "true"},
        headers=auth_headers(publisher),
    )
    real_comments = client.get(
        f"/api/prints/files/{file_id}/comments", headers=auth_headers(stranger)
    )
    assert preview_comments.json() == real_comments.json()
    assert all(c["mine"] is False for c in preview_comments.json()["comments"])

    # The owner's ordinary read is untouched by all this.
    own = client.get(f"/api/prints/files/{file_id}", headers=auth_headers(publisher))
    assert own.json()["mine"] is True
    own_comments = client.get(
        f"/api/prints/files/{file_id}/comments", headers=auth_headers(publisher)
    )
    assert any(c["mine"] for c in own_comments.json()["comments"])


def test_print_preview_is_publisher_only(client, db, fake_storage):
    publisher = _make_user(db, "TV-M-003011", "vp2-pub@example.com", (MECHANIC,))
    other = _make_user(db, "TV-M-003012", "vp2-oth@example.com", (MECHANIC,))
    file_id = _publish(client, publisher).json()["id"]

    for headers in (auth_headers(other), None):
        resp = client.get(
            f"/api/prints/files/{file_id}",
            params={"as_visitor": "true"},
            headers=headers,
        )
        assert resp.status_code == 403, resp.text
        resp = client.get(
            f"/api/prints/files/{file_id}/comments",
            params={"as_visitor": "true"},
            headers=headers,
        )
        assert resp.status_code == 403, resp.text

    # The ordinary reads still answer everyone as before.
    assert client.get(f"/api/prints/files/{file_id}").status_code == 200
    assert (
        client.get(f"/api/prints/files/{file_id}", headers=auth_headers(other)).status_code
        == 200
    )


# -- dealer pages ---------------------------------------------------------


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(
        id=uuid.uuid4(), owner_id=None, name="Matco Tools", is_directory=True
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _represent(db, user, company, verified=True):
    row = dealer_models.CompanyRepresentation(
        id=uuid.uuid4(),
        agent_user_id=user.id,
        company_id=company.id,
        verified=verified,
    )
    db.add(row)
    db.commit()
    return row


def test_dealer_preview_matches_plain_member_view(client, db, company):
    rep = _make_user(db, "TV-D-003001", "vp-rep@example.com", (DEALER,), "Rita Rep")
    member = _make_user(db, "TV-M-003021", "vp-mem@example.com", (MECHANIC,), "Mike Member")
    _represent(db, rep, company)

    # The representative's own view is personal: a personal
    # rename rides over the directory name in everything THEY
    # see. The preview must strip it back to the raw directory
    # view a plain member gets.
    edited = client.put(
        f"/api/dealers/companies/{company.id}/personal-edit",
        json={"name": "Rita's Matco"},
        headers=auth_headers(rep),
    )
    assert edited.status_code == 200, edited.text
    own = client.get(
        f"/api/dealers/companies/{company.id}/detail", headers=auth_headers(rep)
    ).json()
    assert own["company"]["name"] == "Rita's Matco"
    assert own["company"]["personal_edit"] == {"fields": ["name"]}

    preview = client.get(
        f"/api/dealers/companies/{company.id}/detail",
        params={"as_visitor": "true"},
        headers=auth_headers(rep),
    )
    assert preview.status_code == 200, preview.text
    real = client.get(
        f"/api/dealers/companies/{company.id}/detail", headers=auth_headers(member)
    ).json()
    assert preview.json() == real
    assert preview.json()["company"]["name"] == "Matco Tools"
    assert preview.json()["company"]["personal_edit"] is None
    assert preview.json()["my_preferred_agents"] == []


def test_dealer_preview_records_and_roster_are_the_empty_member_set(
    client, db, company
):
    rep = _make_user(db, "TV-D-003002", "vp2-rep@example.com", (DEALER,), "Rita Rep")
    # The comparison member carries the same module frame as
    # the caller (a dealer-group account: the dealers seat
    # turns the records' claims block on through the two-seat
    # gate) but NO relationship with this company — no
    # representation, no agents, no records. The preview's
    # claims gate is computed for the caller as the page's
    # frame (module reach is not part of the personal layer),
    # so the member whose frame matches is the honest
    # side-by-side; the personal CONTENTS are the empty set
    # for both.
    member = _make_user(db, "TV-D-003022", "vp2-mem@example.com", (DEALER,), "Dan Dealer")
    _represent(db, rep, company)

    for path in ("my-records", "roster"):
        preview = client.get(
            f"/api/dealers/companies/{company.id}/{path}",
            params={"as_visitor": "true"},
            headers=auth_headers(rep),
        )
        assert preview.status_code == 200, preview.text
        real = client.get(
            f"/api/dealers/companies/{company.id}/{path}",
            headers=auth_headers(member),
        )
        assert real.status_code == 200
        assert preview.json() == real.json(), path
    records = client.get(
        f"/api/dealers/companies/{company.id}/my-records",
        params={"as_visitor": "true"},
        headers=auth_headers(rep),
    ).json()
    assert records["items"] == []
    assert records["stats"]["items_count"] == 0


def test_dealer_preview_is_representatives_only(client, db, company):
    rep = _make_user(db, "TV-D-003003", "vp3-rep@example.com", (DEALER,), "Rita Rep")
    member = _make_user(db, "TV-M-003023", "vp3-mem@example.com", (MECHANIC,), "Mike Member")
    _represent(db, rep, company)

    for path in ("detail", "my-records", "roster"):
        resp = client.get(
            f"/api/dealers/companies/{company.id}/{path}",
            params={"as_visitor": "true"},
            headers=auth_headers(member),
        )
        assert resp.status_code == 403, (path, resp.text)
    resp = client.get(
        f"/api/flyers/companies/{company.id}",
        params={"as_visitor": "true"},
        headers=auth_headers(member),
    )
    assert resp.status_code == 403, resp.text

    # A private company has no visitor view at all: even its
    # owner's preview request is refused (every other member
    # gets a 404 for the page itself).
    created = client.post(
        "/api/dealers/companies",
        json={"name": "My Own Shop", "email": "", "website": "", "address": "", "phones": [], "notes": ""},
        headers=auth_headers(member),
    )
    assert created.status_code == 201, created.text
    resp = client.get(
        f"/api/dealers/companies/{created.json()['id']}/detail",
        params={"as_visitor": "true"},
        headers=auth_headers(member),
    )
    assert resp.status_code == 403, resp.text


def _pdf_bytes():
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    doc.new_page(612, 792)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_dealer_preview_flyers_tab_has_no_posting_rights(
    client, db, company, fake_storage
):
    rep = _make_user(db, "TV-D-003004", "vp4-rep@example.com", (DEALER,), "Rita Rep")
    member = _make_user(db, "TV-M-003024", "vp4-mem@example.com", (MECHANIC,), "Mike Member")
    _represent(db, rep, company, verified=True)
    source = flyer_service.get_or_create_source(
        db, rep, kind="company", company_id=company.id
    )
    flyer_service._store_flyer(
        db,
        rep,
        source,
        _pdf_bytes(),
        origin="upload",
        origin_url="",
        label="Weekly deals",
        starts_on=TODAY - timedelta(days=1),
        ends_on=TODAY + timedelta(days=6),
        notify=False,
    )

    own = client.get(
        f"/api/flyers/companies/{company.id}", headers=auth_headers(rep)
    ).json()
    assert any(s["can_post"] for s in own["sources"])

    preview = client.get(
        f"/api/flyers/companies/{company.id}",
        params={"as_visitor": "true"},
        headers=auth_headers(rep),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    # The company's current flyer is a visitor fact (the spot
    # rides every member's default dealer list); the posting
    # rights and the postable list are the manager's alone.
    assert body["postable"] == []
    assert len(body["sources"]) == 1
    assert body["sources"][0]["can_post"] is False
    assert body["sources"][0]["current"]["label"] == "Weekly deals"

    real = client.get(
        f"/api/flyers/companies/{company.id}", headers=auth_headers(member)
    ).json()
    assert real["sources"] == body["sources"]
    assert real["postable"] == []
