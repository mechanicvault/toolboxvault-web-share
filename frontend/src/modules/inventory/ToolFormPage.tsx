import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Breadcrumbs,
  Button,
  Checkbox,
  DatePicker,
  FormField,
  formGridStyle,
  Modal,
  Panel,
  Select,
  StickySaveButton,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  LinkButton,
  ProgressBar,
} from "../../components";
import { TagChip } from "../../components";
import { api, ApiError } from "../../lib/api";
import { useFixFocus } from "../../lib/fixFocus";
import { todayLocalIso } from "../../lib/format";
import {
  accountTypeLabel,
  enabledShareGroups,
  RequireAuth,
  type ShareGroupState,
  type SharingOverview,
} from "../core";
import { DealerPicker } from "../dealers/components/DealerFields";
import type { DealerCompany } from "../dealers/types";
import {
  AttachedToolsPicker,
  pickFromAttached,
  type AttachedPick,
} from "./components/AttachedToolsPicker";
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
import { money } from "./format";
import type {
  FieldDefinition,
  InitialSchedule,
  SetPieceInline,
  Tag,
  Tool,
  ToolFormValues,
} from "./types";

const EMPTY: ToolFormValues = {
  name: "",
  brand: "",
  model: "",
  serial_number: "",
  category: "",
  location_id: "",
  notes: "",
  purchase_price: "",
  purchase_date: "",
  replacement_cost: "",
  msrp: "",
  warranty_months: "",
  warranty_provider: "",
  warranty_contact: "",
  warranty_terms: "",
  warranty_type: "",
  quantity: "1",
  size: "",
  model_numbers: [""],
  serial_numbers: [""],
  upc: "",
  consumable: false,
  business_use: false,
  rebuy_store: "",
  rebuy_url: "",
  rebuy_sku: "",
  rebuy_notes: "",
  is_set: false,
  dealer_company_id: "",
  tag_ids: [],
  custom_data: {},
};

function listOrBlank(list: string[]): string[] {
  return list.length > 0 ? [...list] : [""];
}

/** One editable piece row of the inline set editor. Every piece
 *  may carry its own price + purchase date (owner 2026-10-25). */
export interface PieceDraft {
  id?: string;
  kind: "core" | "addon";
  name: string;
  part_number: string;
  serial_number: string;
  status: "present" | "missing" | "sold" | "removed";
  price: string;
  purchase_date: string;
}

export function blankPiece(kind: "core" | "addon"): PieceDraft {
  return {
    kind,
    name: "",
    part_number: "",
    serial_number: "",
    status: "present",
    price: "",
    /* A NEW piece starts on today (owner's date rule, 2026-11-04);
     * existing pieces load their saved date via
     * pieceDraftsFromTool, untouched. Clearable — a piece's date
     * may legitimately stay unknown (submits null). */
    purchase_date: todayLocalIso(),
  };
}

function pieceDraftsFromTool(t: Tool): PieceDraft[] {
  if (!t.set) return [];
  return [...t.set.core_pieces, ...t.set.addon_pieces]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((p) => ({
      id: p.id,
      kind: p.kind,
      name: p.name,
      part_number: p.part_number,
      serial_number: p.serial_number,
      status: p.status,
      price: p.price ?? "",
      purchase_date: p.purchase_date ?? "",
    }));
}

function fromTool(t: Tool): ToolFormValues {
  return {
    name: t.name,
    brand: t.brand,
    model: t.model,
    serial_number: t.serial_number,
    category: t.category,
    location_id: t.location_id ?? "",
    notes: t.notes,
    purchase_price: t.purchase_price ?? "",
    purchase_date: t.purchase_date ?? "",
    replacement_cost: t.replacement_cost ?? "",
    msrp: t.msrp ?? "",
    warranty_months: t.warranty_months === null || t.warranty_months === undefined ? "" : String(t.warranty_months),
    warranty_provider: t.warranty_provider ?? "",
    warranty_contact: t.warranty_contact ?? "",
    warranty_terms: t.warranty_terms ?? "",
    warranty_type: t.warranty_type ?? "",
    quantity: String(t.quantity ?? 1),
    size: t.size ?? "",
    model_numbers: listOrBlank(t.model_numbers ?? []),
    serial_numbers: listOrBlank(t.serial_numbers ?? []),
    upc: t.upc ?? "",
    consumable: t.consumable ?? false,
    business_use: t.business_use ?? false,
    rebuy_store: t.rebuy_store ?? "",
    rebuy_url: t.rebuy_url ?? "",
    rebuy_sku: t.rebuy_sku ?? "",
    rebuy_notes: t.rebuy_notes ?? "",
    is_set: t.is_set ?? false,
    dealer_company_id: t.dealer_company_id ?? "",
    tag_ids: (t.tags ?? []).map((tag) => tag.id),
    custom_data: { ...t.custom_data },
  };
}

/** Repeatable text inputs for the multi-value numbers (the app's
 *  "Add model #" / "Add serial #" pattern). The first entry is the
 *  primary, shown everywhere a single value is expected. */
