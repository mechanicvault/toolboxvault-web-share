import {
  useEffect,
  useState,
} from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormField,
  Modal,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import {
  api,
  ApiError,
} from "../../lib/api";
import {
  accountTypeLabel,
  enabledShareGroups,
  type ShareGroupState,
  type SharingOverview,
} from "../core";
import {DealerPicker} from "../dealers/components/DealerFields";
import {FieldSuggest} from "./components/FieldSuggest";
import {LocationTreePicker} from "./components/LocationTreePicker";
import {BulkModalKind} from "./listUtils";

export function BulkModals({
  modal,
  onClose,
  refs,
  lookup,
  busy,
  runBulk,
  clearSelection,
}: {
  modal: BulkModalKind;
  onClose: () => void;
  refs: { kind: "tool" | "battery"; id: string }[];
  lookup: Map<string, { name: string; isSet: boolean }>;
  busy: boolean;
  runBulk: (action: string, params: Record<string, unknown>, verb?: string) => Promise<void>;
  clearSelection: () => void;
}) {
  const { toast } = useToast();
  const [locationId, setLocationId] = useState<string | null>(null);
  const [dealerId, setDealerId] = useState("");
  const [dealersAvailable, setDealersAvailable] = useState(false);
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [tagName, setTagName] = useState("");
  const [deleteText, setDeleteText] = useState("");
  // Share state: the sharing overview + per-group checks + the
  // per-set "include addons" answers for sets in the selection.
  const [shareOverview, setShareOverview] = useState<SharingOverview | null>(null);
  const [shareChecked, setShareChecked] = useState<Set<string>>(new Set());
  const [shareAddons, setShareAddons] = useState<Map<string, boolean>>(new Map());
  const [shareError, setShareError] = useState("");
  const [shareBusy, setShareBusy] = useState(false);

  useEffect(() => {
    if (modal === null) return;
    setLocationId(null);
    setDealerId("");
    setBrand("");
    setCategory("");
    setTagName("");
    setDeleteText("");
    setShareError("");
    if (modal === "share") {
      setShareOverview(null);
      api<SharingOverview>("/core/sharing")
        .then((overview) => {
          setShareOverview(overview);
          setShareChecked(
            new Set(enabledShareGroups(overview).map((g) => g.recipient_group)),
          );
        })
        .catch((err) =>
          setShareError(
            err instanceof ApiError ? err.message : "Couldn't load your sharing setup.",
          ),
        );
    }
  }, [modal]);

  const selectedSets = refs.filter(
    (r) => r.kind === "tool" && lookup.get(`tool:${r.id}`)?.isSet,
  );
  const shareGroups: ShareGroupState[] = shareOverview
    ? enabledShareGroups(shareOverview)
    : [];

  async function applyShare() {
    if (!shareOverview) return;
    setShareBusy(true);
    setShareError("");
    try {
      for (const group of shareGroups) {
        if (!shareChecked.has(group.recipient_group)) continue;
        const toolIds = new Set(group.shared_tool_ids);
        const batteryIds = new Set(group.shared_battery_ids);
        for (const ref of refs) {
          if (ref.kind === "tool") toolIds.add(ref.id);
          else batteryIds.add(ref.id);
        }
        const choices = new Map(
          (group.set_choices ?? []).map((c) => [c.tool_id, c.include_addons]),
        );
        for (const ref of selectedSets) {
          choices.set(ref.id, shareAddons.get(ref.id) ?? choices.get(ref.id) ?? false);
        }
        await api(`/core/sharing/${group.recipient_group}/items`, {
          method: "PUT",
          body: JSON.stringify({
            tool_ids: [...toolIds],
            battery_ids: [...batteryIds],
            set_choices: [...choices.entries()]
              .filter(([toolId]) => toolIds.has(toolId))
              .map(([tool_id, include_addons]) => ({ tool_id, include_addons })),
          }),
        });
      }
      toast(
        `${refs.length} item${refs.length === 1 ? "" : "s"} added to your shared list${shareChecked.size === 1 ? "" : "s"}.`,
        { tone: "success", title: "Shared" },
      );
      clearSelection();
      onClose();
    } catch (err) {
      setShareError(
        err instanceof ApiError ? err.message : "Couldn't update the shared lists.",
      );
    } finally {
      setShareBusy(false);
    }
  }

  const count = refs.length;
  const countLabel = `${count} item${count === 1 ? "" : "s"}`;

  return (
    <>
      <Modal
        open={modal === "location"}
        onClose={onClose}
        title={`Move ${countLabel} to a location`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={() =>
                void runBulk("move_location", { location_id: locationId }, "moved")
              }
            >
              Move
            </Button>
          </>
        }
      >
        <FormField label="Location" htmlFor="bulk-location">
          <LocationTreePicker
            id="bulk-location"
            value={locationId}
            onChange={(next) => setLocationId(next)}
          />
        </FormField>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginBottom: 0 }}>
          “No location” unfiles the items — they keep every other detail.
        </p>
      </Modal>

      <Modal
        open={modal === "dealer"}
        onClose={onClose}
        title={`Set dealer on ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!dealersAvailable}
              onClick={() =>
                void runBulk("set_dealer", { dealer_company_id: dealerId || null })
              }
            >
              Set dealer
            </Button>
          </>
        }
      >
        <DealerPicker
          id="bulk-dealer"
          label="Dealer (bought from)"
          hint="The company you bought it from — used for dealer contacts and warranty help."
          value={dealerId}
          onChange={setDealerId}
          onAvailability={setDealersAvailable}
        />
        {!dealersAvailable && (
          <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginBottom: 0 }}>
            The dealers module isn't available, so the dealer can't be changed here.
          </p>
        )}
      </Modal>

      <Modal
        open={modal === "brand"}
        onClose={onClose}
        title={`Set brand on ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!brand.trim()}
              onClick={() => void runBulk("set_brand", { brand: brand.trim() })}
            >
              Set brand
            </Button>
          </>
        }
      >
        <FormField label="Brand (manufacturer)" htmlFor="bulk-brand">
          <FieldSuggest field="brand" id="bulk-brand" value={brand} onChange={setBrand} />
        </FormField>
      </Modal>

      <Modal
        open={modal === "category"}
        onClose={onClose}
        title={`Set category on ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={() => void runBulk("set_category", { category: category.trim() })}
            >
              Set category
            </Button>
          </>
        }
      >
        <FormField label="Category" htmlFor="bulk-category">
          <FieldSuggest
            field="category"
            id="bulk-category"
            value={category}
            onChange={setCategory}
          />
        </FormField>
      </Modal>

      <Modal
        open={modal === "tag"}
        onClose={onClose}
        title={`Add a tag to ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!tagName.trim()}
              onClick={() => void runBulk("add_tag", { tag_name: tagName.trim() }, "tagged")}
            >
              Add tag
            </Button>
          </>
        }
      >
        <FormField label="Tag" htmlFor="bulk-tag">
          <TextInput
            id="bulk-tag"
            value={tagName}
            onChange={(e) => setTagName(e.target.value)}
            placeholder="Tag name"
          />
        </FormField>
      </Modal>

      <Modal
        open={modal === "share"}
        onClose={onClose}
        title={`Share ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose} disabled={shareBusy}>
              Cancel
            </Button>
            <Button
              loading={shareBusy}
              disabled={shareGroups.length === 0 || shareChecked.size === 0}
              onClick={() => void applyShare()}
            >
              Share
            </Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {shareError && <Alert tone="danger">{shareError}</Alert>}
          {shareOverview === null && !shareError ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              <Spinner size="sm" /> Loading your sharing setup…
            </p>
          ) : shareGroups.length === 0 ? (
            <p style={{ margin: 0 }}>
              You're not sharing with any group yet — turn sharing on in
              Settings → Sharing first, then bulk-share from here.
            </p>
          ) : (
            <>
              <p style={{ margin: 0 }}>
                Add the selected items to the shared lists for:
              </p>
              <div style={{ display: "grid", gap: "0.35rem" }}>
                {shareGroups.map((g) => (
                  <Checkbox
                    key={g.recipient_group}
                    name={`bulk-share-${g.recipient_group}`}
                    label={`Share with ${accountTypeLabel(g.recipient_group)}`}
                    checked={shareChecked.has(g.recipient_group)}
                    onChange={(e) =>
                      setShareChecked((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(g.recipient_group);
                        else next.delete(g.recipient_group);
                        return next;
                      })
                    }
                  />
                ))}
              </div>
              {selectedSets.length > 0 && (
                <div style={{ display: "grid", gap: "0.35rem" }}>
                  <p style={{ margin: 0, fontWeight: 600 }}>
                    Sets in this selection — include their addons?
                  </p>
                  {selectedSets.map((ref) => (
                    <Checkbox
                      key={ref.id}
                      name={`bulk-share-addons-${ref.id}`}
                      label={`${lookup.get(`tool:${ref.id}`)?.name ?? "Set"} — include addons`}
                      checked={shareAddons.get(ref.id) ?? false}
                      onChange={(e) =>
                        setShareAddons((prev) => new Map(prev).set(ref.id, e.target.checked))
                      }
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </Modal>

      <Modal
        open={modal === "delete"}
        onClose={onClose}
        title={`Delete ${countLabel}?`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={busy}
              disabled={deleteText !== "DELETE"}
              onClick={() => void runBulk("delete", {}, "deleted")}
            >
              Delete {countLabel}
            </Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: "0.7rem" }}>
          <Alert tone="danger">
            This permanently deletes the selected items and their
            attachments. It can't be undone.
          </Alert>
          <FormField label="Type DELETE to confirm" htmlFor="bulk-delete-confirm">
            <TextInput
              id="bulk-delete-confirm"
              value={deleteText}
              onChange={(e) => setDeleteText(e.target.value)}
              placeholder="DELETE"
              autoComplete="off"
            />
          </FormField>
        </div>
      </Modal>
    </>
  );
}
