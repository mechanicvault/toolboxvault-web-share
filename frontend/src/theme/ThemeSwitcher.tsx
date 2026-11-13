import { useT } from "../i18n/LocaleContext";
import { THEME_OPTIONS, useTheme, type ThemeMode } from "./ThemeContext";

/** Theme display (Rail Steel conversion): there is ONE current
 *  design — every retired theme resolves to it in ThemeContext —
 *  so this renders a single labeled current-design state and NO
 *  switch buttons. Phase 3 (2026-10-23): Settings → Appearance
 *  presents it as the preview's current-design swatch plate —
 *  "Rail Steel" over a "Current" marker, skinned by the
 *  .tv-theme-current rules in railsteel.css. The Layout and
 *  Header-variant pickers that once lived beside it are NOT
 *  restored: both contexts are pinned/inert under the rail
 *  shell (LayoutContext pins "sidebar", HeaderVariantContext
 *  pins "yoke", and AppShell ignores both values), so a live
 *  picker would offer choices that do nothing. The providers
 *  stay mounted — other code imports their hooks.
 *
 *  Light mode (2026-10-24): the mode half of this file is now
 *  the REAL Light/Dark toggle — ThemeModePlate below. It binds
 *  to ThemeContext's persisted `mode`/`setMode` (localStorage
 *  `tv-mode`); picking a mode re-points the color tokens via
 *  the [data-mode="light"] block in tokens.css, zero component
 *  changes. Mounts in Settings → Appearance and the StyleGuide,
 *  as before. */
export function ThemeSwitcher({ compact = false }: { compact?: boolean }) {
  const { theme } = useTheme();
  const current =
    THEME_OPTIONS.find((o) => o.name === theme) ?? THEME_OPTIONS[0];
  return (
    <div role="group" aria-label="Theme">
      <span className="tv-theme-current" data-compact={compact || undefined}>
        {current.label}
        <em>Current</em>
      </span>
    </div>
  );
}

const MODE_OPTIONS: { value: ThemeMode; labelKey: "settings.appearance.modeDark" | "settings.appearance.modeLight" }[] = [
  { value: "dark", labelKey: "settings.appearance.modeDark" },
  { value: "light", labelKey: "settings.appearance.modeLight" },
];

/** The MODE toggle (light mode, 2026-10-24): Appearance's mode
 *  row, paired with the design plate above. Two toggle buttons
 *  (Dark / Light) riding the existing .tv-accent-swatch pill
 *  pattern — the same labeled-chip treatment the accent picker
 *  uses, with `is-active` + aria-pressed carrying the state —
 *  wired to the persisted mode in ThemeContext. The legacy
 *  optional `label` prop (Appearance used to pass the localized
 *  name of the current mode, back when this was a read-only
 *  plate) is still accepted so that call site compiles
 *  untouched; it is ignored now that both options label
 *  themselves from the dictionary. */
export function ThemeModePlate({
  compact = false,
  label,
}: {
  compact?: boolean;
  /** Legacy: the localized name of the current mode. Accepted
   *  for call-site compatibility; the toggle labels both of its
   *  options from the dictionary instead. */
  label?: string;
}) {
  const t = useT();
  const { mode, setMode } = useTheme();
  void label;
  return (
    <div
      className="tv-accent-swatches"
      role="group"
      aria-label={t("settings.appearance.mode")}
      data-compact={compact || undefined}
    >
      {MODE_OPTIONS.map((o) => {
        const active = mode === o.value;
        return (
          <button
            key={o.value}
            type="button"
            className={`tv-accent-swatch${active ? " is-active" : ""}`}
            aria-pressed={active}
            onClick={() => setMode(o.value)}
          >
            {t(o.labelKey)}
          </button>
        );
      })}
    </div>
  );
}
