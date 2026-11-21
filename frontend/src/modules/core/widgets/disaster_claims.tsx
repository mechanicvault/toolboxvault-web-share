import {Link} from "react-router-dom";
import {buttonClasses} from "../../../components";
import {ArtIcon} from "../../../components/ArtIcon";
import {formatDate} from "../../../lib/format";
import {formatMoney} from "../../../lib/money";
import {disasterClaimsApi} from "../../claims/api";
import {StatusBadge} from "../../claims/components";
import {
  optBool,
  optNum,
} from "../widgetOptions";
import type {
  WidgetData,
  WidgetDef,
} from "./shared";
import {
  count,
  line,
} from "./shared";

export const disasterClaimsWidget: WidgetDef = {
    icon: <ArtIcon name="disaster" size={24} />,
    tone: "violet",
    cta: "open",
    load: async (t, ctx) => {
      // Sample redesign (2026-11-15): the counts line, then
      // the claims as in-widget TABS — Open and History
      // switching in place. Each row: the item with the
      // claim number, date and insurer quiet underneath,
      // the standing pill in its own column, and the amount.
      // One list read serves both tabs: history is a claim
      // with a close on it, open is everything else.
      const settings = ctx?.settings ?? {};
      const recentCount = optNum(settings, "recentCount", 3, 1, 5);
      const showButtons = optBool(settings, "showButtons", true);
      const showCount = optBool(settings, "showCount", true);
      const showRows = optBool(settings, "showRows", true);
      const claims = await disasterClaimsApi.listClaims(false);
      const isHistory = (c: (typeof claims)[number]) =>
        c.closed_at !== null || c.status === "closed";
      const open = claims.filter((c) => !isHistory(c));
      const history = claims.filter(isHistory);
      const data: WidgetData = { lines: [] };
      if (showCount) {
        const claimed = open.reduce(
          (sum, c) => sum + (Number(c.total_amount) || 0),
          0,
        );
        data.counts = [
          {
            value: count(open.length),
            label: line(t, "home.widget.disasterOpenWord", "open"),
          },
          {
            value: formatMoney(String(claimed), open[0]?.owner_currency ?? null, true),
            label: line(t, "home.widget.disasterClaimedWord", "claimed"),
          },
          {
            value: count(history.length),
            label: line(t, "home.widget.disasterInHistory", "in history"),
          },
        ];
      }
      const claimRow = (c: (typeof claims)[number]) => ({
        cells: [
          <span key="item" className="tv-widget-cellstack">
            <span>{c.first_item_name || "—"}</span>
            <span className="tv-widget-cellsub">
              {c.claim_number} · {formatDate(c.created_at.slice(0, 10))}
              {c.insurer_name ? ` · ${c.insurer_name}` : ""}
            </span>
          </span>,
          <StatusBadge key="status" status={c.status} />,
          formatMoney(c.total_amount, c.owner_currency, true),
        ],
        href: `/disaster-claims/${c.id}`,
      });
      if (showRows) {
        data.tabs = [
          {
            id: "open",
            label: line(t, "home.widget.statOpenClaims", "Open claims"),
            count: open.length,
            rows: open.slice(0, recentCount).map(claimRow),
            rowsVisible: recentCount,
            rowsClass: "tv-widget-rows--reports",
            emptyText: line(t, "home.widget.noOpenClaims", "No open claims"),
          },
          {
            id: "history",
            label: line(t, "home.widget.disasterHistoryTab", "History"),
            count: history.length,
            rows: history.slice(0, recentCount).map(claimRow),
            rowsVisible: recentCount,
            rowsClass: "tv-widget-rows--reports",
            emptyText: line(t, "home.widget.noHistoryClaims", "No past claims"),
          },
        ];
      }
      if (showButtons) {
        data.actions = (
          <>
            <Link to="/inventory?dcsec=closed#disaster-claim" className={buttonClasses("ghost", "sm")}>
              {line(t, "home.widget.disasterHistoryBtn", "History claims")}
            </Link>
            <Link to="/inventory?dcsec=open#disaster-claim" className={buttonClasses("primary", "sm")}>
              {line(t, "home.widget.disasterStart", "Start a claim")}
            </Link>
          </>
        );
        data.actionsEnd = true;
      }
      return data;
    },
  };
