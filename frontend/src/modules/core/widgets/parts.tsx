import { type ReactNode } from "react";
import { ArtIcon } from "../../../components/ArtIcon";
import { getPartsStats, listParts } from "../../parts/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const partsWidget: WidgetDef = {
    icon: <ArtIcon name="parts" size={24} />,
    tone: "teal",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark, appears when the module returns): the
      // parts ride as rows instead of bare title lines —
      // 2 visible before the rest scroll, today's count —
      // and at full width each row gains its quantity
      // beside the title, from the same loaded list. The
      // shelf count line gets its switch.
      const settings = ctx?.settings ?? {};
      const showShelf = optBool(settings, "showShelf", true);
      const visibleRows = optNum(settings, "visibleRows", 2, 2, 5);
      const [stats, parts] = await Promise.all([
        getPartsStats(),
        listParts({}),
      ]);
      const lines: string[] = [];
      if (showShelf) {
        lines.push(line(t, "home.widget.partsOnShelf", "{count} parts on the shelf", { count: count(stats.parts_count) }));
      }
      const data: WidgetData = { lines };
      if (parts.length > 0) {
        const full = ctx?.size === "full";
        if (full) {
          data.header = [
            line(t, "home.widget.colPart", "Part"),
            line(t, "home.widget.colQty", "Qty"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-parts";
        data.rowsVisible = visibleRows;
        data.rows = parts.map((p) => {
          const cells: ReactNode[] = [p.title];
          if (full) cells.push(count(p.quantity));
          return { cells };
        });
      }
      return data;
    },
  };
