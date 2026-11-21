import { useT } from "../i18n/LocaleContext";

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
 * (public/accents/gear-<id>.png), and the CSS dot-painting
 * of rounds 1–3 is retired wholesale: exactly one swatch
 * implementation exists, this component + the owner's PNGs.
 * `value` remains the accent the site re-tints with — plates,
 * glows and text accents still run on the color values; only
 * the picker renders art.
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
   * ART, not a CSS drawing. */
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
 * THE GEAR IS RETIRED (owner, 2026-11-13): the header gear —
 * the hidden chooser that once picked the accent, then carried
 * the rail pin row and the Site settings tree after appearance
 * moved to the header's center theme cluster (2026-11-12) — is
 * removed from the header entirely. Its last two contents live
 * in the user menu now: the pin row (unchanged strings, state
 * and behavior) directly above ONE "Site settings" link to the
 * settings page — a link, not the tree. The gear artwork above
 * survives where it still works: the labeled swatch chips
 * below, in Settings → Appearance and the setup surfaces.
 */

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
    <div className="tv-accent-swatches" role="group" aria-label={t("settings.appearance.accent")}>
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
