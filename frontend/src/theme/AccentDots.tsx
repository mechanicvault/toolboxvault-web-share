import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useT } from "../i18n/LocaleContext";
import { PushPinIcon } from "../components/icons";

import { useTheme } from "./ThemeContext";

/**
 * THE accent set (owner review round 1, 2026-10-19): the color
 * wheel is retired — the owner picked seven fixed colors and
 * wanted them as small glowing circles in the header, one click
 * to change. Red / blue / orange / pink keep their long-standing
 * values; green is a TRUE green (the old lime preset is superseded
 * as "the green"); yellow is new; grey is the silver family.
 *
 * THE GEAR ERA (2026-10-19 20:28, supersedes every CSS dot
 * round AND the same-evening badge set, which never shipped):
 * the owner supplied the actual artwork — seven glossy metallic
 * GEARS, one per accent color ("lets use these gears instead,
 * they fit the theme of the website better") — and directed
 * that the picker render THEM. So the swatches are IMAGES now
 * (public/accents/gear-<id>.png), the account avatar wears the
 * gear of the user's current accent (AccentGearAvatar, below —
 * the Package A SVG gear is retired), and the CSS dot-painting
 * of rounds 1–3 is retired wholesale: exactly one swatch
 * implementation exists, this component + the owner's PNGs.
 * `value` remains the accent the site re-tints with — plates,
 * glows and text accents still run on the color values; only
 * the picker + avatar render art.
 *
 * A stored accent from the wheel era (a custom hex, the retired
 * lime) simply matches no badge — nothing is marked active until
 * the user clicks one, which is honest: the badges are the whole
 * picker now. Every pick rides the same setAccent store path as
 * before, so persistence and the derived soft/strong/glow
 * variants are unchanged. Values live here in the theme layer
 * on purpose.
 */
export const ACCENT_DOTS: {
  id: string;
  label: string;
  value: string;
  /** The owner-supplied gear artwork for this accent
   * (public/accents/, 256×256 transparent PNG): a glossy
   * metallic gear in the accent color. The picker renders the
   * ART, not a CSS drawing, and the account avatar wears the
   * gear of the user's current accent. */
  gear: string;
}[] = [
  { id: "red", label: "Red", value: "#ff0000", gear: "/brand/gear-red.webp" },
  { id: "blue", label: "Blue", value: "#2f6bff", gear: "/brand/gear-blue.webp" },
  { id: "green", label: "Green", value: "#1ea946", gear: "/brand/gear-green.webp" },
  { id: "pink", label: "Pink", value: "#f0568b", gear: "/brand/gear-pink.webp" },
  { id: "yellow", label: "Yellow", value: "#f5b301", gear: "/brand/gear-yellow.webp" },
  { id: "grey", label: "Grey", value: "#c7ccd4", gear: "/brand/gear-grey.webp" },
  { id: "orange", label: "Orange", value: "#f2760a", gear: "/brand/gear-orange.webp" },
];

/**
 * THE HIDDEN CHOOSER (owner, 2026-10-19 20:45): the always-visible
 * header gear row is RETIRED. The gear next to the user's name —
 * which already wears the chosen color's gear — IS the picker:
 * click it and the seven gears drop down; pick one and the accent
 * applies at once, the dropdown closes, and the gear by the name
 * now shows the new color. "A hidden chooser."
 *
 * The control renders signed out too (in the Log in / Sign up
 * cluster): the accent is a local preference, not account data,
 * and a lone gear button is a control, not a picker row — the
 * picker itself stays hidden until asked for, in both states.
 *
 * Menu behavior follows the shell's account-menu pattern:
 * click-outside closes, Esc closes and returns focus to the
 * gear; opening moves focus to the current color; ↑/↓ walk the
 * list, Home/End jump. A pick rides the same setAccent store
 * path as every other accent surface, so persistence and the
 * derived soft/strong/glow variants are unchanged.
 *
 * SITE SETTINGS TREE (owner directive 2026-11-01): the settings
 * dropdown hangs off THIS gear. The popup's resting state is
 * the appearance controls exactly as they were, plus ONE row —
 * "Site settings" — under them. That row is a disclosure only
 * (menu-behavior rule: it never navigates); tapping it expands
 * the link tree in place inside the popup, tapping again
 * collapses it, and each leaf links to its settings page. The
 * leaves arrive as a prop: the app builds them from the SAME
 * settings registry (settingsMeta) the settings pages read, so
 * the tree can never drift from the sections that exist, and
 * the registry's own group gating decides what a seat sees.
 * Signed out there are no links, so the row never renders.
 *
 * RAIL PIN ROW (owner, 2026-11-05): the rail pin toggle moved
 * out of the rail into THIS popup — "move the button to pin
 * the left menu to the gear drop down setting menu. It should
 * rest right above the settings line." It renders only when
 * the app supplies the toggle (a signed-in session; signed out
 * there is no rail to pin), as a menuitemcheckbox directly
 * above the Site settings row, wearing the retired rail
 * button's own strings (pinLabel / pinLabelPinned visible,
 * pinKeep / pinRelease as its action name) and its state at a
 * glance (the pinned glyph fills with the accent — surfaces.css).
 * A click flips the same account rail_pinned the floating
 * button wrote, through the same PATCH path the app owns; the
 * popup STAYS OPEN (like the mode picks) and the rail answers
 * live behind it. On phone widths CSS hides the row (the rail
 * is a top strip there and pinning does nothing — the same
 * honesty the floating pin followed), and the key walk below
 * skips hidden rows so it never eats an arrow press.
 */
