import { useEffect, useState } from "react";
import { Button, FormField, Select } from "../../../components";
import { api } from "../../../lib/api";
import { money } from "../format";
import type { AttachedToolRef, Tool } from "../types";

/** One picked inventory tool in the entry flows, with its display
 *  line precomputed (name + brand/model + its own price). */
export interface AttachedPick {
  id: string;
  name: string;
  detail: string;
}

function detailOf(parts: (string | null | undefined | false)[]): string {
  return parts.filter(Boolean).join(" · ");
}

export function pickFromAttached(t: AttachedToolRef): AttachedPick {
  return {
    id: t.id,
    name: t.name,
    detail: detailOf([
      t.brand,
      t.model,
      t.purchase_total ? money(t.purchase_total) : null,
    ]),
  };
}

export function pickFromTool(t: Tool): AttachedPick {
  return {
    id: t.id,
    name: t.name,
    detail: detailOf([
      t.brand,
      t.model,
      t.purchase_price ? money(t.purchase_price) : null,
      t.quantity > 1 ? `×${t.quantity}` : null,
    ]),
  };
}

/**
 * "Pieces from your inventory" — the build-a-set picker for the
 * entry flows (the tool form's inline set editor + the Add
 * wizard's set page; owner 2026-10-25). Pick standalone tools to
 * fold INTO the set being built: the picked list rides the save as
 * `attach_tool_ids` (the desired attached set — the backend
 * attaches new picks and detaches un-picked ones). A picked tool
 * keeps ALL its data (model, serial, price, photos, documents); it
 * just lives inside the set — one inventory line, counted with the
 * set — exactly as if it had been entered as a piece from the
 * start, and un-picking restores it as a standalone item. The
 * detail page's SetPanel attaches/detaches immediately instead;
 * this picker is the same choice at entry time.
 */
export function AttachedToolsPicker({
  value,
  onChange,
  excludeId,
}: {
  value: AttachedPick[];
  onChange: (next: AttachedPick[]) => void;
  excludeId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<Tool[] | null>(null);
  const [pickId, setPickId] = useState("");

  useEffect(() => {
    if (!open) return;
    api<Tool[]>("/inventory?limit=200")
      .then((rows) =>
        setCandidates(
          rows.filter(
            (t) => !t.is_set && !t.attached_to_set_id && t.id !== excludeId,
          ),
        ),
      )
      .catch(() => setCandidates([]));
  }, [open, excludeId]);

  const pickedIds = new Set(value.map((p) => p.id));
  const available = (candidates ?? []).filter((t) => !pickedIds.has(t.id));

  function addPick() {
    const tool = available.find((t) => t.id === pickId);
    if (!tool) return;
    onChange([...value, pickFromTool(tool)]);
    setPickId("");
  }

  return (
    <div className="tv-attach-picker">
      <p className="tv-attach-picker-head">
        Pieces from your inventory{" "}
        <span>— tools you already have, folded into this set</span>
      </p>
      {value.length === 0 ? (
        <p className="tv-attach-picker-note">
          None picked. Picked tools keep all their details and count as
          part of this set — they stop listing on their own until you
          un-pick them.
        </p>
      ) : (
        value.map((pick) => (
          <div key={pick.id} className="tv-attach-pick-row">
            <p>
              <strong>{pick.name}</strong>{" "}
              {pick.detail && (
                <span className="tv-attach-pick-detail">{pick.detail}</span>
              )}
            </p>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => onChange(value.filter((p) => p.id !== pick.id))}
            >
              Un-pick
            </Button>
          </div>
        ))
      )}
      {!open ? (
        <div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => setOpen(true)}
          >
            + Pick from your inventory
          </Button>
        </div>
      ) : (
        <div className="tv-attach-picker-bar">
          <FormField label="Standalone tool to fold in">
            <Select value={pickId} onChange={(e) => setPickId(e.target.value)}>
              <option value="">Pick a tool…</option>
              {available.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {[t.brand, t.model].filter(Boolean).length > 0
                    ? ` — ${[t.brand, t.model].filter(Boolean).join(" ")}`
                    : ""}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="button" size="sm" onClick={addPick} disabled={!pickId}>
            Add to set
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => setOpen(false)}
          >
            Done
          </Button>
          {candidates !== null && available.length === 0 && (
            <p className="tv-attach-picker-note">
              No other standalone tools to pick from.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
