"""The ONE email template (owner order, 2026-11-09).

Every user-facing email the site sends wears this format; only the
content block changes. Ryan's layout, in his order:

  1. HEADER — the company logo on a brand-navy masthead. The logo is
     the official coin artwork, hosted on the site's own domain
     (frontend/public/email/logo.png) so inboxes can render it; the
     wordmark also rides as real text, so the header still reads
     branded when a client blocks images.
  2. GREETING — "Hi {name}," addressed to the account by name, with
     a plain fallback when no name is known (an address with no
     account behind it: a typed share address, a dealer agent).
  3. CONTENT — the sender's own message, the only part that changes.
  4. FOOTER — the website address (linked), the brand's five social
     icons (clickable, hosted PNGs in brand colours), and a direct
     link to the recipient's notification settings on the site.

The renderer is pure: (content, name, locale, base_url) in,
(text, html) out. app.core.notifications.send_email — the single
transport seam every sender already rides — calls it for every
send, so a flow cannot opt out by accident. The text part it
returns is also what the email_outbox records, exactly as the
outbox has always recorded the sent text.

Email-client reality, by construction: table layout, inline
styles only, no image-only body (every image carries alt text and
the wordmark is text), a real plain-text alternative part, and a
600px card that holds on phone inboxes.

The social hrefs below are the site's ONE spelling of each link,
copied verbatim from the footer row's source of truth
(frontend/src/components/SocialLinks.tsx, SOCIALS) — if a handle
ever changes, change it there and here together.
"""

import html as _html
import re

SITE_URL = "https://toolboxvault.com"

# (label, href, hosted icon file) — see the module docstring for
# the source-of-truth note. Icons are the site's own footer
# glyphs rasterised to PNG (frontend/public/email/).
SOCIALS: tuple[tuple[str, str, str], ...] = (
    ("Facebook", "https://facebook.com/toolboxvault", "social-facebook.png"),
    ("Instagram", "https://instagram.com/toolboxvault", "social-instagram.png"),
    ("Threads", "https://threads.com/@toolboxvault", "social-threads.png"),
    ("TikTok", "https://tiktok.com/@toolboxvault", "social-tiktok.png"),
    ("YouTube", "https://youtube.com/@toolboxvault", "social-youtube.png"),
)

_LOGO_FILE = "logo.png"

# The real destination: Settings is a main-tab-layout page routed
# /settings/:section and "notifications" is the section id of the
# notification-preferences section (frontend settings registry).
_NOTIFICATION_SETTINGS_PATH = "/settings/notifications"

# Brand palette (the landing/navy identity): navy chrome, ink
# body text, the orange accent as the masthead rule.
_NAVY = "#0a1c38"
_INK = "#243447"
_MUTED = "#5a6b84"
_PAGE_BG = "#edf0f4"
_FOOTER_BG = "#f4f6f9"
_ACCENT = "#f2760a"
_LINK = "#17508f"

# The template's own words, per shipped locale. Content keeps
# whatever language its sender produced; only this chrome
# localizes, matching how the announcement fan-out localizes.
_COPY = {
    "en": {
        "greeting_named": "Hi {name},",
        "greeting_fallback": "Hi there,",
        "settings_link": "Manage your notification settings",
        "follow": "Follow Toolbox Vault",
    },
    "es": {
        "greeting_named": "Hola {name},",
        "greeting_fallback": "Hola,",
        "settings_link": "Administre su configuración de notificaciones",
        "follow": "Siga a Toolbox Vault",
    },
}

_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _copy(locale: str) -> dict:
    return _COPY.get((locale or "en").strip().lower(), _COPY["en"])


def _greeting(name: str | None, locale: str) -> str:
    copy = _copy(locale)
    clean = (name or "").strip()
    if clean:
        return copy["greeting_named"].format(name=clean)
    return copy["greeting_fallback"]


def _base(base_url: str | None) -> str:
    """The site's public origin for absolute links/images. The
    configured app_base_url wins; the production origin is the
    fallback so a misconfigured deploy still sends working links
    instead of relative image paths no inbox can resolve."""
    return (base_url or "").strip().rstrip("/") or SITE_URL


def render_text(
    content: str,
    *,
    name: str | None,
    locale: str,
    base_url: str | None,
    link_free: bool = False,
) -> str:
    """The plain-text part: greeting, the sender's content
    verbatim, then the footer lines (site, settings link, socials
    as name + URL — a text part has no clickable icons, so the
    addresses ride in full).

    `link_free` (the message-notification family only): the
    footer shrinks to the brand name alone — no URL of any kind,
    per that family's discipline (see render_email)."""
    base = _base(base_url)
    copy = _copy(locale)
    lines = [
        _greeting(name, locale),
        "",
        (content or "").strip(),
        "",
        "—",
        "Toolbox Vault",
    ]
    if not link_free:
        lines[5] = f"Toolbox Vault · {base}"
        lines += [
            f"{copy['settings_link']}: {base}{_NOTIFICATION_SETTINGS_PATH}",
            "",
            f"{copy['follow']}:",
        ]
        lines += [f"{label}: {href}" for label, href, _ in SOCIALS]
    return "\n".join(lines)


