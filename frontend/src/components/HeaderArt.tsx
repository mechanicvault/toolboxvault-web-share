/**
 * HeaderArt — the page-header plate artwork: a glossy
 * 3D-rendered icon seated as a square tile inside the header's
 * framed plate. The tile itself NEVER moves (the 2026-11-16
 * plate sway was rejected by the owner on 2026-11-17); each
 * icon's artwork is an animated WebP whose own object moves
 * inside the still frame. One shared component for every page
 * header (the SectionPageHeader thumb and the custom Admin /
 * Reports / Repairs / Help / Settings thumbs). The seat lives
 * in theme/surfaces.css (.tv-header-art). Artwork:
 * public/headers/<name>.webp.
 *
 * The ?v= tag is the cache-bust (owner report, 2026-11-17):
 * the artwork files keep one URL while their content changes
 * (still image -> animated WebP), and the host serves them
 * with a 4-hour cache — browsers that picked up a still copy
 * kept showing it long after the animated one shipped. Bump
 * ART_VERSION whenever the artwork set changes.
 */
export type HeaderArtName =
  | "inventory"
  | "downloads"
  | "shared"
  | "borrowing"
  | "dealers"
  | "repairs"
  | "forum"
  | "truck"
  | "feedback"
  | "videos"
  | "expansion"
  | "disaster"
  | "flyers"
  | "parts"
  | "reports"
  | "badge"
  | "support"
  | "settings";

const ART_VERSION = 2;

export function HeaderArt({ name }: { name: HeaderArtName }) {
  return (
    <span className="tv-header-art" aria-hidden="true">
      <img
        src={`/headers/${name}.webp?v=${ART_VERSION}`}
        alt=""
        draggable={false}
      />
    </span>
  );
}