export function RepeatableInputs({
  idPrefix,
  label,
  addLabel,
  values,
  onChange,
}: {
  idPrefix: string;
  label: string;
  addLabel: string;
  values: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <FormField label={label} htmlFor={`${idPrefix}-0`}>
      <div style={{ display: "grid", gap: "0.4rem" }}>
        {values.map((value, i) => (
          <div key={i} style={{ display: "flex", gap: "0.4rem" }}>
            <TextInput
              id={`${idPrefix}-${i}`}
              value={value}
              onChange={(e) =>
                onChange(values.map((v, idx) => (idx === i ? e.target.value : v)))
              }
              placeholder={i === 0 ? "Primary" : `Another ${label.toLowerCase()}`}
            />
            {values.length > 1 && (
              <button
                type="button"
                className="tv-list-remove-btn"
                aria-label={`Remove entry ${i + 1}`}
                title={`Remove entry ${i + 1}`}
                onClick={() => onChange(values.filter((_, idx) => idx !== i))}
              >
                {"−"}
              </button>
            )}
          </div>
        ))}
        <div>
          <button
            type="button"
            onClick={() => onChange([...values, ""])}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              color: "var(--accent)",
              cursor: "pointer",
              fontSize: "0.85rem",
              fontWeight: 600,
            }}
          >
            + {addLabel}
          </button>
        </div>
      </div>
    </FormField>
  );
}

/** Add/edit form. Custom fields render from the field definitions.
 *  Files are picked DURING entry in both modes: edit mode uploads
 *  against the existing record; add mode stages the files (photos,
 *  documents AND receipts) and uploads them against the new record
 *  as part of the same Save. */
