import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  DatePicker,
  FormField,
  Panel,
  QuietSkeleton,
  TextInput,
  useToast,
} from "../../../components";
import { api, ApiError, TOKEN_KEY } from "../../../lib/api";
import { todayLocalIso } from "../../../lib/format";
import { displayDate, money } from "../format";
import type { SaleRecord } from "../types";

/**
 * The Sale panel (wave 2, sold tracking): Mark sold + this
 * item's sale history + the for-sale poster, shown in its own
 * modal window on the tool and battery detail pages (owner
 * correction, 2026-10-31 — it no longer sits in the Details
 * tab). A FULL sale flips the item's standing to sold (it
 * leaves the plan's active set); a partial sale of a quantity
 * records the portion and reduces the count. Sales are never
 * edited — Undo writes a reversal and restores the item, and
 * both events stay in the item's history.
 */
/** The panel's frame, dropped when the panel rides inside a
 *  Modal — the modal supplies the title there. */
function SaleFrame({
  bare,
  children,
}: {
  bare?: boolean;
  children: React.ReactNode;
}) {
  if (bare) return <>{children}</>;
  return <Panel title="Sale">{children}</Panel>;
}

export function SalesPanel({
  itemKind,
  itemId,
  itemName,
  quantity,
  standing,
  isAttachedAddon,
  onChanged,
  bare,
  startWithForm,
}: {
  itemKind: "tool" | "battery";
  itemId: string;
  itemName: string;
  quantity: number;
  standing: string;
  isAttachedAddon?: boolean;
  onChanged: () => void;
  /** Render without the Panel frame (inside the item page's
   *  sale modal window). */
  bare?: boolean;
  /** Open with the record-a-sale form already showing (the
   *  Actions menu's "Mark sold" entry; "Sale details" leaves
   *  it closed). */
  startWithForm?: boolean;
}) {
  const { toast } = useToast();
  const [records, setRecords] = useState<SaleRecord[] | null>(null);
  const [showForm, setShowForm] = useState(startWithForm ?? false);
  const [qty, setQty] = useState("");
  const [buyer, setBuyer] = useState("");
  const [contact, setContact] = useState("");
  const [price, setPrice] = useState("");
  /* A new sale starts on today (owner's date rule, 2026-11-04);
   * clearable back to null, as the field allowed before. */
  const [soldOn, setSoldOn] = useState(() => todayLocalIso());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [posterPrice, setPosterPrice] = useState("");
  const [posterBusy, setPosterBusy] = useState(false);

  const sold = standing === "sold";

  const refresh = useCallback(() => {
    api<SaleRecord[]>(`/inventory/sales?item_id=${itemId}`)
      .then(setRecords)
      .catch(() => setRecords([]));
  }, [itemId]);

  useEffect(refresh, [refresh]);

  async function submitSale() {
    if (price === "") return;
    setBusy(true);
    try {
      const path =
        itemKind === "tool"
          ? `/inventory/tools/${itemId}/mark-sold`
          : `/inventory/batteries/${itemId}/mark-sold`;
      await api(path, {
        method: "POST",
        body: JSON.stringify({
          quantity_sold: qty === "" ? null : Number(qty),
          buyer_name: buyer.trim(),
          buyer_contact: contact.trim(),
          sale_price: price,
          sold_on: soldOn || null,
          note: note.trim(),
        }),
      });
      toast(`“${itemName}” recorded as sold.`);
      setShowForm(false);
      setQty("");
      setBuyer("");
      setContact("");
      setPrice("");
      setSoldOn(todayLocalIso());
      setNote("");
      refresh();
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't record that sale.", { tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function undo(record: SaleRecord) {
    if (
      !window.confirm(
        "Undo this sale? The item comes back and a reversal is written to the ledger — the sale stays in the history.",
      )
    )
      return;
    setBusy(true);
    try {
      await api(`/inventory/sales/${record.id}/undo`, { method: "POST" });
      toast("Sale undone — the reversal is on the ledger.");
      refresh();
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't undo that sale.", { tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function downloadPoster() {
    setPosterBusy(true);
    try {
      // POST + binary body: the reports export download's shape
      // (raw fetch with the stored token — api() is JSON-only).
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch("/api/inventory/sales/poster", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          items: [
            {
              item_kind: itemKind,
              item_id: itemId,
              price: posterPrice === "" ? null : posterPrice,
              listing_url: "",
            },
          ],
        }),
      });
      if (!response.ok) {
        throw new Error(`Poster failed (${response.status}).`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "for-sale-poster.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't build the poster.", { tone: "danger" });
    } finally {
      setPosterBusy(false);
    }
  }

  const liveSales = (records ?? []).filter((r) => r.kind === "sale" && !r.reversed);

  return (
    <SaleFrame bare={bare}>
      <div style={{ display: "grid", gap: "0.75rem" }}>
        {sold && (
          <Alert tone="info">
            This item is <strong>sold</strong> — it no longer counts
            against your plan and it's hidden from sharing. Its record
            and history stay here, and Undo (below) brings it back if
            the sale falls through.
          </Alert>
        )}
        {isAttachedAddon && !sold && (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            This tool rides inside a set — detach it from the set first,
            or sell the set itself.
          </p>
        )}
        {!sold && !isAttachedAddon && !showForm && (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Button variant="secondary" onClick={() => setShowForm(true)}>
              Mark sold
            </Button>
          </div>
        )}
        {!sold && !isAttachedAddon && showForm && (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                gap: "0.75rem",
              }}
            >
              {quantity > 1 && (
                <FormField
                  label={`How many? (of ${quantity})`}
                  htmlFor="sale-qty"
                  hint="Leave blank to sell them all."
                >
                  <TextInput
                    id="sale-qty"
                    inputMode="numeric"
                    value={qty}
                    onChange={(e) => setQty(e.target.value)}
                    placeholder={String(quantity)}
                  />
                </FormField>
              )}
              <FormField label="Sale price (total)" htmlFor="sale-price">
                <TextInput
                  id="sale-price"
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="0.00"
                />
              </FormField>
              <FormField label="Date sold" htmlFor="sale-date">
                <DatePicker
                  id="sale-date"
                  value={soldOn}
                  onChange={setSoldOn}
                  clearable
                />
              </FormField>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: "0.75rem",
              }}
            >
              <FormField label="Buyer (optional)" htmlFor="sale-buyer">
                <TextInput
                  id="sale-buyer"
                  value={buyer}
                  onChange={(e) => setBuyer(e.target.value)}
                />
              </FormField>
              <FormField label="Buyer contact (optional)" htmlFor="sale-contact">
                <TextInput
                  id="sale-contact"
                  value={contact}
                  onChange={(e) => setContact(e.target.value)}
                />
              </FormField>
            </div>
            <FormField label="Note (optional)" htmlFor="sale-note">
              <TextInput
                id="sale-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </FormField>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <Button loading={busy} onClick={() => void submitSale()} disabled={price === ""}>
                Record the sale
              </Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {records === null ? (
          <QuietSkeleton lines={2} />
        ) : records.length > 0 ? (
          <div style={{ display: "grid", gap: "0.4rem" }}>
            <p style={{ margin: 0, fontWeight: 600 }}>Sale history</p>
            {records.map((record) => (
              <div
                key={record.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "1rem",
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <p style={{ margin: 0 }}>
                  {record.kind === "reversal" ? (
                    <Badge tone="neutral">Sale undone</Badge>
                  ) : record.reversed ? (
                    <Badge tone="neutral">Sold (undone)</Badge>
                  ) : (
                    <Badge tone="success">Sold</Badge>
                  )}{" "}
                  {displayDate(record.sold_on)} · {money(record.sale_price)}
                  {record.quantity_sold > 1 && <> · {record.quantity_sold} units</>}
                  {record.buyer_name && <> · to {record.buyer_name}</>}
                  {record.note && (
                    <span style={{ color: "var(--text-muted)" }}> — {record.note}</span>
                  )}
                </p>
                {record.kind === "sale" && !record.reversed && (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busy}
                    onClick={() => void undo(record)}
                  >
                    Undo sale
                  </Button>
                )}
              </div>
            ))}
          </div>
        ) : (
          !sold && (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              No sales recorded for this item yet.
            </p>
          )
        )}

        {!sold && (
          <div
            style={{
              display: "flex",
              gap: "0.5rem",
              alignItems: "end",
              flexWrap: "wrap",
              borderTop: "1px solid var(--border, rgba(127,127,127,0.2))",
              paddingTop: "0.75rem",
            }}
          >
            <FormField
              label="For-sale poster price"
              htmlFor="poster-price"
              hint="Prints a one-page poster with the photo, price and a QR to your public profile."
            >
              <TextInput
                id="poster-price"
                inputMode="decimal"
                value={posterPrice}
                onChange={(e) => setPosterPrice(e.target.value)}
                placeholder="Asking price"
              />
            </FormField>
            <Button
              variant="secondary"
              loading={posterBusy}
              onClick={() => void downloadPoster()}
            >
              Print for-sale poster (PDF)
            </Button>
            {liveSales.length > 0 && (
              <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                Partially sold — the poster advertises what's left.
              </span>
            )}
          </div>
        )}
      </div>
    </SaleFrame>
  );
}
