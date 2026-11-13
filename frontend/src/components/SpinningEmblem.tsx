import { useState } from "react";

/**
 * The brand emblem as a 3D object (owner review round 1,
 * 2026-10-19; reshaped owner 2026-10-20): the official logo —
 * wrench and hammer — spinning slowly in place like a coin,
 * BOTH faces the logo itself, verbatim, never recolored.
 *
 * The plate is an OCTAGON, not a square: the badge drawn in the
 * artwork is itself an octagonal plate (clipped corners, rivets,
 * orange border), and a square frame fights the art — black
 * image corners inside a square silhouette, the badge reading
 * inset and small. Since 2026-10-20 the trim lives in the asset
 * itself: logo-official.webp ships cropped to the badge with an
 * alpha matte on its own chamfers, so the faces just show it
 * full-bleed and the rim is eight facets — four straight + four
 * diagonal — so no square silhouette shows at any point of the
 * turn. Geometry lives in surfaces.css (.tv-emblem3d*).
 *
 * The faces load /brand/logo-256.webp — the SAME cropped badge
 * artwork at 256px (27KB) instead of the 1024px master (444KB):
 * the emblem never renders above ~48px, and the full-size file
 * was blowing the landing page's transfer budget on every page
 * of the site (2026-10-24).
 *
 * Construction: a rotor with preserve-3d turns on the vertical
 * axis over ~9s. The front face sits at +thickness/2; the back
 * face is pre-rotated 180°, so when the turn brings it around
 * the emblem reads CORRECTLY — never mirrored, like a real
 * two-sided sign. Under prefers-reduced-motion the rotor does
 * not turn (surfaces.css + the base.css global flattening both
 * stand it down). Purely decorative chrome: the surrounding
 * brand link carries the accessible name.
 */
export function SpinningEmblem() {
  /* The rotor holds at rest (full face forward) until the face
   * artwork has actually loaded (sweep 10-F10): a cold-cache
   * first paint can therefore never catch the coin mid-turn
   * with its faces still blank — the sliver. Once the image is
   * in, the spin starts from the full face, as designed. */
  const [loaded, setLoaded] = useState(false);
  return (
    <span className="tv-emblem3d" aria-hidden="true">
      <span className="tv-emblem3d-rotor" data-loaded={loaded || undefined}>
        {/* Intrinsic size (sweep 10-F10): both faces carry the
         * asset's real 256×256 dimensions, so the browser
         * reserves the face's full square from the HTML alone —
         * on a cold cache the mark paints at full size the
         * moment the image lands and can never be squeezed
         * into a thin sliver by an unknown aspect. */}
        <span className="tv-emblem3d-face tv-emblem3d-face--front">
          <img
            src="/brand/logo-256.webp"
            alt=""
            width={256}
            height={256}
            draggable={false}
            onLoad={() => setLoaded(true)}
          />
        </span>
        <span className="tv-emblem3d-face tv-emblem3d-face--back">
          <img
            src="/brand/logo-256.webp"
            alt=""
            width={256}
            height={256}
            draggable={false}
          />
        </span>
        <span className="tv-emblem3d-edge tv-emblem3d-edge--r" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--l" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--t" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--b" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--dtr" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--dbr" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--dbl" />
        <span className="tv-emblem3d-edge tv-emblem3d-edge--dtl" />
      </span>
    </span>
  );
}
