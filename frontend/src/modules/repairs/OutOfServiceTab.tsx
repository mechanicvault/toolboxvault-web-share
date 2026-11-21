import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Panel, Spinner, Toggle } from "../../components";
import { api } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { getBorrowingOverview } from "../borrowing/api";
import type { Checkout } from "../borrowing/types";
import {
  DealerCell,
  OutOfServiceEmpty,
  OutOfServiceRow,
  TableHead,
  itemPath,
} from "../maintenance/boards";
import { fullDate } from "../maintenance/format";
import type { OutOfServiceEntry } from "../maintenance/types";

/**
 * The merged page's landing tab (Repairs & Maintenance merge,
 * 2026-11-05): the out-of-service board — every item that is
 * out of service for whatever reason (owner, sheet row 6,
 * 2026-11-15): broken or sent out for repair, marked lost or
 * stolen (the board reads those standings off the inventory
 * records server-side), and the items currently lent out,
 * marked as borrowed with who has them and when they're due.
 *
 * The borrowed rows ride the owner's "Include borrowed
 * tools" toggle. History: the toggle originally started OFF
 * (lent tools hid unless the owner found the switch); sheet
 * row 6 (2026-11-15) put borrowed tools on the list for
 * good and retired the toggle; the owner then asked for the
 * toggle back (2026-11-16) — it returns STARTING ON, so
 * borrowed tools are on the list by default exactly as
 * row 6 ordered, and the switch now only ever hides them
 * at the owner's own hand. Its state is remembered per user
 * through the shared per-user page-layout store (page key
 * "repairs", block key "out-of-service") — no new table; a
 * failed save just means the choice isn't remembered, the
 * toggle itself always works. Borrowed rows load only
 * while the toggle is ON and the borrowing module is
 * effective — with borrowing off there is nothing to
 * include, so the toggle itself hides.
 *
 * The board rows arrive from the page (it fetches the board
 * once for the header count as well).
 */

interface LayoutBlock {
  key: string;
  visible: boolean;
  settings?: Record<string, unknown>;
}

const BLOCK_KEY = "out-of-service";

function BorrowedRow({ checkout }: { checkout: Checkout }) {
  const t = useT();
  const problem = checkout.due_at
    ? `${t("repairs.lentTo")} ${checkout.borrower_name} · ${t("repairs.due")} ${fullDate(checkout.due_at.slice(0, 10))}`
    : `${t("repairs.lentTo")} ${checkout.borrower_name} · ${t("repairs.noDue")}`;
  return (
    <div className="tv-maint-row" role="row">
      <div className="tv-maint-cell-item" role="cell">
        <Link
          to={`${itemPath(checkout)}#lending`}
          style={{ color: "var(--accent)" }}
        >
          {checkout.item_name}
        </Link>
      </div>
      <DealerCell brand={checkout.brand} dealerName={checkout.dealer_company_name} />
      <div role="cell">
        <span className="tv-maint-mlabel">Problem</span>
        <span className="tv-maint-problem" title={problem}>
          {problem}
        </span>
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Since</span>
        {checkout.checked_out_at
          ? fullDate(checkout.checked_out_at.slice(0, 10))
          : "—"}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Status</span>
        <span className="tv-maint-claimcell">
          <Badge tone="accent" dot>
            {t("repairs.borrowed")}
          </Badge>
          {checkout.overdue && (
            <Badge tone="danger">{t("repairs.overdue")}</Badge>
          )}
        </span>
      </div>
      <div role="cell">
        <Link
          to={`${itemPath(checkout)}#lending`}
          style={{ color: "var(--accent)", fontSize: "0.9rem" }}
        >
          Open item →
        </Link>
      </div>
    </div>
  );
}

