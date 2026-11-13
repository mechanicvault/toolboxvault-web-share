"""Help & Support build (2026-11-02): the permanent forum
boards, the site-help room, and the how-to videos list.

Pins:

- Migration 0070: forum_categories gains system_key (+ unique),
  the three built-in rooms seed with fixed ids (Using Toolbox
  Vault / Bug Reports / Feature Requests), help_videos lands;
  downgrade removes all of it.
- The two boards are PERMANENT: the operator category route —
  the strongest write door that exists for a category —
  refuses rename / re-describe / reorder / archive on a board
  row with 422, while ordinary rooms still edit fine. There is
  no category delete route at all (checked by absence).
- The boards carry the feedback engine's live counts on the
  forum's category payload (posts = threads, posts + comments
  = posts), and their newest post rides last_thread_*.
- Forum threads can never be planted inside a board (create
  422, thread list 404): the boards take posts only through
  the feedback boards.
- Feedback globally off → the boards leave the public board
  list (the operator list keeps them); back on → they return.
- Videos: operator-only management, YouTube references
  normalize to the id (watch / short / embed / bare), junk is
  a friendly 422, drafts never reach the member face, publish
  and delete work.
- Ticket summaries carry last_message_author_kind (the help
  page's status strip reads whose message is newest).
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.modules.core import models as core_models
from app.modules.core import module_control
from app.modules.forum import models as forum_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0070_help_support.py"
)


def _make_user(db, account_number, email, *, name="Help User", operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role="user",
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def member(db):
    return _make_user(db, "TV-M-002001", "hmember@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-002002", "hoperator@example.com", operator=True
    )


def _category(db, name, *, system_key=None, sort_order=0, description=""):
    row = forum_models.ForumCategory(
        id=uuid.uuid4(),
        name=name,
        description=description,
        sort_order=sort_order,
        is_active=True,
        system_key=system_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def rooms(db):
    return {
        "help": _category(db, "Using Toolbox Vault", system_key="site_help"),
        "bug": _category(db, "Bug Reports", system_key="bug_reports"),
        "feature": _category(
            db, "Feature Requests", system_key="feature_requests"
        ),
        "plain": _category(db, "Shop Talk"),
    }


# -- the permanent boards ---------------------------------------------------


def test_operator_cannot_edit_permanent_boards(client, operator, rooms):
    for board in (rooms["bug"], rooms["feature"]):
        for payload in (
            {"name": "Renamed"},
            {"description": "New words."},
            {"sort_order": 1},
            {"is_active": False},
        ):
            resp = client.put(
                f"/api/forum/admin/categories/{board.id}",
                json=payload,
                headers=auth_headers(operator),
            )
            assert resp.status_code == 422, (board.name, payload, resp.text)
            assert "permanent" in resp.json()["detail"].lower()
    # The rows stand untouched.
    rows = client.get(
        "/api/forum/admin/categories", headers=auth_headers(operator)
    ).json()
    by_id = {row["id"]: row for row in rows}
    assert by_id[str(rooms["bug"].id)]["name"] == "Bug Reports"
    assert by_id[str(rooms["bug"].id)]["is_active"] is True


def test_operator_can_still_edit_ordinary_rooms(client, operator, rooms):
    resp = client.put(
        f"/api/forum/admin/categories/{rooms['plain'].id}",
        json={"name": "Shop Talk & Crew"},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Shop Talk & Crew"
    # The site-help room is system-seeded but NOT permanent:
    # it stays ordinary operator furniture.
    resp = client.put(
        f"/api/forum/admin/categories/{rooms['help'].id}",
        json={"description": "Ask us anything about the site."},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200


def test_no_category_delete_route(client, operator, rooms):
    resp = client.delete(
        f"/api/forum/admin/categories/{rooms['bug'].id}",
        headers=auth_headers(operator),
    )
    assert resp.status_code in (404, 405)


def test_boards_carry_feedback_counts(client, member, rooms):
    created = client.post(
        "/api/feedback/posts",
        json={
            "board": "bug",
            "title": "The drawer sticks",
            "body": "Third drawer sticks when the box is loaded.",
        },
        headers=auth_headers(member),
    )
    assert created.status_code == 201, created.text
    post = created.json()
    commented = client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Same here on the tall box."},
        headers=auth_headers(member),
    )
    assert commented.status_code == 201, commented.text

    rows = client.get("/api/forum/categories", headers=auth_headers(member)).json()
    by_key = {row["system_key"]: row for row in rows}
    bug = by_key["bug_reports"]
    assert bug["thread_count"] == 1
    assert bug["post_count"] == 2
    assert bug["last_thread_title"] == "The drawer sticks"
    assert bug["last_thread_id"] == post["id"]
    feature = by_key["feature_requests"]
    assert feature["thread_count"] == 0
    assert by_key["site_help"]["name"] == "Using Toolbox Vault"
    assert by_key[None]["name"] == "Shop Talk"


def test_forum_threads_cannot_be_planted_in_a_board(client, member, rooms):
    created = client.post(
        "/api/forum/threads",
        json={
            "category_id": str(rooms["bug"].id),
            "title": "Sneaky thread",
            "body": "Trying to plant a forum thread in the board.",
        },
        headers=auth_headers(member),
    )
    assert created.status_code == 422
    listing = client.get(
        f"/api/forum/categories/{rooms['bug'].id}/threads",
        headers=auth_headers(member),
    )
    assert listing.status_code == 404


def test_boards_follow_the_feedback_switch(client, db, member, operator, rooms):
    module_control.set_global_enabled(db, "feedback", False)
    public = client.get(
        "/api/forum/categories", headers=auth_headers(member)
    ).json()
    keys = {row["system_key"] for row in public}
    assert "bug_reports" not in keys
    assert "feature_requests" not in keys
    assert "site_help" in keys  # the forum-native room stays
    admin = client.get(
        "/api/forum/admin/categories", headers=auth_headers(operator)
    ).json()
    assert {row["system_key"] for row in admin} >= {
        "bug_reports",
        "feature_requests",
    }
    module_control.set_global_enabled(db, "feedback", True)
    public = client.get(
        "/api/forum/categories", headers=auth_headers(member)
    ).json()
    assert "bug_reports" in {row["system_key"] for row in public}


# -- how-to videos ----------------------------------------------------------


def _video_payload(**overrides):
    payload = {
        "title": "Add your first tool",
        "summary": "The two-minute tour of the add-tool wizard.",
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "section": "website",
        "sort_order": 10,
        "is_published": True,
    }
    payload.update(overrides)
    return payload


def test_videos_operator_only_and_publish_flow(client, member, operator):
    # Members can't manage the list.
    assert (
        client.post(
            "/api/admin/support/videos",
            json=_video_payload(),
            headers=auth_headers(member),
        ).status_code
        == 403
    )
    # The member face starts empty (the honest coming-soon state).
    assert (
        client.get("/api/support/videos", headers=auth_headers(member)).json()
        == []
    )

    made = client.post(
        "/api/admin/support/videos",
        json=_video_payload(),
        headers=auth_headers(operator),
    )
    assert made.status_code == 201, made.text
    video = made.json()
    assert video["youtube_id"] == "dQw4w9WgXcQ"
    assert video["is_published"] is True

    member_rows = client.get(
        "/api/support/videos", headers=auth_headers(member)
    ).json()
    assert [row["id"] for row in member_rows] == [video["id"]]
    assert "is_published" not in member_rows[0]

    # A draft never reaches the member face.
    draft = client.post(
        "/api/admin/support/videos",
        json=_video_payload(title="Draft tour", is_published=False),
        headers=auth_headers(operator),
    ).json()
    member_rows = client.get(
        "/api/support/videos", headers=auth_headers(member)
    ).json()
    assert [row["id"] for row in member_rows] == [video["id"]]

    # Publishing the draft through an update does.
    updated = client.put(
        f"/api/admin/support/videos/{draft['id']}",
        json=_video_payload(title="Draft tour", is_published=True),
        headers=auth_headers(operator),
    )
    assert updated.status_code == 200, updated.text
    member_rows = client.get(
        "/api/support/videos", headers=auth_headers(member)
    ).json()
    assert len(member_rows) == 2

    # Delete removes it everywhere.
    assert (
        client.delete(
            f"/api/admin/support/videos/{draft['id']}",
            headers=auth_headers(operator),
        ).status_code
        == 204
    )
    admin_rows = client.get(
        "/api/admin/support/videos", headers=auth_headers(operator)
    ).json()
    assert [row["id"] for row in admin_rows] == [video["id"]]


def test_youtube_reference_forms(client, operator):
    forms = [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    ]
    for form in forms:
        resp = client.post(
            "/api/admin/support/videos",
            json=_video_payload(youtube=form),
            headers=auth_headers(operator),
        )
        assert resp.status_code == 201, (form, resp.text)
        assert resp.json()["youtube_id"] == "dQw4w9WgXcQ"
    junk = client.post(
        "/api/admin/support/videos",
        json=_video_payload(youtube="https://example.com/not-a-video"),
        headers=auth_headers(operator),
    )
    assert junk.status_code == 422


# -- ticket summary ball-in-court -------------------------------------------


def test_ticket_summary_names_whose_message_is_newest(
    client, member, operator
):
    made = client.post(
        "/api/support/tickets",
        json={"subject": "Stuck", "body": "The drawer sticks."},
        headers=auth_headers(member),
    )
    assert made.status_code == 201, made.text
    assert made.json()["last_message_author_kind"] == "user"
    ticket_id = made.json()["id"]
    replied = client.post(
        f"/api/admin/support/tickets/{ticket_id}/messages",
        json={"body": "Try the left rail first."},
        headers=auth_headers(operator),
    )
    assert replied.status_code == 200, replied.text
    rows = client.get(
        "/api/support/tickets", headers=auth_headers(member)
    ).json()
    assert rows[0]["last_message_author_kind"] == "operator"


# -- migration 0070 -----------------------------------------------------------


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0070", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_0070_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
    )
    sa.Table(
        "forum_categories",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    meta.create_all(engine)
    return engine


def _run(engine, fn):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()
        conn.commit()


def test_migration_0070_upgrade_and_downgrade():
    migration = _load_migration()
    engine = _pre_0070_db()
    _run(engine, migration.upgrade)

    inspector = sa.inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("forum_categories")}
    assert "system_key" in cols
    unique_cols = {
        tuple(uc["column_names"])
        for uc in inspector.get_unique_constraints("forum_categories")
    }
    assert ("system_key",) in unique_cols
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT system_key, name, is_active FROM forum_categories"
            )
        ).all()
    seeded = {row[0]: row for row in rows if row[0]}
    assert set(seeded) == {"site_help", "bug_reports", "feature_requests"}
    assert seeded["site_help"][1] == "Using Toolbox Vault"
    assert seeded["bug_reports"][1] == "Bug Reports"
    assert seeded["feature_requests"][1] == "Feature Requests"
    assert all(row[2] for row in seeded.values())

    video_cols = {c["name"] for c in inspector.get_columns("help_videos")}
    assert {
        "id", "title", "summary", "youtube_id", "section",
        "sort_order", "is_published",
    } <= video_cols

    _run(engine, migration.downgrade)
    inspector = sa.inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("forum_categories")}
    assert "system_key" not in cols
    assert "help_videos" not in inspector.get_table_names()
    with engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM forum_categories")
        ).scalar()
    assert count == 0
