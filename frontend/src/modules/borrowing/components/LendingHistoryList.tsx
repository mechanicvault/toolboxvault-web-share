import { Link, useNavigate } from "react-router-dom";
import { borrowerPath, fullDate, itemPath, STATE_LABELS } from "../format";
import type { Checkout } from "../types";
/* The list's skin lives in the module sheet; imported here so
 * the rows are styled on every surface that mounts the list
 * (the Borrowing page AND item pages, via LendingPanel) — the
 * CheckoutModal precedent. */
import "../borrowing.css";

/**
 * The lending history as a Main list layout list (owner order,
 * 2026-11-12): the Inventory tool list's presentation — a
 * bordered panel, a header row, one lend per row, facts in
 * columns with clear dividers. Columns are the owner's three:
 * Checked out · Returned · Borrower — plus the item itself on
 * the page-level histories (the Borrowing page's History tab,
 * a borrower's roll-up), where one list spans many items.
 *
 * Cell conventions keep the paper trail the old stacked rows
 * carried, inside the ordered columns: a lend that never went
 * out shows "Asked <date>" in the Checked out seat; a loan
 * still out says "Still out" in the Returned seat; a declined
 * or cancelled ask names its ending as a quiet sub-line there;
 * a return keeps its "marked back by …" sub-line.
 *
 * The borrower is a link (borrowerPath in format.ts): address
 * book lends land on their book entry, member lends on the
 * person in Shared tools, typed names on the Address book.
 *
 * On the Borrowing page the rows also carry that page's
 * two-way click (rowOpen): the row opens the item's Borrowing
 * tab, the item's name opens the item page — the name is an
 * <a>, so the row's click guard steps aside for it, exactly
 * like the ledger rows in BorrowingPage.
 */
export function LendingHistoryList({
  rows,
  variant,
  emptyText,
  viewerId,
  rowOpen = false,
  flashId,
  renderItem,
}: {
  rows: Checkout[];
  /** item — the detail-page list (no item column);
   *  page — item + the three facts (Borrowing History tab);
   *  rollup — item + out/returned (one borrower's own list,
   *  where the borrower is the page's subject, not a column). */
  variant: "item" | "page" | "rollup";
  /** The honest empty line, in the host surface's own words. */
  emptyText: string;
  /** The signed-in user, when the host knows it — flips the
   *  borrower link for rows the viewer borrowed themselves. */
  viewerId?: string | null;
  /** Borrowing-page rows: the whole row is the door to the
   *  item's Borrowing tab (Order 2's two-way click). */
  rowOpen?: boolean;
  /** The ?checkout= landing flash, as on the ledger rows. */
  flashId?: string | null;
  /** The item cell's content for item-carrying variants (the
   *  Borrowing page passes its name link + standing badges). */
  renderItem?: (row: Checkout) => React.ReactNode;
}) {
  const navigate = useNavigate();

  if (rows.length === 0) {
    return (
      <div className={`tv-bw-mlist tv-bw-mlist--${variant}`}>
        <p className="tv-bw-mlist-empty">{emptyText}</p>
      </div>
    );
  }

  const showItem = variant !== "item";
  const showBorrower = variant !== "rollup";

  function openRow(row: Checkout) {
    navigate(`${itemPath(row)}#borrowing`);
  }

  return (
    <div className={`tv-bw-mlist tv-bw-mlist--${variant}`} role="table">
      <div className="tv-bw-mlist-head" role="row">
        {showItem && <span role="columnheader">Item</span>}
        <span role="columnheader">Checked out</span>
        <span role="columnheader">Returned</span>
        {showBorrower && <span role="columnheader">Borrower</span>}
      </div>
      {rows.map((row) => (
        <div
          key={row.id}
          id={`checkout-${row.id}`}
          role="row"
          className={`tv-bw-mlist-row${rowOpen ? " tv-bw-mlist-row--link" : ""}${
            flashId === row.id ? " tv-bw-row--flash" : ""
          }`}
          {...(rowOpen
            ? {
                tabIndex: 0,
                onClick: (e: React.MouseEvent) => {
                  const el = e.target as HTMLElement;
                  if (
                    el.closest(
                      "a, button, input, select, textarea, [role='button']",
                    )
                  )
                    return;
                  openRow(row);
                },
                onKeyDown: (e: React.KeyboardEvent) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openRow(row);
                  }
                },
              }
            : {})}
        >
          {showItem && (
            <div className="tv-bw-mlist-cell tv-bw-mlist-cell--item" role="cell">
              {renderItem ? renderItem(row) : row.item_name}
            </div>
          )}
          <div className="tv-bw-mlist-cell" role="cell">
            <span className="tv-bw-mlist-label" aria-hidden="true">
              Checked out
            </span>
            {row.checked_out_at
              ? fullDate(row.checked_out_at)
              : `Asked ${fullDate(row.requested_at)}`}
          </div>
          <div className="tv-bw-mlist-cell" role="cell">
            <span className="tv-bw-mlist-label" aria-hidden="true">
              Returned
            </span>
            {row.returned_at ? (
              <>
                {fullDate(row.returned_at)}
                {row.state === "returned" && row.returned_by && (
                  <span className="tv-bw-cell-sub">
                    Marked back by the {row.returned_by}
                  </span>
                )}
              </>
            ) : row.state === "checked_out" ? (
              "Still out"
            ) : (
              <>
                —
                {(row.state === "declined" ||
                  row.state === "cancelled" ||
                  row.state === "requested") && (
                  <span className="tv-bw-cell-sub">
                    {STATE_LABELS[row.state]}
                  </span>
                )}
              </>
            )}
          </div>
          {showBorrower && (
            <div className="tv-bw-mlist-cell" role="cell">
              <span className="tv-bw-mlist-label" aria-hidden="true">
                Borrower
              </span>
              <Link
                className="tv-bw-mlist-borrower"
                to={borrowerPath(row, viewerId)}
              >
                {viewerId && row.borrower_user_id === viewerId
                  ? (row.owner_name ?? "the owner")
                  : row.borrower_name}
              </Link>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
