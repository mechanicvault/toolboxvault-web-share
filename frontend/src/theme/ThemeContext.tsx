import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api, TOKEN_KEY } from "../lib/api";

import "./tokens.css";
import "./themes/railsteel.css";
import "./base.css";
import "./components.css";
import "./widget-kit.css";
import "./surfaces.css";
import "./vaultpanel.css";
import "./header-variants.css";

/** Rail Steel conversion (Phase 1, 2026-10-23): ONE shipping theme.
 *  The Layout 2 — Steel preview Ryan picked becomes the whole design:
 *  tokens.css :root carries its values and themes/railsteel.css its
 *  scoped treatments. Every earlier theme (generic, dark, steel and
 *  all steel* variants, steellight) is RETIRED — its CSS file stays
 *  on disk unimported and unedited. */
export type ThemeName = "railsteel";

/**
 * MODE — the light/dark seam (owner steer, 2026-10-24). The end
 * state is ONE design (Rail Steel) with TWO user controls in the
 * color-gear popup: accent and a light/dark MODE — light being
 * this same design wearing the ONE light palette (Silver Grey;
 * see THE LIGHT PALETTE note below and tokens.css).
 *
 *  - Mode is a PALETTE dimension, not a second theme: it rides
 *    beside `theme` in this context, and the provider stamps it
 *    as `data-mode` on <html> next to `data-theme`, so every
 *    [data-theme="railsteel"] treatment keeps matching in both
 *    modes and only COLOR TOKENS change values.
 *  - The light palette is a token-override block in tokens.css
 *    keyed on [data-mode="light"] — overriding color tokens
 *    only, touching zero component rules (Phase 3's token sweep
 *    made the treatments literal-free; see the conversion
 *    INDEX, "Light-mode seam").
 *  - `mode` is persisted state (localStorage `tv-mode`, the
 *    tv-theme pattern) with a setter, exposed so the Appearance
 *    mode plate (ThemeSwitcher.tsx) and the gear popup bind to
 *    the real hook instead of hardcoding an answer. Anything in
 *    storage that is not "light"/"dark" resolves to CURRENT_MODE.
 *    Since 2026-10-25 the localStorage copy is only the
 *    pre-login cache: signed-in changes ALSO save mode + accent
 *    + theme to the account (PATCH /core/me appearance fields),
 *    and at sign-in the account's saved values are applied over
 *    the local ones via hydrateFromAccount (see AuthProvider) —
 *    the account, not the browser, is the source of truth.
 *    Since 2026-11-08 the accent half is PER-MODE (see
 *    PER-MODE ACCENT at the defaults below): each mode keeps
 *    its own pick, and light's default is silver.
 */
export type ThemeMode = "dark" | "light";

/** The only palette that exists today. */
export const CURRENT_MODE: ThemeMode = "dark";

/**
 * THE LIGHT PALETTE (owner pick, 2026-10-24): exactly one —
 * "Silver Grey", the winner of the Phase D live previews (the
 * other preview looks and the picker are removed). It needs no
 * state here at all: it is simply what the [data-mode="light"]
 * token block in tokens.css declares. The retired preview
 * dimension (localStorage `tv-light-variant` +
 * `data-light-variant` on <html>) is GONE — a stale stored
 * value is never read, and the provider clears the key on
 * mount, so any browser that flipped through the previews
 * lands on plain Silver Grey light with nothing to resolve.
 */
