import { useCallback, useEffect, useRef, useState } from "react";
import { getItemStanding } from "../api";
import type { CareItemKind, ItemStanding } from "../types";
import { SchedulesPanel } from "./SchedulesPanel";

/**
 * The Maintenance tab body on a tool/battery detail page: the
 * item's schedules, fed by ONE fetch of the maintenance module's
 * standing endpoint.
 *
 * Repairs used to live here too — since the repairs ∪ claims
 * merge (2026-11-04) a repair IS a claim, worked from the
 * Claims / Replace tab and the claim's own page, so this tab
 * keeps schedules only.
 *
 * Best-effort by design, like the LendingPanel beside it: if the
 * maintenance module isn't effective for this user (403
 * module_unavailable) the panels never appear; a later reload
 * hiccup keeps the last good data on screen.
 */
export function ItemCarePanels({
  itemKind,
  itemId,
}: {
  itemKind: Exclude<CareItemKind, "piece">;
  itemId: string;
}) {
  const [standing, setStanding] = useState<ItemStanding | null>(null);
  const [hidden, setHidden] = useState(false);
  const loadedRef = useRef(false);

  const load = useCallback(() => {
    getItemStanding(itemKind, itemId)
      .then((next) => {
        loadedRef.current = true;
        setStanding(next);
      })
      .catch(() => {
        if (!loadedRef.current) setHidden(true);
      });
  }, [itemKind, itemId]);

  useEffect(load, [load]);

  if (hidden || standing === null) return null;

  return (
    <div className="tv-item-stack">
      <SchedulesPanel standing={standing} onChanged={load} />
    </div>
  );
}
