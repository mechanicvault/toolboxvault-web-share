import "../../flyers/flyers.css";
import "../../prints/prints.css";
import "../downloads.css";

import type { WidgetDef } from "./shared";
import { inventoryWidget } from "./inventory";
import { marketplaceWidget } from "./marketplace";
import { borrowingWidget } from "./borrowing";
import { maintenanceWidget } from "./maintenance";
import { disasterClaimsWidget } from "./disaster_claims";
import { partsWidget } from "./parts";
import { dealersWidget } from "./dealers";
import { dealersNearYouWidget } from "./dealers_near_you";
import { healthChecksDueWidget } from "./health_checks_due";
import { quickAddWidget } from "./quick_add";
import { accountPlanWidget } from "./account_plan";
import { flyersWidget } from "./flyers";
import { reportsWidget } from "./reports";
import { messagingWidget } from "./messaging";
import { forumWidget } from "./forum";
import { feedbackWidget } from "./feedback";
import { wishlistWidget } from "./wishlist";
import { toolExpansionWidget } from "./tool_expansion";
import { truckAccountsWidget } from "./truck_accounts";
import { sharedToolsWidget } from "./shared_tools";
import { supportWidget } from "./support";
import { printsWidget } from "./prints";
import { downloadsWidget } from "./downloads";
import { converterWidget } from "./converter";

export const HOME_WIDGETS: Record<string, WidgetDef> = {
  inventory: inventoryWidget,
  marketplace: marketplaceWidget,
  borrowing: borrowingWidget,
  maintenance: maintenanceWidget,
  disaster_claims: disasterClaimsWidget,
  parts: partsWidget,
  dealers: dealersWidget,
  dealers_near_you: dealersNearYouWidget,
  health_checks_due: healthChecksDueWidget,
  quick_add: quickAddWidget,
  account_plan: accountPlanWidget,
  flyers: flyersWidget,
  reports: reportsWidget,
  messaging: messagingWidget,
  forum: forumWidget,
  feedback: feedbackWidget,
  wishlist: wishlistWidget,
  tool_expansion: toolExpansionWidget,
  truck_accounts: truckAccountsWidget,
  shared_tools: sharedToolsWidget,
  support: supportWidget,
  prints: printsWidget,
  downloads: downloadsWidget,
  converter: converterWidget,
};

export const HOME_WIDGET_ORDER = [
  "inventory",
  "marketplace",
  "borrowing",
  "maintenance",
  "disaster_claims",
  "messaging",
  "parts",
  "shared_tools",
  "dealers",
  "flyers",
  "reports",
  "forum",
  "wishlist",
  "tool_expansion",
  "truck_accounts",
  "feedback",
  "support",
  "prints",
];
