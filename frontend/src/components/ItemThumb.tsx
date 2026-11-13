import { useT } from "../i18n/LocaleContext";
import { FramedImage } from "./FramedImage";

/**
 * The ONE central no-photo placeholder (owner directive,
 * 2026-11-02; artwork replaced by sweep B2-F7, 2026-11-12): a
 * full-colour rendered toolbox — the site's own motif — on a
 * theme-aware steel ground (the .tv-thumb frame carries the
 * ground; the SVG's own ground is transparent), hand-built as a
 * featherweight SVG in the central brand folder. The old art —
 * flat line-drawn gears on a fixed black slab — was the banned
 * "flat glyph on a slab" in both themes. Every thumbnail slot
 * on the site pulls this same file — nothing is generated or
 * stored per item, and the browser caches it once.
 *
 * DISPLAY-ONLY, by the owner's word: the placeholder is paint,
 * never data. An item showing it is still photo-less to every
 * piece of logic — photo counts stay 0, completeness stays unmet,
 * and claim-readiness warnings fire exactly as before. No media
 * row or file is ever created because this rendered.
 */
export const NO_PHOTO_PLACEHOLDER_SRC = "/brand/no-photo-placeholder.svg";

const RATIO_CLASS: Record<string, string> = {
  "16 / 9": "tv-thumb--16x9",
  "4 / 3": "tv-thumb--4x3",
  "1 / 1": "tv-thumb--1x1",
};

/**
 * The shared item-thumbnail component. Given the item's primary
 * photo rendition URL (or null when the item has no photo), it
 * renders the real photo — framed, exactly as the site's framed
 * slots have always rendered it — or the placeholder plate in the
 * same slot.
 *
 * Two slot shapes:
 *  - framed (default): an aspect-ratio frame (tile 16/9, row 4/3);
 *    the real photo rides FramedImage, the placeholder fills the
 *    same frame (its own plate letterboxes invisibly on the
 *    plate-coloured ground).
 *  - fill: the component fills a fixed-size box the caller picks
 *    via `sizeClass` (the small square slots — reports, parts,
 *    community, wishlist, marketplace cards). The size class sizes
 *    BOTH the real-photo img and the placeholder span, so a row
 *    never changes height when a photo appears.
 *
 * Alt text stays honest: a real photo's alt is the item's name;
 * the placeholder's alt is the "No photo" string — it never poses
 * as a photo of the item.
 */
export function ItemThumb({
  src,
  name,
  aspectRatio = "4 / 3",
  fit = "contain",
  fill = false,
  sizeClass = "",
}: {
  /** Primary-photo rendition URL, or null/undefined when photo-less. */
  src?: string | null;
  /** The item's name — the real photo's alt text. */
  name: string;
  aspectRatio?: string;
  fit?: "cover" | "contain";
  fill?: boolean;
  sizeClass?: string;
}) {
  const t = useT();
  if (fill) {
    if (src) {
      return <img className={`tv-thumb-img ${sizeClass}`} src={src} alt={name} />;
    }
    return (
      <span className={`tv-thumb ${sizeClass}`}>
        <img src={NO_PHOTO_PLACEHOLDER_SRC} alt={t("common.noPhoto")} />
      </span>
    );
  }
  if (src) {
    return (
      <FramedImage src={src} alt={name} aspectRatio={aspectRatio} fit={fit} />
    );
  }
  return (
    <span className={`tv-thumb ${RATIO_CLASS[aspectRatio] ?? "tv-thumb--4x3"}`}>
      <img src={NO_PHOTO_PLACEHOLDER_SRC} alt={t("common.noPhoto")} />
    </span>
  );
}
