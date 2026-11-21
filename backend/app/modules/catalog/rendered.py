"""Rendered page loading for the catalog lookup (row 200).

The grounded reader's raw download (grounded._fetch_html) can
only see what a page's HTML carries. A growing share of maker
and retailer pages are applications: the HTML is an empty
shell and everything the shopper sees — the specification
table, the photo gallery, the "set details" tab listing every
piece with its part number and price — is built by scripts
after the page loads. Reading those pages takes a browser,
not a download.

This module is that browser: one headless Chromium, driven
through Playwright, that opens a page the way a person would —
scripts run, then every tab is opened once so tabbed content
mounts — and hands back the loaded page: its full DOM (which
the ordinary parser reads exactly like a static page) plus a
media inventory (each photo with the text of the card around
it) the piece-photo pairing validates against.

The SSRF discipline of the raw reader is kept whole: the page
URL must pass manuals.assert_safe_url before anything loads,
and every subrequest the page makes is host-checked the same
way — a page that tries to reach a private address is cut off
at that request. Any failure raises RenderError and the
caller falls back to the raw reader: the lookup never gets
worse than the download alone.

One browser per process, renders serialized through a lock —
lookups are user-triggered and rare, and the production box
is small (2 vCPU / 4 GB). The browser is recycled on error
and every _RECYCLE_AFTER pages so a long-lived process never
accumulates a tired browser.
"""

from __future__ import annotations

import ipaddress
import threading
from urllib.parse import urlparse

from . import manuals

_RENDER_TIMEOUT_MS = 25_000
_IDLE_TIMEOUT_MS = 8_000
_MAX_TABS = 10
_RECYCLE_AFTER = 50
_MEDIA_CAP = 40
_CONTEXT_CAP = 160

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# The media inventory, read out of the loaded page: every
# image with its alt text and the text of the card around it
# (the nearest ancestor carrying a readable amount of text —
# the generic shape of a product or set-piece card). Page
# chrome — menus, banners, footers — is skipped: a mega-menu
# can carry hundreds of banner images ahead of the product's
# own pictures, and an inventory filled with those leaves no
# room for the photos that matter (the row 200 fix: the first
# live Matco read returned 40 navigation banners and none of
# the product's images). Main-content images come first.
_MEDIA_SCRIPT = """() => {
  const CHROME_TAGS = ['HEADER', 'NAV', 'FOOTER', 'ASIDE'];
  const CHROME_ROLES = ['navigation', 'banner', 'contentinfo', 'search', 'menubar'];
  const under = (el, tags, roles, mainToo) => {
    let node = el;
    for (let depth = 0; depth < 12 && node; depth++) {
      if (tags.includes(node.tagName)) return true;
      const role = node.getAttribute ? node.getAttribute('role') : null;
      if (role && roles.includes(role)) return true;
      if (mainToo && (node.tagName === 'MAIN' || role === 'main')) return 'main';
      node = node.parentElement;
    }
    return false;
  };
  const main = [];
  const rest = [];
  for (const img of document.querySelectorAll('img')) {
    const src = img.currentSrc || img.src || '';
    if (!src || src.startsWith('data:') || src.startsWith('blob:')) continue;
    if (under(img, CHROME_TAGS, CHROME_ROLES, false)) continue;
    let context = '';
    let node = img;
    for (let depth = 0; depth < 5 && node; depth++) {
      node = node.parentElement;
      if (!node) break;
      const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
      if (text.length >= 8) { context = text.slice(0, 160); break; }
    }
    const entry = { src: src, alt: (img.alt || '').slice(0, 120), context: context };
    if (under(img, [], [], true) === 'main') main.push(entry); else rest.push(entry);
  }
  return main.concat(rest).slice(0, 200);
}"""

# Scroll the page through once, top to bottom, before the
# DOM is read: lazy grids and below-the-fold panels (a set's
# piece list is the standing example) only mount their full
# contents as they approach the viewport. Generic behaviour
# — every scraper-grade reader does this — never anything
# site-specific.
_SCROLL_SCRIPT = """async () => {
  const step = Math.max(400, Math.floor(window.innerHeight * 0.9));
  let y = 0;
  while (y < document.documentElement.scrollHeight && y < 40000) {
    y += step;
    window.scrollTo(0, y);
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  window.scrollTo(0, 0);
  return y;
}"""

# Open every tab once so tabbed panels mount their content
# before the DOM is read. Generic tab behaviour only — role
# and the common tab classes — never anything site-specific.
_TABS_SCRIPT = """() => {
  const tabs = document.querySelectorAll(
    '[role="tab"]:not([aria-selected="true"]), .tab-link:not(.active), ' +
    '.nav-tabs a[data-toggle="tab"], .tabs-nav button'
  );
  const seen = [];
  for (const tab of tabs) {
    if (seen.length >= 10) break;
    const label = (tab.innerText || tab.textContent || '').trim();
    if (!label || seen.includes(label)) continue;
    seen.push(label);
    try { tab.click(); } catch (e) { /* a tab that won't open is skipped */ }
  }
  return seen.length;
}"""


class RenderError(ValueError):
    """The page couldn't be rendered — the caller falls back
    to the raw download, never to a guess."""


