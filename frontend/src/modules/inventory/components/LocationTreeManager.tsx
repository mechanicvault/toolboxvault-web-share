import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormField,
  Modal,
  Select,
  Spinner,
  TextInput,
  useToast,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import type { LocationNode } from "../types";
import {
  LocationGuideExplainer,
  LocationTierHint,
  TIER_PLACEHOLDER_KEYS,
  locationTierForParent,
} from "./LocationTierHint";
import { DrawerAutofill } from "./DrawerAutofill";
import {
  buildLocationTree,
  createLocationNode,
  deleteLocationNode,
  flattenLocationTree,
  indentedNodeLabel,
  listLocationNodes,
  locationSubtreeIds,
  updateLocationNode,
  type LocationTreeNode,
} from "./locationTree";

/**
 * Manage locations (Package B): the modal home of the location
 * tree — create, rename, move (parent select, own subtree
 * excluded), and delete. Deleting an OCCUPIED node (items filed
 * under it, or child locations) asks first: reassign everything to
 * another location, or detach (items unfiled, children lifted to
 * the deleted node's parent). The server's 422 copy is shown
 * verbatim when a delete is refused. UX mirrors the Used Parts
 * page's location tree, adapted to this module's node shape.
 */
export function LocationTreeManager({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [nodes, setNodes] = useState<LocationNode[] | null>(null);
  const [loadError, setLoadError] = useState("");
  // Edit form: "new" | node being edited | null (form closed).
  const [editing, setEditing] = useState<LocationNode | "new" | null>(null);
  const [editName, setEditName] = useState("");
  const [editParentId, setEditParentId] = useState("");
  const [editIsDrawer, setEditIsDrawer] = useState(false);
  const [editDrawerIndex, setEditDrawerIndex] = useState("");
  const [editError, setEditError] = useState("");
  const [saving, setSaving] = useState(false);
  // Delete flow: the node + the occupied-node decision.
  const [deleting, setDeleting] = useState<LocationNode | null>(null);
  const [deleteMode, setDeleteMode] = useState<"reassign" | "detach">("reassign");
  const [reassignTo, setReassignTo] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const editPanelRef = useRef<HTMLDivElement | null>(null);
  const deletePanelRef = useRef<HTMLDivElement | null>(null);

  // Owner fix (2026-10-25): the editor (and the delete panel)
  // open at the TOP of this modal, but a long location list
  // invites the click far below — the panel opened off-screen
  // and the user had to hunt for it. The moment either panel
  // opens, scroll it into view. Smooth unless the user prefers
  // reduced motion (the AppStoreBar matchMedia guard pattern).
  useEffect(() => {
    const el =
      editing !== null
        ? editPanelRef.current
        : deleting !== null
          ? deletePanelRef.current
          : null;
    if (!el) return;
    const reduceMotion =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({
      block: "start",
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [editing, deleting]);

  function load() {
    listLocationNodes()
      .then((rows) => {
        setNodes(rows);
        setLoadError("");
      })
      .catch((err) =>
        setLoadError(
          err instanceof ApiError ? err.message : "Couldn't load locations.",
        ),
      );
  }

  useEffect(() => {
    if (!open) return;
    setNodes(null);
    setEditing(null);
    setDeleting(null);
    setDeleteError("");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open ]);

  const flat = useMemo(() => flattenLocationTree(nodes ?? []), [nodes]);
  const tree = useMemo(() => buildLocationTree(nodes ?? []), [nodes]);

  function startEdit(node: LocationNode | "new") {
    setDeleting(null);
    setDeleteError("");
    setEditError("");
    if (node === "new") {
      setEditName("");
      setEditParentId("");
      setEditIsDrawer(false);
      setEditDrawerIndex("");
    } else {
      setEditName(node.name);
      setEditParentId(node.parent_id ?? "");
      setEditIsDrawer(node.parent_layout_id !== null);
      setEditDrawerIndex(
        node.drawer_index === null ? "" : String(node.drawer_index + 1),
      );
    }
    setEditing(node);
  }

  const editExcluded = useMemo(
    () =>
      editing && editing !== "new"
        ? locationSubtreeIds(nodes ?? [], editing.id)
        : new Set<string>(),
    [editing, nodes],
  );
  const editParentOptions = flat.filter((n) => !editExcluded.has(n.id));

  async function onSaveEdit() {
    if (!editName.trim()) {
      setEditError("Give the location a name.");
      return;
    }
    setSaving(true);
    setEditError("");
    try {
      // Drawer fields (audit A3): the layout is the chosen parent
      // (the toolbox this drawer lives in); the position is kept
      // 1-based in the form, 0-based on the wire (the app's
      // drawer_index). Not a drawer -> both clear to null.
      const drawerFields =
        editIsDrawer && editParentId
          ? {
              parent_layout_id: editParentId,
              drawer_index:
                editDrawerIndex.trim() === ""
                  ? null
                  : Math.max(1, Number(editDrawerIndex) || 1) - 1,
            }
          : { parent_layout_id: null, drawer_index: null };
      if (editing === "new") {
        await createLocationNode({
          name: editName.trim(),
          parent_id: editParentId || null,
          ...drawerFields,
        });
        toast("Location added.", { title: "Saved", tone: "success" });
      } else if (editing) {
        await updateLocationNode(editing.id, {
          name: editName.trim(),
          // Explicit null lifts the node to the top tier.
          parent_id: editParentId || null,
          ...drawerFields,
        });
        toast("Location updated.", { title: "Saved", tone: "success" });
      }
      setEditing(null);
      load();
      onChanged?.();
    } catch (err) {
      setEditError(
        err instanceof ApiError ? err.message : "Couldn't save the location.",
      );
    } finally {
      setSaving(false);
    }
  }

  // AI drawer autofill (2026-10-25): the confirm's Create in
  // the tier-2 add panel. The toolbox itself hasn't been saved
  // yet at that point, so this creates it first, then the
  // confirmed drawers (and any source-named sections after
  // them) as plain tier-3 locations riding the same create
  // machinery — paths, counts, and dropdown rollups just work.
  async function onCreateWithDrawers(childNames: string[]) {
    const name = editName.trim();
    if (!name || !editParentId) return;
    setEditError("");
    try {
      const toolbox = await createLocationNode({
        name,
        parent_id: editParentId,
      });
      for (const [i, childName] of childNames.entries()) {
        await createLocationNode({
          name: childName,
          parent_id: toolbox.id,
          sort_order: i + 1,
        });
      }
      toast(
        `“${name}” added with ${childNames.length} location${
          childNames.length === 1 ? "" : "s"
        } inside it.`,
        { title: "Saved", tone: "success" },
      );
      setEditing(null);
      load();
      onChanged?.();
    } catch (err) {
      setEditError(
        err instanceof ApiError ? err.message : "Couldn't save the location.",
      );
      throw err;
    }
  }

  function startDelete(node: LocationNode) {
    setEditing(null);
    setDeleting(node);
    setDeleteMode("reassign");
    setReassignTo("");
    setDeleteError("");
  }

  const deleteChildCount = useMemo(
    () =>
      deleting ? (nodes ?? []).filter((n) => n.parent_id === deleting.id).length : 0,
    [deleting, nodes],
  );
  const deleteOccupied =
    deleting !== null && (deleting.item_count > 0 || deleteChildCount > 0);
  const reassignTargets = useMemo(
    () =>
      deleting
        ? flat.filter((n) => !locationSubtreeIds(nodes ?? [], deleting.id).has(n.id))
        : [],
    [deleting, flat, nodes],
  );

  async function onConfirmDelete() {
    if (!deleting) return;
    if (deleteOccupied && deleteMode === "reassign" && !reassignTo) {
      setDeleteError("Pick the location everything should move to.");
      return;
    }
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteLocationNode(
        deleting.id,
        deleteOccupied && deleteMode === "reassign"
          ? { reassign_to_id: reassignTo }
          : { detach: true },
      );
      toast(`“${deleting.name}” deleted.`, { title: "Locations", tone: "success" });
      setDeleting(null);
      load();
      onChanged?.();
    } catch (err) {
      // The server's refusal copy (422) is friendly — show it verbatim.
      setDeleteError(
        err instanceof ApiError ? err.message : "Couldn't delete that location.",
      );
    } finally {
      setDeleteBusy(false);
    }
  }

  function renderRows(level: LocationTreeNode[]): ReactNode {
    return level.map((node) => (
      <div key={node.id}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
            paddingLeft: `${node.depth * 1.1}rem`,
            paddingTop: "0.3rem",
            paddingBottom: "0.3rem",
            flexWrap: "wrap",
          }}
        >
          <span style={{ flex: 1, minWidth: "120px", overflowWrap: "anywhere" }}>
            {node.name}{" "}
            {node.drawer_index !== null && (
              <span style={{ color: "var(--accent)", fontSize: "0.8rem", fontWeight: 600 }}>
                Drawer {node.drawer_index + 1}{" "}
              </span>
            )}
            <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
              {node.subtree_item_count} item{node.subtree_item_count === 1 ? "" : "s"}
            </span>
          </span>
          <Button type="button" variant="secondary" size="sm" onClick={() => startEdit(node)}>
            Rename / move
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => startDelete(node)}>
            Delete
          </Button>
        </div>
        {renderRows(node.children)}
      </div>
    ));
  }

  return (
    <Modal open={open} onClose={onClose} title="Manage locations" size="lg">
      <div style={{ display: "grid", gap: "0.9rem" }}>
        <LocationGuideExplainer />
        {loadError && <Alert tone="danger">{loadError}</Alert>}
        {nodes === null && !loadError ? (
          <p style={{ color: "var(--text-muted)", display: "flex", gap: "0.5rem", alignItems: "center", margin: 0 }}>
            <Spinner size="sm" /> Loading locations…
          </p>
        ) : (
          <>
            {editing === null && deleting === null && (
              <div>
                <Button type="button" size="sm" onClick={() => startEdit("new")}>
                  Add location
                </Button>
              </div>
            )}

            {editing !== null && (
              <div ref={editPanelRef} style={{ display: "grid", gap: "0.7rem", border: "1px solid var(--edge)", borderRadius: "var(--radius)", padding: "0.8rem" }}>
                <strong>{editing === "new" ? "New location" : `Edit “${editing.name}”`}</strong>
                {editError && <Alert tone="danger">{editError}</Alert>}
                {/* Tier guidance (Ryan, 2026-10-25): the helper
                    follows the tier being added — it reads the
                    chosen parent (below) and speaks for that
                    tier; the name placeholder matches it. Shown
                    for edits too, since a move re-tiers the node. */}
                <LocationTierHint flat={flat} parentId={editParentId} />
                <FormField label="Name" htmlFor="ltm-name">
                  <TextInput
                    id="ltm-name"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder={
                      editing === "new"
                        ? t(
                            TIER_PLACEHOLDER_KEYS[
                              locationTierForParent(flat, editParentId)
                            ],
                          )
                        : "Shop Toolbox, Left Drawer 2, Truck bin…"
                    }
                  />
                </FormField>
                <FormField label="Inside" htmlFor="ltm-parent">
                  <Select
                    id="ltm-parent"
                    value={editParentId}
                    onChange={(e) => setEditParentId(e.target.value)}
                  >
                    <option value="">— Top level —</option>
                    {editParentOptions.map((n) => (
                      <option key={n.id} value={n.id}>
                        {indentedNodeLabel(n)}
                      </option>
                    ))}
                  </Select>
                </FormField>
                {/* AI drawer lookup (2026-10-25): only while
                    ADDING a tier-2 location (a parent place is
                    picked, so the new node is the storage at
                    that place). The block carries its OWN make +
                    model box — the name above stays the user's
                    own and is never the query once edited.
                    Editing an existing node never offers it. */}
                {editing === "new" &&
                  locationTierForParent(flat, editParentId) === 2 && (
                    <DrawerAutofill
                      nameText={editName}
                      parentId={editParentId}
                      onConfirm={onCreateWithDrawers}
                    />
                  )}
                {editParentId && (
                  <>
                    <Checkbox
                      name="ltm-is-drawer"
                      label="This is a drawer in that location (it has a position in the grid)"
                      checked={editIsDrawer}
                      onChange={(e) => setEditIsDrawer(e.target.checked)}
                    />
                    {editIsDrawer && (
                      <FormField
                        label="Drawer position"
                        htmlFor="ltm-drawer-index"
                        hint="1 is the top/first drawer. Drawers sort by position in the tree."
                      >
                        <TextInput
                          id="ltm-drawer-index"
                          type="number"
                          min="1"
                          step="1"
                          value={editDrawerIndex}
                          onChange={(e) => setEditDrawerIndex(e.target.value)}
                          placeholder="e.g. 1"
                        />
                      </FormField>
                    )}
                  </>
                )}
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Button type="button" size="sm" onClick={() => void onSaveEdit()} loading={saving}>
                    {editing === "new" ? "Add location" : "Save changes"}
                  </Button>
                  <Button type="button" size="sm" variant="secondary" onClick={() => setEditing(null)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {deleting !== null && (
              <div ref={deletePanelRef} style={{ display: "grid", gap: "0.7rem", border: "1px solid var(--edge)", borderRadius: "var(--radius)", padding: "0.8rem" }}>
                <strong>Delete “{deleting.name}”?</strong>
                {deleteError && <Alert tone="danger">{deleteError}</Alert>}
                {deleteOccupied ? (
                  <>
                    <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
                      This location holds {deleting.item_count} item
                      {deleting.item_count === 1 ? "" : "s"}
                      {deleteChildCount > 0
                        ? ` and ${deleteChildCount} child location${deleteChildCount === 1 ? "" : "s"}`
                        : ""}
                      . What should happen to them?
                    </p>
                    <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                      <input
                        type="radio"
                        name="ltm-delete-mode"
                        checked={deleteMode === "reassign"}
                        onChange={() => setDeleteMode("reassign")}
                      />
                      Move everything to another location
                    </label>
                    {deleteMode === "reassign" && (
                      <FormField label="Move to" htmlFor="ltm-reassign">
                        <Select
                          id="ltm-reassign"
                          value={reassignTo}
                          onChange={(e) => setReassignTo(e.target.value)}
                        >
                          <option value="">Pick a location…</option>
                          {reassignTargets.map((n) => (
                            <option key={n.id} value={n.id}>
                              {indentedNodeLabel(n)}
                            </option>
                          ))}
                        </Select>
                      </FormField>
                    )}
                    <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                      <input
                        type="radio"
                        name="ltm-delete-mode"
                        checked={deleteMode === "detach"}
                        onChange={() => setDeleteMode("detach")}
                      />
                      Detach — items lose this location; child locations move up a level
                    </label>
                  </>
                ) : (
                  <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
                    Nothing is filed here, so this is a clean delete.
                  </p>
                )}
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Button type="button" size="sm" variant="danger" onClick={() => void onConfirmDelete()} loading={deleteBusy}>
                    Delete location
                  </Button>
                  <Button type="button" size="sm" variant="secondary" onClick={() => setDeleting(null)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {(nodes ?? []).length === 0 ? (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                No locations yet — add your first toolbox, shelf, or bin above.
              </p>
            ) : (
              <div>{renderRows(tree)}</div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
