import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Panel,
  Spinner,
  useToast,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { api, ApiError } from "../../../lib/api";
import { displayDate, money } from "../format";
import type { SaleRecord, SalesTotals } from "../types";

// Shared const (the inline-style ratchet counts literals, not
// shared style objects).
const headingStyle: CSSProperties = { margin: "0.4rem 0 0" };

/**
 * The Sold section (wave 2): the sale ledger as a view — every
 * sale + reversal, newest first, with the totals across the top.
 * Records link back to their item (a piece links to its set);
 * Undo writes a reversal (sales unwind newest-first per item).
 *
 * Home: Tools For Sale → My Listings, as its "Sold items"
 * section (owner spec 2026-10-25 — the Sold view left the
 * Inventory page; this component and its /inventory/sales
 * feed are unchanged, only the surface moved). The section
 * carries its own heading and hides itself entirely when the
 * inventory module isn't the account's to use (a dealer-,
 * insurer- or shop-only account on My Listings has no sale
 * ledger — the feed 403s module_unavailable, exactly as it
 * did when the Sold view lived on the Inventory page).
 */
export function SoldSection() {
  const t = useT();
  const { toast } = useToast();
  const [records, setRecords] = useState<SaleRecord[] | null>(null);
  const [totals, setTotals] = useState<SalesTotals | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([
      api<SaleRecord[]>("/inventory/sales"),
      api<SalesTotals>("/inventory/sales/totals"),
    ])
      .then(([rows, t]) => {
        setRecords(rows);
        setTotals(t);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.code === "module_unavailable") {
          // Not this account's section at all — render nothing
          // rather than an error (the LendingPanel pattern).
          setUnavailable(true);
          return;
        }
        setError(err instanceof ApiError ? err.message : t("inventory.sold.loadError"));
      });
  }, [t]);

  useEffect(refresh, [refresh]);

  async function undo(record: SaleRecord) {
    if (
      !window.confirm(
        t("inventory.sold.undoConfirm").replace("{name}", record.item_name),
      )
    )
      return;
    setBusyId(record.id);
    try {
      await api(`/inventory/sales/${record.id}/undo`, { method: "POST" });
      toast(t("inventory.sold.undoneToast"));
      refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("inventory.sold.undoError"), { tone: "danger" });
    } finally {
      setBusyId(null);
    }
  }

  function itemLink(record: SaleRecord): string | null {
    if (record.item_kind === "tool") return `/inventory/${record.item_id}`;
    if (record.item_kind === "battery") return `/inventory/batteries/${record.item_id}`;
    if (record.set_id) return `/inventory/${record.set_id}`;
    return null;
  }

  if (unavailable) return null;

  function body() {
    if (error) return <Alert tone="danger">{error}</Alert>;
  if (records === null) {
    return (
      <p style={{ color: "var(--text-muted)", display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <Spinner size="sm" /> {t("inventory.sold.loading")}
      </p>
    );
  }
  if (records.length === 0) {
    return (
      <EmptyState
        title={t("inventory.sold.emptyTitle")}
        description={t("inventory.sold.emptyBody")}
      />
    );
  }

  return (
    <div style={{ display: "grid", gap: "var(--spacing)" }}>
      {totals && (
        <Panel title={t("inventory.sold.totalsTitle")}>
          <p style={{ margin: 0, display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
            <span>
              {t("inventory.sold.soldValue")} <strong>{money(totals.total_sold_value)}</strong>
            </span>
            <span>
              {t("inventory.sold.sales")} <strong>{totals.sale_count}</strong>
            </span>
            <span>
              {t("inventory.sold.units")} <strong>{totals.units_sold}</strong>
            </span>
          </p>
          <p style={{ margin: "0.35rem 0 0", color: "var(--text-muted)", fontSize: "0.88rem" }}>
            {t("inventory.sold.netNote")}
          </p>
        </Panel>
      )}
      <div style={{ display: "grid", gap: "0.6rem" }}>
        {records.map((record) => {
          const link = itemLink(record);
          return (
            <Panel key={record.id}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "1rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <div style={{ display: "grid", gap: "0.2rem" }}>
                  <p style={{ margin: 0, display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                    {record.kind === "reversal" ? (
                      <Badge tone="neutral">{t("inventory.sold.badgeUndone")}</Badge>
                    ) : record.reversed ? (
                      <Badge tone="neutral">{t("inventory.sold.badgeSoldUndone")}</Badge>
                    ) : (
                      <Badge tone="success">{t("inventory.sold.badgeSold")}</Badge>
                    )}
                    {link ? (
                      <Link
                        to={link}
                        style={{ color: "var(--accent)", fontWeight: 600 }}
                      >
                        {record.item_name}
                      </Link>
                    ) : (
                      <strong>{record.item_name}</strong>
                    )}
                    {record.item_kind === "set_piece" && (
                      <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                        {t("inventory.sold.setPiece")}
                      </span>
                    )}
                  </p>
                  <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
                    {displayDate(record.sold_on)} · {money(record.sale_price)}
                    {record.quantity_sold > 1 && (
                      <> · {t("inventory.sold.unitsSuffix").replace("{count}", String(record.quantity_sold))}</>
                    )}
                    {record.buyer_name && (
                      <> · {t("inventory.sold.toBuyer").replace("{name}", record.buyer_name)}</>
                    )}
                    {record.buyer_contact && <> ({record.buyer_contact})</>}
                    {record.source === "migrated" && <> · {t("inventory.sold.fromApp")}</>}
                  </p>
                  {record.note && <p style={{ margin: 0, fontSize: "0.9rem" }}>{record.note}</p>}
                </div>
                {record.kind === "sale" && !record.reversed && (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busyId === record.id}
                    onClick={() => void undo(record)}
                  >
                    {t("inventory.sold.undoButton")}
                  </Button>
                )}
              </div>
            </Panel>
          );
        })}
      </div>
    </div>
    );
  }

  return (
    <>
      <h2 style={headingStyle}>{t("inventory.sold.heading")}</h2>
      {body()}
    </>
  );
}
