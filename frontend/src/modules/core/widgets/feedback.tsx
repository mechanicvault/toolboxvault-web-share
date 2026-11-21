import { Link } from "react-router-dom";
import { buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { formatDate } from "../../../lib/format";
import { getBoard } from "../../feedback/api";
import { UrgencyPill } from "../../feedback/urgency";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetTab, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const feedbackWidget: WidgetDef = {
    icon: <ArtIcon name="feedback" size={24} />,
    tone: "slate",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B: the newest titles
      // from each board ride as rows — the boards already
      // load in full to count them, so the titles are in
      // hand. Rows are grouped per board: stacked at half
      // width, side by side as two titled columns at full.
      // Each row links to its post's own page. 0 per board
      // puts the rows away (today's counts-only widget).
      const settings = ctx?.settings ?? {};
      const showCounts = optBool(settings, "showCounts", true);
      const perBoard = optNum(settings, "rowsPerBoard", 3, 0, 3);
      // Custom-widget aspect gates (Lane 2): each board's
      // rows carry their own switch, both defaulting ON —
      // absence is today's widget exactly.
      const showBugRows = optBool(settings, "showBugRows", true);
      const showFeatureRows = optBool(settings, "showFeatureRows", true);
      const [bugs, features] = await Promise.all([
        getBoard("bug", true),
        getBoard("feature", true),
      ]);
      // Sample redesign (2026-11-15): the counts line, then
      // the two boards as TABS switching in place. Each row
      // wears the sample's shape: the title with its standing
      // and date as the quiet sub-line, the urgency pill, and
      // the votes. The per-board switches gate their tab; the
      // rows-per-board count caps each tab's rows (0 = the
      // counts line alone, as before).
      const counts: { value: string; label: string }[] = [];
      if (showCounts) {
        counts.push({
          value: count(bugs.length),
          label: line(t, "home.widget.boardBugWord", "bug reports"),
        });
        counts.push({
          value: count(features.length),
          label: line(t, "home.widget.boardFeatureWord", "feature ideas"),
        });
      }
      const data: WidgetData = { lines: [] };
      if (counts.length > 0) data.counts = counts;
      const toRows = (posts: typeof bugs) =>
        posts.slice(0, perBoard).map((p) => ({
          cells: [
            <span key="title" className="tv-widget-cellstack">
              <span>{p.title}</span>
              <span className="tv-widget-cellsub">
                {line(t, `feedback.status.${p.status}`, p.status)}
                {" · "}
                {formatDate(p.created_at.slice(0, 10))}
              </span>
            </span>,
            <UrgencyPill key="u" urgency={p.urgency} />,
            `▲ ${count(p.vote_count)}`,
          ],
          href: `/feedback/post/${p.id}`,
        }));
      if (perBoard > 0) {
        const tabs: WidgetTab[] = [];
        if (showBugRows) {
          tabs.push({
            id: "bugs",
            label: line(t, "home.widget.feedbackBugs", "Bug reports"),
            count: bugs.length,
            rowsVisible: perBoard,
            rowsClass: "tv-widget-rows--reports",
            emptyText: line(t, "home.widget.noBugPosts", "No bug reports"),
            rows: toRows(bugs),
          });
        }
        if (showFeatureRows) {
          tabs.push({
            id: "features",
            label: line(t, "home.widget.feedbackFeatures", "Feature ideas"),
            count: features.length,
            rowsVisible: perBoard,
            rowsClass: "tv-widget-rows--reports",
            emptyText: line(t, "home.widget.noFeaturePosts", "No feature ideas"),
            rows: toRows(features),
          });
        }
        if (tabs.length > 0) data.tabs = tabs;
      }
      data.actionsEnd = true;
      data.actions = (
        <>
          <Link to="/feedback/bugs" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.reportBugBtn", "Report a bug")}
          </Link>
          <Link to="/feedback" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.openFeedbackBtn", "Open feedback")}
          </Link>
        </>
      );
      return data;
    },
  };
