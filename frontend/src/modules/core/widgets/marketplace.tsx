import { type ReactNode } from "react";
import { ArtIcon } from "../../../components/ArtIcon";
import { formatMoney } from "../../../lib/money";
import { getBoard as getMarketplaceBoard } from "../../marketplace/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { line } from "./shared";

export const marketplaceWidget: WidgetDef = {
    icon: <ArtIcon name="marketplace" size={24} />,
    tone: "success",
    cta: "viewAll",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark): the listings ride as rows — 3 is
      // today's glance, the choice takes it to 5 — and
      // each listing's price can sit beside its title
      // (off by default: today's widget shows titles
      // only). At full width with prices on, the rows
      // take their title · price table shape. The board
      // already carries the prices, in the seller's
      // currency.
      const settings = ctx?.settings ?? {};
      const showPrices = optBool(settings, "showPrices", false);
      const listingCount = optNum(settings, "listingCount", 3, 3, 5);
      const board = await getMarketplaceBoard({});
      const data: WidgetData = { lines: [] };
      const shown = board.slice(0, listingCount);
      if (shown.length > 0) {
        const full = ctx?.size === "full";
        if (full && showPrices) {
          data.header = [
            line(t, "home.widget.colTitle", "Title"),
            line(t, "inventory.col.price", "Price"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-marketplace";
        data.rows = shown.map((l) => {
          const cells: ReactNode[] = [l.title];
          if (showPrices) {
            cells.push(
              l.price != null
                ? formatMoney(l.price, l.seller_currency)
                : line(t, "home.widget.makeOffer", "Make offer"),
            );
          }
          return { cells };
        });
      }
      return data;
    },
  };
