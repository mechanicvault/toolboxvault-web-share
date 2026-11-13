"""Core module service: the public interface other modules use.

SERVICE INTERFACE (stable; bump manifest version on change):
  - get_user_by_id(db, user_id) -> User | None
  - get_user_by_email(db, email) -> User | None
  - get_user_by_account_number(db, account_number) -> User | None
    (peer sharing invites people by their TV-… number)
  - create_user(db, email, name, password, account_types, referred_by_id=None)
    -> User (password login enabled; group set fixed at signup — a forced
    pick, never empty; referred_by_id records the referral capture)
  - list_referred_users(db, user_id) -> list[User] (accounts this user
    referred; billing's referral accounting consumes this)
  - list_sessions(db, user, current_refresh_token) -> list[dict] (the
    Settings "Your sessions" list: one entry per live session chain)
  - revoke_session(db, user, token_id) -> bool (sign out one session)
  - revoke_other_sessions(db, user, keep_refresh_token) -> int
  - delete_account(db, user) -> None (self-serve permanent deletion:
    the account and everything it owns, across every module)
  - create_oauth_user(db, email, name) -> User (verified; no usable password;
    password_login_enabled=False; group set EMPTY — the app prompts)
  - set_account_types(db, user, account_types) -> User (set or replace the
    group set; the account number NEVER changes — it is final at creation)
  - get_page_layout(db, user_id, page_key) -> list[dict] | None (the user's
    stored page layout; None = never customized, client uses defaults)
  - save_page_layout(db, user_id, page_key, blocks) -> list[dict] (stores the
    layout deduped by key and capped; returns what was stored)
  - resolve_oauth_user(db, email, name) -> User (find-or-create by email)
  - authenticate(db, email, password) -> User | None
  - change_password(db, user, current_password, new_password,
                    keep_refresh_token) -> bool (False = wrong current)
  - issue_session(db, user) -> (access_token, refresh_token)
  - issue_refresh_token(db, user) -> str (plain token; hash is stored)
  - rotate_refresh_token(db, plain) -> (User, new plain token) | None
  - revoke_refresh_token(db, plain) -> None (logout; idempotent)
  - start_email_verification(db, user) -> None (mints token, sends email)
  - verify_email(db, plain_token) -> bool
  - request_password_reset(db, email) -> None (silent by design: the
    caller answers identically whether or not an account exists;
    the email goes out only for a live, unbanned account)
  - reset_password(db, plain_token, new_password) -> str (result
    code: ok | invalid | used | expired | blocked; on ok the
    password is set, password login enabled, ALL sessions revoked)
  - request_email_change(db, user, new_email, current_password)
    -> str (ok | wrong_password | same | taken | banned; on ok a
    confirmation token is minted and the link sent to the NEW
    address — the address itself does not move yet)
  - pending_email_change(db, user) -> EmailChangeToken | None (the
    pending state Settings displays)
  - cancel_email_change(db, user) -> bool (voids the pending change)
  - confirm_email_change(db, plain_token, keep_refresh_token=None)
    -> (str, User | None) (on ok: email swapped, verified, other
    sessions revoked, audit row written, notice sent to the OLD
    address)
  - search_users(db, query, limit=, offset=) -> (list[User], total)
    (the Admin → Users directory: name/email/account-number search)
  - set_user_operator(db, user, flag) / set_user_role(db, user, role) /
    set_user_active(db, user, active) -> User (operator actions;
    deactivation revokes every live session)
  - get_ban(db, email) / is_email_banned(db, email) -> the ban check
    every door consults (signup, login, OAuth resolve, refresh)
  - ban_email(db, email, reason=, banned_by=) -> BannedEmail (also
    revokes the matching account's live sessions)
  - unban_email(db, email) -> bool; list_bans(db) -> list[BannedEmail]

Internal helpers (account-number generation) are private to this module.
"""

import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import i18n, notifications
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.modules.core import journal, models, tiers
from app.modules.core.account_types import ACCOUNT_TYPE_SEGMENTS, canonical_order


def get_user_by_id(db: Session, user_id: str | uuid.UUID) -> models.User | None:
    return db.get(models.User, uuid.UUID(str(user_id)))


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.scalars(
        select(models.User).where(models.User.email == email.lower())
    ).first()


def get_user_by_account_number(
    db: Session, account_number: str
) -> models.User | None:
    """Look an account up by its human-readable number (TV-…).

    Account numbers are the shareable identifier: a user reads theirs
    off their settings page and a coworker invites them by it (peer
    sharing). Input is normalized (trimmed, uppercased) — the stored
    form is canonical uppercase.
    """
    normalized = account_number.strip().upper()
    if not normalized:
        return None
    return db.scalars(
        select(models.User).where(models.User.account_number == normalized)
    ).first()


def format_account_number(digits: str, account_types: list[str]) -> str:
    """THE account-number format — the one helper that owns it.

    `digits` is the zero-padded sequence part ("000123"). With no
    groups chosen yet the number is plain: "TV-000123". With a group
    set it carries the segment — the letters of ALL the account's
    groups in canonical order: "TV-M-000123" (mechanic only),
    "TV-MD-000123" (mechanic + dealer), "TV-SDI-000123", …

    Creation-time ONLY (sweep fix 10-F12): this formats the number
    an account is BORN with. Nothing re-formats a live account's
    number afterwards — set_account_types leaves it untouched.
    """
    segment = "".join(
        ACCOUNT_TYPE_SEGMENTS[t] for t in canonical_order(account_types)
    )
    if not segment:
        return f"TV-{digits}"
    return f"TV-{segment}-{digits}"


def _account_number_digits(account_number: str) -> str:
    """The sequence digits of an existing account number, whatever
    segment it currently carries ("TV-MD-000123" -> "000123")."""
    return account_number.rsplit("-", 1)[-1]


def _next_account_number(db: Session) -> str:
    """Allocate the next TV-000001 account number.

    Uses the account_number_seq Postgres sequence: nextval() is atomic, so
    concurrent signups can never collide. Numbers may skip on rollback
    (gap-tolerant); the UNIQUE constraint on users.account_number is the
    backstop. The sequence itself is created by the Alembic migration (and by
    Base.metadata for create_all-based dev setups).

    Returns the PLAIN number; callers with a group set segment it via
    format_account_number before storing.
    """
    seq_value: int = db.scalar(select(func.nextval("account_number_seq")))
    return format_account_number(f"{seq_value:06d}", [])


