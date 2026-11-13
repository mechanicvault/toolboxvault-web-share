import { useCallback, useEffect, useMemo, useState } from "react";
import { useT } from "../../../i18n/LocaleContext";
import { Alert, Button, Select, TextInput } from "../../../components";
import { ApiError } from "../../../lib/api";
import type { LocationNode } from "../types";
import {
  createLocationNode,
  flattenLocationTree,
  indentedNodeLabel,
  listLocationNodes,
} from "./locationTree";
import { LocationTreeManager } from "./LocationTreeManager";
import { DrawerAutofill } from "./DrawerAutofill";
import {
  LocationTierHint,
  TIER_PLACEHOLDER_KEYS,
  locationTierForParent,
} from "./LocationTierHint";

const linkButtonStyle = {
  background: "none",
  border: "none",
  padding: 0,
  color: "var(--accent)",
  cursor: "pointer",
  fontSize: "0.85rem",
  fontWeight: 600,
} as const;

/**
 * Location tree picker (Package B): a select listing the owner's
 * location nodes indented by depth, "No location" for unfiled, an
 * inline quick-create (name + parent from the same nodes — the new
 * node is selected the moment it exists), and a "Manage
 * locations…" affordance opening the full tree manager modal.
 * Used by the item forms and the inventory list filter/bulk move.
 */
export function LocationTreePicker({
  id,
  value,
  valueLabel,
  emptyLabel = "No location",
  onChange,
  onNodesChanged,
}: {
  id?: string;
  value: string | null;
  /** Display name of the current value, when the caller already
   *  knows it (the edit forms hold the item's denormalized location
   *  string). Deep audit F1-07: while the tree is still loading —
   *  or if the node is missing from it — the select must still
   *  SHOW the item's real location, never fall back to displaying
   *  "No location" for an item that verifiably has one. */
  valueLabel?: string;
  /** Label for the empty ("") option. On item forms "" means the
   *  item is unfiled — "No location" is truthful there. In the
   *  inventory FILTER the same "" means NO filter (all locations),
   *  so the filter passes "All locations" (deep audit F5-11). */
  emptyLabel?: string;
  onChange: (locationId: string | null, node: LocationNode | null) => void;
  /** Fired after any create/manage mutation so a parent that keeps
   *  its own copy of the tree (or a filtered list) can refresh. */
  onNodesChanged?: () => void;
}) {
  const t = useT();
  const [nodes, setNodes] = useState<LocationNode[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newParentId, setNewParentId] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = useCallback(() => {
    listLocationNodes()
      .then((rows) => {
        setNodes(rows);
        setLoaded(true);
      })
      .catch(() => {
        setNodes([]);
        setLoaded(true);
      });
  }, []);

  useEffect(load, [load]);

  const flat = useMemo(() => flattenLocationTree(nodes), [nodes]);
  // The current value rendered as its own option whenever the
  // loaded tree can't speak for it yet (still loading, or the
  // node was deleted out from under the item): the select then
  // displays the truth — and picking anything else replaces it.
  const valueMissing =
    Boolean(value) && !flat.some((n) => n.id === value);

  // AI drawer autofill (2026-10-25): the confirm's Create in
  // the tier-2 quick-create — creates the toolbox, then the
  // confirmed drawers (plus any source-named sections) under
  // it, and selects the toolbox, exactly as the plain
  // quick-create lands.
  async function onQuickCreateWithDrawers(childNames: string[]) {
    const name = newName.trim();
    if (!name || !newParentId) return;
    setCreateError("");
    try {
      const toolbox = await createLocationNode({
        name,
        parent_id: newParentId,
      });
      const created: LocationNode[] = [toolbox];
      for (const [i, childName] of childNames.entries()) {
        created.push(
          await createLocationNode({
            name: childName,
            parent_id: toolbox.id,
            sort_order: i + 1,
          }),
        );
      }
      setNodes((rows) => [...rows, ...created]);
      setNewName("");
      setNewParentId("");
      setCreating(false);
      onChange(toolbox.id, toolbox);
      onNodesChanged?.();
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? err.message : "Couldn't add the location.",
      );
      throw err;
    }
  }

  async function onQuickCreate() {
    if (!newName.trim()) {
      setCreateError("Give the location a name.");
      return;
    }
    setCreateBusy(true);
    setCreateError("");
    try {
      const created = await createLocationNode({
        name: newName.trim(),
        parent_id: newParentId || null,
      });
      setNodes((rows) => [...rows, created]);
      setNewName("");
      setNewParentId("");
      setCreating(false);
      onChange(created.id, created);
      onNodesChanged?.();
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? err.message : "Couldn't add the location.",
      );
    } finally {
      setCreateBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "0.4rem" }}>
      <Select
        id={id}
        value={value ?? ""}
        disabled={!loaded}
        onChange={(e) => {
          const next = e.target.value || null;
          onChange(next, next ? (nodes.find((n) => n.id === next) ?? null) : null);
        }}
      >
        <option value="">{emptyLabel}</option>
        {valueMissing && (
          <option value={value ?? ""}>{valueLabel || "Selected location"}</option>
        )}
        {flat.map((node) => (
          <option key={node.id} value={node.id}>
            {indentedNodeLabel(node)}
          </option>
        ))}
      </Select>
      <div style={{ display: "flex", gap: "0.9rem", flexWrap: "wrap" }}>
        <button type="button" style={linkButtonStyle} onClick={() => setCreating((v) => !v)}>
          {t("inventory.newLocation")}
        </button>
        <button type="button" style={linkButtonStyle} onClick={() => setManagerOpen(true)}>
          {t("inventory.manageLocations")}
        </button>
      </div>
      {creating && (
        <div style={{ display: "grid", gap: "0.4rem" }}>
          {createError && <Alert tone="danger">{createError}</Alert>}
          {/* Tier guidance (Ryan, 2026-10-25): the quick-create
              teaches the place → storage → spot shape too — the
              helper and the name placeholder follow the parent
              picked below. */}
          <LocationTierHint flat={flat} parentId={newParentId} />
          <TextInput
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t(
              TIER_PLACEHOLDER_KEYS[locationTierForParent(flat, newParentId)],
            )}
            aria-label="New location name"
          />
          <Select
            value={newParentId}
            onChange={(e) => setNewParentId(e.target.value)}
            aria-label="New location parent"
          >
            <option value="">— Top level —</option>
            {flat.map((node) => (
              <option key={node.id} value={node.id}>
                {indentedNodeLabel(node)}
              </option>
            ))}
          </Select>
          {/* AI drawer lookup (2026-10-25): offered only
              when the picked parent is a place, so the new
              location is tier-2 storage. The block carries
              its OWN make + model box; the name above stays
              the user's own. */}
          {locationTierForParent(flat, newParentId) === 2 && (
            <DrawerAutofill
              nameText={newName}
              parentId={newParentId}
              onConfirm={onQuickCreateWithDrawers}
            />
          )}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Button
              type="button"
              size="sm"
              onClick={() => void onQuickCreate()}
              loading={createBusy}
              disabled={!newName.trim()}
            >
              Add &amp; select
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={() => setCreating(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      <LocationTreeManager
        open={managerOpen}
        onClose={() => setManagerOpen(false)}
        onChanged={() => {
          load();
          onNodesChanged?.();
        }}
      />
    </div>
  );
}
