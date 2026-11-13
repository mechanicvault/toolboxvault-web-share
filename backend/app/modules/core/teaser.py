"""Teaser mode (owner order, 2026-10-26): until launch day the
public front door is a teaser — brand, a countdown, two doors
(Log in, Create account) — and nothing else is reachable
signed-out.

Operator data, not code, in the same system-settings store as the
launch switches (Admin -> Settings edits both keys):

  teaser.enabled    — bool. Code default False, the same posture
                      as the other launch switches (built dark,
                      flipped by the operator); production ships
                      with it flipped ON and the owner flips it
                      OFF on launch day.
  teaser.gate_code  — the code that unlocks account creation
                      while teaser mode is on. Until the operator
                      stores his own, the effective code is the
                      owner's chosen default below.

ENFORCEMENT IS SERVER-SIDE, at both account-creation doors —
email signup (core/routes.py) and social find-or-create
(core/oauth_routes.py). OPEN SIGNUP (owner order, 2026-11-09)
changed what the gate decides: it no longer decides WHETHER a
browser may create an account, but WHAT the new account is. A
browser without a valid unlock creates a downloads-rung account
(the limited level — core/tiers.py); a browser WITH the unlock
creates a normal account, the full site, exactly as the gate
always granted. The decision is one function — signup_tier
below — asked identically by both doors. The unlock is a
signed, purpose-scoped, 30-minute token (app.core.security)
carried in an httpOnly cookie; the code itself is compared
here, on the server, and never appears in any response, page,
or bundle.
"""

import hmac
import ipaddress

from fastapi import Request
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    SIGNUP_UNLOCK_TTL_MINUTES,
    VISITOR_TOKEN_TTL_DAYS,
    verify_signup_unlock_token,
    verify_visitor_token,
)
from app.modules.billing import entitlements
from app.modules.core import models as core_models

ENABLED_KEY = "teaser.enabled"
GATE_CODE_KEY = "teaser.gate_code"

# The owner's chosen gate code (2026-10-26). Effective until an
# operator stores a different one in Admin -> Settings.
DEFAULT_GATE_CODE = "4823"

UNLOCK_COOKIE = "tv_signup_unlock"
# The cookie's life mirrors the token's, so the two expire together.
UNLOCK_COOKIE_MAX_AGE = SIGNUP_UNLOCK_TTL_MINUTES * 60


def teaser_enabled(db: Session) -> bool:
    """Is the teaser the public front door right now?"""
    return bool(entitlements.get_setting(db, ENABLED_KEY, False))


def _stored_code(db: Session) -> str | None:
    value = entitlements.get_setting(db, GATE_CODE_KEY, None)
    return value if isinstance(value, str) and value else None


def gate_code(db: Session) -> str:
    """The effective gate code: the operator's stored code, else
    the owner's default."""
    return _stored_code(db) or DEFAULT_GATE_CODE


def gate_code_is_custom(db: Session) -> bool:
    """True when the operator has stored a code of his own (the
    Admin panel reports this instead of ever echoing the code)."""
    return _stored_code(db) is not None


def code_matches(db: Session, candidate: str) -> bool:
    """Constant-time comparison against the effective code."""
    return hmac.compare_digest(candidate.strip(), gate_code(db))


def has_valid_unlock(request: Request) -> bool:
    """Does THIS browser hold a live signup unlock?"""
    return verify_signup_unlock_token(request.cookies.get(UNLOCK_COOKIE))


def signup_permitted(db: Session, request: Request) -> bool:
    """The one question both creation doors ask: may this caller
    create an account right now? Teaser off — always. Teaser on —
    only with the unlock."""
    return not teaser_enabled(db) or has_valid_unlock(request)


def signup_tier(db: Session, request: Request) -> str:
    """The rung a NEW account created by this browser is born at
    (open signup, owner order 2026-11-09). Both creation doors —
    email signup and social find-or-create — ask this one
    question, so the two can never drift:

    - teaser OFF: "normal". The gate is retired; signup is the
      full site, exactly as it was before the teaser existed.
    - teaser ON, browser holds a valid unlock (the operator
      code was entered): "normal" — the full site, exactly as
      the gate has always granted it.
    - teaser ON, no unlock: "downloads" — the limited level.
      Signup is OPEN (no code needed); the account reaches the
      Downloads section's member abilities and Help, and
      everything else stays dark until an operator opens it or
      launch flips the account to normal.

    A wrong code never reaches this function as a downgrade: the
    unlock endpoint refuses it with `invalid_gate_code` before
    any account exists, and the signup page treats a typed code
    as an unlock attempt first (see core/routes.py's door)."""
    return "normal" if signup_permitted(db, request) else "downloads"


