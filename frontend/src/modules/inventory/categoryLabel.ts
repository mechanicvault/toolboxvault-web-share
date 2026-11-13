import type { DictKey } from "../../i18n/dictionaries";
import type { CategoryRow } from "./types";

/**
 * Display name for a category row (sweep A4, 2026-11-11):
 * the four preinstalled starter categories are system data,
 * so their DISPLAY follows the reader's language through the
 * dictionary — an account seeded while its locale was English
 * still shows Baterías / Herramientas manuales / … to a
 * Spanish reader. The stored name itself is untouched: it
 * stays the filter value, the rename draft and the value
 * filed on items. User-created categories (system_key null)
 * are user data and always render exactly as written.
 */
const STARTER_KEYS: Record<string, DictKey> = {
  batteries: "inventory.categoryStarter.batteries",
  hand_tools: "inventory.categoryStarter.hand_tools",
  power_tools: "inventory.categoryStarter.power_tools",
  pneumatic_tools: "inventory.categoryStarter.pneumatic_tools",
};

export function categoryDisplayName(
  t: (key: DictKey) => string,
  row: Pick<CategoryRow, "name" | "system_key">,
): string {
  if (row.system_key && STARTER_KEYS[row.system_key]) {
    return t(STARTER_KEYS[row.system_key]);
  }
  return row.name;
}