export function OutOfServiceTab({
  entries,
  error,
  borrowingOn,
  borrowedLocked = false,
}: {
  entries: OutOfServiceEntry[] | null;
  error: string | null;
  borrowingOn: boolean;
  /** Sheet row 135 (owner, 2026-11-18): the Inventory page's
   *  out-of-service view carries NO borrowed toggle — every
   *  out-of-service item shows, borrowed ones included, so
   *  the borrowed rows are locked in and the switch (and its
   *  remembered per-user state) never renders or applies. */
  borrowedLocked?: boolean;
}) {
  const t = useT();
  const [includeBorrowed, setIncludeBorrowed] = useState(true);
  const showBorrowed = borrowedLocked || includeBorrowed;
  const [lentOut, setLentOut] = useState<Checkout[] | null>(null);
  const [borrowedError, setBorrowedError] = useState(false);
  // The layout blocks as loaded, so a toggle save preserves any
  // other block the page key ever gains.
  const blocksRef = useRef<LayoutBlock[]>([]);

  // Hydrate the remembered choice (starts ON until it loads —
  // only a stored OFF turns borrowed rows off). Locked views
  // never read it: borrowed rows there are not a choice.
  useEffect(() => {
    if (borrowedLocked) return;
    let cancelled = false;
    api<{ blocks: LayoutBlock[] }>("/core/layouts/repairs")
      .then((layout) => {
        if (cancelled) return;
        blocksRef.current = layout.blocks ?? [];
        const block = blocksRef.current.find((b) => b.key === BLOCK_KEY);
        if (block?.settings?.include_borrowed === false) {
          setIncludeBorrowed(false);
        }
      })
      .catch(() => {
        // No stored layout (or unreadable): the toggle just
        // starts ON, as the owner ordered.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function onToggle(next: boolean) {
    setIncludeBorrowed(next);
    const others = blocksRef.current.filter((b) => b.key !== BLOCK_KEY);
    const blocks: LayoutBlock[] = [
      ...others,
      {
        key: BLOCK_KEY,
        visible: true,
        settings: { include_borrowed: next },
      },
    ];
    blocksRef.current = blocks;
    void api("/core/layouts/repairs", {
      method: "PUT",
      body: JSON.stringify({ blocks }),
    }).catch(() => {
      // Best-effort memory: the toggle still applies for this
      // visit even if the save doesn't land.
    });
  }

  // Lent-out rows load only while they're wanted.
  useEffect(() => {
    if (!showBorrowed || !borrowingOn || lentOut !== null) return;
    let cancelled = false;
    getBorrowingOverview()
      .then((overview) => {
        if (cancelled) return;
        setLentOut(
          overview.lent_out.filter((row) => row.state === "checked_out"),
        );
      })
      .catch(() => {
        if (!cancelled) setBorrowedError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [showBorrowed, borrowingOn, lentOut]);

  const board = entries ?? [];
  const borrowedRows = showBorrowed && borrowingOn ? (lentOut ?? []) : [];
  const showTable = board.length > 0 || borrowedRows.length > 0;

  return (
    <div>
      {borrowingOn && !borrowedLocked && (
        <div className="tv-repairs-toggle-row">
          <Toggle
            checked={includeBorrowed}
            onChange={onToggle}
            label={t("repairs.includeBorrowed")}
          />
        </div>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {borrowedError && (
        <Alert tone="danger">{t("repairs.borrowedLoadError")}</Alert>
      )}
      {entries === null && !error && <Spinner label="Loading…" />}
      {entries !== null && (
        <Panel title="Currently out of service" className="tv-maint-panel">
          {showTable ? (
            <div
              className="tv-maint-table tv-maint-table--repairs"
              role="table"
            >
              <TableHead
                cols={["Item", "Dealer/Brand", "Problem", "Since", "Status", null]}
              />
              {board.map((entry) => (
                <OutOfServiceRow
                  key={`${entry.item_kind}-${entry.item_id}`}
                  entry={entry}
                />
              ))}
              {borrowedRows.map((checkout) => (
                <BorrowedRow key={checkout.id} checkout={checkout} />
              ))}
            </div>
          ) : (
            <OutOfServiceEmpty />
          )}
        </Panel>
      )}
    </div>
  );
}
