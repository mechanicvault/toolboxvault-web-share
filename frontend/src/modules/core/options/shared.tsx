import { type ReactNode } from "react";


/**
 * WIDGET OPTIONS REGISTRY (widget options program, owner design
 * 2026-11-02): the per-widget option sections that appear in a
 * Home block's Edit-view options popover, keyed by BLOCK key
 * ("widget:maintenance", "notifications", "overview", ...). The
 * popover itself (components/PageBlocks) owns the universal
 * section — the Half | Full width choice every block carries;
 * a widget with something of its own to choose registers a
 * section here and the popover renders it under the width
 * choice, live-editing the same Edit-view draft (Save keeps
 * the changes, Cancel throws them away).
 *
 * Wave 1 shipped this registry EMPTY on purpose: the framework
 * (per-block size, the popover, the settings plumbing through
 * the layout store) landed first, proven end to end. Wave 2
 * registers the owner's named four — Inventory, Borrowing,
 * Claims, Truck accounts — and Waves 3–4 plug the rest in the
 * same way, without touching the popover, the layout hook, or
 * the store.
 *
 * SETTINGS DISCIPLINE: a widget's options are flat leaves in
 * the block's settings bundle (the layout store's sanitizer
 * bounds them server-side). Absence is the unset state, so a
 * control writes `undefined` when the user picks the default —
 * a saved bundle only ever carries real choices. The loaders
 * in homeWidgets read through the same two helpers below with
 * the same defaults, so the popover and the widget can never
 * disagree about what an absent key means.
 */
import { Checkbox } from "../../../components";
import type {
  BlockSettingValue,
  ResolvedBlock,
} from "../../../lib/usePageLayout";

export interface WidgetOptionsApi {
  /** The block being edited (its draft state: size + settings). */
  block: ResolvedBlock;
  /** Write one option into the block's draft settings bundle;
   *  undefined removes the key — absence is the unset state. */
  setSetting: (name: string, value: BlockSettingValue | undefined) => void;
}

export interface WidgetOptionsDef {
  render: (api: WidgetOptionsApi) => ReactNode;
}

/** A boolean option read through the store's unset rule:
 *  a stored boolean wins; anything else means the default. */
export function optBool(
  settings: Record<string, BlockSettingValue>,
  name: string,
  dflt: boolean,
): boolean {
  const v = settings[name];
  return typeof v === "boolean" ? v : dflt;
}

/** A numeric option, clamped to its control's range: a stored
 *  number wins inside [min, max]; anything else is the default. */
export function optNum(
  settings: Record<string, BlockSettingValue>,
  name: string,
  dflt: number,
  min: number,
  max: number,
): number {
  const v = settings[name];
  if (typeof v !== "number" || !Number.isFinite(v)) return dflt;
  return Math.min(max, Math.max(min, Math.round(v)));
}

/** One labeled group inside a widget's popover section — the
 *  same plate language as the popover's own width group. */
export function OptionsGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="tv-block-opts-group">
      <span className="tv-block-opts-label">{label}</span>
      {children}
    </div>
  );
}

/** A checkbox row in a widget's section. Picking the default
 *  clears the key (absence = unset), like every store field. */
export function CheckRow({
  label,
  settings,
  name,
  dflt,
  setSetting,
}: {
  label: string;
  settings: Record<string, BlockSettingValue>;
  name: string;
  dflt: boolean;
  setSetting: WidgetOptionsApi["setSetting"];
}) {
  const checked = optBool(settings, name, dflt);
  return (
    <Checkbox
      label={label}
      checked={checked}
      onChange={(e) =>
        setSetting(name, e.target.checked === dflt ? undefined : e.target.checked)
      }
    />
  );
}

/** A small segmented count choice (the width choice's own
 *  machined track): the numbers this option may take. Picking
 *  the default clears the key, like CheckRow. */
export function CountRow({
  label,
  settings,
  name,
  dflt,
  min,
  max,
  setSetting,
}: {
  label: string;
  settings: Record<string, BlockSettingValue>;
  name: string;
  dflt: number;
  min: number;
  max: number;
  setSetting: WidgetOptionsApi["setSetting"];
}) {
  const value = optNum(settings, name, dflt, min, max);
  const choices: number[] = [];
  for (let n = min; n <= max; n += 1) choices.push(n);
  return (
    <OptionsGroup label={label}>
      <div className="tv-opts-size" role="group" aria-label={label}>
        {choices.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            onClick={() => setSetting(name, n === dflt ? undefined : n)}
          >
            {n}
          </button>
        ))}
      </div>
    </OptionsGroup>
  );
}

/** A segmented choice over an explicit set of numbers (Wave 4
 *  batch A): the Notifications rows cap takes 3 / 5 / 8 — not a
 *  contiguous range — so CountRow's min..max sweep can't speak
 *  for it. Same machined track, same unset rule: picking the
 *  default clears the key. */
export function ChoicesRow({
  label,
  settings,
  name,
  dflt,
  choices,
  setSetting,
}: {
  label: string;
  settings: Record<string, BlockSettingValue>;
  name: string;
  dflt: number;
  choices: number[];
  setSetting: WidgetOptionsApi["setSetting"];
}) {
  const raw = settings[name];
  const value =
    typeof raw === "number" && choices.includes(raw) ? raw : dflt;
  return (
    <OptionsGroup label={label}>
      <div className="tv-opts-size" role="group" aria-label={label}>
        {choices.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            onClick={() => setSetting(name, n === dflt ? undefined : n)}
          >
            {n}
          </button>
        ))}
      </div>
    </OptionsGroup>
  );
}

/** Inventory (Wave 2): the Add Item button, the three lines,
 *  and how many recently added items ride along. Defaults are
 *  today's widget exactly: lines on, no button, latest only. */
