import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Breadcrumbs,
  Button,
  Checkbox,
  DatePicker,
  FormField,
  FramedImage,
  Modal,
  Panel,
  Select,
  StickySaveButton,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { TagChip } from "../../components";
import { formGridStyle } from "../../components/formStyles";
import { api, ApiError } from "../../lib/api";
import { useFixFocus } from "../../lib/fixFocus";
import { todayLocalIso } from "../../lib/format";
import {
  accountTypeLabel,
  enabledShareGroups,
  type ShareGroupState,
  type SharingOverview,
} from "../core";
import { DealerPicker } from "../dealers/components/DealerFields";
import type { DealerCompany } from "../dealers/types";
import { WarrantyFields } from "./components/WarrantyFields";
import { CategoryPicker } from "./components/CategoryPicker";
import { CustomFieldInput } from "./components/CustomFieldInput";
import { FieldSuggest } from "./components/FieldSuggest";
import {
  QuickAddPanel,
  type QuickAddValues,
} from "../catalog/QuickAddPanel";
import { LocationTreePicker } from "./components/LocationTreePicker";
import { PhotoUploader } from "./components/PhotoUploader";
import {
  fileFailureToast,
  StagedFilePicker,
  uploadStagedFiles,
  type StagedFile,
} from "./components/StagedPhotoPicker";
import type {
  Battery,
  BatteryFormValues,
  FieldDefinition,
  InitialSchedule,
  Tag,
  Tool,
} from "./types";

const EMPTY: BatteryFormValues = {
  name: "",
  brand: "",
  model: "",
  serial_number: "",
  // Starts empty: the CategoryPicker fills the standing
  // default (the Batteries starter, in the account's own
  // spelling) once the category list loads — create mode only.
  category: "",
  location_id: "",
  notes: "",
  purchase_price: "",
  purchase_date: "",
  replacement_cost: "",
  msrp: "",
  platform: "",
  voltage: "",
  capacity_ah: "",
  chemistry: "",
  warranty_months: "",
  warranty_provider: "",
  warranty_contact: "",
  warranty_terms: "",
  warranty_type: "",
  currently_in_tool_id: "",
  quantity: "1",
  upc: "",
  business_use: false,
  dealer_company_id: "",
  tag_ids: [],
  custom_data: {},
};

