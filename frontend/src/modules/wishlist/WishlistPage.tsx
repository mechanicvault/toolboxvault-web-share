import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  DatePicker,
  EmptyState,
  FormField,
  ItemThumb,
  Modal,
  Panel,
  SearchBar,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  LinkButton,
} from "../../components";
import { ApiError } from "../../lib/api";
import { todayLocalIso } from "../../lib/format";
import { RequireAuth } from "../core";
import { DealerPicker } from "../dealers/components/DealerFields";
import { money } from "../inventory/format";
import { photoFileError } from "../inventory/components/photoTransfer";
import {
  convertToTool,
  createWishlistItem,
  deleteWishlistItem,
  listWishlist,
  markPurchased,
  updateWishlistItem,
} from "./api";
import type { WishlistItem, WishlistPriority } from "./types";
import { uploadPhotoFile } from "../inventory/components/photoTransfer";

/**
 * The Wishlist (wave 2, 2026-10-20): the want-list — tools you
 * plan to buy, with the link, target price, priority and dealer
 * for each. Buying one is a two-step: mark it purchased with the
 * price actually paid + the date, then Convert to Tool carries
 * those facts into Asset Inventory so the new tool's history
 * starts true. Wishlist items never count against the plan's
 * item limit — they are plans, not assets.
 */

const PRIORITY_TONES: Record<WishlistPriority, "danger" | "warning" | "neutral"> = {
  high: "danger",
  normal: "warning",
  low: "neutral",
};

interface Draft {
  title: string;
  link_url: string;
  target_price: string;
  priority: WishlistPriority;
  dealer_company_id: string;
  notes: string;
}

const EMPTY_DRAFT: Draft = {
  title: "",
  link_url: "",
  target_price: "",
  priority: "normal",
  dealer_company_id: "",
  notes: "",
};

function draftOf(item: WishlistItem): Draft {
  return {
    title: item.title,
    link_url: item.link_url,
    target_price: item.target_price ?? "",
    priority: item.priority,
    dealer_company_id: item.dealer_company_id ?? "",
    notes: item.notes,
  };
}

