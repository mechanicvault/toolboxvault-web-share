import { Button } from "./Button";

interface PaginationProps {
  /** 1-based current page. */
  page: number;
  /** Total number of pages (>= 1). */
  pageCount: number;
  onChange: (page: number) => void;
  /** Optional "Page x of y · N items" summary. */
  summary?: string;
}

/** Page navigation with windowed numbers (never renders 500 buttons). */
export function Pagination({ page, pageCount, onChange, summary }: PaginationProps) {
  if (pageCount < 1) return null;
  const current = Math.min(Math.max(1, page), pageCount);

  const pages: (number | "…")[] = [];
  const window = new Set([1, pageCount, current - 1, current, current + 1]);
  let last = 0;
  for (let p = 1; p <= pageCount; p++) {
    if (!window.has(p)) continue;
    if (last && p - last > 1) pages.push("…");
    pages.push(p);
    last = p;
  }

  return (
    <nav className="tv-pagination" aria-label="Pagination">
      <Button
        size="sm"
        variant="secondary"
        disabled={current <= 1}
        onClick={() => onChange(current - 1)}
        aria-label="Previous page"
      >
        ← Prev
      </Button>
      {pages.map((p, i) =>
        p === "…" ? (
          <span key={`gap-${i}`} aria-hidden="true" style={{ color: "var(--text-muted)" }}>
            …
          </span>
        ) : (
          <Button
            key={p}
            size="sm"
            variant="secondary"
            className={p === current ? "is-current" : undefined}
            aria-current={p === current ? "page" : undefined}
            onClick={() => onChange(p)}
          >
            {p}
          </Button>
        ),
      )}
      <Button
        size="sm"
        variant="secondary"
        disabled={current >= pageCount}
        onClick={() => onChange(current + 1)}
        aria-label="Next page"
      >
        Next →
      </Button>
      {summary && <span className="tv-pagination-info">{summary}</span>}
    </nav>
  );
}
