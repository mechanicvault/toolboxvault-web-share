"""Disaster Claims module manifest.

Disaster Claims (owner order, 2026-11-04; claims separation
build, 2026-11-05): the insurance side of what used to be the
single claims module — claims over lost, stolen or damaged
tools after a disaster-scale event (theft, fire, flood), worked
with the owner's insurer. It is a COMPLETELY separate section
from warranty/repair Claims: its own menu item, list, filing
flow, detail pages, home widget, search group, module switch,
and its own claim-number sequence (DC-<year>-<seq>; claims
filed before the separation keep the numbers they carry).

The claim RECORDS live in the claims module's tables, kind =
insurance_disaster — the storage stays shared because the
billing lapse pin, the inventory delete guards and the item
history feed all key off claim status across kinds by design
(an open claim of either kind pins and guards its items). What
is separated is everything a user can see or touch: this module
owns the insurance section's HTTP surface, and every read/write
through it is kind-scoped in the claims service — a warranty
claim addressed here is a 404, and vice versa.

Behavior re-homed unchanged from the pre-separation claims
module: event-based draft filing with snapshotted lines,
evidence by reference plus claim uploads, the computed
checklist, deadlines with their notification job, and the claim
package (PDF / Drive / email). Insurer accounts and the insurer
directory remain a later phase — the header's insurer/policy
fields are the seam it will consume.
"""

from app.modules.disaster_claims.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="disaster_claims",
    version="0.1.0",
    description="Disaster Claims: file an insurance claim over your tools after a theft, fire or other disaster — values and photos are copied in automatically, deadlines stay in view, and your agent's details are filled in from your insurance profile.",
    route_prefix="/api/disaster-claims",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=(
        "disaster insurance claims",
        "claim targets (tool | set | set piece)",
        "evidence references and uploads",
        "communications log",
        "claim package (PDF / Drive / email)",
        "open-claim lapse pins",
        "claim deadline jobs",
    ),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Disaster Claims",
    nav_path="/disaster-claims",
    nav_order=46,
)
