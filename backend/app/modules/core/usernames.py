"""Username rules.

Every account carries a public username, and it is the ONLY name
other users ever see — forum posts, comments, 3D print publisher,
feedback, borrowing, claims, sharing. The account's real name is
private and never rides a payload meant for anyone else.

The rules, as directed:
- Forced at signup; unique — no two accounts share a name.
- Existing accounts without one pick at next sign-in (the app
  gates them; see the /choose-username screen).
- Changeable in profile settings at most once every 6 months.
- The god account's name is "Toolbox Vault"; the words
  "Toolbox Vault" are reserved — only admin accounts
  (operator / god / moderator_admin tiers) may hold a name
  containing them.

Uniqueness is judged on the KEY form — lowercase, letters and
digits only — so "Tool Box", "Toolbox" and "TOOLBOX" are one
name. That same key makes the reserved check copycat-proof.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models

MIN_LENGTH = 3
MAX_LENGTH = 24
GOD_USERNAME = "Toolbox Vault"
RESERVED_KEY = "toolboxvault"
ADMIN_TIERS = ("god", "moderator_admin")

# Letters, numbers, spaces, underscore, dot, hyphen; must start
# with a letter or number. (The god name "Toolbox Vault" fits.)
_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]*$")
_NON_KEY = re.compile(r"[^a-z0-9]")


class UsernameError(ValueError):
    """A username rule failed; `code` is the stable wire code
    the client turns into words (username_invalid / _taken /
    _reserved / _cooldown)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def username_key(raw: str) -> str:
    """The uniqueness form of a name: lowercase alphanumerics."""
    return _NON_KEY.sub("", raw.lower())


def clean_username(raw: str) -> str:
    """The display form: trimmed, inner whitespace collapsed."""
    return " ".join((raw or "").split())


def is_admin_account(user: models.User) -> bool:
    return bool(user.is_operator) or user.tier in ADMIN_TIERS


def may_hold_reserved(user: models.User) -> bool:
    return is_admin_account(user)


def is_reserved_key(key: str) -> bool:
    return RESERVED_KEY in key


def public_name(user: models.User | None) -> str:
    """What other users see. An account that has not picked a
    username yet reads as a plain "Member" — never its real
    name."""
    if user is None:
        return "Former member"
    return getattr(user, "username", None) or "Member"


def _add_months(moment: datetime, months: int) -> datetime:
    import calendar

    month = moment.month - 1 + months
    year = moment.year + month // 12
    month = month % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def next_change_at(user: models.User) -> datetime | None:
    """When this account may change its username again; None =
    it may change now (never set, or an admin account — admins
    are exempt from the cooldown). Always tz-aware."""
    if user.username is None or user.username_changed_at is None:
        return None
    if is_admin_account(user):
        return None
    changed_at = user.username_changed_at
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    return _add_months(changed_at, 6)


def check_username(
    db: Session,
    raw: str,
    *,
    for_user: models.User | None,
) -> str:
    """Validate a proposed username for `for_user` (None = a
    brand-new signup, which is never an admin). Returns the
    cleaned display form or raises UsernameError."""
    cleaned = clean_username(raw)
    if (
        len(cleaned) < MIN_LENGTH
        or len(cleaned) > MAX_LENGTH
        or not _SHAPE.match(cleaned)
    ):
        raise UsernameError("username_invalid")
    key = username_key(cleaned)
    if len(key) < MIN_LENGTH:
        raise UsernameError("username_invalid")
    if is_reserved_key(key) and not (
        for_user is not None and may_hold_reserved(for_user)
    ):
        raise UsernameError("username_reserved")
    clash = (
        db.query(models.User)
        .filter(models.User.username_key == key)
        .first()
    )
    if clash is not None and (for_user is None or clash.id != for_user.id):
        raise UsernameError("username_taken")
    return cleaned


def set_username(
    db: Session,
    user: models.User,
    raw: str,
    *,
    now: datetime | None = None,
) -> str:
    """Set (first pick) or change `user`'s username, enforcing
    every rule including the 6-month change cooldown. Returns
    the cleaned display form. Caller commits."""
    cleaned = check_username(db, raw, for_user=user)
    moment = now or datetime.now(timezone.utc)
    if user.username is not None:
        unlock = next_change_at(user)
        if unlock is not None and moment < unlock:
            raise UsernameError("username_cooldown")
        if username_key(cleaned) == user.username_key:
            return user.username  # same name, new casing/spacing only
    user.username = cleaned
    user.username_key = username_key(cleaned)
    user.username_changed_at = moment
    return cleaned


def username_availability(
    db: Session, raw: str, *, for_user: models.User | None
) -> dict:
    """The signup/picker check: {available, reason} where reason
    is a UsernameError code or None."""
    try:
        check_username(db, raw, for_user=for_user)
    except UsernameError as exc:
        return {"available": False, "reason": exc.code}
    return {"available": True, "reason": None}