export default function ToolFormPage() {
  const { id } = useParams<{ id: string }>();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const { toast } = useToast();
  /* The health check's Fix-it deep links (owner 2026-11-05):
   * the hash names the gap — land on its exact field, focused
   * and highlighted (lib/fixFocus). */
  useFixFocus((hash) => {
    if (hash === "fix-model") return "tf-model-0";
    if (hash === "fix-purchase-date") return "tf-pdate";
    if (hash.startsWith("fix-piece-"))
      return `tf-piece-serial-${hash.slice("fix-piece-".length)}`;
    return null;
  });

  /* Create mode opens with the purchase date on today (owner's
   * date rule, 2026-11-04); edit mode replaces these values with
   * the record's saved ones in the load effect below. */
  const [values, setValues] = useState<ToolFormValues>(() =>
    id ? EMPTY : { ...EMPTY, purchase_date: todayLocalIso() },
  );
  const [defs, setDefs] = useState<FieldDefinition[]>([]);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* F2-21: the pre-render double-submit guard — a ref flag set
   * synchronously at the top of onSubmit, because the state-driven
   * disabled button only exists after React re-renders, and clicks
   * landing in that window used to create duplicate tools. */
  const busyRef = useRef(false);
  const [loading, setLoading] = useState(true);
  const [savedTool, setSavedTool] = useState<Tool | null>(null);
  // Duplicate detection (wave 4): the create 409's candidates.
  const [duplicate, setDuplicate] = useState<{
    id: string;
    name: string;
    brand: string;
    model: string;
    serial_number: string;
    matched_on: string;
  }[]>([]);
  // Tags: the owner's vocabulary + inline create.
  const [tags, setTags] = useState<Tag[]>([]);
  const [newTagName, setNewTagName] = useState("");
  const [tagBusy, setTagBusy] = useState(false);
  // Inline set editor (Package B): the set's piece rows, edited
  // in this form and submitted with the save.
  const [pieces, setPieces] = useState<PieceDraft[]>([]);
  // Build-a-set from inventory (2026-10-25): existing tools picked
  // to fold into this set; submitted as attach_tool_ids.
  const [attachedPicks, setAttachedPicks] = useState<AttachedPick[]>([]);
  // Optional first maintenance schedule (Package B).
  const [schedOn, setSchedOn] = useState(false);
  const [schedKind, setSchedKind] = useState<InitialSchedule["kind"]>("service");
  const [schedLabel, setSchedLabel] = useState("");
  const [schedInterval, setSchedInterval] = useState("");
  const [schedDue, setSchedDue] = useState("");
  // Whether the dealers module answered (drives whether the save
  // payload carries dealer_company_id at all — see DealerPicker).
  const [dealersAvailable, setDealersAvailable] = useState(false);
  // The picked dealer's full record + whether the picker has
  // reported at all — the warranty fields prefill provider/contact
  // from it (see WarrantyFields).
  const [dealerCompany, setDealerCompany] = useState<DealerCompany | null>(null);
  const [dealerKnown, setDealerKnown] = useState(false);
  // Files staged in the add form (no record to attach them to yet).
  const [stagedPhotos, setStagedPhotos] = useState<StagedFile[]>([]);
  const [stagedDocs, setStagedDocs] = useState<StagedFile[]>([]);
  const [stagedReceipts, setStagedReceipts] = useState<StagedFile[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  // Names of files that failed to upload after a create; the warning
  // toast fires when the create flow lands on the detail page (which
  // may be after the share prompt is answered).
  const failedFileNames = useRef<string[] | null>(null);

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
  // Consent-sharing prompt (create flow only): set when the new tool
  // exists and the owner actively shares with at least one group.
  const [sharePrompt, setSharePrompt] = useState<{
    tool: Tool;
    groups: ShareGroupState[];
  } | null>(null);
  const [promptChecked, setPromptChecked] = useState<Set<string>>(new Set());
  /** Package C: groups where the owner chose "share by rule" in
   *  the prompt — a category rule covering this tool (and future
   *  ones) instead of / alongside the one-off pick. */
  const [promptRuleChecked, setPromptRuleChecked] = useState<Set<string>>(
    new Set(),
  );
  const [promptBusy, setPromptBusy] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);

  useEffect(() => {
    const defsReq = api<FieldDefinition[]>("/inventory/field-definitions?item_type=tool");
    const toolReq = id ? api<Tool>(`/inventory/${id}`) : Promise.resolve(null);
    Promise.all([defsReq, toolReq])
      .then(([d, t]) => {
        setDefs([...d].sort((a, b) => a.sort_order - b.sort_order));
        if (t) {
          setValues(fromTool(t));
          setSavedTool(t);
          setPieces(pieceDraftsFromTool(t));
          setAttachedPicks((t.set?.attached_tools ?? []).map(pickFromAttached));
        }
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load the form."),
      )
      .finally(() => setLoading(false));
    // Vocabulary loads are best-effort: a failure never blocks the form.
    api<Tag[]>("/inventory/tags").then(setTags).catch(() => setTags([]));
  }, [id]);

  function set<K extends keyof ToolFormValues>(key: K, value: ToolFormValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
    /* F2-16: fixing a field clears ITS error immediately — the
     * error text and aria-invalid must not linger until the next
     * submit telling the user a fixed field is still wrong. */
    setFieldErrors((prev) => {
      if (key === "custom_data") {
        const next = { ...prev };
        let changed = false;
        for (const k of Object.keys(next)) {
          if (k !== "name" && k !== "quantity") { delete next[k]; changed = true; }
        }
        return changed ? next : prev;
      }
      if (!prev[key as string]) return prev;
      const next = { ...prev };
      delete next[key as string];
      return next;
    });
  }

  function setPiece(index: number, patch: Partial<PieceDraft>) {
    setPieces((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
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

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (!values.name.trim()) errs.name = "Give the tool a name.";
    const qty = Number(values.quantity);
    if (!Number.isInteger(qty) || qty < 1) errs.quantity = "Quantity is a whole number, 1 or more.";
    for (const def of defs) {
      if (!def.required) continue;
      const v = values.custom_data[def.id];
      const empty =
        v === null || v === undefined || v === "" || (def.field_type === "boolean" && v !== true && v !== false);
      if (empty) errs[def.id] = `${def.label} is required.`;
    }
    /* F2-12: the schedule and set-piece checks live HERE, before
     * any busy state is set — they used to be early returns after
     * setBusy(true), stranding the form in disabled "Saving…"
     * forever with reload (and a lost entry) as the only escape. */
    if (values.is_set && pieces.some((piece) => !piece.name.trim())) {
      setError("Every set piece needs a name — fill it in or remove the row.");
      setFieldErrors(errs);
      return false;
    }
    if (schedOn && !schedInterval && !schedDue) {
      setError("The first maintenance schedule needs an interval or a due date.");
      setFieldErrors(errs);
      return false;
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  /** F2-14: after a failed submit, focus moves to the first
   *  problem field instead of staying on the submit button. */
  function focusFirstError(errs: Record<string, string>) {
    const order = ["name", "quantity", ...Object.keys(errs)];
    for (const key of order) {
      if (!(key in errs)) continue;
      const id = key === "name" ? "tf-name" : key === "quantity" ? "tf-qty" : `cf-${key}`;
      const el = document.getElementById(id);
      if (el) { el.focus(); return; }
    }
    if (values.is_set && pieces.some((piece) => !piece.name.trim())) {
      document.querySelector<HTMLInputElement>('input[aria-label$="name"]')?.focus();
      return;
    }
    if (schedOn && !schedInterval && !schedDue) {
      document.getElementById("tf-sched-interval")?.focus();
    }
  }

  function applyQuickAdd(valuesIn: QuickAddValues) {
    if (valuesIn.name !== undefined) set("name", valuesIn.name);
    if (valuesIn.brand !== undefined) set("brand", valuesIn.brand);
    if (valuesIn.model !== undefined) set("model_numbers", [valuesIn.model]);
    if (valuesIn.category !== undefined) set("category", valuesIn.category);
    if (valuesIn.size !== undefined) set("size", valuesIn.size);
    if (valuesIn.msrp !== undefined) set("msrp", valuesIn.msrp);
    if (valuesIn.description !== undefined) set("notes", valuesIn.description);
  }

  async function onSubmit(e?: FormEvent, force = false) {
    e?.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setError("");
    if (!validate()) {
      busyRef.current = false;
      // validate() has just stored the errors; read them back from
      // the known checks for the focus move.
      const errs: Record<string, string> = {};
      if (!values.name.trim()) errs.name = "name";
      const qty = Number(values.quantity);
      if (!Number.isInteger(qty) || qty < 1) errs.quantity = "quantity";
      for (const def of defs) {
        if (!def.required) continue;
        const v = values.custom_data[def.id];
        if (v === null || v === undefined || v === "") errs[def.id] = def.id;
      }
      focusFirstError(errs);
      return;
    }
    setBusy(true);
    const cleanList = (list: string[]) =>
      list.map((v) => v.trim()).filter((v, i, all) => v && all.indexOf(v) === i);
    const modelNumbers = cleanList(values.model_numbers);
    const serialNumbers = cleanList(values.serial_numbers);
    const payload: Record<string, unknown> = {
      name: values.name.trim(),
      brand: values.brand.trim(),
      model: modelNumbers[0] ?? "",
      serial_number: serialNumbers[0] ?? "",
      model_numbers: modelNumbers,
      serial_numbers: serialNumbers,
      category: values.category.trim(),
      location_id: values.location_id || null,
      notes: values.notes,
      purchase_price: values.purchase_price === "" ? null : values.purchase_price,
      purchase_date: values.purchase_date === "" ? null : values.purchase_date,
      replacement_cost: values.replacement_cost === "" ? null : values.replacement_cost,
      msrp: values.msrp === "" ? null : values.msrp,
      warranty_months: values.warranty_months === "" ? null : Number(values.warranty_months),
      warranty_provider: values.warranty_provider.trim(),
      warranty_contact: values.warranty_contact.trim(),
      warranty_terms: values.warranty_terms.trim(),
      warranty_type: values.warranty_type === "" ? null : values.warranty_type,
      quantity: Number(values.quantity) || 1,
      upc: values.upc.trim(),
      size: values.size.trim(),
      consumable: values.consumable,
      business_use: values.business_use,
      rebuy_store: values.rebuy_store.trim(),
      rebuy_url: values.rebuy_url.trim(),
      rebuy_sku: values.rebuy_sku.trim(),
      rebuy_notes: values.rebuy_notes.trim(),
      is_set: values.is_set,
      tag_ids: values.tag_ids,
      custom_data: values.custom_data,
    };
    // The dealer tag rides ONLY when the dealers module answered:
    // while it's off the stored tag must survive unrelated edits.
    if (dealersAvailable) {
      payload.dealer_company_id = values.dealer_company_id || null;
    }
    // Inline set editor (Package B): while this is a set, the rows
    // ride the save and REPLACE the set's pieces exactly. Unmarking
    // a set that still has pieces must submit pieces: [] explicitly
    // — otherwise the backend refuses the save (422).
    if (values.is_set) {
      payload.pieces = pieces.map(
        (p, i): SetPieceInline => ({
          ...(p.id ? { id: p.id } : {}),
          kind: p.kind,
          name: p.name.trim(),
          part_number: p.part_number.trim(),
          serial_number: p.serial_number.trim(),
          status: p.status,
          // Every piece may carry its own price (2026-10-25).
          price: p.price === "" ? null : p.price,
          purchase_date: p.purchase_date || null,
          sort_order: i,
        }),
      );
      // Build-a-set from inventory: the picked tools are the set's
      // desired attached tools (attach new, detach un-picked).
      payload.attach_tool_ids = attachedPicks.map((p) => p.id);
    } else if (editing && savedTool?.set) {
      if (
        savedTool.set.core_pieces.length + savedTool.set.addon_pieces.length > 0
      ) {
        payload.pieces = [];
      }
      if (savedTool.set.attached_tools.length > 0) {
        // Unmarking the set: its folded-in tools go back to
        // standalone in the same save.
        payload.attach_tool_ids = [];
      }
    }
    // Optional first maintenance schedule (Package B): created by
    // the backend alongside the item when enabled here.
    if (schedOn) {
      payload.initial_schedule = {
        kind: schedKind,
        label: schedLabel.trim(),
        interval_days: schedInterval ? Number(schedInterval) : null,
        due_date: schedDue || null,
      } satisfies InitialSchedule;
    }
    try {
      if (editing && id) {
        const updated = await api<Tool>(`/inventory/${id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        navigate(`/inventory/${updated.id}`, { replace: true });
      } else {
        const created = await api<Tool>(
          force ? "/inventory?force=true" : "/inventory",
          {
            method: "POST",
            body: JSON.stringify(payload),
          },
        );
        // Files picked during entry upload now, against the new
        // record — same Save, no return trip. A file that fails
        // never blocks the tool: the names are kept and the user
        // lands on the detail page with a warning toast and the
        // attachment sections right there (see landOnTool).
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
              `/inventory/${created.id}`,
              group.kind,
              group.files,
              group.apply,
            );
            failedNames.push(...failed.map((f) => f.file.name));
          }
          setUploadingFiles(false);
          failedFileNames.current = failedNames.length > 0 ? failedNames : null;
        }
        // Consent sharing (owner directive 2026-10-17): if the owner
        // already shares their list with a group, ask whether the new
        // tool joins the shared items. No enabled group → no dialog,
        // ever; a failed sharing fetch must never block creation.
        let enabled: ShareGroupState[] = [];
        try {
          const overview = await api<SharingOverview>("/core/sharing");
          enabled = enabledShareGroups(overview);
        } catch {
          enabled = [];
        }
        if (enabled.length > 0) {
          // Groups whose RULES already cover the new tool need no
          // pick — the prompt says so instead of asking (Package C).
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
          setSharePrompt({ tool: created, groups: enabled });
        } else {
          landOnTool(created.id);
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
      setError(err instanceof ApiError ? err.message : "Couldn't save the tool.");
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  async function refreshTool() {
    if (!id) return;
    try {
      const t = await api<Tool>(`/inventory/${id}`);
      setSavedTool(t);
    } catch {
      /* attachments list will refresh on next visit */
    }
  }

  /** Land on a freshly created tool's page, surfacing the failed-file
   *  warning if any staged file didn't make it. Every exit from the
   *  create flow (direct, share-prompt skip, share-prompt confirm)
   *  funnels through here so the warning is never swallowed. */
  function landOnTool(toolId: string) {
    navigate(`/inventory/${toolId}`, { replace: true });
    const failed = failedFileNames.current;
    failedFileNames.current = null;
    if (failed && failed.length > 0) {
      const { title, message } = fileFailureToast("tool", "file", failed);
      toast(message, { title, tone: "warning", duration: 12000 });
    }
  }

  function skipSharePrompt() {
    if (!sharePrompt) return;
    const toolId = sharePrompt.tool.id;
    setSharePrompt(null);
    landOnTool(toolId);
  }

  async function confirmSharePrompt() {
    if (!sharePrompt) return;
    setPromptError(null);
    setPromptBusy(true);
    try {
      for (const group of sharePrompt.groups) {
        // Share by rule (Package C): a category rule for this
        // tool's category — this tool and future ones alike.
        if (
          promptRuleChecked.has(group.recipient_group) &&
          sharePrompt.tool.category
        ) {
          await api(`/core/sharing/${group.recipient_group}/rules`, {
            method: "POST",
            body: JSON.stringify({
              scope: "category",
              scope_value: sharePrompt.tool.category,
              include_addons: false,
            }),
          });
        }
        if (!promptChecked.has(group.recipient_group)) continue;
        await api(`/core/sharing/${group.recipient_group}/items`, {
          method: "PUT",
          body: JSON.stringify({
            tool_ids: [...group.shared_tool_ids, sharePrompt.tool.id],
            battery_ids: group.shared_battery_ids,
            set_choices: group.set_choices,
          }),
        });
      }
      const toolId = sharePrompt.tool.id;
      setSharePrompt(null);
      landOnTool(toolId);
    } catch (err) {
      setPromptError(
        err instanceof ApiError
          ? err.message
          : "Couldn't update the shared list. The tool itself is saved.",
      );
    } finally {
      setPromptBusy(false);
    }
  }

  const quantityNumber = Number(values.quantity);
  const unitPrice = values.purchase_price === "" ? null : Number(values.purchase_price);
  const totalPreview =
    unitPrice !== null && Number.isFinite(unitPrice) && Number.isInteger(quantityNumber) && quantityNumber > 1
      ? money(String(unitPrice * quantityNumber))
      : null;
  const stagedCount = stagedPhotos.length + stagedDocs.length + stagedReceipts.length;
  const stagedDone =
    [...stagedPhotos, ...stagedDocs, ...stagedReceipts].filter((p) => p.status === "done").length;

  return (
    <RequireAuth>
      <div style={{ maxWidth: "760px", margin: "0 auto", display: "grid", gap: "var(--spacing)" }}>
        <div>
          <Breadcrumbs
            items={[
              { label: "Inventory", to: "/inventory" },
              ...(editing && savedTool
                ? [{ label: savedTool.name, to: `/inventory/${id}` }]
                : []),
              { label: editing ? "Edit tool" : "Add a tool" },
            ]}
          />
          <h1 style={{ margin: "0.25rem 0 0", fontSize: "1.5rem" }}>
            {editing ? "Edit tool" : "Add a tool"}
          </h1>
        </div>

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
          <form onSubmit={onSubmit} noValidate style={{ display: "grid", gap: "var(--spacing)" }}>
            {busy && (
              <div style={{ display: "grid", gap: "0.35rem" }} role="status">
                <ProgressBar
                  value={stagedCount > 0 ? Math.round((stagedDone / Math.max(stagedCount, 1)) * 100) : 50}
                  label={uploadingFiles ? `Uploading files (${stagedDone} of ${stagedCount})` : "Saving"}
                />
                <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  {uploadingFiles ? `Uploading files… (${stagedDone} of ${stagedCount})` : "Saving…"}
                </span>
              </div>
            )}
            {!editing && (
              <QuickAddPanel
                kind="tool"
                brand={values.brand}
                model={values.model_numbers[0] ?? ""}
                upc={values.upc}
                onUpcChange={(v) => set("upc", v)}
                onApply={applyQuickAdd}
              />
            )}

            <Panel title="Basics">
              <div style={formGridStyle}>
                <FormField label="Name" htmlFor="tf-name" required error={fieldErrors.name}>
                  <TextInput
                    id="tf-name"
                    invalid={Boolean(fieldErrors.name)}
                    value={values.name}
                    onChange={(e) => set("name", e.target.value)}
                  />
                </FormField>
                <FormField label="Brand (manufacturer)" htmlFor="tf-brand">
                  <FieldSuggest
                    field="brand"
                    id="tf-brand"
                    value={values.brand}
                    onChange={(v) => set("brand", v)}
                  />
                </FormField>
                <RepeatableInputs
                  idPrefix="tf-model"
                  label="Model #"
                  addLabel="Add model #"
                  values={values.model_numbers}
                  onChange={(next) => set("model_numbers", next)}
                />
                <RepeatableInputs
                  idPrefix="tf-serial"
                  label="Serial #"
                  addLabel="Add serial #"
                  values={values.serial_numbers}
                  onChange={(next) => set("serial_numbers", next)}
                />
                <FormField label="Size" htmlFor="tf-size">
                  <FieldSuggest
                    field="size"
                    id="tf-size"
                    value={values.size}
                    onChange={(v) => set("size", v)}
                    placeholder="e.g. 1/2 in drive, 10 mm"
                  />
                </FormField>
                <FormField label="Category" htmlFor="tf-category">
                  <CategoryPicker
                    id="tf-category"
                    value={values.category}
                    onChange={(v) => set("category", v)}
                  />
                </FormField>
                <FormField label="Storage location" htmlFor="tf-location">
                  <LocationTreePicker
                    id="tf-location"
                    value={values.location_id || null}
                    valueLabel={savedTool?.location || undefined}
                    onChange={(locationId) => set("location_id", locationId ?? "")}
                  />
                </FormField>
                <DealerPicker
                  id="tf-dealer"
                  label="Dealer (bought from)"
                  hint="The company you bought it from — used for dealer contacts and warranty help."
                  value={values.dealer_company_id}
                  valueLabel={savedTool?.dealer_company_name ?? undefined}
                  onChange={(companyId) => set("dealer_company_id", companyId)}
                  onAvailability={setDealersAvailable}
                  onCompany={(company) => {
                    setDealerCompany(company);
                    setDealerKnown(true);
                  }}
                />
              </div>
              <div style={{ marginTop: "0.9rem", display: "grid", gap: "0.6rem" }}>
                <Checkbox
                  name="tf-consumable"
                  label="Consumable: used up in the work (blades, bits, abrasives…)"
                  checked={values.consumable}
                  onChange={(e) => set("consumable", e.target.checked)}
                />
                <Checkbox
                  name="tf-business-use"
                  label="Business use: this tool earns its keep (used for work you charge for)"
                  checked={values.business_use}
                  onChange={(e) => set("business_use", e.target.checked)}
                />
                {values.consumable && (
                  <div
                    style={{
                      display: "grid",
                      gap: "0.7rem",
                      border: "1px solid var(--edge)",
                      borderRadius: "var(--radius)",
                      padding: "0.8rem",
                    }}
                  >
                    <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: 0 }}>
                      Re-buy info — where the replacement comes from when
                      this runs out.
                    </p>
                    <div style={formGridStyle}>
                      <FormField label="Store" htmlFor="tf-rebuy-store">
                        <TextInput
                          id="tf-rebuy-store"
                          value={values.rebuy_store}
                          onChange={(e) => set("rebuy_store", e.target.value)}
                        />
                      </FormField>
                      <FormField label="Store SKU / part #" htmlFor="tf-rebuy-sku">
                        <TextInput
                          id="tf-rebuy-sku"
                          value={values.rebuy_sku}
                          onChange={(e) => set("rebuy_sku", e.target.value)}
                        />
                      </FormField>
                    </div>
                    <FormField label="Website" htmlFor="tf-rebuy-url">
                      <TextInput
                        id="tf-rebuy-url"
                        value={values.rebuy_url}
                        onChange={(e) => set("rebuy_url", e.target.value)}
                      />
                    </FormField>
                    <FormField label="Re-buy notes" htmlFor="tf-rebuy-notes">
                      <TextInput
                        id="tf-rebuy-notes"
                        value={values.rebuy_notes}
                        onChange={(e) => set("rebuy_notes", e.target.value)}
                      />
                    </FormField>
                  </div>
                )}
                <Checkbox
                  name="tf-is-set"
                  label="This is a set: a kit with its own pieces (sockets, bits…)"
                  checked={values.is_set}
                  onChange={(e) => set("is_set", e.target.checked)}
                />
                {values.is_set && (
                  <div style={{ display: "grid", gap: "0.6rem" }}>
                    <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: 0 }}>
                      The set's pieces, edited right here — this list
                      replaces the set's pieces exactly when you save.
                      Every piece can carry its own price — what that
                      piece cost, or what it would cost to replace.
                      A piece's price is its own number: it doesn't
                      change the set's price.
                    </p>
                    {pieces.map((piece, i) => (
                      <div
                        key={piece.id ?? `new-${i}`}
                        style={{
                          display: "grid",
                          gap: "0.5rem",
                          border: "1px solid var(--edge)",
                          borderRadius: "var(--radius)",
                          padding: "0.7rem",
                        }}
                      >
                        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                          <Select
                            aria-label={`Piece ${i + 1} kind`}
                            value={piece.kind}
                            onChange={(e) =>
                              setPiece(i, { kind: e.target.value as PieceDraft["kind"] })
                            }
                            style={{ flex: "0 1 130px" }}
                          >
                            <option value="core">Core piece</option>
                            <option value="addon">Addon</option>
                          </Select>
                          <TextInput
                            aria-label={`Piece ${i + 1} name`}
                            value={piece.name}
                            onChange={(e) => setPiece(i, { name: e.target.value })}
                            placeholder="Piece name"
                            style={{ flex: "1 1 180px" }}
                          />
                          <button
                            type="button"
                            className="tv-list-remove-btn"
                            aria-label={`Remove piece ${i + 1}`}
                            title={`Remove piece ${i + 1}`}
                            onClick={() =>
                              setPieces((rows) => rows.filter((_, idx) => idx !== i))
                            }
                          >
                            {"−"}
                          </button>
                        </div>
                        <div
                          style={{
                            display: "grid",
                            gap: "0.5rem",
                            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 140px), 1fr))",
                          }}
                        >
                          <TextInput
                            aria-label={`Piece ${i + 1} part number`}
                            value={piece.part_number}
                            onChange={(e) => setPiece(i, { part_number: e.target.value })}
                            placeholder="Part #"
                          />
                          <TextInput
                            id={piece.id ? `tf-piece-serial-${piece.id}` : undefined}
                            aria-label={`Piece ${i + 1} serial number`}
                            value={piece.serial_number}
                            onChange={(e) => setPiece(i, { serial_number: e.target.value })}
                            placeholder="Serial #"
                          />
                          <Select
                            aria-label={`Piece ${i + 1} presence`}
                            value={piece.status}
                            onChange={(e) =>
                              setPiece(i, { status: e.target.value as PieceDraft["status"] })
                            }
                          >
                            <option value="present">Present</option>
                            <option value="missing">Missing</option>
                            <option value="sold">Sold</option>
                            <option value="removed">Removed</option>
                          </Select>
                          <TextInput
                            aria-label={`Piece ${i + 1} price`}
                            type="number"
                            min="0"
                            step="any"
                            value={piece.price}
                            onChange={(e) => setPiece(i, { price: e.target.value })}
                            placeholder="Price"
                          />
                          <DatePicker
                            aria-label={`Piece ${i + 1} purchase date`}
                            value={piece.purchase_date}
                            onChange={(v) =>
                              setPiece(i, { purchase_date: v })
                            }
                            clearable
                          />
                        </div>
                      </div>
                    ))}
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => setPieces((rows) => [...rows, blankPiece("core")])}
                      >
                        + Add core piece
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => setPieces((rows) => [...rows, blankPiece("addon")])}
                      >
                        + Add addon piece
                      </Button>
                    </div>
                    <AttachedToolsPicker
                      value={attachedPicks}
                      onChange={setAttachedPicks}
                      excludeId={id}
                    />
                  </div>
                )}
              </div>
              <div style={{ marginTop: "0.9rem" }}>
                <FormField label="Notes" htmlFor="tf-notes">
                  <TextArea
                    id="tf-notes"
                    value={values.notes}
                    onChange={(e) => set("notes", e.target.value)}
                    placeholder="Anything worth remembering — searchable later."
                  />
                </FormField>
              </div>
            </Panel>

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

            {editing && (
              <Panel title="Barcode">
                <FormField label="UPC / barcode" htmlFor="tf-upc">
                  <TextInput
                    id="tf-upc"
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
                  No tags yet — create your first below. Tags are your
                  own labels for grouping and filtering (a truck box, a
                  job, a warranty year…).
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

            <Panel title="Maintenance">
              <Checkbox
                name="tf-schedule"
                label="Add a first maintenance schedule (calibration, service, inspection…)"
                checked={schedOn}
                onChange={(e) => setSchedOn(e.target.checked)}
              />
              {schedOn && (
                <div style={{ ...formGridStyle, marginTop: "0.8rem" }}>
                  <FormField label="Kind" htmlFor="tf-sched-kind">
                    <Select
                      id="tf-sched-kind"
                      value={schedKind}
                      onChange={(e) => setSchedKind(e.target.value as InitialSchedule["kind"])}
                    >
                      <option value="calibration">Calibration</option>
                      <option value="service">Service</option>
                      <option value="inspection">Inspection</option>
                      <option value="other">Other</option>
                    </Select>
                  </FormField>
                  <FormField label="Label" htmlFor="tf-sched-label">
                    <TextInput
                      id="tf-sched-label"
                      value={schedLabel}
                      onChange={(e) => setSchedLabel(e.target.value)}
                      placeholder="e.g. Annual calibration"
                    />
                  </FormField>
                  <FormField
                    label="Every (days)"
                    htmlFor="tf-sched-interval"
                    hint="An interval or a due date — one of the two is required."
                  >
                    <TextInput
                      id="tf-sched-interval"
                      type="number"
                      min="1"
                      step="1"
                      value={schedInterval}
                      onChange={(e) => setSchedInterval(e.target.value)}
                    />
                  </FormField>
                  <FormField label="First due date" htmlFor="tf-sched-due">
                    <DatePicker
                      id="tf-sched-due"
                      value={schedDue}
                      onChange={setSchedDue}
                      clearable
                    />
                  </FormField>
                </div>
              )}
            </Panel>

            <Panel title="Costs">
              <div style={formGridStyle}>
                <FormField label="Purchase price (each)" htmlFor="tf-pprice">
                  <TextInput
                    id="tf-pprice"
                    type="number"
                    min="0"
                    step="any"
                    value={values.purchase_price}
                    onChange={(e) => set("purchase_price", e.target.value)}
                  />
                </FormField>
                <FormField label="Quantity" htmlFor="tf-qty" error={fieldErrors.quantity}>
                  <TextInput
                    id="tf-qty"
                    type="number"
                    min="1"
                    step="1"
                    invalid={Boolean(fieldErrors.quantity)}
                    value={values.quantity}
                    onChange={(e) => set("quantity", e.target.value)}
                  />
                </FormField>
                <FormField label="Purchase date" htmlFor="tf-pdate">
                  <DatePicker
                    id="tf-pdate"
                    value={values.purchase_date}
                    onChange={(v) => set("purchase_date", v)}
                    clearable
                  />
                </FormField>
                <FormField label="Replacement cost (each)" htmlFor="tf-repl">
                  <TextInput
                    id="tf-repl"
                    type="number"
                    min="0"
                    step="any"
                    value={values.replacement_cost}
                    onChange={(e) => set("replacement_cost", e.target.value)}
                  />
                </FormField>
                <FormField label="MSRP (each)" htmlFor="tf-msrp">
                  <TextInput
                    id="tf-msrp"
                    type="number"
                    min="0"
                    step="any"
                    value={values.msrp}
                    onChange={(e) => set("msrp", e.target.value)}
                  />
                </FormField>
                <WarrantyFields
                  idPrefix="tf"
                  values={values}
                  onChange={(field, value) => set(field, value)}
                  dealerCompany={dealerCompany}
                  dealerKnown={dealerKnown}
                  resetKey={id ?? "new"}
                />
              </div>
              <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 0 }}>
                Prices are per item — totals multiply by the quantity.
                {totalPreview && (
                  <>
                    {" "}
                    Total paid: <strong>{totalPreview}</strong> for {quantityNumber}.
                  </>
                )}{" "}
                Replacement cost is what you'd pay today; MSRP is the list price. Both feed
                insurance valuations.
              </p>
            </Panel>

            {defs.length > 0 && (
              <Panel title="Custom fields">
                <div style={formGridStyle}>
                  {defs.map((def) => (
                    <CustomFieldInput
                      key={def.id}
                      def={def}
                      value={values.custom_data[def.id]}
                      error={fieldErrors[def.id]}
                      onChange={(v) =>
                        set("custom_data", { ...values.custom_data, [def.id]: v })
                      }
                    />
                  ))}
                </div>
              </Panel>
            )}

            {editing && id ? (
              <>
                <Panel title="Photos">
                  <PhotoUploader
                    toolId={id}
                    kind="photo"
                    onUploaded={refreshTool}
                    existing={(savedTool?.attachments ?? []).filter((a) => a.kind === "photo")}
                  />
                </Panel>
                <Panel title="Documents">
                  <PhotoUploader
                    toolId={id}
                    kind="document"
                    onUploaded={refreshTool}
                    existing={(savedTool?.attachments ?? []).filter((a) => a.kind === "document")}
                  />
                </Panel>
                <Panel title="Receipts">
                  <PhotoUploader
                    toolId={id}
                    kind="receipt"
                    onUploaded={refreshTool}
                    existing={(savedTool?.attachments ?? []).filter((a) => a.kind === "receipt")}
                  />
                  {savedTool && savedTool.attachments.length > 0 && (
                    <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                      {savedTool.attachments.length} file
                      {savedTool.attachments.length === 1 ? "" : "s"} attached across
                      photos, documents, and receipts.
                    </p>
                  )}
                </Panel>
              </>
            ) : null}

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
                    onClick={() => navigate(`/inventory/${duplicate[0].id}`)}
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
                  2026-11-09): this form runs far past one
                  screen — when the seated submit scrolls out
                  of view, its twin pins bottom-right. */}
              <StickySaveButton type="submit" loading={busy}>
                {busy
                  ? uploadingFiles
                    ? `Uploading files… (${stagedDone} of ${stagedCount})`
                    : "Saving…"
                  : editing
                    ? "Save changes"
                    : "Add tool"}
              </StickySaveButton>
              <LinkButton to={editing && id ? `/inventory/${id}` : "/inventory"} variant="secondary">Cancel</LinkButton>
            </div>
          </form>
        )}
      </div>

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
              . Add "{sharePrompt.tool.name}" to the shared items?
            </p>
            {promptError && <Alert tone="danger">{promptError}</Alert>}
            <div style={{ display: "grid", gap: "0.35rem" }}>
              {sharePrompt.groups.map((g) => {
                const alreadyShared = (g.resolved_items ?? []).some(
                  (r) => r.id === sharePrompt.tool.id,
                );
                const category = (sharePrompt.tool.category ?? "").trim();
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
    </RequireAuth>
  );
}
