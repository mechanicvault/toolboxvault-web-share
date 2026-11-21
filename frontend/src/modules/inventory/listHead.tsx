import { useT } from "../../i18n/LocaleContext";
import { SortKey } from "./listUtils";

export function InventoryListHead({
  allSelected,
  onToggleSelectAll,
  sortKey,
  sortDir,
  onSort,
}: {
  allSelected: boolean;
  onToggleSelectAll: () => void;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (key: SortKey) => void;
}) {
  const t = useT();
  // Sheet row 80 (owner): the header descriptions themselves
  // sort — a click on a column sorts by it, a second click on
  // the SAME column reverses the direction. The button carries
  // the column's label plus the direction arrow while its sort
  // runs; the columnheader carries aria-sort for readers.
  const sortHead = (
    key: SortKey,
    label: string,
    num = false,
  ) => (
    <span
      className={num ? "tv-inv-th--num" : undefined}
      role="columnheader"
      aria-sort={
        sortKey === key
          ? sortDir === "asc"
            ? "ascending"
            : "descending"
          : undefined
      }
    >
      <button
        type="button"
        className="tv-inv-th-sort"
        data-active={sortKey === key || undefined}
        onClick={() => onSort(key)}
      >
        {label}
        {sortKey === key && (
          <span className="tv-inv-th-arrow" aria-hidden="true">
            {sortDir === "asc" ? "▲" : "▼"}
          </span>
        )}
      </button>
    </span>
  );
  return (
    <div className="tv-inv-thead" role="row">
      <span role="columnheader" aria-label={t("inventory.col.select")}>
        <button
          type="button"
          className="tv-inv-selectall-link"
          onClick={onToggleSelectAll}
        >
          {allSelected ? t("inventory.selectNone") : t("inventory.selectAll")}
        </button>
      </span>
      {sortHead("name", t("inventory.col.item"))}
      {sortHead("dealer", t("inventory.col.dealerBrand"))}
      {sortHead("status", t("inventory.col.status"))}
      {sortHead("quantity", t("inventory.col.qty"), true)}
      {sortHead("price", t("inventory.col.price"), true)}
      <span role="columnheader" aria-label={t("inventory.actions")} />
    </div>
  );
}

/** A row's lending footer data (borrowing module): the item's
 *  current standing chip. Supplied by the list page, which owns
 *  the borrowing read; absent when borrowing isn't available. */
