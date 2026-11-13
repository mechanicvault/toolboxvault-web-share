/**
 * SETTINGS SECTION METADATA — the single source both the settings
 * registry (settingsRegistry.tsx, which maps ids to components)
 * and the app chrome (App.tsx, which builds the gear-menu account
 * links and the sidebar Settings accordion) read from.
 *
 * TWO GROUPS, by kind (owner decisions 2026-10-19 17:39 + 17:42):
 *  - "account" — the IMPORTANT account-related information, entered
 *    from under the user's name (the gear menu): identity &
 *    security, plan & billing, insurance (Package C registers it),
 *    redeem/referrals, history & restore, export & delete.
 *  - "site" — all actual SITE settings: appearance, sharing, page
 *    customization, dealer profile, public profile & contact,
 *    notifications.
 * Since 2026-10-22 both groups also form the sidebar SETTINGS TREE
 * that takes over the one left menu column on /settings/* routes
 * (owner directive: never two menu columns) — this metadata is its
 * single source, exactly as it is for the gear menu.
 *
 * Later packages add a section by appending one entry here + one
 * component mapping in the registry — no shell changes.
 */
export type SettingsGroup = "account" | "site";

export interface SettingsSectionMeta {
  /** Route segment: /settings/<id>. Never rename (deep links). */
  id: string;
  label: string;
  group: SettingsGroup;
  /** Only accounts holding the tool_dealer group see this one. */
  dealerOnly?: boolean;
  /** Only accounts holding the shop_company group see this one. */
  shopOnly?: boolean;
  /** Only accounts holding the insurance group see this one. */
  insuranceOnly?: boolean;
  /**
   * The feature module this section is a setting FOR (settings
   * follow reach, owner ruling 2026-11-09): the section shows
   * only while that module is effective for the account — the
   * same my-modules set the nav reads. Untagged sections are
   * core account settings and always show. The server refuses
   * the matching writes for unreached modules too (PATCH /me's
   * module-owned fields, the sharing writes, and the modules'
   * own gated routes) — this gate is the honest face of that
   * rule, not the rule itself.
   */
  module?: string;
  /** Bare-minimum flag (chrome reach audit, 2026-11-09): the
   * section belongs to a group-waived account's world — the
   * downloads rung's own basics. A waived account's section
   * lists (the header user menu, the Settings tabs, the gear
   * and rail settings trees, the wizard's settings walk)
   * contain bare sections ONLY: everything else is a window
   * onto the full product it cannot reach yet (Plan & billing
   * with the AI-credits wallet, My Insurance feeding disaster
   * claims, Redeem, History & restore, Cloud backup, the
   * shop-crew surface, the module picker). The question this
   * flag answers: is this section the account's own
   * essentials, or part of the wider site? */
  bare?: boolean;
}

/** The group + reach gates, in one place: a group-gated section
 * shows only to accounts holding the named group (multi-group
 * accounts see the union, like everywhere else), and a
 * module-tagged section shows only while its module is in the
 * caller's effective set. Callers that cannot know the set yet
 * pass an empty one while it loads (tagged sections wait for
 * the read, like the nav's gated items); legacy callers with no
 * module context pass nothing and get the group gates alone. */
