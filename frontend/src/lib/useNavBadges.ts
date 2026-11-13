import { useEffect, useState } from "react";

import { api } from "./api";

/**
 * NEW badges (release machinery, owner rule 2026-11-08): a new
 * feature's menu item carries a NEW badge for its FIRST WEEK.
 *
 * The registry lives server-side (GET /core/nav-badges — a
 * system-settings map of nav item key -> release date,
 * "YYYY-MM-DD", edited in Admin → Settings). Freshness is
 * computed HERE, at render: a badge shows while today is the
 * release date or any of the 6 days after it; on day 8 it
 * simply never renders — no cron, no manual removal, and a
 * stale registry entry is inert. Date math is date-only (UTC
 * midnights) so timezones can't stretch or shrink the week.
 *
 * A failed fetch badges nothing: the nav must never invent a
 * NEW, and a missing badge is a quieter failure than a wrong
 * one.
 */

const DAY_MS = 86_400_000;

function dayNumber(iso: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(ms) ? null : Math.floor(ms / DAY_MS);
}

function todayNumber(): number {
  const now = new Date();
  return Math.floor(
    Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / DAY_MS,
  );
}

export function isWithinFirstWeek(releaseIso: string, today = todayNumber()): boolean {
  const released = dayNumber(releaseIso);
  if (released === null) return false;
  const age = today - released;
  return age >= 0 && age < 7;
}

export function useNavBadges(enabled: boolean): ReadonlySet<string> {
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    if (!enabled) {
      setFresh(new Set());
      return;
    }
    let live = true;
    api<Record<string, string>>("/core/nav-badges")
      .then((registry) => {
        if (!live) return;
        const today = todayNumber();
        setFresh(
          new Set(
            Object.entries(registry)
              .filter(([, date]) => isWithinFirstWeek(date, today))
              .map(([key]) => key),
          ),
        );
      })
      .catch(() => {
        if (live) setFresh(new Set());
      });
    return () => {
      live = false;
    };
  }, [enabled]);

  return fresh;
}
