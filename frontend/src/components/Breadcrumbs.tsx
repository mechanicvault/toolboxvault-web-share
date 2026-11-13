import { Link } from "react-router-dom";

export interface Crumb {
  label: string;
  /** Omit on the last crumb (the current page). */
  to?: string;
}

/**
 * Breadcrumb trail. An item carrying a destination renders as a
 * link; an item without one is plain text, and the LAST such
 * item is marked as the current page. (A one-item trail whose
 * only item points at the parent — the item pages' original
 * "Inventory" — is a link, not a fake current page: marking it
 * current left it unclickable and visually stranded, the defect
 * the owner flagged 2026-11-02.)
 */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="tv-crumbs">
        {items.map((item, i) => {
          const last = i === items.length - 1;
          return (
            <li key={`${item.label}-${i}`}>
              {item.to ? (
                <Link to={item.to}>{item.label}</Link>
              ) : (
                <span aria-current={last ? "page" : undefined}>{item.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
