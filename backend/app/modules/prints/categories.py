"""The 3D print category set (owner order 2026-11-08).

This is the prints shelf's OWN vocabulary — deliberately NOT
the tool categories (a print of a socket rail is not a tool,
and the two sets answer different questions). The definitions
live here in code; the display names live in the i18n
dictionary under `prints.category.<key>` in both locales,
the Part 1 downloads-catalog posture: definitions in code,
copy in the dictionary, the database stores only the key.

The set is mechanic / tool / toolbox only — the shelf's topic
rule (owner order): every category below is a thing a mechanic
prints FOR the shop. There is no general-purpose bucket; the
closest is `other-shop`, which is still shop prints.
"""

CATEGORIES: tuple[str, ...] = (
    "tool-holders",
    "toolbox-drawer",
    "socket-wrench",
    "diagnostic-aids",
    "shop-fixtures",
    "battery-mounts",
    "air-tool",
    "vehicle-specific",
    "parts-trays",
    "other-shop",
)

CATEGORY_KEYS = frozenset(CATEGORIES)


def is_category(key: str) -> bool:
    return key in CATEGORY_KEYS
