"""Shared fixtures: an in-memory SQLite session running the REAL models.

Postgres-only types are shimmed just enough for SQLite DDL (TSVECTOR ->
TEXT; it stays NULL and no test searches on it). JSONB/UUID round-trip
natively. The one Postgres-only code path — the JSONB scrub UPDATE in
delete_definition — is covered at the statement level in
test_custom_fields_scoping.py, not through this fixture.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(TSVECTOR, "sqlite")
def _tsvector_for_sqlite(type_, compiler, **_kw):  # noqa: ANN001, ANN202
    return "TEXT"


from app.core.db import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.billing import models as billing_models  # noqa: E402
from app.modules.borrowing import models as borrowing_models  # noqa: E402
from app.modules.claims import models as claims_models  # noqa: E402
from app.modules.core import models as core_models  # noqa: E402
from app.modules.dealers import models as dealers_models  # noqa: E402
from app.modules.downloads import models as downloads_models  # noqa: E402
from app.modules.inventory import models as inventory_models  # noqa: E402
from app.modules.maintenance import models as maintenance_models  # noqa: E402
from app.modules.feedback import models as feedback_models  # noqa: E402
from app.modules.flyers import models as flyers_models  # noqa: E402
from app.modules.forum import models as forum_models  # noqa: E402
from app.modules.marketplace import models as marketplace_models  # noqa: E402
from app.modules.messaging import models as messaging_models  # noqa: E402
from app.modules.parts import models as parts_models  # noqa: E402
from app.modules.prints import models as prints_models  # noqa: E402
from app.modules.reports import models as reports_models  # noqa: E402
from app.modules.support import models as support_models  # noqa: E402
from app.modules.tool_expansion import models as tool_expansion_models  # noqa: E402
from app.modules.truck_accounts import models as truck_models  # noqa: E402
from app.modules.wishlist import models as wishlist_models  # noqa: E402

_TABLES = [
    core_models.User.__table__,
    core_models.RefreshToken.__table__,
    core_models.EmailVerificationToken.__table__,
    # Email flows (2026-10-18): the provider seam records every
    # send in the outbox, and the reset/change flows run on their
    # token tables — all three exist suite-wide so any test that
    # triggers an email (signup included) writes real rows.
    core_models.EmailOutbox.__table__,
    core_models.PasswordResetToken.__table__,
    core_models.EmailChangeToken.__table__,
    # Module control (doctrine 2026-10-18): the require_module gate
    # reads these on every module request, so they exist suite-wide.
    # They start EMPTY in tests — the service falls back to the
    # manifests' default_groups, which is exactly today's matrix.
    core_models.ModuleState.__table__,
    core_models.ModuleAccess.__table__,
    # Account tiers (2026-10-31): the switchboard's per-tier cells.
    # Starts EMPTY in tests — the service falls back to each
    # module's global state, the migration's seed semantics.
    core_models.ModuleTierAccess.__table__,
    # Per-user module switches (2026-10-24): the require_module
    # gate and the my-modules read consult these whenever a user
    # id is in play, so the table exists suite-wide (starts empty
    # — absence of a row means the module is on for that user).
    core_models.UserModulePref.__table__,
    # Account settings surfaces (Phase A1): sharing/peer/inbox/layout
    # tables exist suite-wide so the data export and the account
    # deletion cascade run against the real schema in any test.
    core_models.ShareConfig.__table__,
    core_models.SharedItem.__table__,
    # Admin panel (Phase A2): bans are consulted on auth paths and
    # every admin endpoint writes audit rows, so both exist
    # suite-wide.
    core_models.BannedEmail.__table__,
    core_models.AuditLog.__table__,
    # Disaster Vault (2026-10-18): Admin -> Settings shows the last
    # backup runs, so the table exists suite-wide (starts empty).
    core_models.BackupRun.__table__,
    # Background jobs ledger (step-4 fix round): Admin → Settings
    # reads the latest job runs, so the table exists suite-wide.
    core_models.JobRun.__table__,
    # Teaser visitor counter (2026-10-26): the anonymous count
    # endpoint bumps this one-row table; it exists suite-wide so
    # the counter's tests run against the real schema. Starts
    # EMPTY (no seed row) — the service's inline-create path is
    # part of what its tests prove.
    core_models.VisitorCounter.__table__,
    # Downloads lead magnet (2026-10-29): the public subscribe /
    # unsubscribe / sheet endpoints write this table; it exists
    # suite-wide so the downloads tests run against the real schema.
    downloads_models.DownloadsSubscriber.__table__,
    # Downloads documents catalog (2026-11-08): the Documents
    # shelf's rows + counters; the catalog endpoints upsert from
    # catalog.py, so the table starts EMPTY here on purpose.
    downloads_models.DownloadFile.__table__,
    # Download events (0098, dashboard-flare lane 2026-11-09):
    # the dated record behind the weekly top-downloads ranking;
    # record_download writes it with every counted download.
    downloads_models.DownloadEvent.__table__,
    # 3D Print Files (2026-11-08): the community shelf's tables —
    # files, versions, ratings, comments, reports, maker links.
    # Showcase media (0095, 2026-11-08): a listing's photos + its
    # one video — detail() reads the set on every file page.
    prints_models.PrintFile.__table__,
    prints_models.PrintFileVersion.__table__,
    prints_models.PrintMedia.__table__,
    prints_models.PrintRating.__table__,
    prints_models.PrintComment.__table__,
    prints_models.PrintReport.__table__,
    prints_models.PrintMakerLink.__table__,
    # Content alerts (sweep E4, 2026-11-12): the per-file
    # update opt-in + the core new-content prefs / watermark —
    # the prints publish path and the downloads catalog sync
    # read them suite-wide.
    prints_models.PrintFileFollow.__table__,
    core_models.NewContentAlertPref.__table__,
    core_models.ContentAlertState.__table__,
    core_models.PeerShare.__table__,
    core_models.PeerShareExclusion.__table__,
    core_models.Notification.__table__,
    core_models.UserPageLayout.__table__,
    # Tier conversion (2026-11-10): the one-request table rides
    # every test database like its sibling core tables.
    core_models.ConversionRequest.__table__,
    # User audit trail (2026-10-19): the journal listener writes on
    # EVERY mutation suite-wide, markers land at signup, and file
    # tombstones ride the delete paths — all three tables exist in
    # every test database.
    core_models.ChangeJournal.__table__,
    core_models.RestoreMarker.__table__,
    core_models.RetainedFile.__table__,
    inventory_models.FieldDefinition.__table__,
    # Dealers (item structure package, 2026-10-18): tools/batteries
    # carry a dealer_company_id FK, so the dealers tables precede
    # them here; the module's own routes, the item tag serialization
    # and the deletion cascade all read them suite-wide.
    dealers_models.DealerCompany.__table__,
    dealers_models.PrivateAgent.__table__,
    dealers_models.PreferredAgent.__table__,
    # Agent takeover (2026-11-03): code-entry requests ride the
    # dealers routes and the deletion cascade.
    dealers_models.AgentTakeoverRequest.__table__,
    # Dealer portal (2026-10-19): profiles + representations ride
    # the dealers routes and the deletion cascade suite-wide.
    dealers_models.AgentProfile.__table__,
    dealers_models.CompanyRepresentation.__table__,
    # Dealer build (2026-10-20): the geocode cache + warranty
    # service requests ride Find-an-Agent, the repair flow and the
    # deletion cascade suite-wide.
    dealers_models.GeocodeCache.__table__,
    dealers_models.WarrantyServiceRequest.__table__,
    # Dealer list customization (2026-10-31): the per-user pick-list
    # overlay rides the dealers routes suite-wide.
    dealers_models.DealerListHidden.__table__,
    dealers_models.DealerListEntry.__table__,
    dealers_models.DealerCompanyPersonalEdit.__table__,
    # Flyers (2026-11-06): sources hang off dealer companies and
    # agent records, flyers off sources — the module's routes and
    # the deletion cascade read them suite-wide.
    flyers_models.FlyerSource.__table__,
    flyers_models.Flyer.__table__,
    flyers_models.FlyerAlertPref.__table__,
    # Inventory location tree (Package B, 2026-10-19): tools and
    # batteries carry a location_id FK into it, so it precedes them.
    inventory_models.InventoryLocation.__table__,
    inventory_models.Tool.__table__,
    # Batteries (2026-10-18): first-class assets — inventory routes,
    # billing's active set, both sharing systems and the account
    # deletion cascade all read the table, so it exists suite-wide.
    inventory_models.Battery.__table__,
    # Item structure package (2026-10-18): set pieces + tags — read by
    # inventory serialization, search, stats and the deletion
    # cascade, so they exist suite-wide too.
    inventory_models.SetPiece.__table__,
    inventory_models.Tag.__table__,
    inventory_models.ItemTag.__table__,
    # General importer (2026-10-19): upload sessions hold the raw
    # spreadsheet bytes server-side; importer routes + the account
    # deletion cascade read the table.
    inventory_models.ImportSession.__table__,
    # Importer smart matching (2026-10-19): learned resolve
    # answers — read by the resolve step, Settings, the export and
    # the deletion cascade.
    inventory_models.ImportValueMapping.__table__,
    # Gap wave 1 (2026-10-20): the category registry (manager
    # surface) + lost/stolen report records — read by the inventory
    # routes, the reports builder and the deletion cascade.
    inventory_models.InventoryCategory.__table__,
    inventory_models.ItemLossReport.__table__,
    # Core's per-set peer-sharing choice (item structure package).
    core_models.PeerSetChoice.__table__,
    # Package C (2026-10-19): sharing rules + exclusions (tier and
    # peer) and the My Insurance profile — read by the sharing
    # services, the claims pre-fill, the export and the deletion
    # cascade suite-wide.
    core_models.ShareRule.__table__,
    core_models.ShareExclusion.__table__,
    core_models.PeerShareExclusionRule.__table__,
    core_models.InsuranceProfile.__table__,
    # Billing (Phase A1): plans/subscriptions/grants/settings/codes/
    # wallet. Inventory routes consult entitlements on every request,
    # so these exist suite-wide too. They start EMPTY — no plans
    # seeded in tests; the engine's fallbacks reproduce free-plan
    # behavior, and enforcement defaults off.
    billing_models.Plan.__table__,
    billing_models.BusinessBracket.__table__,
    billing_models.Subscription.__table__,
    billing_models.EntitlementGrant.__table__,
    billing_models.SystemSetting.__table__,
    billing_models.RedeemCode.__table__,
    billing_models.Redemption.__table__,
    billing_models.AiWallet.__table__,
    billing_models.AiLedger.__table__,
    # Admin polish (2026-11-07): the per-action AI usage
    # metering rows behind the admin AI Usage report.
    billing_models.AiUsage.__table__,
    # Cancellation counts (2026-11-07): the subscription
    # status-change history behind the Accounting report's
    # cancellations-in-period figure.
    billing_models.SubscriptionStatusChange.__table__,
    # Stripe wiring (2026-10-19): the webhook idempotency ledger.
    billing_models.StripeEvent.__table__,
    # Borrowing (2026-10-18): the check-out ledger — borrowing routes
    # gate on the module control tables above and read inventory +
    # peer grants, all present; the ledger itself exists suite-wide
    # because the account deletion cascade and the data export both
    # enumerate it.
    borrowing_models.Checkout.__table__,
    # Borrower address book (gap wave 1, 2026-10-20): the owner's
    # reusable borrower contacts — read by the borrowing routes
    # and the deletion cascade.
    borrowing_models.BorrowerContact.__table__,
    # Reports (2026-10-19): saved configurations — owner-scoped
    # rows the account deletion cascade enumerates.
    reports_models.ReportConfig.__table__,
    # Reports page redesign (2026-11-06): saved templates, the
    # generated-file History, and the seed-once marker — all
    # owner-scoped, all enumerated by the deletion cascade.
    reports_models.ReportTemplate.__table__,
    reports_models.GeneratedReport.__table__,
    reports_models.ReportTemplateSeed.__table__,
    # Maintenance (2026-10-19): schedules + log entries —
    # owner-scoped rows the account deletion cascade and the data
    # export both enumerate. (Repair records retired in the
    # repairs ∪ claims merge, 2026-11-04 — they are claims now.)
    maintenance_models.MaintenanceSchedule.__table__,
    maintenance_models.MaintenanceLogEntry.__table__,
    # Claims (2026-10-19): claims + lines + evidence + comms —
    # owner-scoped rows the account deletion cascade enumerates
    # FIRST (open claims guard their items against deletion) and
    # the data export both enumerate.
    claims_models.Claim.__table__,
    claims_models.ClaimLine.__table__,
    claims_models.ClaimEvidence.__table__,
    claims_models.ClaimCommunication.__table__,
    # Used Parts (2026-10-19): the location tree + part records —
    # read by the parts routes, the data export and the account
    # deletion cascade, so they exist suite-wide. After tools:
    # parts.converted_tool_id references them.
    parts_models.PartLocation.__table__,
    parts_models.Part.__table__,
    # Community pool (2026-10-19): the owner's visibility settings
    # — read by the parts serializers and the pool surface.
    parts_models.PartPoolSettings.__table__,
    # Messaging (2026-10-19): threads/messages/states/blocks/
    # reports — the account deletion cascade enumerates them and
    # the messaging routes read them suite-wide.
    messaging_models.MessageThread.__table__,
    messaging_models.Message.__table__,
    messaging_models.MessageThreadState.__table__,
    messaging_models.UserBlock.__table__,
    messaging_models.MessageReport.__table__,
    # Tools For Sale + reputation (2026-10-19): listings are read
    # by the account deletion cascade and the data export; the
    # interactions/ratings tables ride the messaging profile and
    # the spam trust tiers suite-wide.
    marketplace_models.SaleListing.__table__,
    marketplace_models.DealInteraction.__table__,
    marketplace_models.Rating.__table__,
    # Rating moderation (gap wave 1): reports feed the moderation
    # queue's Ratings section.
    marketplace_models.RatingReport.__table__,
    marketplace_models.ThreadCompletion.__table__,
    # Community Forum (2026-10-20): categories/threads/posts/
    # reports — the journal listener writes on forum mutations
    # suite-wide, and the deletion cascade tombstones them.
    forum_models.ForumCategory.__table__,
    forum_models.ForumThread.__table__,
    forum_models.ForumPost.__table__,
    forum_models.ForumReport.__table__,
    forum_models.ForumFavorite.__table__,
    # Admin lane (2026-11-07): the daily Site Stats snapshot is
    # read by the admin home-widgets payload in any test that
    # touches it, and community blocks gate the forum/feedback
    # write doors suite-wide — both tables exist everywhere.
    core_models.SiteStatsSnapshot.__table__,
    forum_models.CommunityBlock.__table__,
    # Onboarding (2026-11-07): the creation path writes the
    # wizard-flow marker for EVERY suite-created account, and the
    # deletion cascade sweeps the rows — the table exists
    # suite-wide.
    core_models.OnboardingProgress.__table__,
    # Wave 2 (2026-10-20): wishlist, the sale ledger, truck accounts.
    wishlist_models.WishlistItem.__table__,
    inventory_models.SaleRecord.__table__,
    # Acquisition ledger (year-end fix, 2026-10-24): the year-end
    # and tax reports read it, and account deletion sweeps it.
    inventory_models.AcquisitionRecord.__table__,
    truck_models.TruckAccount.__table__,
    truck_models.TruckEntry.__table__,
    # Stage 2 (2026-11-05): the agent payment-request table.
    truck_models.TruckPaymentRequest.__table__,
    # Agent revision (2026-10-31): the transfer history — the
    # account detail reads it on every open.
    truck_models.TruckAccountTransfer.__table__,
    # Wave 3 (2026-10-20): shop crews + insurer directory +
    # affiliations + the FX cache (core tables — read by the crew
    # and insurer routes, the money hint and the deletion cascade
    # suite-wide). Insurer companies precede affiliations +
    # insurance profiles' new FK in spirit (create_all resolves
    # FK order itself; the list order is documentary).
    core_models.InsurerCompany.__table__,
    core_models.ShopMembership.__table__,
    core_models.InsurerAffiliation.__table__,
    core_models.FxRate.__table__,
    # Wave 4: Google Drive connections + the backup-run ledger
    # (plain user columns — no FKs, per the two-party doctrine).
    core_models.CloudDriveConnection.__table__,
    core_models.CloudBackupRun.__table__,
    # Disaster Vault Drive leg (2026-10-24): the platform OAuth
    # connection row — Admin -> Settings reads it suite-wide.
    core_models.PlatformDriveConnection.__table__,
    # Wave 3: the feedback boards (posts -> votes/comments carry
    # real FKs into posts; reports are plain-column rows).
    feedback_models.FeedbackPost.__table__,
    feedback_models.FeedbackVote.__table__,
    feedback_models.FeedbackComment.__table__,
    feedback_models.FeedbackReport.__table__,
    # Audit A15 (2026-10-22): operator-published roadmap entries.
    core_models.RoadmapEntry.__table__,
    # Support tickets (2026-10-24): tickets + their messages —
    # read by the support routes and the account deletion cascade
    # suite-wide (messages carry an FK into tickets, so tickets
    # come first in spirit; create_all resolves FK order itself).
    # Notification channel prefs (owner item 12, 2026-10-24):
    # read by the inbox email hook on every notification suite-
    # wide.
    core_models.NotificationChannelPref.__table__,
    # Release machinery (2026-11-08): the feature-announcement
    # history — the Admin composer writes rows, the fan-out job
    # reads them.
    core_models.FeatureAnnouncement.__table__,
    support_models.SupportTicket.__table__,
    support_models.SupportMessage.__table__,
    # How-to videos (Help & Support build, 2026-11-02): the
    # support module's operator-managed video list.
    support_models.HelpVideo.__table__,
    # Tool Expansion (2026-10-25): the two user-control ledgers —
    # read/written by the module's routes suite-wide through the
    # require_module gate like every other module table.
    tool_expansion_models.ExpansionDismissal.__table__,
    tool_expansion_models.ExpansionReport.__table__,
    # Scale fix follow-up (2026-10-26): the pool snapshot's
    # cross-process epoch counter — read on every expansion call
    # and bumped by the module's flush listener on pool writes.
    tool_expansion_models.PoolEpoch.__table__,
]


@pytest.fixture()
def db():
    # StaticPool + check_same_thread=False: ONE shared in-memory database,
    # visible from the TestClient's worker thread as well as the test's.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


def _make_user(db: Session, account_number: str, email: str) -> core_models.User:
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Test User",
        password_hash="not-a-real-hash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user_a(db) -> core_models.User:
    return _make_user(db, "TV-000001", "a@example.com")


@pytest.fixture()
def user_b(db) -> core_models.User:
    return _make_user(db, "TV-000002", "b@example.com")


@pytest.fixture()
def client(db):
    """HTTP client for the real app, with get_db pointed at the SQLite
    session — full request cycle (routing, auth deps, serialization)
    without Docker/Postgres."""
    from fastapi.testclient import TestClient

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def auth_headers(user: core_models.User) -> dict[str, str]:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
