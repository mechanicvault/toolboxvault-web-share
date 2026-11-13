"""Admin panel schemas (Phase A2): the Users directory + detail,
operator actions, bans, system settings, and the audit read.

These describe the /api/admin/* surface only — operator-facing
shapes, never user-facing ones (schemas.py keeps those).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Role = Literal["user", "moderator", "community_admin"]
# The grantable account rungs (core/tiers.py): "god" is
# deliberately absent — no API path grants or removes the god rung.
Tier = Literal["downloads", "normal", "moderator", "moderator_admin"]
PlanKey = Literal["free", "pro", "business"]


# -- users --------------------------------------------------------------------


class AdminUserSummary(BaseModel):
    """One directory row: who the account is and what it currently
    resolves to (plan via the entitlement resolver)."""

    id: uuid.UUID
    account_number: str
    name: str
    email: str
    account_types: list[str]
    plan_key: str
    plan_name: str
    is_operator: bool
    role: str
    # Account tier (2026-10-31): the primary rung + the beta flag.
    # `tier` is the RESOLVED rung (core/tiers.resolved_tier), so
    # the panel shows the truth even for a pre-0067 row.
    tier: str = "normal"
    beta_tester: bool = False
    is_active: bool
    created_at: datetime


class AdminUserPage(BaseModel):
    items: list[AdminUserSummary]
    total: int
    limit: int
    offset: int


class AdminEntitlementView(BaseModel):
    plan_key: str
    plan_name: str
    source: str
    is_paid: bool
    # The subscription facts behind the answer, when a row exists:
    # period end is what "when does this run out" reads.
    status: str | None = None
    current_period_end: datetime | None = None
    trial_end: datetime | None = None
    grace_until: datetime | None = None


class AdminWalletView(BaseModel):
    allowance_balance: int
    banked_balance: int


class AdminUserDetail(AdminUserSummary):
    email_verified: bool
    referred_by_id: uuid.UUID | None = None
    entitlement: AdminEntitlementView
    wallet: AdminWalletView
    session_count: int
    referral_count: int


class OperatorRequest(BaseModel):
    is_operator: bool


class RoleRequest(BaseModel):
    role: Role


class TierRequest(BaseModel):
    """Set the account's rung. The Literal is the grantable set —
    'god' can never be requested (422), by design."""

    tier: Tier


class BetaRequest(BaseModel):
    """Grant or revoke the Beta Tester upgrade flag."""

    beta_tester: bool


class TrialRequest(BaseModel):
    """Start-a-trial body. Durations are MONTHS (owner directive
    2026-10-22: admins pick months, never a typed day count);
    `months` is the field the panel sends. `days` stays accepted
    for API backward compatibility — supply one or the other."""

    plan_key: PlanKey = "pro"
    months: int | None = Field(default=None, ge=1, le=120)
    days: int | None = Field(default=None, ge=1, le=3660)

    @model_validator(mode="after")
    def _needs_a_duration(self):
        if not self.months and not self.days:
            raise ValueError("A trial needs a duration (months, or legacy days).")
        return self


class FreePeriodRequest(BaseModel):
    """Grant-a-free-period body: months like the trial, or
    `lifetime: true` for the open-ended grant (the same shape the
    lifetime redeem code writes). `days` stays accepted for API
    backward compatibility."""

    plan_key: PlanKey = "pro"
    months: int | None = Field(default=None, ge=1, le=120)
    days: int | None = Field(default=None, ge=1, le=3660)
    lifetime: bool = False

    @model_validator(mode="after")
    def _needs_a_duration(self):
        if not self.lifetime and not self.months and not self.days:
            raise ValueError(
                "A free period needs a duration (months, or legacy days) "
                "or lifetime: true."
            )
        return self


class AiCreditsRequest(BaseModel):
    amount: int = Field(ge=1, le=1_000_000)


# -- bans -----------------------------------------------------------------------


class BanCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    reason: str = Field(default="", max_length=500)


class BanView(BaseModel):
    id: uuid.UUID
    email: str
    reason: str
    banned_by: uuid.UUID | None = None
    banned_by_email: str | None = None
    created_at: datetime


# -- settings -------------------------------------------------------------------


class AiConfigView(BaseModel):
    provider: str = ""
    model: str = ""
    api_key_ref: str = ""
    # Per-action credit prices (wave 4): {action: credits}.
    prices: dict[str, int] = {}
    # Per-action model overrides (2026-10-25): {action: model};
    # an absent/blank action rides the site model above.
    action_models: dict[str, str] = {}


class LookupConfigView(BaseModel):
    """Product lookup layers (wave 4): provider name + API key
    REFERENCE name for the UPC database. Empty legs = that
    layer is dark. (The manual/general web search has no
    settings of its own — it rides the AI provider's web
    search through the AI seam, owner's one-vendor decision
    2026-10-25.)"""

    upc_provider: str = ""
    upc_api_key_ref: str = ""


class StripeCreditPackView(BaseModel):
    """One AI credit pack as the operator defines it (Stripe
    wiring, 2026-10-19): our id/label/credits + the Stripe price
    id that charges for it. The price id is operator config, so
    it round-trips through this panel — prices are set here, not
    in code, and never shown to end users."""

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    credits: int = Field(ge=1)
    stripe_price_id: str = Field(default="", max_length=100)


class StripeBracketRow(BaseModel):
    """One Business bracket for the price-id form (the panel needs
    the catalog's keys to render one input per bracket)."""

    bracket_key: str
    up_to_employees: int | None = None


class StripeConfigView(BaseModel):
    """The Stripe price-id block of Admin -> Settings. `configured`
    reports whether the server has STRIPE_SECRET_KEY at all (env,
    read-only here) — the switch that takes the whole surface
    from dark to live once keys AND price ids both exist."""

    configured: bool = False
    price_pro_monthly: str = ""
    price_pro_yearly: str = ""
    price_business_monthly: str = ""
    price_business_yearly: str = ""
    # Bracket fee price ids, keyed by business_brackets.bracket_key.
    price_business_brackets: dict[str, str] = {}
    brackets: list[StripeBracketRow] = []
    ai_credit_packs: list[StripeCreditPackView] = []


class TruckPaymentsConfigView(BaseModel):
    """Truck-account online payments (wave 2, 2026-10-20): the
    Stripe Connect seam's operator block. `configured` reports
    the EFFECTIVE state (platform keys present AND the switch
    on) — the switch alone changes nothing while the seam is
    dark, and the panel says so."""

    connect_enabled: bool = False
    configured: bool = False
    # The platform fee on ONLINE truck payments, percent. 0 at
    # launch by the owner's pending decision (adoption first);
    # the CURRENT value is what new agreement acceptances
    # disclose in their snapshot.
    truck_fee_percent: float = 0


class SpamTierView(BaseModel):
    """One trust tier's budgets in the anti-spam firewall config
    (messaging, 2026-10-19)."""

    new_threads_per_hour: int
    new_threads_per_day: int
    messages_per_hour: int
    messages_per_day: int


class SpamConfigView(BaseModel):
    """The anti-spam firewall's effective config (defaults merged
    with the operator's stored overrides) — the Settings spam
    panel renders exactly this."""

    blast_threshold: int
    blast_window_minutes: int
    blast_similarity: float
    blocked_domains: list[str] = []
    lure_patterns: list[str] = []
    tiers: dict[str, SpamTierView] = {}


class SpamTierUpdate(BaseModel):
    new_threads_per_hour: int | None = Field(default=None, ge=0, le=100000)
    new_threads_per_day: int | None = Field(default=None, ge=0, le=100000)
    messages_per_hour: int | None = Field(default=None, ge=0, le=100000)
    messages_per_day: int | None = Field(default=None, ge=0, le=100000)


class SpamConfigUpdate(BaseModel):
    """Partial spam-config update: only the fields sent change.
    Lists replace wholesale (the panel edits the whole list)."""

    blast_threshold: int | None = Field(default=None, ge=1, le=100)
    blast_window_minutes: int | None = Field(default=None, ge=1, le=10080)
    blast_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    blocked_domains: list[str] | None = None
    lure_patterns: list[str] | None = None
    tiers: dict[str, SpamTierUpdate] | None = None


class BackupRunView(BaseModel):
    """One Disaster Vault run, as the Settings stats block shows
    it (name, size, status + the posture flags)."""

    started_at: datetime
    finished_at: datetime | None = None
    bundle_name: str | None = None
    size_bytes: int | None = None
    encrypted: bool
    uploaded: bool
    verified: bool
    status: str


class JobRunView(BaseModel):
    """One background job's latest state, as the Settings stats
    block shows it (step-4 fix round): the cadence it runs on and
    its newest ledger row — status + the run's summary or error."""

    job: str
    interval_minutes: int
    last_status: str | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    summary: str | None = None
    error: str | None = None


class LandingConfigView(BaseModel):
    """The public landing page's operator config (landing build,
    2026-10-20). Display prices are strings exactly as typed —
    the page renders them verbatim and hides a plan's figure when
    its string is empty. The trial block and the app-store block
    render ONLY while their switches/URLs say so (the honesty
    rules in core/landing.py)."""

    pro_monthly_price: str = "7.99"
    pro_yearly_price: str = "79.99"
    business_monthly_price: str = ""
    business_yearly_price: str = ""
    self_serve_trial_enabled: bool = False
    trial_copy: str = ""
    app_store_url: str = ""
    play_store_url: str = ""


class BackupDriveView(BaseModel):
    """The Disaster Vault's off-site Drive connection (2026-10-24):
    whether the operator has connected Drive AS the backup account,
    which account that is, and the vault folder uploads land in.
    `oauth_configured` reports whether the server has the Google
    OAuth client at all (env, read-only here) — the Connect button
    can only work while it is true."""

    connected: bool = False
    email: str = ""
    folder_id: str = ""
    connected_at: datetime | None = None
    oauth_configured: bool = False


class TeaserConfigView(BaseModel):
    """Teaser mode (owner order, 2026-10-26): the pre-launch front
    door. `enabled` is the switch; `gate_code_custom` reports only
    WHETHER the operator has stored his own gate code — the code
    itself is never echoed into any view (it is write-only here,
    like a password: set a new one to change it)."""

    enabled: bool = False
    gate_code_custom: bool = False
    # The current teaser trailer (owner refinement, 2026-10-26):
    # whether one is set, and its display name. The storage keys
    # and URLs are never part of this view.
    video_set: bool = False
    video_name: str = ""


class TeaserVideoUploadUrlRequest(BaseModel):
    """Ask for a presigned PUT for one teaser asset: the MP4
    itself or its poster frame. Validation (kind, content type,
    size caps) happens in the route, against core/teaser.py's
    caps — the series' own 10 MiB Facebook limit for the video."""

    kind: Literal["video", "poster"]
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0)


