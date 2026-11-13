import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { api } from "../../lib/api";
import { activeLocale } from "../../lib/format";
import { formatMoney } from "../../lib/money";
import {
  buildLocationTree,
  listLocationNodes,
  type LocationTreeNode,
} from "../../modules/inventory/components/locationTree";
import type { InventoryStats } from "../OverviewRow";
import { PanelUtility } from "./PanelUtility";

/**
 * The Inventory panel (Rail Steel conversion, Phase 2a): the
 * utility search well (the same global search PanelUtility
 * carries everywhere), a Views group of NAVIGATION-level views —
 * the list page's own URL contract (?warranty=due&sort=
 * warranty_end, ?location_id=<node>, the params ToolListPage
 * reads) — top-level locations from the SAME location-tree call
 * the list page's filter picker uses, a Manage group of the
 * module's real routes, and a stats list from /inventory/stats,
 * the shared payload Home's overview reads.
 *
 * The page keeps its in-content filter toolbar (MAPPING §3,
 * accepted deviation 1): the panel never duplicates page filter
 * state, it links the views the URL can carry. /inventory/stats
 * counts tools + batteries together (total_items) — there is no
 * honest per-kind split in any existing payload, so the stats
 * list says "Items tracked", never an invented tool count.
 */

const LOCATION_CAP = 8;

function PanelLink({
  to,
  active,
  count,
  children,
}: {
  to: string;
  active: boolean;
  count?: number;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      className={`tv-sp-item${active ? " is-active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      <span>{children}</span>
      {count !== undefined && (
        <span className="tv-sp-count">{count.toLocaleString(activeLocale())}</span>
      )}
    </Link>
  );
}

export function InventoryPanel() {
  const t = useT();
  // Labels run through the dictionary (es render check flagged
  // the hardcoded "Health Check" here, 2026-10-24).
  const manageLinks: { to: string; label: string }[] = [
    { to: "/inventory/categories", label: t("inventory.categories") },
    { to: "/inventory/health", label: t("inventory.healthCheck") },
    { to: "/inventory/import", label: t("inventory.import") },
    { to: "/inventory/labels", label: t("inventory.printLabels") },
  ];
  const location = useLocation();
  const [roots, setRoots] = useState<LocationTreeNode[]>([]);
  const [rootTotal, setRootTotal] = useState(0);
  const [stats, setStats] = useState<InventoryStats | null>(null);

  useEffect(() => {
    let live = true;
    listLocationNodes()
      .then((nodes) => {
        if (!live) return;
        const tree = buildLocationTree(nodes);
        setRoots(tree.slice(0, LOCATION_CAP));
        setRootTotal(tree.length);
      })
      .catch(() => undefined);
    api<InventoryStats>("/inventory/stats")
      .then((s) => {
        if (live) setStats(s);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const params = new URLSearchParams(location.search);
  const onList = location.pathname === "/inventory";
  const activeLocationId = onList ? params.get("location_id") : null;
  const warrantyActive = onList && params.get("warranty") === "due";
  const allActive =
    onList && !params.get("warranty") && !params.get("location_id");

  return (
    <>
      <p className="tv-sp-kicker">{t("nav.inventory")}</p>
      <h2 className="tv-sp-title">{t("nav.inventory")}</h2>
      <PanelUtility />
      <p className="tv-sp-group">{t("panel.views")}</p>
      <div className="tv-sp-list">
        <PanelLink to="/inventory" active={allActive}>
          {t("panel.inventory.allTools")}
        </PanelLink>
        <PanelLink
          to="/inventory?warranty=due&sort=warranty_end"
          active={warrantyActive}
          count={stats?.warranties_expiring_soon}
        >
          {t("panel.inventory.warrantyDue")}
        </PanelLink>
        {roots.map((node) => (
          <PanelLink
            key={node.id}
            to={`/inventory?location_id=${node.id}`}
            active={activeLocationId === node.id}
            count={node.subtree_item_count}
          >
            {node.name}
          </PanelLink>
        ))}
      </div>
      {rootTotal > roots.length && (
        <p className="tv-sp-hint">
          {t("panel.inventory.moreLocations").replace(
            "{count}",
            String(rootTotal - roots.length),
          )}
        </p>
      )}
      <p className="tv-sp-group">{t("panel.manage")}</p>
      <div className="tv-sp-list">
        {manageLinks.map((link) => (
          <PanelLink
            key={link.to}
            to={link.to}
            active={location.pathname === link.to}
          >
            {link.label}
          </PanelLink>
        ))}
      </div>
      {stats && (
        <ul className="tv-sp-stats">
          <li>
            <span>{t("panel.inventory.itemsTracked")}</span>
            <strong>{stats.total_items.toLocaleString(activeLocale())}</strong>
          </li>
          <li>
            <span>{t("stat.inventory.total_market_value")}</span>
            <strong>{formatMoney(stats.total_value, null, true)}</strong>
          </li>
          <li>
            <span>{t("panel.inventory.warrantiesExpiring")}</span>
            <strong>
              {stats.warranties_expiring_soon.toLocaleString(activeLocale())}
            </strong>
          </li>
          <li>
            <span>{t("inventory.categories")}</span>
            <strong>{stats.category_count.toLocaleString(activeLocale())}</strong>
          </li>
        </ul>
      )}
    </>
  );
}