def _create_user(
    db: Session,
    email: str,
    name: str,
    password_hash: str,
    *,
    email_verified: bool,
    password_login_enabled: bool,
    account_types: list[str],
    referred_by_id: uuid.UUID | None = None,
    country: str | None = None,
    currency: str | None = None,
    locale: str | None = None,
    tier: str = "normal",
) -> models.User:
    """The one account-creation path: every way an account comes into
    existence (password signup, social login) goes through here, so the
    account number and field defaults can never drift between paths.

    `tier` is the rung the account is born at (open signup,
    2026-11-09): both creation doors resolve it through
    teaser.signup_tier — "downloads" for a no-code signup while
    the teaser gate is up, "normal" otherwise. An unknown value
    falls back to normal rather than failing a signup."""
    from app.modules.core import money

    digits = _account_number_digits(_next_account_number(db))
    clean_country = money.normalize_country(country)
    # Interface language (signup basics, owner 2026-10-22): only a
    # shipped locale sticks; anything else stays unset ("") and the
    # resolution falls back to country, then browser, then English.
    clean_locale = locale if locale in ("en", "es") else ""
    # Currency: the explicit pick wins; else it defaults from the
    # country; else USD (money.normalize_currency's fallback).
    clean_currency = (
        money.normalize_currency(currency)
        if currency
        else money.currency_for_country(clean_country)
    )
    user = models.User(
        account_number=format_account_number(digits, account_types),
        account_types=canonical_order(account_types),
        email=email.lower(),
        name=name,
        password_hash=password_hash,
        email_verified=email_verified,
        password_login_enabled=password_login_enabled,
        referred_by_id=referred_by_id,
        country=clean_country,
        currency=clean_currency,
        locale=clean_locale,
        tier=tier if tier in tiers.TIERS else "normal",
        role=tiers.role_for_tier(tier if tier in tiers.TIERS else "normal"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # Preinstalled starter categories (owner spec 2026-10-25):
    # every account starts with Batteries / Hand Tools / Power
    # Tools / Pneumatic Tools, starred. Seeded here, on the ONE
    # creation path, so password and social signups alike get
    # them — and seeded with the journal STOOD DOWN, before the
    # baseline marker below: the starters are part of the
    # account's initial state (like the baseline itself), not
    # activity in it. No journal entries means the baseline
    # watermark stays 0 by construction, a restore can never
    # unwind them, the daily-marker run never counts them, and
    # a new account's history opens clean. A seeding hiccup
    # must never fail an account creation (the same philosophy
    # as the verification email at signup): the seed is
    # idempotent and can be re-run for the account.
    try:
        from app.modules.inventory import service as inventory_service

        with journal.suspended():
            inventory_service.ensure_starter_categories(
                db, user.id, user.locale or None
            )
    except Exception:  # noqa: BLE001 — account creation outranks the seed
        import logging

        logging.getLogger(__name__).exception(
            "Could not seed starter categories for user %s", user.id
        )
    # Audit trail (2026-10-19): every account starts with a
    # baseline restore marker — the point "before anything
    # happened" that the whole journal unwinds to. Its journal
    # watermark is 0 by construction (the new account has no
    # entries yet), so this is always safe here.
    journal.create_baseline(db, user.id)
    # Onboarding (owner design 2026-10-31, built 2026-11-07):
    # every account born from now on carries the wizard-flow
    # marker, written here on the ONE creation path so password
    # and social signups alike land in the setup wizard rather
    # than the legacy completion gate. Accounts that predate the
    # wizard never pass through here again, so they never get the
    # marker and their behavior is untouched. A marker hiccup
    # must never fail an account creation (the starter-category
    # philosophy): the account simply reads as legacy until a
    # later write lands it.
    try:
        from app.modules.core import onboarding

        onboarding.mark_fresh(db, user)
    except Exception:  # noqa: BLE001 — account creation outranks the marker
        import logging

        logging.getLogger(__name__).exception(
            "Could not mark onboarding flow for user %s", user.id
        )
    return user


def create_user(
    db: Session,
    email: str,
    name: str,
    password: str,
    account_types: list[str],
    referred_by_id: uuid.UUID | None = None,
    country: str | None = None,
    currency: str | None = None,
    locale: str | None = None,
    tier: str = "normal",
) -> models.User:
    """Email signup. Since the onboarding build (2026-11-07) the
    group set is NO longer a forced pick: signup is just an
    account, the set starts empty (plain account number), and the
    setup wizard's step 1 makes the pick — the number minted here
    is final and never changes when the pick lands (sweep fix
    10-F12). A client that still sends a set gets it honored
    exactly as before — its number is segmented at birth and
    stays that way. `tier` is the birth rung the door
    resolved (teaser.signup_tier): "downloads" for a no-code
    signup under the teaser gate, "normal" otherwise."""
    return _create_user(
        db,
        email,
        name,
        hash_password(password),
        email_verified=False,
        password_login_enabled=True,
        account_types=account_types,
        referred_by_id=referred_by_id,
        country=country,
        currency=currency,
        locale=locale,
        tier=tier,
    )


def update_profile(
    db: Session, user: models.User, fields: dict
) -> models.User:
    """PATCH /me's write path (2026-10-19): apply exactly the
    profile fields the caller sent — the display name plus the
    community contact preferences (public area label, publishable
    phone, show-phone opt-in). Keys outside the whitelist are
    ignored by construction: the route passes model_fields_set-
    filtered input and this function reads only its own keys."""
    if "name" in fields and fields["name"] is not None:
        user.name = str(fields["name"]).strip()
    if "public_area_label" in fields and fields["public_area_label"] is not None:
        user.public_area_label = str(fields["public_area_label"]).strip()
    if "contact_phone" in fields and fields["contact_phone"] is not None:
        user.contact_phone = str(fields["contact_phone"]).strip()
    if "show_phone" in fields and fields["show_phone"] is not None:
        user.show_phone = bool(fields["show_phone"])
    if (
        "silence_claim_readiness_nudges" in fields
        and fields["silence_claim_readiness_nudges"] is not None
    ):
        user.silence_claim_readiness_nudges = bool(
            fields["silence_claim_readiness_nudges"]
        )
    # Community catalog contribution (wave 4): the Settings ->
    # Sharing switch; read-time aggregation makes it immediate.
    if "catalog_contribute" in fields and fields["catalog_contribute"] is not None:
        user.catalog_contribute = bool(fields["catalog_contribute"])
    # Appearance (owner ruling, 2026-10-25): the account-held
    # look. Values arrive schema-validated (mode is dark|light,
    # accent a hex color, theme a bounded id); stored verbatim —
    # the client resolves theme ids and falls back per-field, so
    # no normalization belongs here. A field sent as None is
    # "not part of this update", like every field above — there
    # is no clear-back-to-never-saved gesture.
    if "appearance_mode" in fields and fields["appearance_mode"] is not None:
        user.appearance_mode = str(fields["appearance_mode"])
    if "appearance_accent" in fields and fields["appearance_accent"] is not None:
        user.appearance_accent = str(fields["appearance_accent"]).strip()
    if (
        "appearance_accent_light" in fields
        and fields["appearance_accent_light"] is not None
    ):
        user.appearance_accent_light = str(
            fields["appearance_accent_light"]
        ).strip()
    if "appearance_theme" in fields and fields["appearance_theme"] is not None:
        user.appearance_theme = str(fields["appearance_theme"]).strip()
    # Wizard defaults (Wizard Phase 1, 2026-10-25): the account-
    # held Add-wizard setup document. The schema validated its
    # shape and size at the door; stored verbatim — the client
    # resolves unknown section keys, exactly like the appearance
    # theme id. Sent as None = not part of this update; an empty
    # document ({}) is a real save (the bare setup, explicit).
    if "wizard_defaults" in fields and fields["wizard_defaults"] is not None:
        user.wizard_defaults = fields["wizard_defaults"]
    # Rail pin (widget options Wave 1, 2026-11-02): the
    # account-held menu-pin choice. Sent as None = not part of
    # this update; True/False both store — False is the explicit
    # unpin (the column's NULL is only ever "never set").
    if "rail_pinned" in fields and fields["rail_pinned"] is not None:
        user.rail_pinned = bool(fields["rail_pinned"])
    # Interface language (audit A17): only the shipped locales
    # stick; anything else normalizes to unset ("").
    if "locale" in fields and fields["locale"] is not None:
        user.locale = fields["locale"] if fields["locale"] in ("en", "es") else ""
    # Report contact details (reports alignment, 2026-10-19): the
    # Prepared-For phone + postal address. The address keeps its
    # line breaks (it prints as a block); both strip the edges.
    if "phone" in fields and fields["phone"] is not None:
        user.phone = str(fields["phone"]).strip()
    if "postal_address" in fields and fields["postal_address"] is not None:
        user.postal_address = str(fields["postal_address"]).strip()
    # Country + currency (wave 3): a country sent WITHOUT a
    # currency re-defaults the currency from the new country; an
    # explicit currency always wins. Unknown codes normalize away
    # (country → unset, currency → unchanged-by-fallback is wrong
    # here, so an unrecognized currency is simply not applied).
    if "country" in fields or "currency" in fields:
        from app.modules.core import money

        if "country" in fields and fields["country"] is not None:
            user.country = money.normalize_country(fields["country"])
        if "currency" in fields and fields["currency"] is not None:
            candidate = str(fields["currency"]).strip().upper()
            if candidate in money.CURRENCIES:
                user.currency = candidate
        elif "country" in fields and fields["country"] is not None:
            user.currency = money.currency_for_country(user.country)
    db.commit()
    db.refresh(user)
    return user


def list_referred_users(db: Session, user_id: str | uuid.UUID) -> list[models.User]:
    """Accounts that named this user as their referrer at signup.
    Billing's referral accounting (5 currently-paying referrals =
    1 free month) consumes this through the service interface."""
    return list(
        db.scalars(
            select(models.User).where(
                models.User.referred_by_id == uuid.UUID(str(user_id))
            )
        ).all()
    )


def set_account_types(
    db: Session, user: models.User, account_types: list[str]
) -> models.User:
    """Set or replace `user`'s group set — the one-time first pick and
    later self-serve changes in Settings both land here.

    The set is stored in canonical order. The account number is
    NEVER touched here (sweep fix 10-F12): the number minted at
    creation is the number for the life of the account. Signup
    tells the user to keep it handy — it is how their shop or
    dealer identifies the account, and it rides referral codes
    and invites — so a later group pick must not rewrite it,
    letters or digits. (Before this fix the number was
    re-segmented to match the new set: TV-001007 became
    TV-M-001007 the moment the type was picked, breaking the
    number the user had just been told to keep.) An empty set is
    refused — an account must always belong to at least one group
    once it has picked (the schemas enforce this too; this is the
    service-level backstop).
    """
    chosen = canonical_order(account_types)
    if not chosen:
        raise ValueError("An account must belong to at least one group")
    user.account_types = chosen
    db.commit()
    db.refresh(user)
    return user


# -- page layouts -------------------------------------------------------------
#
# Per-user page arrangement (owner directive 2026-10-17: users choose
# which blocks appear on each page and in what order). The server is a
# dumb, safe store: block keys are opaque strings owned by the frontend
# page registries, so the only rules here are shape (enforced by the
# schemas), dedupe, and the cap.

MAX_LAYOUT_BLOCKS = 50

# Cap on one block entry's hidden-stat list (the overview registry
# holds a dozen stats today; the cap is headroom, not a target).
MAX_LAYOUT_HIDDEN_STATS = 100

# Caps for one block entry's settings bundle (widget options
# Wave 1, 2026-11-02): a widget's registry holds a handful of
# options today; the caps are headroom, not targets — and the
# sanitizer below enforces them field-by-field regardless of
# what the schema door already checked.
MAX_LAYOUT_SETTINGS_KEYS = 32
MAX_LAYOUT_SETTINGS_KEY_LEN = 64
MAX_LAYOUT_SETTINGS_STR_LEN = 200
MAX_LAYOUT_SETTINGS_LIST_ITEMS = 50
MAX_LAYOUT_SETTINGS_LIST_ITEM_LEN = 100


def _sanitize_block_settings(raw: dict) -> dict:
    """Field-by-field allowlist cleaning for a block's settings
    bundle (widget options Wave 1): keys are bounded strings;
    values are LEAF values only — booleans, finite numbers,
    bounded strings, or bounded deduped string lists. Nested
    documents, None, and anything else are dropped, never
    stored (absence is this store's unset state, like every
    other field here — and it keeps the bundle clear of the
    layout responses' exclude_none serialization), so the
    bundle stays a flat options document whatever a client
    sends. Returns the cleaned dict (possibly empty)."""
    clean: dict = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > MAX_LAYOUT_SETTINGS_KEY_LEN
        ):
            continue
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (int, float)):
            # NaN and the infinities are not values a client can
            # mean here — drop them rather than store a number
            # no JSON reader can round-trip.
            if math.isfinite(value):
                clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:MAX_LAYOUT_SETTINGS_STR_LEN]
        elif isinstance(value, list):
            items: list[str] = []
            for item in value:
                if isinstance(item, str) and item:
                    item = item[:MAX_LAYOUT_SETTINGS_LIST_ITEM_LEN]
                    if item not in items:
                        items.append(item)
                if len(items) >= MAX_LAYOUT_SETTINGS_LIST_ITEMS:
                    break
            clean[key] = items
        # Anything else (a nested dict, ...) is not a leaf
        # value: dropped by construction.
        if len(clean) >= MAX_LAYOUT_SETTINGS_KEYS:
            break
    return clean


def get_page_layout(
    db: Session, user_id: str | uuid.UUID, page_key: str
) -> list[dict] | None:
    """The user's stored blocks for `page_key`, or None when they have
    never saved a layout for it (the client renders page defaults)."""
    row = db.scalar(
        select(models.UserPageLayout).where(
            models.UserPageLayout.user_id == uuid.UUID(str(user_id)),
            models.UserPageLayout.page_key == page_key,
        )
    )
    if row is None:
        return None
    return list(row.blocks or [])


