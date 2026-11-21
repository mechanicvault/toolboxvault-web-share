import { InventoryOptions } from "./inventory";
import { BorrowingOptions } from "./borrowing";
import { DisasterClaimsOptions } from "./disaster_claims";
import { TruckOptions } from "./truck_accounts";
import { DealerTruckOptions } from "./dealer_truck_accounts";
import { ForumOptions } from "./forum";
import { NotificationsOptions } from "./notifications";
import { DealerDashboardOptions } from "./dealer_dashboard";
import { MaintenanceOptions } from "./maintenance";
import { ReportsOptions } from "./reports";
import { DealersOptions } from "./dealers";
import { DealersNearYouOptions } from "./dealers_near_you";
import { HealthChecksDueOptions } from "./health_checks_due";
import { FeedbackOptions } from "./feedback";
import { SharedToolsOptions } from "./shared_tools";
import { SupportOptions } from "./support";
import { DownloadsOptions } from "./downloads";
import { PrintsOptions } from "./prints";
import { QuickReportsOptions } from "./quick_reports";
import { ExpansionOptions } from "./tool_expansion";
import { PartsOptions } from "./parts";
import { MarketplaceOptions } from "./marketplace";
import { MessagingOptions } from "./messaging";
import { WishlistOptions } from "./wishlist";
import { FlyersOptions } from "./flyers";
import { AdminTicketsOptions } from "./admin_tickets";
import { AdminBoardOptions } from "./admin_board";
import { AdminForumModeratorOptions } from "./admin_forum_moderator";
import { AdminSiteStatsOptions } from "./admin_site_stats";
import { AccountPlanOptions } from "./account_plan";
import { AdminOverviewOptions } from "./admin_overview";
import { AdminScoreboardOptions } from "./admin_scoreboard";
import { AdminHealthOptions } from "./admin_health";
import { type ReactNode } from "react";
import { ResolvedBlock } from "../../../lib/usePageLayout";
import { WidgetOptionsApi, WidgetOptionsDef } from "./shared";

export const WIDGET_OPTIONS: Record<string, WidgetOptionsDef> = {
  account_plan: { render: (api) => <AccountPlanOptions api={api} /> },
  "widget:flyers": { render: (api) => <FlyersOptions api={api} /> },
  "widget:inventory": { render: (api) => <InventoryOptions api={api} /> },
  "widget:borrowing": { render: (api) => <BorrowingOptions api={api} /> },
  "widget:disaster_claims": {
    render: (api) => <DisasterClaimsOptions api={api} />,
  },
  "widget:truck_accounts": { render: (api) => <TruckOptions api={api} /> },
  "widget:forum": { render: (api) => <ForumOptions api={api} /> },
  notifications: { render: (api) => <NotificationsOptions api={api} /> },
  dealer_dashboard: {
    render: (api) => <DealerDashboardOptions api={api} />,
  },
  dealer_truck_accounts: {
    render: (api) => <DealerTruckOptions api={api} />,
  },
  "widget:maintenance": { render: (api) => <MaintenanceOptions api={api} /> },
  "widget:reports": { render: (api) => <ReportsOptions api={api} /> },
  "widget:dealers": { render: (api) => <DealersOptions api={api} /> },
  dealers_near_you: {
    render: (api) => <DealersNearYouOptions api={api} />,
  },
  health_checks_due: {
    render: (api) => <HealthChecksDueOptions api={api} />,
  },
  "widget:feedback": { render: (api) => <FeedbackOptions api={api} /> },
  "widget:shared_tools": { render: (api) => <SharedToolsOptions api={api} /> },
  "widget:support": { render: (api) => <SupportOptions api={api} /> },
  "widget:downloads": { render: (api) => <DownloadsOptions api={api} /> },
  "widget:prints": { render: (api) => <PrintsOptions api={api} /> },
  quick_reports: { render: (api) => <QuickReportsOptions api={api} /> },
  "widget:tool_expansion": { render: (api) => <ExpansionOptions api={api} /> },
  "widget:parts": { render: (api) => <PartsOptions api={api} /> },
  "widget:marketplace": { render: (api) => <MarketplaceOptions api={api} /> },
  "widget:messaging": { render: (api) => <MessagingOptions api={api} /> },
  "widget:wishlist": { render: (api) => <WishlistOptions api={api} /> },

  admin_tickets: { render: (api) => <AdminTicketsOptions api={api} /> },
  admin_overview: { render: (api) => <AdminOverviewOptions api={api} /> },
  admin_scoreboard: { render: (api) => <AdminScoreboardOptions api={api} /> },
  admin_health: { render: (api) => <AdminHealthOptions api={api} /> },
  admin_bug_reports: { render: (api) => <AdminBoardOptions api={api} /> },
  admin_feature_requests: { render: (api) => <AdminBoardOptions api={api} /> },
  admin_forum_moderator: {
    render: (api) => <AdminForumModeratorOptions api={api} />,
  },
  admin_site_stats: { render: (api) => <AdminSiteStatsOptions api={api} /> },
};

/** The popover's extra content for one block: its registered
 *  option sections, or null when the block has none. */
export function renderWidgetOptions(
  block: ResolvedBlock,
  setSetting: WidgetOptionsApi["setSetting"],
): ReactNode {
  const def = WIDGET_OPTIONS[block.key];
  if (!def) return null;
  return def.render({ block, setSetting });
}
