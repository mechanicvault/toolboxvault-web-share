"""Step-4 fix round (2026-10-20): the campaign defects D2–D6 + the
jobs scheduler.

Pins:
- D2: the inventory searches sort on the SERVER across the whole
  filtered set (Package B keys + convention, set price_total for
  sets, nulls last), page with limit/offset, and report the total
  in X-Total-Count — any item is reachable by paging, and a price
  sort with sort_dir=desc surfaces the priciest tool FIRST.
- D3: GET /inventory and /inventory/batteries honor limit/offset
  (default page 200) instead of returning the whole vault.
- D4: the sharing preview pages its RESPONSE (resolution still
  runs whole-set) and reports the total; the unpaged payload is
  identical to the paged concatenation.
- D5: a full-set report keeps its summary math under the batched
  row build (dealer names, tags, checked-out status, set totals).
- D6: a moderator removing/discarding a post whose author deleted
  their account succeeds (was a 500: the change_journal write FK'd
  on the dead owner).
- Scheduler: the registry covers all five jobs at their documented
  cadences, runs are ledgered in job_runs (ok AND failed), due
  logic respects the cadence, and the compose file ships the jobs
  service.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.core import sharing
from app.modules.inventory import models as inv_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, account_types=(MECHANIC,), **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=kw.pop("name", "Fix User"),
        password_hash="not-a-real-hash",
        account_types=list(account_types),
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000401", "fix-owner@example.com")


def _tool(db, owner, name, **kw):
    tool = inv_models.Tool(id=uuid.uuid4(), owner_id=owner.id, name=name, **kw)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _battery(db, owner, name, **kw):
    battery = inv_models.Battery(
        id=uuid.uuid4(), owner_id=owner.id, name=name, **kw
    )
    db.add(battery)
    db.commit()
    db.refresh(battery)
    return battery


# -- D2: server-side sort ---------------------------------------------------


def test_search_sorts_by_name_server_side(client, db, owner):
    _tool(db, owner, "Wrench")
    _tool(db, owner, "awl")
    _tool(db, owner, "Magnet")
    response = client.get(
        "/api/inventory/search?sort=name", headers=auth_headers(owner)
    )
    assert response.status_code == 200
    assert [t["name"] for t in response.json()] == ["awl", "Magnet", "Wrench"]
    assert response.headers["X-Total-Count"] == "3"


def test_search_price_sort_uses_extended_total_and_set_total(client, db, owner):
    _tool(db, owner, "Plain", purchase_price=Decimal("10"), quantity=3)  # 30
    _tool(db, owner, "Single", purchase_price=Decimal("50"), quantity=1)  # 50
    _tool(db, owner, "Priceless")  # no price — trails
    big_set = _tool(
        db, owner, "Big Set", purchase_price=Decimal("100"), quantity=1,
        is_set=True,
    )
    db.add(
        inv_models.SetPiece(
            id=uuid.uuid4(), set_id=big_set.id, owner_id=owner.id,
            kind="addon", name="Addon", price=Decimal("999"),
            status="present",
        )
    )
    attached = _tool(
        db, owner, "Attached", purchase_price=Decimal("500"), quantity=2,
    )
    attached.attached_to_set_id = big_set.id
    db.commit()
    # Set total = 100 + 999 + 500*2 = 2099 — the richest row.
    response = client.get(
        "/api/inventory/search?sort=price", headers=auth_headers(owner)
    )
    names = [t["name"] for t in response.json()]
    assert names == ["Plain", "Single", "Big Set", "Priceless"]
    # The campaign's reachability test: most expensive FIRST on desc.
    response = client.get(
        "/api/inventory/search?sort=price&sort_dir=desc",
        headers=auth_headers(owner),
    )
    assert response.json()[0]["name"] == "Big Set"


def test_search_purchase_date_nulls_last(client, db, owner):
    _tool(db, owner, "Dated", purchase_date=datetime(2024, 1, 1).date())
    _tool(db, owner, "Undated")
    _tool(db, owner, "Newer", purchase_date=datetime(2025, 6, 1).date())
    response = client.get(
        "/api/inventory/search?sort=purchase_date",
        headers=auth_headers(owner),
    )
    assert [t["name"] for t in response.json()] == ["Dated", "Newer", "Undated"]


def test_search_sorts_by_status_server_side(client, db, owner):
    # Sheet row 80: STATUS is a sort key — the item's standing,
    # alphabetical under the standard convention.
    _tool(db, owner, "Serviced")  # standing defaults to in_service
    _tool(db, owner, "Busted", standing="broken")
    _tool(db, owner, "InShop", standing="in_repair")
    response = client.get(
        "/api/inventory/search?sort=status", headers=auth_headers(owner)
    )
    assert response.status_code == 200
    assert [t["name"] for t in response.json()] == [
        "Busted",
        "InShop",
        "Serviced",
    ]
    response = client.get(
        "/api/inventory/search?sort=status&sort_dir=desc",
        headers=auth_headers(owner),
    )
    assert [t["name"] for t in response.json()] == [
        "Serviced",
        "InShop",
        "Busted",
    ]


def test_search_all_sorts_by_status_and_quantity(client, db, owner):
    # Both kinds carry the row-80 keys in the merged stream.
    _tool(db, owner, "ToolQty", quantity=4)  # in_service
    _battery(db, owner, "BattQty", quantity=2, standing="lost")
    response = client.get(
        "/api/inventory/search/all?sort=status", headers=auth_headers(owner)
    )
    assert [r["name"] for r in response.json()] == ["ToolQty", "BattQty"]
    response = client.get(
        "/api/inventory/search/all?sort=quantity",
        headers=auth_headers(owner),
    )
    assert [r["name"] for r in response.json()] == ["BattQty", "ToolQty"]
    response = client.get(
        "/api/inventory/search/all?sort=quantity&sort_dir=desc",
        headers=auth_headers(owner),
    )
    assert [r["name"] for r in response.json()] == ["ToolQty", "BattQty"]


def test_search_all_merges_kinds_under_one_sort(client, db, owner):
    _tool(db, owner, "ToolMid", purchase_price=Decimal("20"), quantity=1)
    _battery(db, owner, "BattHigh", purchase_price=Decimal("90"), quantity=1)
    _battery(db, owner, "BattLow", purchase_price=Decimal("5"), quantity=1)
    response = client.get(
        "/api/inventory/search/all?sort=price&sort_dir=desc",
        headers=auth_headers(owner),
    )
    rows = response.json()
    assert [r["name"] for r in rows] == ["BattHigh", "ToolMid", "BattLow"]
    assert [r["item_kind"] for r in rows] == ["battery", "tool", "battery"]
    assert response.headers["X-Total-Count"] == "3"


def test_search_default_sort_is_date_added_newest_first(client, db, owner):
    # Owner spec 2026-10-25: with NO sort specified, the list
    # default is DATE ADDED (created_at), newest first — on the
    # unified stream and the tools-only stream alike. The
    # oldest-added row carries the NEWEST updated_at, so the old
    # newest-touched default would surface it first; the new
    # default must put it last.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    oldest = _tool(db, owner, "AddedFirst")
    middle = _battery(db, owner, "AddedSecond")
    newest = _tool(db, owner, "AddedThird")
    oldest.created_at = base
    oldest.updated_at = base + timedelta(days=90)
    middle.created_at = base + timedelta(days=10)
    middle.updated_at = base + timedelta(days=10)
    newest.created_at = base + timedelta(days=20)
    newest.updated_at = base + timedelta(days=20)
    db.commit()

    rows = client.get(
        "/api/inventory/search/all", headers=auth_headers(owner)
    ).json()
    assert [r["name"] for r in rows] == ["AddedThird", "AddedSecond", "AddedFirst"]
    rows = client.get(
        "/api/inventory/search", headers=auth_headers(owner)
    ).json()
    assert [r["name"] for r in rows] == ["AddedThird", "AddedFirst"]
    # An explicit sort still wins over the default.
    rows = client.get(
        "/api/inventory/search/all?sort=name", headers=auth_headers(owner)
    ).json()
    assert [r["name"] for r in rows] == ["AddedFirst", "AddedSecond", "AddedThird"]


def test_search_all_price_filter_judges_extended_total(client, db, owner):
    _tool(db, owner, "CheapUnitMany", purchase_price=Decimal("10"), quantity=10)
    _tool(db, owner, "DearUnit", purchase_price=Decimal("90"), quantity=1)
    response = client.get(
        "/api/inventory/search/all?min_price=95", headers=auth_headers(owner)
    )
    # Extended totals: 100 vs 90 — only the bulk-cheap tool passes.
    assert [r["name"] for r in response.json()] == ["CheapUnitMany"]


def test_search_bad_sort_is_a_loud_422(client, db, owner):
    response = client.get(
        "/api/inventory/search?sort=bogus", headers=auth_headers(owner)
    )
    assert response.status_code == 422


def test_paging_reaches_every_item(client, db, owner):
    for i in range(250):
        _tool(db, owner, f"Tool {i:03d}", purchase_price=Decimal("1"))
    seen: list[str] = []
    for offset in (0, 100, 200):
        response = client.get(
            f"/api/inventory/search?sort=name&limit=100&offset={offset}",
            headers=auth_headers(owner),
        )
        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "250"
        seen += [t["id"] for t in response.json()]
    assert len(seen) == 250
    assert len(set(seen)) == 250  # no duplicates across pages


# -- D3: paginated plain lists ----------------------------------------------


def test_list_tools_pages_with_default_200(client, db, owner):
    for i in range(5):
        _tool(db, owner, f"T{i}")
    page = client.get("/api/inventory?limit=2", headers=auth_headers(owner))
    assert page.status_code == 200
    assert len(page.json()) == 2
    assert page.headers["X-Total-Count"] == "5"
    rest = client.get(
        "/api/inventory?limit=2&offset=4", headers=auth_headers(owner)
    )
    assert len(rest.json()) == 1
    everything = client.get("/api/inventory", headers=auth_headers(owner))
    assert len(everything.json()) == 5  # default page covers small vaults


def test_list_batteries_honors_limit(client, db, owner):
    for i in range(3):
        _battery(db, owner, f"B{i}")
    page = client.get(
        "/api/inventory/batteries?limit=2", headers=auth_headers(owner)
    )
    assert len(page.json()) == 2
    assert page.headers["X-Total-Count"] == "3"
    bad = client.get(
        "/api/inventory/batteries?limit=0", headers=auth_headers(owner)
    )
    assert bad.status_code == 422  # rejected loudly, never ignored


# -- D4: sharing preview paging ---------------------------------------------


def _share_all(db, owner, tools):
    db.add(
        core_models.ShareConfig(
            id=uuid.uuid4(), owner_id=owner.id,
            recipient_group="shop_company", enabled=True,
            fields=["name", "brand", "category"],
        )
    )
    for tool in tools:
        db.add(
            core_models.SharedItem(
                id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
                tool_id=tool.id, recipient_group="shop_company",
            )
        )
    db.commit()


def test_preview_pages_response_and_reports_total(client, db, owner):
    tools = [_tool(db, owner, f"Shared {i}") for i in range(5)]
    _share_all(db, owner, tools)

    page, total = sharing.build_preview_page(
        db, owner.id, "shop_company", limit=2, offset=0
    )
    assert total == 5
    assert len(page) == 2
    page2, _ = sharing.build_preview_page(
        db, owner.id, "shop_company", limit=2, offset=4
    )
    assert len(page2) == 1
    # The unpaged payload is exactly the concatenation of the pages.
    whole = sharing.build_preview(db, owner.id, "shop_company")
    assert len(whole) == 5
    paged = []
    for offset in (0, 2, 4):
        chunk, _ = sharing.build_preview_page(
            db, owner.id, "shop_company", limit=2, offset=offset
        )
        paged += chunk
    assert paged == whole

    response = client.get(
        "/api/core/sharing/preview?group=shop_company&limit=2",
        headers=auth_headers(owner),
    )
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.headers["X-Total-Count"] == "5"


# -- D5: reports under the batched build -------------------------------------


def test_report_values_survive_batching(client, db, owner):
    from app.modules.borrowing import models as borrowing_models
    from app.modules.dealers import models as dealer_models
    from app.modules.reports import schemas as report_schemas
    from app.modules.reports import service as report_service

    dealer = dealer_models.DealerCompany(
        id=uuid.uuid4(), name="Acme Tool Supply", kind="platform",
    )
    db.add(dealer)
    drill = _tool(
        db, owner, "Drill", purchase_price=Decimal("100"), quantity=2,
        dealer_company_id=dealer.id, category="Power",
    )
    tag = inv_models.Tag(id=uuid.uuid4(), owner_id=owner.id, name="garage")
    db.add(tag)
    db.flush()  # PG enforces FKs: the tag lands before its links (row 117).
    db.add(
        inv_models.ItemTag(
            id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
            tool_id=drill.id, tag_id=tag.id,
        )
    )
    db.add(
        borrowing_models.Checkout(
            id=uuid.uuid4(), owner_id=owner.id, item_kind="tool",
            item_id=drill.id, item_name="Drill", borrower_name="Pat",
            state="checked_out",
        )
    )
    kit = _tool(
        db, owner, "Socket Kit", purchase_price=Decimal("50"), quantity=1,
        is_set=True, category="Hand",
    )
    db.add(
        inv_models.SetPiece(
            id=uuid.uuid4(), set_id=kit.id, owner_id=owner.id,
            kind="addon", name="Deep sockets", price=Decimal("25"),
            status="present",
        )
    )
    db.commit()

    spec = report_schemas.ReportSpec(
        columns=["name", "dealer", "tags", "status", "price_total"]
    )
    report = report_service.build_report(db, owner.id, spec)
    rows = {
        row["values"]["name"]: row["values"]
        for group in report["groups"]
        for row in group["rows"]
    }
    assert rows["Drill"]["dealer"] == "Acme Tool Supply"
    assert rows["Drill"]["tags"] == "garage"
    assert rows["Drill"]["status"] == "Checked out"
    # The set row carries the bundle total (50 + 25), not its own 50.
    assert Decimal(rows["Socket Kit"]["price_total"]) == Decimal("75")
    assert Decimal(report["summary"]["price_total"]) == Decimal("275")


def test_report_full_set_totals_at_scale(db, owner):
    from app.modules.reports import schemas as report_schemas
    from app.modules.reports import service as report_service

    for i in range(600):
        _tool(
            db, owner, f"Bulk {i:03d}",
            purchase_price=Decimal("2"), quantity=1,
        )
    spec = report_schemas.ReportSpec()
    report = report_service.build_report(db, owner.id, spec)
    assert report["summary"]["items"] == 600
    assert Decimal(report["summary"]["price_total"]) == Decimal("1200")


# -- D6: moderation on deleted authors ---------------------------------------


def test_moderator_remove_post_of_deleted_author(client, db):
    from tests.test_forum import _category, _reply, _thread

    poster = _make_user(
        db, "TV-M-001201", "d6-poster@example.com", name="Pat Poster"
    )
    author = _make_user(
        db, "TV-S-001202", "d6-author@example.com",
        account_types=("shop_company",), name="Dee Deleted",
    )
    moderator = _make_user(
        db, "TV-M-001203", "d6-mod@example.com", name="Mo Mod",
        role="moderator",
    )
    operator = _make_user(
        db, "TV-M-001204", "d6-op@example.com", name="Olive Op",
        is_operator=True,
    )
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    reply = _reply(client, author, thread["id"], body="Spammy reply.")
    assert reply.status_code == 201, reply.text
    post_id = reply.json()["id"]

    # The author deletes their account (the campaign's exact case):
    # the post survives as a "Former member" tombstone.
    core_service.delete_account(db, author)
    assert db.get(core_models.User, author.id) is None

    removed = client.post(
        f"/api/forum/mod/posts/{post_id}/remove",
        json={"resolution": "Spam"},
        headers=auth_headers(moderator),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "removed"

    audit_rows = db.scalars(
        select(core_models.AuditLog).where(
            core_models.AuditLog.action == "forum.post_remove"
        )
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].actor_user_id == moderator.id


# -- scheduler ---------------------------------------------------------------


def test_scheduler_registry_covers_all_five_jobs():
    from app.scripts import scheduler

    by_name = {spec.name: spec for spec in scheduler.JOBS}
    # Wave 2 (2026-10-20) added the truck-accounts reminders job
    # ("truck", hourly). Wave 3 added the crew 30-day-rule job
    # ("crew", hourly) and the daily FX refresh ("fx"). Wave 4
    # added the cloud-backup runner ("cloud-backups", hourly).
    # Audit A2 (2026-10-22) added the dealer route-day reminders
    # ("dealers", hourly) — the registry now carries ten jobs.
    # The flyer module (2026-11-06) added the standing flyer URL
    # pulls ("flyers", daily) — eleven. The admin lane
    # (2026-11-07) added the daily Site Stats snapshot
    # ("admin-stats", daily) — twelve. The agent invite
    # reminder (2026-11-07) added the 30-day unclaimed-record
    # nudge ("agent-invite-reminders", daily) — thirteen.
    # The release-machinery lane (2026-11-08) added the feature
    # announcement fan-out ("announcements", every minute) — fourteen.
    # The warranty sheet row (2026-11-15) added the warranty
    # expiry warnings ("warranty", hourly) — fifteen.
    assert set(by_name) == {
        "entitlements", "maintenance", "claims", "marketplace", "audit",
        "truck", "crew", "fx", "cloud-backups", "dealers", "flyers",
        "admin-stats", "agent-invite-reminders", "announcements",
        "warranty",
    }
    assert by_name["entitlements"].interval_minutes == 60
    assert by_name["maintenance"].interval_minutes == 60
    assert by_name["warranty"].interval_minutes == 60
    assert by_name["claims"].interval_minutes == 240
    assert by_name["marketplace"].interval_minutes == 1440
    assert by_name["audit"].interval_minutes == 1440
    assert by_name["truck"].interval_minutes == 60
    assert by_name["crew"].interval_minutes == 60
    assert by_name["fx"].interval_minutes == 1440
    assert by_name["cloud-backups"].interval_minutes == 60
    assert by_name["dealers"].interval_minutes == 60
    assert by_name["flyers"].interval_minutes == 1440
    assert by_name["agent-invite-reminders"].interval_minutes == 1440
    assert by_name["announcements"].interval_minutes == 1
    for spec in scheduler.JOBS:
        assert spec.interval_minutes > 0


def test_scheduler_run_due_ledgers_ok_and_failed(db):
    from app.scripts import scheduler

    ran = scheduler.run_due(db)
    assert set(ran) == {spec.name for spec in scheduler.JOBS}
    rows = db.scalars(select(core_models.JobRun)).all()
    assert len(rows) == len(scheduler.JOBS)
    assert all(row.status == "ok" for row in rows)
    assert all(row.detail.get("summary") for row in rows)

    # Nothing is due again inside its cadence.
    assert scheduler.run_due(db) == []

    # A failing job is ledgered as failed, never raised.
    bogus = scheduler.JobSpec("bogus", "app.scripts.no_such_module", 60)
    row = scheduler.run_job(db, bogus)
    assert row.status == "failed"
    assert "error" in row.detail


def test_scheduler_due_after_interval(db):
    from app.scripts import scheduler

    spec = scheduler.JOBS[0]
    scheduler.run_job(db, spec)
    now = datetime.now(timezone.utc)
    assert not scheduler.is_due(db, spec, now)
    later = now + timedelta(minutes=spec.interval_minutes + 1)
    assert scheduler.is_due(db, spec, later)


def test_admin_settings_expose_job_statuses(client, db):
    from app.scripts import scheduler

    operator = _make_user(
        db, "TV-M-001301", "jobs-op@example.com", is_operator=True
    )
    scheduler.run_due(db)
    response = client.get(
        "/api/admin/settings", headers=auth_headers(operator)
    )
    assert response.status_code == 200, response.text
    jobs = {row["job"]: row for row in response.json()["jobs"]}
    assert set(jobs) == {spec.name for spec in scheduler.JOBS}
    assert jobs["audit"]["last_status"] == "ok"
    assert jobs["audit"]["interval_minutes"] == 1440


def test_compose_ships_jobs_service():
    compose = (
        Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
    ).read_text()
    assert "jobs:" in compose
    assert "app.scripts.scheduler" in compose


def test_scheduler_close_stale_runs(db):
    """Sheet row 72: a job_runs row stuck at "running" past the
    stale horizon is closed automatically as failed; a fresh
    in-flight row and finished rows are untouched."""
    from app.scripts import scheduler

    now = datetime.now(timezone.utc)
    stuck = core_models.JobRun(
        id=uuid.uuid4(),
        job="announcements",
        status="running",
        started_at=now - timedelta(hours=2),
        detail={},
    )
    fresh = core_models.JobRun(
        id=uuid.uuid4(),
        job="audit",
        status="running",
        started_at=now - timedelta(minutes=5),
        detail={},
    )
    done = core_models.JobRun(
        id=uuid.uuid4(),
        job="fx",
        status="ok",
        started_at=now - timedelta(hours=3),
        finished_at=now - timedelta(hours=3),
        detail={"summary": "fine"},
    )
    db.add_all([stuck, fresh, done])
    db.commit()

    closed = scheduler.close_stale_runs(db, now)
    assert closed == 1
    db.refresh(stuck)
    db.refresh(fresh)
    db.refresh(done)
    assert stuck.status == "failed"
    assert stuck.finished_at is not None
    assert "Interrupted" in stuck.detail["error"]
    assert fresh.status == "running"
    assert done.status == "ok"

    # The wake itself sweeps first: a stale row left by a dead
    # process is closed by the next run_due, not just by hand.
    stuck2 = core_models.JobRun(
        id=uuid.uuid4(),
        job="crew",
        status="running",
        started_at=now - timedelta(days=6),
        detail={},
    )
    db.add(stuck2)
    db.commit()
    scheduler.run_due(db, now)
    db.refresh(stuck2)
    assert stuck2.status == "failed"


def test_repair_text_only_locations(db, owner):
    """Sheet row 70: an item carrying location text but no
    location record gets the record created and linked, so the
    header's location count (which counts records) can never
    silently undercount."""
    from app.modules.inventory import service

    loose = _tool(db, owner, "Loose wrench", location="Top drawer")
    assert loose.location_id is None
    battery = _battery(db, owner, "Loose battery", location="Top drawer")
    assert battery.location_id is None

    repaired = service.repair_text_only_locations(db, owner.id)
    assert repaired == 2
    db.refresh(loose)
    db.refresh(battery)
    assert loose.location_id is not None
    # Both items share ONE record for the same text.
    assert battery.location_id == loose.location_id
    node = db.get(inv_models.InventoryLocation, loose.location_id)
    assert node is not None and node.name == "Top drawer"
    assert loose.location == "Top drawer"

    # Idempotent: nothing left to repair.
    assert service.repair_text_only_locations(db, owner.id) == 0

    # A text that IS an existing node's path links to that node
    # instead of minting a top-level node with the path as name.
    shop = service.create_location_node(db, owner.id, name="Shop")
    drawer = service.create_location_node(
        db, owner.id, name="Drawer 2", parent_id=shop.id
    )
    nested = _tool(db, owner, "Nested wrench", location="Shop / Drawer 2")
    assert service.repair_text_only_locations(db, owner.id) == 1
    db.refresh(nested)
    assert nested.location_id == drawer.id
