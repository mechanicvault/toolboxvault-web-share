"""Flyers module manifest (owner order, 2026-11-05 19:09 #10).

Dealer flyers: every dealer company and every agent can run a
flyer spot — this week's flyer as a PDF, posted by pasting a
website link (the site downloads it through the manuals
import's SSRF guard), uploading a PDF, or photographing the
paper flyer page by page (the scanner finds the paper edges,
squares and cleans each page, and assembles one PDF). Sources
with a standing web address are pulled daily by the jobs
service. Connected users see the current flyer on the flyer
page (one tab per source), as thumbnail teasers in the Home
widget, on the dealer's Flyers tab, and as an inbox
notification with its own on/off switch when a new flyer
posts.
"""

from app.modules.flyers.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="flyers",
    version="0.1.0",
    description="Dealer flyers: this week's flyer from your dealers and agents — posted by link, PDF upload, or phone photos the site scans into one clean PDF, with a feed on Home and a tab on every dealer page.",
    route_prefix="/api/flyers",
    router=router,
    always_on=False,
    dependencies=("core", "dealers", "catalog"),
    provides=(
        "dealer and agent flyer sources",
        "flyer posting (link fetch, PDF upload, photo scan)",
        "standing flyer URL daily pull",
        "current flyer feed + per-source history",
        "new-flyer notifications (own on/off switch)",
    ),
    default_groups=("mechanic_technician", "shop_company", "tool_dealer"),
    nav_label="Flyers",
    nav_path="/flyers",
    nav_order=47,
)
