"""Flyers module (owner order, 2026-11-05 #10; posting gate
tightened 2026-11-06 22:15 — only registered dealers/agents
post): posting rights (the company-owning dealer account /
verified company rep / the platform agent himself; private
records and non-dealer-owned companies confer NONE), the
three intake routes (guarded link download, PDF upload,
photo scan with corner nudge), the standing-URL daily pull
with content-hash dedupe plus the SYSTEM official-link pull
(22:20 — a dealer's own standing address overrides the
platform's link), the current/history window, source
visibility, the connected-user notification with its own off
switch, the module gate, and the account-deletion cascade.
"""

import io
import uuid
from datetime import date, timedelta

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.flyers import models as flyer_models
from app.modules.flyers import service as flyer_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"
TODAY = date.today()


def _make_user(db, account_number, email, account_types, name="Flyer User"):
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


@pytest.fixture()
def rep(db):
    return _make_user(db, "TV-D-000601", "rep@example.com", (DEALER,), "Rita Rep")


@pytest.fixture()
def agent(db):
    return _make_user(db, "TV-D-000602", "andy@example.com", (DEALER,), "Andy Agent")


@pytest.fixture()
def mechanic(db):
    return _make_user(
        db, "TV-M-000601", "mike@example.com", (MECHANIC,), "Mike Mechanic"
    )


@pytest.fixture()
def stranger(db):
    return _make_user(
        db, "TV-M-000602", "sam@example.com", (MECHANIC,), "Sam Stranger"
    )


