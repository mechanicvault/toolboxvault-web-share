"""Core module schemas: auth and user shapes."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.modules.core import money
from app.modules.core.account_types import SELF_SERVE_ACCOUNT_TYPES

# Password policy (blueprint §11): minimum length is the one rule with
# real-world payoff; composition rules just push users to write passwords
# down. Enforced here so every password-setting path inherits it.
# Owner policy change 2026-10-17: minimum is 6 characters (was 10).
PASSWORD_MIN_LENGTH = 6

# The account groups (account_types.ACCOUNT_TYPES is the canonical
# list; this Literal is its schema-level mirror — a value outside it
# fails validation with a 422 before any handler runs).
AccountType = Literal[
    "mechanic_technician", "shop_company", "tool_dealer", "insurance"
]

# A group SET as clients send it: valid groups only (a value
# outside the vocabulary is a 422). Whether the set may be EMPTY
# is each surface's own rule, set by its Field: the account-type
# editor still refuses empty (min_length=1); signup no longer
# asks at all (onboarding design, owner 2026-10-31 — the pick
# moved into the setup wizard, where at least one is required to
# complete step 1).
AccountTypeSet = list[AccountType]


class SignupRequest(BaseModel):
    email: EmailStr
    # Same bounds as ProfileUpdate and the String(200) column —
    # uncapped, an oversized name only failed at the database
    # (a 500 on Postgres) instead of a clean 422 (hardening
    # 2026-10-19).
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)
    # Onboarding (owner design 2026-10-31, built 2026-11-07):
    # signup is JUST an account — email + name + password. The
    # group set is no longer asked here (it is the wizard's step
    # 1); a client that still sends one gets it honored, with the
    # self-serve validation below unchanged. Absent/empty = the
    # account starts ungrouped, like a social-login account, and
    # the wizard flow (not the legacy gate) carries it from there.
    account_types: AccountTypeSet = Field(default_factory=list)
    # Referral capture (billing): the referrer's account number,
    # when a friend sent them. Optional; an unknown code is ignored
    # (signup never fails over a referral), a known one is stored on
    # the account for the referral rule.
    referral_code: str | None = Field(default=None, max_length=32)
    # Signup basics (owner directive 2026-10-22; MOVED into the
    # wizard by the onboarding design, 2026-10-31): country,
    # currency and language were required picks at registration;
    # they are now the wizard's basics step, pre-filled with the
    # same defaults. The fields stay accepted (older clients, the
    # service's other creation paths) and stay validated WHEN
    # SENT — an unknown country/currency or unshipped locale is
    # still a 422; absent/empty simply lands unset, and the
    # service's lenient normalization fills the rest.
    # Per-user module choices (2026-10-24): the feature modules
    # the new user unchecked on the signup module step. Unknown,
    # always-on, and unentitled ids are ignored by the service —
    # signup never fails over this list.
    disabled_modules: list[str] = Field(default_factory=list, max_length=32)
    country: str = Field(default="", max_length=2)
    currency: str = Field(default="", max_length=3)
    # Interface language: one of the shipped locales (audit A17).
    locale: Literal["en", "es"] | None = None

    @field_validator("account_types")
    @classmethod
    def _signup_groups_are_self_serve(cls, value: list[str]) -> list[str]:
        # Signup is a self-serve pick: only SELF_SERVE_ACCOUNT_TYPES
        # may be chosen (owner directive 2026-10-31 — insurance is off
        # the list for now). The full vocabulary stays valid at the
        # service layer, where an operator provisions accounts.
        not_offered = [t for t in value if t not in SELF_SERVE_ACCOUNT_TYPES]
        if not_offered:
            raise ValueError(
                "These account types can't be picked at signup: "
                + ", ".join(not_offered)
            )
        return value

    @field_validator("country", mode="before")
    @classmethod
    def _signup_country_known(cls, value: object) -> object:
        if isinstance(value, str):
            candidate = value.strip().upper()
            # Empty = unset (the wizard's basics step asks later);
            # a country that IS sent must be a known one.
            if not candidate:
                return ""
            if candidate in {code for code, _ in money.COUNTRIES}:
                return candidate
            raise ValueError("unknown country")
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def _signup_currency_known(cls, value: object) -> object:
        if isinstance(value, str):
            candidate = value.strip().upper()
            if not candidate:
                return ""
            if candidate in money.CURRENCIES:
                return candidate
            raise ValueError("unknown currency")
        return value


class ProfileUpdate(BaseModel):
    """Body of PATCH /me: profile editing. Every field is optional
    and only the fields sent are applied (the Settings name form
    sends {name}; the Public profile & contact form sends the
    community fields). Email is NOT here: changing it safely
    requires confirming the NEW address by email (the email-change
    flow)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Community contact preferences (2026-10-19): the coarse area
    # label shown on the public profile / pool listings, the phone
    # the user may publish, and the opt-in that lets it show.
    public_area_label: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=40)
    show_phone: bool | None = None
    silence_claim_readiness_nudges: bool | None = None
    # Interface language (audit A17): "en" | "es" | "" (unset);
    # the service normalizes anything else to unset.
    locale: str | None = Field(default=None, max_length=5)
    # Report contact details (reports alignment, 2026-10-19): the
    # phone + postal address that head the owner's own generated
    # paperwork (the reports' Prepared-For block). Private — never
    # published; "" clears them back to unset.
    phone: str | None = Field(default=None, max_length=40)
    postal_address: str | None = Field(default=None, max_length=500)
    # Country + currency (wave 3): editable in Profile. Sending a
    # country WITHOUT a currency re-defaults the currency from
    # the country; sending both keeps the explicit currency.
    country: str | None = Field(default=None, max_length=2)
    currency: str | None = Field(default=None, max_length=3)
    # Community catalog contribution (wave 4): the Settings ->
    # Sharing switch. True = the account's items' spec data
    # (brand/model/category/size/list price) feeds the derived
    # community catalog; False removes its weight immediately
    # (the catalog aggregates live items at read time).
    catalog_contribute: bool | None = None
    # Appearance (owner ruling, 2026-10-25): the account-held
    # look. The client sends the full triple on any appearance
    # change (Settings -> Appearance or the header gear popup);
    # each field is independently optional here like every other
    # field in this body. Mode is a closed pair; the accent is a
    # hex color (3- or 6-digit, the shapes the client's accent
    # system derives from); the theme is a theme id — the
    # client resolves unknown ids to the current design, so
    # the pattern only bounds the shape.
    appearance_mode: Literal["dark", "light"] | None = None
    appearance_accent: str | None = Field(
        default=None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"
    )
    # Per-mode accent (owner order, 2026-11-08): the LIGHT-mode
    # pick, a sibling of appearance_accent (the dark-mode pick)
    # with the same hex shape. Absent/None = no light pick yet;
    # there is no clear-back gesture, like every field above.
    appearance_accent_light: str | None = Field(
        default=None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"
    )
    appearance_theme: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_-]{0,31}$"
    )
    # Wizard defaults (Wizard Phase 1, 2026-10-25): the user's
    # Add wizard setup as ONE JSON document — the client owns its
    # shape (a "sections" list of wizard section keys, the usual
    # "location_id" and "dealer_company_id"); like the appearance
    # theme, the server stores it verbatim and the client
    # resolves unknown section keys away. None = "not part of
    # this update"; there is no clear gesture — resetting the
    # wizard means saving the bare setup explicitly. The one
    # server rule is size: the document is small by design, so
    # anything past the bound is refused at the door with a 422.
    wizard_defaults: dict | None = None
    # Rail pin (widget options Wave 1, owner design 2026-11-02):
    # whether the left menu rail stays open for this account.
    # None = not part of this update; True/False are the two
    # real saves (False is the explicit unpin — the column's own
    # NULL is only ever "never set", read as unpinned).
    rail_pinned: bool | None = None

    @field_validator("wizard_defaults")
    @classmethod
    def _wizard_defaults_bounded(cls, value: dict | None) -> dict | None:
        if value is None:
            return value
        import json

        if len(json.dumps(value)) > 4096:
            raise ValueError("wizard defaults document is too large")
        sections = value.get("sections", [])
        if not isinstance(sections, list) or any(
            not isinstance(s, str) or len(s) > 64 for s in sections
        ):
            raise ValueError("wizard defaults sections must be short strings")
        if len(sections) > 32:
            raise ValueError("too many wizard default sections")
        for key in ("location_id", "dealer_company_id"):
            raw = value.get(key, "")
            if not isinstance(raw, str) or len(raw) > 64:
                raise ValueError(f"wizard defaults {key} must be a short string")
        return value


