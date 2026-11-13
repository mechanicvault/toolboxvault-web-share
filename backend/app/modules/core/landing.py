"""Public landing page config (core module service, 2026-10-20).

Ryan's spec (2026-10-20 08:20 + 08:21): a signed-out visitor
landing on the site gets a page that SELLS it — abilities,
pricing, free-trial offers, the free tier — plus app-store links.
The HONESTY RULES (stated to Ryan with the spec):

  - Pricing and trial copy are ADMIN SETTINGS, driven by the real
    plan catalog — the page can only advertise what the system
    actually offers. Prices are display strings exactly as the
    operator typed them (never parsed, never reformatted).
  - The trial block renders ONLY while
    `landing.self_serve_trial_enabled` is true (default False —
    trials are admin-started today; never advertise what doesn't
    exist).
  - The app-store block renders ONLY while at least one store URL
    is set (both default empty — no verified store listing URLs
    are on file; NEVER invent one).
  - The free tier's item limit is read from the plan catalog (the
    free plan's `item_limit`), never hardcoded — if the catalog
    changes, the page tells the new truth.
  - Business pricing is "base + per-crew-size brackets" (owner
    decision 2026-10-18); dollar figures render ONLY when the
    operator sets them (the app anchor prices Business never had).

Seeded defaults are the existing app's anchor (account-and-
payments design, 2026-10-18): Pro $7.99/mo, $79.99/yr. The admin
panel edits every value live — no deploy — through the same
system-settings store + per-key audit rows as the Stripe panel.

SERVICE INTERFACE (stable):
  - landing_config(db) -> dict — every landing setting at its
    effective value (stored value, else the seeded default).
  - free_item_limit(db) -> int — the free plan's catalog limit.
  - public_landing(db) -> dict — the ONLY shape the anonymous
    endpoint exposes: landing_config + free_item_limit. Every
    value in it is public-safe by construction.
"""

from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import module_control, teaser

# -- operator settings keys (system_settings; Admin -> Settings) --------

PRO_MONTHLY_PRICE_KEY = "landing.pro_monthly_price"
PRO_YEARLY_PRICE_KEY = "landing.pro_yearly_price"
BUSINESS_MONTHLY_PRICE_KEY = "landing.business_monthly_price"
BUSINESS_YEARLY_PRICE_KEY = "landing.business_yearly_price"
SELF_SERVE_TRIAL_ENABLED_KEY = "landing.self_serve_trial_enabled"
TRIAL_COPY_KEY = "landing.trial_copy"
APP_STORE_URL_KEY = "landing.app_store_url"
PLAY_STORE_URL_KEY = "landing.play_store_url"

ALL_KEYS = (
    PRO_MONTHLY_PRICE_KEY,
    PRO_YEARLY_PRICE_KEY,
    BUSINESS_MONTHLY_PRICE_KEY,
    BUSINESS_YEARLY_PRICE_KEY,
    SELF_SERVE_TRIAL_ENABLED_KEY,
    TRIAL_COPY_KEY,
    APP_STORE_URL_KEY,
    PLAY_STORE_URL_KEY,
)

# Seeded defaults: the app's anchor prices (the owner edits them
# in Admin -> Settings; an empty stored string CLEARS a price back
# to "not shown" — for Business that is the seeded state).
DEFAULTS: dict[str, object] = {
    PRO_MONTHLY_PRICE_KEY: "7.99",
    PRO_YEARLY_PRICE_KEY: "79.99",
    BUSINESS_MONTHLY_PRICE_KEY: "",
    BUSINESS_YEARLY_PRICE_KEY: "",
    SELF_SERVE_TRIAL_ENABLED_KEY: False,
    TRIAL_COPY_KEY: "",
    APP_STORE_URL_KEY: "",
    PLAY_STORE_URL_KEY: "",
}

# The fallback when a database somehow has no free plan row (the
# catalog seeds it at migration 0010; this only guards a bare
# pre-catalog database from 500ing the public page).
FREE_LIMIT_FALLBACK = 20


def _text(db: Session, key: str) -> str:
    value = entitlements.get_setting(db, key, DEFAULTS[key])
    return value if isinstance(value, str) else str(value)


def landing_config(db: Session) -> dict:
    """Every landing setting at its effective value."""
    trial = entitlements.get_setting(
        db, SELF_SERVE_TRIAL_ENABLED_KEY, DEFAULTS[SELF_SERVE_TRIAL_ENABLED_KEY]
    )
    return {
        "pro_monthly_price": _text(db, PRO_MONTHLY_PRICE_KEY),
        "pro_yearly_price": _text(db, PRO_YEARLY_PRICE_KEY),
        "business_monthly_price": _text(db, BUSINESS_MONTHLY_PRICE_KEY),
        "business_yearly_price": _text(db, BUSINESS_YEARLY_PRICE_KEY),
        "self_serve_trial_enabled": bool(trial),
        "trial_copy": _text(db, TRIAL_COPY_KEY),
        "app_store_url": _text(db, APP_STORE_URL_KEY),
        "play_store_url": _text(db, PLAY_STORE_URL_KEY),
    }


def free_item_limit(db: Session) -> int:
    """The free tier's item limit, from the plan catalog itself —
    the same number the entitlement engine enforces at launch."""
    plan = entitlements.get_plan(db, entitlements.FREE_PLAN)
    if plan is not None and plan.item_limit is not None:
        return plan.item_limit
    return FREE_LIMIT_FALLBACK


def public_landing(db: Session) -> dict:
    """The anonymous endpoint's whole answer. Nothing here is a
    secret by construction: display prices, the trial switch and
    its copy, the store URLs, the catalog's free limit — and, since
    the teaser build (2026-10-26), the teaser-mode flag itself:
    one boolean that tells the signed-out shell whether the front
    door is the landing or the teaser. The gate code is NEVER
    part of this shape (core/teaser.py owns it, server-side only)."""
    video_url, poster_url = teaser.public_video_urls(db)
    return {
        **landing_config(db),
        "free_item_limit": free_item_limit(db),
        "teaser_mode": teaser.teaser_enabled(db),
        # Free-access card gates (owner 2026-10-31, hidden modules):
        # the landing's Tools For Sale / Community Parts cards are
        # public advertisements for switchboard modules — they may
        # only render while the operator layer has the module usable
        # somewhere on the site. Park the module and the card goes
        # with it, no landing edit needed.
        "marketplace_enabled": module_control.usable_anywhere(db, "marketplace"),
        "community_parts_enabled": module_control.usable_anywhere(db, "parts"),
        # The current teaser trailer (owner refinement,
        # 2026-10-26): presigned reads of the site's own stored
        # MP4 + poster frame. Both empty unless the teaser is on
        # AND a video is set — no slot, no trace, in every other
        # state (see core/teaser.py public_video_urls).
        "teaser_video_url": video_url,
        "teaser_poster_url": poster_url,
    }