# -- The teaser video (owner refinement, 2026-10-26) --------------
#
# The owner is producing a series of short teaser trailers for
# the Facebook Page; the CURRENT approved one also plays on the
# teaser page. The operator sets / replaces / clears it in
# Admin -> Settings (same panel as the switch). The file lives in
# the site's own object storage (never an external embed), under
# a site namespace:
#
#   site/assets/teaser/video/<uuid>-<name>.mp4
#   site/assets/teaser/poster/<uuid>-<name>.webp|jpg|png
#
# and the settings store remembers only the keys + display name:
#
#   teaser.video_key         — S3 key of the current MP4
#   teaser.video_poster_key  — S3 key of its poster frame
#   teaser.video_name        — original filename, for the panel
#
# No keys set = NO slot on the page: the page renders complete
# without any video element at all. The series' own constraint
# caps the MP4 at 10 MiB (the Facebook limit); the poster is a
# single frame the admin page captures in the browser at upload
# time (the API image carries no ffmpeg), capped at 2 MiB.

VIDEO_KEY = "teaser.video_key"
VIDEO_POSTER_KEY = "teaser.video_poster_key"
VIDEO_NAME_KEY = "teaser.video_name"

VIDEO_MAX_BYTES = 10 * 1024 * 1024
POSTER_MAX_BYTES = 2 * 1024 * 1024
VIDEO_CONTENT_TYPE = "video/mp4"
POSTER_CONTENT_TYPES = {"image/webp", "image/jpeg", "image/png"}
VIDEO_KEY_PREFIX = "site/assets/teaser/video/"
POSTER_KEY_PREFIX = "site/assets/teaser/poster/"


def _stored_key(db: Session, key: str) -> str:
    value = entitlements.get_setting(db, key, "")
    return value if isinstance(value, str) else ""


def video_state(db: Session) -> dict:
    """What the Admin panel shows: whether a video is set, and
    its display name. URLs and keys never ride this shape."""
    return {
        "set": bool(_stored_key(db, VIDEO_KEY)),
        "name": _stored_key(db, VIDEO_NAME_KEY),
    }


def current_video_keys(db: Session) -> tuple[str, str]:
    """(video_key, poster_key) — either may be empty."""
    return _stored_key(db, VIDEO_KEY), _stored_key(db, VIDEO_POSTER_KEY)


def set_current_video(
    db: Session, *, video_key: str, poster_key: str, name: str
) -> tuple[str, str]:
    """Point the slot at new objects; returns the OLD keys so the
    caller can delete the replaced objects from storage."""
    old = current_video_keys(db)
    entitlements.set_setting(db, VIDEO_KEY, video_key)
    entitlements.set_setting(db, VIDEO_POSTER_KEY, poster_key)
    entitlements.set_setting(db, VIDEO_NAME_KEY, name)
    return old


def clear_current_video(db: Session) -> tuple[str, str]:
    """Empty the slot; returns the old keys for storage cleanup."""
    old = current_video_keys(db)
    entitlements.set_setting(db, VIDEO_KEY, "")
    entitlements.set_setting(db, VIDEO_POSTER_KEY, "")
    entitlements.set_setting(db, VIDEO_NAME_KEY, "")
    return old


def public_video_urls(db: Session) -> tuple[str, str]:
    """(video_url, poster_url) for the anonymous landing payload:
    fresh presigned reads, minted per request like every other
    stored-file URL on the site. Empty unless the teaser is ON
    and a video is set — the off state must behave exactly as the
    pre-teaser build, and the full landing has no slot."""
    if not teaser_enabled(db):
        return "", ""
    video_key, poster_key = current_video_keys(db)
    if not video_key:
        return "", ""
    # Imported here: storage pulls in the S3 client stack, and
    # this module is imported by the landing read path.
    from app.core.storage import storage

    poster_url = storage.presigned_get_url(poster_key) if poster_key else ""
    return storage.presigned_get_url(video_key), poster_url