export interface GearSiteSettingsLink {
  label: string;
  path: string;
}

export function AccentGearChooser({
  siteSettingsLinks = [],
  railPinned,
  onToggleRailPin,
}: {
  siteSettingsLinks?: GearSiteSettingsLink[];
  /** Rail pin (owner, 2026-11-05): the account's held-open
   * choice and its toggle, forwarded by the shell. The row
   * renders only when a toggle is supplied. */
  railPinned?: boolean;
  onToggleRailPin?: () => void;
}) {
  const t = useT();
  const { accent, setAccent, mode, setMode } = useTheme();
  const [open, setOpen] = useState(false);
  const [treeOpen, setTreeOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const current = ACCENT_DOTS.find((d) => d.value === accent.toLowerCase());

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    // Focus the current color (or the first gear) so the menu is
    // keyboard-live the moment it drops.
    const items = menuRef.current?.querySelectorAll<HTMLButtonElement>(
      '[role="menuitemradio"]',
    );
    if (items && items.length > 0) {
      const idx = ACCENT_DOTS.findIndex((d) => d.value === accent.toLowerCase());
      items[Math.max(0, idx)]?.focus();
    }
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, accent]);

  function pick(value: string) {
    setAccent(value);
    setOpen(false);
    btnRef.current?.focus();
  }

  /** Mode picks apply at once but KEEP the popup open (unlike
   *  accent picks, which close it): accent + mode can be set in
   *  one visit. Focus stays on the picked row — the menu's
   *  ↑/↓/Home/End walk already covers every menuitemradio, so
   *  the mode rows are keyboard-reachable from the accent list. */
  function pickMode(value: "dark" | "light") {
    setMode(value);
  }

  /* The settings tree always starts collapsed when the popup
   * reopens — the resting state is appearance + the one row. */
  useEffect(() => {
    if (!open) setTreeOpen(false);
  }, [open ]);

  function onMenuKey(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") {
      return;
    }
    // The walk covers every row in the popup — the appearance
    // radios AND, when present, the pin row, the Site settings
    // disclosure row and its expanded leaves. Hidden rows (the
    // pin row on phone widths) are skipped: a display:none row
    // has no client rects, and focusing one would swallow the
    // press with nothing to show for it.
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>(
        '[role="menuitemradio"], [role="menuitemcheckbox"], [role="menuitem"]',
      ) ?? [],
    ).filter((el) => el.getClientRects().length > 0);
    if (items.length === 0) return;
    e.preventDefault();
    const idx = items.indexOf(document.activeElement as HTMLElement);
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? items.length - 1
          : e.key === "ArrowDown"
            ? (idx + 1) % items.length
            : (idx - 1 + items.length) % items.length;
    items[next]?.focus();
  }

  return (
    <div className="tv-gear-chooser" ref={ref}>
      <button
        ref={btnRef}
        type="button"
        className="tv-gear-chooser-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={
          current
            ? `Accent color: ${current.label}. Change accent color`
            : "Change accent color"
        }
        title="Accent color"
        onClick={() => setOpen((v) => !v)}
      >
        <AccentGearAvatar />
      </button>
      {open && (
        <div
          className="tv-menu tv-gear-menu"
          role="menu"
          aria-label="Accent color"
          ref={menuRef}
          onKeyDown={onMenuKey}
        >
          <div className="tv-gear-menu-title" aria-hidden="true">
            Accent color
          </div>
          {ACCENT_DOTS.map((d) => {
            const active = accent.toLowerCase() === d.value;
            return (
              <button
                key={d.id}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                className={`tv-menu-item tv-gear-item${active ? " is-current" : ""}`}
                onClick={() => pick(d.value)}
              >
                <img src={d.gear} alt="" width={22} height={22} draggable={false} aria-hidden="true" />
                <span>{t(`color.${d.id}` as never)}</span>
                {active && (
                  <span className="tv-gear-current" aria-hidden="true">
                    Current
                  </span>
                )}
              </button>
            );
          })}
          <div className="tv-gear-menu-title" aria-hidden="true">
            {t("settings.appearance.mode")}
          </div>
          {(
            [
              { value: "dark", labelKey: "settings.appearance.modeDark" },
              { value: "light", labelKey: "settings.appearance.modeLight" },
            ] as const
          ).map((o) => {
            const active = mode === o.value;
            return (
              <button
                key={o.value}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                className={`tv-menu-item tv-gear-item${active ? " is-current" : ""}`}
                onClick={() => pickMode(o.value)}
              >
                <span>{t(o.labelKey)}</span>
                {active && (
                  <span className="tv-gear-current" aria-hidden="true">
                    Current
                  </span>
                )}
              </button>
            );
          })}
          {onToggleRailPin && (
            <button
              type="button"
              role="menuitemcheckbox"
              aria-checked={!!railPinned}
              className="tv-menu-item tv-gear-item tv-gear-pinrow"
              aria-label={railPinned ? t("shell.pinRelease") : t("shell.pinKeep")}
              title={railPinned ? t("shell.pinRelease") : t("shell.pinKeep")}
              onClick={onToggleRailPin}
            >
              <span className="tv-gear-pin-ico" aria-hidden="true">
                <PushPinIcon size={20} />
              </span>
              <span>
                {railPinned ? t("shell.pinLabelPinned") : t("shell.pinLabel")}
              </span>
            </button>
          )}
          {siteSettingsLinks.length > 0 && (
            <button
              type="button"
              role="menuitem"
              aria-expanded={treeOpen}
              className="tv-menu-item tv-gear-tree-toggle"
              onClick={() => setTreeOpen((v) => !v)}
            >
              <span>{t("shell.siteSettings")}</span>
              <span className="tv-gear-tree-caret" aria-hidden="true">
                {treeOpen ? "▾" : "▸"}
              </span>
            </button>
          )}
          {treeOpen &&
            siteSettingsLinks.map((l) => (
              <Link
                key={l.path}
                to={l.path}
                role="menuitem"
                className="tv-menu-item tv-gear-tree-leaf"
                onClick={() => setOpen(false)}
              >
                {l.label}
              </Link>
            ))}
        </div>
      )}
    </div>
  );
}

