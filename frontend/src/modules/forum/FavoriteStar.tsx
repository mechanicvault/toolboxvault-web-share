import { useEffect, useState } from "react";

import { useToast } from "../../components";
import { StarIcon } from "../../components/icons";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { listFavorites, starFavorite, unstarFavorite } from "./api";
import type { ForumFavoriteKind } from "./types";

/**
 * The favorite star (forum favorites, widget options Wave 3):
 * the toggle in a thread page's header — and, for the permanent
 * boards, in a board post's page header. It learns its state
 * from the member's own favorites list (the feature's only
 * reader — there is no per-target endpoint to chatter with),
 * flips optimistically on a tap, and rolls back with a toast
 * if the server refuses. Signed-out visitors never see it:
 * reading is public, but a star is account furniture.
 */
export function FavoriteStar({
  kind,
  targetId,
  signedIn,
}: {
  kind: ForumFavoriteKind;
  targetId: string;
  signedIn: boolean;
}) {
  const t = useT();
  const { toast } = useToast();
  const [starred, setStarred] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!signedIn) return;
    let live = true;
    listFavorites()
      .then((favs) => {
        if (live) {
          setStarred(
            favs.some((f) => f.kind === kind && f.target_id === targetId),
          );
        }
      })
      .catch(() => {
        if (live) setStarred(false);
      });
    return () => {
      live = false;
    };
  }, [kind, targetId, signedIn]);

  if (!signedIn || starred === null) return null;

  const toggle = async () => {
    const next = !starred;
    setStarred(next);
    setBusy(true);
    try {
      if (next) await starFavorite(kind, targetId);
      else await unstarFavorite(kind, targetId);
    } catch (err) {
      setStarred(!next);
      toast(
        err instanceof ApiError ? err.message : t("forum.favorite.error"),
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  };

  const label = starred ? t("forum.favorited") : t("forum.favorite");
  return (
    <button
      type="button"
      className="tv-fav-btn"
      aria-pressed={starred}
      aria-label={label}
      title={label}
      disabled={busy}
      onClick={() => void toggle()}
    >
      <StarIcon size={16} />
      <span>{label}</span>
    </button>
  );
}