class TeaserVideoUploadUrlView(BaseModel):
    upload_url: str
    key: str
    expires_in: int = 900


class TeaserVideoCompleteRequest(BaseModel):
    """Register the uploaded objects as the current teaser video.
    The route HEAD-verifies both objects (existence, real content
    type, size, MP4 magic bytes) before the settings move."""

    key: str = Field(min_length=1, max_length=512)
    poster_key: str = Field(default="", max_length=512)
    name: str = Field(default="", max_length=255)


class SettingsView(BaseModel):
    # The launch switch (owner decision 2026-10-18: limits are
    # built now and enforced from launch — this stays OFF until
    # the owner flips it at launch).
    enforcement_enabled: bool
    # Teaser mode (2026-10-26): the temporary pre-launch front
    # door + its signup gate. Ships ON in production; the owner
    # turns it OFF on launch day. Defaulted so older clients of
    # this view don't break.
    teaser: TeaserConfigView = TeaserConfigView()
    # The OTHER launch switch, same posture: when ON, unverified
    # password-signup accounts can't sign in (OAuth accounts are
    # provider-verified and exempt). OFF until launch.
    require_email_verification: bool
    # User audit trail (2026-10-19): how long deleted files are
    # retained for restore before the purge seam destroys them.
    audit_retention_days: int = 180
    ai: AiConfigView
    # Product lookup layers (wave 4): the UPC database + manual
    # web search configuration.
    lookup: LookupConfigView = LookupConfigView()
    # Stripe price-id config (billing owns the keys; the values
    # live in the same system-settings store).
    stripe: StripeConfigView = StripeConfigView()
    # Public landing page config (core owns the keys; every value
    # is a display string / switch the anonymous page may show).
    landing: LandingConfigView = LandingConfigView()
    # Community (2026-10-19): the anti-spam firewall's effective
    # config and the Community Parts pool's operator switch.
    spam: SpamConfigView = SpamConfigView(
        blast_threshold=3,
        blast_window_minutes=60,
        blast_similarity=0.85,
    )
    parts_pool_enabled: bool = True
    # Tools For Sale (2026-10-19): the marketplace kill switch,
    # same panel + posture as the pool's.
    marketplace_enabled: bool = True
    # Community Forum (2026-10-20): the forum kill switch, same
    # panel + posture.
    forum_enabled: bool = True
    # Claim-readiness nudges (audit A8): the operator kill
    # switch + the per-user period, raw stored values.
    claim_readiness_nudges_enabled: bool = True
    claim_readiness_interval_days: int = 7
    # Truck payments (wave 2): the Connect seam's switch + fee.
    truck_payments: TruckPaymentsConfigView = TruckPaymentsConfigView()
    stats: dict
    # Disaster Vault: the newest backup runs (empty until the
    # backup service's first night — and on a database that predates
    # migration 0013).
    backups: list[BackupRunView] = []
    # Disaster Vault off-site leg (2026-10-24): the platform Drive
    # connection posture. Defaulted so older clients don't break.
    backup_drive: BackupDriveView = BackupDriveView()
    # Background jobs (step-4 fix round): the scheduler registry
    # with each job's latest ledger row (empty last_* until the
    # jobs service's first run).
    jobs: list[JobRunView] = []
    # NEW-badge registry (release machinery, 2026-11-08): nav
    # item key -> release date ("YYYY-MM-DD"). An item badges
    # NEW for its first week from that date; the client computes
    # freshness at render, so a stale entry is inert. Defaulted
    # so older clients of this view don't break.
    nav_new_badges: dict[str, str] = {}


class SettingsUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    enforcement_enabled: bool | None = None
    require_email_verification: bool | None = None
    # Teaser mode (2026-10-26): the switch, and the signup gate
    # code — write-only (sending a value replaces the stored code;
    # an empty string clears it back to the owner's default). The
    # update handler refuses a non-empty code under 4 chars: the
    # owner's code is 4 digits, and the floor keeps an accidental
    # near-blank code out.
    teaser_enabled: bool | None = None
    teaser_gate_code: str | None = Field(default=None, max_length=64)
    # Retention window for restore (days): a week at the shortest
    # (a restore point must outlive a long weekend of regret), ten
    # years at the longest.
    audit_retention_days: int | None = Field(default=None, ge=7, le=3650)
    ai_provider: str | None = Field(default=None, max_length=100)
    ai_model: str | None = Field(default=None, max_length=100)
    ai_api_key_ref: str | None = Field(default=None, max_length=200)
    # AI per-action credit prices (wave 4; whole credits, 0 =
    # free). One field per action in billing.ai_service.PRICE_KEYS.
    ai_price_lookup: int | None = Field(default=None, ge=0, le=100000)
    ai_price_identify: int | None = Field(default=None, ge=0, le=100000)
    ai_price_manual_lookup: int | None = Field(default=None, ge=0, le=100000)
    ai_price_report_summary: int | None = Field(default=None, ge=0, le=100000)
    ai_price_drawer_lookup: int | None = Field(default=None, ge=0, le=100000)
    # AI per-action model override (2026-10-25): blank clears it
    # back to riding the site model.
    ai_model_drawer_lookup: str | None = Field(default=None, max_length=100)
    # Product lookup layers (wave 4): provider + key REFERENCE
    # name for the UPC database. (No manual-search fields —
    # web search rides the AI seam; see LookupConfigView.)
    lookup_upc_provider: str | None = Field(default=None, max_length=100)
    lookup_upc_api_key_ref: str | None = Field(default=None, max_length=200)
    # Stripe price ids (empty string clears one back to "not set
    # yet" — that plan/pack simply stops being purchasable).
    stripe_price_pro_monthly: str | None = Field(default=None, max_length=100)
    stripe_price_pro_yearly: str | None = Field(default=None, max_length=100)
    stripe_price_business_monthly: str | None = Field(
        default=None, max_length=100
    )
    stripe_price_business_yearly: str | None = Field(default=None, max_length=100)
    stripe_price_business_brackets: dict[str, str] | None = None
    stripe_ai_credit_packs: list[StripeCreditPackView] | None = None
    # Public landing page (2026-10-20): display prices (empty
    # string hides that figure on the page), the self-serve trial
    # switch + its copy, and the app-store URLs (empty = the whole
    # store block stays hidden — never advertise what isn't real).
    landing_pro_monthly_price: str | None = Field(default=None, max_length=32)
    landing_pro_yearly_price: str | None = Field(default=None, max_length=32)
    landing_business_monthly_price: str | None = Field(
        default=None, max_length=32
    )
    landing_business_yearly_price: str | None = Field(default=None, max_length=32)
    landing_self_serve_trial_enabled: bool | None = None
    landing_trial_copy: str | None = Field(default=None, max_length=2000)
    landing_app_store_url: str | None = Field(default=None, max_length=500)
    landing_play_store_url: str | None = Field(default=None, max_length=500)
    # Community (2026-10-19): the spam panel's partial update and
    # the pool switch.
    spam: SpamConfigUpdate | None = None
    community_parts_pool_enabled: bool | None = None
    community_marketplace_enabled: bool | None = None
    community_forum_enabled: bool | None = None
    claim_readiness_nudges_enabled: bool | None = None
    claim_readiness_interval_days: int | None = Field(default=None, ge=1, le=90)
    # Truck payments (wave 2): the Connect switch + the platform
    # fee percent on online payments (0–100).
    payments_connect_enabled: bool | None = None
    payments_truck_fee_percent: float | None = Field(
        default=None, ge=0, le=100
    )
    # NEW-badge registry (release machinery, 2026-11-08): the
    # whole map replaces the stored one; the handler validates
    # every value is a real YYYY-MM-DD date before storing.
    nav_new_badges: dict[str, str] | None = None


# -- audit ----------------------------------------------------------------------


class AuditEntryView(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_email: str
    action: str
    target: str
    detail: dict
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntryView]
    total: int
    limit: int
    offset: int


# -- user history & restore (audit trail, 2026-10-19) --------------------------

from app.modules.core.schemas import (  # noqa: E402  (shared wire shapes)
    JournalEntryView,
    MarkerCreate,
    RestoreMarkerView,
    RestoreRequest,
    RestoreResultView,
)


class AdminUserHistory(BaseModel):
    markers: list[RestoreMarkerView]
    entries: list[JournalEntryView]
    entries_total: int


# -- conversion requests (tier conversion, 2026-11-10) ------------------------


class AdminConversionRequestView(BaseModel):
    """One row of the god queue: who is asking, when they asked,
    where the request stands, and — once decided — who decided
    it and when. The requester's identity is the account's own
    (name, account number, email): the decider judges a person,
    not a token."""

    id: uuid.UUID
    user_id: uuid.UUID
    account_number: str
    name: str
    email: str
    status: str
    created_at: datetime
    decided_by_email: str = ""
    decided_at: datetime | None = None
