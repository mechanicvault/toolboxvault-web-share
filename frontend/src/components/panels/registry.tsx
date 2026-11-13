import type { ReactNode } from "react";

import { AdminPanel } from "./AdminPanel";
import { BorrowingPanel } from "./BorrowingPanel";
import { ClaimsPanel } from "./ClaimsPanel";
import { CommunityPanel } from "./CommunityPanel";
import { DealersPanel } from "./DealersPanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { ForumPanel } from "./ForumPanel";
import { HomePanel } from "./HomePanel";
import { InventoryPanel } from "./InventoryPanel";
import { MaintenancePanel } from "./MaintenancePanel";
import { MarketplacePanel } from "./MarketplacePanel";
import { MessagesPanel } from "./MessagesPanel";
import { ModerationPanel } from "./ModerationPanel";
import { NotificationsPanel } from "./NotificationsPanel";
import { SearchPanel } from "./SearchPanel";
import { PartsPanel } from "./PartsPanel";
import { ReportsPanel } from "./ReportsPanel";
import { SharedToolsPanel } from "./SharedToolsPanel";
import { SupportPanel } from "./SupportPanel";
import { TruckAccountsPanel } from "./TruckAccountsPanel";
import { WishlistPanel } from "./WishlistPanel";

/**
 * Panel registry (Rail Steel conversion, Phase 1).
 *
 * Mechanism: App.tsx computes the panel content by route prefix
 * (longest matching prefix wins; sub-pages inherit their parent
 * module's panel) and passes it to AppShell as `panelContent`.
 * Settings mode (route or the rail's Settings switch) overrides
 * the panel with the settings tree via AppShell's sidebarContent
 * slot — exactly the old takeover semantics.
 *
 * Final composition (decided Phase 1):
 *  - Home panel: kicker/title → account plate → stats list →
 *    utility block (search well, then the notification note).
 *  - Every other module panel: kicker/title → utility block
 *    (search well directly under the title block, notification
 *    note under the search) → module sections.
 *
 * Phase 2a (2026-10-23): Inventory, Claims, My Parts, Community
 * Parts and Marketplace became dedicated.
 * Phase 2c (2026-10-23, the build the brief calls Phase 2b):
 * Borrowing, Maintenance, Dealers, Reports, Messages, Moderation,
 * Forum, Feedback, Wishlist, Truck Accounts and Shared Tools
 * became dedicated — every NAV module now has a dedicated panel.
 * Catalog has NO route anywhere in the app — it is embedded
 * panels inside inventory forms/detail pages (QuickAdd /
 * LocateManual) — so there is no panel slot to register for it;
 * recorded in the conversion INDEX.
 *
 * Phase 3 (2026-10-23): Admin became dedicated (AdminPanel —
 * the ADMIN_SECTIONS list, operator-gated exactly like the old
 * AdminShell nav) and AdminShell retired to a guard pass-through.
 * /account joined the panel-less set (MAPPING §3): it and
 * /choose-group render with no panel, content widened.
 */

interface PanelEntry {
  prefix: string;
  /** Panel region aria-label while this entry is showing. */
  label: string;
  /** The feature module this panel belongs to, when it has one:
   *  App suppresses the panel while that module isn't effective
   *  for the signed-in user (hidden-modules directive, 2026-10-31
   *  — a parked module leaves no sign, its panel included). */
  module?: string;
  render: () => ReactNode;
}

export const PANEL_ENTRIES: PanelEntry[] = [
  { prefix: "/inventory", label: "Inventory", module: "inventory", render: () => <InventoryPanel /> },
  { prefix: "/claims", label: "Claims", module: "claims", render: () => <ClaimsPanel /> },
  { prefix: "/parts/community", label: "Community Parts", module: "parts", render: () => <CommunityPanel /> },
  { prefix: "/parts", label: "My Parts", module: "parts", render: () => <PartsPanel /> },
  { prefix: "/marketplace", label: "Tools for sale", module: "marketplace", render: () => <MarketplacePanel /> },
  { prefix: "/shared-tools", label: "Shared tools", module: "shared_tools", render: () => <SharedToolsPanel /> },
  { prefix: "/borrowing", label: "Borrowing", module: "borrowing", render: () => <BorrowingPanel /> },
  { prefix: "/maintenance", label: "Repairs & maintenance", module: "maintenance", render: () => <MaintenancePanel /> },
  // The merged page (Repairs & Maintenance merge, 2026-11-05)
  // composes TWO modules, so its panel carries no single module
  // gate: it is never suppressed for just one of them being off.
  { prefix: "/repairs", label: "Repairs & Maintenance", render: () => <MaintenancePanel /> },
  { prefix: "/dealers", label: "Dealer directory", module: "dealers", render: () => <DealersPanel /> },
  { prefix: "/reports", label: "Reports", module: "reports", render: () => <ReportsPanel /> },
  { prefix: "/messages", label: "Messages", module: "messaging", render: () => <MessagesPanel /> },
  { prefix: "/moderation", label: "Moderation", render: () => <ModerationPanel /> },
  { prefix: "/forum", label: "Community Forum", module: "forum", render: () => <ForumPanel /> },
  { prefix: "/feedback", label: "Feedback", module: "feedback", render: () => <FeedbackPanel /> },
  { prefix: "/wishlist", label: "Wishlist", module: "wishlist", render: () => <WishlistPanel /> },
  { prefix: "/truck-accounts", label: "Truck accounts", module: "truck_accounts", render: () => <TruckAccountsPanel /> },
  { prefix: "/admin", label: "Admin", render: () => <AdminPanel /> },
  /* Home + Header program (2026-10-24): the ? door's page and
   * the bell's see-all page get panels like every other surface. */
  { prefix: "/help", label: "Help & Support", render: () => <SupportPanel /> },
  { prefix: "/notifications", label: "Notifications", render: () => <NotificationsPanel /> },
  /* Global search (2026-10-25): the header bar's results page
   * gets a panel like every other surface. */
  { prefix: "/search", label: "Search", render: () => <SearchPanel /> },
];

/** Routes that render with NO panel (content widens): the group
 *  completion gate and the public/legal pages. Unknown routes
 *  (the 404 page) also resolve to no panel. */
const PANEL_LESS_PREFIXES = [
  "/account",
  "/choose-group",
  "/terms",
  "/privacy",
  "/roadmap",
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/confirm-email-change",
  "/auth/callback",
];

export interface ResolvedPanel {
  label: string;
  content: ReactNode;
  /** The winning entry's feature module, when it carries one. */
  module?: string;
}

export function panelForRoute(pathname: string): ResolvedPanel | null {
  if (pathname === "/") {
    return { label: "Home", content: <HomePanel /> };
  }
  if (PANEL_LESS_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return null;
  }
  let best: PanelEntry | null = null;
  for (const entry of PANEL_ENTRIES) {
    if (pathname === entry.prefix || pathname.startsWith(`${entry.prefix}/`)) {
      if (!best || entry.prefix.length > best.prefix.length) best = entry;
    }
  }
  if (!best) return null;
  return { label: best.label, content: best.render(), module: best.module };
}
