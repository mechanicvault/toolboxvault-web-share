"""NEW badges for menu items (release machinery, owner rule
2026-11-08): when a feature adds a menu/nav item, that item
carries a NEW badge for its FIRST WEEK.

The registry is one system-settings key — `nav.new_badges` —
holding a JSON object that maps a nav item key to the item's
release date ("YYYY-MM-DD"):

    {"reports": "2026-12-01", "flyers": "2026-12-03"}

Nav item keys are the FRONTEND registry names (frontend/src/
modules/registry.ts `name` — e.g. "reports", "flyers",
"truck-accounts") plus "core-settings" for the shell's Settings
item. The server stores and serves the map verbatim (validated);
the CLIENT computes freshness at render — a badge shows while
today is the release date or any of the 6 days after it, and on
day 8 it simply never renders. No cron, no manual removal: a
stale entry is inert data, prunable whenever an operator next
edits the setting in Admin -> Settings.
"""

import re
from datetime import date

from sqlalchemy.orm import Session

from app.modules.billing import entitlements

NAV_BADGES_KEY = "nav.new_badges"

_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_badge_map(value) -> bool:
    """The stored/served shape: an object whose keys are
    non-empty item keys and whose values are real ISO dates."""
    if not isinstance(value, dict):
        return False
    for key, raw in value.items():
        if not isinstance(key, str) or not key or len(key) > 100:
            return False
        if not isinstance(raw, str) or not _DATE_SHAPE.match(raw):
            return False
        try:
            date.fromisoformat(raw)
        except ValueError:
            return False
    return True


def get_nav_badges(db: Session) -> dict[str, str]:
    """The registry as stored. A malformed stored value reads
    as an empty registry — a bad setting must never badge (or
    break) the whole nav."""
    value = entitlements.get_setting(db, NAV_BADGES_KEY, {})
    if not valid_badge_map(value):
        return {}
    return dict(value)


def set_nav_badges(db: Session, value: dict[str, str]) -> None:
    entitlements.set_setting(db, NAV_BADGES_KEY, dict(value))
