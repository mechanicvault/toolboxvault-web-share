import { Link } from "react-router-dom";
import { buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { api } from "../../../lib/api";
import type {
  HealthCheckDueItem,
  HealthCheckDueResult,
} from "../../inventory/types";
import { optNum } from "../widgetOptions";
import type { WidgetRow, WidgetStat, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const healthChecksDueWidget: WidgetDef = {
    icon: <ArtIcon name="inventory" size={24} />,
    tone: "warning",
    cta: "open",
    path: "/inventory#health-check",
    // A NEW widget (widget wave 2, owner approval 2026-11-09):
    // OFF by default like the Dealers near you widget beside
    // it — nobody's stored Home is rearranged; Edit view's Add
    // menu and the widget gallery offer it. (It is
    // NOT a module widget in HOME_WIDGET_ORDER — the inventory
    // module already seats its own widget there; CorePage
    // seats this one as its own block gated on the inventory
    // module, the Dealers near you pattern.)
    defaultOff: true,
    load: async (t, ctx) => {
      // Health checks due (idea C#2): the items the Health
      // Check scan flags, read from /inventory/health-check-due
      // — the scan itself, verbatim, plus each item's photo
      // thumbnail. The scan has ONE definition of "needs a
      // check" (an ACTIVE item missing an identifier — a model
      // OR a serial satisfies it — a photo, a price, or a
      // purchase date; a set's pieces missing serials surface
      // under the set),
      // and this widget restates none of it: the headline and
      // the counts line are the Health Check page's own words,
      // the row's gap column is the page's own labels, and a
      // row's link is the page's own Fix-it target — the FIRST
      // gap's exact fix spot (gapTarget/firstGapTarget in
      // HealthCheckPage, mirrored here; the two must move
      // together). Nothing flagged is the quiet state: the
      // page's all-ready line and one plain explainer.
      const settings = ctx?.settings ?? {};
      const rowsToShow = optNum(settings, "rowsToShow", 4, 2, 6);
      const due = await api<HealthCheckDueResult>("/inventory/health-check-due");
      const openDoor = (primary: boolean) => (
        <Link
          to="/inventory#health-check"
          className={buttonClasses(primary ? "primary" : "ghost", "sm")}
        >
          {line(t, "home.widget.health.open", "Open health check")}
        </Link>
      );
      if (due.total === 0) {
        return {
          lines: [
            line(t, "inventory.health.allReady", "Everything is claim-ready."),
            line(
              t,
              "home.widget.health.explainer",
              "The health check scans your active items for the details a claim needs. When everything has them, this widget stays quiet.",
            ),
          ],
          actions: openDoor(false),
        };
      }
      const labelKeys: Record<string, string> = {
        identifier: "inventory.health.labelIdentifier",
        photo: "inventory.health.labelPhoto",
        price: "inventory.health.labelPrice",
        purchase_date: "inventory.health.labelPurchase",
      };
      // Sheet row 51 (owner, 2026-11-15): the per-gap stat
      // tiles (one box per missing kind) are replaced by ONE
      // box — "Items missing information:" + the total count
      // of items that need attention — with the fix list
      // below it. The per-row sub-lines still name each
      // item's own missing facts.
      const statTiles: WidgetStat[] = [
        {
          label: line(
            t,
            "home.widget.health.itemsMissing",
            "Items missing information",
          ),
          value: count(due.total),
        },
      ];
      const gapTarget = (item: HealthCheckDueItem, gap: string): string => {
        const base =
          item.kind === "tool"
            ? `/inventory/${item.id}`
            : `/inventory/batteries/${item.id}`;
        if (gap === "photo") return `${base}#photos`;
        if (gap === "identifier") return `${base}/edit#fix-model`;
        if (gap === "price") return `${base}/edit#fix-price`;
        if (gap === "purchase_date") return `${base}/edit#fix-purchase-date`;
        return `${base}/edit`;
      };
      const firstGapTarget = (item: HealthCheckDueItem): string => {
        if (item.missing.length > 0) return gapTarget(item, item.missing[0]);
        if (item.pieces_missing.length > 0)
          return `/inventory/${item.id}/edit#fix-piece-${item.pieces_missing[0].id}`;
        return gapTarget(item, "");
      };
      // Sample redesign (2026-11-15): the rows wear the
      // sample's shape — the item (photo or artwork tile) with
      // its missing facts as the quiet sub-line, and a real
      // Fix button riding to the first gap's exact fix spot
      // (the row itself is not a link — the button is the
      // door, as the sample draws it). The single summary box
      // (sheet row 51) stacks above the rows.
      const rows: WidgetRow[] = due.items.map((item) => {
        const gaps = item.missing.map((key) =>
          line(t, labelKeys[key] ?? key, key),
        );
        if (item.pieces_missing.length > 0) {
          gaps.push(
            line(t, "inventory.health.labelPieceSerial", "Piece serials"),
          );
        }
        const target = firstGapTarget(item);
        return {
          cells: [
            <span key="item" className="tv-health-item">
              {item.thumb_url_sm ? (
                <img className="tv-health-thumb" src={item.thumb_url_sm} alt="" />
              ) : (
                <span className="tv-health-thumb tv-health-thumb--art" aria-hidden="true">
                  <ArtIcon
                    name={item.kind === "battery" ? "parts" : "inventory"}
                    size={18}
                  />
                </span>
              )}
              <span className="tv-widget-cellstack">
                <span>{item.name}</span>
                <span className="tv-widget-cellsub">
                  {gaps.length > 0
                    ? gaps.join(" · ")
                    : line(
                        t,
                        "inventory.health.subLimit",
                        "Business use — your policy's sub-limit may cap this item",
                      )}
                </span>
              </span>
            </span>,
            ctx?.editing ? (
              <span key="fix" className={buttonClasses("secondary", "sm")}>
                {line(t, "home.widget.health.fix", "Fix")}
              </span>
            ) : (
              <Link
                key="fix"
                to={target}
                className={buttonClasses("secondary", "sm")}
              >
                {line(t, "home.widget.health.fix", "Fix")}
              </Link>
            ),
          ],
        };
      });
      const data: WidgetData = {
        lines: [
          line(
            t,
            due.total === 1
              ? "inventory.health.needOne"
              : "inventory.health.needMany",
            due.total === 1
              ? "{count} item needs attention"
              : "{count} items need attention",
            { count: count(due.total) },
          ),
        ],
        stats: statTiles,
        groups: [
          {
            label: line(t, "home.widget.health.fixNext", "FIX THESE NEXT"),
            rowsClass: "tv-widget-rows--cols-healthfix tv-widget-rows--ruled",
            rows: rows.slice(0, rowsToShow),
          },
        ],
        actions: openDoor(true),
        actionsEnd: true,
      };
      return data;
    },
  };