function batteryToForm(battery: Battery): BatteryFormValues {
  return {
    name: battery.name,
    brand: battery.brand,
    model: battery.model,
    serial_number: battery.serial_number,
    category: battery.category,
    location_id: battery.location_id ?? "",
    notes: battery.notes,
    purchase_price: battery.purchase_price ?? "",
    purchase_date: battery.purchase_date ?? "",
    replacement_cost: battery.replacement_cost ?? "",
    msrp: battery.msrp ?? "",
    platform: battery.platform,
    voltage: battery.voltage ?? "",
    capacity_ah: battery.capacity_ah ?? "",
    chemistry: battery.chemistry,
    warranty_months:
      battery.warranty_months === null ? "" : String(battery.warranty_months),
    warranty_provider: battery.warranty_provider ?? "",
    warranty_contact: battery.warranty_contact ?? "",
    warranty_terms: battery.warranty_terms ?? "",
    warranty_type: battery.warranty_type ?? "",
    currently_in_tool_id: battery.currently_in_tool_id ?? "",
    quantity: String(battery.quantity ?? 1),
    upc: battery.upc ?? "",
    business_use: battery.business_use ?? false,
    dealer_company_id: battery.dealer_company_id ?? "",
    tag_ids: (battery.tags ?? []).map((tag) => tag.id),
    custom_data: battery.custom_data ?? {},
  };
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/**
 * Add / edit a battery. Same shape as the tool form (it IS the same
 * machinery): basics, the battery facts, cost details, the owner's
 * custom fields (definitions that apply to batteries), and photos —
 * picked during entry in both modes: edit mode uploads against the
 * existing battery; add mode stages the files and uploads them
 * against the new battery as part of the same Save. The "currently
 * in" picker lists the owner's tools; the link lives on the battery,
 * so moving a battery between tools is just this select. After
 * creating one, if group sharing is active, the same share prompt as
 * the tool form asks whether the new battery joins the shared lists.
 */
export default function BatteryFormPage() {
  const { id } = useParams<{ id: string }>();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const { toast } = useToast();
  /* The health check's Fix-it deep links (owner 2026-11-05):
   * the hash names the gap — land on its exact field, focused
   * and highlighted (lib/fixFocus). */
  useFixFocus((hash) => {
    if (hash === "fix-model") return "bf-model";
    if (hash === "fix-purchase-date") return "bf-date";
    return null;
  });

  /* Create mode opens with the purchase date on today (owner's
   * date rule, 2026-11-04); edit mode replaces these values with
   * the record's saved ones in the load effect below. */
  const [values, setValues] = useState<BatteryFormValues>(() =>
    editing ? EMPTY : { ...EMPTY, purchase_date: todayLocalIso() },
  );
  const [definitions, setDefinitions] = useState<FieldDefinition[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [savedBattery, setSavedBattery] = useState<Battery | null>(null);
  // Duplicate detection (wave 4): the create 409's candidates.
  const [duplicate, setDuplicate] = useState<{
    id: string;
    name: string;
    brand: string;
    model: string;
    serial_number: string;
    matched_on: string;
  }[]>([]);
  const [loading, setLoading] = useState(editing);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const [sharePrompt, setSharePrompt] = useState<{
    battery: Battery;
    groups: ShareGroupState[];
  } | null>(null);
  const [promptChecked, setPromptChecked] = useState<Set<string>>(new Set());
  /** Package C: groups where the owner chose "share by rule" in
   *  the prompt — a category rule covering this battery (and
   *  future ones) instead of / alongside the one-off pick. */
  const [promptRuleChecked, setPromptRuleChecked] = useState<Set<string>>(
    new Set(),
  );
  const [promptError, setPromptError] = useState<string | null>(null);
  const [promptBusy, setPromptBusy] = useState(false);

  // Files staged in the add form (no record to attach them to yet),
  // mirroring the tool form: photos, documents AND receipts. Failed
  // upload names survive until the create flow lands on the detail
  // page and the warning toast fires.
  const [stagedPhotos, setStagedPhotos] = useState<StagedFile[]>([]);
  const [stagedDocs, setStagedDocs] = useState<StagedFile[]>([]);
  const [stagedReceipts, setStagedReceipts] = useState<StagedFile[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const failedFileNames = useRef<string[] | null>(null);
  // Tags + location vocabulary + dealers availability (the tag
  // picker hides when the dealers module is off; the save payload
  // then omits dealer_company_id entirely so a stored tag survives).
  const [tags, setTags] = useState<Tag[]>([]);
  const [newTagName, setNewTagName] = useState("");
  const [tagBusy, setTagBusy] = useState(false);
  const [dealersAvailable, setDealersAvailable] = useState(false);
  // The picked dealer's full record + whether the picker has
  // reported at all — the warranty fields prefill provider/contact
  // from it (see WarrantyFields).
  const [dealerCompany, setDealerCompany] = useState<DealerCompany | null>(null);
  const [dealerKnown, setDealerKnown] = useState(false);
  // Optional first maintenance schedule (Package B).
  const [schedOn, setSchedOn] = useState(false);
  const [schedKind, setSchedKind] = useState<InitialSchedule["kind"]>("service");
  const [schedLabel, setSchedLabel] = useState("");
  const [schedInterval, setSchedInterval] = useState("");
  const [schedDue, setSchedDue] = useState("");

  const stagedRef = useRef<StagedFile[]>([]);
  stagedRef.current = [...stagedPhotos, ...stagedDocs, ...stagedReceipts];
  useEffect(
    () => () => {
      for (const p of stagedRef.current) {
        if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
      }
    },
    [],
  );

  useEffect(() => {
    let live = true;
    Promise.all([
      api<FieldDefinition[]>("/inventory/field-definitions?item_type=battery"),
      api<Tool[]>("/inventory?limit=200"),
      editing ? api<Battery>(`/inventory/batteries/${id}`) : Promise.resolve(null),
    ])
      .then(([defs, toolList, battery]) => {
        if (!live) return;
        setDefinitions(defs);
        setTools(toolList);
        if (battery) {
          setSavedBattery(battery);
          setValues(batteryToForm(battery));
        }
      })
      .catch((err) => {
        if (live) {
          setLoadError(
            err instanceof ApiError ? err.message : "Couldn't load the battery.",
          );
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    api<Tag[]>("/inventory/tags").then((rows) => live && setTags(rows)).catch(() => {});
    return () => {
      live = false;
    };
  }, [id, editing]);

  function set<K extends keyof BatteryFormValues>(key: K, value: BatteryFormValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function createTag() {
    const name = newTagName.trim();
    if (!name) return;
    setTagBusy(true);
    try {
      const tag = await api<Tag>("/inventory/tags", {
        method: "POST",
        body: JSON.stringify({ name, color: "amber" }),
      });
      setTags((rows) => (rows.some((t) => t.id === tag.id) ? rows : [...rows, tag]));
      setValues((v) => ({
        ...v,
        tag_ids: v.tag_ids.includes(tag.id) ? v.tag_ids : [...v.tag_ids, tag.id],
      }));
      setNewTagName("");
    } catch {
      /* the tag simply isn't created; the form carries on */
    } finally {
      setTagBusy(false);
    }
  }

  function applyQuickAdd(valuesIn: QuickAddValues) {
    if (valuesIn.name !== undefined) set("name", valuesIn.name);
    if (valuesIn.brand !== undefined) set("brand", valuesIn.brand);
    if (valuesIn.model !== undefined) set("model", valuesIn.model);
    if (valuesIn.category !== undefined) set("category", valuesIn.category);
    if (valuesIn.msrp !== undefined) set("msrp", valuesIn.msrp);
    if (valuesIn.description !== undefined) set("notes", valuesIn.description);
  }

  async function onSubmit(e?: FormEvent, force = false) {
    e?.preventDefault();
    setError(null);
    setFieldErrors({});
    const errors: Record<string, string> = {};
    if (!values.name.trim()) errors.name = "A name is required.";
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        name: values.name.trim(),
        brand: values.brand,
        model: values.model,
        serial_number: values.serial_number,
        category: values.category || "Batteries",
        location_id: values.location_id || null,
        notes: values.notes,
        purchase_price: numberOrNull(values.purchase_price),
        purchase_date: values.purchase_date || null,
        replacement_cost: numberOrNull(values.replacement_cost),
        msrp: numberOrNull(values.msrp),
        platform: values.platform,
        voltage: numberOrNull(values.voltage),
        capacity_ah: numberOrNull(values.capacity_ah),
        chemistry: values.chemistry,
        warranty_months: numberOrNull(values.warranty_months),
        warranty_provider: values.warranty_provider.trim(),
        warranty_contact: values.warranty_contact.trim(),
        warranty_terms: values.warranty_terms.trim(),
        warranty_type: values.warranty_type === "" ? null : values.warranty_type,
        currently_in_tool_id: values.currently_in_tool_id || null,
        upc: values.upc.trim(),
        business_use: values.business_use,
        quantity: Math.max(1, Math.floor(Number(values.quantity) || 1)),
        tag_ids: values.tag_ids,
        custom_data: values.custom_data,
      };
      if (dealersAvailable) {
        payload.dealer_company_id = values.dealer_company_id || null;
      }
      // Optional first maintenance schedule (Package B).
      if (schedOn) {
        if (!schedInterval && !schedDue) {
          setError("The first maintenance schedule needs an interval or a due date.");
          setBusy(false);
          return;
        }
        payload.initial_schedule = {
          kind: schedKind,
          label: schedLabel.trim(),
          interval_days: schedInterval ? Number(schedInterval) : null,
          due_date: schedDue || null,
        } satisfies InitialSchedule;
      }
      if (editing) {
        const updated = await api<Battery>(`/inventory/batteries/${id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        navigate(`/inventory/batteries/${updated.id}`, { replace: true });
      } else {
        const created = await api<Battery>(
          force ? "/inventory/batteries?force=true" : "/inventory/batteries",
          {
            method: "POST",
            body: JSON.stringify(payload),
          },
        );
        // Files picked during entry upload now, against the new
        // record — same Save, no return trip. A failed file never
        // blocks the battery (see landOnBattery).
        const staged: { kind: "photo" | "document" | "receipt"; files: StagedFile[]; apply: (n: StagedFile[]) => void }[] = [
          { kind: "photo", files: stagedPhotos, apply: setStagedPhotos },
          { kind: "document", files: stagedDocs, apply: setStagedDocs },
          { kind: "receipt", files: stagedReceipts, apply: setStagedReceipts },
        ];
        if (staged.some((s) => s.files.length > 0)) {
          setUploadingFiles(true);
          const failedNames: string[] = [];
          for (const group of staged) {
            if (group.files.length === 0) continue;
            const { failed } = await uploadStagedFiles(
              `/inventory/batteries/${created.id}`,
              group.kind,
              group.files,
              group.apply,
            );
            failedNames.push(...failed.map((f) => f.file.name));
          }
          setUploadingFiles(false);
          failedFileNames.current = failedNames.length > 0 ? failedNames : null;
        }
        let enabled: ShareGroupState[] = [];
        try {
          const overview = await api<SharingOverview>("/core/sharing");
          enabled = enabledShareGroups(overview);
        } catch {
          enabled = [];
        }
        if (enabled.length > 0) {
          // Groups whose RULES already cover the new battery need
          // no pick — the prompt says so instead (Package C).
          setPromptChecked(
            new Set(
              enabled
                .filter(
                  (g) =>
                    !(g.resolved_items ?? []).some((r) => r.id === created.id),
                )
                .map((g) => g.recipient_group),
            ),
          );
          setPromptRuleChecked(new Set());
          setSharePrompt({ battery: created, groups: enabled });
        } else {
          landOnBattery(created.id);
        }
      }
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.code === "possible_duplicate" &&
        !force
      ) {
        const existing = err.detail?.existing;
        setDuplicate(Array.isArray(existing) ? (existing as typeof duplicate) : []);
        return;
      }
      setError(
        err instanceof ApiError ? err.message : "Couldn't save the battery.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function refreshBattery() {
    if (!id) return;
    try {
      const b = await api<Battery>(`/inventory/batteries/${id}`);
      setSavedBattery(b);
    } catch {
      /* attachments list will refresh on next visit */
    }
  }

  /** Land on a freshly created battery's page, surfacing the
   *  failed-file warning if any staged file didn't make it. Every
   *  exit from the create flow funnels through here. */
  function landOnBattery(batteryId: string) {
    navigate(`/inventory/batteries/${batteryId}`, { replace: true });
    const failed = failedFileNames.current;
    failedFileNames.current = null;
    if (failed && failed.length > 0) {
      const { title, message } = fileFailureToast("battery", "file", failed);
      toast(message, { title, tone: "warning", duration: 12000 });
    }
  }

  function skipSharePrompt() {
    if (!sharePrompt) return;
    const batteryId = sharePrompt.battery.id;
    setSharePrompt(null);
    landOnBattery(batteryId);
  }

  async function confirmSharePrompt() {
    if (!sharePrompt) return;
    setPromptError(null);
    setPromptBusy(true);
    try {
      for (const group of sharePrompt.groups) {
        // Share by rule (Package C): a category rule for this
        // battery's category — this battery and future ones alike.
        if (
          promptRuleChecked.has(group.recipient_group) &&
          sharePrompt.battery.category
        ) {
          await api(`/core/sharing/${group.recipient_group}/rules`, {
            method: "POST",
            body: JSON.stringify({
              scope: "category",
              scope_value: sharePrompt.battery.category,
              include_addons: false,
            }),
          });
        }
        if (!promptChecked.has(group.recipient_group)) continue;
        await api(`/core/sharing/${group.recipient_group}/items`, {
          method: "PUT",
          body: JSON.stringify({
            tool_ids: [...group.shared_tool_ids],
            battery_ids: [...group.shared_battery_ids, sharePrompt.battery.id],
            set_choices: group.set_choices,
          }),
        });
      }
      const batteryId = sharePrompt.battery.id;
      setSharePrompt(null);
      landOnBattery(batteryId);
    } catch (err) {
      setPromptError(
        err instanceof ApiError
          ? err.message
          : "Couldn't update the shared list. The battery itself is saved.",
      );
    } finally {
      setPromptBusy(false);
    }
  }

  const photos = (savedBattery?.attachments ?? []).filter((a) => a.kind === "photo");

  return (
    <div style={{ maxWidth: "760px", margin: "0 auto", display: "grid", gap: "var(--spacing)" }}>
      <div>
        <Breadcrumbs
          items={[
            { label: "Inventory", to: "/inventory" },
            ...(editing && savedBattery
              ? [
                  {
                    label: savedBattery.name,
                    to: `/inventory/batteries/${id}`,
                  },
                ]
              : []),
            { label: editing ? "Edit battery" : "Add a battery" },
          ]}
        />
        <h1 style={{ margin: "0.25rem 0 0", fontSize: "1.5rem" }}>
          {editing ? "Edit battery" : "Add a battery"}
        </h1>
      </div>

      {loadError && <Alert tone="danger">{loadError}</Alert>}

      {loading ? (
        <p
          style={{
            color: "var(--text-muted)",
            display: "flex",
            gap: "var(--space-2)",
            alignItems: "center",
          }}
        >
          <Spinner size="sm" /> Loading…
        </p>
      ) : (
        <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--spacing)" }}>
          <Panel title="Basics">
            <div style={formGridStyle}>
              <FormField label="Name" htmlFor="bf-name" required error={fieldErrors.name}>
                <TextInput
                  id="bf-name"
                  invalid={Boolean(fieldErrors.name)}
                  value={values.name}
                  onChange={(e) => set("name", e.target.value)}
                />
              </FormField>
              <FormField label="Brand (manufacturer)" htmlFor="bf-brand">
                <FieldSuggest
                  field="brand"
                  id="bf-brand"
                  value={values.brand}
                  onChange={(v) => set("brand", v)}
                />
              </FormField>
              <FormField label="Model" htmlFor="bf-model">
                <TextInput
                  id="bf-model"
                  value={values.model}
                  onChange={(e) => set("model", e.target.value)}
                />
              </FormField>
              <FormField label="Serial number" htmlFor="bf-serial">
                <TextInput
                  id="bf-serial"
                  value={values.serial_number}
                  onChange={(e) => set("serial_number", e.target.value)}
                />
              </FormField>
              <FormField label="Category" htmlFor="bf-category">
                <CategoryPicker
                  id="bf-category"
                  value={values.category}
                  onChange={(v) => set("category", v)}
                  defaultSystemKey={id ? undefined : "batteries"}
                />
              </FormField>
              <FormField label="Storage location" htmlFor="bf-location">
                <LocationTreePicker
                  id="bf-location"
                  value={values.location_id || null}
                  valueLabel={savedBattery?.location || undefined}
                  onChange={(locationId) => set("location_id", locationId ?? "")}
                />
              </FormField>
              <DealerPicker
                id="bf-dealer"
                label="Dealer (bought from)"
                hint="The company you bought it from — used for dealer contacts and warranty help."
                value={values.dealer_company_id}
                valueLabel={savedBattery?.dealer_company_name ?? undefined}
                onChange={(companyId) => set("dealer_company_id", companyId)}
                onAvailability={setDealersAvailable}
                onCompany={(company) => {
                  setDealerCompany(company);
                  setDealerKnown(true);
                }}
              />
            </div>
          </Panel>

          {!editing && (
            <QuickAddPanel
              kind="battery"
              brand={values.brand}
              model={values.model}
              upc={values.upc}
              onUpcChange={(v) => set("upc", v)}
              onApply={applyQuickAdd}
            />
          )}
          {editing && (
            <Panel title="Barcode">
              <FormField label="UPC / barcode" htmlFor="bf-upc">
                <TextInput
                  id="bf-upc"
                  value={values.upc}
                  onChange={(e) => set("upc", e.target.value)}
                  placeholder="The number under the barcode"
                  inputMode="numeric"
                />
              </FormField>
            </Panel>
          )}

          <Panel title="Tags">
            {tags.length === 0 && values.tag_ids.length === 0 ? (
              <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
                No tags yet — create your first below.
              </p>
            ) : (
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.7rem" }}>
                {tags.map((tag) => {
                  const selected = values.tag_ids.includes(tag.id);
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      aria-pressed={selected}
                      onClick={() =>
                        set(
                          "tag_ids",
                          selected
                            ? values.tag_ids.filter((t) => t !== tag.id)
                            : [...values.tag_ids, tag.id],
                        )
                      }
                      style={{
                        background: "none",
                        border: "none",
                        padding: 0,
                        cursor: "pointer",
                        opacity: selected ? 1 : 0.55,
                      }}
                    >
                      <TagChip name={tag.name} color={tag.color} selected={selected} />
                    </button>
                  );
                })}
              </div>
            )}
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 180px" }}>
                <FieldSuggest
                  field="tag"
                  value={newTagName}
                  onChange={setNewTagName}
                  placeholder="New tag name"
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void createTag()}
                loading={tagBusy}
                disabled={!newTagName.trim()}
              >
                Add tag
              </Button>
            </div>
          </Panel>

          <Panel title="Use">
            <Checkbox
              name="bf-business-use"
              label="Business use: this battery earns its keep (used for work you charge for)"
              checked={values.business_use}
              onChange={(e) => set("business_use", e.target.checked)}
            />
          </Panel>

          <Panel title="Maintenance">
            <Checkbox
              name="bf-schedule"
              label="Add a first maintenance schedule (calibration, service, inspection…)"
              checked={schedOn}
              onChange={(e) => setSchedOn(e.target.checked)}
            />
            {schedOn && (
              <div style={{ ...formGridStyle, marginTop: "0.8rem" }}>
                <FormField label="Kind" htmlFor="bf-sched-kind">
                  <Select
                    id="bf-sched-kind"
                    value={schedKind}
                    onChange={(e) => setSchedKind(e.target.value as InitialSchedule["kind"])}
                  >
                    <option value="calibration">Calibration</option>
                    <option value="service">Service</option>
                    <option value="inspection">Inspection</option>
                    <option value="other">Other</option>
                  </Select>
                </FormField>
                <FormField label="Label" htmlFor="bf-sched-label">
                  <TextInput
                    id="bf-sched-label"
                    value={schedLabel}
                    onChange={(e) => setSchedLabel(e.target.value)}
                    placeholder="e.g. Annual calibration"
                  />
                </FormField>
                <FormField
                  label="Every (days)"
                  htmlFor="bf-sched-interval"
                  hint="An interval or a due date — one of the two is required."
                >
                  <TextInput
                    id="bf-sched-interval"
                    type="number"
                    min="1"
                    step="1"
                    value={schedInterval}
                    onChange={(e) => setSchedInterval(e.target.value)}
                  />
                </FormField>
                <FormField label="First due date" htmlFor="bf-sched-due">
                  <DatePicker
                    id="bf-sched-due"
                    value={schedDue}
                    onChange={setSchedDue}
                    clearable
                  />
                </FormField>
              </div>
            )}
          </Panel>

          <Panel title="Battery details">
            <div style={formGridStyle}>
              <FormField
                label="Platform"
                htmlFor="bf-platform"
                hint="The battery family, e.g. M18, 20V MAX, FlexVolt."
              >
                <TextInput
                  id="bf-platform"
                  value={values.platform}
                  onChange={(e) => set("platform", e.target.value)}
                />
              </FormField>
              <FormField label="Voltage" htmlFor="bf-voltage">
                <TextInput
                  id="bf-voltage"
                  inputMode="decimal"
                  value={values.voltage}
                  onChange={(e) => set("voltage", e.target.value)}
                />
              </FormField>
              <FormField label="Capacity (Ah)" htmlFor="bf-capacity">
                <TextInput
                  id="bf-capacity"
                  inputMode="decimal"
                  value={values.capacity_ah}
                  onChange={(e) => set("capacity_ah", e.target.value)}
                />
              </FormField>
              <FormField
                label="Chemistry"
                htmlFor="bf-chemistry"
                hint="e.g. Li-ion, NiCd, NiMH."
              >
                <TextInput
                  id="bf-chemistry"
                  value={values.chemistry}
                  onChange={(e) => set("chemistry", e.target.value)}
                />
              </FormField>
              <WarrantyFields
                idPrefix="bf"
                values={values}
                onChange={(field, value) => set(field, value)}
                dealerCompany={dealerCompany}
                dealerKnown={dealerKnown}
                resetKey={id ?? "new"}
              />
              <FormField
                label="Currently in"
                htmlFor="bf-in-tool"
                hint="Which tool this battery is sitting in right now, if any."
              >
                <Select
                  id="bf-in-tool"
                  value={values.currently_in_tool_id}
                  onChange={(e) => set("currently_in_tool_id", e.target.value)}
                >
                  <option value="">Not in a tool</option>
                  {tools.map((tool) => (
                    <option key={tool.id} value={tool.id}>
                      {tool.name}
                      {[tool.brand, tool.model].filter(Boolean).length > 0
                        ? ` — ${[tool.brand, tool.model].filter(Boolean).join(" ")}`
                        : ""}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </Panel>

          <Panel title="Cost details">
            <div style={formGridStyle}>
              <FormField label="Purchase price (each)" htmlFor="bf-price">
                <TextInput
                  id="bf-price"
                  inputMode="decimal"
                  value={values.purchase_price}
                  onChange={(e) => set("purchase_price", e.target.value)}
                />
              </FormField>
              <FormField label="Quantity" htmlFor="bf-qty">
                <TextInput
                  id="bf-qty"
                  type="number"
                  min="1"
                  step="1"
                  value={values.quantity}
                  onChange={(e) => set("quantity", e.target.value)}
                />
              </FormField>
              <FormField label="Purchase date" htmlFor="bf-date">
                <DatePicker
                  id="bf-date"
                  value={values.purchase_date}
                  onChange={(v) => set("purchase_date", v)}
                  clearable
                />
              </FormField>
              <FormField label="Replacement cost" htmlFor="bf-replacement">
                <TextInput
                  id="bf-replacement"
                  inputMode="decimal"
                  value={values.replacement_cost}
                  onChange={(e) => set("replacement_cost", e.target.value)}
                />
              </FormField>
              <FormField label="Current market price (MSRP)" htmlFor="bf-msrp">
                <TextInput
                  id="bf-msrp"
                  inputMode="decimal"
                  value={values.msrp}
                  onChange={(e) => set("msrp", e.target.value)}
                />
              </FormField>
            </div>
            <div style={{ marginTop: "1rem" }}>
              <FormField label="Notes" htmlFor="bf-notes">
                <TextArea
                  id="bf-notes"
                  rows={3}
                  value={values.notes}
                  onChange={(e) => set("notes", e.target.value)}
                />
              </FormField>
            </div>
          </Panel>

          {definitions.length > 0 && (
            <Panel title="Custom fields">
              <div style={formGridStyle}>
                {definitions.map((def) => (
                  <CustomFieldInput
                    key={def.id}
                    def={def}
                    value={values.custom_data[def.id]}
                    onChange={(v) =>
                      set("custom_data", { ...values.custom_data, [def.id]: v })
                    }
                  />
                ))}
              </div>
            </Panel>
          )}

          {editing && savedBattery && (
            <>
              <Panel title="Photos">
                {photos.length > 0 && (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                      gap: "var(--space-3)",
                      marginBottom: "var(--space-3)",
                    }}
                  >
                    {photos.map((a) => (
                      <FramedImage key={a.key} src={a.url} alt={a.filename} />
                    ))}
                  </div>
                )}
                <PhotoUploader
                  toolId={savedBattery.id}
                  basePath={`/inventory/batteries/${savedBattery.id}`}
                  kind="photo"
                  onUploaded={refreshBattery}
                />
              </Panel>
              <Panel title="Documents">
                <PhotoUploader
                  toolId={savedBattery.id}
                  basePath={`/inventory/batteries/${savedBattery.id}`}
                  kind="document"
                  onUploaded={refreshBattery}
                  existing={(savedBattery.attachments ?? []).filter((a) => a.kind === "document")}
                />
              </Panel>
              <Panel title="Receipts">
                <PhotoUploader
                  toolId={savedBattery.id}
                  basePath={`/inventory/batteries/${savedBattery.id}`}
                  kind="receipt"
                  onUploaded={refreshBattery}
                  existing={(savedBattery.attachments ?? []).filter((a) => a.kind === "receipt")}
                />
              </Panel>
            </>
          )}

          {!editing && (
            <>
              <Panel title="Photos">
                <StagedFilePicker
                  kind="photo"
                  files={stagedPhotos}
                  onChange={setStagedPhotos}
                  disabled={busy}
                />
              </Panel>
              <Panel title="Documents">
                <StagedFilePicker
                  kind="document"
                  files={stagedDocs}
                  onChange={setStagedDocs}
                  disabled={busy}
                />
              </Panel>
              <Panel title="Receipts">
                <StagedFilePicker
                  kind="receipt"
                  files={stagedReceipts}
                  onChange={setStagedReceipts}
                  disabled={busy}
                />
              </Panel>
            </>
          )}

          {duplicate.length > 0 && (
            <Panel title="You already have one like this">
              {duplicate.map((existing) => (
                <p key={existing.id} style={{ marginTop: 0 }}>
                  <strong>{existing.name}</strong> — {existing.brand}{" "}
                  {existing.model}
                  {existing.serial_number
                    ? `, serial ${existing.serial_number}`
                    : ""}
                  <span className="tv-muted">
                    {" "}
                    (matched on the {existing.matched_on})
                  </span>
                </p>
              ))}
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setDuplicate([]);
                    void onSubmit(undefined, true);
                  }}
                >
                  Add anyway
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() =>
                    navigate(`/inventory/batteries/${duplicate[0].id}`)
                  }
                >
                  Open the existing one
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setDuplicate([])}
                >
                  Keep editing
                </Button>
              </div>
            </Panel>
          )}
          {error && <Alert tone="danger">{error}</Alert>}

          <div style={{ display: "flex", gap: "0.75rem" }}>
            {/* The floating save (dashboard-flare lane,
                2026-11-09): same long-form pattern as the tool
                form — the submit's twin pins bottom-right once
                the seated one scrolls out of view. */}
            <StickySaveButton type="submit" loading={busy}>
              {busy && uploadingFiles
                ? `Uploading files… (${[...stagedPhotos, ...stagedDocs, ...stagedReceipts].filter((p) => p.status === "done").length} of ${stagedPhotos.length + stagedDocs.length + stagedReceipts.length})`
                : editing
                  ? "Save changes"
                  : "Add battery"}
            </StickySaveButton>
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                navigate(
                  editing ? `/inventory/batteries/${id}` : "/inventory",
                  { replace: true },
                )
              }
            >
              Cancel
            </Button>
          </div>
        </form>
      )}

      <Modal
        open={sharePrompt !== null}
        onClose={skipSharePrompt}
        title="Add to your shared list?"
        footer={
          <>
            <Button
              variant="secondary"
              onClick={skipSharePrompt}
              disabled={promptBusy}
            >
              Not now
            </Button>
            <Button onClick={confirmSharePrompt} loading={promptBusy}>
              Add
            </Button>
          </>
        }
      >
        {sharePrompt && (
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <p style={{ margin: 0 }}>
              You're sharing your list with{" "}
              {sharePrompt.groups
                .map((g) => accountTypeLabel(g.recipient_group))
                .join(" and ")}
              . Add "{sharePrompt.battery.name}" to the shared items?
            </p>
            {promptError && <Alert tone="danger">{promptError}</Alert>}
            <div style={{ display: "grid", gap: "0.35rem" }}>
              {sharePrompt.groups.map((g) => {
                const alreadyShared = (g.resolved_items ?? []).some(
                  (r) => r.id === sharePrompt.battery.id,
                );
                const category = (sharePrompt.battery.category ?? "").trim();
                const hasCategoryRule = (g.rules ?? []).some(
                  (r) =>
                    r.scope === "category" &&
                    r.scope_value.trim().toLowerCase() ===
                      category.toLowerCase(),
                );
                return (
                  <div key={g.recipient_group}>
                    {alreadyShared ? (
                      <p style={{ margin: 0, color: "var(--text-muted)" }}>
                        Already shared with{" "}
                        {accountTypeLabel(g.recipient_group)} — one of
                        your sharing rules covers it.
                      </p>
                    ) : (
                      <Checkbox
                        name={`share-prompt-${g.recipient_group}`}
                        label={`Share with ${accountTypeLabel(g.recipient_group)}`}
                        checked={promptChecked.has(g.recipient_group)}
                        onChange={(e) =>
                          setPromptChecked((prev) => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(g.recipient_group);
                            else next.delete(g.recipient_group);
                            return next;
                          })
                        }
                      />
                    )}
                    {!alreadyShared && category && !hasCategoryRule && (
                      <div style={{ marginLeft: "1.6rem" }}>
                        <Checkbox
                          name={`share-prompt-rule-${g.recipient_group}`}
                          label={`Share by rule: the whole “${category}” category with ${accountTypeLabel(g.recipient_group)}, future items too`}
                          checked={promptRuleChecked.has(g.recipient_group)}
                          onChange={(e) =>
                            setPromptRuleChecked((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked)
                                next.add(g.recipient_group);
                              else next.delete(g.recipient_group);
                              return next;
                            })
                          }
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
