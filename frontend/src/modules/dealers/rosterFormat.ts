import { displayDate } from "../inventory/format";
import type { useT } from "../../i18n/LocaleContext";
import type { PreferredAgent, PreferredSummary, RosterEntry } from "./types";

/** Shared words for the roster + the agent record (stage 1,
 *  2026-11-04): tenure and route summaries, spelled the same
 *  way on the list row and on the record itself. `t` is the
 *  locale hook's translate function. */

type T = ReturnType<typeof useT>;

export function freqLabel(t: T, frequency: string | null): string {
  if (frequency === "weekly") return t("dealers.roster.freq.weekly");
  if (frequency === "biweekly") return t("dealers.roster.freq.biweekly");
  if (frequency === "monthly") return t("dealers.roster.freq.monthly");
  return t("dealers.roster.freq.na");
}

export function dayLabel(t: T, day: number | null): string {
  if (day === null || day < 0 || day > 6) return "";
  return t(`dealers.roster.day.${day}` as never);
}

/** The preferred-agent SUMMARY for one company's connection
 *  rows (owner ruling 2026-11-06) — the client half of the
 *  one display resolver; the server half is the dealers
 *  service's preferred_summary_view behind the on-record
 *  endpoint, and the two agree exactly: more than one flagged
 *  → "many" (name nobody); exactly one flagged → "one" with
 *  him; none flagged → the earliest row as "one" (the
 *  standing pre-flag fallback), or "none" when there are no
 *  rows. `entries` must arrive in connection order (the
 *  preferred read's order: created_at, then id). */
export function summarizePreferred(
  entries: PreferredAgent[],
): PreferredSummary {
  const flagged = entries.filter((entry) => entry.is_preferred);
  if (flagged.length >= 2) return { state: "many", agent: null };
  if (flagged.length === 1) return { state: "one", agent: flagged[0] };
  return entries.length > 0
    ? { state: "one", agent: entries[0] }
    : { state: "none", agent: null };
}

/** "Weekly · Wednesday" — or the no-route line. */
export function routeText(t: T, entry: RosterEntry): string {
  if (!entry.route_frequency) return t("dealers.roster.routeNone");
  const day = dayLabel(t, entry.route_day_of_week);
  const freq = freqLabel(t, entry.route_frequency);
  return day ? `${freq} · ${day}` : freq;
}

/** The tenure/status column: "Since Mar 2023", a closed range,
 *  or an em dash when nothing is recorded. */
export function tenureText(t: T, entry: RosterEntry): string {
  if (entry.started_at && entry.ended_at) {
    return t("dealers.roster.tenureRange")
      .replace("{start}", displayDate(entry.started_at))
      .replace("{end}", displayDate(entry.ended_at));
  }
  if (entry.ended_at) {
    return t("dealers.roster.ended").replace(
      "{date}",
      displayDate(entry.ended_at),
    );
  }
  if (entry.started_at) {
    return t("dealers.roster.since").replace(
      "{date}",
      displayDate(entry.started_at),
    );
  }
  return "—";
}
