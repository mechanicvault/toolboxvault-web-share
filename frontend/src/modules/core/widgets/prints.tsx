import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { buttonClasses } from "../../../components";
import { ArtIcon } from "../../../components/ArtIcon";
import { browsePrints, getMyPrints, previewUrl } from "../../prints/api";
import type { PrintFileRow } from "../../prints/types";
import { optBool, optNum } from "../widgetOptions";
import type { WidgetTab, WidgetData, WidgetDef } from "./shared";
import { count, line } from "./shared";

export const printsWidget: WidgetDef = {
    icon: <ArtIcon name="parts" size={24} />,
    tone: "violet",
    cta: "viewAll",
    defaultOff: true,
    load: async (t, ctx) => {
      // Sample redesign (2026-11-15): the counts line
      // (shared / yours / downloads), then the two shelves
      // as in-widget TABS — New uploads and Most downloaded
      // switching in place, photo tiles with their star
      // ratings — and the three doors as the footer row.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const showRatings = optBool(settings, "showRatings", true);
      const showUpload = optBool(settings, "showUpload", true);
      const showNew = optBool(settings, "showNew", true);
      const showTop = optBool(settings, "showTop", true);
      const showMine = optBool(settings, "showMine", true);
      const showFiles = optBool(settings, "showFiles", true);
      const tilesToShow = optNum(settings, "tilesToShow", 8, 4, 12);
      const [newest, top, mine] = await Promise.all([
        browsePrints({ sort: "newest" }),
        browsePrints({ sort: "downloads" }).catch(() => null),
        getMyPrints().catch(() => null),
      ]);
      const data: WidgetData = { lines: [] };
      if (showCount) {
        const counts: { value: string; label: string }[] = [
          {
            value: count(newest.stats.listings),
            label: line(t, "home.widget.printsSharedWord", "shared"),
          },
        ];
        if (mine) {
          counts.push({
            value: count(mine.files.filter((f) => f.status === "live").length),
            label: line(t, "home.widget.printsYoursWord", "yours"),
          });
        }
        counts.push({
          value: count(newest.stats.downloads),
          label: line(t, "home.widget.printsDownloadsWord", "downloads"),
        });
        data.counts = counts;
      }
      const tile = (row: PrintFileRow, withRating: boolean) => ({
        thumb: row.has_preview ? previewUrl(row.id) : undefined,
        icon: <ArtIcon name="parts" size={30} />,
        title: row.title,
        sub:
          withRating && row.rating.count > 0 && row.rating.average !== null
            ? `★ ${row.rating.average.toFixed(1)} (${count(row.rating.count)})`
            : count(row.download_count),
        href: `/3dprints/${row.slug ?? row.id}`,
      });
      const tabs: WidgetTab[] = [];
      if (showNew && newest.files.length > 0) {
        tabs.push({
          id: "new",
          label: line(t, "home.widget.printsNew", "New uploads"),
          count: newest.total,
          strips: [
            {
              tiles: newest.files
                .slice(0, tilesToShow)
                .map((row) => tile(row, showRatings)),
            },
          ],
        });
      }
      if (showTop && top && top.files.length > 0) {
        tabs.push({
          id: "top",
          label: line(t, "home.widget.printsTop", "Most downloaded"),
          count: top.total,
          strips: [
            {
              tiles: top.files
                .slice(0, tilesToShow)
                .map((row) => tile(row, false)),
            },
          ],
        });
      }
      if (tabs.length > 0) data.tabs = tabs;
      const buttons: ReactNode[] = [];
      if (showMine) {
        buttons.push(
          <Link key="mine" to="/3dprints#my" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.printsMine", "My Uploads")}
          </Link>,
        );
      }
      if (showFiles) {
        buttons.push(
          <Link key="all" to="/3dprints" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.printsFiles", "All files")}
          </Link>,
        );
      }
      if (showUpload) {
        buttons.push(
          <Link key="up" to="/3dprints/upload" className={buttonClasses("primary", "sm")}>
            {line(t, "prints.upload", "Upload a print file")}
          </Link>,
        );
      }
      if (buttons.length > 0) {
        data.actions = <>{buttons}</>;
        data.actionsEnd = true;
      }
      return data;
    },
  };
