import { type ReactNode } from "react";
import { ArtIcon } from "../../../components/ArtIcon";
import { listWishlist } from "../../wishlist/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const wishlistWidget: WidgetDef = {
    icon: <ArtIcon name="wishlist" size={24} />,
    tone: "slate",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark): the three lines each get a switch, and
      // the wanted items ride as rows — a few visible,
      // the rest scrolling inside the box. The rows take
      // the Latest line's place (the latest item is the
      // first row); putting the rows away (0) brings the
      // Latest line back. At full width each row carries
      // its priority marker beside the title. The full
      // list already loads to count it.
      const settings = ctx?.settings ?? {};
      const showWanted = optBool(settings, "showWanted", true);
      const showHigh = optBool(settings, "showHigh", true);
      const showLatest = optBool(settings, "showLatest", true);
      const wantedRows = optNum(settings, "wantedRows", 3, 0, 5);
      const items = await listWishlist();
      const wanted = items.filter((i) => i.status === "wanted");
      const lines: string[] = [];
      if (showWanted) {
        lines.push(line(t, "home.widget.wanted", "{count} wanted", { count: count(wanted.length) }));
      }
      const high = wanted.filter((i) => i.priority === "high").length;
      if (showHigh && high > 0) {
        lines.push(line(t, "home.widget.highPriority", "{count} high priority", { count: count(high) }));
      }
      const data: WidgetData = { lines };
      if (wantedRows > 0 && wanted.length > 0) {
        const full = ctx?.size === "full";
        if (full) {
          data.header = [
            line(t, "home.widget.colItem", "Item"),
            line(t, "home.widget.colPriority", "Priority"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-wishlist";
        data.rowsVisible = wantedRows;
        data.rows = wanted.map((i) => {
          const cells: ReactNode[] = [i.title];
          if (full) {
            cells.push(line(t, `home.widget.priority.${i.priority}`, i.priority));
          }
          return { cells };
        });
      } else if (showLatest && wanted[0]) {
        lines.push(line(t, "home.widget.latest", "Latest: {name}", { name: wanted[0].title }));
      }
      return data;
    },
  };
