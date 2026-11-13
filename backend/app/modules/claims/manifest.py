"""Claims module manifest.

Claims (blueprint §15, owner spec 2026-10-18/19, two-types
rebuild 2026-10-25, SEPARATED 2026-11-05): WARRANTY & REPAIR
claims only — a tool breaks, the claim runs through the owner's
own dealer agent (never the whole dealer company), and both
seats track it on the same page. Claims target a tool, a whole
set (with the include-addons choice asked and STORED), or a
single set piece; lines are priced and snapshotted so a claim
never drifts. Items on an OPEN claim are pinned active against
a lapse (the billing pin registry) and can't be deleted out
from under the claim (the inventory delete guards) — both wired
through registries in service.py, so this module can be removed
without either engine noticing.

INSURANCE (disaster) claims are a separate module now —
disaster_claims — with its own section, switch and numbering.
The claim records share one table (kind-scoped in service.py)
because the pin/guard/history seams key off claim status across
kinds; nothing user-facing is shared.
"""

from app.modules.claims.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="claims",
    version="0.5.0",
    description="Claims: warranty and repair claims that run through your own dealer agent (never the whole dealer company) — open one from a broken tool and track the repair together on the same page. (Insurance claims after a disaster live in Disaster Claims.)",
    route_prefix="/api/claims",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=(
        "warranty and repair claims with dealers",
        "claim targets (tool | set | set piece)",
        "evidence references and uploads",
        "communications log",
        "open-claim lapse pins",
    ),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Claims",
    nav_path="/claims",
    nav_order=45,
)
