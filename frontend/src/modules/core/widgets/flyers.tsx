import { ArtIcon } from "../../../components/ArtIcon";
import { flyerFeed, flyerRecentPast } from "../../flyers/api";
import { sourceTitle } from "../../flyers/types";
import { optBool } from "../widgetOptions";
import type { WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const flyersWidget: WidgetDef = {
    icon: <ArtIcon name="flyers" size={24} />,
    tone: "accent",
    cta: "viewAll",
    load: async (t, ctx) => {
      // Flyers (2026-11-06): thumbnail teasers of THIS WEEK's
      // flyers from the user's connected dealers/agents. The
      // options choose which sources show (hiddenSources holds
      // the unchecked ones; absence shows everything). A row
      // click lands on the flyer page at that source's tab.
      const settings = ctx?.settings ?? {};
      const raw = settings.hiddenSources;
      const hidden = new Set(Array.isArray(raw) ? raw : []);
      // Custom-widget aspect gates (Lane 2): the count line
      // and the source rows carry their own switches, both
      // defaulting ON — absence is today's widget exactly.
      const showCount = optBool(settings, "showCount", true);
      const showRows = optBool(settings, "showRows", true);
      const feed = await flyerFeed();
      const shown = feed.filter((s) => !hidden.has(s.key));
      const lines = showCount
        ? [
            shown.length === 1
              ? line(t, "flyers.widgetOne", "1 flyer up this week")
              : line(t, "flyers.widgetLive", "{count} flyers up this week", {
                  count: count(shown.length),
                }),
          ]
        : [];
      const data: WidgetData = { lines };
      if (showRows && shown.length > 0) {
        data.rowsVisible = 3;
        // Sheet row 51 (owner, 2026-11-15): the rows carried
        // no column class, so the flyer's label floated
        // mid-row wherever the source name ended. The files
        // grid puts the label in its own right column, the
        // same seat on every row.
        data.rowsClass = "tv-widget-rows--reports";
        data.rows = shown.map((s) => ({
          cells: [
            <span key="who" className="tv-widget-cellstack">
              <span>{sourceTitle(s)}</span>
              <span className="tv-widget-cellsub">
                {s.current?.label ||
                  `${s.current?.starts_on} → ${s.current?.ends_on}`}
              </span>
            </span>,
            // Sheet row 55 (owner, 2026-11-15): the small
            // thumbnail sits in the RIGHT column, like the
            // Reports rows are structured — not beside the
            // name on the left.
            s.current?.thumb_url ? (
              <img
                key="thumb"
                className="flyer-widget-thumb"
                src={s.current.thumb_url}
                alt=""
              />
            ) : null,
          ],
          href: `/flyers#${s.key}`,
        }));
      }
      if (showRows && shown.length === 0) {
        // Sheet row 51 (owner, 2026-11-15): nothing live this
        // week used to leave a bare "0 flyers" line in a big
        // empty box. The most recent flyers that DID run ride
        // as rows instead — real history, honestly labelled.
        try {
          const past = await flyerRecentPast();
          const visiblePast = past.filter((r) => !hidden.has(r.key));
          if (visiblePast.length > 0) {
            data.groups = [
              {
                label: line(
                  t,
                  "flyers.widgetRecentGroup",
                  "Most recent flyers",
                ),
                rowsClass:
                  "tv-widget-rows--reports",
                rows: visiblePast.map((r) => ({
                  cells: [
                    <span key="who" className="tv-widget-cellstack">
                      <span>
                        {r.agent_name
                          ? `${r.agent_name} · ${r.company_name}`
                          : r.company_name}
                      </span>
                      <span className="tv-widget-cellsub">
                        {r.flyer.label ||
                          `${r.flyer.starts_on} → ${r.flyer.ends_on}`}
                      </span>
                    </span>,
                    // Sheet row 55: thumbnail in the right
                    // column, same as the current rows above.
                    r.flyer.thumb_url ? (
                      <img
                        key="thumb"
                        className="flyer-widget-thumb"
                        src={r.flyer.thumb_url}
                        alt=""
                      />
                    ) : null,
                  ],
                  href: `/flyers#${r.key}`,
                })),
                visible: 3,
              },
            ];
          }
        } catch {
          // The fallback is a garnish — the count line stands.
        }
      }
      return data;
    },
  };
