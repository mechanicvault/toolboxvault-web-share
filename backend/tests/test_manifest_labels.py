"""C-09 census (Deep Audit Round 2): backend manifest nav
labels + display names against the canonical module-name table
(Round G standard: sentence case, one name per module). Label
consumers (my-module-prefs, signup module options) fall back to
`nav_label or name`, so a module with no declared label leaks
its raw lowercase id — every feature module must declare its
canonical name."""

from app.modules.registry import FEATURE_MODULES

CANONICAL = {
    "inventory": "Inventory",
    "shared_tools": "Shared tools",
    "borrowing": "Borrowing",
    "dealers": "Dealer directory",
    "reports": "Reports",
    "maintenance": "Repairs & maintenance",
    "claims": "Claims",
    "parts": "My Parts",
    "messaging": "Messages",
    "marketplace": "Tools for sale",
    "forum": "Community Forum",
    "wishlist": "Wishlist",
    "truck_accounts": "Truck accounts",
    "feedback": "Feedback",
    "catalog": "Product catalog",
    "support": "Help & Support",
    "tool_expansion": "Tool Expansion",
    "ai_assistant": "AI assistant",
}


def test_every_feature_module_declares_its_canonical_name():
    for module_id, expected in CANONICAL.items():
        manifest = FEATURE_MODULES[module_id]
        assert manifest.nav_label == expected, (
            f"{module_id}: nav_label {manifest.nav_label!r} != canonical "
            f"{expected!r} (prefs label would drift or fall back to the id)"
        )


def test_no_manifest_label_is_a_raw_id_or_title_case_drift():
    for module_id, manifest in FEATURE_MODULES.items():
        label = manifest.nav_label or manifest.name
        assert label != module_id, f"{module_id} label falls back to its raw id"
        assert label not in {"Tools For Sale", "Truck Accounts", "Dealers", "Maintenance"}
