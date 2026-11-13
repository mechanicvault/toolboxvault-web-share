"""Messaging module manifest. FEATURE module (module doctrine,
owner 2026-10-18): the operator can disable it globally and assign
it to account groups; the seeded defaults are ALL FOUR groups —
messaging is how the community surfaces talk, and every signed-in
user may hold a conversation.

Depends on core ONLY: threads stand alone (anchors point at other
modules' records by id + title snapshot; the anchor target's
module validates the anchor at open time). The anti-spam firewall
(app/modules/messaging/spam.py) is this module's shared service —
the forum and for-sale modules consume it when they land.
"""

from app.modules.messaging.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="messaging",
    version="0.2.0",
    description="Messages: message other members about parts and tools for sale. First messages from someone new land in requests until you accept them.",
    route_prefix="/api/messaging",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("messages", "message requests", "seller profiles", "spam firewall"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    nav_label="Messages",
    nav_path="/messages",
    nav_order=55,
)
