import { ArtIcon } from "../../../components/ArtIcon";
import { listTemplates } from "../../reports/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const reportsWidget: WidgetDef = {
    icon: <ArtIcon name="reports" size={24} />,
    tone: "violet",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch A: the saved reports ride
      // as real rows — 2 visible before scrolling is today's
      // shape; the option takes it to 5. The list already loads
      // in full. Reports redesign (2026-11-06): the saved
      // reports are the page's TEMPLATES now — at full width
      // each row links to the tab that template lives on
      // (Quick Reports on #new, Accounting on #accounting); at
      // half width the rows stay names, and the box's own cover
      // link rules the click.
      const settings = ctx?.settings ?? {};
      const rowsVisible = optNum(settings, "rowsVisible", 2, 2, 5);
      // Custom-widget aspect gates (Lane 2): the count line
      // and the template rows carry their own switches, both
      // defaulting ON — absence is today's widget exactly.
      const showCount = optBool(settings, "showCount", true);
      const showRows = optBool(settings, "showRows", true);
      const { templates } = await listTemplates();
      // Sheet row 110: the count line means reports the member
      // actually saved — the seven seeded defaults (is_default)
      // are the page's starter templates, not the user's saved
      // reports, and a brand-new user must not read "7 saved".
      // (The rows below still list every template: they are the
      // doors to the Reports page, defaults included.)
      const savedCount = templates.filter((x) => !x.is_default).length;
      const lines = showCount
        ? [
            line(t, "home.widget.savedReports", "{count} saved reports", { count: count(savedCount) }),
          ]
        : [];
      const data: WidgetData = { lines };
      if (showRows && templates.length > 0) {
        const full = ctx?.size === "full";
        data.rowsVisible = rowsVisible;
        data.rows = templates.map((c) =>
          full
            ? {
                cells: [c.name],
                href: c.area === "accounting" ? "/reports#accounting" : "/reports#new",
              }
            : { cells: [c.name] },
        );
      }
      return data;
    },
  };
