import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Panel, useToast } from "../../../components";
import { ApiError } from "../../../lib/api";
import {
  approveCheckout,
  declineCheckout,
  getItemLending,
  returnCheckout,
} from "../api";
import { STATE_TONES, standingText } from "../format";
import type { CheckoutItemKind, ItemLending } from "../types";
import { CheckoutModal, type CheckoutTarget } from "./CheckoutModal";
import { LendingHistoryList } from "./LendingHistoryList";

/**
 * The lending block on a tool/battery detail page, in three
 * separated parts (owner, 2026-11-12 — they used to blend into
 * one another): STATUS: with the item's current standing as a
 * chip ("Checked out to Nate · due Oct 30" / "Requested by
 * Bob") and the actions that belong to it (check out,
 * approve/decline a pending request, mark returned); NOTES:
 * with the current (or most recent) loan's notes — the notes
 * the Borrowing lists no longer face; then the lending history
 * in its own box below, a Main list layout list.
 *
 * Best-effort by design, like the batteries-in-tool panel beside
 * it: if the borrowing module isn't effective for this user (403
 * module_unavailable) — or the read fails — the panel renders
 * nothing and the item page stands on its own.
 */
export function LendingPanel({
  itemKind,
  itemId,
  itemName,
  itemActive,
  isSet,
  onChanged,
  onUnavailable,
}: {
  itemKind: CheckoutItemKind;
  itemId: string;
  itemName: string;
  /** Entitlement standing: false = over the plan limit. Inactive
   *  items can't START a lend (the server enforces it too), so the
   *  Check out button hides — an item already out can still be
   *  marked returned from here. */
  itemActive?: boolean;
  /** Sets get the "include addon pieces?" checkout prompt. */
  isSet?: boolean;
  /** Fired after any successful lend change (checkout, approve,
   *  decline, return) — the item page's status strip listens,
   *  since a lend never touches the item row itself. */
  onChanged?: () => void;
  /** Fired when the panel hides itself (the read failed — the
   *  module isn't effective for this viewer). The Borrowing tab
   *  that hosts the panel drops itself on this signal, so the
   *  tab vanishes exactly when the panel would have. */
  onUnavailable?: () => void;
}) {
  const { toast } = useToast();
  const [lending, setLending] = useState<ItemLending | null>(null);
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [checkingOut, setCheckingOut] = useState(false);

  const load = useCallback(() => {
    getItemLending(itemKind, itemId)
      .then(setLending)
      .catch(() => {
        setHidden(true);
        onUnavailable?.();
      });
  }, [itemKind, itemId, onUnavailable]);

  useEffect(load, [load]);

  // Memoized: the modal keys its one-time initialization on
  // this object's identity staying stable across re-renders.
  // (Above the early return — hooks run unconditionally.)
  const target: CheckoutTarget = useMemo(
    () => ({
      kind: itemKind,
      id: itemId,
      name: itemName,
      isSet: Boolean(isSet),
    }),
    [itemKind, itemId, itemName, isSet],
  );

  if (hidden || lending === null) return null;

  const current = lending.current;

  async function act(id: string, action: "approve" | "decline" | "return") {
    setBusy(id);
    try {
      if (action === "approve") await approveCheckout(id);
      else if (action === "decline") await declineCheckout(id);
      else await returnCheckout(id);
      toast(
        action === "approve"
          ? "Request approved — it's checked out now."
          : action === "decline"
            ? "Request declined."
            : "Marked returned — the item is back in your vault.",
        { tone: "success", title: "Borrowing" },
      );
      load();
      onChanged?.();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "That didn't work. Try again.",
        { tone: "danger" },
      );
    } finally {
      setBusy(null);
    }
  }

  // The NOTES section speaks for the current loan; with nothing
  // out, it speaks for the most recent loan the ledger holds —
  // history is newest-first and includes every lend.
  const notesRow = current ?? lending.history[0] ?? null;

  return (
    <Panel title="Borrowing">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <div style={{ display: "grid", gap: "0.45rem" }}>
          <p className="tv-bw-lend-label">Status:</p>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "1rem",
              flexWrap: "wrap",
            }}
          >
            {current ? (
              <Badge tone={current.overdue ? "danger" : STATE_TONES[current.state]} dot>
                {standingText(current)}
              </Badge>
            ) : (
              <span style={{ color: "var(--text-muted)" }}>
                Not lent out — it's in your vault.
              </span>
            )}
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {!current && itemActive !== false && (
                <Button type="button" size="sm" onClick={() => setCheckingOut(true)}>
                  Check out
                </Button>
              )}
              {current?.state === "requested" && (
                <>
                  <Button
                    type="button"
                    size="sm"
                    loading={busy === current.id}
                    onClick={() => void act(current.id, "approve")}
                  >
                    Approve
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={busy === current.id}
                    onClick={() => void act(current.id, "decline")}
                  >
                    Decline
                  </Button>
                </>
              )}
              {current?.state === "checked_out" && (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  loading={busy === current.id}
                  onClick={() => void act(current.id, "return")}
                >
                  Mark returned
                </Button>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gap: "0.45rem" }}>
          <p className="tv-bw-lend-label">Notes:</p>
          {notesRow?.notes ? (
            <p style={{ margin: 0 }}>“{notesRow.notes}”</p>
          ) : (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>No notes</p>
          )}
        </div>

        <div style={{ display: "grid", gap: "0.45rem" }}>
          <p className="tv-bw-lend-label">Lending history</p>
          <LendingHistoryList
            variant="item"
            rows={lending.history.slice(0, 8)}
            emptyText="This item has never been lent out."
          />
          {lending.history.length > 8 && (
            <Link to="/borrowing#history" style={{ color: "var(--accent)" }}>
              See the full history in Borrowing →
            </Link>
          )}
        </div>
      </div>

      <CheckoutModal
        target={checkingOut ? target : null}
        onClose={() => setCheckingOut(false)}
        onDone={(checkout) => {
          setCheckingOut(false);
          toast(`“${itemName}” is checked out to ${checkout.borrower_name}.`, {
            tone: "success",
            title: "Checked out",
          });
          load();
          onChanged?.();
        }}
      />
    </Panel>
  );
}
