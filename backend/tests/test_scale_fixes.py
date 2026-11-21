"""Scale fixes (2026-10-26; scale-proof audit B1/B2/B3 + F-11):

  - Tool Expansion reads run over a per-process pool snapshot
    (built once, invalidated by writes, TTL-backstopped) instead
    of a whole-pool recompute per call — with the suggestion
    CONTENT, the per-viewer spelling votes, the opt-out's
    immediacy and the user controls' immediacy all unchanged.
  - tools.model_norm / batteries.model_norm exist, are indexed,
    and are maintained on every ORM write (migration 0062 +
    mapper listeners) with the same fold norm_model computes.
  - Inventory list serialization batches its per-row lookups via
    serialize_context: identical payloads, a page's worth of
    queries instead of a page-times-rows worth.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import event, func, select

from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inv_models
from app.modules.inventory import service as inv_service
from app.modules.tool_expansion import service as te_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


# -- model_norm ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("DCF891", "dcf891"),
        ("  DCF  891 ", "dcf 891"),
        ("", ""),
        (None, ""),
        ("SPRB4A", "sprb4a"),
        ("M18\tFuel", "m18 fuel"),
    ],
)
def test_model_norm_fold_matches_norm_model(raw, expected):
    """The mapper-maintained fold (inventory.models._model_norm),
    migration 0062's frozen copy, and the canonical
    tool_expansion.service.norm_model are the same function."""
    assert inv_models._model_norm(raw) == expected
    assert te_service.norm_model(raw) == expected

    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0062_model_norm.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0062_norm", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._norm_model(raw) == expected


def test_model_norm_maintained_on_insert_and_update(db, user_a):
    tool = inv_models.Tool(
        owner_id=user_a.id, name="Wrench", model="  DCF  891 "
    )
    battery = inv_models.Battery(
        owner_id=user_a.id, name="Pack", model="M18 B5"
    )
    db.add_all([tool, battery])
    db.commit()
    assert tool.model_norm == "dcf 891"
    assert battery.model_norm == "m18 b5"

    tool.model = "NEW-1"
    db.commit()
    db.refresh(tool)
    assert tool.model_norm == "new-1"


def test_migration_0062_backfills_and_indexes():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0062_model_norm.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0062", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    tool_id, battery_id = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE tools (id VARCHAR(36) PRIMARY KEY,"
                " model VARCHAR(200))"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE batteries (id VARCHAR(36) PRIMARY KEY,"
                " model VARCHAR(200))"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE tool_expansion_reports ("
                "id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36),"
                " anchor_model VARCHAR(200), suggested_model VARCHAR(200))"
            )
        )
        conn.execute(
            sa.text("INSERT INTO tools (id, model) VALUES (:i, ' DCF  891 ')"),
            {"i": tool_id},
        )
        conn.execute(
            sa.text("INSERT INTO batteries (id, model) VALUES (:i, 'M18 B5')"),
            {"i": battery_id},
        )

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.upgrade()
        conn.commit()

        assert conn.execute(
            sa.text("SELECT model_norm FROM tools WHERE id = :i"),
            {"i": tool_id},
        ).scalar() == "dcf 891"
        assert conn.execute(
            sa.text("SELECT model_norm FROM batteries WHERE id = :i"),
            {"i": battery_id},
        ).scalar() == "m18 b5"
        index_names = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA index_list('tools')"))
        } | {
            row[1]
            for row in conn.execute(sa.text("PRAGMA index_list('batteries')"))
        } | {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA index_list('tool_expansion_reports')")
            )
        }
        assert "ix_tools_model_norm" in index_names
        assert "ix_batteries_model_norm" in index_names
        assert "ix_tool_expansion_reports_pair" in index_names

        with Operations.context(ctx):
            migration.downgrade()
        conn.commit()
        cols = {
            row[1] for row in conn.execute(sa.text("PRAGMA table_info('tools')"))
        }
        assert "model_norm" not in cols


# -- serialize_context equivalence + query counts ------------------------------


def _strip_signed_urls(obj):
    """Presigned/thumb URLs are time-signed by design — they
    differ between ANY two calls, old code included. Compare
    payloads with the signature material removed."""
    if isinstance(obj, dict):
        return {k: _strip_signed_urls(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_signed_urls(v) for v in obj]
    if isinstance(obj, str) and obj.startswith(("http://", "https://", "/api/")):
        return obj.split("?")[0]
    return obj


def _rich_page(db, owner):
    """A page exercising every per-row lookup the serializers
    make: a set with pieces + an attached tool, dealer tags, item
    tags, a replaced marker, a business-use row, a battery in a
    tool."""
    company = dealer_models.DealerCompany(name="Acme", is_directory=True)
    db.add(company)
    db.flush()
    from app.modules.core import insurance as core_insurance  # noqa: F401

    profile = core_models.InsuranceProfile(
        user_id=owner.id, business_sub_limit_cents=1000, policy_type="standard"
    )
    db.add(profile)
    aset = inv_models.Tool(
        owner_id=owner.id, name="Set", model="SET-1", is_set=True,
        dealer_company_id=company.id,
    )
    plain = inv_models.Tool(
        owner_id=owner.id, name="Plain", model="P-1", business_use=True,
        dealer_company_id=company.id,
    )
    attached = inv_models.Tool(
        owner_id=owner.id, name="Attached", model="A-1", purchase_price=10,
    )
    old = inv_models.Tool(
        owner_id=owner.id, name="Old", model="O-1",
        replaced_by_item_id=plain.id,
    )
    db.add_all([aset, plain, attached, old])
    db.flush()
    attached.attached_to_set_id = aset.id
    db.add_all(
        [
            inv_models.SetPiece(
                set_id=aset.id, owner_id=owner.id, kind="core",
                name="Core", part_number="C-1", sort_order=1,
            ),
            inv_models.SetPiece(
                set_id=aset.id, owner_id=owner.id, kind="addon",
                name="Addon", part_number="AD-1", sort_order=2,
            ),
        ]
    )
    battery = inv_models.Battery(
        owner_id=owner.id, name="Batt", model="B-1",
        currently_in_tool_id=plain.id, dealer_company_id=company.id,
        replaced_by_item_id=aset.id,
    )
    db.add(battery)
    tag = inv_models.Tag(owner_id=owner.id, name="fav", color="red")
    db.add(tag)
    db.flush()
    db.add_all(
        [
            inv_models.ItemTag(
                owner_id=owner.id, tag_id=tag.id, item_kind="tool",
                tool_id=aset.id,
            ),
            inv_models.ItemTag(
                owner_id=owner.id, tag_id=tag.id, item_kind="battery",
                battery_id=battery.id,
            ),
        ]
    )
    db.commit()
    return [aset, plain, attached, old], [battery]


def test_serialize_context_payloads_identical(db, user_a):
    tools, batteries = _rich_page(db, user_a)
    plain_tools = [
        _strip_signed_urls(inv_service.serialize_tool(db, t)) for t in tools
    ]
    ctx = inv_service.serialize_context(db, tools=tools, batteries=batteries)
    ctx_tools = [
        _strip_signed_urls(inv_service.serialize_tool(db, t, ctx=ctx))
        for t in tools
    ]
    assert ctx_tools == plain_tools

    plain_batts = [
        _strip_signed_urls(inv_service.serialize_battery(db, b))
        for b in batteries
    ]
    ctx_batts = [
        _strip_signed_urls(inv_service.serialize_battery(db, b, ctx=ctx))
        for b in batteries
    ]
    assert ctx_batts == plain_batts

    # dealer hidden: the ctx path hides exactly like the plain path
    hidden_ctx = inv_service.serialize_context(
        db, tools=tools, dealer_visible=False
    )
    for t in tools:
        assert inv_service.serialize_tool(
            db, t, dealer_visible=False, ctx=hidden_ctx
        )["dealer_company_name"] == inv_service.serialize_tool(
            db, t, dealer_visible=False
        )["dealer_company_name"]


def test_serialize_context_collapses_query_count(db, user_a):
    tools, batteries = _rich_page(db, user_a)
    # A page's shape at 6x the rows: repeat the lookups' targets.
    page = tools * 6
    engine = db.get_bind()
    counter = {"n": 0}

    def count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        counter["n"] = 0
        for t in page:
            inv_service.serialize_tool(db, t)
        legacy = counter["n"]
        counter["n"] = 0
        ctx = inv_service.serialize_context(db, tools=page, batteries=batteries)
        for t in page:
            inv_service.serialize_tool(db, t, ctx=ctx)
        batched = counter["n"]
    finally:
        event.remove(engine, "before_cursor_execute", count)
    # The batched page (24 tools, tags/dealer/sets/replaced rows
    # throughout) costs a small constant; the per-row path costs
    # several queries per tool.
    assert batched < 25, batched
    assert legacy > batched * 4, (legacy, batched)


# -- pool snapshot behaviour ----------------------------------------------------


def _make_user(db, account_number, email, *, contribute=True):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Scale User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        catalog_contribute=contribute,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_set(client, user, *, name, model, pieces):
    resp = client.post(
        "/api/inventory",
        json={
            "name": name, "brand": "Acme", "model": model, "is_set": True,
            "pieces": [
                {"kind": k, "name": n, "part_number": p} for k, n, p in pieces
            ],
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_pool_snapshot_builds_once_and_invalidates_on_write(
    client, db, monkeypatch
):
    source = _make_user(db, "TV-M-002001", "s1@example.com")
    viewer = _make_user(db, "TV-M-002002", "v1@example.com")
    _add_set(
        client, source, name="Source set", model="SS-9",
        pieces=[("core", "Core 1", "C-1"), ("addon", "Addon 1", "AD-1")],
    )
    _add_set(
        client, viewer, name="Viewer set", model="SS-9",
        pieces=[("core", "Core 1", "C-1")],
    )

    builds = {"n": 0}
    real_build = te_service._build_snapshot

    def counting_build(session, epoch):
        builds["n"] += 1
        return real_build(session, epoch)

    monkeypatch.setattr(te_service, "_build_snapshot", counting_build)
    te_service.invalidate_pool_cache()

    first = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert builds["n"] == 1
    models_first = {
        s["suggested_model"]
        for g in first["groups"]
        for s in g["suggestions"]
    }
    assert models_first == {"ad-1"}

    # summary + counts ride the SAME snapshot — no rebuild.
    client.get("/api/tool-expansion/summary", headers=auth_headers(viewer))
    client.get("/api/tool-expansion/counts", headers=auth_headers(viewer))
    assert builds["n"] == 1

    # A pool write (a new source set with a new addon for the same
    # set model) invalidates at the write: the very next read
    # rebuilds and already carries the new suggestion.
    _add_set(
        client, source, name="Source set two", model="SS-9",
        pieces=[("addon", "Addon 2", "AD-2")],
    )
    second = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert builds["n"] == 2
    models_second = {
        s["suggested_model"]
        for g in second["groups"]
        for s in g["suggestions"]
    }
    assert models_second == {"ad-1", "ad-2"}


def test_pool_snapshot_ttl_backstop(client, db):
    source = _make_user(db, "TV-M-002003", "s2@example.com")
    viewer = _make_user(db, "TV-M-002004", "v2@example.com")
    _add_set(
        client, source, name="Source set", model="SS-7",
        pieces=[("addon", "Addon 1", "AD-1")],
    )
    _add_set(
        client, viewer, name="Viewer set", model="SS-7", pieces=[],
    )
    te_service.invalidate_pool_cache()
    resp = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    )
    assert resp.status_code == 200
    snap = te_service._pool_snapshot
    assert snap is not None
    # Age the snapshot past its TTL: the next read rebuilds even
    # with no write — the multi-worker backstop.
    import time as _time

    snap.built_at = _time.monotonic() - te_service.POOL_TTL_SECONDS - 1
    fresh = te_service._pool(db)
    assert fresh is not snap


def test_opt_out_removes_weight_immediately(client, db):
    source = _make_user(db, "TV-M-002005", "s3@example.com")
    viewer = _make_user(db, "TV-M-002006", "v3@example.com")
    _add_set(
        client, source, name="Source set", model="SS-5",
        pieces=[("addon", "Addon 1", "AD-1")],
    )
    _add_set(
        client, viewer, name="Viewer set", model="SS-5", pieces=[],
    )
    before = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert before["total"] == 1

    # The Settings -> Sharing write path: flipping the flag is a
    # User write; its flush invalidates the snapshot, so the very
    # next read carries none of the source's weight.
    source.catalog_contribute = False
    db.commit()
    after = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert after["total"] == 0


def test_dismissal_and_report_bite_with_warm_cache(client, db):
    source = _make_user(db, "TV-M-002007", "s4@example.com")
    viewer = _make_user(db, "TV-M-002008", "v4@example.com")
    _add_set(
        client, source, name="Source set", model="SS-3",
        pieces=[("addon", "Addon 1", "AD-1"), ("addon", "Addon 2", "AD-2")],
    )
    mine = _add_set(client, viewer, name="Viewer set", model="SS-3", pieces=[])
    resp = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    )
    assert resp.json()["total"] == 2  # cache now warm

    # Dismissal: live ledger read — gone on the next read, the
    # other suggestion untouched.
    resp = client.post(
        "/api/tool-expansion/dismiss",
        json={
            "anchor_kind": "tool",
            "anchor_id": mine["id"],
            "suggested_model": "AD-1",
        },
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 204, resp.text
    after = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert after["total"] == 1
    assert after["groups"][0]["suggestions"][0]["suggested_model"] == "ad-2"

    # A report hides the pairing for the reporter at once.
    resp = client.post(
        "/api/tool-expansion/report",
        json={"anchor_model": "SS-3", "suggested_model": "AD-2"},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 204, resp.text
    after = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert after["total"] == 0


def test_pool_query_shape_is_column_light(db, user_a):
    """The snapshot build must never SELECT a full Tool row (the
    JSONB attachments/custom_data haul was the original sin):
    every statement it issues names its columns."""
    engine = db.get_bind()
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        te_service.invalidate_pool_cache()
        te_service._pool(db)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    tool_selects = [
        s for s in statements if "FROM tools" in s and s.strip().upper().startswith("SELECT")
    ]
    assert tool_selects, statements
    for stmt in tool_selects:
        assert "attachments" not in stmt, stmt
        assert "custom_data" not in stmt, stmt


# -- the cross-process pool epoch ------------------------------------------------


def test_pool_epoch_makes_sibling_worker_see_writes(client, db):
    """Simulates a sibling API worker: it still holds the pre-write
    snapshot object (nobody invalidated ITS memory), yet its next
    read must rebuild — the shared epoch moved with the write."""
    source = _make_user(db, "TV-M-002010", "s10@example.com")
    viewer = _make_user(db, "TV-M-002011", "v10@example.com")
    _add_set(
        client, source, name="Source set", model="SS-5",
        pieces=[("addon", "Addon 1", "AD-1")],
    )
    _add_set(client, viewer, name="Viewer set", model="SS-5", pieces=[])
    te_service.invalidate_pool_cache()
    first = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    assert first["total"] == 1
    warm = te_service._pool_snapshot
    assert warm is not None

    _add_set(
        client, source, name="Source set two", model="SS-5",
        pieces=[("addon", "Addon 2", "AD-2")],
    )
    # Stand in for the sibling worker: restore the stale snapshot
    # object it never stopped holding. Only the epoch can save it.
    te_service._pool_snapshot = warm
    assert te_service._read_epoch(db) != warm.epoch
    second = client.get(
        "/api/tool-expansion/suggestions", headers=auth_headers(viewer)
    ).json()
    models_second = {
        s["suggested_model"]
        for g in second["groups"]
        for s in g["suggestions"]
    }
    assert models_second == {"ad-1", "ad-2"}


def test_pool_epoch_bumps_only_on_pool_writes(client, db):
    from app.modules.inventory import schemas as inv_schemas

    user = _make_user(db, "TV-M-002012", "epoch@example.com")
    before = te_service._read_epoch(db)
    # Categories are organizational only — they do not feed the
    # pool, so the epoch must not move.
    inv_service.create_category(db, user.id, "Epoch Neutral")
    assert te_service._read_epoch(db) == before
    inv_service.create_tool(
        db, user.id, inv_schemas.ToolCreate(name="Epoch Mover", model="EM-1")
    )
    assert te_service._read_epoch(db) > before


def test_migration_0063_pool_epoch_table():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0063_te_pool_epoch.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0063", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0062_model_norm"

    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.upgrade()
        conn.commit()
        rows = conn.execute(
            sa.text("SELECT id, epoch FROM te_pool_epoch")
        ).fetchall()
        assert rows == [(1, 0)]
        with Operations.context(ctx):
            migration.op = Operations(ctx)
            migration.downgrade()
        conn.commit()
        tables = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "te_pool_epoch" not in tables