_lock = threading.Lock()
_playwright = None
_browser = None
_pages_served = 0


def rendered_enabled() -> bool:
    """The operator dial (Settings field, env
    RENDERED_FETCH_ENABLED). Default on; the loader itself
    also goes dark on its own when the browser machinery is
    unavailable, so a missing install degrades to the raw
    reader instead of breaking lookups."""
    try:
        from app.core.config import settings

        return bool(settings.rendered_fetch_enabled)
    except Exception:
        return True


def _host_is_public(host: str) -> bool:
    """The manuals SSRF rule for subrequests: the host must
    resolve, and every resolved address must be public."""
    if not host or host == "localhost":
        return False
    try:
        ips = manuals._host_ips(host)
    except OSError:
        return False
    if not ips:
        return False
    for raw in ips:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return False
        if not address.is_global:
            return False
    return True


def _request_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme in ("data", "blob", "about"):
        return True
    if parsed.scheme not in ("http", "https"):
        return False
    return _host_is_public(parsed.hostname or "")


def _get_browser():
    """The process's one browser, started lazily. Raises
    RenderError when the machinery isn't available."""
    global _playwright, _browser
    if _browser is not None:
        return _browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError("The page browser isn't installed.") from exc
    try:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
            ],
        )
    except Exception as exc:
        _playwright = None
        _browser = None
        raise RenderError("The page browser couldn't start.") from exc
    return _browser


def _drop_browser() -> None:
    global _playwright, _browser, _pages_served
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright is not None:
            _playwright.stop()
    except Exception:
        pass
    _playwright = None
    _browser = None
    _pages_served = 0


def render_page(url: str) -> tuple[str, list[dict]]:
    """Load one page in the browser and return (dom_html,
    media) — the serialized post-script DOM and the media
    inventory. The URL must already have passed
    manuals.assert_safe_url (grounded.validate_page_url);
    every subrequest is host-checked as it leaves. Raises
    RenderError on any failure."""
    html, media, _recordings = _render(url, record=False)
    return html, media


def render_page_recorded(url: str) -> tuple[str, list[dict], list[dict]]:
    """The same render, plus the page's recorded JSON data
    responses (rebuild Phase 1): the evidence layer's raw
    material — the payloads behind rotating lists, tabs and
    carousels, scrubbed before they are stored or read (see
    evidence.ResponseRecorder). Returns (dom_html, media,
    recordings)."""
    return _render(url, record=True)


def _render(url: str, *, record: bool) -> tuple[str, list[dict], list[dict]]:
    global _pages_served
    with _lock:
        browser = _get_browser()
        context = None
        page = None
        try:
            context = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )

            def _route(route):
                if _request_allowed(route.request.url):
                    route.continue_()
                else:
                    route.abort()

            context.route("**/*", _route)
            page = context.new_page()
            responses: list = []
            if record:

                def _collect(response):
                    responses.append(response)

                # A plain function, never a builtin like
                # list.append: Playwright's event registration
                # annotates the handler object, which builtin
                # methods refuse — passing responses.append made
                # every recorded render raise before the page
                # even loaded (found live 2026-11-20: the agent's
                # recorded view had silently never worked).
                page.on("response", _collect)
            page.goto(
                url, wait_until="domcontentloaded", timeout=_RENDER_TIMEOUT_MS
            )
            try:
                page.wait_for_load_state("networkidle", timeout=_IDLE_TIMEOUT_MS)
            except Exception:
                # A page that never goes idle (trackers,
                # polling) is still read as it stands.
                pass
            try:
                clicked = page.evaluate(_TABS_SCRIPT)
                if clicked:
                    page.wait_for_timeout(600)
                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=3_000
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            # Two scroll cycles: grids that mount in waves
            # (a first screenful, then the rest as the tab
            # settles) need the second pass to finish loading.
            for _cycle in range(2):
                try:
                    page.evaluate(_SCROLL_SCRIPT)
                    page.wait_for_timeout(400)
                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=2_000
                        )
                    except Exception:
                        pass
                except Exception:
                    break
            html = page.content()
            try:
                media = page.evaluate(_MEDIA_SCRIPT)
            except Exception:
                media = []
            if not isinstance(html, str) or "<html" not in html.lower():
                raise RenderError("That page didn't load as a web page.")
            if len(html.encode("utf-8", "replace")) > 12_000_000:
                raise RenderError("That page is too large to read.")
            recordings: list[dict] = []
            if record:
                from app.modules.catalog.evidence import ResponseRecorder

                recorder = ResponseRecorder()
                for response in responses:
                    try:
                        recorder.offer(
                            response.url,
                            response.status,
                            (response.headers or {}).get("content-type", ""),
                            response.text(),
                        )
                    except Exception:
                        # A body that can't be read (redirect,
                        # aborted fetch) is skipped, never fatal.
                        continue
                recordings = recorder.recordings
            _pages_served += 1
            if _pages_served >= _RECYCLE_AFTER:
                _drop_browser()
            return html, media if isinstance(media, list) else [], recordings
        except RenderError:
            raise
        except Exception as exc:
            _drop_browser()
            raise RenderError("Couldn't load that page in the browser.") from exc
        finally:
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