@pytest.fixture()
def company(db):
    row = dealer_models.DealerCompany(
        id=uuid.uuid4(), owner_id=None, name="Matco Tools", is_directory=True
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _represent(db, user, company, verified):
    row = dealer_models.CompanyRepresentation(
        id=uuid.uuid4(),
        agent_user_id=user.id,
        company_id=company.id,
        verified=verified,
    )
    db.add(row)
    db.commit()
    return row


def _pdf_bytes(pages=1):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(612, 792)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class _FakeStorage:
    """Dict-backed stand-in for the object store."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, data, content_type):
        self.objects[key] = bytes(data)
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


def _window(days=6):
    return TODAY, TODAY + timedelta(days=days)


def _company_source(db, user, company):
    return flyer_service.get_or_create_source(
        db, user, kind="company", company_id=company.id
    )


# -- posting rights ---------------------------------------------------


def test_verified_rep_posts_company_flyer_by_upload(
    db, client, rep, company, fake_storage
):
    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    starts, ends = _window()
    issued = client.post(
        "/api/flyers/uploads/pdf-url",
        json={
            "filename": "weekly.pdf",
            "content_type": "application/pdf",
            "size_bytes": 100,
        },
        headers=auth_headers(rep),
    )
    assert issued.status_code == 200, issued.text
    key = issued.json()["key"]
    fake_storage.objects[key] = _pdf_bytes()
    posted = client.post(
        f"/api/flyers/sources/{source.id}/flyers/upload",
        json={"key": key, "label": "Weekly deals", "starts_on": str(starts), "ends_on": str(ends)},
        headers=auth_headers(rep),
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["page_count"] == 1
    assert body["thumb_url"] and body["pdf_url"]
    assert body["is_current"] is True
    stored = db.query(flyer_models.Flyer).one()
    assert stored.origin == "upload"
    assert stored.pdf_key in fake_storage.objects
    assert stored.thumb_key in fake_storage.objects
    # The staging object was consumed.
    assert key not in fake_storage.objects


def test_unverified_rep_cannot_post_company_flyer(db, rep, agent, company):
    _represent(db, rep, company, verified=False)
    with pytest.raises(flyer_service.FlyerError):
        _company_source(db, rep, company)
    # An agent with NO representation at all can't either.
    with pytest.raises(flyer_service.FlyerError):
        _company_source(db, agent, company)


def test_platform_agent_posts_own_spot_only(db, agent, rep, company, fake_storage):
    _represent(db, agent, company, verified=False)
    source = flyer_service.get_or_create_source(
        db, agent, kind="agent", company_id=company.id, agent_user_id=agent.id
    )
    starts, ends = _window()
    flyer = flyer_service.post_from_upload(
        db,
        agent,
        source,
        key=_stage(fake_storage, agent, _pdf_bytes()),
        label="Andy's deals",
        starts_on=starts,
        ends_on=ends,
    )
    assert flyer.source_id == source.id
    # Another dealer seat can't post to Andy's spot.
    _represent(db, rep, company, verified=True)
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.post_from_upload(
            db,
            rep,
            source,
            key=_stage(fake_storage, rep, _pdf_bytes()),
            label="hijack",
            starts_on=starts,
            ends_on=ends,
        )


def _stage(fake_storage, user, data, ext="pdf"):
    key = f"flyer-staging/{user.id}/{uuid.uuid4().hex}-file.{ext}"
    fake_storage.objects[key] = data
    return key


def _private_record(db, owner, company, name="Pete"):
    record = dealer_models.PrivateAgent(
        id=uuid.uuid4(), owner_id=owner.id, company_id=company.id, name=name
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _private_source_row(db, owner, company, record):
    """A private-agent spot row as it could exist from before
    the gate (inserted directly — the service refuses to open
    one now)."""
    source = flyer_models.FlyerSource(
        kind="agent",
        company_id=company.id,
        private_agent_id=record.id,
        created_by_id=owner.id,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_private_agent_record_confers_no_posting(
    db, mechanic, stranger, company, fake_storage
):
    """The gate (owner, 2026-11-06 22:15): adding your own
    agent record gives you NO flyer posting — the spot can't
    be opened, every intake refuses, and nothing is offered
    in the postable list. The spot itself stays visible to
    its owner only."""
    record = _private_record(db, mechanic, company)
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.get_or_create_source(
            db, mechanic, kind="agent", company_id=company.id,
            private_agent_id=record.id,
        )
    # Even a spot row that already exists is unpostable.
    source = _private_source_row(db, mechanic, company, record)
    assert flyer_service.can_post_source(db, mechanic, source) is False
    starts, ends = _window()
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.post_from_upload(
            db,
            mechanic,
            source,
            key=_stage(fake_storage, mechanic, _pdf_bytes()),
            label="Pete's flyer",
            starts_on=starts,
            ends_on=ends,
        )
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.update_source_settings(
            db, mechanic, source, standing_url="https://x.example/f.pdf"
        )
    # Even taking a flyer DOWN is a poster's act: a flyer
    # that somehow sits on the spot (stored directly, as a
    # pre-gate leftover could) can't be deleted by its owner.
    leftover = flyer_service._store_flyer(
        db, None, source, _pdf_bytes(), origin="upload", origin_url="",
        label="Old", starts_on=starts, ends_on=ends, notify=False,
    )
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.delete_flyer(db, mechanic, leftover)
    # Nothing is offered to post to — not for the owner, and
    # the stranger never had a path to someone else's record.
    offered = flyer_service.postable_sources(db, mechanic)
    assert all(e["private_agent_id"] is None for e in offered)
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.get_or_create_source(
            db, stranger, kind="agent", company_id=company.id,
            private_agent_id=record.id,
        )
    # Viewing is untouched: the owner still sees the spot;
    # nobody else does.
    assert flyer_service.source_visible_to(db, mechanic.id, source) is True
    assert flyer_service.source_visible_to(db, stranger.id, source) is False
    view = flyer_service.source_view(db, mechanic, source)
    assert view["can_post"] is False


def test_company_owner_must_be_a_dealer_account(
    db, mechanic, rep, fake_storage
):
    """Owning a company posts its flyers ONLY from a dealer
    account; the same company in a mechanic's hands confers
    nothing (owner, 2026-11-06 22:15)."""
    mine = dealer_models.DealerCompany(
        id=uuid.uuid4(), owner_id=mechanic.id, name="Mike's Own", is_directory=False
    )
    db.add(mine)
    db.commit()
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.get_or_create_source(
            db, mechanic, kind="company", company_id=mine.id
        )
    offered = flyer_service.postable_sources(db, mechanic)
    assert all(e["company_id"] != mine.id for e in offered)

    hers = dealer_models.DealerCompany(
        id=uuid.uuid4(), owner_id=rep.id, name="Rita's Own", is_directory=False
    )
    db.add(hers)
    db.commit()
    source = flyer_service.get_or_create_source(
        db, rep, kind="company", company_id=hers.id
    )
    assert flyer_service.can_post_source(db, rep, source) is True
    starts, ends = _window()
    flyer = flyer_service.post_from_upload(
        db,
        rep,
        source,
        key=_stage(fake_storage, rep, _pdf_bytes()),
        label="Rita's deals",
        starts_on=starts,
        ends_on=ends,
    )
    assert flyer.source_id == source.id


# -- the link route -----------------------------------------------------


def test_link_route_posts_pdf_and_rejects_non_pdf(
    db, rep, company, fake_storage, monkeypatch
):
    from app.modules.catalog import manuals

    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    starts, ends = _window()
    monkeypatch.setattr(
        manuals, "_download", lambda url: (_pdf_bytes(), "application/pdf")
    )
    flyer = flyer_service.post_from_link(
        db,
        rep,
        source,
        url="https://matco.example/flyer.pdf",
        label="Linked",
        starts_on=starts,
        ends_on=ends,
    )
    assert flyer.origin == "link"
    assert flyer.origin_url == "https://matco.example/flyer.pdf"
    monkeypatch.setattr(
        manuals, "_download", lambda url: (b"<html>nope</html>", "text/html")
    )
    with pytest.raises(flyer_service.FlyerError):
        flyer_service.post_from_link(
            db,
            rep,
            source,
            url="https://matco.example/page",
            label="Not a pdf",
            starts_on=starts,
            ends_on=ends,
        )


# -- the photo scan route ----------------------------------------------


def _page_photo(skew=12):
    """A synthetic 'photo': a bright paper sheet with text-like
    bars on a dark desk, the whole scene rotated — the paper
    stays a clean quad, the shape the scanner is built for."""
    import cv2
    import numpy as np

    scene = np.full((1200, 1600, 3), 40, dtype=np.uint8)
    paper = np.full((640, 880, 3), 245, dtype=np.uint8)
    for i in range(12):
        y = 36 + i * 48
        cv2.rectangle(
            paper, (44, y), (44 + 480 + (i % 3) * 90, y + 18), (30, 30, 30), -1
        )
    scene[280:920, 360:1240] = paper
    matrix = cv2.getRotationMatrix2D((800, 600), skew, 1.0)
    rotated = cv2.warpAffine(scene, matrix, (1600, 1200))
    photo = rotated[150:1050, 200:1400]  # the camera frame: 1200x900
    ok, buf = cv2.imencode(".jpg", photo)
    assert ok
    return buf.tobytes()


def test_scan_finds_the_page_not_the_boxes_on_it():
    """Regression (flyer lane proof, 2026-11-06): a page
    carrying large printed boxes must not let a box win — the
    detector floors candidates at 8% of the frame and falls
    back to the page contour's minimum-area rectangle when
    soft corners split into extra polygon points."""
    import cv2
    import numpy as np

    from app.modules.flyers import scan

    scene = np.full((1200, 1600, 3), 40, dtype=np.uint8)
    paper = np.full((640, 880, 3), 245, dtype=np.uint8)
    # Big printed boxes — each a clean 4-point contour of its
    # own, several % of the frame once photographed.
    for i in range(3):
        cv2.rectangle(
            paper, (50, 40 + i * 200), (500, 170 + i * 200), (35, 35, 35), -1
        )
    scene[280:920, 360:1240] = paper
    matrix = cv2.getRotationMatrix2D((800, 600), 9, 1.0)
    rotated = cv2.warpAffine(scene, matrix, (1600, 1200))
    photo = rotated[150:1050, 200:1400]
    ok, buf = cv2.imencode(".jpg", photo)
    assert ok
    corners, detected, _w, _h = scan.detect_corners(buf.tobytes())
    assert detected is True
    xs = [pt[0] for pt in corners]
    ys = [pt[1] for pt in corners]
    # The quad spans the PAGE (most of the frame), not a box.
    assert max(xs) - min(xs) > 0.45
    assert max(ys) - min(ys) > 0.45


def test_scan_detects_paper_and_posts_with_nudged_corners(
    db, rep, company, fake_storage
):
    from app.modules.flyers import scan

    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    photo = _page_photo()
    corners, detected, width, height = scan.detect_corners(photo)
    assert detected is True
    assert (width, height) == (1200, 900)
    # The guess hugs the paper (inside the frame, off its edges).
    assert all(0.02 < x < 0.98 for pt in corners for x in pt)
    # Nudge one corner the way a user fixing a bad guess would.
    nudged = [list(pt) for pt in corners]
    nudged[0][0] = min(0.98, nudged[0][0] + 0.02)
    nudged[0][1] = max(0.02, nudged[0][1] - 0.02)
    key1 = _stage(fake_storage, rep, photo, ext="jpg")
    key2 = _stage(fake_storage, rep, _page_photo(skew=-8), ext="jpg")
    starts, ends = _window()
    flyer = flyer_service.post_from_photos(
        db,
        rep,
        source,
        pages=[
            {"key": key1, "corners": nudged},
            {"key": key2, "corners": scan.detect_corners(_page_photo(-8))[0]},
        ],
        label="Scanned",
        starts_on=starts,
        ends_on=ends,
    )
    assert flyer.origin == "photos"
    assert flyer.page_count == 2
    assert key1 not in fake_storage.objects


# -- window, history, visibility ----------------------------------------


def _post(db, user, source, fake_storage, starts, ends, label="F"):
    return flyer_service.post_from_upload(
        db,
        user,
        source,
        key=_stage(fake_storage, user, _pdf_bytes()),
        label=label,
        starts_on=starts,
        ends_on=ends,
    )


def test_expired_flyer_leaves_current_and_history_setting_rules(
    db, rep, mechanic, company, fake_storage
):
    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    # The expired flyer enters through the storage door (the
    # posting routes rightly refuse an already-over window).
    old = flyer_service._store_flyer(
        db,
        rep,
        source,
        _pdf_bytes(),
        origin="upload",
        origin_url="",
        label="Old",
        starts_on=TODAY - timedelta(days=14),
        ends_on=TODAY - timedelta(days=8),
        notify=False,
    )
    new = _post(db, rep, source, fake_storage, *_window(), label="New")
    view = flyer_service.source_view(db, mechanic, source, with_history=True)
    assert view["current"]["id"] == new.id
    assert [h["id"] for h in view["history"]] == [old.id]
    # History off: connected users see the current one only.
    flyer_service.update_source_settings(
        db, rep, source, history_visible=False
    )
    view = flyer_service.source_view(db, mechanic, source, with_history=True)
    assert view["history"] == []
    assert view["current"]["id"] == new.id
    # The poster still sees their own history either way.
    mine = flyer_service.source_view(db, rep, source, with_history=True)
    assert len(mine["history"]) == 1


def test_visibility_toggle_hides_source_from_connected_users(
    db, client, rep, mechanic, company, fake_storage
):
    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    _post(db, rep, source, fake_storage, *_window())
    feed = client.get("/api/flyers/feed", headers=auth_headers(mechanic))
    assert feed.status_code == 200
    assert [s["key"] for s in feed.json()] == [f"company:{company.id}"]
    flyer_service.update_source_settings(db, rep, source, visible=False)
    feed = client.get("/api/flyers/feed", headers=auth_headers(mechanic))
    assert feed.json() == []
    detail = client.get(
        f"/api/flyers/sources/{source.id}", headers=auth_headers(mechanic)
    )
    assert detail.status_code == 404


def test_hidden_company_hides_its_source(db, rep, mechanic, company, fake_storage):
    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    _post(db, rep, source, fake_storage, *_window())
    assert flyer_service.source_visible_to(db, mechanic.id, source) is True
    db.add(
        dealer_models.DealerListHidden(
            id=uuid.uuid4(), user_id=mechanic.id, company_id=company.id
        )
    )
    db.commit()
    assert flyer_service.source_visible_to(db, mechanic.id, source) is False
    assert flyer_service.feed(db, mechanic) == []


# -- notifications -------------------------------------------------------


def test_notification_fires_and_alert_switch_silences(
    db, rep, mechanic, stranger, company, fake_storage
):
    _represent(db, rep, company, verified=True)
    # The stranger hid this dealer: not connected, no alert.
    db.add(
        dealer_models.DealerListHidden(
            id=uuid.uuid4(), user_id=stranger.id, company_id=company.id
        )
    )
    db.commit()
    source = _company_source(db, rep, company)
    _post(db, rep, source, fake_storage, *_window(), label="One")
    notes = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.kind == "flyer_posted")
        .all()
    )
    assert [n.user_id for n in notes] == [mechanic.id]
    assert notes[0].data["source_key"] == f"company:{company.id}"
    # The poster's own alert switch off → silence next time.
    flyer_service.set_alerts_enabled(db, mechanic.id, False)
    assert flyer_service.alerts_enabled(db, mechanic.id) is False
    _post(db, rep, source, fake_storage, *_window(), label="Two")
    count = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.kind == "flyer_posted")
        .count()
    )
    assert count == 1
    # The poster never alerts themselves.
    assert (
        db.query(core_models.Notification)
        .filter(core_models.Notification.user_id == rep.id)
        .count()
        == 0
    )


# -- standing pull --------------------------------------------------------


def test_standing_pull_dedupes_unchanged_and_posts_changed(
    db, rep, mechanic, company, fake_storage, monkeypatch
):
    from app.modules.catalog import manuals

    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    flyer_service.update_source_settings(
        db, rep, source, standing_url="https://matco.example/weekly.pdf"
    )
    payload = {"data": _pdf_bytes()}
    monkeypatch.setattr(
        manuals, "_download", lambda url: (payload["data"], "application/pdf")
    )
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "1 posted" in summary
    assert db.query(flyer_models.Flyer).count() == 1
    posted = db.query(flyer_models.Flyer).one()
    assert posted.origin == "standing"
    assert posted.ends_on == TODAY + timedelta(days=6)
    # Unchanged bytes: no re-post, no re-notify.
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "1 unchanged" in summary
    assert db.query(flyer_models.Flyer).count() == 1
    # Changed bytes: a fresh current flyer posts.
    payload["data"] = _pdf_bytes(pages=2)
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "1 posted" in summary
    assert db.query(flyer_models.Flyer).count() == 2
    # A dead URL counts as failed and never raises.
    def _boom(url):
        raise manuals.ManualError("no route")

    monkeypatch.setattr(manuals, "_download", _boom)
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "1 failed" in summary


def test_standing_pull_skips_private_agent_spots(
    db, mechanic, company, fake_storage, monkeypatch
):
    """Posting was removed from private spots entirely — a
    standing address left on one no longer posts either."""
    from app.modules.catalog import manuals

    record = _private_record(db, mechanic, company)
    source = _private_source_row(db, mechanic, company, record)
    source.standing_url = "https://pete.example/weekly.pdf"
    db.commit()
    monkeypatch.setattr(
        manuals, "_download", lambda url: (_pdf_bytes(), "application/pdf")
    )
    flyer_service.run_standing_pulls(db, today=TODAY)
    assert db.query(flyer_models.Flyer).count() == 0


def _official_company(db, url, name="Mac Tools"):
    row = dealer_models.DealerCompany(
        id=uuid.uuid4(),
        owner_id=None,
        name=name,
        is_directory=True,
        official_flyer_url=url,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_official_pull_posts_dedupes_and_notifies(
    db, mechanic, fake_storage, monkeypatch
):
    """The system pass (owner, 2026-11-06 22:20): a directory
    company's official flyer link posts under its company
    spot all by itself — the spot is created owned by nobody,
    the audience is notified, and an unchanged edition never
    re-posts."""
    from app.modules.catalog import manuals

    brand = _official_company(db, "https://mac.example/flyer.pdf")
    payload = {"data": _pdf_bytes()}
    monkeypatch.setattr(
        manuals, "_download", lambda url: (payload["data"], "application/pdf")
    )
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "official links: 1 posted" in summary
    source = db.query(flyer_models.FlyerSource).one()
    assert source.company_id == brand.id
    assert source.created_by_id is None
    flyer = db.query(flyer_models.Flyer).one()
    assert flyer.origin == "standing"
    assert flyer.posted_by_id is None
    assert flyer.origin_url == "https://mac.example/flyer.pdf"
    assert flyer.ends_on == TODAY + timedelta(days=6)
    # The connected audience heard about it.
    notes = (
        db.query(core_models.Notification)
        .filter(core_models.Notification.kind == "flyer_posted")
        .all()
    )
    assert [n.user_id for n in notes] == [mechanic.id]
    # The feed carries it like any posted flyer.
    feed = flyer_service.feed(db, mechanic)
    assert [s["key"] for s in feed] == [f"company:{brand.id}"]
    # Unchanged edition: no re-post, no re-notify.
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "official links: 0 posted, 1 unchanged" in summary
    assert db.query(flyer_models.Flyer).count() == 1
    # A changed edition posts fresh.
    payload["data"] = _pdf_bytes(pages=2)
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "official links: 1 posted" in summary
    assert db.query(flyer_models.Flyer).count() == 2
    # A dead link counts as failed and never raises.
    def _boom(url):
        raise manuals.ManualError("no route")

    monkeypatch.setattr(manuals, "_download", _boom)
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "official links: 0 posted, 0 unchanged, 1 failed" in summary


def test_official_pull_yields_to_the_posters_own_address(
    db, rep, company, fake_storage, monkeypatch
):
    """A dealer's own standing address OVERRIDES the system
    link: while it is set, the official pass posts nothing
    and the poster pass pulls theirs; clear it and the
    system link takes over again."""
    from app.modules.catalog import manuals

    _represent(db, rep, company, verified=True)
    company.official_flyer_url = "https://brand.example/official.pdf"
    db.commit()
    source = _company_source(db, rep, company)
    flyer_service.update_source_settings(
        db, rep, source, standing_url="https://dealer.example/mine.pdf"
    )
    seen = []

    def _download(url):
        seen.append(url)
        return _pdf_bytes(), "application/pdf"

    monkeypatch.setattr(manuals, "_download", _download)
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert seen == ["https://dealer.example/mine.pdf"]
    assert "official links: 0 posted, 0 unchanged, 0 failed, 1 overridden" in summary
    flyer = db.query(flyer_models.Flyer).one()
    assert flyer.origin_url == "https://dealer.example/mine.pdf"
    # Clear the dealer's address: the system link resumes.
    flyer_service.update_source_settings(db, rep, source, standing_url="")
    seen.clear()
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert seen == ["https://brand.example/official.pdf"]
    assert "official links: 1 posted" in summary
    assert db.query(flyer_models.Flyer).count() == 2


def test_official_pull_skips_a_switched_off_spot(
    db, rep, company, fake_storage, monkeypatch
):
    """A spot switched off is off for the system too."""
    from app.modules.catalog import manuals

    _represent(db, rep, company, verified=True)
    company.official_flyer_url = "https://brand.example/official.pdf"
    db.commit()
    source = _company_source(db, rep, company)
    flyer_service.update_source_settings(db, rep, source, visible=False)
    monkeypatch.setattr(
        manuals, "_download", lambda url: (_pdf_bytes(), "application/pdf")
    )
    summary = flyer_service.run_standing_pulls(db, today=TODAY)
    assert "official links: 0 posted, 0 unchanged, 0 failed, 0 overridden, 1 skipped" in summary
    assert db.query(flyer_models.Flyer).count() == 0


# -- module gate + cascade -------------------------------------------------


def test_module_personally_off_gates_routes(db, client, mechanic):
    db.add(
        core_models.UserModulePref(
            id=uuid.uuid4(), user_id=mechanic.id, module_id="flyers",
            enabled=False,
        )
    )
    db.commit()
    resp = client.get("/api/flyers/feed", headers=auth_headers(mechanic))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"


def test_delete_account_cleans_flyer_rows(db, mechanic, company, fake_storage):
    from app.modules.core import service as core_service

    record = dealer_models.PrivateAgent(
        id=uuid.uuid4(), owner_id=mechanic.id, company_id=company.id, name="Pete"
    )
    db.add(record)
    db.commit()
    # Rows as they could exist from before the posting gate
    # (the service refuses to open a private spot now): the
    # flyer enters through the storage door.
    source = _private_source_row(db, mechanic, company, record)
    flyer_service._store_flyer(
        db,
        mechanic,
        source,
        _pdf_bytes(),
        origin="upload",
        origin_url="",
        label="Old",
        starts_on=TODAY,
        ends_on=TODAY + timedelta(days=6),
        notify=False,
    )
    flyer_service.set_alerts_enabled(db, mechanic.id, False)
    assert db.query(flyer_models.Flyer).count() == 1
    core_service.delete_account(db, mechanic)
    assert db.query(flyer_models.Flyer).count() == 0
    assert db.query(flyer_models.FlyerSource).count() == 0
    assert db.query(flyer_models.FlyerAlertPref).count() == 0


def test_feed_lists_only_sources_with_a_live_flyer(
    db, client, rep, mechanic, company, fake_storage
):
    _represent(db, rep, company, verified=True)
    source = _company_source(db, rep, company)
    feed = client.get("/api/flyers/feed", headers=auth_headers(mechanic))
    assert feed.json() == []  # spot exists but nothing is live
    sources = client.get("/api/flyers/sources", headers=auth_headers(mechanic))
    assert len(sources.json()) == 1  # the tab still shows
    _post(db, rep, source, fake_storage, *_window())
    feed = client.get("/api/flyers/feed", headers=auth_headers(mechanic))
    body = feed.json()
    assert len(body) == 1
    assert body[0]["current"]["thumb_url"].startswith("https://files.test/get/")
    assert body[0]["company_name"] == "Matco Tools"
