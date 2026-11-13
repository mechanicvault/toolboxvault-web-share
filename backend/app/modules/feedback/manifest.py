"""Feedback boards module manifest (wave 3, 2026-10-20). FEATURE
module: the operator can disable it globally and assign it to
account groups; the seeded defaults are ALL FOUR groups.

IA CHOICE (documented): ONE module, TWO boards. A post names its
board (bug | feature); the UI hangs the boards at /feedback/bugs
and /feedback/features under one "Feedback" nav entry. Statuses,
votes, comments and moderation are one code path filtered by
board — two modules would duplicate all of it for zero product
difference.

Depends on core ONLY — deliberately (the forum's doctrine): the
spam firewall + trust tiers and the inbox are consumed through
service interfaces at request time, so no sibling's kill switch
can touch the boards.

Nav order 61: right after the Community Forum (60) — the
community cluster's new tail.

DELIBERATE DEVIATION (owner decision 2026-10-20): unlike the
forum, posting is NOT paid-gated — any signed-in account, free
included, may post/vote/comment. READING was fully public under
that ruling until 2026-11-10, when Ryan reversed it (busy work
#1): the two boards are members-only reading now — anonymous
callers are refused server-side, and every registered account
(downloads level included) reads as before.
"""

from app.modules.feedback.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="feedback",
    version="1.2.0",
    description="Feedback: report a bug or ask for a feature, and see what other members have raised.",
    route_prefix="/api/feedback",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("feedback boards", "feedback posts", "feedback moderation"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    nav_label="Feedback",
    nav_path="/feedback",
    nav_order=61,
)
