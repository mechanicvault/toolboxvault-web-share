"""AI Assistant — FEATURE module manifest (module doctrine, owner
2026-10-18; spec: files/ai-token-system.md).

REPURPOSED (AI wizard completion lane, 2026-11-07 — Ryan's
entry-AI doctrine, 2026-11-06 23:54: item entry AI is the
system's biggest crutch and must be painless "by any means
necessary", so it is CORE, never a purchasable add-on).

What this module used to claim: a purchasable add-on whose
credits powered the catalog lookup chain, item identification,
manual lookups and the reports summary. What was actually
true: NO consumer ever checked this module — every AI surface
is gated by the site AI configuration (the seam below) plus
the caller's catalog / inventory / reports module access, and
per-action prices default to 0. The module sat in the
switchboard and the sales copy implying entry help was an
extra people might have to buy. It is not, and now nothing
says it is:

  - ENTRY AI STAYS CORE. The wizard lookup, photo
    identification, manual finder, drawer autofill and report
    summaries remain available wherever the inventory /
    catalog features are, independent of this module — today,
    unchanged, by design. Do not add a gate on this module to
    any entry surface.
  - THIS MODULE IS THE FUTURE GATE for the parked header AI
    ask bar (files/future-header-ai-ask-bar.md, parked
    2026-11-06, NOT built): the one AI surface that is a
    genuine luxury extra. When that bar is built, it checks
    this module; until then the module gates nothing and is
    assigned to no group (`default_groups` stays EMPTY), so
    nobody can be sold — or blocked by — a feature that does
    not exist yet.

Why repurpose instead of retire: the registry entry, tier
rows and switchboard row already exist and are consistent;
retiring would need a data migration to scrub control rows
for zero user benefit, and the ask bar will need exactly
this gate when it is unparked. The choice is REVERSIBLE —
retirement later is the same registry + copy change, made
once the ask bar's own decision lands.

The credit WALLET lives in the billing module and works
regardless of this module's state: admins can grant credits
and users can redeem credit codes ahead of launch. Wave 4
(2026-10-20) landed the provider seam —
billing/ai_service.py (provider + model + key reference and
per-action credit prices are all admin-panel settings). Until
an operator configures a provider the seam is dark: consumers
answer 503 {code: ai_not_configured} and the UI hides every
AI surface.

The router is an empty placeholder: FEATURE_MODULES never mounts
routers (only MODULES does), it exists to satisfy the manifest
contract.
"""

from fastapi import APIRouter

from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="ai_assistant",
    version="0.2.0",
    description=(
        "AI assistant add-on (coming later): an ask-anything helper in the "
        "site header. Identifying and looking up items while you add them "
        "is built into the catalog and always included — never part of "
        "this add-on."
    ),
    route_prefix="/api/billing",
    router=APIRouter(),
    always_on=False,
    dependencies=("core",),
    provides=("ai_identification", "ai_assist"),
    default_groups=(),
    # No nav entry of its own (nav_path stays None); the
    # canonical display name keeps label consumers (module
    # prefs, signup preview) off the raw id "ai_assistant"
    # (C-09 census).
    nav_label="AI assistant",
)
