"""Core module tables.

Owned exclusively by the core module. Other modules read user data via
service.py functions, never by importing these models.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Sequence, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Gapless allocation is NOT promised (rollbacks can skip numbers); uniqueness
# and concurrency-safety are. nextval() is atomic in Postgres, so concurrent
# signups can never receive the same number. Created by the Alembic migration.
account_number_seq = Sequence("account_number_seq", metadata=Base.metadata)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable account number. Assigned ONCE at signup and
    # never changed afterwards (sweep fix 10-F12): an account born
    # with a group set carries their segment — the letters of ALL
    # the account's groups in canonical order, e.g. "TV-MD-000123"
    # for a mechanic who also deals (see account_types.py +
    # service.format_account_number) — and an account born bare
    # keeps the plain "TV-000123" form even after it picks its
    # groups. Later group changes never rewrite the number:
    # signup tells the user to keep it handy, so the number they
    # were given is the number for the life of the account.
    account_number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    # The account's group SET (account_types.ACCOUNT_TYPES), stored
    # as a JSON array in canonical order. Empty = not chosen yet:
    # OAuth-created accounts start empty (email signup forces a pick;
    # social login can't ask mid-redirect) and pre-group legacy
    # accounts start empty until the one-time in-app prompt. The app
    # gates empty-set users onto that prompt.
    account_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Whether email+password login works for this account. OAuth-created
    # accounts hold an unmatchable random hash, indistinguishable from a
    # real password — this flag is the record. Set False at OAuth
    # creation, True at email signup and after any password change.
    password_login_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=True
    )
    email_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Referral capture (billing, owner decisions 2026-10-18): who
    # referred this account — the referrer's user id, resolved at
    # signup from the referral code (the referrer's account number).
    # NULL = organic signup. The referral rule (5 currently-paying
    # referrals = 1 free month) reads exactly this column.
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    # Operator (module doctrine, owner 2026-10-18): the site owner's
    # own flag — gates the /api/admin/* surface and the /admin/modules
    # screen. Not a group and never self-serve: set by migration or
    # directly in the database, for named accounts only.
    is_operator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Community role (role ladder, owner 2026-10-18): the account's
    # standing on community surfaces — user | moderator |
    # community_admin (service.ROLES). Separate from the account
    # GROUP set and from is_operator: a moderator is not an
    # operator. The foundation lands with the admin panel; the
    # community modules consume it when they ship.
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="user", server_default="user"
    )
    # Account tier (owner design, 2026-10-31 — core/tiers.py): the
    # account's primary RUNG: downloads | normal | moderator |
    # moderator_admin | god (downloads added 2026-11-09: the
    # limited level a no-code signup lands on). The rung drives who may grant what (admin user
    # management), the god account's self-only protection, and the
    # module switchboard's per-tier layer. The community `role`
    # above is the rung's shadow on community surfaces, kept in
    # sync by service.set_user_tier / set_user_role. Backfilled by
    # migration 0067 from (is_operator, role): operator ⇒ god,
    # community_admin ⇒ moderator_admin, moderator ⇒ moderator.
    tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default="normal", server_default="normal"
    )
    # Beta Tester upgrade (owner design, 2026-10-31): NOT a rung —
    # a stackable flag (normal/moderator accounts) granting early
    # access to modules lit for the switchboard's beta tier.
    # Granted/revoked by god or a moderator admin; never self-serve.
    beta_tester: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Soft deactivation (admin panel, owner 2026-10-18): False =
    # the account cannot sign in and its sessions are revoked, but
    # NOTHING is deleted — an operator can reactivate it and the
    # account returns exactly as it was. Distinct from the user's
    # own permanent self-delete (service.delete_account).
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Stripe customer id (billing, 2026-10-19). NULL until the
    # account's first checkout creates the customer lazily — the
    # billing module owns the write (it resolves users through
    # core's service), core only stores the fact. The id is the
    # join key every Stripe webhook resolves by when an event
    # carries no user metadata.
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    # Community contact preferences (messaging + parts pool,
    # 2026-10-19): the seller-facing facts the community surfaces
    # may show. All three are the user's own choices, edited in
    # Settings → Public profile & contact:
    # - public_area_label — a COARSE area ("Central Minnesota"),
    #   never an address; shown on the public profile and pool
    #   listings unless a listing overrides it.
    # - contact_phone — the number the user is willing to publish.
    # - show_phone — the opt-in itself (default OFF): the number
    #   rides a public payload ONLY while this is true (a listing
    #   may override it per part).
    public_area_label: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    contact_phone: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", server_default=""
    )
    show_phone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Claim-readiness nudges (audit A8): the user's own opt-out
    # for the periodic inbox nudge about claim-critical record
    # gaps. Default OFF-silence (nudges on); edited in
    # Settings -> Notifications.
    silence_claim_readiness_nudges: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Report contact details (reports alignment, 2026-10-19): the
    # owner's phone + postal address for the PREPARED FOR block on
    # generated paperwork (app-style reports, claims documents).
    # Private account data — unlike contact_phone above, these are
    # never published to community surfaces; they only render on
    # the owner's own documents. Both optional: "" = unset, and
    # unset renders as ABSENT on a report, never a blank line.
    phone: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", server_default=""
    )
    postal_address: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    # Country + currency (wave 3, 2026-10-20). `country` is an
    # ISO 3166-1 alpha-2 code the user may give at signup and edit
    # in Profile — optional, "" = unset. `currency` is an ISO 4217
    # code, default USD; it DEFAULTS FROM the country when the
    # country is picked (core.money.COUNTRY_CURRENCIES) and is
    # independently changeable afterwards.
    #
    # V1 SEMANTICS (deliberate, owner brief): an account's amounts
    # are IN its currency — stored amounts are never converted.
    # The currency only decides how the owner's own money renders
    # and which approximate "≈" hint a viewer in another currency
    # sees on cross-user surfaces (core.money + the fx_rates cache).
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="", server_default=""
    )
    # Interface language (audit A17, 2026-10-22): the user's
    # explicit locale preference ("en" | "es"; "" = unset, fall
    # back to the country default, then English). Edited in
    # Settings -> Appearance; read by the frontend shell, the
    # transactional emails, and the report/PDF chrome.
    locale: Mapped[str] = mapped_column(
        String(5), nullable=False, default="", server_default=""
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    # Community product catalog consent (wave 4, 2026-10-20):
    # while True, this account's items feed the derived community
    # catalog with SPEC FIELDS ONLY (brand, model, category, size,
    # list price / MSRP) — serials, prices paid, photos and notes
    # NEVER contribute. The catalog aggregates live items at read
    # time, so turning this off removes the account's weight from
    # every aggregate immediately; there are no copies to scrub.
    catalog_contribute: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Appearance (owner ruling, 2026-10-25): the site's look —
    # light/dark mode, accent color, theme — lives with the
    # ACCOUNT, not the browser. All three are NULL until the
    # user first saves an appearance while signed in; NULL reads
    # as "never saved", and the client keeps its defaults (dark +
    # orange) for such accounts, so legacy accounts see no
    # surprise change. Once saved, the account value wins over
    # any browser-local value at sign-in, on every device. The
    # browser's localStorage copy remains only as a pre-login
    # cache (and the signed-out landing's behavior). Edited via
    # Settings -> Appearance and the header color-gear popup,
    # which read/write the same fields through PATCH /me.
    appearance_mode: Mapped[str | None] = mapped_column(
        String(8), nullable=True, default=None
    )
    appearance_accent: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None
    )
    # Per-mode accent (owner order, 2026-11-08): the accent is
    # remembered PER MODE — appearance_accent above is the DARK
    # mode pick (it is the value every account saved before this
    # split existed, saved overwhelmingly in dark), and this
    # column is the LIGHT mode pick. NULL = no pick in light
    # mode, and the client applies the light default (silver)
    # until the user picks a color while in light. A pick in one
    # mode never writes the other mode's column.
    appearance_accent_light: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None
    )
    appearance_theme: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    # Wizard defaults (Wizard Phase 1, 2026-10-25): the user's
    # Add-tool / Add-battery wizard setup as ONE JSON document —
    # the optional sections pre-checked on the wizard's include
    # step, plus the usual storage location and usual dealer the
    # wizard pre-fills. NULL = never saved (the client uses the
    # shipped defaults: nothing pre-checked, no usual values);
    # a saved object — an empty sections list included — is the
    # user's explicit setup and follows the account to every
    # device, like the appearance triple above. The client owns
    # the document's shape; the schema bounds its size at the
    # PATCH /me door. Edited via Settings → Add-tool wizard
    # defaults.
    wizard_defaults: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    # Rail pin (widget options Wave 1, owner design 2026-11-02):
    # the account-held choice to keep the left menu rail open.
    # NULL = never set — the client reads it as unpinned, so
    # legacy accounts keep the rail's hover behavior exactly;
    # True = the rail stays open on every device the account
    # signs in on; False = an explicit unpin. Mirrors the
    # appearance posture above: written via PATCH /me, hydrated
    # at sign-in, the account wins over any browser-local value.
    rail_pinned: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BannedEmail(Base):
    """One banned email address (admin panel, owner 2026-10-18).

    A ban is an operator block on an ADDRESS, enforced at every
    door: email signup refuses it, password sign-in refuses it,
    social sign-in refuses it (resolve_oauth_user checks before
    find-or-create, so a banned address can't slip in via Google),
    and banning revokes the live sessions of any account already
    holding the address. A ban deletes nothing; removing the row
    restores access exactly as it was.
    """

    __tablename__ = "banned_emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stored lowercased (emails compare case-insensitively here,
    # exactly as users.email lookups do).
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # The operator who placed the ban (plain id — no FK, so the
    # record survives any account lifecycle event).
    banned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    """One operator action, recorded (admin panel, owner
    2026-10-18: "see all audit data"). Every mutating /api/admin/*
    endpoint writes a row through audit.record: who (id + email
    snapshot, so the trail survives account changes), what action,
    which target, and a small JSON detail. Read-only once written —
    no endpoint edits or deletes rows.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True
    )
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    # Dotted action vocabulary (audit.ACTIONS): module.global_toggle,
    # code.create, user.operator_grant, ban.create, setting.update, …
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # What the action was done TO: a user id, an email, a module id,
    # a code string, a setting key — as text, so any target fits.
    target: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class ModuleState(Base):
    """One feature module's global switch (module doctrine, owner
    2026-10-18). A row per registered feature module, seeded by the
    migration from the manifests. globally_enabled=False is the
    operator's kill switch: the module is off for EVERYONE, whatever
    the group assignment says. A missing row reads as enabled (the
    service's fallback) so a freshly registered module works before
    its seed lands."""

    __tablename__ = "module_state"

    module_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    globally_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModuleAccess(Base):
    """One (feature module, account group) assignment cell (module
    doctrine, owner 2026-10-18). The operator's per-group switch:
    enabled=True means accounts holding that group get the module
    (subject to the global switch and the dependency graph). Seeded
    by the migration from each manifest's default_groups; when a
    module has NO rows at all, the service falls back to those
    defaults — the seeded matrix and the fallback always agree."""

    __tablename__ = "module_access"
    __table_args__ = (
        UniqueConstraint("module_id", "account_group", name="uq_module_access_cell"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # account_types.ACCOUNT_TYPES vocabulary.
    account_group: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModuleTierAccess(Base):
    """One (feature module, account tier) switchboard cell (owner
    design, 2026-10-31). The staged-rollout layer of module
    control: enabled=True means accounts whose rung (or beta flag)
    carries this tier key may use the module — subject to the
    global switch, the group assignment, and their own switches.
    Seeded by migration 0067 from each module's global state (on ⇒
    every tier on; off ⇒ every tier off); when a module has NO rows
    at all, the service reads every tier as the module's global
    state, so the seed and the fallback can never disagree."""

    __tablename__ = "module_tier_access"
    __table_args__ = (
        UniqueConstraint("module_id", "tier", name="uq_module_tier_access_cell"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # core/tiers.TIER_KEYS vocabulary: normal | moderator |
    # moderator_admin | beta | downloads (0096: the downloads
    # level's cells are seeded explicitly — that key reads no
    # fallback in the service). God has no cell — god bypasses.
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserModulePref(Base):
    """One user's own on/off switch for one feature module
    (per-user module toggles, owner 2026-10-24).

    A row exists only where the user flipped a switch; absence
    of a row means the module is ON for that user (subject to the
    operator layer in module_control). The user's switches only
    ever NARROW what the operator layer already allows — a row
    can never grant a module the user's groups don't entitle.
    Data is never touched by a switch: turning a module back on
    restores it exactly, row and all (an "on" flip keeps its row
    with enabled=True). Inventory and support are always-on and
    never carry a disabling row — the service guards their writes.
    """

    __tablename__ = "user_module_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "module_id", name="uq_user_module_pref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserPageLayout(Base):
    """One user's saved layout for one page (owner directive 2026-10-17:
    users arrange the blocks on each page themselves).

    `blocks` is the ordered list of {"key": str, "visible": bool} the
    client saved. Block keys are OPAQUE to the server — the page's block
    registry lives in the frontend; stored entries for blocks that no
    longer exist (or that the user's groups can't see) are simply
    ignored at render time. No row = the user never customized the
    page, and the client renders the page's registered defaults.
    """

    __tablename__ = "user_page_layouts"
    __table_args__ = (
        UniqueConstraint("user_id", "page_key", name="uq_user_page_layout"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    page_key: Mapped[str] = mapped_column(String(64), nullable=False)
    blocks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConversionRequest(Base):
    """A downloads-level account's ONE request for full access
    (owner order, 2026-11-10): the no-code path beside the gate
    code. An account that was handed the full-access code converts
    itself (core/tier_conversion.py); an account without one may
    ASK — once. The unique user_id is the anti-spam rule at the
    schema level: one request per account, EVER. A denial does
    not free the slot (the owner's ruling — the code door stays
    the route after a no), and approval consumes it too: the
    conversion itself ends the account's life on the rung, so a
    second request could never mean anything.

    status: pending → approved | denied, decided by a god-tier
    account alone. The decider is snapshotted (id + email, the
    audit trail's posture) so the record stays readable even if
    accounts later change.
    """

    __tablename__ = "conversion_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_by_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    """A long-lived refresh token, stored ONLY as a SHA-256 hash.

    Rotation: every use revokes the presented token and issues a new one
    (`replaced_by_id` chains them). Presenting an already-revoked token
    that was ROTATED AWAY (`replaced_by_id` set) is treated as theft —
    the service revokes the user's whole token family. Presenting a
    token that was revoked WITHOUT a replacement (logout, session
    revoke, password change, ban) just fails on its own: the revocation
    was a deliberate act, and a stale client retrying it is not theft
    (deep audit F4-01).
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # The browser/device that started this session, captured at
    # issuance and inherited across rotations — drives the Settings
    # "Your sessions" list. NULL for sessions minted before the
    # capture existed (OAuth callbacks included, until threaded).
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Set when the token is rotated out, logged out, or killed on reuse.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EmailVerificationToken(Base):
    """One-time email-verification token, stored ONLY as a SHA-256 hash."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PasswordResetToken(Base):
    """One-time password-reset token, stored ONLY as a SHA-256 hash.

    Same shape as EmailVerificationToken on purpose — its own table
    (not a purpose column on the verification table) so the working
    signup-verification path takes zero churn, and each flow's
    expiry/consumption rules stay independently readable. The plain
    token travels only inside the emailed link.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EmailChangeToken(Base):
    """One pending email change, confirmed at the NEW address.

    The row IS the pending state Settings shows: `new_email` is
    where the confirmation link went; the change lands only when
    the token is consumed. Stored token is ONLY a SHA-256 hash,
    like every other one-time token in this module.
    """

    __tablename__ = "email_change_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    new_email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EmailOutbox(Base):
    """One outbound email, recorded by the provider seam
    (app/core/notifications.py) on EVERY send attempt.

    The pre-launch drill book: with EMAIL_PROVIDER=dev nothing
    leaves the server, but every flow (verification, password
    reset, email change) writes its message here — recipient,
    subject, body and all — so the whole system is testable and
    inspectable before the Resend key exists. With the provider
    live, `status` is the delivery record: "sent" or "failed"
    (dev rows record "logged"). `body` is stored whole: it makes
    the row a complete drill artifact, links and all; the links
    inside are single-use and short-lived by design.
    """

    __tablename__ = "email_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # The flow that produced the message: verification |
    # password_reset | email_change | email_changed_notice |
    # generic (notifications.EMAIL_KINDS).
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    body: Mapped[str] = mapped_column(String, nullable=False, default="")
    # The transport that handled it: dev | resend (settings).
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="dev")
    # logged (dev) | sent | failed (resend outcomes).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="logged")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShareConfig(Base):
    """One owner's sharing setup for ONE recipient group (consent
    sharing, owner directive 2026-10-17).

    A row exists only after the owner saves sharing settings for that
    group; no row = never configured = the catalog defaults with
    sharing OFF (see sharing.py). `fields` holds the chosen OPTIONAL
    fields (sharing_catalog.OPTIONAL_FIELDS) in catalog order; the
    locked identity fields are not stored — they always go when an
    item is shared.
    """

    __tablename__ = "share_configs"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "recipient_group", name="uq_share_config_owner_group"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # sharing_catalog.RECIPIENT_GROUPS: shop_company | insurance.
    recipient_group: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PeerShare(Base):
    """One person's tool LIST shared with one specific person (peer
    sharing, owner directive 2026-10-17).

    A different system from consent (tier) sharing above: the
    recipient is a named person, not a group, and the payload is
    FIXED and minimal (identity + photos — see peer_sharing.py). A
    mechanic shares with their crew so anyone can search "who has
    this tool?"; a shop owner shares shop tools the same way.

    Viewer identity is one of:
      - viewer_user_id — set when the invite named an account
        (by account number, or by an email that already has one), or
        when a pre-signup email invite is accepted;
      - invited_email — set for invites sent by email. An invite to
        an email with no account waits here and attaches when that
        email signs up (pending lists match on it).

    Status is pending → accepted. Decline / revoke / leave DELETE
    the row: a refused or ended share leaves no residue, and the
    owner can always invite again. Nothing is visible to the viewer
    before acceptance.
    """

    __tablename__ = "peer_shares"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "viewer_user_id", name="uq_peer_share_owner_viewer"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    viewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Lowercased at invite time. Set for email invites (whether or
    # not the account exists yet); NULL for account-number invites.
    invited_email: Mapped[str | None] = mapped_column(String(320))
    # "pending" | "accepted" (peer_sharing.PEER_STATUSES).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PeerShareExclusion(Base):
    """One item the owner withholds from ALL peer viewers.

    Peer sharing is default-include: every item on the owner's list
    is visible to accepted viewers except the rows here. (Tier
    sharing is the opposite shape — explicit per-item rows — because
    that consent is per group; a crew list is meant to be the whole
    toolbox minus what the owner holds back.)

    `item_kind` discriminates the target ('tool' — the original
    rows — or 'battery'); exactly one of tool_id / battery_id is
    set, matching the kind. Rows written before batteries existed
    are all kind 'tool' with battery_id NULL.
    """

    __tablename__ = "peer_share_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "item_kind",
            "tool_id",
            "battery_id",
            name="uq_peer_exclusion_owner_item",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tool", server_default="tool"
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        index=True,
    )
    battery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batteries.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SharedItem(Base):
    """One item the owner shares with one recipient group.

    The per-item half of consent sharing: an item reaches a group's
    recipients only when a row exists here AND the group's
    ShareConfig is enabled. Rows are replaced wholesale by the
    settings item picker (the client sends the full set).

    `item_kind` discriminates the target ('tool' — the original
    rows — or 'battery'); exactly one of tool_id / battery_id is
    set, matching the kind. Batteries share under the same field
    rules as tools (sharing_catalog.py) — the kind only changes
    which table the id names.
    """

    __tablename__ = "shared_items"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "item_kind",
            "tool_id",
            "battery_id",
            "recipient_group",
            name="uq_shared_item_owner_item_group",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tool", server_default="tool"
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        index=True,
    )
    battery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batteries.id", ondelete="CASCADE"),
        index=True,
    )
    recipient_group: Mapped[str] = mapped_column(String(50), nullable=False)
    # SETS (item structure package, 2026-10-18): when the shared item
    # is a set, the owner's stored answer to "include the addon
    # pieces too?" — asked at selection time, carried with the share
    # (attached tools follow it). Meaningless for non-set items.
    include_addons: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PeerSetChoice(Base):
    """The owner's stored addon choice for ONE set in PEER sharing
    (item structure package, 2026-10-18).

    Tier (consent) sharing stores its choice per share row
    (shared_items.include_addons — opt-in there, default off). Peer
    sharing is the owner's CREW list: its payload philosophy is
    default-include, so the choice defaults TRUE and this table only
    records sets the owner has explicitly decided about. Absence of
    a row = include addons. Attached tools ride inside the set entry
    either way (they never appear as top-level peer items while
    attached); the flag governs whether their (and addon pieces')
    details are carried.
    """

    __tablename__ = "peer_set_choices"
    __table_args__ = (
        UniqueConstraint("owner_id", "set_tool_id", name="uq_peer_set_choice"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    set_tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    include_addons: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShareRule(Base):
    """One rule that shares items with a recipient group by SCOPE
    (Package C, owner review round 1 item 15, 2026-10-19).

    Tier sharing's per-item picks (shared_items) are the `item`
    scope; a rule is everything else — a whole category, a location
    node (subtree), a tag, or ALL inventory. Rules resolve
    DYNAMICALLY at read time (sharing.resolve_shared_items): an
    item bought tomorrow into a shared category or toolbox is
    shared with zero further action; an item moved out stops being
    shared. A rule never stores item ids — it stores the scope and
    matches live data on every read.

    `scope_value` is the match text for category rules and a
    display snapshot for the others; `scope_ref_id` names the
    location node / tag for those scopes. The ref is deliberately
    NOT a foreign key: if the node or tag is deleted, the rule
    dangles harmlessly (matches nothing, shows a zero count) and
    the owner can delete it — a rule must never take items down
    with it or block a delete elsewhere. `include_addons` is the
    stored answer to "include the addon pieces too?" for sets the
    rule matches (asked when the rule is created, editable later);
    a per-item PICK's own stored choice outranks it for that set.
    """

    __tablename__ = "share_rules"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "recipient_group",
            "scope",
            "scope_value",
            "scope_ref_id",
            name="uq_share_rule_owner_group_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_group: Mapped[str] = mapped_column(String(50), nullable=False)
    # sharing.RULE_SCOPES: category | location | tag | all
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_value: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    scope_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    include_addons: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ShareExclusion(Base):
    """One item the owner withholds from ONE recipient group even
    though a sharing rule (or a pick) would otherwise share it
    (Package C). Exclusions are the top of the resolution order:
    (picks ∪ rule matches) − exclusions. Shape mirrors SharedItem
    so the two read side by side; the group is per-row because
    withholding from the shop says nothing about the insurer."""

    __tablename__ = "share_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "item_kind",
            "tool_id",
            "battery_id",
            "recipient_group",
            name="uq_share_exclusion_owner_item_group",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tool", server_default="tool"
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        index=True,
    )
    battery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batteries.id", ondelete="CASCADE"),
        index=True,
    )
    recipient_group: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PeerShareExclusionRule(Base):
    """One rule that withholds items from ALL peer viewers by scope
    (Package C). Peer sharing is default-include — the whole list
    goes minus what the owner holds back — so the tier rule model
    generalizes in the WITHHOLDING direction: a category, a
    location subtree, or a tag whose items never appear on the
    crew list, resolved dynamically exactly like tier rules (a
    tool filed tomorrow into a withheld location is withheld with
    no further action). Per-item withholding stays in
    peer_share_exclusions; this table is its scope-level sibling.
    `scope_ref_id` is not an FK, for the same reason as ShareRule's.
    """

    __tablename__ = "peer_share_exclusion_rules"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "scope",
            "scope_value",
            "scope_ref_id",
            name="uq_peer_exclusion_rule_owner_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # sharing.RULE_SCOPES minus 'all' (withholding everything is
    # what revoke is for): category | location | tag.
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_value: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    scope_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InsuranceProfile(Base):
    """The user's own insurance details (Package C, owner review
    round 1 item 17): ONE profile per user — their insurer and
    their agent — kept in Settings → My Insurance and consumed by
    the claims flow. Insurers don't have accounts in v1 (blueprint
    §15's directory is a later phase); this is the near-term
    answer: the claim form pre-fills insurer + policy from here,
    and each claim SNAPSHOTS the agent block at creation so a
    later profile edit never rewrites a filed claim. Every field
    is free text the user typed about their own policy — nothing
    here is verified against any insurer, and nothing is shared.
    """

    __tablename__ = "insurance_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    insurer_company: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    # Wave 3 (2026-10-20): the optional link to the platform's
    # insurer directory (insurer_companies below). Picking a
    # company FILLS insurer_company from the directory row's name;
    # the name stays editable afterwards and free text remains the
    # fallback when no directory company fits. SET NULL on
    # directory delete — the typed name survives, the link goes.
    insurer_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("insurer_companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_name: Mapped[str] = mapped_column(
        String(300), nullable=False, default=""
    )
    agent_phone: Mapped[str] = mapped_column(
        String(60), nullable=False, default=""
    )
    agent_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    policy_number: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    notes: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Policy depth (audit A9, 2026-10-22): the owner's own record
    # of what their policy says. policy_type is one of
    # insurance.POLICY_TYPES ("" = not recorded); a DEDICATED tool
    # policy never triggers the business-use sub-limit guidance.
    # Money is cents, NULL = not declared. valuation_basis is
    # "" | "acv" | "rcv" — recorded, never computed with.
    policy_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", server_default=""
    )
    deductible_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_limit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valuation_basis: Mapped[str] = mapped_column(
        String(10), nullable=False, default="", server_default=""
    )
    business_sub_limit_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    how_to_file: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Notification(Base):
    """One in-app notification for one user (the inbox behind the
    header ticker and the home Notifications block — NOT email; the
    outbound mail stub lives in app/core/notifications.py).

    Rows are generated by the services that own the event (today:
    the peer-sharing lifecycle — see inbox.py) in the same commit as
    the event itself, so the inbox can never announce something that
    didn't happen. `data` carries the event's ids for future deep
    links; `read_at` NULL = unread.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # inbox.KINDS: peer_invite_received | peer_invite_accepted |
    # peer_invite_declined (today — the only cross-party events).
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationChannelPref(Base):
    """One user's on/off choice for one notification CHANNEL in
    one category (owner item 12, 2026-10-24).

    The model is channel-shaped on purpose — `channel` is a
    plain string ("email" today; "push" / "sms" slot in later
    with no rebuild) — while the BELL is not modeled at all: the
    in-app inbox is the base layer and is always on. A row
    exists only where the user changed a category's channel
    away from its default; absence means the category default
    (see notification_prefs.CATEGORY_EMAIL_DEFAULTS). Rows never
    delete: flipping back stores the default value explicitly,
    which reads identically.
    """

    __tablename__ = "notification_channel_prefs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category", "channel", name="uq_notification_channel_pref"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NewContentAlertPref(Base):
    """One user's new-content inbox opt-ins (sweep E4,
    busy-work #6, 2026-11-12): "tell me when NEW file downloads
    / NEW 3D print files appear."

    The flyer_alert_prefs pattern (the module-owned pref table,
    a row only where the user flipped away from the default)
    with the default INVERTED, per Ryan's spec for this lane:
    every opt-in defaults OFF, so absence of a row reads as
    opted OUT and a row exists only where the user checked a
    box (the stored booleans then say exactly which boxes).
    These govern the INBOX notices themselves — unlike
    NotificationChannelPref, which governs only email twins.
    """

    __tablename__ = "new_content_alert_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    downloads_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    prints_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ContentAlertState(Base):
    """Tiny key/value state for the content-alert fan-outs
    (sweep E4). One row today: key "downloads_catalog_seen_at"
    — the watermark the downloads catalog sync stamps the
    FIRST time it ever runs in an environment. A catalog key
    whose first appearance is observed while the watermark
    already exists is genuinely new and may notify; anything
    present at (or before) the first sync is baseline shelf
    and never notifies. This is what keeps a deploy from
    announcing the whole shelf."""

    __tablename__ = "content_alert_state"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FeatureAnnouncement(Base):
    """One operator-composed feature announcement (release
    machinery, owner rule 2026-11-08: every new feature ships
    with a notification to ALL current users).

    The row is the durable record of the announcement itself —
    the Admin history reads these rows, never the per-user
    notification copies. Lifecycle: an operator composes one in
    Admin -> Announcements, which lands it here as "queued";
    the announcements job (app/scripts/run_announcement_jobs.py)
    fans it out to every ACTIVE account as an inbox notification
    (inbox kind feature_announcement) and flips the row to
    "sent" with the recipient count and timestamp. A row is
    never edited or re-sent once created — corrections are a
    new announcement — so `status` moves exactly once,
    queued -> sent (or queued -> failed, with the job free to
    retry a failed row on its next run by flipping it back
    through the same path).
    """

    __tablename__ = "feature_announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # Optional in-app destination for the notification's
    # click-through (a route like "/reports"). Validated as an
    # internal path at compose time and again at link resolution.
    link: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    recipient_count: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # The author's display name, snapshotted at compose time so
    # the history stays readable even if the account is renamed
    # or removed later.
    created_by_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Release scoping (module release events, owner order
    # 2026-11-09; migration 0096): an announcement queued by a
    # module tier flip names its module here and carries the
    # exact audience — the accounts that GAINED the module in
    # that flip — as a JSON list of user ids. NULL on both =
    # an operator-composed announcement to everyone, exactly as
    # this table has always behaved. When release_module_id is
    # set, the fan-out renders the title/body per recipient from
    # the release templates in the recipient's language
    # (announcements.py); the stored title/body are the English
    # rendering, which is what the Admin history reads.
    release_module_id: Mapped[str | None] = mapped_column(String(64))
    audience_user_ids: Mapped[list | None] = mapped_column(JSON)
    # Per-language parts (single-language rule, owner order
    # 2026-11-10; migration 0102). The stored title/body above
    # are the English rendering — the Admin history record.
    # These nullable columns hold the announcement's renderings
    # split by language (the Spanish title; the English body;
    # the Spanish body) so the fan-out can give EVERY recipient
    # — inbox entry and email twin alike — only their own set
    # language (announcements.recipient_copy_for). NULL = no
    # part was composed for that language; the fan-out falls
    # back to the stored title/body for those recipients.
    title_es: Mapped[str | None] = mapped_column(String(200))
    body_en: Mapped[str | None] = mapped_column(String(1000))
    body_es: Mapped[str | None] = mapped_column(String(1000))


class BackupRun(Base):
    """One Disaster Vault bundle run (app/backup/job.py).

    The platform-backup ledger: the nightly job writes a row when
    it STARTS (status "running") and completes it with the outcome,
    so a crashed job leaves a visible unfinished row instead of a
    silent gap — silence is exactly what a backup system must
    never produce. `detail` carries the manifest summary (counts,
    hashes), the failing stage + error on failure, and the record
    of any report emails the run triggered.

    Status vocabulary:
      running                   — in progress (or died mid-run)
      ok                        — built, encrypted, uploaded, verified
      local_only                — built (+ encrypted when configured)
                                  but no Drive leg configured; kept
                                  on the server, NOT a failure
      encryption_not_configured — built but the age recipient key is
                                  unset: unencrypted, local-only, and
                                  never uploaded by design
      failed                    — a stage raised; detail says which
                                  stage, the error, and the fix
    """

    __tablename__ = "backup_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bundle_name: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class JobRun(Base):
    """One run of a periodic background job (app/scripts/scheduler.py).

    The jobs ledger — the BackupRun pattern applied to the five
    run_*_jobs chores (entitlements, maintenance, claims,
    marketplace, audit). The scheduler writes a row when a run
    STARTS (status "running") and completes it with the outcome,
    so a crashed job leaves a visible unfinished row instead of a
    silent gap. `detail` carries the job's own summary line on
    success and the exception on failure. Admin → Settings shows
    the latest run per job, read from this table.

    Status vocabulary: running | ok | failed.
    """

    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# -- user audit trail + restore (owner feature note 2026-10-19) --------------
#
# Every user's OWN content carries a change journal: each create /
# update / delete lands a row here with the full before + after
# snapshot of the changed record, written by the journal listener
# (app/modules/core/journal.py) inside the same transaction as the
# change itself. Restore markers are the points an account can roll
# back to. Deleted files are tombstoned in retained_files so a
# restore brings photos back with their records; the purge seam
# hard-deletes them once the retention window (the admin setting
# `audit.retention_days`, default 180) has passed.


class ChangeJournal(Base):
    """One journaled change to one user-owned record.

    `seq` is the monotonic insertion order (the before_insert hook
    below, exactly the checkouts pattern from migration 0023):
    occurred_at alone cannot order the trail — one transaction
    shares one timestamp — and markers remember the seq they were
    taken at, so "everything after this marker" is precise.

    `restorable` is the restore engine's honesty flag: two-party
    records (borrowing rows, peer shares) and filed-claim changes
    are journaled for VISIBILITY only — the engine skips them and
    the restore summary counts them as not changed. `label` is the
    plain-language line the timeline renders ("Deleted tool 'QA
    Prompt Wrench'"). `marker_id` is set only on restore events,
    pointing at the marker that was restored to.
    """

    __tablename__ = "change_journal"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # create | update | delete | restore (restore = the engine's own
    # event row, one per restore, never itself inverted).
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    marker_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    restorable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    label: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class RestoreMarker(Base):
    """A point an account can be restored to.

    `journal_seq` is the journal watermark at creation: a restore
    to this marker inverts every restorable journal entry with a
    higher seq. Kinds: baseline (account creation / the one-time
    deploy baseline), daily (the jobs seam, at most one per user
    per day, only when the journal moved since the last marker),
    manual (the user or an operator pressed the button), pre_bulk
    (forced before an importer confirm), pre_restore (written by
    the restore engine immediately before it runs, so the restore
    itself can be undone).
    """

    __tablename__ = "restore_markers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    journal_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RetainedFile(Base):
    """A tombstoned storage object: its record no longer references
    it (the item was deleted, a photo replaced), but the bytes are
    RETAINED so a restore inside the retention window brings the
    file back with its record. The purge seam (run_audit_jobs)
    hard-deletes rows + objects older than `audit.retention_days`.
    One row per storage key — a key that leaves and returns (a
    restore) drops its tombstone; a key that leaves again re-adds
    it with a fresh clock.
    """

    __tablename__ = "retained_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(
        String(1024), nullable=False, unique=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -- wave 3 (2026-10-20): shop crews, insurer directory, FX cache --------------


class ShopMembership(Base):
    """One person's place in one shop's crew (wave 3).

    shop_user_id is the shop_company-group account that OWNS the
    shop; employee_user_id is the crew member's account (NULL while
    the invite is addressed to an email that has no account yet —
    the pre-signup attach claims it at first read, the truck
    accounts pattern). Both user columns are PLAIN ids, NOT
    foreign keys — the 0038 lesson: a two-party table whose user
    columns are FKs blocks Postgres account deletion; core's
    cascade sweeps these rows explicitly instead.

    Status flow: invited -> active (accept) | declined (refused);
    active -> left (removed by the owner or left by the member).
    A `left` row is the 30-DAY RULE's clock: left_at starts it,
    and the crew job notifies at day 25 and at expiry. Rejoining
    (a fresh invite accepted) simply writes a new active row —
    history stays.

    Membership grants NO data access by itself: what a crew member
    can see of the shop's inventory is decided solely by tier
    sharing (the owner sharing toward the shop_company group) —
    pinned by test.
    """

    __tablename__ = "shop_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shop_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    employee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    invite_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    invite_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # Free text the owner types: "Technician", "Lead tech",
    # "Service manager" — the shop's own words, never a vocabulary.
    role_label: Mapped[str] = mapped_column(
        String(120), nullable=False, default=""
    )
    # invited | active | left | declined
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="invited"
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The 30-day rule's notice ledger: which of the day-25 /
    # expiry notices the crew job has already sent for THIS
    # departure (idempotency lives on the row, like the truck
    # reminders' setting-marker but per-departure).
    grace_notices: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InsurerCompany(Base):
    """One platform-directory insurer (wave 3): operator-curated,
    like the dealer directory. Starts EMPTY — no seed data is
    invented; operators add the real companies. Users pick from
    this directory for their My Insurance profile and (insurance-
    group accounts) their verified affiliation.
    """

    __tablename__ = "insurer_companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    website: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Claims phone numbers: [{label, number}] — the dealer
    # directory's shape (a general line, a claims line, …).
    phones: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InsurerAffiliation(Base):
    """An insurance-group user's claim "I work for THIS directory
    insurer" (wave 3) — the dealer CompanyRepresentation shape:
    self-asserted links are UNVERIFIED until an operator verifies
    them (Admin → Insurer directory → Affiliations, audit rows on
    every flip). Only a VERIFIED affiliation unlocks the
    Policyholders view, and even then the data comes solely from
    the policyholders' own tier sharing toward the insurance
    group — the affiliation alone shares nothing (pinned by test).
    """

    __tablename__ = "insurer_affiliations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "company_id", name="uq_insurer_affiliation_user_company"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("insurer_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The user's role at the company, their own words ("Claims
    # adjuster", "Agent", …).
    role_at_company: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FxRate(Base):
    """One cached exchange rate (wave 3): 1 unit of `currency` =
    `rate` units of EUR (the ECB's base, via frankfurter.app).
    Refreshed daily by the fx job; a failed fetch keeps yesterday's
    rows and logs — a stale hint beats no hint, and hints are
    DISPLAY ONLY (stored amounts never convert; see User.currency).

    The table is platform data: no owner, no per-user rows, and
    account deletion never touches it.
    """

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("currency", "rate_date", name="uq_fx_rate_currency_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CloudDriveConnection(Base):
    """One user's Google Drive connection for automatic backups
    (wave 4, 2026-10-20). ONE row per user: the OAuth refresh
    token (Fernet-encrypted at rest — see core/cloud_backup.py;
    the plaintext never persists and never leaves through the
    API), the app-created "Toolbox Vault Backups" folder id, and
    the backup schedule (off | daily | weekly). The user column
    is PLAIN (the 0038 lesson): the core deletion cascade sweeps
    this row explicitly."""

    __tablename__ = "cloud_drive_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    refresh_token_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    drive_folder_id: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    drive_folder_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    schedule: Mapped[str] = mapped_column(
        String(10), nullable=False, default="off", server_default="off"
    )
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_backup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlatformDriveConnection(Base):
    """The PLATFORM's Google Drive connection for Disaster Vault
    off-site copies (2026-10-24). Effectively a SINGLE row: the
    operator connects Drive ONCE as the MechanicVault account
    (full drive scope, so the job can write into the pre-existing
    "Toolbox Vault Backups" folder), and the nightly backup job
    uploads AS that account — a service account has no storage
    quota of its own, which is why the old SA leg 403'd forever.
    The OAuth refresh token is Fernet-encrypted at rest (see
    core/cloud_crypto.py + core/cloud_backup.py); the plaintext
    never persists and never leaves through the API.
    `connected_by_id` is a PLAIN user id (no FK, the 0038 lesson).
    """

    __tablename__ = "platform_drive_connection"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    refresh_token_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    drive_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    drive_folder_id: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CloudBackupRun(Base):
    """One cloud-backup attempt (wave 4): the history ledger the
    Settings -> Cloud backup section renders — manual and scheduled
    runs alike, successes and failures (a failure also lands an
    inbox notification at run time). `file_id` is the Drive file
    id; the row's "open in Drive" link is built from it."""

    __tablename__ = "cloud_backup_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running"
    )
    file_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


from sqlalchemy import event, text  # noqa: E402  (hook lives with its model)


@event.listens_for(ChangeJournal, "before_insert")
def _assign_journal_seq(mapper, connection, target):  # noqa: ANN001, ANN202
    """Give every journal row the next sequence value — the
    checkouts pattern (migration 0023): Postgres draws from the
    real `change_journal_seq` sequence (created by migration
    0027); SQLite takes max+1 inside the insert transaction."""
    if target.seq is not None:
        return
    if connection.dialect.name == "postgresql":
        target.seq = connection.scalar(text("SELECT nextval('change_journal_seq')"))
    else:
        target.seq = connection.scalar(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM change_journal")
        )


class RoadmapEntry(Base):
    """One operator-published roadmap line (audit A15):
    the public "What's coming" page renders these; only
    operators write them. Ships EMPTY — content is the
    operator's word, never seeded."""

    __tablename__ = "roadmap_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )


class VisitorCounter(Base):
    """Unique-visitor counters (owner orders, 2026-10-26,
    2026-11-08 and 2026-11-10): one row per counted page —
    id 1 the teaser page, id 2 the Downloads page, id 3 the
    3D Print Files page — each bumped by a single atomic
    UPDATE per newly-counted browser — the te_pool_epoch pattern
    (migration 0063), never a Python read-modify-write. Who gets
    counted (first-party counted-cookie, automation and operator
    exclusions) lives in core/teaser.py; this table is just the
    numbers. Seeded by migrations 0064 (id 1), 0094 (id 2) and
    0099 (id 3); the service also creates a row inline if a
    database ever lacks it."""

    __tablename__ = "visitor_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class SiteStatsSnapshot(Base):
    """One day's site-state snapshot (admin lane, owner
    2026-11-06): the figures day-over-day deltas are computed
    from — the state a day ENDED in, which timestamps alone
    can't reconstruct later (tier grants, plan changes and
    cancellations aren't timestamped history). The jobs service
    writes one row per day (app/modules/core/site_stats.py);
    `payload` carries the whole day's fact bag (users by tier,
    free vs paying counts, MRR at the day's prices, the day's
    derived counts) so a new delta never needs a new column.
    One row per day, enforced by the unique day; the writer is
    an upsert, so a re-run corrects the day instead of
    duplicating it. Migration 0085."""

    __tablename__ = "site_stats_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OnboardingProgress(Base):
    """One row per (account, setup step) in the onboarding system
    (owner design 2026-10-31, built 2026-11-07; migration 0086).

    The wizard is a guided path over the REAL settings/module
    machinery — this table never stores a setting. It stores only
    where the account stands in the guided pass:

    - step rows: step_key is "account_type", "basics",
      "module:<feature-module-id>" or "setting:<settings-section-id>";
      status is done | skipped | notified (notified = a new-feature
      step the account has been told about, not yet resolved).
    - "__fresh__" (status done): written by the ONE account-creation
      path for every account born after the wizard shipped. Its
      presence is what puts an account in the wizard flow instead
      of the legacy one-time completion gate; accounts that predate
      the wizard never get one, so their behavior is untouched.
    - "__baseline__": detail holds the JSON list of feature module
      ids the account was entitled to when its baseline was taken
      (at first read for a pre-existing complete account; when a
      fresh account finishes or dismisses its first pass). A module
      entitled later, absent from the baseline and unresolved, is a
      NEW FEATURE for this account — the living part of the design.
    - "__dismissed__" (status done): the account waived setup
      prompts. Banners stay down until a step is notified AFTER
      this row's updated_at; reopening deletes the row.

    user_id is a PLAIN id, NOT a foreign key — the 0038 lesson
    (two-party tables whose user columns are FKs block Postgres
    account deletion); core's deletion cascade sweeps these rows
    explicitly, like shop_memberships.
    """

    __tablename__ = "onboarding_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "step_key", name="uq_onboarding_user_step"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="done", server_default="done"
    )
    detail: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