def save_page_layout(
    db: Session, user_id: str | uuid.UUID, page_key: str, blocks: list[dict]
) -> list[dict]:
    """Store `blocks` as the user's layout for `page_key` (wholesale
    replace). Duplicate keys collapse to their FIRST occurrence and the
    list is capped at MAX_LAYOUT_BLOCKS — a buggy or hostile client
    cannot grow the row without bound. Returns what was stored."""
    seen: set[str] = set()
    clean: list[dict] = []
    for block in blocks:
        key = block["key"]
        if key in seen:
            continue
        seen.add(key)
        entry: dict = {"key": key, "visible": bool(block.get("visible", True))}
        # Per-stat show/hide for the overview block (owner review
        # round 1): sanitized like everything else in this store —
        # strings only, deduped, capped — and only stored when the
        # user actually hid something, so untouched layouts keep
        # their original shape byte-for-byte.
        raw_stats = block.get("hidden_stats")
        if isinstance(raw_stats, list):
            stats: list[str] = []
            for stat in raw_stats:
                if isinstance(stat, str) and stat and stat not in stats:
                    stats.append(stat)
                if len(stats) >= MAX_LAYOUT_HIDDEN_STATS:
                    break
            if stats:
                entry["hidden_stats"] = stats
        # Per-stat display order (Home + Header program): same
        # sanitize contract as hidden_stats — strings only,
        # deduped, capped — and only stored when non-empty, so
        # untouched layouts keep their original shape.
        raw_order = block.get("order")
        if isinstance(raw_order, list):
            order: list[str] = []
            for item in raw_order:
                if isinstance(item, str) and item and item not in order:
                    order.append(item)
                if len(order) >= MAX_LAYOUT_HIDDEN_STATS:
                    break
            if order:
                entry["order"] = order
        # Home panel pseudo-entry extras (Phase C): same sanitize
        # contract — strings only, deduped, capped, stored only
        # when non-empty.
        for field in ("panel_hidden", "panel_order"):
            raw_panel = block.get(field)
            if isinstance(raw_panel, list):
                vals: list[str] = []
                for item in raw_panel:
                    if isinstance(item, str) and item and item not in vals:
                        vals.append(item)
                    if len(vals) >= MAX_LAYOUT_HIDDEN_STATS:
                        break
                if vals:
                    entry[field] = vals
        # Panel stat picks (Phase 3): same sanitizing, but this
        # field is a pick LIST — stored whenever the client sent
        # a list at all, EMPTY included (empty = the user removed
        # every row, a real choice; absent/None = never
        # customized, and the entry keeps its original shape).
        raw_picks = block.get("panel_stat_order")
        if isinstance(raw_picks, list):
            picks: list[str] = []
            for item in raw_picks:
                if isinstance(item, str) and item and item not in picks:
                    picks.append(item)
                if len(picks) >= MAX_LAYOUT_HIDDEN_STATS:
                    break
            entry["panel_stat_order"] = picks
        # Home grid width (widget options Wave 1): a closed pair
        # — anything else the client sent is a bug and drops, so
        # the block falls back to its registered default width.
        # Stored only when a valid value was actually sent, so
        # untouched layouts keep their original shape.
        raw_size = block.get("size")
        if raw_size in ("half", "full"):
            entry["size"] = raw_size
        # Per-widget options bundle (widget options Wave 1):
        # sanitized field-by-field like everything else in this
        # store, and only stored when something survived — an
        # all-junk bundle stores nothing at all.
        raw_settings = block.get("settings")
        if isinstance(raw_settings, dict):
            cleaned_settings = _sanitize_block_settings(raw_settings)
            if cleaned_settings:
                entry["settings"] = cleaned_settings
        clean.append(entry)
        if len(clean) >= MAX_LAYOUT_BLOCKS:
            break
    uid = uuid.UUID(str(user_id))
    row = db.scalar(
        select(models.UserPageLayout).where(
            models.UserPageLayout.user_id == uid,
            models.UserPageLayout.page_key == page_key,
        )
    )
    if row is None:
        row = models.UserPageLayout(user_id=uid, page_key=page_key, blocks=clean)
        db.add(row)
    else:
        row.blocks = clean
    db.commit()
    db.refresh(row)
    return list(row.blocks or [])


def create_oauth_user(
    db: Session, email: str, name: str, tier: str = "normal"
) -> models.User:
    """Create an account for a social-login identity.

    The provider has already verified the email, so the account starts
    verified. There is NO usable password: the stored hash is of random
    bytes nobody knows, so password login can never match — the user
    signs in with their provider. password_login_enabled=False records
    that (the hash alone can't say it); the user can set a real password
    later from Settings. The group set starts empty (see below).
    `tier` is the birth rung the door resolved (teaser.signup_tier) —
    a social signup is a signup, so it lands on the same rung an
    email signup from the same browser would.
    """
    unusable_hash = hash_password(secrets.token_urlsafe(64))
    return _create_user(
        db,
        email,
        name,
        unusable_hash,
        email_verified=True,
        password_login_enabled=False,
        # Social login can't ask for groups mid-redirect: the set
        # starts EMPTY and the app prompts once after first login.
        account_types=[],
        tier=tier,
    )


class EmailBannedError(ValueError):
    """Social sign-in attempted with a banned email (admin panel).

    Raised by resolve_oauth_user BEFORE any find-or-create, so a
    banned address can never slip in — or back in — via Google or
    Facebook. The OAuth routes turn it into the login page's banned
    notice."""


class AccountDeactivatedError(ValueError):
    """Social sign-in attempted for a deactivated account (admin
    panel soft-deactivation). The OAuth routes turn it into the
    login page's deactivated notice."""


def resolve_oauth_user(
    db: Session, email: str, name: str, tier: str = "normal"
) -> models.User:
    """Find-or-create the account for a provider-verified identity.

    The provider just proved the caller controls `email`, so an existing
    account with that address is theirs — this is also the claim path
    for users migrated from the old app — and the address counts as
    verified from now on. A new email gets a fresh social-login account
    at `tier` (the door's teaser.signup_tier reading; an EXISTING
    account's rung never moves here — a sign-in is not a creation).

    Bans and deactivation are enforced HERE, before the find-or-create,
    so the social door is exactly as closed as the password door.
    """
    if is_email_banned(db, email):
        raise EmailBannedError(f"{email} is banned")
    user = get_user_by_email(db, email)
    if user is not None:
        if not user.is_active:
            raise AccountDeactivatedError(f"{email} is deactivated")
        if not user.email_verified:
            user.email_verified = True
            db.commit()
        return user
    return create_oauth_user(db, email, name or email.split("@")[0], tier=tier)


def authenticate(db: Session, email: str, password: str) -> models.User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def change_password(
    db: Session,
    user: models.User,
    current_password: str | None,
    new_password: str,
    keep_refresh_token: str | None,
) -> bool:
    """Set `user`'s password. Returns False when a required current
    password is missing or doesn't verify (nothing changes).

    An account with password login enabled must prove knowledge of the
    current password. An OAuth-only account has none to prove — its
    authenticated session is the identity proof, and setting the first
    password enables password login for it.

    On success every OTHER refresh token is revoked (other devices and
    sessions must sign in again); the caller's own session, identified
    by `keep_refresh_token`, survives.
    """
    if user.password_login_enabled:
        if current_password is None or not verify_password(
            current_password, user.password_hash
        ):
            return False
    user.password_hash = hash_password(new_password)
    user.password_login_enabled = True
    stmt = update(models.RefreshToken).where(
        models.RefreshToken.user_id == user.id,
        models.RefreshToken.revoked_at.is_(None),
    )
    if keep_refresh_token:
        stmt = stmt.where(
            models.RefreshToken.token_hash != hash_opaque_token(keep_refresh_token)
        )
    db.execute(stmt.values(revoked_at=_now()))
    db.commit()
    return True


# -- sessions ----------------------------------------------------------------
def issue_session(
    db: Session, user: models.User, user_agent: str | None = None
) -> tuple[str, str]:
    """(access_token, refresh_token) for a freshly authenticated user.

    The single issuance path: password login and social login both mint
    sessions here, so token policy can never drift between them.
    """
    return create_access_token(str(user.id)), issue_refresh_token(
        db, user, user_agent=user_agent
    )


