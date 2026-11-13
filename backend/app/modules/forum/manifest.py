"""Community Forum module manifest. FEATURE module (module
doctrine, owner 2026-10-18): the operator can disable it globally
and assign it to account groups; the seeded defaults are ALL FOUR
groups — the forum is the community's common room, every member
may read and (subject to the paid-contribution gate) post.

Depends on core ONLY — deliberately. The forum consumes the
suite's shared machinery through service interfaces at request
time: the messaging spam firewall's content screen + trust
tiers, the marketplace reputation aggregate, and the pool /
marketplace public-listing resolvers for post link cards. None
of those modules needs the forum to exist.

Nav order 60: the community cluster's tail — right after
Messages (55), closing the sidebar.
"""

from app.modules.forum.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="forum",
    version="0.3.0",
    description="Community Forum: talk shop with other mechanics — questions, fixes, and trade talk.",
    route_prefix="/api/forum",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("forum categories", "forum threads", "forum posts", "forum moderation"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    nav_label="Community Forum",
    nav_path="/forum",
    nav_order=60,
)
