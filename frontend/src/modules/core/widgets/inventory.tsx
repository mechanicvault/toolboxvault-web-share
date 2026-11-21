import { Link } from "react-router-dom";
import { buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { api } from "../../../lib/api";
import { formatMoney } from "../../../lib/money";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const inventoryWidget: WidgetDef = {
    icon: <ArtIcon name="inventory" size={24} />,
    tone: "slate",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 2: the line toggles, the Add Item
      // button, and the recently-added list (1–5). Defaults:
      // lines on, no button, the latest five items (the
      // default was 1 until sheet row 51, 2026-11-15). The
      // data is the same two reads the widget has always
      // made — the search just asks for a few more names,
      // per the approved design.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const showValue = optBool(settings, "showValue", true);
      const showLatest = optBool(settings, "showLatest", true);
      const addButton = optBool(settings, "addButton", false);
      // Sheet row 51 (owner, 2026-11-15): the default was 1 —
      // a 394-tool account's widget showed exactly ONE row
      // in a mostly empty box. The default is now the full
      // glance of 5; the option still narrows it to 1.
      const recentCount = optNum(settings, "recentCount", 5, 1, 5);
      const [stats, tools] = await Promise.all([
        api<{
          total_items: number;
          total_value: string;
          warranties_expiring_soon?: number;
        }>("/inventory/stats"),
        api<{ id: string; name: string; location: string }[]>(
          "/inventory/search?limit=5",
        ),
      ]);
      const lines: string[] = [];
      if (showCount) {
        lines.push(line(t, "home.widget.toolsTracked", "{count} tools tracked", { count: count(stats.total_items) }));
      }
      if (showValue) {
        lines.push(line(t, "home.widget.totalValue", "Total value {value}", { value: formatMoney(stats.total_value, null, true) }));
      }
      // Sweep B1 (01-F7): a related fact the stats read already
      // carries — warranties about to expire — fills the panel
      // honestly when it is true, and stays absent when it isn't.
      if ((stats.warranties_expiring_soon ?? 0) > 0) {
        lines.push(
          line(t, "home.widget.warrantiesSoon", "{count} warranties expiring soon", {
            count: count(stats.warranties_expiring_soon ?? 0),
          }),
        );
      }
      const data: WidgetData = { lines };
      const recent = tools.slice(0, recentCount);
      if (showLatest && recent.length > 0) {
        // The recent items ride as proper rows at EVERY width
        // (widget remake, owner 2026-11-14: at half width they
        // used to collapse into bare name lines — his "JUNK"
        // class). Each row names the item and where it lives;
        // the column headings join at full width.
        data.header = [
          line(t, "home.widget.colItem", "Item"),
          line(t, "home.panel.location", "Location"),
        ];
        data.rowsClass = "tv-widget-rows--reports";
        data.rows = recent.map((tool) => ({
          cells: [tool.name, tool.location || "—"],
          href: `/inventory/${tool.id}`,
        }));
      }
      if (addButton) {
        // A real inner control: it rides the actions layer
        // above the whole-box cover, so the click starts the
        // wizard instead of following the box.
        data.actions = (
          <Link to="/inventory/new" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.addItem", "Add item")}
          </Link>
        );
      }
      return data;
    },
  };
