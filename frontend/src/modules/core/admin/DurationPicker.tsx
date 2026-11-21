import { useEffect, useRef, useState } from "react";

import { Select, TextInput } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";

/**
 * Admin duration picker (owner directive 2026-10-22): wherever
 * an admin hands out free time — promo codes, trials, free
 * periods — the duration is picked in MONTHS, never typed as a
 * day count. Presets run 1–11 months, then "1 year", then
 * "Lifetime" (when the surface allows an open-ended grant),
 * plus a Custom mode taking any number of months.
 *
 * The value is a plain shape the three call sites map onto
 * their APIs: promo codes turn it into a code kind + amount,
 * the user actions turn it into months / lifetime fields.
 *
 * F2-20 honesty: the select carries the caller's `id` (its
 * FormField label points at it); the selection re-syncs when the
 * parent resets the value; and the custom box only commits on
 * blur/Enter — the clamped value is written BACK into the box,
 * so the number on screen is always the number granted.
 */

export interface DurationChoice {
  /** Calendar months. 12 for the "1 year" preset; meaningless
   *  (0) when `lifetime` is true. */
  months: number;
  lifetime: boolean;
  /** True only for the explicit "1 year" preset — promo codes
   *  map it to the free_year kind rather than 12 free months. */
  oneYear: boolean;
}

export const ONE_MONTH: DurationChoice = {
  months: 1,
  lifetime: false,
  oneYear: false,
};

export const CUSTOM_MAX_MONTHS = 120;

const MONTH_PRESETS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

type Selection = string; // "1".."11" | "year" | "lifetime" | "custom"

function selectionFor(value: DurationChoice): Selection {
  if (value.lifetime) return "lifetime";
  if (value.oneYear) return "year";
  if (MONTH_PRESETS.includes(value.months)) return String(value.months);
  return "custom";
}

function sameChoice(a: DurationChoice, b: DurationChoice): boolean {
  return a.months === b.months && a.lifetime === b.lifetime && a.oneYear === b.oneYear;
}

export function DurationPicker({
  value,
  onChange,
  allowLifetime = true,
  id,
}: {
  value: DurationChoice;
  onChange: (choice: DurationChoice) => void;
  allowLifetime?: boolean;
  /** Id for the select — the caller's FormField htmlFor targets it. */
  id?: string;
}) {
  const tt = useT();
  const [selection, setSelection] = useState<Selection>(() => selectionFor(value));
  const [custom, setCustom] = useState<string>(() =>
    selectionFor(value) === "custom" ? String(value.months || 12) : "12",
  );
  const lastEmitted = useRef<DurationChoice>(value);

  function emit(choice: DurationChoice) {
    lastEmitted.current = choice;
    onChange(choice);
  }

  /* Re-sync when the PARENT changes the value (e.g. Promos
   * switching code type resets the duration): our own emissions
   * are recognised via lastEmitted and never fight the user. */
  useEffect(() => {
    if (sameChoice(value, lastEmitted.current)) return;
    lastEmitted.current = value;
    const next = selectionFor(value);
    setSelection(next);
    if (next === "custom") setCustom(String(value.months || 12));
  }, [value]);

  function pick(next: Selection) {
    setSelection(next);
    if (next === "lifetime") {
      emit({ months: 0, lifetime: true, oneYear: false });
    } else if (next === "year") {
      emit({ months: 12, lifetime: false, oneYear: true });
    } else if (next === "custom") {
      const months = Math.min(
        CUSTOM_MAX_MONTHS,
        Math.max(1, Number(custom) || 1),
      );
      setCustom(String(months));
      emit({ months, lifetime: false, oneYear: false });
    } else {
      emit({ months: Number(next), lifetime: false, oneYear: false });
    }
  }

  /* Custom months commit on blur/Enter ONLY: while typing, the
   * box may hold a partial or out-of-range string, but nothing is
   * granted from it; on commit the value is clamped to 1..120 and
   * the clamped number is written back into the box. */
  function commitCustom() {
    const months = Math.min(
      CUSTOM_MAX_MONTHS,
      Math.max(1, Math.floor(Number(custom) || 1)),
    );
    setCustom(String(months));
    emit({ months, lifetime: false, oneYear: false });
  }

  return (
    <span style={{ display: "inline-flex", gap: "var(--space-2)", alignItems: "end", flexWrap: "wrap" }}>
      <Select id={id} aria-label="Duration" value={selection} onChange={(e) => pick(e.target.value)}>
        {MONTH_PRESETS.map((n) => (
          <option key={n} value={String(n)}>
            {n} {n === 1 ? "month" : "months"}
          </option>
        ))}
        <option value="year">1 year</option>
        {allowLifetime && <option value="lifetime">Lifetime</option>}
        <option value="custom">Custom…</option>
      </Select>
      {selection === "custom" && (
        <span style={{ display: "inline-flex", gap: "var(--space-1)", alignItems: "center", flexWrap: "wrap" }}>
          <TextInput
            type="number"
            min={1}
            max={CUSTOM_MAX_MONTHS}
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            onBlur={commitCustom}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitCustom(); } }}
            style={{ width: "5.5rem" }}
            aria-label="Custom months"
          />
          <span style={{ color: "var(--text-muted)" }}>months</span>
          <span style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)", flexBasis: "100%" }}>
            {tt("admin.duration.customNote")}
          </span>
        </span>
      )}
    </span>
  );
}