/**
 * The account button's mark: the gear artwork in the user's
 * CURRENT accent color (owner, 2026-10-19 20:28 — the gears "fit
 * the theme of the website better" than the Package A SVG gear,
 * which this retires). It follows setAccent live like everything
 * else in the accent system. An accent matching no preset (a
 * custom hex from the wheel era) falls back to the orange gear —
 * the brand's heritage color. Decorative: the button carries
 * the user's name as visible text beside it.
 */
export function AccentGearAvatar({ size = 28 }: { size?: number }) {
  const { accent } = useTheme();
  const match =
    ACCENT_DOTS.find((d) => d.value === accent.toLowerCase()) ??
    ACCENT_DOTS.find((d) => d.id === "orange")!;
  return (
    <img
      className="tv-accent-gear"
      src={match.gear}
      alt=""
      width={size}
      height={size}
      draggable={false}
      aria-hidden="true"
    />
  );
}

/**
 * The Settings → Appearance version of the same set: labeled
 * chips carrying the same gear artwork (and the Style Guide
 * renders these too) so the choice is unmistakable on the pages
 * where appearance lives.
 */
export function AccentSwatches() {
  const t = useT();
  const { accent, setAccent } = useTheme();
  return (
    <div className="tv-accent-swatches" role="group" aria-label="Accent color">
      {ACCENT_DOTS.map((d) => {
        const active = accent.toLowerCase() === d.value;
        return (
          <button
            key={d.id}
            type="button"
            className={`tv-accent-swatch${active ? " is-active" : ""}`}
            aria-pressed={active}
            onClick={() => setAccent(d.value)}
          >
            <img
              className="tv-accent-swatch-dot"
              src={d.gear}
              alt=""
              draggable={false}
              aria-hidden="true"
            />
            {t(`color.${d.id}` as never)}
          </button>
        );
      })}
    </div>
  );
}
