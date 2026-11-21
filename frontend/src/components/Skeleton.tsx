/**
 * Loading skeletons (deep audit F1-01, 2026-10-23): every
 * navigation must paint the shell plus a content frame that
 * matches the incoming page's geometry — never a bare void and
 * never a lone spinner floating on an empty page. The blocks are
 * inert (aria-hidden; the region carries aria-busy) and styled
 * entirely by the .tv-skel classes in theme/surfaces.css, so
 * every theme renders them in its own surface/edge tokens.
 */

export function SkeletonBar({
  width = "100%",
  height = "0.9rem",
}: {
  width?: string;
  height?: string;
}) {
  return <div className="tv-skel" style={{ width, height }} aria-hidden="true" />;
}

/** A panel-shaped skeleton: header line + body lines, at the real
 *  Panel's padding/radius (the .tv-skel-panel class mirrors it). */
export function SkeletonPanel({ lines = 3 }: { lines?: number }) {
  return (
    <div className="tv-skel-panel" aria-hidden="true">
      <SkeletonBar width="38%" height="1rem" />
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonBar key={i} width={i === lines - 1 ? "64%" : "92%"} />
      ))}
    </div>
  );
}

/** The generic route frame: page-title bar + two panels. Used as
 *  the Suspense fallback so a lazy chunk load keeps the shell
 *  filled with page-shaped content instead of empty space. */
export function PageSkeleton() {
  return (
    <div className="tv-skel-stack" role="status" aria-label="Loading" aria-busy="true">
      <SkeletonBar width="13rem" height="1.6rem" />
      <SkeletonPanel lines={3} />
      <SkeletonPanel lines={2} />
    </div>
  );
}

/** Home frame: the stat-card row (same grid + card height as
 *  .tv-overview-grid / .tv-stat-card) over two panels. */
export function HomeSkeleton() {
  return (
    <div className="tv-skel-stack" role="status" aria-label="Loading" aria-busy="true">
      <div className="tv-overview-grid" aria-hidden="true">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="tv-skel tv-skel-stat" />
        ))}
      </div>
      <SkeletonPanel lines={3} />
      <SkeletonPanel lines={2} />
    </div>
  );
}

/** Inventory frame: the list table's shape — one panel holding
 *  a header line over a run of record rows (the inventory is a
 *  list, only a list — owner, 2026-11-05). */
export function InventorySkeleton() {
  return (
    <div
      className="tv-skel-panel"
      role="status"
      aria-label="Loading"
      aria-busy="true"
      aria-hidden="true"
      style={{ gap: "0.85rem" }}
    >
      <SkeletonBar width="42%" height="1rem" />
      {Array.from({ length: 6 }, (_, i) => (
        <div
          key={i}
          style={{ display: "flex", gap: "1rem", alignItems: "center" }}
        >
          <SkeletonBar width="2.6rem" height="2.6rem" />
          <SkeletonBar width="34%" />
          <SkeletonBar width="18%" />
          <SkeletonBar width="12%" />
        </div>
      ))}
    </div>
  );
}

/** Item-detail frame: title bar, hero-photo block (the real hero's
 *  height), then two panels — the detail page's actual shape. */
export function DetailSkeleton() {
  return (
    <div className="tv-skel-stack" role="status" aria-label="Loading" aria-busy="true">
      <SkeletonBar width="16rem" height="1.6rem" />
      <div className="tv-skel" style={{ height: "20rem" }} aria-hidden="true" />
      <SkeletonPanel lines={4} />
      <SkeletonPanel lines={3} />
    </div>
  );
}

/** Quiet in-panel placeholder for secondary detail panels (deep
 *  audit F1-02): two still skeleton lines instead of a per-panel
 *  spinner — the panel keeps its shape while its data lands, with
 *  no spinner theatre competing with the page's primary content. */
export function QuietSkeleton({ lines = 2 }: { lines?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      aria-busy="true"
      style={{ display: "grid", gap: "0.55rem" }}
    >
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonBar key={i} width={i === lines - 1 ? "58%" : "88%"} />
      ))}
    </div>
  );
}