interface ThemeContextValue {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
  /** The current light/dark mode (see the seam note above). */
  mode: ThemeMode;
  setMode: (m: ThemeMode) => void;
  /** The EFFECTIVE accent for the current mode (see PER-MODE
   *  ACCENT below): the mode's own pick, or that mode's default
   *  when the mode has no pick yet. Any CSS color. Re-tints
   *  --accent (+ soft/strong/glow) across the site. */
  accent: string;
  /** Picks a color for the CURRENT mode only — the other
   *  mode's pick (or default) is untouched. */
  setAccent: (c: string) => void;
  /** The dark mode's stored pick (always a value: the orange
   *  default fills the empty slot). Exposed so AuthContext's
   *  adoption can save the full per-mode state faithfully. */
  accentDark: string;
  /** The light mode's stored pick, or null when light has no
   *  pick yet (the silver default is showing, un-picked). */
  accentLight: string | null;
  /** Account hydration (owner ruling, 2026-10-25 — appearance
   *  lives with the ACCOUNT, not the browser): AuthContext calls
   *  this once per sign-in with the /me appearance values. When
   *  the account has anything saved, the saved values are
   *  applied over this browser's local ones (state + the local
   *  mirror, so the next boot paints them immediately) and are
   *  NOT saved back. A fully-empty account value is a no-op —
   *  AuthContext adopts the current look into the account
   *  instead (see AuthProvider). */
  hydrateFromAccount: (a: {
    mode: string | null;
    accent: string | null;
    accentLight: string | null;
    theme: string | null;
  }) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const THEMES: ThemeName[] = ["railsteel"];

/** Menu order + labels: the single current design. Consumers map
 *  this list to offer theme choices — with one entry, no surface
 *  can offer a retired theme. */
export const THEME_OPTIONS: { name: ThemeName; label: string }[] = [
  { name: "railsteel", label: "Rail Steel" },
];

/** Saved-preference migration (Rail Steel conversion): EVERY saved
 *  value — generic, dark, steel, steellight, any retired steel* id,
 *  or garbage — resolves to "railsteel", and the provider persists
 *  the resolved id over the stored one (the existing pattern). */
function resolveSavedTheme(saved: string | null): ThemeName {
  if (saved !== null && (THEMES as string[]).includes(saved)) {
    return saved as ThemeName;
  }
  return "railsteel";
}
/** The default accent is ORANGE — the owner's ruling (2026-10-19):
 *  the gear that shows is the chosen color's gear, and the default
 *  is orange. This is the orange preset's EXACT value (see
 *  ACCENT_DOTS in AccentDots.tsx), not the nearby heritage orange
 *  #e8641c it replaces: a fresh visitor with nothing stored must
 *  land ON the orange preset, so the account gear renders the
 *  orange gear and the chooser marks Orange current. A stored
 *  choice always wins — this only fills the empty slot. */
const DEFAULT_ACCENT = "#f2760a";

/** PER-MODE ACCENT (owner order, 2026-11-08): "The default
 *  color for the light theme should be silver when choosing
 *  the light theme." Each mode remembers its OWN accent: the
 *  dark pick lives in the original store (localStorage
 *  `tv-accent`, account `appearance_accent` — every value saved
 *  before this split is a dark-side value), and the light pick
 *  in its sibling (`tv-accent-light`, account
 *  `appearance_accent_light`). The light slot starts EMPTY:
 *  light with no pick shows the LIGHT default — silver, the
 *  palette's grey preset value EXACTLY (see ACCENT_DOTS in
 *  AccentDots.tsx, whose header records grey as "the silver
 *  family", with the owner's silver gear art) — so the picker
 *  marks that swatch current in light until the user picks,
 *  exactly as the orange preset marks dark's default. A pick
 *  made in one mode never leaks into the other: dark+orange
 *  flipping to light sees silver, flipping back sees orange. */
const LIGHT_DEFAULT_ACCENT = "#c7ccd4";

/** Derive a translucent + a darker variant from a hex accent color. */
function deriveAccent(hex: string): { soft: string; strong: string; glow: string } {
  const m = hex.replace("#", "");
  const full = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  if ([r, g, b].some(Number.isNaN)) {
    return { soft: "rgb(232 100 28 / 0.12)", strong: "#c24f10", glow: "0 0 12px rgb(232 100 28 / 0.45)" };
  }
  const strong = `#${[r, g, b].map((v) => Math.round(v * 0.78).toString(16).padStart(2, "0")).join("")}`;
  return {
    soft: `rgb(${r} ${g} ${b} / 0.12)`,
    strong,
    glow: `0 0 12px rgb(${r} ${g} ${b} / 0.45)`,
  };
}

/** The plate mid-tone (Steel family worn plates): the accent plate
 * gradient's full-strength stop. Overlay-blended wear is a
 * mathematical no-op over a channel pinned at 0 or 255 — the blend
 * returns the channel unchanged — so a FULLY pinned accent (every
 * channel 0 or 255; of the shipping set only pure red #ff0000) shows
 * zero wear and reads glassy smooth while every other accent's
 * channels sit mid-range and distress visibly (measured 2026-10-19:
 * wear-map luminance std over #ff0000 = 0.0000, over orange/blue/
 * pink ≈ 0.07–0.08). For a pinned accent the plate mid is pulled
 * to the same 0.78 factor `strong` uses — still unmistakably the
 * same color (red stays red), but its channels sit where the wear
 * map can bite. --accent itself is untouched: glows, text, borders
 * and every non-plate surface keep the exact picked color. Any
 * unpinned accent passes through unchanged. */
function derivePlateMid(hex: string): string {
  const m = hex.replace("#", "");
  const full = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  const rgb = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  if (rgb.some(Number.isNaN)) return hex;
  const pinned = rgb.every((v) => v === 0 || v === 255);
  if (!pinned) return hex;
  return `#${rgb.map((v) => Math.round(v * 0.78).toString(16).padStart(2, "0")).join("")}`;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>(() => {
    const saved = localStorage.getItem("tv-theme");
    const resolved = resolveSavedTheme(saved);
    // Persist the migration so storage holds a canonical id from now on.
    if (saved !== null && saved !== resolved) {
      localStorage.setItem("tv-theme", resolved);
    }
    return resolved;
  });
  // The two per-mode accent slots (see PER-MODE ACCENT above):
  // the dark pick always holds a value (the orange default
  // fills its empty slot); the light pick is NULL until the
  // user picks a color while in light mode.
  const [accentDark, setAccentDarkState] = useState<string>(
    () => localStorage.getItem("tv-accent") ?? DEFAULT_ACCENT,
  );
  const [accentLight, setAccentLightState] = useState<string | null>(
    () => localStorage.getItem("tv-accent-light"),
  );
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem("tv-mode");
    return saved === "light" || saved === "dark" ? saved : CURRENT_MODE;
  });
  // The EFFECTIVE accent: the current mode's pick, or that
  // mode's default when the mode has no pick yet. Everything
  // downstream (CSS vars, pickers, the gear avatar) reads this.
  const accent =
    mode === "light" ? (accentLight ?? LIGHT_DEFAULT_ACCENT) : accentDark;
  // The current appearance, mirrored in a ref so the setters
  // can build the FULL next appearance (the account stores the
  // fields together) without depending on render timing.
  const stateRef = useRef({ theme, mode, accentDark, accentLight });
  stateRef.current = { theme, mode, accentDark, accentLight };

  /** Apply a whole appearance at once: React state + the local
   *  mirror (tv-theme / tv-mode / tv-accent + tv-accent-light —
   *  the boot/pre-login cache), and, when `persist` and a
   *  session exists, the account itself via PATCH /core/me
   *  (owner ruling, 2026-10-25: appearance lives with the
   *  account). A null light pick is simply not sent — the
   *  account field stays NULL ("no pick in light"), which is a
   *  state, not an unsent update. The account save is
   *  fire-and-forget: the local apply never waits on the
   *  network, and a failed save is retried by the next change
   *  or the next sign-in's adoption — the account can lag a
   *  click, never lose to the browser once saved. */
  const applyAppearance = useCallback(
    (
      next: {
        theme: ThemeName;
        mode: ThemeMode;
        accentDark: string;
        accentLight: string | null;
      },
      persist: boolean,
    ) => {
      stateRef.current = next;
      setThemeState(next.theme);
      setModeState(next.mode);
      setAccentDarkState(next.accentDark);
      setAccentLightState(next.accentLight);
      localStorage.setItem("tv-theme", next.theme);
      localStorage.setItem("tv-mode", next.mode);
      localStorage.setItem("tv-accent", next.accentDark);
      if (next.accentLight !== null) {
        localStorage.setItem("tv-accent-light", next.accentLight);
      } else {
        localStorage.removeItem("tv-accent-light");
      }
      if (persist && localStorage.getItem(TOKEN_KEY)) {
        void api("/core/me", {
          method: "PATCH",
          body: JSON.stringify({
            appearance_mode: next.mode,
            appearance_accent: next.accentDark,
            ...(next.accentLight !== null
              ? { appearance_accent_light: next.accentLight }
              : {}),
            appearance_theme: next.theme,
          }),
        }).catch(() => undefined);
      }
    },
    [],
  );

  const setTheme = useCallback(
    (t: ThemeName) => {
      applyAppearance({ ...stateRef.current, theme: t }, true);
    },
    [applyAppearance],
  );

  const setMode = useCallback(
    (m: ThemeMode) => {
      applyAppearance({ ...stateRef.current, mode: m }, true);
    },
    [applyAppearance],
  );

  /** A pick lands in the CURRENT mode's slot only — flipping
   *  modes afterwards shows the other mode's own pick (or its
   *  default), never this one. */
  const setAccent = useCallback(
    (c: string) => {
      const cur = stateRef.current;
      applyAppearance(
        cur.mode === "light"
          ? { ...cur, accentLight: c }
          : { ...cur, accentDark: c },
        true,
      );
    },
    [applyAppearance],
  );

  const hydrateFromAccount = useCallback(
    (a: {
      mode: string | null;
      accent: string | null;
      accentLight: string | null;
      theme: string | null;
    }) => {
      // Fully unsaved account: nothing to apply (AuthContext
      // adopts the current look instead).
      if (
        a.mode == null &&
        a.accent == null &&
        a.accentLight == null &&
        a.theme == null
      )
        return;
      // Partially saved (only possible from a manual write —
      // the client always saves the set): the gaps fill from
      // the DEFAULTS, not from this browser's local values,
      // because a saved account is the source of truth. A null
      // light pick stays null — silver is a default, not a
      // pick, and must not be written into the pick slot.
      applyAppearance(
        {
          theme: resolveSavedTheme(a.theme),
          mode:
            a.mode === "light" || a.mode === "dark" ? a.mode : CURRENT_MODE,
          accentDark: a.accent ?? DEFAULT_ACCENT,
          accentLight: a.accentLight ?? null,
        },
        false,
      );
    },
    [applyAppearance],
  );

  // Light-variant retirement (2026-10-24): the preview key is
  // dead and nothing reads it — clear it once so no stale value
  // lingers in storage (see THE LIGHT PALETTE note above).
  useEffect(() => {
    localStorage.removeItem("tv-light-variant");
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    // The mode seam (see CURRENT_MODE): the attribute contract
    // exists from today so a light palette keys on it without
    // any shell or component change.
    document.documentElement.dataset.mode = mode;
    const root = document.documentElement;
    const { soft, strong, glow } = deriveAccent(accent);
    root.style.setProperty("--accent", accent);
    root.style.setProperty("--accent-soft", soft);
    root.style.setProperty("--accent-strong", strong);
    root.style.setProperty("--accent-plate-mid", derivePlateMid(accent));
    root.style.setProperty("--glow", glow);
  }, [theme, accent, mode]);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      mode,
      setMode,
      accent,
      setAccent,
      accentDark,
      accentLight,
      hydrateFromAccount,
    }),
    [
      theme,
      setTheme,
      mode,
      setMode,
      accent,
      setAccent,
      accentDark,
      accentLight,
      hydrateFromAccount,
    ],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