# -- The visitor counter (owner order, 2026-10-26) -----------------
#
# A small count of UNIQUE visitors on the teaser page: bare
# digits at the bottom-left of the page, no words, no label.
# Unique means unique BROWSERS, proven by a first-party
# "counted" cookie (a signed, purpose-scoped token from
# app.core.security, one-year life): a browser holding a valid
# one is never counted twice; a browser without one is counted
# once and issued one. Cleared cookies, a private window, or a
# second device count again — that is the honest definition of
# this counter, and no fingerprinting narrows it further.
#
# Two classes of traffic are NEVER counted (they read the
# current count and are issued nothing):
#
#   * Automation — user agents carrying a headless / bot /
#     script-client token (the build + proof rigs drive
#     headless Chromium; search crawlers and curl alike land
#     here). A missing user agent counts as automation.
#   * Operator IP exclusions — the `teaser.visit_exclude_ips`
#     setting (a JSON list of addresses and/or CIDR ranges)
#     covers the owner's own build/proof infrastructure: its
#     traffic leaves through a shared egress NAT pool, so the
#     exclusion is a range, not one address. The client address
#     is read from CF-Connecting-IP first — Cloudflare writes
#     that header at its edge and every real visitor arrives
#     through Cloudflare, so request.client (a Cloudflare edge
#     address) would be useless here; X-Forwarded-For is the
#     fallback for non-Cloudflare paths.
#
# The number itself lives in the one-row visitor_counter table
# and moves ONLY by a single atomic UPDATE (the te_pool_epoch
# pattern) — two first-time visitors arriving in the same
# instant can never lose one of the two counts.
#
# Counting runs only while teaser mode is on: the teaser page
# is the counter's only caller, so while the teaser is retired
# the number simply rests.

COUNT_COOKIE = "tv_visitor"
# The cookie's life mirrors the token's, so the two expire together.
COUNT_COOKIE_MAX_AGE = VISITOR_TOKEN_TTL_DAYS * 24 * 60 * 60

EXCLUDE_IPS_KEY = "teaser.visit_exclude_ips"

_AUTOMATION_UA_TOKENS = (
    "headless",
    "playwright",
    "puppeteer",
    "phantomjs",
    "slimerjs",
    "selenium",
    "webdriver",
    "cypress",
    "bot",
    "crawl",
    "spider",
    "curl",
    "wget",
    "python-requests",
    "python-httpx",
    "httpx",
    "aiohttp",
    "okhttp",
    "go-http-client",
    "axios",
    "node-fetch",
    "undici",
    "lighthouse",
    "pagespeed",
)


def ua_is_automation(user_agent: str | None) -> bool:
    """Headless browsers, crawlers and script clients are not
    visitors. A request with no user agent at all is treated as
    automation — real browsers always send one."""
    if not user_agent:
        return True
    ua = user_agent.lower()
    return any(token in ua for token in _AUTOMATION_UA_TOKENS)


def client_ip(request: Request) -> str:
    """The visitor's address as Cloudflare reports it (see the
    section note above); empty string when nothing usable rides
    the request."""
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def ip_is_excluded(db: Session, ip: str) -> bool:
    """Is this address on the operator's exclusion list (exact
    addresses and CIDR ranges; malformed entries are ignored)?"""
    if not ip:
        return False
    entries = entitlements.get_setting(db, EXCLUDE_IPS_KEY, [])
    if not isinstance(entries, list):
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            continue
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry.strip(), strict=False):
                    return True
            elif address == ipaddress.ip_address(entry.strip()):
                return True
        except ValueError:
            continue
    return False


TEASER_COUNTER_ID = 1


def current_count(db: Session, counter_id: int = TEASER_COUNTER_ID) -> int:
    """The count as it stands (0 before the first counted visit
    and on any database missing the seed row)."""
    value = db.scalar(
        select(core_models.VisitorCounter.count).where(
            core_models.VisitorCounter.id == counter_id
        )
    )
    return int(value) if value is not None else 0


def _increment(db: Session, counter_id: int = TEASER_COUNTER_ID) -> None:
    """One atomic UPDATE — the database adds the 1, never a
    Python read-modify-write two requests could interleave."""
    result = db.execute(
        update(core_models.VisitorCounter)
        .where(core_models.VisitorCounter.id == counter_id)
        .values(count=core_models.VisitorCounter.count + 1)
    )
    if result.rowcount == 0:
        # The seed row should always exist (migrations 0064 /
        # 0094); create it if a database ever lacks it. A
        # concurrent first insert loses on the primary key — by
        # then the row exists, so the plain bump applies on
        # retry.
        try:
            with db.begin_nested():
                db.execute(
                    insert(core_models.VisitorCounter).values(
                        id=counter_id, count=1
                    )
                )
        except IntegrityError:
            db.rollback()
            db.execute(
                update(core_models.VisitorCounter)
                .where(core_models.VisitorCounter.id == counter_id)
                .values(count=core_models.VisitorCounter.count + 1)
            )