export default function WishlistPage() {
  const { toast } = useToast();
  const [items, setItems] = useState<WishlistItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<WishlistItem | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [dealerAvailable, setDealerAvailable] = useState(true);
  const [saving, setSaving] = useState(false);
  const [buying, setBuying] = useState<WishlistItem | null>(null);
  const [paidPrice, setPaidPrice] = useState("");
  const [paidDate, setPaidDate] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);

  const refresh = useCallback(() => {
    listWishlist(query.trim() || undefined)
      .then(setItems)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load your wishlist."),
      );
  }, [query]);

  useEffect(() => {
    const t = setTimeout(refresh, 250);
    return () => clearTimeout(t);
  }, [refresh]);

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(item: WishlistItem) {
    setDraft(draftOf(item));
    setEditing(item);
  }

  async function save() {
    if (!draft.title.trim()) return;
    setSaving(true);
    try {
      const body = {
        title: draft.title.trim(),
        link_url: draft.link_url.trim(),
        target_price: draft.target_price === "" ? null : draft.target_price,
        priority: draft.priority,
        dealer_company_id: dealerAvailable
          ? draft.dealer_company_id || null
          : undefined,
        notes: draft.notes,
      };
      if (editing === "new") {
        const created = await createWishlistItem({
          title: body.title,
          link_url: body.link_url,
          target_price: body.target_price,
          priority: body.priority,
          dealer_company_id: body.dealer_company_id ?? null,
          notes: body.notes,
        });
        toast(`“${created.title}” is on your wishlist.`);
      } else if (editing) {
        await updateWishlistItem(editing.id, body);
        toast("Wishlist updated.");
      }
      setEditing(null);
      refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save that item.", { tone: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function onPhoto(item: WishlistItem, file: File) {
    const problem = photoFileError(file);
    if (problem) {
      toast(problem, { tone: "danger" });
      return;
    }
    setPhotoBusy(true);
    try {
      await uploadPhotoFile(`/wishlist/items/${item.id}`, file);
      refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That photo didn't upload.", { tone: "danger" });
    } finally {
      setPhotoBusy(false);
    }
  }

  async function confirmPurchase() {
    if (!buying || paidPrice === "") return;
    setBusyId(buying.id);
    try {
      await markPurchased(buying.id, {
        purchased_price: paidPrice,
        purchased_on: paidDate || null,
      });
      toast(`“${buying.title}” marked purchased. Convert it whenever you're ready.`);
      setBuying(null);
      setPaidPrice("");
      setPaidDate("");
      refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't mark that purchased.", { tone: "danger" });
    } finally {
      setBusyId(null);
    }
  }

  async function onConvert(item: WishlistItem) {
    setBusyId(item.id);
    try {
      const result = await convertToTool(item.id);
      toast(`“${item.title}” is now in your Inventory.`);
      setItems((rows) =>
        (rows ?? []).map((r) => (r.id === item.id ? result.item : r)),
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't convert that item.", { tone: "danger" });
    } finally {
      setBusyId(null);
    }
  }

  async function onDelete(item: WishlistItem) {
    if (!window.confirm(`Remove “${item.title}” from your wishlist?`)) return;
    setBusyId(item.id);
    try {
      await deleteWishlistItem(item.id);
      setItems((rows) => (rows ?? []).filter((r) => r.id !== item.id));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't remove that item.", { tone: "danger" });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <RequireAuth>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
            flexWrap: "wrap",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "1.6rem" }}>Wishlist</h1>
          <Button onClick={openNew}>Add to wishlist</Button>
        </div>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          The tools you're planning to buy. When you buy one, mark it
          purchased with the real price and date — converting it to a
          tool carries those facts into your inventory.
        </p>

        {error && <Alert tone="danger">{error}</Alert>}

        <SearchBar
          value={query}
          onChange={setQuery}
          placeholder="Search your wishlist…"
          ariaLabel="Search your wishlist"
        />

        {items === null ? (
          <p style={{ color: "var(--text-muted)", display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <Spinner size="sm" /> Loading…
          </p>
        ) : items.length === 0 ? (
          <EmptyState
            title={query ? "Nothing matches" : "Your wishlist is empty"}
            description={
              query
                ? "Try a different search."
                : "Add the next tool you're saving for — a link and a target price are all it takes."
            }
            action={
              !query ? <Button onClick={openNew}>Add to wishlist</Button> : undefined
            }
          />
        ) : (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {items.map((item) => {
              const photo = item.attachments.find((a) => a.kind === "photo");
              return (
                <Panel key={item.id}>
                  <div
                    style={{
                      display: "flex",
                      gap: "1rem",
                      alignItems: "flex-start",
                      flexWrap: "wrap",
                    }}
                  >
                    <ItemThumb
                      fill
                      sizeClass="tv-thumb--s76"
                      src={photo?.url ?? null}
                      name={item.title}
                    />
                    <div style={{ flex: 1, minWidth: 220, display: "grid", gap: "0.3rem" }}>
                      <p style={{ margin: 0, display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                        <strong>{item.title}</strong>
                        <Badge tone={PRIORITY_TONES[item.priority]} dot>
                          {item.priority} priority
                        </Badge>
                        {item.status === "purchased" && (
                          <Badge tone="success">Purchased</Badge>
                        )}
                        {item.converted_tool_id && (
                          <Badge tone="accent">In inventory</Badge>
                        )}
                      </p>
                      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
                        {item.target_price !== null && (
                          <>Target {money(item.target_price)} · </>
                        )}
                        {item.dealer_name && <>From {item.dealer_name} · </>}
                        {item.status === "purchased" && item.purchased_price !== null && (
                          <>Paid {money(item.purchased_price)}</>
                        )}
                      </p>
                      {item.notes && (
                        <p style={{ margin: 0, fontSize: "0.9rem" }}>{item.notes}</p>
                      )}
                      {item.link_url && (
                        <p style={{ margin: 0 }}>
                          <a
                            href={item.link_url}
                            target="_blank"
                            rel="noreferrer"
                            style={{ color: "var(--accent)", fontWeight: 600 }}
                          >
                            View the listing →
                          </a>
                        </p>
                      )}
                    </div>
                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                      {item.status === "wanted" && (
                        <Button
                          size="sm"
                          loading={busyId === item.id}
                          onClick={() => {
                            setBuying(item);
                            setPaidPrice(item.target_price ?? "");
                            setPaidDate(todayLocalIso());
                          }}
                        >
                          Mark purchased
                        </Button>
                      )}
                      {item.status === "purchased" && !item.converted_tool_id && (
                        <Button
                          size="sm"
                          loading={busyId === item.id}
                          onClick={() => void onConvert(item)}
                        >
                          Convert to tool
                        </Button>
                      )}
                      {item.converted_tool_id && (
                        <LinkButton to={`/inventory/${item.converted_tool_id}`} size="sm" variant="secondary">Open the tool</LinkButton>
                      )}
                      <Button size="sm" variant="secondary" onClick={() => openEdit(item)}>
                        Edit
                      </Button>
                      <label
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          cursor: photoBusy ? "wait" : "pointer",
                        }}
                      >
                        <Button size="sm" variant="secondary" disabled={photoBusy}>
                          {photo ? "Replace photo" : "Add photo"}
                        </Button>
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          hidden
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) void onPhoto(item, file);
                            e.target.value = "";
                          }}
                        />
                      </label>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busyId === item.id}
                        onClick={() => void onDelete(item)}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                </Panel>
              );
            })}
          </div>
        )}
      </div>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Add to wishlist" : "Edit wishlist item"}
      >
        <div style={{ display: "grid", gap: "0.75rem" }}>
          <FormField label="What do you want?" htmlFor="wish-title">
            <TextInput
              id="wish-title"
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="e.g. 1/2in cordless impact wrench"
            />
          </FormField>
          <FormField
            label="Link (optional)"
            htmlFor="wish-link"
            hint="Where you saw it — a product page, a truck catalog, anywhere."
          >
            <TextInput
              id="wish-link"
              value={draft.link_url}
              onChange={(e) => setDraft({ ...draft, link_url: e.target.value })}
              placeholder="https://…"
            />
          </FormField>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <FormField label="Target price" htmlFor="wish-target">
              <TextInput
                id="wish-target"
                inputMode="decimal"
                value={draft.target_price}
                onChange={(e) => setDraft({ ...draft, target_price: e.target.value })}
                placeholder="0.00"
              />
            </FormField>
            <FormField label="Priority" htmlFor="wish-priority">
              <Select
                id="wish-priority"
                value={draft.priority}
                onChange={(e) =>
                  setDraft({ ...draft, priority: e.target.value as WishlistPriority })
                }
              >
                <option value="high">High</option>
                <option value="normal">Normal</option>
                <option value="low">Low</option>
              </Select>
            </FormField>
          </div>
          <DealerPicker
            id="wish-dealer"
            value={draft.dealer_company_id}
            onChange={(companyId) => setDraft({ ...draft, dealer_company_id: companyId })}
            onAvailability={setDealerAvailable}
            label="Dealer / brand (optional)"
          />
          <FormField label="Notes" htmlFor="wish-notes">
            <TextArea
              id="wish-notes"
              value={draft.notes}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
              rows={3}
            />
          </FormField>
          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void save()} disabled={!draft.title.trim()}>
              {editing === "new" ? "Add to wishlist" : "Save changes"}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={buying !== null}
        onClose={() => setBuying(null)}
        title={buying ? `Bought “${buying.title}”?` : "Mark purchased"}
      >
        <div style={{ display: "grid", gap: "0.75rem" }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            Record what you actually paid and when — converting to a tool
            carries both into your inventory, so the tool's value history
            starts true.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <FormField label="Price paid" htmlFor="wish-paid">
              <TextInput
                id="wish-paid"
                inputMode="decimal"
                value={paidPrice}
                onChange={(e) => setPaidPrice(e.target.value)}
                placeholder="0.00"
              />
            </FormField>
            <FormField label="Date purchased" htmlFor="wish-paid-date">
              <DatePicker
                id="wish-paid-date"
                value={paidDate}
                onChange={setPaidDate}
                clearable
              />
            </FormField>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setBuying(null)}>
              Not yet
            </Button>
            <Button
              loading={busyId === buying?.id}
              onClick={() => void confirmPurchase()}
              disabled={paidPrice === ""}
            >
              Mark purchased
            </Button>
          </div>
        </div>
      </Modal>
    </RequireAuth>
  );
}
