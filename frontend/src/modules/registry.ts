import { createElement, lazy, type ReactNode } from "react";

import { ArtIcon } from "../components/ArtIcon";
import { ALL_ACCOUNT_TYPES, type AccountType } from "./core/accountTypes";

export interface FrontendModule {
  /** Unique id, mirrors the backend module name. */
  name: string;
  /** Route path. */
  path: string;
  /** Label shown in the nav. */
  label: string;
  /** Leading glyph for the icon-forward nav presentations (the
   *  top-bar strip and the rail). The sidebar presentation predates
   *  icons and stays label-only, so the default layout is pixel-
   *  identical whether or not a module declares one. */
  icon?: ReactNode;
  /** Nav ordering is config-driven (see blueprint law 7). */
  navOrder: number;
  /** False for routes that exist but don't appear in the nav (detail/edit/auth). */
  showInNav?: boolean;
  /**
   * The account groups this module serves. Nav visibility is a UNION:
   * the entry shows when ANY of the signed-in user's groups is in
   * this list. Declare a narrower list to make a module group-only —
   * e.g. the future dealer portal gets `groups: ["tool_dealer"]`.
   * Most modules serve all four groups; inventory is the exception
   * (mechanics only, owner directive 2026-10-17).
   */
  groups: AccountType[];
  /**
   * The backend FEATURE module this route belongs to (module
   * doctrine, owner 2026-10-18), when it belongs to one. Entries
   * with a featureModule render only while that module is effective
   * for the user (GET /api/core/my-modules — the operator's switch
   * and assignment, server-resolved); direct navigation to an
   * ineffective module's route lands on the "isn't enabled" panel
   * (ModuleGate in App.tsx). The `groups` list above remains the
   * coarse pre-filter the shell has always used; my-modules is the
   * authority. Core routes declare no featureModule — core is
   * infrastructure, never gated.
   */
  featureModule?: string;
  /**
   * Alternative to featureModule for routes with TWO seats: the
   * route renders while ANY of the listed modules is effective for
   * the user. The claim detail page is the case (claims two-types,
   * 2026-10-25): the owner seat rides the claims module, the dealer
   * party seat rides the dealers module — the API enforces the same
   * split per claim, so the route gate must not dead-end a dealer
   * following a claim addressed to their company.
   */
  featureModuleAnyOf?: string[];
  /** Lazily loaded so modules don't bloat the initial bundle. */
  element: React.LazyExoticComponent<() => React.JSX.Element>;
}

/**
 * Frontend module registry — mirrors backend/app/modules/registry.py.
 * To add a module: add its page under src/modules/<name>/ and one entry here.
 * To reorder the nav: change navOrder. No rebuild of other modules needed.
 */
