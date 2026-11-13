import { useEffect, useState } from "react";
import {
  Button,
  DatePicker,
  FormField,
  Select,
  TextInput,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { todayLocalIso } from "../../../lib/format";
import type { Battery, Tool } from "../types";
import "../itemPage.css";

/**
 * The mark-replaced form: date (defaults today), a searchable
 * picker over the owner's OTHER tools + batteries, optional
 * note. Submitting stamps replaced_on + the optional successor
 * + note via POST /inventory/{segment}/{id}/replaced — a
 * history marker, not a retirement (the item stays in the
 * active set). Rendered inside the Actions menu's modal
 * (ItemActionsMenu); it used to live in the history panel
 * before the owner moved the control to the header (audit tab
 * read-only, 2026-10-31) and then into the Actions dropdown.
 */
export function ReplacedForm({
  segment,
  itemId,
  toast,
  onCancel,
  onDone,
}: {
  segment: string;
  itemId: string;
  toast: (
    message: string,
    options?: { tone?: "info" | "success" | "warning" | "danger" },
  ) => void;
  onCancel: () => void;
  onDone: () => void;
}) {
  const [replacedOn, setReplacedOn] = useState(() => todayLocalIso());
  const [filter, setFilter] = useState("");
  const [options, setOptions] = useState<{ id: string; name: string }[]>([]);
  const [replacedBy, setReplacedBy] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [tools, batteries] = await Promise.all([
          api<Tool[]>("/inventory?limit=1000"),
          api<Battery[]>("/inventory/batteries?limit=1000"),
        ]);
        if (cancelled) return;
        setOptions(
          [
            ...tools
              .filter((t) => t.id !== itemId)
              .map((t) => ({ id: t.id, name: `${t.name} (tool)` })),
            ...batteries
              .filter((b) => b.id !== itemId)
              .map((b) => ({ id: b.id, name: `${b.name} (battery)` })),
          ].sort((a, b) => a.name.localeCompare(b.name)),
        );
      } catch (err) {
        if (!cancelled)
          toast(
            err instanceof ApiError ? err.message : "Couldn't list your items.",
            { tone: "danger" },
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [itemId, toast]);

  const filtered = options.filter((o) =>
    o.name.toLowerCase().includes(filter.trim().toLowerCase()),
  );

  const onSave = async () => {
    setSaving(true);
    try {
      await api(`/inventory/${segment}/${itemId}/replaced`, {
        method: "POST",
        body: JSON.stringify({
          replaced_on: replacedOn || null,
          replaced_by_item_id: replacedBy || null,
          note,
        }),
      });
      toast("Marked replaced.", { tone: "success" });
      onDone();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save it.",
        { tone: "danger" },
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="tv-replaced-form">
      <FormField label="Replacement date">
        <DatePicker
          value={replacedOn}
          onChange={setReplacedOn}
          clearable
        />
      </FormField>
      <FormField label="Replacement item (optional)">
        <TextInput
          placeholder="Type to search your tools and batteries…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </FormField>
      <FormField label="Pick the replacement">
        <Select
          value={replacedBy}
          onChange={(e) => setReplacedBy(e.target.value)}
          disabled={loading}
        >
          <option value="">None — no successor recorded</option>
          {filtered.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </Select>
      </FormField>
      <FormField label="Note (optional)">
        <TextInput
          placeholder="e.g. Warranty swap"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </FormField>
      <div className="tv-replaced-actions">
        <Button variant="primary" onClick={onSave} loading={saving}>
          {saving ? "Saving…" : "Mark replaced"}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
