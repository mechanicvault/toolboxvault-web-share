import { Link } from "react-router-dom";
import { Badge, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { getExpansionSummary, getExpansions } from "../../tool-expansion/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const toolExpansionWidget: WidgetDef = {
    icon: <ArtIcon name="expansion" size={24} />,
    tone: "accent",
    cta: "viewAll",
    load: async (t, ctx) => {
      // Sample redesign (2026-11-15): the counts line,
      // then SUGGESTED ADD-ONS as soft rows — a colored
      // dot, the piece with the item it expands quiet
      // underneath, and its model number as the chip in
      // its own column. (The catalog carries no fit-kind,
      // so no fit word is invented for the chip.) The
      // full suggestions read supplies the per-item rows;
      // the summary keeps the headline count honest.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const rowsToShow = optNum(settings, "rowsToShow", 3, 2, 5);
      const showRows = optBool(settings, "showRows", true);
      const summary = await getExpansionSummary();
      const data: WidgetData = { lines: [] };
      let groups: Awaited<ReturnType<typeof getExpansions>> | null =
        null;
      try {
        groups = await getExpansions();
      } catch {
        groups = null;
      }
      if (showCount) {
        const counts: { value: string; label: string }[] = [
          {
            value: count(summary.count),
            label: line(t, "home.widget.expKnownWord", "known add-ons"),
          },
        ];
        if (groups && groups.groups.length > 0) {
          counts.push({
            value: count(groups.groups.length),
            label: line(t, "home.widget.expForToolsWord", "of your tools"),
          });
        }
        data.counts = counts;
      }
      if (showRows && groups) {
        const dotTones = ["var(--accent)", "var(--success)", "var(--info)", "var(--warning)"];
        const flat = groups.groups.flatMap((g) =>
          g.suggestions.map((sug) => ({ sug, item: g.item })),
        );
        if (flat.length > 0) {
          data.groups = [
            {
              label: line(t, "home.widget.expSuggestedGroup", "Suggested add-ons"),
              rowsClass: "tv-widget-rows--reports",
              rows: flat.slice(0, rowsToShow).map(({ sug, item }, i) => ({
                cells: [
                  <span
                    key="d"
                    className="tv-widget-dot"
                    style={{ background: dotTones[i % dotTones.length] }}
                  />,
                  <span key="s" className="tv-widget-cellstack">
                    <span>{sug.name}</span>
                    <span className="tv-widget-cellsub">
                      {line(t, "home.widget.expForYour", "For your {item}", {
                        item: item.name,
                      })}
                    </span>
                  </span>,
                  <Badge key="m" tone="neutral">{sug.model_number}</Badge>,
                ],
              })),
              visible: rowsToShow,
            },
          ];
        }
      }
      data.actions = (
        <>
          <Link to="/inventory#expand" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.expBrowse", "Browse catalog")}
          </Link>
          <Link to="/inventory#expand" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.expOpen", "Open tool expansion")}
          </Link>
        </>
      );
      data.actionsEnd = true;
      return data;
    },
  };
