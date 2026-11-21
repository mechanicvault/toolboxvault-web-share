/** The seller rating badge for surfaces whose payloads don't
 *  carry reputation (the Community Parts pool's pinned payload
 *  predates the engine and keeps its exact keys). Reads the
 *  member's public profile — the ONE aggregate, via messaging's
 *  profile route — once per seller per page session and renders
 *  the shared badge text. Renders nothing until it knows, and
 *  nothing at all on failure (a badge is decoration; the
 *  profile page is the record). */

import { useEffect, useState } from "react";
import { getPublicProfile } from "../messaging/api";
import { reputationBadge, type ReputationSummary } from "./types";

const cache = new Map<string, ReputationSummary>();

export function SellerRatingBadge({ sellerId }: { sellerId: string }) {
  const [summary, setSummary] = useState<ReputationSummary | null>(
    () => cache.get(sellerId) ?? null,
  );

  useEffect(() => {
    const cached = cache.get(sellerId);
    if (cached) {
      setSummary(cached);
      return;
    }
    let cancelled = false;
    getPublicProfile(sellerId)
      .then((profile) => {
        cache.set(sellerId, profile.reputation);
        if (!cancelled) setSummary(profile.reputation);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [sellerId]);

  if (!summary) return null;
  return <span title="Seller rating"> · {reputationBadge(summary)}</span>;
}
