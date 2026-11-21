import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n/LocaleContext";
import { ChevronDownIcon } from "../components/icons";

import { ACCENT_DOTS } from "./AccentDots";
import { HeaderThemeSwitch } from "./HeaderThemeSwitch";
import { useTheme } from "./ThemeContext";

/**
 * THE HEADER THEME CLUSTER (owner, 2026-11-12 21:49): "Place a
 * toggle switch on the top header, centered on the page — this
 * toggle will toggle from light to dark. Next to that toggle
 * switch, have a small button with an arrow pointing downward;
 * that button will bring up the color pickers for the theme
 * layout. Then take all of those options out of the gear icon."
 *
 * The cluster seats INSIDE the header bar at its true center
 * (.tv-topbar-center, railsteel-home.css): the word "Theme"
 * (shell.theme), the theme switch, and a chevron disclosure
 * that drops the accent picker the gear used to carry.
 *
 * THE SWITCH IS ITS OWN COMPONENT (owner, 2026-11-13):
 * HeaderThemeSwitch.tsx — the header toggle and nothing else
 * uses it, exactly as every in-page switch renders through
 * components/Toggle.tsx and nothing else. It owns its wide
 * seat, glyphs, OFF dash and flipped mapping (checked = dark)
 * internally; its full history (the Ember settlement, the
 * flip, the missing-dash first build) lives in that file.
 * This file keeps only the cluster around it: the label (the
 * cluster NAMES itself — owner, 2026-11-13: a control the user
 * cannot identify is a control they never find), the chevron
 * (resting in the bar's full ink, not the muted hbtn ink that
 * washed out in both themes), and the popover.
 *
 * The popover follows the gear menu's discipline (the shell's
 * menu pattern): click-outside closes, Esc closes and returns
 * focus to the chevron, opening focuses the current color,
 * ↑/↓/Home/End walk the rows, and a pick applies at once,
 * closes, and returns focus to the chevron. It is a disclosure
 * only — it never navigates.
 *
 * The cluster renders in BOTH header bars the shell ships (the
 * signed-in bar and the signed-out strip): appearance is a
 * local preference, not account data — the same reason the old
 * gear chooser rendered signed out.
 */
export function HeaderThemeControls() {
  const t = useT();
  const { accent, setAccent } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

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
    // keyboard-live the moment it drops — the gear menu's pattern.
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

  function onMenuKey(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") {
      return;
    }
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [],
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
    <div className="tv-topbar-center" ref={ref}>
      <span className="tv-theme-label" aria-hidden="true">
        {t("shell.theme")}
      </span>
      <HeaderThemeSwitch />
      <button
        ref={btnRef}
        type="button"
        className="tv-hbtn tv-theme-chevron"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("shell.themeColors")}
        title={t("shell.themeColors")}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDownIcon size={17} />
      </button>
      {open && (
        <div
          className="tv-menu tv-theme-menu"
          role="menu"
          aria-label={t("settings.appearance.accent")}
          ref={menuRef}
          onKeyDown={onMenuKey}
        >
          <div className="tv-gear-menu-title" aria-hidden="true">
            {t("settings.appearance.accent")}
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
                    {t("shell.current")}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