export function sectionVisibleFor(
  section: SettingsSectionMeta,
  accountTypes: readonly string[],
  modules?: ReadonlySet<string>,
  bareRung = false,
): boolean {
  if (section.dealerOnly && !accountTypes.includes("tool_dealer")) return false;
  if (section.shopOnly && !accountTypes.includes("shop_company")) return false;
  if (section.insuranceOnly && !accountTypes.includes("insurance")) return false;
  if (section.module && modules && !modules.has(section.module)) return false;
  // A group-waived (bare-minimum) account sees bare sections
  // only — the chrome reach rule: shared chrome enumerates
  // nothing outside the account's reach, and for a waived rung
  // "reach" over sections is exactly the bare set. Full
  // accounts pass bareRung=false and are untouched.
  if (bareRung && !section.bare) return false;
  return true;
}

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  // -- ACCOUNT (gear menu) -------------------------------------
  { id: "profile", label: "Profile", group: "account", bare: true },
  // The onboarding wizard's permanent home (design 2026-10-31):
  // progress summary + the reopen door. Account group, so the
  // wizard's own settings walk (group "site") never lists it
  // as one of its steps.
  { id: "setup", label: "Account setup", group: "account", bare: true },
  { id: "security", label: "Security & sessions", group: "account", bare: true },
  { id: "billing", label: "Plan & billing", group: "account" },
  { id: "insurance", label: "My Insurance", group: "account" },
  { id: "redeem", label: "Redeem & referrals", group: "account" },
  { id: "history", label: "History & restore", group: "account" },
  // Import matching is Inventory's matching rules (its component
  // and endpoints live in the inventory module) — reach-gated to
  // it since 2026-11-09 (settings follow reach).
  { id: "import-matching", label: "Import matching", group: "account", module: "inventory" },
  // Wave 4: automatic backups to the user's own Google Drive —
  // account group, next to Export & delete (its sibling surface).
  { id: "cloud-backup", label: "Cloud backup", group: "account" },
  { id: "data", label: "Export & delete", group: "account", bare: true },
  // -- SITE (sidebar Settings accordion) ------------------------
  // Modules FIRST in Site settings (per-user module switches,
  // owner directive 2026-10-24): the on/off list for everything
  // the account's groups entitle.
  { id: "modules", label: "Modules", group: "site" },
  { id: "appearance", label: "Appearance", group: "site", bare: true },
  // Sharing settings configure the sharing of the account's
  // inventory — reach-gated to Inventory (owner ruling
  // 2026-11-09: a user shouldn't change settings for a module
  // they can't reach; what a user shares IS their inventory).
  { id: "sharing", label: "Sharing", group: "site", module: "inventory" },
  // "Page customization" for HOME is RETIRED (dashboard
  // redesign, owner decision 2026-11-10): Home's layout is
  // edited on Home itself, per widget — the widget IS the
  // settings. The section id is gone from the registry, so the
  // gear menu, the sidebar tree, the wizard walk, and the rung
  // bare set (all of which read this list) stop offering it in
  // the same move; a stale deep link falls back like any
  // unknown section.
  { id: "custom-fields", label: "Custom fields", group: "site", module: "inventory" },
  // Wizard Phase 1 (2026-10-25): the Add wizard's per-user
  // defaults — pre-checked include sections + usual location
  // and dealer, held by the account (migration 0058). The Add
  // wizard is Inventory's, so the section follows its reach.
  { id: "wizard-defaults", label: "Add-tool wizard defaults", group: "site", module: "inventory" },
  // Dealer list customization (2026-10-31): the per-user pick
  // list for dealer entry — prefilled brands removed, own entries
  // added — beside the wizard defaults it feeds.
  { id: "dealer-list", label: "My dealer list", group: "site", module: "dealers" },
  { id: "dealer-profile", label: "Dealer profile", group: "site", dealerOnly: true, module: "dealers" },
  // Wave 3: the shop crew (owner side), the employee's own shop
  // view, and the insurer profile — each gated to its group.
  { id: "crew", label: "My crew", group: "site", shopOnly: true },
  { id: "my-shop", label: "My shop", group: "site" },
  { id: "insurer-profile", label: "Insurer profile", group: "site", insuranceOnly: true },
  { id: "public-profile", label: "Public profile & contact", group: "site", bare: true },
  { id: "notifications", label: "Notifications", group: "site", bare: true },
];

export function settingsSectionsFor(
  group: SettingsGroup,
  accountTypes: readonly string[],
  modules?: ReadonlySet<string>,
  bareRung = false,
): SettingsSectionMeta[] {
  return SETTINGS_SECTIONS.filter(
    (s) =>
      s.group === group && sectionVisibleFor(s, accountTypes, modules, bareRung),
  );
}

/** Legacy hash anchors → section ids. The old single-page Settings
 *  scrolled to #billing / #custom-fields (and Stripe returned to
 *  #billing?checkout=…); those links still land — the shell
 *  redirects them to the section route. */
export const LEGACY_SECTION_ANCHORS: Record<string, string> = {
  billing: "billing",
  "custom-fields": "custom-fields",
};