# -- refresh tokens --------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """Normalize a DB timestamp to tz-aware UTC (SQLite returns naive)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def issue_refresh_token(
    db: Session, user: models.User, user_agent: str | None = None
) -> str:
    """Mint a refresh token for `user`. Returns the PLAIN token (shown to
    the client once); only its hash is stored."""
    plain, token_hash = generate_opaque_token()
    db.add(
        models.RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            user_agent=(user_agent or "")[:500] or None,
            expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    db.commit()
    return plain


def _revoke_all_refresh_tokens(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(models.RefreshToken)
        .where(
            models.RefreshToken.user_id == user_id,
            models.RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )


def rotate_refresh_token(
    db: Session, plain: str
) -> tuple[models.User, str] | None:
    """Exchange a refresh token for a new one (rotation on every use).

    Returns (user, new plain token), or None if the presented token is
    unknown, expired, or revoked.

    A REVOKED token splits into two very different cases (deep audit
    F4-01):

    - It was ROTATED AWAY (`replaced_by_id` set): a token that should
      never be presented again came back — the classic theft/replay
      signal. The user's entire token family is revoked and the
      exchange fails.
    - It was revoked WITHOUT a replacement (`replaced_by_id` NULL):
      a deliberate, authenticated act ended it — logout, a
      Settings session revoke, "sign out other sessions", a password
      change, deactivation/ban. A stale tab or app retry presenting
      it is ordinary client behaviour, NOT theft: the exchange fails
      for this token alone and no other session is touched.
    """
    token = db.scalars(
        select(models.RefreshToken).where(
            models.RefreshToken.token_hash == hash_opaque_token(plain)
        )
    ).first()
    if token is None:
        return None
    if token.revoked_at is not None:
        if token.replaced_by_id is not None:
            # Rotated-away token replayed: theft response — the whole
            # family dies, including the legitimate newest token.
            _revoke_all_refresh_tokens(db, token.user_id)
            db.commit()
        # User-revoked token: plain failure, no side effects.
        return None
    if _aware(token.expires_at) <= _now():
        token.revoked_at = _now()
        db.commit()
        return None
    user = db.get(models.User, token.user_id)
    if user is None:
        return None
    if not user.is_active or is_email_banned(db, user.email):
        # Deactivated or banned since the session began: the whole
        # family dies here (deactivation/banning already revoked
        # every live token; this is the backstop for a token minted
        # in between). No new session is issued.
        _revoke_all_refresh_tokens(db, token.user_id)
        db.commit()
        return None
    new_plain, new_hash = generate_opaque_token()
    replacement = models.RefreshToken(
        user_id=user.id,
        token_hash=new_hash,
        # The session's device identity survives rotation.
        user_agent=token.user_agent,
        expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(replacement)
    db.flush()  # replacement.id must exist before the old token points at it
    token.revoked_at = _now()
    token.replaced_by_id = replacement.id
    db.commit()
    return user, new_plain


def revoke_refresh_token(db: Session, plain: str) -> None:
    """Logout: revoke the presented token if it exists. Idempotent and
    silent about unknown tokens (no oracle about which tokens exist)."""
    token = db.scalars(
        select(models.RefreshToken).where(
            models.RefreshToken.token_hash == hash_opaque_token(plain)
        )
    ).first()
    if token is not None and token.revoked_at is None:
        token.revoked_at = _now()
        db.commit()


# -- session management (Settings → Account & security) ----------------------
#
# A "session" is one refresh-token CHAIN: login mints a root token and
# every refresh rotates it (the old link is revoked, replaced_by_id
# points forward). So each live session has exactly ONE unrevoked,
# unexpired token — its head — and the chain behind it gives the
# session's true start time.


def list_sessions(
    db: Session, user: models.User, current_refresh_token: str | None
) -> list[dict]:
    """The user's live sessions, oldest first. `is_current` marks the
    session whose head matches the caller's own refresh token (the
    client sends it in a header — the same trust as a refresh call)."""
    tokens = list(
        db.scalars(
            select(models.RefreshToken).where(models.RefreshToken.user_id == user.id)
        ).all()
    )
    by_id = {t.id: t for t in tokens}
    parent_of = {
        t.replaced_by_id: t for t in tokens if t.replaced_by_id is not None
    }
    current_hash = (
        hash_opaque_token(current_refresh_token) if current_refresh_token else None
    )
    now = _now()
    sessions = []
    for token in tokens:
        if token.revoked_at is not None or _aware(token.expires_at) <= now:
            continue  # not a live head
        root = token
        seen = set()
        while root.id in parent_of and root.id not in seen:
            seen.add(root.id)
            root = parent_of[root.id]
        sessions.append(
            {
                "id": token.id,
                "created_at": root.created_at,
                "last_used_at": token.created_at,
                "user_agent": token.user_agent or root.user_agent,
                "is_current": current_hash is not None
                and token.token_hash == current_hash,
            }
        )
    sessions.sort(key=lambda s: s["created_at"])
    return sessions


def revoke_session(db: Session, user: models.User, token_id: uuid.UUID) -> bool:
    """Sign out ONE session: revoke the live head of the chain the
    given token belongs to (the id may name any link of the chain —
    the client got it from list_sessions, where it names the head).
    False when no live session matches (already gone, or not the
    caller's — indistinguishable on purpose)."""
    token = db.get(models.RefreshToken, token_id)
    if token is None or token.user_id != user.id:
        return False
    by_id = {
        t.id: t
        for t in db.scalars(
            select(models.RefreshToken).where(models.RefreshToken.user_id == user.id)
        ).all()
    }
    head = token
    seen = set()
    while head.replaced_by_id is not None and head.id not in seen:
        seen.add(head.id)
        successor = by_id.get(head.replaced_by_id)
        if successor is None:
            break
        head = successor
    if head.revoked_at is not None or _aware(head.expires_at) <= _now():
        return False
    head.revoked_at = _now()
    db.commit()
    return True


def revoke_other_sessions(
    db: Session, user: models.User, keep_refresh_token: str | None
) -> int:
    """Sign out everywhere else: revoke every live token of the user
    except the one matching `keep_refresh_token`. Returns how many
    sessions were ended."""
    keep_hash = hash_opaque_token(keep_refresh_token) if keep_refresh_token else None
    now = _now()
    ended = 0
    for token in db.scalars(
        select(models.RefreshToken).where(
            models.RefreshToken.user_id == user.id,
            models.RefreshToken.revoked_at.is_(None),
        )
    ).all():
        if keep_hash is not None and token.token_hash == keep_hash:
            continue
        token.revoked_at = now
        ended += 1
    if ended:
        db.commit()
    return ended


# -- account deletion ----------------------------------------------------------


def delete_account(db: Session, user: models.User) -> None:
    """Self-serve PERMANENT account deletion — the wrapper owns the
    audit-trail posture: journaling is suspended and file
    retirement runs in PERMANENT mode for the whole cascade, and
    any files the account had tombstoned for restore are destroyed
    with it. The trail protects a living account; it is never an
    undelete for a closed one. The cascade itself lives in
    _delete_account_cascade below."""
    from app.core.storage import StorageError, storage

    with journal.suspended(permanent=True):
        for row in (
            db.query(models.RetainedFile)
            .filter(models.RetainedFile.user_id == user.id)
            .all()
        ):
            try:
                storage.delete(row.storage_key)
            except StorageError:
                pass
        _delete_account_cascade(db, user)


def _delete_account_cascade(db: Session, user: models.User) -> None:
    """Self-serve PERMANENT account deletion (Settings → danger
    zone, type-to-confirm). Deletes the account and everything it
    owns across every module, in dependency order, then the user
    row itself. Other users' references to the account
    (users.referred_by_id) are nulled — their accounts survive;
    peer shares pointing at the account die with it, both ways.

    Module tables are reached through lazy model imports (the same
    cycle discipline as the rest of the codebase): core orchestrates
    the cascade because core owns the user row, but each module's
    tables are enumerated explicitly here — a new module with
    user-owned tables MUST add its cleanup to this list.
    """
    from app.modules.billing import models as billing_models
    from app.modules.borrowing import models as borrowing_models
    from app.modules.claims import models as claims_models
    from app.modules.dealers import models as dealers_models
    from app.modules.inventory import models as inventory_models
    from app.modules.inventory import service as inventory_service
    from app.modules.maintenance import models as maintenance_models
    from app.modules.parts import models as parts_models
    from app.modules.parts import service as parts_service
    from app.modules.reports import models as reports_models

    uid = user.id

    # Claims FIRST, before inventory: open claims GUARD their items
    # against deletion (the inventory delete guards claims
    # registers) — the claims must be gone before the inventory
    # loop runs, or the cascade would refuse its own items.
    # Claim-specific upload files go best-effort with them, then
    # communications, evidence, lines, and the claims themselves.
    from app.core.storage import StorageError, storage

    for evidence in (
        db.query(claims_models.ClaimEvidence)
        .filter(
            claims_models.ClaimEvidence.owner_id == uid,
            claims_models.ClaimEvidence.source == "upload",
        )
        .all()
    ):
        key = (evidence.attachment or {}).get("key")
        if key:
            try:
                storage.delete(key)
            except StorageError:
                pass
    for model in (
        claims_models.ClaimCommunication,
        claims_models.ClaimEvidence,
        claims_models.ClaimLine,
        claims_models.Claim,
    ):
        db.query(model).filter(model.owner_id == uid).delete(
            synchronize_session=False
        )

    # Borrowing: my own ledger goes with my vault. Lends where I was
    # the BORROWER live in other people's ledgers — those rows stay
    # (the borrower_name snapshot keeps them readable) with the
    # account link nulled, the referred_by treatment.
    db.query(borrowing_models.Checkout).filter(
        borrowing_models.Checkout.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(borrowing_models.Checkout).filter(
        borrowing_models.Checkout.borrower_user_id == uid
    ).update(
        {borrowing_models.Checkout.borrower_user_id: None},
        synchronize_session=False,
    )
    # Borrower address book (gap wave 1, 2026-10-20): my book goes
    # with the account; other owners' book entries that LINKED to
    # me keep their entry and lose the link (the referred_by
    # treatment). My own lends' borrower_contact_id links point at
    # my own contacts and die with the rows above.
    db.query(borrowing_models.BorrowerContact).filter(
        borrowing_models.BorrowerContact.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(borrowing_models.BorrowerContact).filter(
        borrowing_models.BorrowerContact.linked_user_id == uid
    ).update(
        {borrowing_models.BorrowerContact.linked_user_id: None},
        synchronize_session=False,
    )

    # Inventory: tools and batteries first (their stored files are
    # cleaned up best-effort by the inventory service path), then
    # definitions. Order between the two kinds doesn't matter —
    # deleting a tool only unlinks its batteries. include_attached:
    # addon tools inside sets are records too — every tool must go
    # or the owner FK blocks the user delete. Set pieces and tag
    # links die inside delete_tool/delete_battery; the tag
    # vocabulary rows themselves are deleted right after.
    for tool in inventory_service.list_tools(db, uid, include_attached=True):
        inventory_service.delete_tool(db, uid, tool.id)
    for battery in inventory_service.list_batteries(db, uid):
        inventory_service.delete_battery(db, uid, battery.id)
    db.query(inventory_models.Tag).filter(
        inventory_models.Tag.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(inventory_models.FieldDefinition).filter(
        inventory_models.FieldDefinition.owner_id == uid
    ).delete(synchronize_session=False)
    # Importer: any spreadsheet uploads still sitting in a session
    # (raw bytes included) go with the account.
    db.query(inventory_models.ImportSession).filter(
        inventory_models.ImportSession.owner_id == uid
    ).delete(synchronize_session=False)
    # Importer smart matching (2026-10-19): the learned resolve
    # answers are the owner's data too — they go with the account.
    db.query(inventory_models.ImportValueMapping).filter(
        inventory_models.ImportValueMapping.owner_id == uid
    ).delete(synchronize_session=False)
    # Inventory location tree (Package B): items above already went
    # through the service deletes (their node FK is SET NULL
    # regardless); the nodes themselves go now — parents unlinked
    # first so the self-FK can't trip the bulk delete.
    db.query(inventory_models.InventoryLocation).filter(
        inventory_models.InventoryLocation.owner_id == uid
    ).update(
        {inventory_models.InventoryLocation.parent_id: None},
        synchronize_session=False,
    )
    db.query(inventory_models.InventoryLocation).filter(
        inventory_models.InventoryLocation.owner_id == uid
    ).delete(synchronize_session=False)
    # Gap wave 1 (2026-10-20): the category registry goes with
    # the account. Lost/stolen report records already went inside
    # delete_tool/delete_battery above (they die with their
    # items); this sweep is the backstop for any row whose item
    # left by another path.
    db.query(inventory_models.InventoryCategory).filter(
        inventory_models.InventoryCategory.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(inventory_models.ItemLossReport).filter(
        inventory_models.ItemLossReport.owner_id == uid
    ).delete(synchronize_session=False)

    # Dealer build (2026-10-20) — BEFORE any dealers row goes:
    #
    # (a) Agent-deletion snapshots. Users who preferred ME directly
    # (typed my account number or tapped my public card) have no
    # private record of their own — today the preference row dies
    # here and they lose the agent's contact info entirely. So for
    # each such row, materialize a private_agents snapshot from my
    # profile (name, phone, email; the company rides the row) and
    # re-point the row at it. Owners who arrived via the
    # private -> platform LINK-SWITCH are skipped: their archived
    # placeholder unarchives below (existing behavior), and their
    # rows are deleted here as before. An agent with no profile
    # still snapshots — name from the account, contacts empty.
    _leaving_profile = (
        db.query(dealers_models.AgentProfile)
        .filter(dealers_models.AgentProfile.user_id == uid)
        .first()
    )
    _rows_naming_me = (
        db.query(dealers_models.PreferredAgent)
        .filter(
            dealers_models.PreferredAgent.agent_user_id == uid,
            dealers_models.PreferredAgent.user_id != uid,
        )
        .all()
    )
    if _rows_naming_me:
        from datetime import date as _date

        _note = (
            "Agent left the platform — saved from their profile on "
            f"{_date.today().isoformat()}."
        )
        _linked_owners = {
            row[0]
            for row in db.query(dealers_models.PrivateAgent.owner_id)
            .filter(dealers_models.PrivateAgent.linked_user_id == uid)
            .all()
        }
        for _row in _rows_naming_me:
            if _row.user_id in _linked_owners:
                continue
            _snapshot = dealers_models.PrivateAgent(
                owner_id=_row.user_id,
                company_id=_row.company_id,
                name=(
                    (_leaving_profile.display_name if _leaving_profile else "")
                    or user.name
                ),
                phone=_leaving_profile.phone if _leaving_profile else "",
                email=_leaving_profile.contact_email if _leaving_profile else "",
                notes=_note,
            )
            db.add(_snapshot)
            db.flush()
            _row.agent_user_id = None
            _row.private_agent_id = _snapshot.id
        db.flush()
    #
    # (b) Warranty service requests. As REQUESTER: my requests
    # tombstone for the dealer — the row stays (their work record),
    # named "Former member", contact snapshots BLANKED (account
    # deletion stays final; the dealer keeps the item facts, not
    # my contact details). As AGENT: requests I claimed return to
    # UNCLAIMED, re-routed to the company's remaining registered
    # agents — a request is never stranded with a deleted claimer —
    # and I come off every routing list.
    db.query(dealers_models.WarrantyServiceRequest).filter(
        dealers_models.WarrantyServiceRequest.requester_id == uid
    ).update(
        {
            dealers_models.WarrantyServiceRequest.requester_deleted: True,
            dealers_models.WarrantyServiceRequest.requester_name: "Former member",
            dealers_models.WarrantyServiceRequest.requester_email: "",
            dealers_models.WarrantyServiceRequest.requester_phone: "",
        },
        synchronize_session=False,
    )
    from app.modules.dealers import warranty as dealers_warranty

    _my_claimed = (
        db.query(dealers_models.WarrantyServiceRequest)
        .filter(
            dealers_models.WarrantyServiceRequest.claimed_by_id == uid,
            dealers_models.WarrantyServiceRequest.status.in_(
                (dealers_models.WR_RECEIVED, dealers_models.WR_IN_PROCESS)
            ),
        )
        .all()
    )
    for _request in _my_claimed:
        _remaining = []
        if _request.company_id is not None:
            _remaining = [
                agent
                for agent in dealers_warranty.registered_agents(
                    db, _request.company_id
                )
                if agent.id != uid
            ]
        _request.claimed_by_id = None
        _request.status = dealers_models.WR_UNCLAIMED
        _request.routed_agent_ids = [str(agent.id) for agent in _remaining]
    _routed_to_me = (
        db.query(dealers_models.WarrantyServiceRequest)
        .filter(
            dealers_models.WarrantyServiceRequest.claimed_by_id.is_(None),
            dealers_models.WarrantyServiceRequest.status
            == dealers_models.WR_UNCLAIMED,
        )
        .all()
    )
    for _request in _routed_to_me:
        _ids = [str(x) for x in (_request.routed_agent_ids or [])]
        if str(uid) in _ids:
            _request.routed_agent_ids = [x for x in _ids if x != str(uid)]
    db.flush()

    # Flyers (2026-11-06): flyer SOURCES the user personally
    # carries go with their flyers — sources for my own agent
    # seat, my private agent records (deleted just below), and
    # my own companies. A directory company's flyer spot
    # SURVIVES the rep who opened it (their flyers stay as the
    # company's record; posted_by_id nulls out at the user
    # delete). My flyer alert switch goes too.
    from app.modules.flyers import models as flyer_models

    db.query(flyer_models.FlyerAlertPref).filter(
        flyer_models.FlyerAlertPref.user_id == uid
    ).delete(synchronize_session=False)

    # Content alerts (sweep E4, 2026-11-12): my new-content
    # opt-in row and my per-print-file follows go with the
    # account (the flyer alert switch's posture, one block up).
    db.query(models.NewContentAlertPref).filter(
        models.NewContentAlertPref.user_id == uid
    ).delete(synchronize_session=False)
    from app.modules.prints import models as print_follow_models

    db.query(print_follow_models.PrintFileFollow).filter(
        print_follow_models.PrintFileFollow.user_id == uid
    ).delete(synchronize_session=False)
    _flyer_source_ids = [
        row.id
        for row in db.query(flyer_models.FlyerSource)
        .filter(
            (flyer_models.FlyerSource.agent_user_id == uid)
            | flyer_models.FlyerSource.private_agent_id.in_(
                db.query(dealers_models.PrivateAgent.id).filter(
                    dealers_models.PrivateAgent.owner_id == uid
                )
            )
            | flyer_models.FlyerSource.company_id.in_(
                db.query(dealers_models.DealerCompany.id).filter(
                    dealers_models.DealerCompany.owner_id == uid
                )
            )
        )
        .all()
    ]
    if _flyer_source_ids:
        from app.core.storage import storage as _flyer_storage

        for _flyer_row in (
            db.query(flyer_models.Flyer)
            .filter(flyer_models.Flyer.source_id.in_(_flyer_source_ids))
            .all()
        ):
            for _key in (_flyer_row.pdf_key, _flyer_row.thumb_key):
                if _key:
                    try:
                        _flyer_storage.delete(_key)
                    except Exception:  # noqa: BLE001 — best effort
                        pass
        db.query(flyer_models.Flyer).filter(
            flyer_models.Flyer.source_id.in_(_flyer_source_ids)
        ).delete(synchronize_session=False)
        db.query(flyer_models.FlyerSource).filter(
            flyer_models.FlyerSource.id.in_(_flyer_source_ids)
        ).delete(synchronize_session=False)

    # Dealers: my preferences (including other users' preferences
    # that named ME as their platform agent — the link dies with the
    # account), my private agent records, and my private companies.
    # Directory companies are platform data and stay. (Rows the
    # snapshot pass just re-pointed at new private records no
    # longer name me, so they survive this delete — deliberately.)
    db.query(dealers_models.PreferredAgent).filter(
        (dealers_models.PreferredAgent.user_id == uid)
        | (dealers_models.PreferredAgent.agent_user_id == uid)
    ).delete(synchronize_session=False)
    # Agent takeover (2026-11-03): requests I made die with my
    # account, and requests on records I OWN die with those
    # records just below — both named explicitly rather than
    # left to FK cascades alone.
    from sqlalchemy import select as _select

    _my_record_ids = _select(dealers_models.PrivateAgent.id).where(
        dealers_models.PrivateAgent.owner_id == uid
    )
    db.query(dealers_models.AgentTakeoverRequest).filter(
        (dealers_models.AgentTakeoverRequest.requester_user_id == uid)
        | (
            dealers_models.AgentTakeoverRequest.private_agent_id.in_(
                _my_record_ids
            )
        )
    ).delete(synchronize_session=False)
    db.query(dealers_models.PrivateAgent).filter(
        dealers_models.PrivateAgent.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(dealers_models.DealerCompany).filter(
        dealers_models.DealerCompany.owner_id == uid
    ).delete(synchronize_session=False)
    # Dealer-list customization (2026-10-31): my overlay on the
    # directory — the brands I removed and the entries I added —
    # is mine alone and goes with the account. (Missed when the
    # overlay shipped: both FKs carry no cascade, so ANY user who
    # had customized their list could not delete their account at
    # all — the user delete died on
    # user_dealer_list_hidden_user_id_fkey. Fixed 2026-11-05.)
    db.query(dealers_models.DealerListHidden).filter(
        dealers_models.DealerListHidden.user_id == uid
    ).delete(synchronize_session=False)
    db.query(dealers_models.DealerListEntry).filter(
        dealers_models.DealerListEntry.user_id == uid
    ).delete(synchronize_session=False)
    # Personal dealer edits (2026-11-05): the user's own details
    # layered over directory dealers — his alone, gone with the
    # account; the directory rows themselves are platform data
    # and stay. (The FK carries no cascade, the overlay-family
    # posture: named here so account deletion can never die on
    # it the way it died on the list overlay in the Job 2h fix.)
    db.query(dealers_models.DealerCompanyPersonalEdit).filter(
        dealers_models.DealerCompanyPersonalEdit.user_id == uid
    ).delete(synchronize_session=False)
    # Dealer portal (2026-10-19): my company representations and my
    # agent profile (photo object best-effort, like claim uploads).
    # Other users' private records that were LINKED to me unarchive
    # and unlink — the record is theirs and outlives the link; their
    # preference rows naming me were deleted just above.
    db.query(dealers_models.CompanyRepresentation).filter(
        dealers_models.CompanyRepresentation.agent_user_id == uid
    ).delete(synchronize_session=False)
    # Verification provenance: representations I VERIFIED for
    # other agents are their records — they keep their verified
    # standing; only the "who verified" link nulls, the
    # referred_by treatment. (The FK carries no action either, so
    # an operator who had ever verified a representation could
    # not delete their account — fixed 2026-11-05.)
    db.query(dealers_models.CompanyRepresentation).filter(
        dealers_models.CompanyRepresentation.verified_by_id == uid
    ).update(
        {dealers_models.CompanyRepresentation.verified_by_id: None},
        synchronize_session=False,
    )
    profile = (
        db.query(dealers_models.AgentProfile)
        .filter(dealers_models.AgentProfile.user_id == uid)
        .first()
    )
    if profile is not None:
        if profile.photo_key:
            try:
                storage.delete(profile.photo_key)
            except StorageError:
                pass
        db.delete(profile)
    # Other users' records linked to me: the link severs, the
    # record (and everything referencing it — claims, truck
    # accounts, route facts) stays with its owner, whole. A
    # TAKEOVER link also ROTATES the record's agent code
    # (2026-11-03 safeguard): the old code was in the departed
    # agent's hands, so it stops resolving here; the owner can
    # hand the fresh code to a future agent and the claim cycle
    # works again. Switch links keep their code — it was never
    # the switching mechanism.
    from app.modules.dealers.agent_codes import generate_agent_code

    for _record in (
        db.query(dealers_models.PrivateAgent)
        .filter(dealers_models.PrivateAgent.linked_user_id == uid)
        .all()
    ):
        _was_takeover = _record.link_source == "takeover"
        _record.archived = False
        _record.linked_user_id = None
        _record.link_source = None
        _record.link_snapshot = []
        if _was_takeover:
            _code = generate_agent_code()
            while (
                db.query(dealers_models.PrivateAgent.id)
                .filter(dealers_models.PrivateAgent.agent_code == _code)
                .first()
                is not None
            ):
                _code = generate_agent_code()
            _record.agent_code = _code
    db.flush()

    # Reports: my saved configurations are mine alone — they go
    # with the account.
    db.query(reports_models.ReportConfig).filter(
        reports_models.ReportConfig.owner_id == uid
    ).delete(synchronize_session=False)
    # Reports library (redesign, 2026-11-06): my generated files
    # are destroyed with their History rows (the objects are
    # mine alone, in my reports namespace), then my saved
    # templates, then the defaults seed marker.
    _report_files = (
        db.query(reports_models.GeneratedReport)
        .filter(reports_models.GeneratedReport.owner_id == uid)
        .all()
    )
    if _report_files:
        from app.core.storage import storage as _report_storage

        for _report_row in _report_files:
            try:
                _report_storage.delete(_report_row.storage_key)
            except Exception:  # noqa: BLE001 — best effort
                pass
    db.query(reports_models.GeneratedReport).filter(
        reports_models.GeneratedReport.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(reports_models.ReportTemplate).filter(
        reports_models.ReportTemplate.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(reports_models.ReportTemplateSeed).filter(
        reports_models.ReportTemplateSeed.user_id == uid
    ).delete(synchronize_session=False)

    # Used Parts: my spares and my location tree (photo objects
    # best-effort through the parts service path, parts before
    # their locations). A converted tool keeps its own copied
    # photos — they live in the tool's namespace and go with the
    # tool above.
    for part in (
        db.query(parts_models.Part)
        .filter(parts_models.Part.owner_id == uid)
        .all()
    ):
        parts_service.delete_part(db, uid, part.id)
    db.query(parts_models.PartLocation).filter(
        parts_models.PartLocation.owner_id == uid
    ).delete(synchronize_session=False)
    # Community pool settings (2026-10-19): my visibility defaults
    # and per-category choices are mine alone.
    db.query(parts_models.PartPoolSettings).filter(
        parts_models.PartPoolSettings.owner_id == uid
    ).delete(synchronize_session=False)

    # Tools For Sale (2026-10-19): my listings go with the
    # account — through the service delete so their photo objects
    # are retired with them (the journal runs in permanent mode
    # here, so retirement is a hard delete). My thread-completion
    # rows go too. Deal interactions and ratings DELIBERATELY
    # SURVIVE: they are two-party history keyed by plain ids, and
    # the other side's completed-deals count and published
    # ratings must stay honest — ratings I left keep counting
    # toward the other member's aggregate with my name resolved
    # to "Former member" (marketplace reputation's rule).
    from app.modules.marketplace import models as marketplace_models
    from app.modules.marketplace import service as marketplace_service

    for listing in marketplace_service.list_mine(db, uid):
        marketplace_service.delete_listing(db, uid, listing.id)
    db.query(marketplace_models.ThreadCompletion).filter(
        marketplace_models.ThreadCompletion.user_id == uid
    ).delete(synchronize_session=False)
    # Rating moderation (gap wave 1): reports I FILED go with the
    # account (they are my moderation paperwork, keyed to me).
    # Reports OTHERS filed about ratings survive — the ratings
    # themselves survive anonymized by the same rule as above.
    db.query(marketplace_models.RatingReport).filter(
        marketplace_models.RatingReport.reporter_id == uid
    ).delete(synchronize_session=False)

    # Community Forum (2026-10-20): my posts do NOT go with the
    # account — they tombstone in place (bodies wiped, author
    # rendered "Former member") so threads I took part in keep
    # their shape for everyone else, the same two-party-history
    # posture as my ratings. Reports I filed go; reports ON my
    # posts stay for the moderators (they now point at
    # tombstones).
    from app.modules.forum import service as forum_service

    forum_service.tombstone_author(db, uid)

    # 3D Print Files (2026-11-08): the forum posture, one shelf
    # over — my files come OFF the shelf under a Former-member
    # tombstone (their versions and other members' comments
    # keep their shape on the tombstone), my comments stay as
    # tombstones, and my own ratings / reports / maker links go
    # with the account (rating aggregates on other members'
    # files are repaired inside the prints pass).
    from app.modules.prints import service as prints_service

    prints_service.tombstone_author(db, uid)

    # Messaging (2026-10-19): every conversation I took part in
    # goes with the account — the thread, its messages, both
    # participants' read states, and any reports filed on it (the
    # other participant loses the thread too: a conversation whose
    # other side has vanished has nothing left to answer). Blocks
    # in both directions go as well; reports I filed are covered
    # by the thread sweep (reports only ever hang on threads the
    # reporter took part in).
    from app.modules.messaging import models as messaging_models

    my_thread_ids = [
        row.id
        for row in db.query(messaging_models.MessageThread)
        .filter(
            (messaging_models.MessageThread.participant_low_id == uid)
            | (messaging_models.MessageThread.participant_high_id == uid)
        )
        .all()
    ]
    if my_thread_ids:
        db.query(messaging_models.MessageReport).filter(
            messaging_models.MessageReport.thread_id.in_(my_thread_ids)
        ).delete(synchronize_session=False)
        db.query(messaging_models.MessageThreadState).filter(
            messaging_models.MessageThreadState.thread_id.in_(my_thread_ids)
        ).delete(synchronize_session=False)
        db.query(messaging_models.Message).filter(
            messaging_models.Message.thread_id.in_(my_thread_ids)
        ).delete(synchronize_session=False)
        db.query(messaging_models.MessageThread).filter(
            messaging_models.MessageThread.id.in_(my_thread_ids)
        ).delete(synchronize_session=False)
    db.query(messaging_models.UserBlock).filter(
        (messaging_models.UserBlock.blocker_id == uid)
        | (messaging_models.UserBlock.blocked_id == uid)
    ).delete(synchronize_session=False)

    # Maintenance: schedules and their logs are mine alone —
    # they go with the account (log entries first; they also
    # cascade from their schedules). Repair history is claims
    # data since the merge and goes with the claims block.
    db.query(maintenance_models.MaintenanceLogEntry).filter(
        maintenance_models.MaintenanceLogEntry.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(maintenance_models.MaintenanceSchedule).filter(
        maintenance_models.MaintenanceSchedule.owner_id == uid
    ).delete(synchronize_session=False)

    # Wave 2 (2026-10-20):
    # - Wishlist: my want-list goes with the account, through the
    #   service delete so photo objects retire with the rows (the
    #   journal is in permanent mode here — retirement is a hard
    #   delete).
    # - Sale ledger: my sales history is mine alone — it goes.
    # - Truck accounts: TWO-PARTY tabs tombstone, never vanish
    #   under the other side: my side flags deleted, the account
    #   closes, and the ledger stays readable for the survivor
    #   under my name snapshot ("Former member"). An account
    #   whose OTHER side already deleted dies outright (entries
    #   cascade with it) — nobody is left to read it.
    from app.modules.inventory import models as _inv_models_w2
    from app.modules.truck_accounts import models as truck_models
    from app.modules.wishlist import service as wishlist_service

    for wish in wishlist_service.list_items(db, uid, limit=100000):
        wishlist_service.delete_item(db, uid, wish.id)
    db.query(_inv_models_w2.SaleRecord).filter(
        _inv_models_w2.SaleRecord.owner_id == uid
    ).delete(synchronize_session=False)
    # Acquisition ledger (year-end fix, 2026-10-24): my purchase
    # history is mine alone — it goes with the account, exactly
    # like the sold ledger above.
    db.query(_inv_models_w2.AcquisitionRecord).filter(
        _inv_models_w2.AcquisitionRecord.owner_id == uid
    ).delete(synchronize_session=False)
    for account in (
        db.query(truck_models.TruckAccount)
        .filter(
            (truck_models.TruckAccount.dealer_user_id == uid)
            | (truck_models.TruckAccount.customer_user_id == uid)
        )
        .all()
    ):
        if account.dealer_user_id == uid:
            account.dealer_deleted = True
        if account.customer_user_id == uid:
            account.customer_deleted = True
            if not account.customer_name:
                account.customer_name = user.name
        if account.customer_deleted and account.dealer_deleted:
            db.delete(account)  # entries cascade (FK)
        else:
            account.status = "closed"
    db.flush()

    # Wave 3 (2026-10-20):
    # - Shop memberships: BOTH directions go. My shop's roster is
    #   my record; my memberships in other shops die with me (the
    #   owner's roster simply loses a member — memberships are
    #   live structure, not two-party history, so no tombstone).
    # - Insurer affiliation: my claim to represent a company goes
    #   with the account. (My Insurance profiles die in the core
    #   sweep below as before; their directory link is just a
    #   column on that row.)
    # - Feedback: the forum posture — my posts + comments stay as
    #   Former-member tombstones, my votes and filed reports go.
    # - Cloud backups (wave 4): the Drive connection (its stored
    #   token must not outlive the account) and the backup
    #   history rows go. The backup FILES in the user's own Drive
    #   are the user's property on the user's storage — account
    #   deletion here never reaches into their Drive.
    db.query(models.CloudBackupRun).filter(
        models.CloudBackupRun.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.CloudDriveConnection).filter(
        models.CloudDriveConnection.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.ShopMembership).filter(
        (models.ShopMembership.shop_user_id == uid)
        | (models.ShopMembership.employee_user_id == uid)
    ).delete(synchronize_session=False)
    # Onboarding (2026-11-07): the setup pass's progress rows are
    # the account's own — they go with it (plain-id table, the
    # 0038 pattern, swept explicitly like the memberships above).
    from app.modules.core import onboarding

    onboarding.sweep_user(db, uid)
    db.query(models.InsurerAffiliation).filter(
        models.InsurerAffiliation.user_id == uid
    ).delete(synchronize_session=False)
    from app.modules.feedback import service as feedback_service

    feedback_service.tombstone_author(db, uid)

    # Support tickets (2026-10-24): a ticket is private two-party
    # mail, not public content — no tombstone posture here. Every
    # message I authored goes first (including any on tickets
    # that outlive … none do: my tickets go right after, with
    # their remaining messages — the team's replies to me — via
    # the ticket sweep / FK cascade).
    from app.modules.support import models as support_models

    db.query(support_models.SupportMessage).filter(
        support_models.SupportMessage.author_id == uid
    ).delete(synchronize_session=False)
    _my_ticket_ids = [
        row.id
        for row in db.query(support_models.SupportTicket)
        .filter(support_models.SupportTicket.user_id == uid)
        .all()
    ]
    if _my_ticket_ids:
        db.query(support_models.SupportMessage).filter(
            support_models.SupportMessage.ticket_id.in_(_my_ticket_ids)
        ).delete(synchronize_session=False)
    db.query(support_models.SupportTicket).filter(
        support_models.SupportTicket.user_id == uid
    ).delete(synchronize_session=False)

    # Billing: wallet + ledger, redemptions (they reference grants),
    # grants, subscription status-change history (it references the
    # subscription), subscription.
    for model in (
        billing_models.AiLedger,
        billing_models.AiWallet,
        billing_models.Redemption,
        billing_models.EntitlementGrant,
        billing_models.SubscriptionStatusChange,
        billing_models.Subscription,
    ):
        db.query(model).filter(model.user_id == uid).delete(
            synchronize_session=False
        )

    # Core: sharing (both directions), inbox, layouts, tokens.
    db.query(models.PeerShareExclusion).filter(
        models.PeerShareExclusion.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(models.PeerSetChoice).filter(
        models.PeerSetChoice.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(models.SharedItem).filter(models.SharedItem.owner_id == uid).delete(
        synchronize_session=False
    )
    # Package C: sharing rules + exclusions (tier and peer) and the
    # My Insurance profile go with the account too.
    db.query(models.ShareRule).filter(models.ShareRule.owner_id == uid).delete(
        synchronize_session=False
    )
    db.query(models.ShareExclusion).filter(
        models.ShareExclusion.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(models.PeerShareExclusionRule).filter(
        models.PeerShareExclusionRule.owner_id == uid
    ).delete(synchronize_session=False)
    db.query(models.InsuranceProfile).filter(
        models.InsuranceProfile.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.ShareConfig).filter(models.ShareConfig.owner_id == uid).delete(
        synchronize_session=False
    )
    db.query(models.PeerShare).filter(
        (models.PeerShare.owner_id == uid) | (models.PeerShare.viewer_user_id == uid)
    ).delete(synchronize_session=False)
    db.query(models.Notification).filter(models.Notification.user_id == uid).delete(
        synchronize_session=False
    )
    # Tier conversion (2026-11-10): the account's one request
    # dies with it; requests it DECIDED as a god account keep
    # their row (the decider snapshot carries the email) with
    # the FK nulled.
    db.query(models.ConversionRequest).filter(
        models.ConversionRequest.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.ConversionRequest).filter(
        models.ConversionRequest.decided_by_id == uid
    ).update(
        {models.ConversionRequest.decided_by_id: None},
        synchronize_session=False,
    )
    db.query(models.UserPageLayout).filter(
        models.UserPageLayout.user_id == uid
    ).delete(synchronize_session=False)
    # Per-user module switches (2026-10-24): the user's own
    # settings rows — they die with the account like its layouts.
    db.query(models.UserModulePref).filter(
        models.UserModulePref.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.RefreshToken).filter(models.RefreshToken.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(models.EmailVerificationToken).filter(
        models.EmailVerificationToken.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.user_id == uid
    ).delete(synchronize_session=False)
    db.query(models.EmailChangeToken).filter(
        models.EmailChangeToken.user_id == uid
    ).delete(synchronize_session=False)
    # The mail log rows addressed to this account (the outbox is
    # keyed by address, not user id — it is a delivery record).
    db.query(models.EmailOutbox).filter(
        models.EmailOutbox.recipient == user.email
    ).delete(synchronize_session=False)

    # Tool Expansion (2026-10-25): my dismissal + report rows are
    # my own moderation paperwork — they go with the account, the
    # marketplace-reports rule above (a killed match can revive if
    # its reporters' accounts all go; that is the honest count).
    from app.modules.tool_expansion import models as expansion_models

    db.query(expansion_models.ExpansionDismissal).filter(
        expansion_models.ExpansionDismissal.user_id == uid
    ).delete(synchronize_session=False)
    db.query(expansion_models.ExpansionReport).filter(
        expansion_models.ExpansionReport.user_id == uid
    ).delete(synchronize_session=False)

    # Referral links from other accounts: the referrer is gone; the
    # accounts stay, their referral source becomes nobody.
    db.query(models.User).filter(models.User.referred_by_id == uid).update(
        {models.User.referred_by_id: None}, synchronize_session=False
    )

    db.delete(user)
    db.commit()


# -- admin: directory, operator actions, bans ---------------------------------
#
# The service half of the Admin panel (Phase A2). The routes
# (admin_routes.py) own HTTP + audit; these functions own the
# state changes, so any future surface applies the same rules.

# The community role ladder (owner 2026-10-18): a user's standing
# on community surfaces, separate from groups and from is_operator.
ROLES: tuple[str, ...] = ("user", "moderator", "community_admin")


def search_users(
    db: Session, query: str | None, *, limit: int = 25, offset: int = 0
) -> tuple[list[models.User], int]:
    """The Admin → Users directory: case-insensitive substring
    search across name, email, and account number, newest accounts
    first. Returns (page, total). An empty query lists everyone."""
    stmt = select(models.User)
    count_stmt = select(func.count(models.User.id))
    needle = (query or "").strip()
    if needle:
        like = f"%{needle}%"
        condition = (
            models.User.name.ilike(like)
            | models.User.email.ilike(like)
            | models.User.account_number.ilike(like)
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = list(
        db.scalars(
            stmt.order_by(models.User.created_at.desc(), models.User.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total


def referral_count(db: Session, user_id: str | uuid.UUID) -> int:
    """How many accounts this user referred (users.referred_by_id)."""
    return (
        db.scalar(
            select(func.count(models.User.id)).where(
                models.User.referred_by_id == uuid.UUID(str(user_id))
            )
        )
        or 0
    )


def set_user_operator(db: Session, user: models.User, flag: bool) -> models.User:
    """Grant or revoke operator (God) access. The route guards the
    self-revoke case; this is the plain state change + commit."""
    user.is_operator = bool(flag)
    db.commit()
    db.refresh(user)
    return user


def set_user_role(db: Session, user: models.User, role: str) -> models.User:
    """Set the community role. Raises ValueError outside ROLES.

    The role ladder folds into the tier system (owner 2026-10-31):
    setting a role moves the rung to match (user ⇒ normal,
    moderator ⇒ moderator, community_admin ⇒ moderator_admin), so
    the two never drift. The god rung is out of this function's
    reach — it never names a role, and a god account's tier is
    left untouched here (its role stays community_admin)."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    user.role = role
    if tiers.resolved_tier(user) != "god":
        # The downloads rung (2026-11-09) is the one rung the role
        # ladder cannot speak for: its shadow IS "user", so folding
        # a role write into the rung would read "user" as a
        # promotion to normal. A downloads account changes rung
        # only through set_user_tier (the grant machinery) — a
        # role write on one still lands the role itself, and a
        # moderator/community_admin role write is refused the
        # rung move too: grant the rung first, then the role.
        if tiers.resolved_tier(user) != "downloads":
            user.tier = tiers.tier_for_role(role)
    db.commit()
    db.refresh(user)
    return user


def set_user_tier(db: Session, user: models.User, tier: str) -> models.User:
    """Set the account's rung and its community-role shadow
    together (core/tiers.py). Raises ValueError outside the
    GRANTABLE rungs — 'god' is deliberately ungrantable here: the
    rung is assigned by migration 0067's backfill and no API path
    creates or removes it. The route owns the grant rules (who may
    set which rung on whom); this is the plain state change."""
    if tier not in tiers.GRANTABLE_TIERS:
        raise ValueError(f"Tier is not grantable: {tier}")
    user.tier = tier
    user.role = tiers.role_for_tier(tier)
    db.commit()
    db.refresh(user)
    return user


def set_user_beta(db: Session, user: models.User, flag: bool) -> models.User:
    """Grant or revoke the Beta Tester upgrade flag (core/tiers.py).
    The route owns the grant rules; this is the plain state
    change + commit."""
    user.beta_tester = bool(flag)
    db.commit()
    db.refresh(user)
    return user


def revoke_all_sessions(db: Session, user: models.User) -> int:
    """Revoke EVERY live refresh token of the user (deactivation
    and bans both land here: existing sessions end immediately;
    already-issued access tokens live out their short remainder,
    the same contract as a single-session revoke). Returns how
    many live tokens were revoked."""
    now = _now()
    live = list(
        db.scalars(
            select(models.RefreshToken).where(
                models.RefreshToken.user_id == user.id,
                models.RefreshToken.revoked_at.is_(None),
                models.RefreshToken.expires_at > now,
            )
        ).all()
    )
    for token in live:
        token.revoked_at = now
    if live:
        db.commit()
    return len(live)


def set_user_active(db: Session, user: models.User, active: bool) -> models.User:
    """Soft deactivation / reactivation. Deactivation blocks
    sign-in (login route + deps check the flag) and revokes every
    live session; the account's data is untouched, and reactivation
    restores access exactly as it was."""
    user.is_active = bool(active)
    db.commit()
    if not active:
        revoke_all_sessions(db, user)
    db.refresh(user)
    return user


# -- bans ---------------------------------------------------------------------


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def get_ban(db: Session, email: str) -> models.BannedEmail | None:
    return db.scalars(
        select(models.BannedEmail).where(
            models.BannedEmail.email == _normalize_email(email)
        )
    ).first()


def is_email_banned(db: Session, email: str) -> bool:
    return get_ban(db, email) is not None


def ban_email(
    db: Session,
    email: str,
    *,
    reason: str = "",
    banned_by: uuid.UUID | None = None,
) -> models.BannedEmail:
    """Ban an address (upsert: re-banning updates the reason and
    who placed it). If an account already holds the address, its
    live sessions are revoked in the same breath — a ban that left
    the account signed in would be a ban in name only. Nothing is
    deleted; unban restores access as it was."""
    normalized = _normalize_email(email)
    if "@" not in normalized or normalized.startswith("@"):
        raise ValueError("That doesn't look like an email address.")
    row = get_ban(db, normalized)
    if row is None:
        row = models.BannedEmail(email=normalized)
        db.add(row)
    row.reason = reason[:500]
    row.banned_by = banned_by
    db.commit()
    db.refresh(row)
    account = get_user_by_email(db, normalized)
    if account is not None:
        revoke_all_sessions(db, account)
    return row


def unban_email(db: Session, email: str) -> bool:
    """Remove a ban. True when a ban existed. Access returns as it
    was (the account signs in fresh; revoked sessions stay revoked)."""
    row = get_ban(db, email)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_bans(db: Session) -> list[models.BannedEmail]:
    return list(
        db.scalars(
            select(models.BannedEmail).order_by(models.BannedEmail.created_at.desc())
        ).all()
    )


# -- email verification ------------------------------------------------------
def start_email_verification(db: Session, user: models.User) -> None:
    """Mint a verification token for `user` and send the link.

    Sending goes through app.core.notifications (the Resend seam).
    Login gating on verification is a separate launch switch
    (`auth.require_email_verification`, read by the login route
    via billing's entitlements) — this function is just the send.
    """
    plain, token_hash = generate_opaque_token()
    db.add(
        models.EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=_now()
            + timedelta(hours=settings.email_verification_expire_hours),
        )
    )
    db.commit()
    notifications.send_verification_email(db, user.email, plain, locale=i18n.resolve_locale(user))


def verify_email(db: Session, plain: str) -> bool:
    """Consume a verification token. On success the user's email_verified
    flag is set and the token can never be used again."""
    token = db.scalars(
        select(models.EmailVerificationToken).where(
            models.EmailVerificationToken.token_hash == hash_opaque_token(plain)
        )
    ).first()
    if token is None or token.used_at is not None:
        return False
    if _aware(token.expires_at) <= _now():
        return False
    user = db.get(models.User, token.user_id)
    if user is None:
        return False
    token.used_at = _now()
    user.email_verified = True
    db.commit()
    return True


# -- password reset ------------------------------------------------------------
#
# The lockout fix: before this flow, a forgotten password meant the
# account was gone (the design audit flagged it as an absolute
# lockout). The request side is SILENT — the route answers the same
# words for every address, and the email goes out only when a live,
# unbanned account actually holds it. The confirm side can afford
# to be specific: whoever holds the link already proved inbox
# control, so expiry/reuse errors say exactly what happened.


def request_password_reset(db: Session, email: str) -> None:
    """Ask for a reset link for `email`. Sends only when the
    account exists, is active, and is not banned — every other
    case is indistinguishable silence (see the section note)."""
    user = get_user_by_email(db, email)
    if user is None or not user.is_active or is_email_banned(db, user.email):
        return
    # A fresh request supersedes every older unused link: at most
    # one live reset link per account, ever.
    db.execute(
        update(models.PasswordResetToken)
        .where(
            models.PasswordResetToken.user_id == user.id,
            models.PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    plain, token_hash = generate_opaque_token()
    db.add(
        models.PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=_now()
            + timedelta(hours=settings.password_reset_expire_hours),
        )
    )
    db.commit()
    notifications.send_password_reset_email(db, user.email, plain, locale=i18n.resolve_locale(user))


def reset_password(db: Session, plain_token: str, new_password: str) -> str:
    """Consume a reset token and set the password. Returns a result
    code the route turns into copy:

      ok       — password set, password login enabled, the token
                 consumed, every other outstanding reset token
                 voided, and ALL sessions revoked (a reset is a
                 credential-compromise response: nothing signed in
                 before it stays signed in).
      invalid  — no such token (or its account is gone).
      used     — the link was already consumed.
      expired  — the link outlived its hour.
      blocked  — the account is banned or deactivated; a reset
                 must never be a way back in for a blocked account.
    """
    token = db.scalars(
        select(models.PasswordResetToken).where(
            models.PasswordResetToken.token_hash == hash_opaque_token(plain_token)
        )
    ).first()
    if token is None:
        return "invalid"
    if token.used_at is not None:
        return "used"
    if _aware(token.expires_at) <= _now():
        return "expired"
    user = db.get(models.User, token.user_id)
    if user is None:
        return "invalid"
    if is_email_banned(db, user.email) or not user.is_active:
        return "blocked"
    user.password_hash = hash_password(new_password)
    user.password_login_enabled = True
    token.used_at = _now()
    db.execute(
        update(models.PasswordResetToken)
        .where(
            models.PasswordResetToken.user_id == user.id,
            models.PasswordResetToken.id != token.id,
            models.PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    _revoke_all_refresh_tokens(db, user.id)
    db.commit()
    return "ok"


# -- email change --------------------------------------------------------------
#
# The sign-in address moves only after the NEW inbox proves control
# (a confirmation link sent there — request_email_change), and the
# move is announced to the OLD inbox (confirm_email_change), so a
# hijacked session can't silently steal an account's identity: the
# real owner sees the tripwire email. The pending token row is the
# pending state; nothing about users.email changes until confirm.


def request_email_change(
    db: Session,
    user: models.User,
    new_email: str,
    current_password: str | None,
) -> str:
    """Start an email change for `user`. Returns a result code:

      ok             — confirmation link sent to the new address.
      wrong_password — the account has password login and the
                       current password didn't verify (an
                       OAuth-only account skips this check: its
                       live session is the identity proof, exactly
                       as in change_password).
      same           — the new address IS the current address.
      taken          — another account already holds the address.
      banned         — the new address is operator-banned.
    """
    if user.password_login_enabled:
        if current_password is None or not verify_password(
            current_password, user.password_hash
        ):
            return "wrong_password"
    normalized = new_email.strip().lower()
    if normalized == user.email.lower():
        return "same"
    if is_email_banned(db, normalized):
        return "banned"
    existing = get_user_by_email(db, normalized)
    if existing is not None and existing.id != user.id:
        return "taken"
    # A new request replaces any pending one (the old link dies).
    db.execute(
        update(models.EmailChangeToken)
        .where(
            models.EmailChangeToken.user_id == user.id,
            models.EmailChangeToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    plain, token_hash = generate_opaque_token()
    db.add(
        models.EmailChangeToken(
            user_id=user.id,
            new_email=normalized,
            token_hash=token_hash,
            expires_at=_now()
            + timedelta(hours=settings.email_change_expire_hours),
        )
    )
    db.commit()
    notifications.send_email_change_email(db, normalized, plain, locale=i18n.resolve_locale(user))
    return "ok"


def pending_email_change(db: Session, user: models.User) -> models.EmailChangeToken | None:
    """The caller's live pending change (unused, unexpired), newest
    first — what Settings shows as "confirmation sent to …"."""
    return db.scalars(
        select(models.EmailChangeToken)
        .where(
            models.EmailChangeToken.user_id == user.id,
            models.EmailChangeToken.used_at.is_(None),
            models.EmailChangeToken.expires_at > _now(),
        )
        .order_by(models.EmailChangeToken.created_at.desc())
    ).first()


def cancel_email_change(db: Session, user: models.User) -> bool:
    """Void the pending change (the sent link dies with it). True
    when there was a live pending change to cancel."""
    pending = pending_email_change(db, user)
    if pending is None:
        return False
    db.execute(
        update(models.EmailChangeToken)
        .where(
            models.EmailChangeToken.user_id == user.id,
            models.EmailChangeToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    db.commit()
    return True


def confirm_email_change(
    db: Session, plain_token: str, keep_refresh_token: str | None = None
) -> tuple[str, models.User | None]:
    """Consume an email-change token and move the address. Returns
    (result code, user) — the user only on "ok":

      ok       — users.email is the new address (verified by
                 construction — the inbox proved control), the
                 token is consumed along with any other pending
                 change, every session but `keep_refresh_token`'s
                 is revoked, an audit row records the move, and
                 the OLD address gets the "your email was changed"
                 notice.
      invalid  — no such token (or its account is gone).
      used     — the link was already consumed.
      expired  — the link outlived its hour.
      taken    — another account claimed the address between
                 request and confirm (re-checked here: the request
                 check alone would leave a race).
      blocked  — the account is banned or deactivated, or the NEW
                 address was banned meanwhile; a blocked account
                 can't move its identity.
    """
    # Imported here: audit sits beside the service in the same
    # module, but keeping the import local mirrors the codebase's
    # cycle discipline for cross-cutting writers.
    from app.modules.core import audit

    token = db.scalars(
        select(models.EmailChangeToken).where(
            models.EmailChangeToken.token_hash == hash_opaque_token(plain_token)
        )
    ).first()
    if token is None:
        return "invalid", None
    if token.used_at is not None:
        return "used", None
    if _aware(token.expires_at) <= _now():
        return "expired", None
    user = db.get(models.User, token.user_id)
    if user is None:
        return "invalid", None
    if (
        not user.is_active
        or is_email_banned(db, user.email)
        or is_email_banned(db, token.new_email)
    ):
        return "blocked", None
    existing = get_user_by_email(db, token.new_email)
    if existing is not None and existing.id != user.id:
        return "taken", None
    old_email = user.email
    user.email = token.new_email
    user.email_verified = True
    token.used_at = _now()
    db.execute(
        update(models.EmailChangeToken)
        .where(
            models.EmailChangeToken.user_id == user.id,
            models.EmailChangeToken.id != token.id,
            models.EmailChangeToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    stmt = update(models.RefreshToken).where(
        models.RefreshToken.user_id == user.id,
        models.RefreshToken.revoked_at.is_(None),
    )
    if keep_refresh_token:
        stmt = stmt.where(
            models.RefreshToken.token_hash != hash_opaque_token(keep_refresh_token)
        )
    db.execute(stmt.values(revoked_at=_now()))
    db.commit()
    audit.record(
        db,
        user,
        action="user.email_change",
        target=token.new_email,
        detail={"from": old_email, "to": token.new_email},
    )
    notifications.send_email_changed_notice(db, old_email, token.new_email, locale=i18n.resolve_locale(user))
    db.refresh(user)
    return "ok", user