class SessionPublic(BaseModel):
    """One live session in Settings → Account & security."""

    id: uuid.UUID
    created_at: datetime  # when the session (chain) began
    last_used_at: datetime  # when its token last rotated
    user_agent: str | None = None
    is_current: bool


class RevokeOthersRequest(BaseModel):
    """Body of POST /sessions/revoke-others: the caller's own
    refresh token — the one session that survives."""

    refresh_token: str | None = None


class DeleteAccountRequest(BaseModel):
    """Body of DELETE /me: the type-to-confirm word. The service
    refuses anything but the exact confirmation."""

    confirmation: str = Field(max_length=50)


class AccountTypeRequest(BaseModel):
    """Body of POST /account-type: set (first pick) or replace the
    caller's whole group set. Same rules as signup — never empty."""

    account_types: AccountTypeSet = Field(min_length=1)


class OnboardingStepView(BaseModel):
    """One step of the caller's setup plan (onboarding system,
    2026-11-07). The server owns the probe steps (account_type,
    basics) and the registry module steps; the settings steps are
    the client registry's own — their progress rides the plan's
    `progress` map, not this list."""

    key: str
    kind: str
    module_id: str | None = None
    status: str
    new: bool = False


class OnboardingPlanView(BaseModel):
    flow: str
    dismissed: bool
    steps: list[OnboardingStepView]
    progress: dict[str, str]
    new_feature_modules: list[str]
    resolved: int
    total: int


class OnboardingProgressRequest(BaseModel):
    """Body of POST /onboarding/progress: one step's outcome.
    The service validates the key's shape (and, for module steps,
    the module's existence in the live registry)."""

    step_key: str = Field(min_length=1, max_length=120)
    status: Literal["done", "skipped"]


