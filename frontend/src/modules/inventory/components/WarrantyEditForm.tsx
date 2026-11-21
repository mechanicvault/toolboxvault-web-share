import { useState, type FormEvent } from "react";
import { Button, useToast } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { WarrantyFields, type WarrantyField, type WarrantyValues } from "./WarrantyFields";
import "../itemPage.css";

/**
 * The Warranty tab's in-place editor (sheet rows, 2026-11-15):
 * Ryan's complaint was that the tab showed the warranty but
 * offered "no options for anything" — editing meant leaving for
 * Actions → Edit and hunting the warranty section of the full
 * form. The tab now edits IN PLACE: the same WarrantyFields
 * group the item forms use, saved through the items' partial
 * PUT (the backend applies only the fields sent), then the page
 * refreshes and the tab is back to its read view.
 *
 * One component serves tools and batteries so the two tabs
 * cannot drift.
 */

/** The "Warranty ends" countdown suffix (sheet row, 2026-11-15):
 *  the end date alone wasn't enough — the tab also says how
 *  long is left, or how long ago it ran out. */
export function warrantyCountdown(endDate: string | null): string | null {
  if (!endDate) return null;
  const [y, m, d] = endDate.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  const end = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((end.getTime() - today.getTime()) / 86_400_000);
  if (days > 1) return `${days} days left`;
  if (days === 1) return "1 day left";
  if (days === 0) return "ends today";
  if (days === -1) return "expired yesterday";
  return `expired ${-days} days ago`;
}

export interface WarrantyItem {
  warranty_months: number | null;
  warranty_provider: string;
  warranty_contact: string;
  warranty_terms: string;
  warranty_type: string | null;
}

export function WarrantyEditForm({
  segment,
  itemId,
  item,
  onSaved,
  onCancel,
}: {
  segment: "tools" | "batteries";
  itemId: string;
  item: WarrantyItem;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { toast } = useToast();
  const [values, setValues] = useState<WarrantyValues>({
    warranty_months: item.warranty_months != null ? String(item.warranty_months) : "",
    warranty_provider: item.warranty_provider ?? "",
    warranty_contact: item.warranty_contact ?? "",
    warranty_terms: item.warranty_terms ?? "",
    warranty_type: item.warranty_type ?? "",
  });
  const [busy, setBusy] = useState(false);

  function onChange(field: WarrantyField, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const path =
        segment === "batteries"
          ? `/inventory/batteries/${itemId}`
          : `/inventory/${itemId}`;
      await api(path, {
        method: "PUT",
        body: JSON.stringify({
          warranty_months:
            values.warranty_months === "" ? null : Number(values.warranty_months),
          warranty_provider: values.warranty_provider.trim(),
          warranty_contact: values.warranty_contact.trim(),
          warranty_terms: values.warranty_terms.trim(),
          warranty_type: values.warranty_type === "" ? null : values.warranty_type,
        }),
      });
      toast("Warranty saved.", { tone: "success", title: "Warranty" });
      onSaved();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save the warranty.", {
        tone: "danger",
      });
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void onSave(e)} className="tv-warranty-edit-form">
      <WarrantyFields
        idPrefix={`warranty-tab-${segment}`}
        values={values}
        onChange={onChange}
        dealerCompany={null}
        dealerKnown={false}
        resetKey={itemId}
      />
      <div className="tv-warranty-edit-actions">
        <Button type="submit" size="sm" loading={busy}>
          Save warranty
        </Button>
        <Button type="button" size="sm" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
