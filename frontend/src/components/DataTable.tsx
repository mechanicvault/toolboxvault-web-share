import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Enable header sorting; provide sortValue (or a comparable render). */
  sortable?: boolean;
  sortValue?: (row: T) => string | number;
  align?: "left" | "center" | "right";
  width?: string;
}

export type SortDirection = "asc" | "desc";

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Shown when rows is empty. Defaults to a standard message. */
  emptyState?: ReactNode;
  onRowClick?: (row: T) => void;
  /* Controlled sorting (optional). Omit for built-in client-side sort. */
  sortKey?: string;
  sortDirection?: SortDirection;
  onSortChange?: (key: string, direction: SortDirection) => void;
}

function compare(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * The shared data table every module uses for lists: sortable headers,
 * row hover, and a standard empty state. Modules must NOT build their
 * own tables — extend this one via props instead.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyState,
  onRowClick,
  sortKey: sortKeyProp,
  sortDirection: sortDirProp,
  onSortChange,
}: DataTableProps<T>) {
  const [localSort, setLocalSort] = useState<{ key: string; dir: SortDirection } | null>(null);
  const controlled = sortKeyProp !== undefined;
  const sortKey = controlled ? sortKeyProp : localSort?.key;
  const sortDir: SortDirection = controlled ? (sortDirProp ?? "asc") : (localSort?.dir ?? "asc");

  const sortedRows = useMemo(() => {
    if (controlled || !localSort) return rows;
    const col = columns.find((c) => c.key === localSort.key);
    if (!col?.sortValue) return rows;
    const dir = localSort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => dir * compare(col.sortValue!(a), col.sortValue!(b)));
  }, [rows, columns, localSort, controlled]);

  function toggleSort(col: Column<T>) {
    if (!col.sortable) return;
    const nextDir: SortDirection = sortKey === col.key && sortDir === "asc" ? "desc" : "asc";
    if (controlled) {
      onSortChange?.(col.key, nextDir);
    } else {
      setLocalSort({ key: col.key, dir: nextDir });
    }
  }

  return (
    <div className="tv-table-wrap">
      <table className="tv-table">
        <thead>
          <tr>
            {columns.map((col) => {
              const active = sortKey === col.key;
              return (
                <th
                  key={col.key}
                  style={{ textAlign: col.align ?? "left", width: col.width }}
                  aria-sort={
                    active ? (sortDir === "asc" ? "ascending" : "descending") : undefined
                  }
                >
                  {col.sortable ? (
                    <button
                      type="button"
                      className="tv-th-sort"
                      onClick={() => toggleSort(col)}
                      aria-label={`Sort by ${col.header}`}
                    >
                      {col.header}
                      <span className="tv-th-arrow" aria-hidden="true">
                        {active ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "is-clickable" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((col) => (
                <td key={col.key} style={{ textAlign: col.align ?? "left" }}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="tv-table-empty">{emptyState ?? "Nothing to show yet."}</div>
      )}
    </div>
  );
}
