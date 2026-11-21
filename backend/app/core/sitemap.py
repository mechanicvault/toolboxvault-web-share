"""The public sitemap (sheet row 83, SEO plan).

Served at /sitemap.xml by the API and proxied there by nginx —
robots.txt already names that URL. Generated per request from
the canonical public routes plus every live, public 3D print
file (each has its own public page at /3dprints/<id>), so the
map updates itself as public pages and files come and go; there
is no static file to go stale.

Members-only surfaces (flyers included — the flyer shelf sits
behind sign-in) deliberately stay out: a sitemap entry a crawler
cannot open earns nothing.
"""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.email_template import SITE_URL
from app.modules.prints import models as prints_models

# (path, changefreq, priority) for the standing public pages.
_STATIC_PAGES: tuple[tuple[str, str, str], ...] = (
    ("/", "weekly", "1.0"),
    ("/landing", "weekly", "0.9"),
    ("/downloads", "monthly", "0.8"),
    ("/3dprints", "weekly", "0.9"),
)


def _url_entry(loc: str, changefreq: str, priority: str, lastmod: datetime | None) -> str:
    lines = [
        "  <url>",
        f"    <loc>{escape(loc)}</loc>",
    ]
    if lastmod is not None:
        lines.append(f"    <lastmod>{lastmod.date().isoformat()}</lastmod>")
    lines.append(f"    <changefreq>{changefreq}</changefreq>")
    lines.append(f"    <priority>{priority}</priority>")
    lines.append("  </url>")
    return "\n".join(lines)


def build_sitemap_xml(db: Session) -> str:
    """The full sitemap document for the site's public surface."""
    files = list(
        db.scalars(
            select(prints_models.PrintFile)
            .where(
                prints_models.PrintFile.status == "live",
                prints_models.PrintFile.is_public.is_(True),
            )
            .order_by(prints_models.PrintFile.created_at.asc())
        ).all()
    )
    shelf_lastmod = max((f.updated_at for f in files), default=None)

    entries: list[str] = []
    for path, changefreq, priority in _STATIC_PAGES:
        lastmod = shelf_lastmod if path == "/3dprints" else None
        entries.append(_url_entry(f"{SITE_URL}{path}", changefreq, priority, lastmod))
    for f in files:
        # The slug URL is the canonical address (row 99); a row
        # without a slug yet keeps its id URL, which resolves to
        # the same page.
        entries.append(
            _url_entry(f"{SITE_URL}/3dprints/{f.slug or f.id}", "monthly", "0.6", f.updated_at)
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
