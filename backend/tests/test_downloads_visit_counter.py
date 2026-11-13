"""The Downloads page visitor counter (owner order, 2026-11-08).

The teaser counter's mirror: unique BROWSERS, counted once —
a first visit bumps the Downloads row (visitor_counter id 2)
and sets its own signed, year-long counted cookie; a browser
carrying it is never counted again. Automation user agents and
operator-excluded IPs READ the count and are issued nothing.
Two differences from the teaser, both by design: the Downloads
page counts whether or not teaser mode is on (it is a live
page), and its count is fully separate from the teaser's — a
browser counted on one page has not been counted on the other.
"""

import pytest

from app.core.security import verify_visitor_token
from app.modules.billing import entitlements
from app.modules.core import teaser

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
HEADLESS_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) HeadlessChrome/126.0.0.0 Safari/537.36"
)


def _visit(client, **kwargs):
    kwargs.setdefault("headers", {"User-Agent": BROWSER_UA})
    return client.post("/api/downloads/visit", **kwargs)


def _count(db) -> int:
    db.expire_all()
    return teaser.downloads_count(db)


def _teaser_count(db) -> int:
    db.expire_all()
    return teaser.current_count(db)


# -- the counting path ---------------------------------------------------


def test_first_visit_counts_once_and_sets_a_year_cookie(client, db):
    # No teaser-mode setup anywhere: the Downloads page counts
    # with the teaser OFF (its resting production posture).
    res = _visit(client)
    assert res.status_code == 200
    assert res.json() == {"count": 1}
    set_cookie = res.headers.get("set-cookie", "")
    assert f"{teaser.DOWNLOADS_COUNT_COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert f"Max-Age={teaser.COUNT_COOKIE_MAX_AGE}" in set_cookie
    token = client.cookies.get(teaser.DOWNLOADS_COUNT_COOKIE)
    assert token and verify_visitor_token(token)
    assert _count(db) == 1


def test_counted_browser_is_never_counted_twice(client, db):
    assert _visit(client).json() == {"count": 1}
    for _ in range(3):
        res = _visit(client)
        assert res.json() == {"count": 1}
        assert "set-cookie" not in res.headers
    assert _count(db) == 1


def test_each_new_browser_counts_once(client, db):
    assert _visit(client).json() == {"count": 1}
    client.cookies.clear()  # a second browser: no counted cookie
    assert _visit(client).json() == {"count": 2}
    client.cookies.clear()  # and a third
    assert _visit(client).json() == {"count": 3}
    assert _count(db) == 3


def test_forged_counted_cookie_does_not_skip_the_count(client, db):
    res = _visit(
        client,
        headers={
            "User-Agent": BROWSER_UA,
            "Cookie": f"{teaser.DOWNLOADS_COUNT_COOKIE}=forged",
        },
    )
    assert res.json() == {"count": 1}
    token = client.cookies.get(teaser.DOWNLOADS_COUNT_COOKIE)
    assert token and token != "forged" and verify_visitor_token(token)


# -- separation from the teaser counter ------------------------------------


def test_the_two_counters_are_independent(client, db):
    entitlements.set_setting(db, teaser.ENABLED_KEY, True)
    # Count this browser on the Downloads page...
    assert _visit(client).json() == {"count": 1}
    assert _count(db) == 1
    assert _teaser_count(db) == 0
    # ...the teaser does not consider it counted: its own cookie
    # name is different, so the teaser counts it there too.
    res = client.post("/api/core/visit", headers={"User-Agent": BROWSER_UA})
    assert res.json() == {"count": 1}
    assert _teaser_count(db) == 1
    assert _count(db) == 1
    # And a fresh browser on the teaser moves only the teaser row.
    client.cookies.clear()
    res = client.post("/api/core/visit", headers={"User-Agent": BROWSER_UA})
    assert res.json() == {"count": 2}
    assert _count(db) == 1


# -- the exclusions --------------------------------------------------------


@pytest.mark.parametrize(
    "ua",
    [
        HEADLESS_UA,  # headless Chromium (the proof rigs)
        "Mozilla/5.0 Playwright/1.40",  # scripted browser driver
        "curl/8.5.0",  # script client
        "python-httpx/0.27.0",  # script client (also the TestClient default)
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "",  # no user agent at all
    ],
)
def test_automation_reads_but_is_never_counted(client, db, ua):
    res = client.post("/api/downloads/visit", headers={"User-Agent": ua})
    assert res.status_code == 200
    assert res.json() == {"count": 0}
    assert "set-cookie" not in res.headers
    assert _count(db) == 0


def test_excluded_ip_reads_but_is_never_counted(client, db):
    entitlements.set_setting(db, teaser.EXCLUDE_IPS_KEY, ["203.0.113.0/24"])
    res = _visit(
        client,
        headers={"User-Agent": BROWSER_UA, "CF-Connecting-IP": "203.0.113.9"},
    )
    assert res.json() == {"count": 0}
    assert "set-cookie" not in res.headers
    assert _count(db) == 0
    # A visitor from anywhere else still counts.
    res = _visit(
        client,
        headers={"User-Agent": BROWSER_UA, "CF-Connecting-IP": "198.51.100.7"},
    )
    assert res.json() == {"count": 1}


def test_counts_with_teaser_on_and_off_alike(client, db):
    assert _visit(client).json() == {"count": 1}
    entitlements.set_setting(db, teaser.ENABLED_KEY, True)
    client.cookies.clear()
    assert _visit(client).json() == {"count": 2}
    assert _count(db) == 2
