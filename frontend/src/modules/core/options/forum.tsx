import { useEffect, useState } from "react";
import { useT } from "../../../i18n/LocaleContext";
import { listFavorites } from "../../forum/api";
import type { ForumFavorite } from "../../forum/types";
import { WidgetOptionsApi, OptionsGroup } from "./shared";

export function ForumOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const [favorites, setFavorites] = useState<ForumFavorite[] | null>(null);
  useEffect(() => {
    let live = true;
    listFavorites()
      .then((favs) => {
        if (live) setFavorites(favs);
      })
      .catch(() => {
        if (live) setFavorites([]);
      });
    return () => {
      live = false;
    };
  }, []);
  const pick =
    typeof api.block.settings.featured === "string"
      ? api.block.settings.featured
      : "";
  return (
    <OptionsGroup label={t("home.opt.forum.featured")}>
      <div className="tv-fav-picks">
        <button
          type="button"
          className="tv-fav-pick"
          aria-pressed={pick === ""}
          onClick={() => api.setSetting("featured", undefined)}
        >
          <span className="tv-fav-pick-title">
            {t("home.opt.forum.mostRecent")}
          </span>
        </button>
        {(favorites ?? []).map((f) => {
          const key = `${f.kind}:${f.target_id}`;
          return (
            <button
              key={key}
              type="button"
              className="tv-fav-pick"
              aria-pressed={pick === key}
              onClick={() => api.setSetting("featured", key)}
            >
              <span className="tv-fav-pick-title">{f.title}</span>
              <span className="tv-fav-pick-board">{f.board_name}</span>
            </button>
          );
        })}
      </div>
      {favorites !== null && favorites.length === 0 && (
        <p className="tv-muted">{t("home.opt.forum.none")}</p>
      )}
    </OptionsGroup>
  );
}

/** Notifications (Wave 4 batch A): how many rows show before
 *  the list scrolls inside the block (3 / 5 / 8 — 5 is today's
 *  cap), the maintenance overdue line, and unread-only. The
 *  block itself reads the same keys through the same helpers;
 *  defaults are today's block exactly. */