export const MODULES: FrontendModule[] = [
  {
    name: "core",
    path: "/",
    label: "Home",
    icon: createElement(ArtIcon, { name: "home" }),
    navOrder: 0,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./core/HomePage")),
  },
  {
    // The official landing page's own seat (the Combination,
    // promoted 2026-11-08): its public home is "/" behind the
    // teaser (HomePage serves it to signed-out visitors when
    // the teaser is off), but at "/" a signed-in user gets
    // their home — this seat exists so a signed-in user can
    // open the landing itself; the header's Testing link
    // points here (owner: "so I can view it when I want to").
    // Not a nav item, never gated. Signed out, the teaser
    // wall still bounces this path to the teaser while the
    // teaser is on, so the page stays hidden behind it.
    name: "core-landing",
    path: "/landing",
    label: "Landing page",
    navOrder: 102,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/LandingComboPage")),
  },
  {
    // Legal pages (audit A1, 2026-10-22): the app's published
    // Terms/Privacy ported to the website, adapted to website
    // reality (Stripe billing, Resend email, 20-item free tier).
    // Public, not a nav item, never gated (core infrastructure).
    name: "core-terms",
    path: "/terms",
    label: "Terms of Service",
    navOrder: 100,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() =>
      import("./core/LegalPage").then((m) => ({ default: m.TermsPage })),
    ),
  },
  {
    name: "core-privacy",
    path: "/privacy",
    label: "Privacy Policy",
    navOrder: 101,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() =>
      import("./core/LegalPage").then((m) => ({ default: m.PrivacyPage })),
    ),
  },
  {
    // Help & Support (Home + Header program, 2026-10-24): the ?
    // header door's page — terms link, forum link, and the
    // support module's ticket desk. Not a nav item (the header ?
    // is its door); the page itself is core infrastructure and
    // never gated — the TICKETS section inside hides itself when
    // the support module is off for the user.
    name: "support-help",
    path: "/help",
    label: "Help & Support",
    navOrder: 97,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./support/HelpSupportPage")),
  },
  {
    // How-to videos (owner, 2026-11-06): the Help page's
    // videos tab promoted to its own main-tab-layout page —
    // the Home widget's "View all videos" door. Same
    // operator-managed list, same support-module data (the
    // page says so plainly when the module is off). Not a nav
    // item: the widget button and Help are its doors.
    name: "support-videos",
    path: "/how-to-videos",
    label: "How-to videos",
    navOrder: 96,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./support/HowToVideosPage")),
  },
  {
    // Notifications (Home + Header program, 2026-10-24): the
    // bell popup's "see all" target — the full inbox page.
    name: "core-notifications",
    path: "/notifications",
    label: "Notifications",
    navOrder: 98,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/NotificationsPage")),
  },
  {
    // Global search results (owner spec, 2026-10-25): where the
    // header search bar lands — the user's own records everywhere,
    // grouped by kind of record. Core infrastructure: never gated
    // itself (the RESULTS respect each module's switches on the
    // server), not a nav item.
    name: "core-search",
    path: "/search",
    label: "Search",
    navOrder: 97,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/SearchPage")),
  },
  {
    // Admin support desk (Home + Header program, 2026-10-24):
    // the operator side of the ticket system, inside Admin.
    name: "admin-support",
    path: "/admin/support",
    label: "Support tickets",
    navOrder: 107,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    // Roadmap (audit A15, 2026-10-22): the operator-published
    // "What's coming" page. Public, not a nav item, never gated.
    name: "core-roadmap",
    path: "/roadmap",
    label: "What's coming",
    navOrder: 102,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/RoadmapPage")),
  },
  {
    // Downloads (2026-10-29 as the bare lead-magnet door; a real
    // main-tab page since 2026-11-08): About + Documents, all
    // public and free — and exempt from the teaser wall by exact
    // path (core/teaser.tsx). A MAIN NAV item since 2026-11-09
    // (owner's direct order): a plain link in the rail for every
    // account group, deliberately NO featureModule and no
    // PUBLIC_FAMILY seat, so no module switch can gate it away
    // from anyone; signed out (no rail), the shell's strip
    // carries the same item as a plain header link (App.tsx's
    // downloadsLink). Seated at the rail's tail (65, after
    // Feedback) — the free-resources door closes the list,
    // above the app-appended Settings. Since 2026-11-10 the
    // PAGE renders in the full shell like every other page
    // (owner: "part of the main site"); only its teaser-wall
    // exemption — who may view it signed out — sets it apart.
    name: "core-downloads",
    path: "/downloads",
    label: "Downloads",
    icon: createElement(ArtIcon, { name: "downloads" }),
    navOrder: 65,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./core/DownloadsPage")),
  },
  {
    // 3D Print Files (Downloads Part 2, 2026-11-08): the
    // shelf's own page, reached through the Downloads page's
    // door tab. PUBLIC for reading like the forum's — no
    // featureModule on the read routes (the API answers
    // signed-out visitors; writes ride the session + module
    // gate server-side). Not a nav item: the Downloads door
    // is its seat. Canonical seat is the clean top-level
    // /3dprints (owner, 2026-11-08 21:03 — directly linkable,
    // shareable, teaser-open like /downloads); the original
    // /downloads/prints paths survive only as App-level
    // redirects to these routes.
    name: "downloads-prints",
    path: "/3dprints",
    label: "3D Print Files",
    navOrder: 104,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./prints/BrowsePage")),
  },
  {
    name: "downloads-prints-detail",
    path: "/3dprints/:fileId",
    label: "3D Print Files",
    navOrder: 104,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./prints/DetailPage")),
  },
  {
    // Publishing is members-only: the feature module gate +
    // RequireAuth, the marketplace-new posture.
    name: "downloads-prints-upload",
    featureModule: "prints",
    path: "/3dprints/upload",
    label: "Upload a print file",
    navOrder: 104,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./prints/UploadPage")),
  },
  {
    // The publisher's listing edit (owner, 2026-11-08):
    // title / description / category, the photo set and the
    // one showcase video — never the file's version. The
    // same members-only posture as the upload door; the
    // server confines it to the listing's own publisher.
    name: "downloads-prints-edit",
    featureModule: "prints",
    path: "/3dprints/:fileId/edit",
    label: "Edit print listing",
    navOrder: 104,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./prints/EditPage")),
  },
  {
    name: "core-login",
    path: "/login",
    label: "Log in",
    navOrder: 90,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/LoginPage")),
  },
  {
    name: "core-signup",
    path: "/signup",
    label: "Sign up",
    navOrder: 91,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/SignupPage")),
  },
  {
    name: "core-account",
    path: "/account",
    label: "Account",
    navOrder: 92,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/AccountPage")),
  },
  {
    name: "core-auth-callback",
    path: "/auth/callback",
    label: "Sign in",
    navOrder: 93,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/OAuthCallbackPage")),
  },
  {
    name: "core-choose-group",
    path: "/choose-group",
    label: "Choose your groups",
    navOrder: 96,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/ChooseGroupPage")),
  },
  {
    name: "core-forgot-password",
    path: "/forgot-password",
    label: "Forgot password",
    navOrder: 97,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/ForgotPasswordPage")),
  },
  {
    name: "core-reset-password",
    path: "/reset-password",
    label: "Reset password",
    navOrder: 98,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/ResetPasswordPage")),
  },
  {
    name: "core-confirm-email-change",
    path: "/confirm-email-change",
    label: "Confirm email change",
    navOrder: 99,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/ConfirmEmailChangePage")),
  },
  {
    name: "core-verify-email",
    path: "/verify-email",
    label: "Verify email",
    navOrder: 100,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/auth/VerifyEmailPage")),
  },
  {
    name: "core-style-guide",
    path: "/style-guide",
    label: "Style guide",
    navOrder: 94,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/StyleGuidePage")),
  },
  {
    // Account setup — the onboarding wizard's hub (owner design
    // 2026-10-31, built 2026-11-07). Not a nav item: reached from
    // the Home setup banner, Settings → Account setup, and the
    // new-feature notification's deep link.
    name: "core-setup",
    path: "/setup",
    label: "Account setup",
    navOrder: 94,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/SetupPage")),
  },
  {
    name: "core-settings",
    path: "/settings",
    label: "Settings",
    navOrder: 95,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/SettingsPage")),
  },
  {
    // One route per settings section (settings restructure, owner
    // review round 1): the shell renders the section named by the
    // segment from the section registry; /settings itself lands
    // on the first account section. Declared AFTER "/settings" —
    // React Router ranks the static path above the parameter.
    name: "core-settings-section",
    path: "/settings/:section",
    label: "Settings",
    navOrder: 95,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/SettingsPage")),
  },
  {
    name: "inventory",
    featureModule: "inventory",
    path: "/inventory",
    label: "Inventory",
    icon: createElement(ArtIcon, { name: "inventory" }),
    navOrder: 10,
    // Inventory belongs to mechanics (owner directive 2026-10-17) —
    // other groups never see it in the nav. The API enforces the
    // same gate server-side.
    groups: ["mechanic_technician"],
    element: lazy(() => import("./inventory/ToolListPage")),
  },
  {
    name: "inventory-new",
    featureModule: "inventory",
    path: "/inventory/new",
    label: "Add tool",
    navOrder: 11,
    groups: ["mechanic_technician"],
    showInNav: false,
    // Wizard Phase 1 (owner-confirmed 2026-10-25): adding always
    // opens the wizard ("Is it a battery?" fork). Editing stays
    // on the full form below.
    element: lazy(() => import("./inventory/AddWizardPage")),
  },
  {
    name: "inventory-detail",
    featureModule: "inventory",
    path: "/inventory/:id",
    label: "Tool",
    navOrder: 12,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/ToolDetailPage")),
  },
  {
    name: "inventory-edit",
    featureModule: "inventory",
    path: "/inventory/:id/edit",
    label: "Edit tool",
    navOrder: 13,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/ToolFormPage")),
  },
  {
    name: "inventory-battery-new",
    featureModule: "inventory",
    path: "/inventory/batteries/new",
    label: "Add battery",
    navOrder: 14,
    groups: ["mechanic_technician"],
    showInNav: false,
    // Wizard Phase 1: same wizard as /inventory/new — the page
    // reads this path and starts with the battery branch answered.
    element: lazy(() => import("./inventory/AddWizardPage")),
  },
  {
    name: "inventory-import",
    featureModule: "inventory",
    path: "/inventory/import",
    label: "Import spreadsheet",
    navOrder: 15,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/ImportPage")),
  },
  {
    name: "inventory-battery-detail",
    featureModule: "inventory",
    path: "/inventory/batteries/:id",
    label: "Battery",
    navOrder: 15,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/BatteryDetailPage")),
  },
  {
    // QR bin labels (blueprint §18): the print surface. Gated by
    // the inventory feature module like every inventory route —
    // direct navigation while the module is off lands on the
    // "isn't enabled" panel.
    name: "inventory-labels",
    featureModule: "inventory",
    path: "/inventory/labels",
    label: "Print labels",
    navOrder: 17,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/LabelsPrintPage")),
  },
  {
    // Canonical kind URLs — what the item labels' QR codes encode.
    // Aliases only: they redirect to the detail routes above.
    name: "inventory-tool-alias",
    featureModule: "inventory",
    path: "/inventory/tool/:id",
    label: "Tool",
    navOrder: 18,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() =>
      import("./inventory/KindRedirect").then((m) => ({ default: m.ToolKindRedirect })),
    ),
  },
  {
    name: "inventory-battery-alias",
    featureModule: "inventory",
    path: "/inventory/battery/:id",
    label: "Battery",
    navOrder: 19,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() =>
      import("./inventory/KindRedirect").then((m) => ({ default: m.BatteryKindRedirect })),
    ),
  },
  {
    // Health Check (gap wave 1): the claim-readiness scan.
    name: "inventory-health",
    featureModule: "inventory",
    path: "/inventory/health",
    label: "Health Check",
    navOrder: 16,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/HealthCheckPage")),
  },
  {
    // Categories & tags manager (gap wave 1).
    name: "inventory-categories",
    featureModule: "inventory",
    path: "/inventory/categories",
    label: "Categories & tags",
    navOrder: 16,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/CategoriesPage")),
  },
  {
    name: "inventory-battery-edit",
    featureModule: "inventory",
    path: "/inventory/batteries/:id/edit",
    label: "Edit battery",
    navOrder: 16,
    groups: ["mechanic_technician"],
    showInNav: false,
    element: lazy(() => import("./inventory/BatteryFormPage")),
  },
  {
    // Used Parts (blueprint §18): the spare-parts shelf — the
    // owner's own customizable entries on their own location tree.
    // Core-only dependency (backend manifest carries the same
    // defaults; my-modules is the authority). Nav sits right after
    // Asset Inventory.
    name: "parts",
    featureModule: "parts",
    path: "/parts",
    label: "My Parts",
    icon: createElement(ArtIcon, { name: "parts" }),
    navOrder: 15,
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./parts/PartsPage")),
  },
  {
    name: "parts-new",
    featureModule: "parts",
    path: "/parts/new",
    label: "Add part",
    navOrder: 21,
    groups: ["mechanic_technician", "shop_company"],
    showInNav: false,
    element: lazy(() => import("./parts/PartFormPage")),
  },
  {
    name: "parts-detail",
    featureModule: "parts",
    path: "/parts/:id",
    label: "Part",
    navOrder: 22,
    groups: ["mechanic_technician", "shop_company"],
    showInNav: false,
    element: lazy(() => import("./parts/PartDetailPage")),
  },
  {
    name: "parts-edit",
    featureModule: "parts",
    path: "/parts/:id/edit",
    label: "Edit part",
    navOrder: 23,
    groups: ["mechanic_technician", "shop_company"],
    showInNav: false,
    element: lazy(() => import("./parts/PartFormPage")),
  },
  {
    // Community Parts pool (2026-10-19): every user's publicly
    // listed parts, searchable by year / make / model / engine.
    // Deliberately NO featureModule: the pool is readable by all
    // groups (and, signed out, through the same page's public
    // payload) — the API gates the surfaces that need gating
    // (owner controls ride the parts module; the listings
    // themselves check only the pool switch).
    name: "parts-community",
    path: "/parts/community",
    label: "Community Parts",
    icon: createElement(ArtIcon, { name: "people" }),
    navOrder: 18,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./parts/CommunityPartsPage")),
  },
  {
    // Tools For Sale (2026-10-19): the community board (blueprint
    // §9's wanted/for-sale board folded in). Deliberately NO
    // featureModule on the board + detail: readable by all groups
    // and, signed out, through the same pages' public payload —
    // the API gates the contributing surfaces (owner pages below
    // ride the marketplace module; the board itself checks only
    // the marketplace switches).
    name: "marketplace",
    path: "/marketplace",
    label: "Tools for sale",
    icon: createElement(ArtIcon, { name: "marketplace" }),
    navOrder: 19,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./marketplace/pages").then((m) => ({ default: m.MarketplaceBoardPage }))),
  },
  {
    name: "marketplace-listing",
    path: "/marketplace/:id",
    label: "Listing",
    navOrder: 20,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./marketplace/pages").then((m) => ({ default: m.MarketplaceListingPage }))),
  },
  {
    name: "marketplace-mine",
    featureModule: "marketplace",
    path: "/marketplace/mine",
    label: "My listings & deals",
    navOrder: 21,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./marketplace/MyListingsPage")),
  },
  {
    name: "marketplace-new",
    featureModule: "marketplace",
    path: "/marketplace/new",
    label: "List an item",
    navOrder: 22,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./marketplace/ListingFormPage")),
  },
  {
    name: "marketplace-edit",
    featureModule: "marketplace",
    path: "/marketplace/:id/edit",
    label: "Edit listing",
    navOrder: 23,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./marketplace/ListingFormPage")),
  },
  {
    name: "peer-shared-tools",
    featureModule: "shared_tools",
    path: "/shared-tools",
    label: "Shared tools",
    icon: createElement(ArtIcon, { name: "shared" }),
    navOrder: 20,
    // Peer sharing is the tool-owning world (owner directive
    // 2026-10-17): mechanics and shops own lists and browse them.
    // Dealer/insurance-only accounts never see the module; the API
    // enforces the same split for sending invites.
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./peer/SharedToolsPage")),
  },
  {
    name: "borrowing",
    featureModule: "borrowing",
    path: "/borrowing",
    label: "Borrowing",
    icon: createElement(ArtIcon, { name: "borrowing" }),
    navOrder: 30,
    // Borrowing grows out of peer sharing (owner 2026-10-18): the
    // same two groups hold it — mechanics lend their own tools,
    // shops lend the shop's. The backend manifest carries the
    // same defaults and my-modules is the authority.
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./borrowing/BorrowingPage")),
  },
  {
    // Repairs & Maintenance (owner's merge, 2026-11-05): the
    // Claims and Maintenance menus fold into this ONE entry.
    // The claims and maintenance MODULES stay separate under
    // the hood — this entry rides on EITHER being effective,
    // and the page's tabs gate individually.
    name: "repairs",
    path: "/repairs",
    label: "Repairs & Maintenance",
    icon: createElement(ArtIcon, { name: "repairs" }),
    navOrder: 35,
    featureModuleAnyOf: ["claims", "maintenance"],
    // Repairs/schedules/warranty ride on inventory (backend
    // manifest carries the same defaults; my-modules is the
    // authority).
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./repairs/RepairsPage")),
  },
  {
    // The retired standalone route: /maintenance lands on the
    // merged page's Tool Maintenance tab. No nav entry and no
    // module gate of its own — the merged page decides.
    name: "maintenance",
    path: "/maintenance",
    label: "Repairs & maintenance",
    icon: createElement(ArtIcon, { name: "repairs" }),
    navOrder: 35,
    showInNav: false,
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() =>
      import("./repairs/Redirects").then((m) => ({
        default: m.MaintenanceRedirect,
      })),
    ),
  },
  {
    name: "dealers",
    featureModule: "dealers",
    path: "/dealers",
    label: "Dealer directory",
    icon: createElement(ArtIcon, { name: "dealers" }),
    navOrder: 40,
    // The dealer directory + preferred agents serve ALL four groups
    // (backend manifest carries the same defaults; my-modules is
    // the authority). Item dealer tags hide when the module is off —
    // inventory itself never depends on this module.
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./dealers/DealersPage")),
  },
  {
    name: "dealers-new",
    path: "/dealers/new",
    label: "Add dealer",
    navOrder: 41,
    showInNav: false,
    groups: ALL_ACCOUNT_TYPES,
    featureModule: "dealers",
    // Wizard Phase 2 (owner-confirmed model, 2026-10-25): adding
    // a dealer always opens the wizard — basics, then the agent
    // step ("add an authorized agent for this dealer, or pick
    // one from a list"), review, save. Editing stays on the
    // full form on the Dealers page. React Router ranks this
    // static path above /dealers/:companyId.
    element: lazy(() => import("./dealers/AddDealerWizardPage")),
  },
  {
    name: "dealers-company",
    path: "/dealers/:companyId",
    label: "Company",
    navOrder: 41,
    showInNav: false,
    groups: ALL_ACCOUNT_TYPES,
    featureModule: "dealers",
    element: lazy(() => import("./dealers/CompanyDetailPage")),
  },
  {
    // Find an Agent (dealer build, 2026-10-20): the standalone
    // search surface (also embedded in the Dealers page).
    // Deliberately NO featureModule and reachable signed-out: the
    // page itself picks its posture — signed-in gets contact
    // actions + one-tap preferred from the gated endpoint;
    // signed-out reads the public twin (no contact actions).
    name: "dealers-find-agent",
    path: "/dealers/find-agent",
    label: "Find an agent",
    navOrder: 42,
    showInNav: false,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./dealers/FindAgentPage")),
  },
  {
    name: "claims",
    path: "/claims",
    label: "Claims",
    icon: createElement(ArtIcon, { name: "claims" }),
    navOrder: 45,
    showInNav: false,
    // The retired standalone route (Repairs & Maintenance
    // merge, 2026-11-05): the warranty claims list — warranty
    // ONLY, insurance lives in Disaster Claims below — now
    // lives on the merged page's Repair claims tab (Repair
    // history for /claims#history). No module gate of its own:
    // the merged page decides. Claim DETAIL (/claims/:id)
    // below is untouched.
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() =>
      import("./repairs/Redirects").then((m) => ({
        default: m.ClaimsRedirect,
      })),
    ),
  },
  {
    name: "claims-detail",
    path: "/claims/:id",
    label: "Claim",
    navOrder: 46,
    showInNav: false,
    groups: ALL_ACCOUNT_TYPES,
    // Two seats (see featureModuleAnyOf): the claim's owner rides
    // claims; a dealer the claim is addressed to rides dealers.
    featureModuleAnyOf: ["claims", "dealers"],
    element: lazy(() => import("./claims/ClaimDetailPage")),
  },
  {
    // Disaster Claims (claims separation, 2026-11-05): the
    // insurance section — its own module, menu item, list,
    // filing flow and detail pages, 100% separated from Claims.
    // Rollout mirrors claims (backend manifest carries the same
    // defaults; my-modules is the authority). Insurer accounts/
    // directory are a later phase.
    name: "disaster-claims",
    featureModule: "disaster_claims",
    path: "/disaster-claims",
    label: "Disaster Claims",
    icon: createElement(ArtIcon, { name: "disaster" }),
    navOrder: 46,
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./disaster-claims/DisasterClaimsPage")),
  },
  {
    name: "disaster-claims-detail",
    path: "/disaster-claims/:id",
    label: "Disaster claim",
    navOrder: 47,
    showInNav: false,
    groups: ["mechanic_technician", "shop_company"],
    featureModule: "disaster_claims",
    element: lazy(() => import("./disaster-claims/DisasterClaimDetailPage")),
  },
  {
    name: "flyers",
    featureModule: "flyers",
    path: "/flyers",
    label: "Flyers",
    icon: createElement(ArtIcon, { name: "flyers" }),
    navOrder: 48,
    groups: ["mechanic_technician", "shop_company", "tool_dealer"],
    element: lazy(() => import("./flyers/FlyersPage")),
  },
  {
    name: "reports",
    featureModule: "reports",
    path: "/reports",
    label: "Reports",
    icon: createElement(ArtIcon, { name: "reports" }),
    navOrder: 50,
    // Reports read the vault the same two groups own (backend
    // manifest carries the same defaults; my-modules is the
    // authority). Dealers/insurers have no inventory to report on.
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./reports/ReportsPage")),
  },
  {
    // Messaging (2026-10-19): two-party conversations with the
    // first-contact quarantine + the anti-spam firewall. All four
    // groups (backend manifest carries the same defaults;
    // my-modules is the authority).
    name: "messaging",
    featureModule: "messaging",
    path: "/messages",
    label: "Messages",
    icon: createElement(ArtIcon, { name: "messages" }),
    navOrder: 55,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./messaging/MessagesPage")),
  },
  {
    name: "messaging-thread",
    featureModule: "messaging",
    path: "/messages/:threadId",
    label: "Conversation",
    navOrder: 56,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./messaging/ThreadPage")),
  },
  {
    // The moderation queue: role-ladder moderators + operators.
    // Hidden from the nav (the Messages page links it for those
    // who hold the role); the API enforces the ladder.
    name: "messaging-moderation",
    featureModule: "messaging",
    path: "/moderation",
    label: "Moderation",
    navOrder: 57,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./messaging/ModerationPage")),
  },
  {
    // The public seller profile — NO featureModule: it is read
    // from listings by every group and by signed-out visitors;
    // the API checks only the messaging global switch.
    name: "messaging-profile",
    path: "/users/:userId",
    label: "Member profile",
    navOrder: 58,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./messaging/PublicProfilePage")),
  },
  {
    // Community Forum (2026-10-20): the community's common room,
    // closing the community cluster after Messages. NO
    // featureModule on the board + category + thread — reading
    // is public (signed-in and signed-out read the same payloads
    // through these pages); the WRITE surfaces (posting, edit,
    // report) answer the API's own gates (module, then the
    // paid-contribution gate) and render the honest refusal. The
    // backend manifest carries the same posture for group-less
    // nav payloads.
    name: "forum",
    path: "/forum",
    label: "Community Forum",
    icon: createElement(ArtIcon, { name: "forum" }),
    navOrder: 60,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./forum/pages").then((m) => ({ default: m.ForumPage }))),
  },
  {
    name: "forum-category",
    path: "/forum/category/:categoryId",
    label: "Forum category",
    navOrder: 61,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./forum/pages").then((m) => ({ default: m.CategoryPage }))),
  },
  {
    name: "forum-thread",
    path: "/forum/thread/:threadId",
    label: "Forum thread",
    navOrder: 62,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./forum/pages").then((m) => ({ default: m.ThreadPage }))),
  },
  {
    // Feedback boards (wave 3, 2026-10-20): Bug Reports +
    // Feature Requests under one module. Like the forum
    // entries, NO featureModule on the routes — but reading is
    // MEMBERS-ONLY since 2026-11-10 (busy work #1): the API
    // refuses anonymous reads and the pages render a sign-in
    // door for signed-out visitors. The WRITE surfaces answer
    // the API's own gates (feedback module on; any signed-in
    // account may post, free included — the deliberate
    // deviation from the forum's paid gate).
    // Main tab layout (program lane 9, 2026-11-10): /feedback
    // is ONE tabbed page (Bug Reports · Feature Requests over
    // the shared BoardBody); the two board routes below are
    // doors — they redirect into the page at the matching tab
    // (#bugs / #features) so every link already pointing at
    // them keeps landing on the right board.
    name: "feedback",
    path: "/feedback",
    label: "Feedback",
    icon: createElement(ArtIcon, { name: "feedback" }),
    navOrder: 63,
    groups: ALL_ACCOUNT_TYPES,
    element: lazy(() => import("./feedback/pages").then((m) => ({ default: m.FeedbackHomePage }))),
  },
  {
    name: "feedback-bugs",
    path: "/feedback/bugs",
    label: "Bug Reports",
    navOrder: 64,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./feedback/pages").then((m) => ({ default: m.BugBoardRedirect }))),
  },
  {
    name: "feedback-features",
    path: "/feedback/features",
    label: "Feature Requests",
    navOrder: 65,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./feedback/pages").then((m) => ({ default: m.FeatureBoardRedirect }))),
  },
  {
    name: "feedback-post",
    path: "/feedback/post/:postId",
    label: "Feedback post",
    navOrder: 66,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./feedback/pages").then((m) => ({ default: m.PostDetailPage }))),
  },
  {
    // Wishlist (wave 2, 2026-10-20): the want-list that converts
    // into Asset Inventory — mechanic + shop, like the vault it
    // feeds (the backend manifest carries the same defaults).
    name: "wishlist",
    featureModule: "wishlist",
    path: "/wishlist",
    label: "Wishlist",
    icon: createElement(ArtIcon, { name: "wishlist" }),
    navOrder: 17,
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./wishlist/WishlistPage")),
  },
  {
    // Tool Expansion (owner spec 2026-10-25): known addons for
    // the tools and sets you own, learned community-wide by
    // model-number matching. Mechanic + shop, like the wishlist
    // it sits beside (the backend manifest carries the same
    // defaults and the inventory dependency).
    name: "tool-expansion",
    featureModule: "tool_expansion",
    path: "/tool-expansion",
    label: "Tool Expansion",
    icon: createElement(ArtIcon, { name: "expansion" }),
    navOrder: 18,
    groups: ["mechanic_technician", "shop_company"],
    element: lazy(() => import("./tool-expansion/ToolExpansionPage")),
  },
  {
    // Truck Accounts (wave 2): the dealer↔customer running tab —
    // all three trading groups hold a side of it.
    name: "truck-accounts",
    featureModule: "truck_accounts",
    path: "/truck-accounts",
    label: "Truck accounts",
    icon: createElement(ArtIcon, { name: "truck" }),
    navOrder: 56,
    groups: ["mechanic_technician", "shop_company", "tool_dealer"],
    element: lazy(() => import("./truck-accounts/TruckAccountsPage")),
  },
  {
    name: "truck-account-detail",
    featureModule: "truck_accounts",
    path: "/truck-accounts/:id",
    label: "Truck account",
    navOrder: 57,
    groups: ["mechanic_technician", "shop_company", "tool_dealer"],
    showInNav: false,
    element: lazy(() => import("./truck-accounts/TruckAccountDetailPage")),
  },
  {
    name: "core-admin",
    path: "/admin",
    label: "Admin",
    navOrder: 97,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-modules",
    path: "/admin/modules",
    label: "Admin · Modules",
    navOrder: 98,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    // Site pulse (sweep D4): the operator's morning-glance tab
    // of the Admin page — same re-homing as every other section.
    name: "core-admin-site-pulse",
    path: "/admin/site-pulse",
    label: "Admin · Site pulse",
    navOrder: 99,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-users",
    path: "/admin/users",
    label: "Admin · Users",
    navOrder: 99,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    // Conversion requests (tier conversion, 2026-11-10): the
    // god queue tab of the Admin page — same re-homing as every
    // other section.
    name: "core-admin-conversion-requests",
    path: "/admin/conversion-requests",
    label: "Admin · Conversion requests",
    navOrder: 100,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-promos",
    path: "/admin/promos",
    label: "Admin · Promos",
    navOrder: 100,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-bans",
    path: "/admin/bans",
    label: "Admin · Bans",
    navOrder: 101,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-roadmap",
    path: "/admin/roadmap",
    label: "Admin · Roadmap",
    navOrder: 103,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    // Announcements (release machinery, 2026-11-08): the
    // feature-announcement composer + history tab of the Admin
    // page — same re-homing as every other section.
    name: "core-admin-announcements",
    path: "/admin/announcements",
    label: "Admin · Announcements",
    navOrder: 103,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-settings",
    path: "/admin/settings",
    label: "Admin · Settings",
    navOrder: 102,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-audit",
    path: "/admin/audit",
    label: "Admin · Audit",
    navOrder: 103,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    name: "core-admin-dealer-directory",
    path: "/admin/dealer-directory",
    label: "Admin · Dealer directory",
    navOrder: 104,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    // Insurer directory (wave 3): the dealer directory's mirror —
    // platform insurer companies + affiliation verification.
    name: "core-admin-insurer-directory",
    path: "/admin/insurer-directory",
    label: "Admin · Insurer directory",
    navOrder: 105,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() => import("./core/admin/AdminPage")),
  },
  {
    // Catch-all 404 (completeness audit A4). Declared LAST: React
    // Router ranks "*" below every concrete path, so it only ever
    // renders for URLs nothing else claims. Ungated on purpose —
    // signed-in users see it inside their shell, signed-out visitors
    // inside the plain header chrome.
    name: "core-not-found",
    path: "*",
    label: "Page not found",
    navOrder: 106,
    groups: ALL_ACCOUNT_TYPES,
    showInNav: false,
    element: lazy(() =>
      import("./core/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
    ),
  },
];