def _content_html(content: str, *, link_free: bool = False) -> str:
    """The sender's plain-text content as body HTML: escaped
    first, split into paragraphs on blank lines, single newlines
    become line breaks, and bare URLs become clickable links (the
    verify/reset flows put their one action link in the content —
    an inbox must be able to tap it). `link_free` skips the
    linkification — that family's content carries no URLs by
    construction, and none may be manufactured for it."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", (content or "").strip()):
        escaped = _html.escape(block.strip())
        linked = (
            escaped
            if link_free
            else _URL_RE.sub(
                lambda m: (
                    f'<a href="{m.group(0)}" '
                    f'style="color:{_LINK};text-decoration:underline;">{m.group(0)}</a>'
                ),
                escaped,
            )
        )
        paragraphs.append(
            '<p style="margin:0 0 16px 0;font-size:15px;line-height:1.55;'
            f'color:{_INK};">{linked.replace(chr(10), "<br>")}</p>'
        )
    return "".join(paragraphs)


def render_html(
    content: str,
    *,
    name: str | None,
    locale: str,
    base_url: str | None,
    link_free: bool = False,
) -> str:
    """The HTML part: masthead, greeting + content, footer —
    tables and inline styles only, per the module docstring.

    `link_free`: the same frame with the link layer removed —
    no anchors, no hosted images (the masthead is the navy band
    + wordmark text alone), no URLs in the footer (the brand
    name alone). See render_email for why the variant exists."""
    base = _base(base_url)
    copy = _copy(locale)
    greeting = _html.escape(_greeting(name, locale))
    settings_url = f"{base}{_NOTIFICATION_SETTINGS_PATH}"
    if link_free:
        masthead_inner = (
            '<td style="font-family:Arial,Helvetica,sans-serif;font-size:22px;'
            'font-weight:bold;color:#ffffff;letter-spacing:0.2px;">Toolbox Vault</td>'
        )
        footer_inner = (
            '<span style="font-size:15px;font-weight:bold;'
            f'color:{_NAVY};">Toolbox Vault</span>'
        )
    else:
        masthead_inner = (
            f'<td style="padding-right:14px;"><img src="{base}/email/{_LOGO_FILE}" '
            'width="44" height="44" alt="Toolbox Vault" style="display:block;border:0;"></td>'
            '<td style="font-family:Arial,Helvetica,sans-serif;font-size:22px;'
            'font-weight:bold;color:#ffffff;letter-spacing:0.2px;">Toolbox Vault</td>'
        )
        social_cells = "".join(
            '<td style="padding:0 5px;">'
            f'<a href="{href}" target="_blank" rel="noopener noreferrer">'
            f'<img src="{base}/email/{icon}" width="24" height="24" alt="{label}" '
            'style="display:block;border:0;"></a></td>'
            for label, href, icon in SOCIALS
        )
        footer_inner = (
            f'<a href="{base}" style="font-size:15px;font-weight:bold;'
            f'color:{_NAVY};text-decoration:none;">toolboxvault.com</a>'
            '<table role="presentation" cellpadding="0" cellspacing="0" align="center" '
            f'style="margin:12px auto 4px auto;"><tr>{social_cells}</tr></table>'
            f'<p style="margin:8px 0 0 0;font-size:13px;line-height:1.5;color:{_MUTED};">'
            f'<a href="{settings_url}" style="color:{_LINK};text-decoration:underline;">'
            f"{copy['settings_link']}</a></p>"
        )
    return f"""<!DOCTYPE html>
<html lang="{_html.escape((locale or 'en').strip().lower())}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:{_PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_PAGE_BG};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;background-color:#ffffff;border-radius:10px;overflow:hidden;">
<tr><td style="background-color:{_NAVY};padding:20px 28px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
{masthead_inner}
</tr></table>
</td></tr>
<tr><td style="background-color:{_ACCENT};font-size:0;line-height:0;" height="3">&nbsp;</td></tr>
<tr><td style="padding:28px;font-family:Arial,Helvetica,sans-serif;">
<p style="margin:0 0 16px 0;font-size:15px;line-height:1.55;color:{_INK};">{greeting}</p>
{_content_html(content, link_free=link_free)}
</td></tr>
<tr><td style="background-color:{_FOOTER_BG};padding:20px 28px;font-family:Arial,Helvetica,sans-serif;" align="center">
{footer_inner}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_email(
    content: str,
    *,
    name: str | None = None,
    locale: str = "en",
    base_url: str | None = None,
    link_free: bool = False,
) -> tuple[str, str]:
    """(text, html) for one send. The seam calls this for every
    email; the parts differ only in medium, never in message.

    LINK-FREE VARIANT — one family, named on purpose: the
    message-notification email (messaging, 2026-10-19) is
    content-free BY DESIGN and carries NO links of any kind, so
    a mail client or a forwarded inbox can never become a side
    channel into a private conversation. It wears the template's
    frame (masthead band, greeting, footer band) with every
    link, URL and hosted image removed — the one sender that
    cannot carry the template's link layer, recorded in the
    lane INDEX with this reason."""
    return (
        render_text(content, name=name, locale=locale, base_url=base_url, link_free=link_free),
        render_html(content, name=name, locale=locale, base_url=base_url, link_free=link_free),
    )
