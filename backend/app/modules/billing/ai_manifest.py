"""AI Assistant — FEATURE module manifest.

ENTRY AI IS CORE, never a purchasable add-on: item entry AI
is the system's biggest crutch and must be painless, so the
wizard lookup, photo identification, manual finder, drawer
autofill and report summaries remain available wherever the
inventory / catalog features are, independent of this module.
Do not add a gate on this module to any entry surface. Every
AI surface is gated by the site AI configuration (the provider
seam in billing/ai_service.py) plus the caller's own module
access, and per-action prices default to 0.

THIS MODULE IS THE FUTURE GATE for the parked header AI ask
bar: the one AI surface that is a genuine luxury extra. When
that bar is built, it checks this module; until then the
module gates nothing and is assigned to no group
(`default_groups` stays EMPTY), so nobody can be sold — or
blocked by — a feature that does not exist yet. The registry
entry is kept (rather than retired) because the ask bar will
need exactly this gate, and retiring would need a data
migration to scrub control rows for zero user benefit.

The credit WALLET lives in the billing module and works
regardless of this module's state: admins can grant credits
and users can redeem credit codes ahead of launch. Until an
operator configures a provider the seam is dark: consumers
answer 503 {code: ai_not_configured} and the UI hides every AI
surface. The router is an empty placeholder: FEATURE_MODULES
never mounts routers (only MODULES does); it exists to satisfy
the manifest contract."""

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