class PageLayoutBlock(BaseModel):
    """One entry of a page layout: a block key (opaque to the server —
    the page's registry lives in the frontend) and whether it shows.

    `hidden_stats` (owner review round 1, 2026-10-19) is the one
    block-level extra the server carries: the overview block's
    per-stat show/hide choices ride inside its layout entry as a
    list of hidden stat keys (opaque strings, frontend-owned, same
    as block keys). Absent/None = the user never hid a stat, and the
    field is omitted from responses entirely (the routes serialize
    with exclude_none) so pre-existing payloads stay byte-identical.
    """

    key: str = Field(min_length=1, max_length=100)
    visible: bool = True
    hidden_stats: list[Annotated[str, Field(max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    # `order` (Home + Header program, 2026-10-24): the second
    # block-level extra, same contract as hidden_stats — the
    # overview block's per-stat display ORDER (the user drags
    # stat boxes; block order itself is the list order). Opaque
    # frontend-owned keys; absent = registry order.
    order: list[Annotated[str, Field(max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    # `panel_hidden` / `panel_order` (Phase C, 2026-10-24): the
    # Home panel pseudo-entry's extras — the entry with key
    # "panel" carries which Home side-panel sections the user hid
    # and their display order. Same contract as the extras above:
    # opaque frontend-owned section keys; absent = defaults
    # (all sections shown, registry order).
    panel_hidden: list[Annotated[str, Field(max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    panel_order: list[Annotated[str, Field(max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    # `panel_stat_order` (Phase 3, 2026-10-24): the panel
    # entry's third extra — the user's OWN panel stat picks, in
    # display order (the panel's stat catalog keys, frontend-
    # owned). This is a pick LIST, not a hidden list: a stat
    # shows in the panel only when it is listed here, so new
    # catalog stats wait in the panel's Add menu instead of
    # appearing uninvited, and a stat whose module is switched
    # off keeps its place for when the module returns. Absent =
    # never customized — the client renders its default rows.
    panel_stat_order: list[Annotated[str, Field(max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    # `size` + `settings` (widget options Wave 1, owner design
    # 2026-11-02): the framework extras every block may carry.
    # `size` is the block's Home grid width — a closed pair;
    # absent = the block's registered default (module widgets
    # half, the special blocks full), so pre-existing payloads
    # stay byte-identical. `settings` is the widget's own
    # options bundle: a small FLAT document of leaf values
    # (bools, numbers, short strings, short string lists) whose
    # keys are owned by the frontend widget registries — opaque
    # to the server like block keys, and bounded twice: the
    # validator below caps the document at the door, and the
    # service's sanitizer re-checks every entry field-by-field
    # before anything is stored. Absent/None = no options set.
    size: Literal["half", "full"] | None = None
    settings: dict[str, Any] | None = None

    @field_validator("settings")
    @classmethod
    def _settings_bounded(cls, value: dict | None) -> dict | None:
        if value is None:
            return value
        import json

        if len(value) > 32:
            raise ValueError("too many block settings")
        for key in value:
            if not isinstance(key, str) or len(key) > 64:
                raise ValueError("block setting keys must be short strings")
        if len(json.dumps(value)) > 4096:
            raise ValueError("block settings document is too large")
        return value


class PageLayoutSave(BaseModel):
    """Body of PUT /layouts/{page_key}: the page's whole block list,
    in display order. The service dedupes by key (first wins) and caps
    the stored list at service.MAX_LAYOUT_BLOCKS entries."""

    blocks: list[PageLayoutBlock] = Field(default_factory=list, max_length=200)


class PageLayoutResponse(BaseModel):
    """A user's stored layout for one page. `blocks` is EMPTY when the
    user has never customized the page — the client then renders the
    page's registered defaults (the server does not know them)."""

    page_key: str
    blocks: list[PageLayoutBlock]


class PasswordResetRequest(BaseModel):
    """Body of POST /password-reset/request. The answer is the
    same whether or not the account exists — this shape carries
    nothing that could leak that."""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Body of POST /password-reset/confirm: the emailed token and
    the new password (the shared minimum-length policy applies —
    a reset sets a password like any other password path)."""

    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)


class EmailChangeRequest(BaseModel):
    """Body of POST /email-change/request. `current_password` is
    required only when the account has password login enabled —
    an OAuth-only account proves identity with its live session
    (same rule as change-password)."""

    new_email: EmailStr
    current_password: str | None = None


class EmailChangeConfirm(BaseModel):
    """Body of POST /email-change/confirm. The token is the proof
    (the link was sent to the new inbox). `refresh_token` is the
    confirming browser's own session, when it has one — the one
    session that survives the change."""

    token: str = Field(min_length=1, max_length=200)
    refresh_token: str | None = None


class EmailChangeState(BaseModel):
    """GET /email-change: the caller's pending change, if any."""

    pending_email: str | None = None
    expires_at: datetime | None = None


class EmailChangeConfirmResponse(BaseModel):
    detail: str
    email: str


class ResendVerificationRequest(BaseModel):
    """Body of POST /resend-verification (the login page's resend
    for a blocked unverified account). The answer is generic —
    same words whether the account exists, is verified already,
    or never did."""

    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    """Password set/change (Settings → Account & security).

    `current_password` is required only when the account already has
    password login enabled; an OAuth-only account proves identity with
    its live session instead. `refresh_token` is the caller's current
    refresh token — the one session that survives the change; every
    other session is revoked.
    """

    current_password: str | None = None
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class OAuthProviders(BaseModel):
    """Which social-login providers are configured. The frontend renders
    a "Continue with …" button only for the True ones."""

    google: bool
    facebook: bool


class LandingPublicView(BaseModel):
    """The anonymous landing page's ONLY data (landing build,
    2026-10-20; core/landing.py owns the values). Every field is
    public-safe by construction: display prices the operator
    typed, the trial switch + its copy, the store URLs, and the
    plan catalog's free item limit. Nothing else about the system
    leaks through this shape."""

    pro_monthly_price: str
    pro_yearly_price: str
    business_monthly_price: str
    business_yearly_price: str
    self_serve_trial_enabled: bool
    trial_copy: str
    app_store_url: str
    play_store_url: str
    free_item_limit: int
    # Teaser mode (2026-10-26): one boolean — is the public front
    # door the teaser right now? Defaulted so older constructors of
    # this shape keep validating; the endpoint always sends it.
    teaser_mode: bool = False
    # Free-access card gates (2026-10-31): may the landing advertise
    # Tools For Sale / Community Parts? True only while the module
    # switchboard has the module usable somewhere. Defaulted False
    # (never advertise what isn't there); the endpoint always sends
    # the computed values.
    marketplace_enabled: bool = False
    community_parts_enabled: bool = False
    # The current teaser trailer's presigned URLs (site-hosted
    # MP4 + poster frame). Empty unless the teaser is on AND the
    # operator has set a video; defaulted like teaser_mode.
    teaser_video_url: str = ""
    teaser_poster_url: str = ""


class SignupGateView(BaseModel):
    """The signup gate's whole public answer (teaser build,
    2026-10-26): is teaser mode on, and does THIS browser already
    hold a valid unlock? Two booleans — nothing about the gate
    code ever rides in a response."""

    teaser_mode: bool
    unlocked: bool


class VisitCountView(BaseModel):
    """The visitor counter's whole public answer (owner order,
    2026-10-26): the unique-visitor count, as a bare number —
    the teaser page renders it as digits with no words, and
    nothing else about the visit rides in the response."""

    count: int


class SignupUnlockRequest(BaseModel):
    """The gate-code attempt. The code is compared server-side
    (core/teaser.py) and never echoed back."""

    code: str = Field(min_length=1, max_length=64)


class AccessCodeRequest(BaseModel):
    """The tier-conversion code attempt (2026-11-10): a
    downloads-level account presenting the gate code it was
    handed after signup. Same discipline as the signup unlock —
    compared server-side (core/teaser.py), never echoed back."""

    code: str = Field(min_length=1, max_length=64)


class TierConversionView(BaseModel):
    """The conversion's answer: the account's rung now."""

    tier: str


class ConversionRequestStateView(BaseModel):
    """The caller's own conversion-request state: `status` is
    None when the account has never asked (its one request is
    still unspent), else pending | approved | denied."""

    status: str | None
    requested_at: datetime | None = None
    decided_at: datetime | None = None


class UserPublic(BaseModel):
    """What the API ever reveals about a user. No hashes, ever."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_number: str
    # The account's group set, canonical order; [] = not chosen yet
    # (the app prompts). Never null in API output.
    account_types: list[str]
    email: str
    name: str
    email_verified: bool
    # Drives the Settings password form: False = OAuth-only account
    # (offer "set a password"), True = offer "change password".
    password_login_enabled: bool
    # Operator flag (module doctrine, owner 2026-10-18): drives the
    # Admin nav item. The /api/admin/* endpoints re-check it server-
    # side; this field only controls what the UI offers.
    is_operator: bool = False
    # Community role (role ladder): drives the moderation-queue
    # link; the queue endpoints re-check it server-side.
    role: str = "user"
    # Account tier (2026-10-31): the caller's rung + beta flag —
    # drives the Admin entry for moderator admins (user
    # management) and any tier-aware UI; endpoints re-check
    # server-side.
    tier: str = "normal"
    beta_tester: bool = False
    # Community contact preferences (2026-10-19) — the caller's OWN
    # values, so Settings can edit them. Other users' phones never
    # travel this shape: the public profile (messaging) includes a
    # phone only while its owner opted in.
    public_area_label: str = ""
    contact_phone: str = ""
    show_phone: bool = False
    silence_claim_readiness_nudges: bool = False
    # Report contact details (reports alignment, 2026-10-19) — the
    # caller's OWN values, so Settings → Profile can edit them.
    phone: str = ""
    postal_address: str = ""
    # Country + currency (wave 3): the caller's own values — the
    # settings chooser edits them and money surfaces format by the
    # currency.
    country: str = ""
    currency: str = "USD"
    locale: str = ""
    # Community catalog contribution (wave 4) — the caller's own
    # switch state for Settings -> Sharing.
    catalog_contribute: bool = True
    # Appearance (owner ruling, 2026-10-25) — the caller's own
    # saved look; each field is None until the account first
    # saves an appearance (all three None = never saved, and
    # the client keeps its defaults). Only ever the caller's
    # own values, like every field above.
    appearance_mode: str | None = None
    appearance_accent: str | None = None
    # Per-mode accent (owner order, 2026-11-08): the caller's
    # LIGHT-mode pick; None until picked in light mode.
    appearance_accent_light: str | None = None
    appearance_theme: str | None = None
    # Wizard defaults (Wizard Phase 1, 2026-10-25) — the caller's
    # own Add-wizard setup document; None until the account first
    # saves wizard defaults. Only ever the caller's own value.
    wizard_defaults: dict | None = None
    # Rail pin (widget options Wave 1, 2026-11-02) — the caller's
    # own menu-pin choice; None until the account first sets it
    # (None reads as unpinned). Only ever the caller's own value.
    rail_pinned: bool | None = None
    created_at: datetime


# -- consent sharing (sharing_catalog owns the vocabulary) -----------------
#
# A mechanic shares their tool list with the shop group and/or the
# insurance group: per group they pick the OPTIONAL fields that group
# may see (the locked identity fields always go) and the items.
# These shapes serve Settings → Sharing and the recipient preview.

# Groups a tool list can be shared WITH (sharing_catalog.RECIPIENT_GROUPS).
ShareRecipientGroup = Literal["shop_company", "insurance"]

# The toggleable fields (sharing_catalog.OPTIONAL_FIELDS). The locked
# identity fields are deliberately NOT valid here — they always go
# when an item is shared, so they are never part of a saved config.
ShareableField = Literal[
    "category",
    "location",
    "purchase_price",
    "purchase_date",
    "msrp",
    "replacement_cost",
    "notes",
    "photos",
    "documents",
    "custom_fields",
]


class ShareConfigUpdate(BaseModel):
    """Body of PUT /sharing/{group}: the group's on/off flag and the
    optional fields that group may see."""

    enabled: bool
    fields: list[ShareableField] = []


class ShareSetChoice(BaseModel):
    """One set's addon choice in a sharing write/read: the stored
    answer to "include the addon pieces too?" for a shared set."""

    tool_id: uuid.UUID
    include_addons: bool = False


class ShareItemsUpdate(BaseModel):
    """Body of PUT /sharing/{group}/items: the COMPLETE set of item
    ids shared with the group (wholesale replace — select-all sends
    every id, select-none sends empty lists), split by kind."""

    tool_ids: list[uuid.UUID] = []
    battery_ids: list[uuid.UUID] = []
    # Per-set addon choices for the sets among tool_ids.
    set_choices: list[ShareSetChoice] = []


class ShareItemRef(BaseModel):
    """One shared item reference: the kind + the id in that kind's
    table."""

    kind: str  # 'tool' | 'battery'
    id: uuid.UUID


# -- sharing rules (Package C) ----------------------------------------------------
#
# Rules alongside the per-item picks: a scope (category | location
# subtree | tag | all) resolved dynamically at read time
# (sharing.resolve_shared_items). The 'item' scope IS the picks in
# shared_items, so it never appears as a rule row.


class ShareRuleView(BaseModel):
    """One stored rule as Settings renders it, with its live
    label and the count of items it is actually sharing now."""

    id: uuid.UUID
    scope: str
    scope_value: str
    scope_ref_id: uuid.UUID | None = None
    scope_label: str
    include_addons: bool = False
    match_count: int = 0
    created_at: datetime


class ShareRuleCreate(BaseModel):
    """Body of POST /sharing/{group}/rules. Category rules carry
    their text in scope_value; location/tag rules carry the node's
    / tag's id in scope_ref_id (the server snapshots the label)."""

    scope: Literal["category", "location", "tag", "all"]
    scope_value: str = Field(default="", max_length=500)
    scope_ref_id: uuid.UUID | None = None
    include_addons: bool = False


class ShareRuleUpdate(BaseModel):
    """Body of PUT /sharing/{group}/rules/{id}: the include-addons
    answer (any scope) and, for category rules, the category text."""

    include_addons: bool | None = None
    scope_value: str | None = Field(default=None, max_length=500)


class ShareExclusionsUpdate(BaseModel):
    """Body of PUT /sharing/{group}/exclusions: the COMPLETE set of
    per-item withholdings for the group (wholesale replace, same
    contract as the picks)."""

    tool_ids: list[uuid.UUID] = []
    battery_ids: list[uuid.UUID] = []


class ShareTagOption(BaseModel):
    """One tag the rule editor can point at."""

    id: uuid.UUID
    name: str
    item_count: int = 0


class ShareLocationOption(BaseModel):
    """One location-tree node the rule editor can point at (the
    whole serialized tree node — extra keys are ignored)."""

    id: uuid.UUID
    name: str
    path: str
    subtree_item_count: int = 0


class ShareGroupState(BaseModel):
    """One recipient group's sharing setup as Settings renders it."""

    recipient_group: str
    enabled: bool
    # Chosen optional fields, catalog order. A group that was never
    # configured reports the catalog defaults with enabled=False.
    fields: list[str]
    shared_tool_ids: list[uuid.UUID]
    shared_battery_ids: list[uuid.UUID] = []
    shared_items: list[ShareItemRef] = []
    # Stored per-set addon choices (see sharing.set_shared_items).
    set_choices: list[ShareSetChoice] = []
    # Package C: the group's rules, its per-item exclusions, and
    # the set that resolves as shared right now.
    rules: list[ShareRuleView] = []
    excluded_items: list[ShareItemRef] = []
    resolved_items: list[ShareItemRef] = []
    resolved_count: int = 0


class ShareItemSummary(BaseModel):
    """One of the owner's items (tool or battery), with the groups
    it is shared with. `kind` marks which — 'tool' for every item
    that existed before batteries."""

    id: uuid.UUID
    kind: str = "tool"
    name: str
    brand: str
    model: str
    serial_number: str
    # Sets render the addon-choice prompt in the picker.
    is_set: bool = False
    shared_with: list[str]


class SharingOverview(BaseModel):
    """GET /sharing: both groups' configs + the owner's items with
    per-group shared flags — everything the Settings page needs in
    one call."""

    groups: list[ShareGroupState]
    items: list[ShareItemSummary]
    # Package C: the rule editor's vocab — the owner's own
    # categories, tags, and location tree to point rules at.
    categories: list[str] = []
    tags: list[ShareTagOption] = []
    locations: list[ShareLocationOption] = []


# -- peer sharing (peer_sharing.py owns the logic) -------------------------
#
# A person shares their tool LIST with specific people (crew-mates),
# who browse and search it for borrowing. The item payload is fixed
# and minimal; these shapes are only the grant bookkeeping around it.


class PeerInviteRequest(BaseModel):
    """Body of POST /sharing/peer/invite: name the person ONE way —
    their account number (TV-…) or their email. Exactly one."""

    account_number: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def exactly_one_target(self):
        has_number = bool(self.account_number and self.account_number.strip())
        has_email = self.email is not None
        if has_number == has_email:
            raise ValueError("Invite by account number or by email — not both.")
        return self


class PeerPerson(BaseModel):
    """The only identity the peer surfaces ever show about a person."""

    id: uuid.UUID
    name: str
    account_number: str


class PeerOutgoingGrant(BaseModel):
    """A grant as its owner sees it. `viewer` is None while an EMAIL
    invite is still pending — by design, even for the owner, so the
    flow can't reveal whether the address has an account."""

    id: uuid.UUID
    status: str
    created_at: datetime
    responded_at: datetime | None = None
    viewer: PeerPerson | None = None
    invited_email: str | None = None


class PeerIncomingGrant(BaseModel):
    """A grant as its viewer sees it: who is sharing with me."""

    id: uuid.UUID
    status: str
    created_at: datetime
    responded_at: datetime | None = None
    owner: PeerPerson


class PeerToolIdentity(BaseModel):
    """One of the owner's own tools (identity fields only) — the
    exclusions picker's rows."""

    id: uuid.UUID
    name: str
    brand: str
    model: str
    serial_number: str
    # Sets carry the addon-choice toggle in the peer settings.
    is_set: bool = False


class PeerSetChoiceView(BaseModel):
    """One of my sets with its effective peer addon choice."""

    tool_id: uuid.UUID
    name: str = ""
    include_addons: bool = True


class PeerSetChoiceUpdate(BaseModel):
    """Body of PUT /sharing/peer/set-choices: store the addon
    choice for one of my sets."""

    tool_id: uuid.UUID
    include_addons: bool


class PeerExclusionRuleView(BaseModel):
    """One peer withholding rule (Package C): a category / location
    subtree / tag whose items never reach the crew list, with how
    many items it is withholding right now."""

    id: uuid.UUID
    scope: str
    scope_value: str
    scope_ref_id: uuid.UUID | None = None
    scope_label: str
    match_count: int = 0
    created_at: datetime


class PeerExclusionRuleCreate(BaseModel):
    """Body of POST /sharing/peer/exclusion-rules. No 'all' scope —
    withholding everything is what revoking the grant is for."""

    scope: Literal["category", "location", "tag"]
    scope_value: str = Field(default="", max_length=500)
    scope_ref_id: uuid.UUID | None = None


class PeerOverview(BaseModel):
    """GET /sharing/peer: my grants, grants to me, invites awaiting
    my decision, my exclusions, and my items for the picker (tools
    and batteries — batteries are peer-visible assets too)."""

    sharing_with: list[PeerOutgoingGrant]
    shared_with_me: list[PeerIncomingGrant]
    pending_for_me: list[PeerIncomingGrant]
    excluded_tool_ids: list[uuid.UUID]
    excluded_battery_ids: list[uuid.UUID] = []
    my_tools: list[PeerToolIdentity]
    # Same identity shape as my_tools — the picker renders one list.
    my_batteries: list[PeerToolIdentity] = []
    # My sets with their effective "include addon pieces?" choice.
    set_choices: list[PeerSetChoiceView] = []
    # Package C: scope-level withholding rules + the vocab their
    # editor points at (same option shapes as the tier editor).
    exclusion_rules: list[PeerExclusionRuleView] = []
    categories: list[str] = []
    tags: list[ShareTagOption] = []
    locations: list[ShareLocationOption] = []


class PeerExclusionsUpdate(BaseModel):
    """Body of PUT /sharing/peer/exclusions: the COMPLETE set of
    items withheld from peer viewers (wholesale replace), split
    by kind."""

    tool_ids: list[uuid.UUID] = []
    battery_ids: list[uuid.UUID] = []


class PeerExclusionsResponse(BaseModel):
    excluded_tool_ids: list[uuid.UUID]
    excluded_battery_ids: list[uuid.UUID] = []


class NotificationPublic(BaseModel):
    """One inbox row as the client renders it. `text` is the
    one-liner the header ticker consumes (it keys on id + text);
    `tone` maps to the ticker dot (null = accent default)."""

    id: uuid.UUID
    kind: str
    title: str
    body: str
    text: str
    tone: str | None = None
    data: dict = {}
    # Click-through destination (owner spec 2026-10-25), resolved
    # server-side by inbox_links; null only for a kind with no
    # destination (the completeness test keeps that set empty).
    link: str | None = None
    created_at: datetime
    read_at: datetime | None = None
    read: bool


class ReadAllResponse(BaseModel):
    updated: int


# -- my insurance profile (Package C) --------------------------------------
#
# The user's own insurer + agent, kept in Settings → My Insurance
# and consumed by the claims flow (prefill + agent snapshot).


# -- per-category data removal (audit A11) ---------------------------------


class DataRemovalCategoryView(BaseModel):
    key: str
    label: str
    count: int
    note: str
    blocked_reason: str | None = None


class DataRemovalRequest(BaseModel):
    category: str = Field(max_length=40)
    # Typed confirmation: the category key itself, typed back.
    confirmation: str = Field(max_length=40)


class DataRemovalResult(BaseModel):
    category: str
    removed: dict[str, int]


class InsuranceProfileView(BaseModel):
    """The profile as Settings renders it. `has_profile` is False
    when the user has never saved one — the fields then read as
    empty strings and the claim form simply doesn't pre-fill."""

    has_profile: bool = False
    insurer_company: str = ""
    # Wave 3: the directory link behind insurer_company (None =
    # free text only) + the directory company's current name, so
    # the form can show what the link points at.
    insurer_company_id: uuid.UUID | None = None
    insurer_company_name: str = ""
    agent_name: str = ""
    agent_phone: str = ""
    agent_email: str = ""
    policy_number: str = ""
    notes: str = ""
    # Policy depth (audit A9): the owner's own policy facts.
    # Money is cents; None = not declared.
    policy_type: str = ""
    deductible_cents: int | None = None
    coverage_limit_cents: int | None = None
    valuation_basis: str = ""
    business_sub_limit_cents: int | None = None
    how_to_file: str = ""
    updated_at: datetime | None = None


class InsuranceProfileUpdate(BaseModel):
    """Body of PUT /insurance: the COMPLETE profile (the settings
    form edits the whole record at once)."""

    insurer_company: str = Field(default="", max_length=300)
    # Wave 3: pick-from-directory. Sending a company id fills
    # insurer_company from the directory (the service resolves
    # it); sending null unlinks while the typed name stays.
    insurer_company_id: uuid.UUID | None = None
    agent_name: str = Field(default="", max_length=300)
    agent_phone: str = Field(default="", max_length=60)
    agent_email: str = Field(default="", max_length=320)
    policy_number: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=20000)
    policy_type: str = Field(default="", max_length=40)
    deductible_cents: int | None = Field(default=None, ge=0)
    coverage_limit_cents: int | None = Field(default=None, ge=0)
    valuation_basis: str = Field(default="", max_length=10)
    business_sub_limit_cents: int | None = Field(default=None, ge=0)
    how_to_file: str = Field(default="", max_length=20000)


# -- shop crews (wave 3) ---------------------------------------------------


class CrewInviteWrite(BaseModel):
    """One crew invite: by email OR by exact account number
    (exactly one — the route refuses a body with both/neither).
    role_label is the shop's own free text."""

    email: str | None = Field(default=None, max_length=320)
    account_number: str | None = Field(default=None, max_length=16)
    role_label: str = Field(default="", max_length=120)


class CrewMembershipView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shop_user_id: uuid.UUID
    shop_name: str = ""
    employee_user_id: uuid.UUID | None = None
    employee_name: str = ""
    employee_email: str = ""
    employee_account_number: str = ""
    invite_email: str = ""
    role_label: str = ""
    status: str
    invited_at: datetime
    accepted_at: datetime | None = None
    left_at: datetime | None = None
    grace_days_left: int | None = None


class CrewBracketView(BaseModel):
    plan_key: str
    bracket_key: str
    up_to_employees: int | None = None
    label: str


class CrewSummaryView(BaseModel):
    active_count: int
    invited_count: int
    bracket: CrewBracketView | None = None
    bracket_note: str = ""


class CrewMemberToolsView(BaseModel):
    """The shop's READ-ONLY window into one crew member's list
    (claims-ownership lane, 2026-11-07): the member's own
    shop-group sharing projection, verbatim — items are the
    sharing payload dicts (identity + the fields the member
    chose to share), so the shape is the projection's, not a
    second vocabulary."""

    member_user_id: uuid.UUID
    member_name: str = ""
    member_account_number: str = ""
    member_currency: str = "USD"
    sharing_enabled: bool
    items: list[dict] = []


class CrewRespondWrite(BaseModel):
    accept: bool


# -- insurers (wave 3) -----------------------------------------------------


class InsurerCompanyWrite(BaseModel):
    """Operator write for one directory insurer. phones ride as
    [{label, number}] — the dealer directory's shape."""

    name: str = Field(min_length=1, max_length=300)
    website: str = Field(default="", max_length=500)
    phones: list[dict] = Field(default_factory=list)
    address: str = Field(default="", max_length=5000)
    notes: str = Field(default="", max_length=20000)


class InsurerCompanyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website: str = ""
    phones: list = []
    address: str = ""
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class InsurerAffiliationWrite(BaseModel):
    company_id: uuid.UUID
    role_at_company: str = Field(default="", max_length=200)


class InsurerAffiliationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str = ""
    role_at_company: str = ""
    verified: bool = False
    created_at: datetime


class InsurerAffiliationAdminView(InsurerAffiliationView):
    user_id: uuid.UUID
    user_name: str = ""
    user_email: str = ""
    user_account_number: str = ""
    verified_at: datetime | None = None


class InsurerVerifyWrite(BaseModel):
    verified: bool


class PolicyholderView(BaseModel):
    """One policyholder in the verified insurer's view: identity +
    the item count their insurance-group sharing preview carries.
    The preview itself rides the existing sharing machinery (the
    route serves it through core.sharing) — this row is only the
    directory of who shares with the insurance group at all."""

    user_id: uuid.UUID
    name: str
    account_number: str
    item_count: int


# -- module control (module doctrine, owner 2026-10-18) ---------------------


class ModuleNav(BaseModel):
    """The nav entry a feature module contributes when effective."""

    label: str
    path: str
    order: int


class EffectiveModule(BaseModel):
    """One entry of GET /api/core/my-modules: a feature module the
    caller can use right now, with everything the shell needs to
    render it (nav entry, home tile)."""

    id: str
    name: str
    description: str
    provides: list[str]
    depends_on: list[str]
    nav: ModuleNav | None = None


class AdminModule(BaseModel):
    """One row of GET /api/admin/modules: the module's manifest, both
    switch layers, and its dependency health."""

    id: str
    name: str
    version: str
    description: str
    provides: list[str]
    depends_on: list[str]
    default_groups: list[str]
    nav: ModuleNav | None = None
    globally_enabled: bool
    groups: dict[str, bool]
    # Per-tier switches (2026-10-31): normal | moderator |
    # moderator_admin | beta — the staged-rollout layer.
    tiers: dict[str, bool] = {}
    dependency_status: str  # "ok" | "blocked by <dep>" | graph reason


class ModuleToggleRequest(BaseModel):
    """Body of the operator PUTs (global switch and per-group cell)."""

    enabled: bool


class ModulePref(BaseModel):
    """One entry of GET /api/core/my-module-prefs: a feature module
    the caller's groups entitle, with the caller's own switch state
    on it. `visible` is False when the module is switched off or a
    dependency the user switched off blocks it (`blocked_by`)."""

    id: str
    name: str
    label: str
    description: str
    nav: ModuleNav | None = None
    switchable: bool
    user_enabled: bool
    visible: bool
    blocked_by: str | None = None


class NotificationChannelPrefView(BaseModel):
    """One category's effective channel states — the Settings ->
    Notifications payload (owner item 12, 2026-10-24). The bell
    is the always-on base layer and is not a field; `email_enabled`
    is the EFFECTIVE value (the user's stored flip when one
    exists, else the category default). The view is
    channel-shaped in spirit: a future channel lands as a
    sibling field, not a new endpoint."""

    category: str
    email_enabled: bool


class NotificationChannelPrefUpdate(BaseModel):
    """Body of PUT /api/core/me/notification-preferences. Only
    "email" is a live channel today — push/SMS are modeled in
    the store but have no sender, so naming one is a 422 until
    it exists."""

    category: str = Field(min_length=1, max_length=50)
    channel: str = Field(pattern=r"^email$")
    enabled: bool


class ModuleOption(BaseModel):
    """One entry of GET /api/core/module-options: a feature module
    a group set entitles, for the public signup preview."""

    id: str
    name: str
    label: str
    description: str
    nav: ModuleNav | None = None
    switchable: bool


# -- history & restore (user audit trail, 2026-10-19) -------------------------


class RestoreMarkerView(BaseModel):
    id: uuid.UUID
    label: str
    kind: str  # baseline | daily | manual | pre_bulk | pre_restore
    journal_seq: int
    created_at: datetime


class MarkerCreate(BaseModel):
    label: str = Field(default="", max_length=200)


class JournalEntryView(BaseModel):
    id: uuid.UUID
    seq: int
    occurred_at: datetime
    module: str
    entity_type: str
    action: str  # create | update | delete | restore
    label: str
    restorable: bool
    # Who made the change, from the reader's point of view: the
    # account owner ("you" / "owner" on the admin surface), another
    # person (a peer/borrower acting on a shared record), an
    # operator, or the system (jobs).
    actor: str


class HistoryEntriesPage(BaseModel):
    entries: list[JournalEntryView]
    total: int


class RestorePreviewView(BaseModel):
    marker_id: uuid.UUID
    changes_to_undo: int
    shared_not_changed: int


class RestoreRequest(BaseModel):
    marker_id: uuid.UUID


class RestoreResultView(BaseModel):
    restored: int
    not_changed: int
    pre_restore_marker_id: uuid.UUID
    marker_id: uuid.UUID


class RoadmapEntryView(BaseModel):
    id: str
    title: str
    note: str = ""
    status: str
    sort_order: int = 0


class RoadmapEntryWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=4000)
    status: str = "planned"
    sort_order: int = 0
