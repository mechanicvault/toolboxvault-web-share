import { useT } from "../i18n/LocaleContext";
import { MoonIcon, SunIcon } from "../components/icons";

import { useTheme } from "./ThemeContext";

/**
 * THE HEADER THEME SWITCH — its own component (owner, 2026-11-13):
 * "you need to make the header toggle its own toggle switch. Then
 * all other toggle switches on the entire website need to be
 * calling the same file to display the other toggles. Everything
 * is uniform, everything is the same no matter what page you are
 * on." So the site has exactly TWO switch implementations: this
 * one, used ONLY by the header (HeaderThemeControls), and the
 * shared in-page Toggle (components/Toggle.tsx) that renders
 * every other switch. No other surface may import this file.
 *
 * It renders as .tv-header-switch — its own class, styled beside
 * .tv-switch in the one switch section of theme/components.css,
 * where it owns its wide 4.65rem seat internally (the earlier
 * arrangement borrowed the shared .tv-switch and re-widened it
 * through a .tv-topbar-center container rule; both are gone).
 * It carries the same Ember design as the site switch (owner-
 * settled 2026-11-13: black inset track, molten fill, rim-lit
 * knob, red dash OFF) at the header's own geometry.
 *
 * The flip (owner, 2026-11-13): "the orange shown when the dark
 * theme is enabled." This control's mapping is backwards from
 * every other switch on the site ON PURPOSE: aria-checked is
 * true exactly when the DARK theme is enabled, so the Ember ON
 * read (molten fill, knob right) IS the dark read, and OFF
 * (empty track, red dash) is the light read. ThemeContext is
 * untouched — mode still stores/persists 'dark'/'light' the
 * same way; only this control's checked derivation and click
 * expression invert (a click still just toggles the mode).
 *
 * The track glyphs: moon seated at the left end, sun at the
 * right, under the knob's travel — the knob covers the glyph on
 * its own side, so the exposed end always shows the CURRENT
 * mode's glyph (moon while dark, sun while light), engraved so
 * the state reads at a glance in both modes. The dash follows
 * aria-checked, so it lands in the light seat, behind the sun
 * — the same #c0504d on the same near-black track.
 *
 * The OFF dash is this component's own element
 * (.tv-header-switch-dash): the first header build (when the
 * markup was hand-rolled inside HeaderThemeControls) omitted
 * the dash entirely, so the OFF read shipped without its red —
 * one reason the switch now lives in exactly one file.
 */
export function HeaderThemeSwitch() {
  const t = useT();
  const { mode, setMode } = useTheme();
  const dark = mode === "dark";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      className="tv-header-switch"
      aria-label={t("shell.themeMode")}
      title={t("shell.themeMode")}
      onClick={() => setMode(dark ? "light" : "dark")}
    >
      <span className="tv-header-switch-dash" aria-hidden="true" />
      <span
        className="tv-header-switch-glyph tv-header-switch-glyph--moon"
        aria-hidden="true"
      >
        <MoonIcon size={11} />
      </span>
      <span
        className="tv-header-switch-glyph tv-header-switch-glyph--sun"
        aria-hidden="true"
      >
        <SunIcon size={11} />
      </span>
    </button>
  );
}
