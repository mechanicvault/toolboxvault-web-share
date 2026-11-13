/**
 * THE user-facing date + plural helpers (Deep audit Round G,
 * F5-20 / F5-22 / F5-28).
 *
 * DATE STANDARD: one format everywhere a user reads a date —
 * "Oct 30, 2026" (medium: short month, day, year), rendered with
 * Intl in the ACTIVE interface locale (documentElement.lang,
 * which LocaleContext keeps in step with the account's locale),
 * so Spanish renders "30 oct 2026" from the same call. Short
 * chip form drops the year: "Oct 30". Numeric M/D/YYYY survives
 * only inside date INPUTS and admin timestamps. Never hardcode
 * a locale string in a formatter again.
 */

export function activeLocale(): string | undefined {
  if (typeof document !== "undefined" && document.documentElement.lang) {
    return document.documentElement.lang;
  }
  return undefined;
}

/** Today's date as a "YYYY-MM-DD" string in the VIEWER's local
 * calendar (date-pickers site-wide, 2026-11-04). Local components,
 * deliberately NOT `toISOString().slice(0, 10)`: the UTC date is
 * already tomorrow for a US-evening user, and a "defaults to
 * today" field must show the date on the user's own calendar.
 * THE today-default source for every date entry in the system. */
export function todayLocalIso(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** "Oct 30, 2026" in the active locale; "—" when absent/invalid. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(activeLocale(), {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
}

/** "Oct 30" — the chip/short form of the same standard. */
export function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(activeLocale(), { month: "short", day: "numeric" });
}

/** "Oct 30, 2026, 2:41 PM" in the active locale. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString(activeLocale(), {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

/** "1 item" / "3 items" — the one plural helper (F5-22). */
export function plural(n: number, singular: string, pluralForm?: string): string {
  return `${n} ${n === 1 ? singular : (pluralForm ?? `${singular}s`)}`;
}

