import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Panel, Spinner, Toggle } from "../../components";
import { api } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { getBorrowingOverview } from "../borrowing/api";
import type { Checkout } from "../borrowing/types";
import {
  OutOfServiceEmpty,
  OutOfServiceRow,
  TableHead,
  itemPath,
} from "../maintenance/boards";
import { fullDate } from "../maintenance/format";
import type { OutOfServiceEntry } from "../maintenance/types";

/**
 * The merged page's landing tab (Repairs & Maintenance merge,
 * 2026-11-05): the out-of-service board — items marked broken
 * or sent out for repair, each with its claim and claim status
 * when it has one — plus the owner's toggle "Include borrowed
 * tools": ON, the items currently lent out join the same list,
 * marked as borrowed with who has them and when they're due;
 * OFF, the list is strictly out-of-service items.
 *
 * The toggle starts OFF and its state is remembered per user
 * through the shared per-user page-layout store (page key
 * "repairs", block key "out-of-service") — no new table; a
 * failed save just means the choice isn't remembered, the
 * toggle itself always works.
 *
 * The board rows arrive from the page (it fetches the board
 * once for the header count as well). Borrowed rows load only
 * while the toggle is ON and the borrowing module is effective
 * — with borrowing off there is nothing to include, so the
 * toggle itself hides.
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
      <div role="cell">
        <span className="tv-maint-problem" title={problem}>
          {problem}
        </span>
      </div>
      <div role="cell">
        {checkout.checked_out_at
          ? fullDate(checkout.checked_out_at.slice(0, 10))
          : "—"}
      </div>
      <div role="cell">
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
}: {
  entries: OutOfServiceEntry[] | null;
  error: string | null;
  borrowingOn: boolean;
}) {
  const t = useT();
  const [includeBorrowed, setIncludeBorrowed] = useState(false);
  const [lentOut, setLentOut] = useState<Checkout[] | null>(null);
  const [borrowedError, setBorrowedError] = useState(false);
  // The layout blocks as loaded, so a toggle save preserves any
  // other block the page key ever gains.
  const blocksRef = useRef<LayoutBlock[]>([]);

  // Hydrate the remembered choice (starts OFF until it loads).
  useEffect(() => {
    let cancelled = false;
    api<{ blocks: LayoutBlock[] }>("/core/layouts/repairs")
      .then((layout) => {
        if (cancelled) return;
        blocksRef.current = layout.blocks ?? [];
        const block = blocksRef.current.find((b) => b.key === BLOCK_KEY);
        if (block?.settings?.include_borrowed === true) {
          setIncludeBorrowed(true);
        }
      })
      .catch(() => {
        // No stored layout (or unreadable): the toggle just
        // starts OFF, as specified.
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
    if (!includeBorrowed || !borrowingOn || lentOut !== null) return;
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
  }, [includeBorrowed, borrowingOn, lentOut]);

  const board = entries ?? [];
  const borrowedRows = includeBorrowed && borrowingOn ? (lentOut ?? []) : [];
  const showTable = board.length > 0 || borrowedRows.length > 0;

  return (
    <div>
      {borrowingOn && (
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
                cols={["Item", "Problem", "Since", "Status", null]}
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
