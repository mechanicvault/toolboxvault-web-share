import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  FormField,
  ItemThumb,
  Modal,
  Panel,
  SearchBar,
  Select,
  Spinner,
  TextInput,
  useToast,
  LinkButton,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import type { FieldDefinition } from "../inventory/types";
import { customValueText } from "../inventory/format";
import {
  createLocation,
  deleteLocation,
  getPoolSettings,
  listLocations,
  listParts,
  updateLocation,
  updatePoolSettings,
} from "./api";
import {
  LOCATION_LEVELS,
  levelLabel,
  type Part,
  type PartLocation,
  type PoolSettings,
} from "./types";

/**
 * Used Parts (blueprint §18): the spare-parts shelf. Search covers
 * the title, notes and every searchable custom value; the location
 * tree (the owner's own warehouse → aisle → bin) filters by subtree
 * — picking a warehouse shows everything filed under it.
 */

interface TreeNode extends PartLocation {
  children: TreeNode[];
}

function buildTree(locations: PartLocation[]): TreeNode[] {
  const byId = new Map<string, TreeNode>(
    locations.map((l) => [l.id, { ...l, children: [] }]),
  );
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sortLevel = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((n) => sortLevel(n.children));
  };
  sortLevel(roots);
  return roots;
}

/** The ids a node may NOT be moved/reassigned into: itself + its subtree. */
function subtreeIds(locations: PartLocation[], rootId: string): Set<string> {
  const children = new Map<string, string[]>();
  for (const loc of locations) {
    if (loc.parent_id) {
      const list = children.get(loc.parent_id) ?? [];
      list.push(loc.id);
      children.set(loc.parent_id, list);
    }
  }
  const found = new Set<string>();
  const stack = [rootId];
  while (stack.length > 0) {
    const id = stack.pop()!;
    if (found.has(id)) continue;
    found.add(id);
    stack.push(...(children.get(id) ?? []));
  }
  return found;
}

function TreeRows({
  nodes,
  depth,
  selectedId,
  onSelect,
  onEdit,
  onDelete,
}: {
  nodes: TreeNode[];
  depth: number;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onEdit: (loc: PartLocation) => void;
  onDelete: (loc: PartLocation) => void;
}) {
  return (
    <>
      {nodes.map((node) => (
        <div key={node.id}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              paddingLeft: `${depth * 1.1}rem`,
              paddingTop: "0.3rem",
              paddingBottom: "0.3rem",
            }}
          >
            <button
              type="button"
              onClick={() => onSelect(selectedId === node.id ? null : node.id)}
              style={{
                flex: 1,
                minWidth: 0,
                textAlign: "left",
                background: "none",
                border: "none",
                cursor: "pointer",
                color: selectedId === node.id ? "var(--accent)" : "var(--text)",
                fontWeight: selectedId === node.id ? 700 : 400,
                overflowWrap: "anywhere",
              }}
            >
              {node.name}{" "}
              <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                {levelLabel(node.level)} · {node.part_count}
              </span>
            </button>
            <Button type="button" variant="secondary" size="sm" onClick={() => onEdit(node)}>
              Edit
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={() => onDelete(node)}>
              Delete
            </Button>
          </div>
          <TreeRows
            nodes={node.children}
            depth={depth + 1}
            selectedId={selectedId}
            onSelect={onSelect}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        </div>
      ))}
    </>
  );
}

