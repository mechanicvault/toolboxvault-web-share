"""The teaser visitor counter (owner order, 2026-10-26).

Unique BROWSERS, counted once: a first visit bumps the one-row
counter and sets a signed, year-long counted cookie; a browser
carrying it is never counted again. Automation user agents and
operator-excluded IPs READ the count and are issued nothing —
the owner's own build/proof traffic must never inflate the
number. Counting runs only while teaser mode is on.
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


def _teaser_on(db):
    entitlements.set_setting(db, teaser.ENABLED_KEY, True)


def _visit(client, **kwargs):
    kwargs.setdefault("headers", {"User-Agent": BROWSER_UA})
    return client.post("/api/core/visit", **kwargs)


def _count(db) -> int:
    db.expire_all()
    return teaser.current_count(db)


# -- the counting path ---------------------------------------------------


def test_first_visit_counts_once_and_sets_a_year_cookie(client, db):
    _teaser_on(db)
    res = _visit(client)
    assert res.status_code == 200
    assert res.json() == {"count": 1}
    set_cookie = res.headers.get("set-cookie", "")
    assert f"{teaser.COUNT_COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert f"Max-Age={teaser.COUNT_COOKIE_MAX_AGE}" in set_cookie
    token = client.cookies.get(teaser.COUNT_COOKIE)
    assert token and verify_visitor_token(token)
    assert _count(db) == 1


def test_counted_browser_is_never_counted_twice(client, db):
    _teaser_on(db)
    assert _visit(client).json() == {"count": 1}
    # The TestClient jar now carries the counted cookie, like a
    # returning browser: further loads read, never bump.
    for _ in range(3):
        res = _visit(client)
        assert res.json() == {"count": 1}
        assert "set-cookie" not in res.headers
    assert _count(db) == 1


def test_each_new_browser_counts_once(client, db):
    _teaser_on(db)
    assert _visit(client).json() == {"count": 1}
    client.cookies.clear()  # a second browser: no counted cookie
    assert _visit(client).json() == {"count": 2}
    client.cookies.clear()  # and a third
    assert _visit(client).json() == {"count": 3}
    assert _count(db) == 3


def test_forged_counted_cookie_does_not_skip_the_count(client, db):
    _teaser_on(db)
    res = _visit(
        client, headers={"User-Agent": BROWSER_UA, "Cookie": f"{teaser.COUNT_COOKIE}=forged"}
    )
    assert res.json() == {"count": 1}
    token = client.cookies.get(teaser.COUNT_COOKIE)
    assert token and token != "forged" and verify_visitor_token(token)


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
    _teaser_on(db)
    res = client.post("/api/core/visit", headers={"User-Agent": ua})
    assert res.status_code == 200
    assert res.json() == {"count": 0}
    assert "set-cookie" not in res.headers
    assert _count(db) == 0


def test_excluded_ip_reads_but_is_never_counted(client, db):
    _teaser_on(db)
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


def test_exact_ip_exclusion_and_bad_entries_ignored(client, db):
    _teaser_on(db)
    entitlements.set_setting(
        db, teaser.EXCLUDE_IPS_KEY, ["not-an-ip", "198.51.100.7", 42]
    )
    res = _visit(
        client,
        headers={"User-Agent": BROWSER_UA, "CF-Connecting-IP": "198.51.100.7"},
    )
    assert res.json() == {"count": 0}
    assert _count(db) == 0


# -- posture -----------------------------------------------------------------


def test_no_counting_while_teaser_is_off(client, db):
    # Default posture: teaser off. The endpoint answers with the
    # resting count and counts nobody — the merged landing has
    # no counter and nothing accrues behind its back.
    res = _visit(client)
    assert res.json() == {"count": 0}
    assert "set-cookie" not in res.headers
    assert _count(db) == 0
