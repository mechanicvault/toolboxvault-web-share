import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { formatDate } from "../../../lib/format";
import { getClaimsStats, listClaims } from "../../claims/api";
import { StatusBadge } from "../../claims/components";
import { getMaintenanceOverview, getMaintenanceStats } from "../../maintenance/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetTab, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const maintenanceWidget: WidgetDef = {
    icon: <ArtIcon name="repairs" size={24} />,
    tone: "warning",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch A: the two counts are
      // individually hideable (both on = today's combined line,
      // byte for byte), and the coming-up list — the schedules
      // as real rows from the SAME overview this widget has
      // always loaded, 1–5 visible before the rest scroll. The
      // list is the design's named shape, so it defaults on;
      // switching it off restores today's single Next line.
      // Full width adds the due-date column.
      //
      // Claims merge (owner, 2026-11-06): the standalone
      // Claims widget is GONE — everything it carried lives
      // here now, under this widget's own view options
      // (defaults = everything both widgets showed, so nobody
      // loses information on upgrade): the open-claims count
      // line, a backordered line when any claim sits
      // backordered, the recent-claims rows, and the Repair
      // claims / Repair history buttons (the merged page's
      // tabs). WARRANTY/repair claims only (claims
      // separation): insurance stays in the Disaster Claims
      // widget. The claims reads load SOFTLY — the claims
      // module can be off for a user whose maintenance module
      // is on, and then this widget simply shows its
      // maintenance half.
      const settings = ctx?.settings ?? {};
      const showDue = optBool(settings, "showDue", true);
      const showOut = optBool(settings, "showOut", true);
      const comingUp = optBool(settings, "comingUp", true);
      const visibleRows = optNum(settings, "visibleRows", 3, 1, 5);
      const showClaimsLine = optBool(settings, "showClaimsLine", true);
      const showBackordered = optBool(settings, "showBackordered", true);
      const claimsList = optBool(settings, "claimsList", true);
      const claimCount = optNum(settings, "claimCount", 3, 1, 5);
      const showClaimButtons = optBool(settings, "showClaimButtons", true);
      const [stats, overview] = await Promise.all([
        getMaintenanceStats(),
        getMaintenanceOverview(),
      ]);
      let claimStats: Awaited<ReturnType<typeof getClaimsStats>> | null = null;
      let claimList: Awaited<ReturnType<typeof listClaims>> | null = null;
      if (showClaimsLine || showBackordered || claimsList || showClaimButtons) {
        try {
          [claimStats, claimList] = await Promise.all([
            getClaimsStats(),
            listClaims(false),
          ]);
        } catch {
          claimStats = null;
          claimList = null;
        }
      }
      // Sample redesign (2026-11-15): the widget wears the
      // samples' shape — ONE counts line under the head, then
      // TABS that switch the list in place (Open claims /
      // Coming up / Repaired), then the footer pair. The view
      // options keep their meanings, mapped onto the new
      // shape: showDue/showOut gate their counts, the claims
      // switches gate the claims tabs, comingUp gates the
      // schedules tab, the row counts cap their tab's rows.
      const counts: { value: string; label: string }[] = [];
      if (showDue) {
        counts.push({
          value: count(stats.maintenance_due_count),
          label: line(t, "home.widget.countDue", "due"),
        });
      }
      if (showOut) {
        counts.push({
          value: count(stats.out_of_service_count),
          label: line(t, "home.widget.countOut", "out of service"),
        });
      }
      const allClaims = claimList ?? [];
      const openClaims = allClaims.filter(
        (c) => c.status !== "completed" && !c.closed_at,
      );
      const doneClaims = allClaims.filter(
        (c) => c.status === "completed" || c.closed_at,
      );
      if (claimList && showBackordered) {
        const backordered = openClaims.filter(
          (c) => c.status === "backordered",
        ).length;
        if (backordered > 0) {
          counts.push({
            value: count(backordered),
            label: line(t, "home.widget.countBackordered", "backordered"),
          });
        }
      }
      const data: WidgetData = { lines: [] };
      if (counts.length > 0) data.counts = counts;
      const full = ctx?.size === "full";
      const claimStack = (c: (typeof allClaims)[number], sub: string) => (
        <span key="item" className="tv-widget-cellstack">
          <span>{c.first_item_name || "—"}</span>
          <span className="tv-widget-cellsub">{sub}</span>
        </span>
      );
      // Sheet row 12 (owner): the claim rows carry the
      // dealer and the agent the claim runs through, not
      // just the date — "Reported {date} · {dealer} ·
      // {agent}", each part present only when the claim
      // carries it.
      const claimSub = (c: (typeof allClaims)[number]) => {
        const bits = [
          line(t, "home.widget.claimReportedDate", "Reported {date}", {
            date: formatDate((c.reported_at ?? c.created_at).slice(0, 10)),
          }),
        ];
        const dealer = c.dealer_name || c.dealers?.[0]?.name || "";
        if (dealer) bits.push(dealer);
        if (c.warranty_agent_name) bits.push(c.warranty_agent_name);
        return bits.join(" · ");
      };
      const tabs: WidgetTab[] = [];
      if (claimList && (showClaimsLine || claimsList)) {
        tabs.push({
          id: "claims",
          label: line(t, "home.widget.statOpenClaims", "Open claims"),
          count: openClaims.length,
          rowsVisible: claimCount,
          rowsClass: "tv-widget-rows--reports",
          emptyText: line(t, "home.widget.noOpenClaims", "No open claims"),
          rows: openClaims.slice(0, claimCount).map((c) => ({
            cells: [
              // The row carries the item name, the date the
              // claim started, the dealer/agent (row 12), and
              // the status — the claim number stays off the
              // row (standing rule 2026-11-14: claim dates
              // visible, claim number demoted).
              claimStack(c, claimSub(c)),
              <StatusBadge key="status" status={c.status} />,
            ],
            href: `/claims/${c.id}`,
            chevron: true,
          })),
        });
      }
      if (comingUp) {
        tabs.push({
          id: "coming",
          label: line(t, "home.widget.comingUp", "Coming up"),
          count: overview.schedules.length,
          rowsVisible: visibleRows,
          rowsClass: "tv-widget-rows--reports",
          header: full
            ? [
                line(t, "home.widget.colItem", "Item"),
                line(t, "home.widget.colWhatsDue", "What's due"),
                line(t, "home.widget.colDueDate", "Due date"),
              ]
            : undefined,
          emptyText: line(t, "home.widget.noComingUp", "Nothing coming up"),
          rows: overview.schedules.map((s) => {
            const cells: ReactNode[] = [s.item_name, s.label];
            if (full) {
              const due = s.next_due ?? s.due_date;
              cells.push(due ? formatDate(due) : "—");
            }
            return { cells };
          }),
        });
      }
      if (claimList && claimsList) {
        tabs.push({
          id: "repaired",
          label: line(t, "home.widget.tabRepaired", "Repaired"),
          count: doneClaims.length,
          rowsVisible: claimCount,
          rowsClass: "tv-widget-rows--reports",
          emptyText: line(t, "home.widget.noRepaired", "No repaired claims yet"),
          rows: doneClaims.slice(0, claimCount).map((c) => ({
            cells: [
              // Same rule as the Open claims tab: the row
              // carries the date the claim started plus the
              // dealer/agent (row 12) — the claim number
              // stays off the row (standing rule 2026-11-14).
              // The middle cell already shows the repaired
              // date.
              claimStack(c, claimSub(c)),
              c.repair_completed_at
                ? formatDate(c.repair_completed_at.slice(0, 10))
                : "—",
              <StatusBadge key="status" status={c.status} />,
            ],
            href: `/claims/${c.id}`,
          })),
        });
      }
      if (tabs.length > 0) {
        data.tabs = tabs;
        data.linesAfter = [
          line(
            t,
            "home.widget.tabsHint",
            "Tap a tab to switch lists. Only one list shows at a time, so the box stays short.",
          ),
        ];
      } else if (!comingUp) {
        const next = overview.schedules[0];
        if (next) {
          data.linesAfter = [
            line(t, "home.widget.next", "Next: {item} — {label}", { item: next.item_name, label: next.label }),
          ];
        }
      }
      if (showClaimButtons && (claimStats || claimList)) {
        data.actionsEnd = true;
        data.actions = (
          <>
            <Link to="/inventory?rcsec=history#repair-claims" className={buttonClasses("ghost", "sm")}>
              {line(t, "home.widget.historyClaimsBtn", "Repair history")}
            </Link>
            <Link to="/inventory#repair-claims" className={buttonClasses("primary", "sm")}>
              {line(t, "home.widget.openClaimsBtn", "Repair claims")}
            </Link>
          </>
        );
      }
      return data;
    },
  };
