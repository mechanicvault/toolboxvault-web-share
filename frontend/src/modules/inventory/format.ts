import { formatDate } from "../../lib/format";
import { formatMoney } from "../../lib/money";

/** Format a decimal-as-string from the API in the VIEWER's
 * currency (wave 3: the one formatter, lib/money — an account's
 * amounts are in its own currency). Null/blank → em dash. */
export function money(value: string | null | undefined): string {
  return formatMoney(value);
}

/** Format a YYYY-MM-DD date string for display. A full ISO
 * timestamp (the history timeline's event stamps carry one)
 * renders readably instead of the raw string, microseconds and
 * all (wave-review round, 2026-10-20): a stamp at exactly
 * midnight UTC is a day-granular fact (purchase / sale / loss
 * dates are stored that way), so it renders as that date in
 * UTC — a local rendering would shift it to the previous
 * evening for US users; any other stamp is a real instant and
 * renders as a local date + time. */
export function displayDate(value: string | null | undefined): string {
  if (!value) return "—";
  if (value.includes("T")) {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    const midnightUtc =
      d.getUTCHours() === 0 &&
      d.getUTCMinutes() === 0 &&
      d.getUTCSeconds() === 0 &&
      d.getUTCMilliseconds() === 0;
    if (midnightUtc) {
      // Day-granular fact: render the UTC calendar date in the
      // shared standard format (Round G) rather than numeric.
      return formatDate(d.toISOString().slice(0, 10));
    }
    return d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  }
  return formatDate(value) === "—" ? value : formatDate(value);
}

/** Human-readable rendering of a custom field value by type. */
export function customValueText(value: unknown, fieldType: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (fieldType === "boolean") return value === true ? "Yes" : "No";
  if (fieldType === "date" && typeof value === "string") return displayDate(value);
  return String(value);
}