function LocationFormModal({
  locations,
  editing,
  onClose,
  onSaved,
}: {
  locations: PartLocation[];
  editing: PartLocation | "new" | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [level, setLevel] = useState("other");
  const [parentId, setParentId] = useState<string>("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (editing && editing !== "new") {
      setName(editing.name);
      setLevel(editing.level);
      setParentId(editing.parent_id ?? "");
    } else {
      setName("");
      setLevel("other");
      setParentId("");
    }
    setError("");
  }, [editing]);

  const excluded = useMemo(
    () =>
      editing && editing !== "new"
        ? subtreeIds(locations, editing.id)
        : new Set<string>(),
    [editing, locations],
  );
  const parentOptions = locations.filter((l) => !excluded.has(l.id));

  async function onSave() {
    if (!name.trim()) {
      setError("Give the location a name.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editing === "new" || editing === null) {
        await createLocation({
          name: name.trim(),
          level,
          parent_id: parentId || null,
        });
        toast("Location added.", { title: "Saved", tone: "success" });
      } else {
        await updateLocation(editing.id, {
          name: name.trim(),
          level,
          parent_id: parentId || null,
        });
        toast("Location updated.", { title: "Saved", tone: "success" });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the location.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={editing !== null}
      onClose={onClose}
      title={editing === "new" || editing === null ? "Add location" : "Edit location"}
      size="sm"
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void onSave()} disabled={saving}>
            {saving ? "Saving…" : "Save location"}
          </Button>
        </>
      }
    >
      <div style={{ display: "grid", gap: "0.9rem" }}>
        {error && <Alert tone="danger">{error}</Alert>}
        <FormField label="Name" htmlFor="loc-name">
          <TextInput
            id="loc-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Main Warehouse, Aisle 3, Bin 12…"
          />
        </FormField>
        <FormField label="Kind" htmlFor="loc-level">
          <Select id="loc-level" value={level} onChange={(e) => setLevel(e.target.value)}>
            {LOCATION_LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Inside" htmlFor="loc-parent">
          <Select
            id="loc-parent"
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
          >
            <option value="">— Top level —</option>
            {parentOptions.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </Modal>
  );
}

function DeleteLocationModal({
  locations,
  target,
  onClose,
  onDone,
}: {
  locations: PartLocation[];
  target: PartLocation | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [mode, setMode] = useState<"reassign" | "detach">("reassign");
  const [reassignTo, setReassignTo] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const childCount = useMemo(
    () =>
      target
        ? locations.filter((l) => l.parent_id === target.id).length
        : 0,
    [locations, target],
  );
  const holds = (target?.part_count ?? 0) > 0 || childCount > 0;
  const targets = useMemo(
    () =>
      target
        ? locations.filter((l) => !subtreeIds(locations, target.id).has(l.id))
        : [],
    [locations, target],
  );

  useEffect(() => {
    setMode("reassign");
    setReassignTo("");
    setError("");
  }, [target]);

  async function onConfirm() {
    if (!target) return;
    setBusy(true);
    setError("");
    try {
      await deleteLocation(
        target.id,
        holds
          ? mode === "reassign"
            ? { reassign_to_id: reassignTo || undefined }
            : { detach: true }
          : {},
      );
      toast(`“${target.name}” deleted.`, { title: "Deleted", tone: "success" });
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete the location.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={target !== null}
      onClose={onClose}
      title={target ? `Delete “${target.name}”?` : "Delete location"}
      size="sm"
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() => void onConfirm()}
            disabled={busy || (holds && mode === "reassign" && !reassignTo)}
          >
            {busy ? "Deleting…" : "Delete location"}
          </Button>
        </>
      }
    >
      <div style={{ display: "grid", gap: "0.9rem" }}>
        {error && <Alert tone="danger">{error}</Alert>}
        {!holds && (
          <p style={{ margin: 0 }}>
            This location is empty — nothing is filed in it and it has no
            sub-locations.
          </p>
        )}
        {holds && target && (
          <>
            <p style={{ margin: 0 }}>
              This location still holds{" "}
              {target.part_count > 0 &&
                `${target.part_count} part${target.part_count === 1 ? "" : "s"}`}
              {target.part_count > 0 && childCount > 0 && " and "}
              {childCount > 0 &&
                `${childCount} sub-location${childCount === 1 ? "" : "s"}`}
              . They are never deleted or orphaned — choose where they go:
            </p>
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <input
                type="radio"
                name="loc-delete-mode"
                checked={mode === "reassign"}
                onChange={() => setMode("reassign")}
              />
              Move everything to another location
            </label>
            {mode === "reassign" && (
              <Select
                value={reassignTo}
                onChange={(e) => setReassignTo(e.target.value)}
                aria-label="Move to location"
              >
                <option value="">Choose a location…</option>
                {targets.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
            )}
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <input
                type="radio"
                name="loc-delete-mode"
                checked={mode === "detach"}
                onChange={() => setMode("detach")}
              />
              Detach — sub-locations move up a level, parts become unfiled
            </label>
          </>
        )}
      </div>
    </Modal>
  );
}

/**
 * The Community Parts pool controls (2026-10-19): the owner's
 * shelf-wide default + per-category choices. A part's own setting
 * always wins over both (that's on the part's form/detail page).
 * Publishing is a paid-plan act once enforcement switches on at
 * launch — the API says so plainly if it refuses.
 */
function PoolPanel({ parts }: { parts: Part[] | null }) {
  const { toast } = useToast();
  const [settings, setSettings] = useState<PoolSettings | null>(null);
  const [draft, setDraft] = useState<PoolSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getPoolSettings()
      .then((s) => {
        setSettings(s);
        setDraft(s);
      })
      .catch(() => setSettings(null));
  }, []);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const part of parts ?? []) {
      if (part.category) set.add(part.category);
    }
    for (const key of Object.keys(settings?.category_visibility ?? {})) {
      set.add(key);
    }
    return [...set].sort();
  }, [parts, settings]);

  const publicCount = (parts ?? []).filter((p) => p.is_public).length;

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    setError("");
    try {
      const saved = await updatePoolSettings(draft);
      setSettings(saved);
      setDraft(saved);
      toast("Pool settings saved — your shelf's public face is updated.", {
        title: "Saved",
        tone: "success",
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save pool settings.");
    } finally {
      setSaving(false);
    }
  }

  if (settings === null || draft === null) return null;

  return (
    <Panel title="Community Parts">
      <div style={{ display: "grid", gap: "0.8rem" }}>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          Parts you publish appear in{" "}
          <Link to="/parts/community">Community Parts</Link>, where every
          member can search by year, make, model and engine and message
          you. Your storage locations and notes are never shown.{" "}
          {publicCount > 0
            ? `${publicCount} of your parts ${publicCount === 1 ? "is" : "are"} listed right now.`
            : "Nothing is listed right now."}
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        {/* Measure-capped (supervisory polish 2026-10-23): this
            two-option select stretched the full ~1,140px panel
            width; it now keeps the same 560px measure as Settings
            fields. */}
        <div style={{ maxWidth: "560px" }}>
        <FormField label="Whole shelf default" htmlFor="pool-default">
          <Select
            id="pool-default"
            value={draft.default_visibility}
            onChange={(e) => setDraft({ ...draft, default_visibility: e.target.value })}
          >
            <option value="private">Private — list nothing by default</option>
            <option value="public">Public — list everything by default</option>
          </Select>
        </FormField>
        </div>
        {categories.length > 0 && (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            <p style={{ margin: 0, fontWeight: 600 }}>Per category</p>
            {categories.map((category) => (
              <div
                key={category}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) minmax(140px, 220px)",
                  gap: "0.6rem",
                  alignItems: "center",
                }}
              >
                <span style={{ overflowWrap: "anywhere" }}>{category}</span>
                <Select
                  aria-label={`Visibility for ${category}`}
                  value={draft.category_visibility[category] ?? ""}
                  onChange={(e) => {
                    const next = { ...draft.category_visibility };
                    if (e.target.value) next[category] = e.target.value;
                    else delete next[category];
                    setDraft({ ...draft, category_visibility: next });
                  }}
                >
                  <option value="">Use shelf default</option>
                  <option value="public">Public</option>
                  <option value="private">Private</option>
                </Select>
              </div>
            ))}
          </div>
        )}
        <div>
          <Button type="button" onClick={() => void onSave()} disabled={saving}>
            {saving ? "Saving…" : "Save pool settings"}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function PartsContent() {
  const [searchParams] = useSearchParams();
  const [locations, setLocations] = useState<PartLocation[] | null>(null);
  const [defs, setDefs] = useState<FieldDefinition[]>([]);
  const [parts, setParts] = useState<Part[] | null>(null);
  const [query, setQuery] = useState("");
  // The panel's location items land here as ?location_id=<node>
  // (Phase 2a): seed from the URL and re-apply when the param's
  // VALUE changes (ToolListPage's W-01 pattern) — local tree
  // clicks never write the URL, so they never fight the sync.
  const [selectedLocation, setSelectedLocation] = useState<string | null>(
    () => searchParams.get("location_id"),
  );
  const appliedLocationParam = useRef(searchParams.get("location_id"));
  useEffect(() => {
    const next = searchParams.get("location_id");
    if (appliedLocationParam.current !== next) {
      appliedLocationParam.current = next;
      setSelectedLocation(next);
    }
  }, [searchParams]);
  const [error, setError] = useState("");
  const [editingLocation, setEditingLocation] = useState<PartLocation | "new" | null>(null);
  const [deletingLocation, setDeletingLocation] = useState<PartLocation | null>(null);

  const refreshLocations = useCallback(() => {
    listLocations()
      .then(setLocations)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load locations."),
      );
  }, []);

  useEffect(() => {
    refreshLocations();
    api<FieldDefinition[]>("/inventory/field-definitions?item_type=part")
      .then(setDefs)
      .catch(() => setDefs([]));
  }, [refreshLocations]);

  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      listParts({
        q: query.trim() || undefined,
        location_id: selectedLocation ?? undefined,
      })
        .then((data) => {
          if (live) setParts(data);
        })
        .catch((err) => {
          if (live) {
            setError(
              err instanceof ApiError ? err.message : "Couldn't load your parts.",
            );
          }
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query, selectedLocation]);

  const defsById = useMemo(
    () => new Map(defs.map((d) => [d.id, d])),
    [defs],
  );
  const tree = useMemo(() => buildTree(locations ?? []), [locations]);
  const selected = (locations ?? []).find((l) => l.id === selectedLocation);

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <h1 style={{ margin: 0 }}>My Parts</h1>
        <LinkButton to="/parts/new">Add part</LinkButton>
      </div>
      <p style={{ margin: 0, color: "var(--text-muted)", maxWidth: "46rem" }}>
        Spares you're keeping for later — your own fields, your own shelves.
        Your parts live here, not in Inventory, and they never count
        against your plan's item limit.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <PoolPanel parts={parts} />
      <div
        style={{
          display: "grid",
          gap: "1rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 300px), 1fr))",
          alignItems: "start",
        }}
      >
        <Panel title="Locations">
          {locations === null ? (
            <Spinner />
          ) : locations.length === 0 ? (
            <div style={{ display: "grid", gap: "0.7rem" }}>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                No locations yet. Add your warehouse, aisles and bins so
                every spare has a shelf — or skip it and leave parts
                unfiled.
              </p>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditingLocation("new")}
              >
                Add your first location
              </Button>
            </div>
          ) : (
            <div style={{ display: "grid", gap: "0.4rem" }}>
              <button
                type="button"
                onClick={() => setSelectedLocation(null)}
                style={{
                  textAlign: "left",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: "0.3rem 0",
                  color: selectedLocation === null ? "var(--accent)" : "var(--text)",
                  fontWeight: selectedLocation === null ? 700 : 400,
                }}
              >
                All locations
              </button>
              <TreeRows
                nodes={tree}
                depth={0}
                selectedId={selectedLocation}
                onSelect={setSelectedLocation}
                onEdit={setEditingLocation}
                onDelete={setDeletingLocation}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setEditingLocation("new")}
              >
                Add location
              </Button>
            </div>
          )}
        </Panel>
        <div style={{ display: "grid", gap: "1rem" }}>
          <SearchBar
            value={query}
            onChange={setQuery}
            placeholder="Search title, notes, part numbers, anything you've recorded…"
            ariaLabel="Search my parts"
          />
          {selected && (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              Showing everything under <strong>{selected.name}</strong> (
              {levelLabel(selected.level)}) — sub-locations included.{" "}
              <button
                type="button"
                onClick={() => setSelectedLocation(null)}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--accent)",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                Clear
              </button>
            </p>
          )}
          {parts === null ? (
            <Spinner />
          ) : parts.length === 0 ? (
            <EmptyState
              title={
                query || selectedLocation
                  ? "No parts match"
                  : "No parts yet"
              }
              description={
                query || selectedLocation
                  ? "Nothing on the shelf matches that search here. Try different words, or clear the location filter."
                  : "Add the spares you're keeping — a pump on a shelf, seals in a bin — with whatever details matter to you."
              }
              action={
                <LinkButton to="/parts/new">Add your first part</LinkButton>
              }
            />
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {parts.map((part) => {
                const photo = part.attachments[0];
                const chips = Object.entries(part.custom_data)
                  .filter(([, v]) => v !== null && v !== "")
                  .slice(0, 4)
                  .map(([key, value]) => {
                    const def = defsById.get(key);
                    return def
                      ? `${def.label}: ${customValueText(value, def.field_type)}`
                      : null;
                  })
                  .filter((c): c is string => c !== null);
                return (
                  <Link
                    key={part.id}
                    to={`/parts/${part.id}`}
                    style={{ textDecoration: "none", color: "inherit" }}
                  >
                    <Panel className="tv-part-row">
                      <div
                        style={{
                          display: "flex",
                          gap: "0.9rem",
                          alignItems: "center",
                        }}
                      >
                        <ItemThumb
                          fill
                          sizeClass="tv-thumb--s56"
                          src={photo?.url ?? null}
                          name={part.title}
                        />
                        <div style={{ display: "grid", gap: "0.25rem", minWidth: 0 }}>
                          <span style={{ fontWeight: 600, overflowWrap: "anywhere" }}>
                            {part.title}
                            {part.quantity > 1 && (
                              <>
                                {" "}
                                <Badge tone="neutral">×{part.quantity}</Badge>
                              </>
                            )}
                            {part.converted_tool_id && (
                              <>
                                {" "}
                                <Badge tone="success">In inventory</Badge>
                              </>
                            )}
                            {part.is_public ? (
                              <>
                                {" "}
                                <Badge tone="accent">Public</Badge>
                              </>
                            ) : part.visibility === "public" ? (
                              <>
                                {" "}
                                <Badge tone="warning">Set public — pool off</Badge>
                              </>
                            ) : null}
                          </span>
                          <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                            <span className="tv-bin-chip">{part.location?.path ?? "Unfiled"}</span>
                            {part.condition && ` · ${part.condition}`}
                          </span>
                          {/* F1-14: the data the owner recorded —
                              vehicle fit + asking price — belongs
                              ON the list row, not only on detail. */}
                          {([part.year, part.make, part.model, part.engine].some((v) => v !== null && v !== "") || part.asking_price !== null) && (
                            <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                              {[part.year, part.make, part.model, part.engine]
                                .filter((v) => v !== null && v !== "")
                                .join(" ")}
                              {part.asking_price !== null &&
                                ` · $${Number(part.asking_price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                            </span>
                          )}
                          {chips.length > 0 && (
                            <span style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                              {chips.map((chip) => (
                                <Badge key={chip} tone="neutral">
                                  {chip}
                                </Badge>
                              ))}
                            </span>
                          )}
                        </div>
                      </div>
                    </Panel>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <LocationFormModal
        locations={locations ?? []}
        editing={editingLocation}
        onClose={() => setEditingLocation(null)}
        onSaved={refreshLocations}
      />
      <DeleteLocationModal
        locations={locations ?? []}
        target={deletingLocation}
        onClose={() => setDeletingLocation(null)}
        onDone={() => {
          if (deletingLocation && selectedLocation === deletingLocation.id) {
            setSelectedLocation(null);
          }
          refreshLocations();
        }}
      />
    </div>
  );
}

export default function PartsPage() {
  return (
    <RequireAuth>
      <PartsContent />
    </RequireAuth>
  );
}
