import { Link } from "react-router-dom";
import { Badge, buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { formatDate } from "../../../lib/format";
import { getCategories, getThreads, listFavorites } from "../../forum/api";
import type { WidgetRowGroup, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const forumWidget: WidgetDef = {
    icon: <ArtIcon name="forum" size={24} />,
    tone: "info",
    cta: "open",
    load: async (t, ctx) => {
      // Sample redesign (2026-11-15): a banner for the
      // starred thread that moved most recently, the
      // counts, then STARRED THREADS and HOT THIS WEEK as
      // ruled rows — every row linking straight to its
      // thread (owner, 2026-11-15). The forum keeps no
      // read-state, so nothing here claims replies are
      // unread; "hot" is ranked from this week's boards by
      // reply count, read board by board with soft fails.
      const cats = await getCategories(true);
      const threadsTotal = cats.reduce((n, c) => n + c.thread_count, 0);
      let favorites: Awaited<ReturnType<typeof listFavorites>> = [];
      try {
        favorites = await listFavorites();
      } catch {
        favorites = [];
      }
      const data: WidgetData = { lines: [] };
      data.counts = [
        {
          value: count(cats.length),
          label: line(t, "home.widget.forumBoardsWord", "boards"),
        },
        {
          value: count(threadsTotal),
          label: line(t, "home.widget.forumThreadsWord", "threads"),
        },
        {
          value: count(favorites.length),
          label: line(t, "home.widget.forumStarredWord", "starred threads"),
        },
      ];
      const threadHref = (kind: string, id: string) =>
        kind === "thread" ? `/forum/thread/${id}` : `/feedback/post/${id}`;
      const featured =
        typeof ctx?.settings?.featured === "string"
          ? favorites.find(
              (f) => `${f.kind}:${f.target_id}` === ctx.settings.featured,
            ) ?? favorites[0]
          : favorites[0];
      if (featured) {
        data.banner = (
          <div className="tv-forum-banner-in">
            <div className="tv-borrow-banner-text">
              <span className="tv-forum-banner-eyebrow">
                {line(t, "home.widget.forumStarredEyebrow", "Starred thread")}
              </span>
              <strong>{featured.title}</strong>
              <span>
                {featured.board_name} ·{" "}
                {line(t, "home.widget.forumLastReply", "last reply {date}", {
                  date: formatDate(featured.last_activity_at.slice(0, 10)),
                })}
              </span>
            </div>
            <Link
              to={threadHref(featured.kind, featured.target_id)}
              className={buttonClasses("primary", "sm")}
            >
              {line(t, "home.widget.forumRead", "Read")}
            </Link>
          </div>
        );
      }
      const replyBadge = (n: number) => (
        <Badge tone="neutral">
          {line(t, "home.widget.forumReplies", "{count} replies", {
            count: count(n),
          })}
        </Badge>
      );
      const groups: WidgetRowGroup[] = [];
      if (favorites.length > 0) {
        groups.push({
          label: line(t, "home.widget.forumStarredGroup", "Starred threads"),
          rowsClass: "tv-widget-rows--reports",
          rows: favorites.slice(0, 3).map((f) => ({
            cells: [
              <span key="s" className="tv-widget-cellstack">
                <span>{f.title}</span>
                <span className="tv-widget-cellsub">
                  {f.board_name} · {formatDate(f.last_activity_at.slice(0, 10))}
                </span>
              </span>,
              replyBadge(f.reply_count),
            ],
            href: threadHref(f.kind, f.target_id),
          })),
          visible: 3,
        });
      }
      // Hot this week: every board's threads, ranked by
      // replies among threads active in the last 7 days,
      // starred ones left to their own group.
      try {
        const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
        const starredIds = new Set(favorites.map((f) => f.target_id));
        const boardName = new Map(cats.map((c) => [c.id, c.name]));
        const lists = await Promise.all(
          cats.map((c) => getThreads(c.id, true).catch(() => [])),
        );
        const hot = lists
          .flat()
          .filter(
            (th) =>
              !starredIds.has(th.id) &&
              new Date(th.last_post_at).getTime() >= weekAgo,
          )
          .sort((a, b) => b.reply_count - a.reply_count)
          .slice(0, 3);
        if (hot.length > 0) {
          groups.push({
            label: line(t, "home.widget.forumHotGroup", "Hot this week"),
            rowsClass: "tv-widget-rows--reports",
            rows: hot.map((th) => ({
              cells: [
                <span key="s" className="tv-widget-cellstack">
                  <span>{th.title}</span>
                  <span className="tv-widget-cellsub">
                    {boardName.get(th.category_id) ?? ""} ·{" "}
                    {formatDate(th.last_post_at.slice(0, 10))}
                  </span>
                </span>,
                replyBadge(th.reply_count),
              ],
              href: `/forum/thread/${th.id}`,
            })),
            visible: 3,
          });
        }
        // Sheet row 51 (owner, 2026-11-15): with nothing
        // starred and nothing hot this week the widget used
        // to collapse to a counts line + a hint + a door
        // button while threads sat in the forum unseen.
        // The fallback is the latest threads themselves —
        // most recent activity first, whatever the date.
        if (groups.length === 0) {
          const latest = lists
            .flat()
            .sort(
              (a, b) =>
                new Date(b.last_post_at).getTime() -
                new Date(a.last_post_at).getTime(),
            )
            .slice(0, 3);
          if (latest.length > 0) {
            groups.push({
              label: line(t, "home.widget.forumLatestGroup", "Latest threads"),
              rowsClass: "tv-widget-rows--reports",
              rows: latest.map((th) => ({
                cells: [
                  <span key="s" className="tv-widget-cellstack">
                    <span>{th.title}</span>
                    <span className="tv-widget-cellsub">
                      {boardName.get(th.category_id) ?? ""} ·{" "}
                      {formatDate(th.last_post_at.slice(0, 10))}
                    </span>
                  </span>,
                  replyBadge(th.reply_count),
                ],
                href: `/forum/thread/${th.id}`,
              })),
              visible: 3,
            });
          }
        }
      } catch {
        // Hot is a garnish — the starred group stands alone.
      }
      if (groups.length > 0) data.groups = groups;
      if (favorites.length === 0 && groups.length === 0) {
        data.linesAfter = [
          line(
            t,
            "home.widget.favEmpty",
            "Star a thread in the forum and it will be featured here.",
          ),
        ];
      }
      data.actions = (
        <>
          <Link to="/forum" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.forumNewThread", "New thread")}
          </Link>
          <Link to="/forum" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.forumOpen", "Open forum")}
          </Link>
        </>
      );
      data.actionsEnd = true;
      return data;
    },
  };