def _record_counter_visit(
    db: Session, request: Request, *, counter_id: int, cookie_name: str
) -> tuple[int, bool]:
    """One counter's counting decision, shared by every page
    that carries one: automation UA, excluded IP, or a browser
    already holding a valid counted cookie under THIS counter's
    cookie name — read the count, change nothing, issue
    nothing. Otherwise count this browser exactly once and
    tell the route to set its cookie."""
    if ua_is_automation(request.headers.get("user-agent")):
        return current_count(db, counter_id), False
    if ip_is_excluded(db, client_ip(request)):
        return current_count(db, counter_id), False
    if verify_visitor_token(request.cookies.get(cookie_name)):
        return current_count(db, counter_id), False
    _increment(db, counter_id)
    db.commit()
    return current_count(db, counter_id), True


def record_visit(db: Session, request: Request) -> tuple[int, bool]:
    """The teaser count endpoint's whole decision, in order;
    returns (count, set_counted_cookie): teaser off reads the
    resting count and counts nobody; with the teaser on, the
    shared counting rules apply (see _record_counter_visit)."""
    if not teaser_enabled(db):
        return current_count(db), False
    return _record_counter_visit(
        db, request, counter_id=TEASER_COUNTER_ID, cookie_name=COUNT_COOKIE
    )


# -- The Downloads page counter (owner order, 2026-11-08) ----------
#
# The Downloads page carries the same quiet counter as the
# teaser: bare digits, unique browsers, the same exclusions.
# It is the Downloads page's OWN count of ITS visitors, so it
# lives in its own visitor_counter row (id 2, seeded by
# migration 0094) behind its own counted cookie — a browser
# counted on the teaser has NOT been counted here until it
# visits here, and vice versa. One difference from the teaser:
# no teaser-mode gate. The Downloads page is a live page
# regardless of the teaser switch, so its counter counts
# whenever the page is visited.

DOWNLOADS_COUNTER_ID = 2
DOWNLOADS_COUNT_COOKIE = "tv_downloads_visitor"


def downloads_count(db: Session) -> int:
    """The Downloads page's count as it stands."""
    return current_count(db, DOWNLOADS_COUNTER_ID)


def record_downloads_visit(
    db: Session, request: Request
) -> tuple[int, bool]:
    """The Downloads count endpoint's decision: the shared
    counting rules against the Downloads row and the Downloads
    cookie; no teaser gate (see the section note above)."""
    return _record_counter_visit(
        db,
        request,
        counter_id=DOWNLOADS_COUNTER_ID,
        cookie_name=DOWNLOADS_COUNT_COOKIE,
    )


# -- The 3D Print Files page counter (owner order, 2026-11-10) ----
#
# The prints shelf gets the same quiet counter as the teaser
# and Downloads: bare digits at the bottom of ITS page, unique
# browsers, the same exclusions. Its own count of its own
# visitors, so its own visitor_counter row (id 3, seeded by
# migration 0099) behind its own counted cookie — the three
# counters share the machinery and nothing else. Like
# Downloads, no teaser-mode gate: the shelf is a live page
# regardless of the teaser switch. (The shelf's own module
# gate is the route's business — prints/routes.py 404s the
# visit with the reads while the module is off for the
# public.)

PRINTS_COUNTER_ID = 3
PRINTS_COUNT_COOKIE = "tv_prints_visitor"


def prints_count(db: Session) -> int:
    """The 3D Print Files page's count as it stands."""
    return current_count(db, PRINTS_COUNTER_ID)


def record_prints_visit(
    db: Session, request: Request
) -> tuple[int, bool]:
    """The prints count endpoint's decision: the shared
    counting rules against the prints row and the prints
    cookie; no teaser gate (see the section note above)."""
    return _record_counter_visit(
        db,
        request,
        counter_id=PRINTS_COUNTER_ID,
        cookie_name=PRINTS_COUNT_COOKIE,
    )
