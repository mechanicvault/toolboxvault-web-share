import { Link } from "react-router-dom";
import { buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { api } from "../../../lib/api";
import { formatDate } from "../../../lib/format";
import { FileTypeArt } from "../../../components/FileTypeArt";
import { browsePrints, previewUrl } from "../../prints/api";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetTab, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const downloadsWidget: WidgetDef = {
    icon: <ArtIcon name="downloads" size={24} />,
    tone: "info",
    cta: "open",
    path: "/downloads",
    load: async (t, ctx) => {
      // Downloads widget REBUILT (dashboard-flare lane, owner
      // order 2026-11-09). Still NOT a module widget — Downloads
      // is a plain ungated door, seated as its own block in
      // CorePage. The shape is now the glanceable one Ryan
      // ordered: (b) a STATS GRID of the shelf's facts
      // (documents, wallpapers, 3D print files, total
      // downloads), (a) a thumbnail strip of the TOP DOWNLOADS
      // THIS WEEK from the dated download record (migration
      // 0098's download_events, read through
      // /downloads/top-window) — while that record is younger
      // than a week the strip labels itself "since <date>",
      // never a dressed-up week, and with no events at all it
      // says the chart starts with the first download instead
      // of inventing a ranking; and (c) an Open Downloads
      // button. The old cumulative most-downloaded lists retire
      // here (the page itself still ranks all-time); names ride
      // the shelf's dictionary copy, exactly as the page
      // speaks them.
      const settings = ctx?.settings ?? {};
      const showStats = optBool(settings, "showStats", true);
      const showWeekly = optBool(settings, "showWeekly", true);
      const tilesToShow = optNum(settings, "tilesToShow", 8, 4, 12);
      // Custom-widget aspect gate (Lane 2): the Open
      // Downloads button carries its own switch, defaulting
      // ON — absence is today's widget exactly.
      const showDoor = optBool(settings, "showDoor", true);
      const [catalog, shelf, topWindow, prints] = await Promise.all([
        api<{
          files: {
            key: string;
            format: string;
            filename: string;
            download_count: number;
          }[];
        }>("/downloads/catalog"),
        api<{
          wallpapers: {
            key: string;
            branded: boolean;
            download_count: number;
          }[];
        }>("/downloads/wallpapers"),
        api<{
          window_days: number;
          tracking_since: string | null;
          items: { key: string; kind: string; count: number }[];
        }>("/downloads/top-window"),
        browsePrints({}).catch(() => null),
      ]);
      // Sample redesign (2026-11-15): the counts line, then
      // the shelves as in-widget TABS with gallery tiles —
      // Documents (a PDF wears a PDF icon), Wallpapers
      // (photo tiles), 3D print files, and Downloads (the
      // top-downloaded chart, the weekly strip's honest
      // window) — and the single footer door.
      const data: WidgetData = { lines: [] };
      const totalDownloads =
        catalog.files.reduce((sum, f) => sum + f.download_count, 0) +
        shelf.wallpapers.reduce((sum, w) => sum + w.download_count, 0) +
        (prints?.files ?? []).reduce((sum, it) => sum + it.download_count, 0);
      if (showStats) {
        data.counts = [
          {
            value: count(catalog.files.length),
            label: line(t, "home.widget.dlWordDocuments", "documents"),
          },
          {
            value: count(shelf.wallpapers.length),
            label: line(t, "home.widget.dlWordWallpapers", "wallpapers"),
          },
        ];
        if (prints) {
          data.counts.push({
            value: count(prints.total),
            label: line(t, "home.widget.dlWordPrints", "3D print files"),
          });
        }
        data.counts.push({
          value: count(totalDownloads),
          label: line(t, "home.widget.dlWordDownloads", "downloads"),
        });
      }
      const tabs: WidgetTab[] = [];
      const cap = tilesToShow;
      // Sheet row 51 (owner, 2026-11-15): the Documents tab is
      // a LIST, not a tile strip — name on the left, the
      // file-type icon in its own right column on every row.
      tabs.push({
        id: "documents",
        label: line(t, "home.widget.dlStatDocuments", "Documents"),
        count: catalog.files.length,
        rowsVisible: cap,
        rowsClass: "tv-widget-rows--reports",
        rows: catalog.files.slice(0, cap).map((f) => ({
          cells: [
            <span key="name" className="tv-widget-cellstack">
              <span>{line(t, `downloads.file.${f.key}.name`, f.filename)}</span>
              <span className="tv-widget-cellsub">
                {line(t, "home.widget.dlKindDocument", "Document")}
              </span>
            </span>,
            <FileTypeArt
              key="icon"
              kind={f.format === "xlsx" ? "sheet" : "pdf"}
              height={30}
            />,
          ],
          href: "/downloads#documents",
        })),
        emptyText: line(t, "home.widget.dlNoneDocuments", "No documents yet."),
      });
      tabs.push({
        id: "wallpapers",
        label: line(t, "home.widget.dlStatWallpapers", "Wallpapers"),
        count: shelf.wallpapers.length,
        strips:
          shelf.wallpapers.length > 0
            ? [
                {
                  tiles: shelf.wallpapers.slice(0, cap).map((w) => ({
                    thumb: `/api/downloads/wallpapers/${w.key}/view/thumb`,
                    icon: <ArtIcon name="downloads" size={30} />,
                    title: line(t, `downloads.wallpaper.${w.key}.name`, w.key),
                    sub: line(t, "home.widget.dlKindWallpaper", "Wallpaper"),
                    href: "/downloads#wallpapers",
                  })),
                },
              ]
            : undefined,
        emptyText: line(t, "home.widget.dlNoneWallpapers", "No wallpapers yet."),
      });
      if (prints) {
        tabs.push({
          id: "prints",
          label: line(t, "home.widget.dlStatPrints", "3D print files"),
          count: prints.total,
          strips:
            prints.files.length > 0
              ? [
                  {
                    tiles: prints.files.slice(0, cap).map((it) => ({
                      thumb: it.has_preview ? previewUrl(it.id) : undefined,
                      icon: <ArtIcon name="parts" size={30} />,
                      title: it.title,
                      sub: line(t, "home.widget.dlKindPrint", "3D print file"),
                      href: `/3dprints/${it.slug ?? it.id}`,
                    })),
                  },
                ]
              : undefined,
          emptyText: line(t, "home.widget.dlNonePrints", "No print files yet."),
        });
      }
      if (showWeekly) {
        const docByKey = new Map(catalog.files.map((f) => [f.key, f]));
        const items = topWindow.items.slice(0, cap);
        const since = topWindow.tracking_since
          ? new Date(topWindow.tracking_since)
          : null;
        const fullWeek =
          since != null &&
          Date.now() - since.getTime() >= 7 * 24 * 3600 * 1000;
        tabs.push({
          id: "downloads",
          label: line(t, "home.widget.dlStatDownloads", "Downloads"),
          count: totalDownloads,
          // Sheet row 51: the top-downloads chart is a LIST
          // too — the window label rides as the group label,
          // each row's visual (wallpaper thumb or file-type
          // icon) sits in the right column.
          groups:
            items.length > 0
              ? [
                  {
                    label: fullWeek
                      ? line(t, "home.widget.dlTopWeek", "Top downloads · last 7 days")
                      : line(t, "home.widget.dlTopSince", "Top downloads since {date}", {
                          date: since ? formatDate(since.toISOString()) : "",
                        }),
                    rowsClass: "tv-widget-rows--reports",
                    rows: items.map((item) =>
                      item.kind === "wallpaper"
                        ? {
                            cells: [
                              <span key="name" className="tv-widget-cellstack">
                                <span>{line(t, `downloads.wallpaper.${item.key}.name`, item.key)}</span>
                                <span className="tv-widget-cellsub">{count(item.count)}</span>
                              </span>,
                              <img
                                key="thumb"
                                className="tv-widget-filethumb"
                                src={`/api/downloads/wallpapers/${item.key}/view/thumb`}
                                alt=""
                              />,
                            ],
                            href: "/downloads#wallpapers",
                          }
                        : {
                            cells: [
                              <span key="name" className="tv-widget-cellstack">
                                <span>
                                  {line(
                                    t,
                                    `downloads.file.${item.key}.name`,
                                    docByKey.get(item.key)?.filename ?? item.key,
                                  )}
                                </span>
                                <span className="tv-widget-cellsub">{count(item.count)}</span>
                              </span>,
                              <FileTypeArt
                                key="icon"
                                kind={
                                  docByKey.get(item.key)?.format === "xlsx"
                                    ? "sheet"
                                    : "pdf"
                                }
                                height={30}
                              />,
                            ],
                            href: "/downloads#documents",
                          },
                    ),
                  },
                ]
              : undefined,
          emptyText: line(
            t,
            "home.widget.dlNoneDownloads",
            "No downloads yet — the chart starts with the first one.",
          ),
        });
      }
      if (showStats || tabs.length > 0) data.tabs = tabs;
      if (showDoor) {
        data.actionsEnd = true;
        data.actions = (
          <Link to="/downloads" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.dlOpen", "Open downloads")}
          </Link>
        );
      }
      return data;
    },
  };
