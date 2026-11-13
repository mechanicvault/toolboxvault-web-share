import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import "./wizard.css";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Breadcrumbs,
  Button,
  Checkbox,
  DatePicker,
  FormField,
  formGridStyle,
  LinkButton,
  Modal,
  Panel,
  ProgressBar,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useDraftDirty,
  useToast,
  useUnsavedWorkGuard,
} from "../../components";
import { TagChip } from "../../components";
import { api, ApiError } from "../../lib/api";
import { focusFirstInvalid } from "../../lib/focusFirstInvalid";
import { todayLocalIso } from "../../lib/format";
import { useT } from "../../i18n/LocaleContext";
import {
  accountTypeLabel,
  enabledShareGroups,
  RequireAuth,
  useAuth,
  type ShareGroupState,
  type SharingOverview,
} from "../core";
import { DealerPicker } from "../dealers/components/DealerFields";
import type { DealerCompany } from "../dealers/types";
import { useMyModules } from "../core/MyModules";
import { type QuickAddValues } from "../catalog/QuickAddPanel";
import { ManualFinder } from "../catalog/ManualFinder";
import {
  importManual,
  importManualLink,
  type ManualCandidate,
} from "../catalog/api";
import { WizardLookup } from "./WizardLookup";
import { readQuickAddSeed } from "./quickAddSeed";
import { WarrantyFields } from "./components/WarrantyFields";
import { CategoryPicker } from "./components/CategoryPicker";
import { CustomFieldInput } from "./components/CustomFieldInput";
import { FieldSuggest } from "./components/FieldSuggest";
import { LocationTreePicker } from "./components/LocationTreePicker";
import {
  flattenLocationTree,
  indentedNodeLabel,
  listLocationNodes,
} from "./components/locationTree";
import {
  fileFailureToast,
  StagedFilePicker,
  uploadStagedFiles,
  type StagedFile,
} from "./components/StagedPhotoPicker";
import {
  blankPiece,
  RepeatableInputs,
  type PieceDraft,
} from "./ToolFormPage";
import {
  AttachedToolsPicker,
  type AttachedPick,
} from "./components/AttachedToolsPicker";
import {
  batteryCatalogName,
  searchBatteryCatalog,
  type BatteryCatalogEntry,
} from "./batteryCatalog";
import {
  parseWizardDefaults,
  WIZARD_SECTION_KEYS,
  WIZARD_SECTIONS,
  type WizardDefaults,
} from "./wizardDefaults";
import { displayDate, money } from "./format";
import type {
  Battery,
  BatteryFormValues,
  FieldDefinition,
  InitialSchedule,
  LocationNode,
  SetPieceInline,
  Tag,
  Tool,
  ToolFormValues,
} from "./types";

/**
 * The Add wizard (Wizard Phase 1, 2026-10-25 — Ryan's confirmed
 * model). Every Add entry point lands here (/inventory/new and
 * /inventory/batteries/new); EDITING stays on the full forms.
 *
 * The first question is "Is it a battery?"
 * - BATTERY branch (deliberately tiny): pick the pack from the
 *   seeded list (or enter it by hand), then the SAME quick
 *   lookup step the tool branch leads with (AI wizard
 *   completion, 2026-11-07 — photo ID included), then company
 *   + warranty and the small basics — done. The battery
 *   details step also carries the manual finder; its pick is
 *   imported the moment the battery is created, exactly like
 *   the tool branch's manuals section.
 * - TOOL branch: catalog lookup → the required basics → "What
 *   do you want to include?" (one checkbox column; every checked
 *   section becomes its own step, unchecked sections do not
 *   exist for this tool) → a set step when the tool is a set →
 *   review → save.
 *
 * Per-user wizard defaults (Settings → Add-tool wizard
 * defaults, account-held) pre-check the include column and
 * pre-fill the usual location + dealer; the include step still
 * shows, so one Next accepts the defaults. Save reuses the
 * forms' exact payload shapes, the staged-file upload, the
 * duplicate check and the consent-share prompt — the wizard is
 * a new front door onto the same machinery, not a second one.
 */

const EMPTY_TOOL: ToolFormValues = {
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

const EMPTY_BATTERY: BatteryFormValues = {
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

/* The wizard's today — the shared local-calendar helper
 * (lib/format), so a US-evening default is the user's own today,
 * not UTC's tomorrow. */
function today(): string {
  return todayLocalIso();
}

// The wizard's truck-account charge (owner, 2026-10-31): with a
// dealer picked and a price entered, the buyer may put any
// portion of the price on his truck account with that dealer.
// The context is the truck module's own read for the company —
// which active accounts exist, whether an invite is waiting,
// and whose name a self-opened tab would land under.
interface TruckWizardAccount {
  id: string;
  agent_name: string;
  balance: string;
}

interface TruckWizardAgent {
  agent_user_id: string | null;
  private_agent_id: string | null;
  name: string;
  is_preferred: boolean;
  is_default: boolean;
  active_accounts: TruckWizardAccount[];
}

interface TruckWizardContext {
  company_id: string;
  company_name: string;
  active_accounts: TruckWizardAccount[];
  invited_exists: boolean;
  new_account_agent_name: string | null;
  /** Every roster agent for the company (multi-preferred,
   *  2026-11-05); the top-level fields above are the display
   *  default agent's. */
  agents: TruckWizardAgent[];
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

type Branch = "fork" | "tool" | "battery";
type StepId =
  | "lookup"
  | "basics"
  | "include"
  | "set"
  | "review"
  | "battery-pick"
  | "battery-lookup"
  | "battery-details"
  | string; // a WIZARD_SECTIONS key

const pageStackStyle = { display: "grid", gap: "var(--spacing)" } as const;
const pageWidthStyle = {
  maxWidth: "760px",
  margin: "0 auto",
  display: "grid",
  gap: "var(--spacing)",
} as const;
const mutedStyle = { margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" } as const;
const navRowStyle = {
  display: "flex",
  gap: "0.75rem",
  flexWrap: "wrap",
  alignItems: "center",
} as const;
const checkColumnStyle = { display: "grid", gap: "0.7rem" } as const;

interface DuplicateHit {
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  matched_on: string;
}

export default function AddWizardPage() {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const { user, refreshUser } = useAuth();
  const presetBattery = location.pathname.startsWith("/inventory/batteries");

  // Quick Add seed (widget wave 2 build 3, 2026-11-10): the
  // Home Quick Add widget's typed handoff — a tool name and/or
  // one photo File riding location state (see quickAddSeed.ts).
  // Read ONCE from the entry navigation; every other entry into
  // the wizard carries no state and reads as no seed, so the
  // wizard's normal flow is byte-for-byte untouched. The fork
  // still asks its question: the seed seats in whichever branch
  // the user picks (the name in the tool draft's name field and
  // the battery branch's catalog search + name; the photo
  // staged as the item's first photo and handed to the lookup
  // step's identification flow).
  const [quickSeed] = useState(() => readQuickAddSeed(location.state));
  // The handoff is consumed from the first render's state;
  // drop it from history so a refresh or a Back trip into the
  // wizard starts clean instead of re-seeding.
  useEffect(() => {
    if (quickSeed) {
      navigate(`${location.pathname}${location.search}`, {
        replace: true,
        state: null,
      });
    }
    // Entry-only by design (the seed exists only on the entry
    // navigation); later location changes are the wizard's own.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [branch, setBranch] = useState<Branch>(presetBattery ? "battery" : "fork");
  const [stepIndex, setStepIndex] = useState(0);

  // ---- shared vocabulary --------------------------------------
  const [defs, setDefs] = useState<FieldDefinition[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [newTagName, setNewTagName] = useState("");
  const [tagBusy, setTagBusy] = useState(false);
  const [locationNodes, setLocationNodes] = useState<LocationNode[]>([]);
  const [vocabLoaded, setVocabLoaded] = useState(false);

  // ---- tool draft ----------------------------------------------
  // A Quick Add name seed lands in the name field itself — the
  // basics step shows it, the lookup step stays free to enrich
  // or replace it through its own "Use this".
  const [tool, setTool] = useState<ToolFormValues>(() =>
    quickSeed?.name ? { ...EMPTY_TOOL, name: quickSeed.name } : EMPTY_TOOL,
  );
  const [pieces, setPieces] = useState<PieceDraft[]>([]);
  // Build-a-set from inventory (2026-10-25): existing tools picked
  // to fold into the set this wizard creates.
  const [attachedPicks, setAttachedPicks] = useState<AttachedPick[]>([]);
  const [schedKind, setSchedKind] = useState<InitialSchedule["kind"]>("service");
  const [schedLabel, setSchedLabel] = useState("");
  const [schedInterval, setSchedInterval] = useState("");
  const [schedDue, setSchedDue] = useState("");
  const [stagedPhotos, setStagedPhotos] = useState<StagedFile[]>([]);
  const [stagedDocs, setStagedDocs] = useState<StagedFile[]>([]);
  const [stagedReceipts, setStagedReceipts] = useState<StagedFile[]>([]);
  const [stagedManuals, setStagedManuals] = useState<StagedFile[]>([]);
  // Find the manual (owner order 2026-11-05): the pick is only
  // REMEMBERED here — the item doesn't exist yet — and imported
  // through the item page's own endpoint the moment it does.
  // The pasted manual link rides the same post-create import.
  const [manualPick, setManualPick] = useState<ManualCandidate | null>(null);
  const [wizardManualLink, setWizardManualLink] = useState("");
  const [included, setIncluded] = useState<Set<string>>(new Set());

  // ---- battery draft --------------------------------------------
  // A Quick Add name seed seats in the battery branch's own
  // search field (the catalog pick list filters on it) and in
  // the draft's name, where the hand-entry path shows it; a
  // catalog pick overwrites both through the normal pick flow.
  const [battery, setBattery] = useState<BatteryFormValues>(() =>
    quickSeed?.name ? { ...EMPTY_BATTERY, name: quickSeed.name } : EMPTY_BATTERY,
  );
  const [batteryQuery, setBatteryQuery] = useState(quickSeed?.name ?? "");
  const [batteryPicked, setBatteryPicked] = useState<BatteryCatalogEntry | null>(null);
  const [batteryManual, setBatteryManual] = useState(false);
  // Battery-branch manual finder (2026-11-07): the same
  // remember-the-pick contract as the tool branch — imported
  // through the battery's own endpoint the moment it exists.
  const [batteryManualPick, setBatteryManualPick] =
    useState<ManualCandidate | null>(null);
  const [batteryManualLink, setBatteryManualLink] = useState("");
  // The lookup step's pasted product-page link lives inside
  // WizardLookup; it is typed work too, so it folds into the
  // guard's draft snapshot below via this mirror.
  const [lookupLink, setLookupLink] = useState("");

  // ---- the truck-account charge (2026-10-31) -------------------
  // One state for both branches (a run uses exactly one). The
  // question defaults to NO on every run — it is a money
  // question: never pre-answered, never written to the saved
  // wizard defaults. The context refetches whenever the picked
  // dealer changes; the amount fills with the full price the
  // moment the buyer says yes, and stays editable from there.
  const myModules = useMyModules();
  const truckModuleOn = myModules.has("truck_accounts");
  const [truckYes, setTruckYes] = useState(false);
  const [truckAmount, setTruckAmount] = useState("");
  const [truckAccountId, setTruckAccountId] = useState("");
  const [truckAgentKey, setTruckAgentKey] = useState("");
  const [truckCtx, setTruckCtx] = useState<TruckWizardContext | null>(null);
  const truckCompanyId =
    branch === "battery" ? battery.dealer_company_id : tool.dealer_company_id;
  const truckPrice =
    branch === "battery" ? battery.purchase_price : tool.purchase_price;
  // The wizard's agent pick (multi-preferred, 2026-11-05): the
  // charge targets the DISPLAY-DEFAULT agent unless the buyer
  // picks another roster agent; the account list and the
  // would-open name follow the PICKED agent.
  const truckAgentKeyOf = (a: TruckWizardAgent) =>
    a.agent_user_id ?? a.private_agent_id ?? "";
  const truckAgents = truckCtx?.agents ?? [];
  const selectedTruckAgent =
    truckAgents.find((a) => truckAgentKeyOf(a) === truckAgentKey) ?? null;
  const truckActiveAccounts = selectedTruckAgent
    ? selectedTruckAgent.active_accounts
    : (truckCtx?.active_accounts ?? []);
  useEffect(() => {
    setTruckYes(false);
    setTruckAmount("");
    setTruckAccountId("");
    setTruckAgentKey("");
    setTruckCtx(null);
    if (!truckModuleOn || !truckCompanyId) return;
    let live = true;
    api<TruckWizardContext>(
      `/truck-accounts/wizard-context?company_id=${encodeURIComponent(truckCompanyId)}`,
    )
      .then((ctx) => {
        if (!live) return;
        setTruckCtx(ctx);
        const agents = ctx.agents ?? [];
        const def = agents.find((a) => a.is_default) ?? agents[0];
        if (def) setTruckAgentKey(def.agent_user_id ?? def.private_agent_id ?? "");
      })
      .catch(() => {
        if (live) setTruckCtx(null);
      });
    return () => {
      live = false;
    };
  }, [truckCompanyId, truckModuleOn, branch]);

  // ---- shared form machinery ------------------------------------
  const [dealersAvailable, setDealersAvailable] = useState(false);
  const [dealerCompany, setDealerCompany] = useState<DealerCompany | null>(null);
  const [dealerKnown, setDealerKnown] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const busyRef = useRef(false);
  const failedFileNames = useRef<string[] | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateHit[]>([]);
  const [sharePrompt, setSharePrompt] = useState<{
    kind: "tool" | "battery";
    id: string;
    name: string;
    category: string;
    groups: ShareGroupState[];
  } | null>(null);
  const [promptChecked, setPromptChecked] = useState<Set<string>>(new Set());
  const [promptRuleChecked, setPromptRuleChecked] = useState<Set<string>>(new Set());
  const [promptBusy, setPromptBusy] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);

  const stagedRef = useRef<StagedFile[]>([]);
  stagedRef.current = [
    ...stagedPhotos,
    ...stagedDocs,
    ...stagedReceipts,
    ...stagedManuals,
  ];
  useEffect(
    () => () => {
      for (const p of stagedRef.current) {
        if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
      }
    },
    [],
  );

  // Vocabulary: field definitions + tags + the location tree
  // (the tree only feeds the review step's location label; the
  // pickers load their own copies).
  useEffect(() => {
    let live = true;
    Promise.all([
      api<FieldDefinition[]>("/inventory/field-definitions?item_type=tool").catch(
        () => [] as FieldDefinition[],
      ),
      api<Tag[]>("/inventory/tags").catch(() => [] as Tag[]),
      listLocationNodes().catch(() => [] as LocationNode[]),
    ]).then(([d, tagRows, nodes]) => {
      if (!live) return;
      setDefs([...d].sort((a, b) => a.sort_order - b.sort_order));
      setTags(tagRows);
      setLocationNodes(nodes);
      setVocabLoaded(true);
    });
    return () => {
      live = false;
    };
  }, []);

  // Account-held wizard defaults, applied ONCE when the account
  // resolves: pre-checked include sections + the usual location
  // and dealer on both drafts. The purchase date pre-fills to
  // today in the wizard (an adding-now flow; the field stays
  // visible and editable on the basics step).
  const defaultsAppliedFor = useRef<string | null>(null);
  // The account's saved defaults document, kept alongside the
  // working include set so the include step can offer "Save these
  // selections for future tools" exactly when the two differ
  // (owner, 2026-10-25).
  const [savedDefaults, setSavedDefaults] = useState<WizardDefaults | null>(null);
  const [savingSelections, setSavingSelections] = useState(false);
  useEffect(() => {
    if (!user || defaultsAppliedFor.current === user.id) return;
    defaultsAppliedFor.current = user.id;
    const defaults = parseWizardDefaults(user.wizard_defaults);
    setSavedDefaults(defaults);
    setIncluded(new Set(defaults.sections));
    setTool((v) => ({
      ...v,
      location_id: defaults.location_id || v.location_id,
      dealer_company_id: defaults.dealer_company_id || v.dealer_company_id,
      purchase_date: v.purchase_date || today(),
    }));
    setBattery((v) => ({
      ...v,
      location_id: defaults.location_id || v.location_id,
      dealer_company_id: defaults.dealer_company_id || v.dealer_company_id,
      purchase_date: v.purchase_date || today(),
    }));
  }, [user]);

  // Quick Add seed photo (widget wave 2 build 3): the handed-in
  // File, held for the lookup step's identification flow (both
  // branches render that step) and staged as the item's first
  // photo through applyLookupPhoto — the lookup step's own
  // staging path, Photos section included. The staging effect
  // keys on the same user landing as the defaults effect above
  // and is declared after it, so on the commit where the
  // account resolves, the defaults' include-set write lands
  // first and the seed's Photos inclusion survives it.
  const [seedPhoto, setSeedPhoto] = useState<File | null>(
    quickSeed?.photo ?? null,
  );
  const seedStagedRef = useRef(false);
  useEffect(() => {
    if (!user || seedStagedRef.current || !quickSeed?.photo) return;
    seedStagedRef.current = true;
    applyLookupPhoto(quickSeed.photo);
  }, [user, quickSeed]);

  // A required custom field leaves the user no real choice: the
  // Custom fields section force-includes (and locks in the
  // include column) so its step always runs.
  const customRequired = defs.some((d) => d.required);
  useEffect(() => {
    if (customRequired) {
      setIncluded((prev) => (prev.has("custom") ? prev : new Set(prev).add("custom")));
    }
  }, [customRequired]);

  // ---- unsaved-work guard (B-08) ----------------------------------
  // The whole draft, serialized: every field, picker, toggle,
  // staged file and section selection of BOTH branches (the two
  // drafts are one page's work). Navigation state (branch, step)
  // is deliberately absent — moving inside the wizard is not
  // leaving it, and the per-page Skip drops its section by
  // design, never through this guard. The baseline is captured
  // once the account + vocabulary settle (defaults already
  // applied), so pre-filled defaults read as the starting point,
  // not as the user's typing; anything past it — lookup autofill
  // included, it lands in these same fields — asks before an
  // exit discards it (see components/UnsavedWorkGuard).
  const draftSerialized = JSON.stringify({
    tool,
    pieces,
    attached: attachedPicks.map((p) => p.id),
    sched: [schedKind, schedLabel, schedInterval, schedDue],
    files: [
      ...stagedPhotos,
      ...stagedDocs,
      ...stagedReceipts,
      ...stagedManuals,
    ].map((f) => `${f.id}:${f.file.name}:${f.file.size}`),
    manualPick: manualPick ? manualPick.source_url : null,
    manualLink: wizardManualLink,
    included: [...included].sort(),
    truck: [truckYes, truckAmount, truckAccountId],
    battery,
    batteryQuery,
    batteryManual,
    batteryPicked: batteryPicked
      ? `${batteryPicked.brand}|${batteryPicked.model}|${batteryPicked.platform}`
      : null,
    batteryManualPick: batteryManualPick
      ? batteryManualPick.source_url
      : null,
    batteryManualLink,
    lookupLink,
    newTagName,
  });
  const wizardDirty = useDraftDirty(
    draftSerialized,
    Boolean(user) && vocabLoaded,
  );
  const guard = useUnsavedWorkGuard(wizardDirty, "/inventory");

  // ---- step model -------------------------------------------------
  const toolSteps: StepId[] = useMemo(() => {
    const steps: StepId[] = ["lookup", "basics", "include"];
    if (tool.is_set) steps.push("set");
    for (const section of WIZARD_SECTIONS) {
      if (section.key === "custom" && defs.length === 0) continue;
      if (included.has(section.key)) steps.push(section.key);
    }
    steps.push("review");
    return steps;
  }, [tool.is_set, included, defs.length]);

  const batterySteps: StepId[] = [
    "battery-pick",
    "battery-lookup",
    "battery-details",
  ];
  const steps = branch === "battery" ? batterySteps : toolSteps;
  const step: StepId =
    branch === "fork" ? "fork" : steps[Math.min(stepIndex, steps.length - 1)];

  // Step changes are page changes: land at the top, never at the
  // previous step's scroll depth (navigation rule).
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [step, branch]);

  function goTo(index: number) {
    setError("");
    setDuplicate([]);
    setStepIndex(Math.max(0, Math.min(index, steps.length - 1)));
  }

  function chooseBranch(next: "tool" | "battery") {
    setBranch(next);
    setStepIndex(0);
    setError("");
  }

  // ---- draft setters ----------------------------------------------
  function setToolField<K extends keyof ToolFormValues>(key: K, value: ToolFormValues[K]) {
    setTool((v) => ({ ...v, [key]: value }));
    setFieldErrors((prev) => {
      if (!prev[key as string]) return prev;
      const next = { ...prev };
      delete next[key as string];
      return next;
    });
  }

  function setBatteryField<K extends keyof BatteryFormValues>(
    key: K,
    value: BatteryFormValues[K],
  ) {
    setBattery((v) => ({ ...v, [key]: value }));
    setFieldErrors((prev) => {
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
      setTags((rows) => (rows.some((r) => r.id === tag.id) ? rows : [...rows, tag]));
      setToolField(
        "tag_ids",
        tool.tag_ids.includes(tag.id) ? tool.tag_ids : [...tool.tag_ids, tag.id],
      );
      setNewTagName("");
    } catch {
      /* the tag simply isn't created; the wizard carries on */
    } finally {
      setTagBusy(false);
    }
  }

  function applyQuickAdd(valuesIn: QuickAddValues) {
    if (valuesIn.name !== undefined) setToolField("name", valuesIn.name);
    if (valuesIn.brand !== undefined) setToolField("brand", valuesIn.brand);
    if (valuesIn.model !== undefined) setToolField("model_numbers", [valuesIn.model]);
    if (valuesIn.category !== undefined) setToolField("category", valuesIn.category);
    if (valuesIn.size !== undefined) {
      setToolField("size", valuesIn.size);
      setIncluded((prev) => new Set(prev).add("size"));
    }
    if (valuesIn.msrp !== undefined) {
      setToolField("msrp", valuesIn.msrp);
      setIncluded((prev) => new Set(prev).add("costs"));
    }
    if (valuesIn.description !== undefined) {
      // The product page's own description homes in Notes —
      // the one long-text field an item carries — and the
      // Notes section comes along so it isn't dropped at save.
      setToolField("notes", valuesIn.description);
      setIncluded((prev) => new Set(prev).add("notes"));
    }
  }

  // The battery branch's lookup apply (2026-11-07): the same
  // values the tool branch takes, mapped onto the battery
  // draft. Size has no battery home and never arrives (the
  // chain's battery consumers skip it); the description homes
  // in the battery's Notes, same as a tool's.
  function applyBatteryLookup(valuesIn: QuickAddValues) {
    if (valuesIn.name !== undefined) setBatteryField("name", valuesIn.name);
    if (valuesIn.brand !== undefined) setBatteryField("brand", valuesIn.brand);
    if (valuesIn.model !== undefined) setBatteryField("model", valuesIn.model);
    if (valuesIn.category !== undefined)
      setBatteryField("category", valuesIn.category);
    if (valuesIn.msrp !== undefined) setBatteryField("msrp", valuesIn.msrp);
    if (valuesIn.description !== undefined)
      setBatteryField("notes", valuesIn.description);
  }

  // The grounded lookup's photo offer (2026-10-25): the product
  // page's real photo, downloaded by the lookup card, stages
  // here exactly like a photo the user picked themselves — it
  // rides the same staged-photo save and includes the Photos
  // section so it isn't silently dropped at the include step.
  function applyLookupPhoto(file: File) {
    const staged: StagedFile = {
      id: `lookup-photo-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
      file,
      previewUrl: URL.createObjectURL(file),
      status: "staged",
      progress: 0,
    };
    setStagedPhotos((rows) => [...rows, staged]);
    setIncluded((prev) => new Set(prev).add("photos"));
  }

  function pickBattery(entry: BatteryCatalogEntry) {
    setBatteryPicked(entry);
    setBatteryManual(false);
    setBattery((v) => ({
      ...v,
      name: batteryCatalogName(entry),
      brand: entry.brand,
      platform: entry.platform,
      model: entry.model,
      voltage: String(entry.voltage),
      capacity_ah: String(entry.capacityAh),
      chemistry: entry.chemistry,
    }));
    goTo(1);
  }

  // ---- per-step validation (runs on Next) --------------------------
  function validateBasics(): boolean {
    const errs: Record<string, string> = {};
    if (!tool.name.trim()) errs.name = "Give the tool a name.";
    const qty = Number(tool.quantity);
    if (!Number.isInteger(qty) || qty < 1)
      errs.quantity = "Quantity is a whole number, 1 or more.";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function validateSet(): boolean {
    if (pieces.some((p) => !p.name.trim())) {
      setError("Every set piece needs a name — fill it in or remove the row.");
      return false;
    }
    return true;
  }

  function validateSchedule(): boolean {
    if (!schedInterval && !schedDue) {
      setError("The first maintenance schedule needs an interval or a due date.");
      return false;
    }
    return true;
  }

  function validateCustom(): boolean {
    const errs: Record<string, string> = {};
    for (const def of defs) {
      if (!def.required) continue;
      const v = tool.custom_data[def.id];
      const empty =
        v === null ||
        v === undefined ||
        v === "" ||
        (def.field_type === "boolean" && v !== true && v !== false);
      if (empty) errs[def.id] = `${def.label} is required.`;
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function onNext() {
    setError("");
    // B-05: a failed Next moves focus to the first invalid field
    // (the shared wizard validation clause — see
    // lib/focusFirstInvalid). Step-level errors (set/schedule)
    // mark no field, so focus simply stays put there.
    if (step === "basics" && !validateBasics()) { focusFirstInvalid(); return; }
    if (step === "set" && !validateSet()) return;
    if (step === "schedule" && !validateSchedule()) return;
    if (step === "custom" && !validateCustom()) { focusFirstInvalid(); return; }
    goTo(stepIndex + 1);
  }

  // ---- Skip (owner, 2026-10-25) --------------------------------
  // Every OPTIONAL section page (and the set page) can be skipped
  // from its own bottom bar: the section leaves the include set,
  // so saveTool's per-section gating drops whatever was typed on
  // the page for this tool, and the next step slides into the
  // same index as the step list shrinks. Required steps (lookup,
  // basics, include, review) never skip; Custom fields can't be
  // skipped while one of them is required (it never leaves the
  // set). A plain skip, no confirm — the data simply isn't saved
  // for this item.
  const skippableStep =
    branch === "tool" &&
    (step === "set" || WIZARD_SECTION_KEYS.includes(step)) &&
    !(step === "custom" && customRequired);

  function skipStep() {
    if (!skippableStep) return;
    setError("");
    setDuplicate([]);
    if (step === "set") {
      // The set page is driven by the basics checkbox, not the
      // include set: skipping un-marks the set and drops its
      // pieces for this tool.
      setToolField("is_set", false);
      setPieces([]);
      setAttachedPicks([]);
      return;
    }
    setIncluded((prev) => {
      const next = new Set(prev);
      next.delete(step);
      return next;
    });
  }

  // ---- include step: save selections as the defaults ------------
  // Shown only while the working selections differ from the saved
  // defaults; saving writes the whole defaults document back
  // (usual location/dealer ride along untouched) through the same
  // PATCH /core/me the Settings page uses.
  const includedSectionKeys = WIZARD_SECTION_KEYS.filter((k) =>
    included.has(k),
  );
  // A required custom field force-includes "custom" on the working
  // side; count it as present on the saved side too, or the save
  // option would show forever for those accounts.
  const effectiveSavedSections =
    savedDefaults === null
      ? []
      : customRequired && !savedDefaults.sections.includes("custom")
        ? [...savedDefaults.sections, "custom"]
        : savedDefaults.sections;
  const selectionsDiffer =
    savedDefaults !== null &&
    (includedSectionKeys.length !== effectiveSavedSections.length ||
      includedSectionKeys.some((k) => !effectiveSavedSections.includes(k)));

  async function saveSelectionsAsDefaults() {
    if (!savedDefaults || savingSelections) return;
    setSavingSelections(true);
    try {
      const doc: WizardDefaults = {
        ...savedDefaults,
        sections: [...includedSectionKeys],
      };
      await api("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ wizard_defaults: doc }),
      });
      setSavedDefaults(doc);
      await refreshUser();
      toast(t("wizardDefaults.saved"), { title: "Saved", tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't save your selections.",
      );
    } finally {
      setSavingSelections(false);
    }
  }

  // ---- save: tool ---------------------------------------------------
  async function saveTool(force = false) {
    if (busyRef.current) return;
    if (!truckChargeValid()) {
      goTo(steps.indexOf("basics"));
      focusFirstInvalid();
      return;
    }
    if (!validateBasics()) {
      goTo(steps.indexOf("basics"));
      focusFirstInvalid();
      return;
    }
    if (tool.is_set && !validateSet()) {
      goTo(steps.indexOf("set"));
      return;
    }
    if (included.has("schedule") && !validateSchedule()) {
      goTo(steps.indexOf("schedule"));
      return;
    }
    if (!validateCustom()) {
      goTo(steps.indexOf("custom"));
      focusFirstInvalid();
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setError("");
    const inc = (key: string) => included.has(key);
    const cleanList = (list: string[]) =>
      list.map((v) => v.trim()).filter((v, i, all) => v && all.indexOf(v) === i);
    // Unchecked sections do not exist for this tool: their
    // fields save blank. The numbers lists keep their FIRST
    // entry regardless — it is the tool's primary model/serial,
    // set by the lookup step; the section governs the extras.
    const modelNumbers = cleanList(
      inc("numbers") ? tool.model_numbers : tool.model_numbers.slice(0, 1),
    );
    const serialNumbers = cleanList(
      inc("numbers") ? tool.serial_numbers : tool.serial_numbers.slice(0, 1),
    );
    const payload: Record<string, unknown> = {
      name: tool.name.trim(),
      brand: tool.brand.trim(),
      model: modelNumbers[0] ?? "",
      serial_number: serialNumbers[0] ?? "",
      model_numbers: modelNumbers,
      serial_numbers: serialNumbers,
      category: tool.category.trim(),
      location_id: tool.location_id || null,
      notes: inc("notes") ? tool.notes : "",
      purchase_price: tool.purchase_price === "" ? null : tool.purchase_price,
      purchase_date: tool.purchase_date === "" ? null : tool.purchase_date,
      replacement_cost: inc("costs")
        ? tool.replacement_cost === ""
          ? null
          : tool.replacement_cost
        : null,
      msrp: inc("costs") ? (tool.msrp === "" ? null : tool.msrp) : null,
      warranty_months: inc("warranty")
        ? tool.warranty_months === ""
          ? null
          : Number(tool.warranty_months)
        : null,
      warranty_provider: inc("warranty") ? tool.warranty_provider.trim() : "",
      warranty_contact: inc("warranty") ? tool.warranty_contact.trim() : "",
      warranty_terms: inc("warranty") ? tool.warranty_terms.trim() : "",
      warranty_type: inc("warranty")
        ? tool.warranty_type === ""
          ? null
          : tool.warranty_type
        : null,
      quantity: Number(tool.quantity) || 1,
      upc: tool.upc.trim(),
      size: inc("size") ? tool.size.trim() : "",
      consumable: inc("usage") ? tool.consumable : false,
      // Business use rides the basics step since 2026-11-07
      // (Ryan: the checkbox belongs on the FIRST screen), so
      // it is no longer gated on the usage section existing.
      business_use: tool.business_use,
      rebuy_store: inc("usage") ? tool.rebuy_store.trim() : "",
      rebuy_url: inc("usage") ? tool.rebuy_url.trim() : "",
      rebuy_sku: inc("usage") ? tool.rebuy_sku.trim() : "",
      rebuy_notes: inc("usage") ? tool.rebuy_notes.trim() : "",
      is_set: tool.is_set,
      tag_ids: inc("tags") ? tool.tag_ids : [],
      custom_data: inc("custom") ? tool.custom_data : {},
    };
    if (dealersAvailable) {
      payload.dealer_company_id = tool.dealer_company_id || null;
    }
    const toolTruck = truckPayload();
    if (toolTruck) payload.truck_charge = toolTruck;
    if (tool.is_set) {
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
      payload.attach_tool_ids = attachedPicks.map((p) => p.id);
    }
    if (inc("schedule")) {
      payload.initial_schedule = {
        kind: schedKind,
        label: schedLabel.trim(),
        interval_days: schedInterval ? Number(schedInterval) : null,
        due_date: schedDue || null,
      } satisfies InitialSchedule;
    }
    try {
      const created = await api<Tool>(
        force ? "/inventory?force=true" : "/inventory",
        { method: "POST", body: JSON.stringify(payload) },
      );
      const staged: { kind: "photo" | "document" | "receipt" | "manual"; files: StagedFile[]; apply: (n: StagedFile[]) => void }[] = [
        { kind: "photo", files: inc("photos") ? stagedPhotos : [], apply: setStagedPhotos },
        { kind: "document", files: inc("documents") ? stagedDocs : [], apply: setStagedDocs },
        { kind: "receipt", files: inc("receipts") ? stagedReceipts : [], apply: setStagedReceipts },
        { kind: "manual", files: inc("manuals") ? stagedManuals : [], apply: setStagedManuals },
      ];
      const failedNames: string[] = [];
      if (staged.some((s) => s.files.length > 0)) {
        setUploadingFiles(true);
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
      }
      // Find the manual (2026-11-05): the remembered pick and
      // the pasted link go through the item page's own import
      // endpoints now that the item exists — the same guarded
      // download, landing as manual attachments. A failure
      // names itself in the same couldn't-add toast as a
      // failed upload; the item itself is already saved.
      if (inc("manuals") && manualPick) {
        try {
          await importManual(
            "tools",
            created.id,
            manualPick.source_url,
            manualPick.source_name,
          );
        } catch {
          failedNames.push(manualPick.title);
        }
      }
      if (inc("manuals") && wizardManualLink.trim()) {
        try {
          await importManualLink("tools", created.id, wizardManualLink.trim());
        } catch {
          failedNames.push(wizardManualLink.trim());
        }
      }
      failedFileNames.current = failedNames.length > 0 ? failedNames : null;
      await afterCreate("tool", created.id, created.name, created.category ?? "");
    } catch (err) {
      if (err instanceof ApiError && err.code === "possible_duplicate" && !force) {
        const existing = err.detail?.existing;
        setDuplicate(Array.isArray(existing) ? (existing as DuplicateHit[]) : []);
        return;
      }
      setError(err instanceof ApiError ? err.message : "Couldn't save the tool.");
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  // ---- save: battery --------------------------------------------------
  async function saveBattery(force = false) {
    if (busyRef.current) return;
    if (!truckChargeValid()) {
      focusFirstInvalid();
      return;
    }
    if (!battery.name.trim()) {
      setFieldErrors({ name: "A name is required." });
      focusFirstInvalid();
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setError("");
    const payload: Record<string, unknown> = {
      name: battery.name.trim(),
      brand: battery.brand,
      model: battery.model,
      serial_number: battery.serial_number,
      category: battery.category || "Batteries",
      location_id: battery.location_id || null,
      // The draft's own facts (2026-11-07 parity fix): the
      // lookup step fills notes (the found description), msrp
      // and upc, and the details step carries the business-use
      // checkbox — all of it used to be discarded by hardcoded
      // blanks here even though the draft held the fields.
      notes: battery.notes,
      purchase_price: numberOrNull(battery.purchase_price),
      purchase_date: battery.purchase_date || null,
      replacement_cost: null,
      msrp: numberOrNull(battery.msrp),
      platform: battery.platform,
      voltage: numberOrNull(battery.voltage),
      capacity_ah: numberOrNull(battery.capacity_ah),
      chemistry: battery.chemistry,
      warranty_months: numberOrNull(battery.warranty_months),
      warranty_provider: battery.warranty_provider.trim(),
      warranty_contact: battery.warranty_contact.trim(),
      warranty_terms: battery.warranty_terms.trim(),
      warranty_type: battery.warranty_type === "" ? null : battery.warranty_type,
      currently_in_tool_id: null,
      upc: battery.upc.trim(),
      business_use: battery.business_use,
      quantity: Math.max(1, Math.floor(Number(battery.quantity) || 1)),
      tag_ids: [],
      custom_data: {},
    };
    if (dealersAvailable) {
      payload.dealer_company_id = battery.dealer_company_id || null;
    }
    const batteryTruck = truckPayload();
    if (batteryTruck) payload.truck_charge = batteryTruck;
    try {
      const created = await api<Battery>(
        force ? "/inventory/batteries?force=true" : "/inventory/batteries",
        { method: "POST", body: JSON.stringify(payload) },
      );
      // Post-create, the tool branch's own machinery: the
      // lookup's staged product photo uploads against the new
      // battery, and the manual finder's remembered pick (and
      // a pasted manual link) import through the battery's own
      // endpoints. Failures name themselves in the same
      // couldn't-add toast the tool branch uses.
      const failedNames: string[] = [];
      if (stagedPhotos.length > 0) {
        setUploadingFiles(true);
        const { failed } = await uploadStagedFiles(
          `/inventory/batteries/${created.id}`,
          "photo",
          stagedPhotos,
          setStagedPhotos,
        );
        failedNames.push(...failed.map((f) => f.file.name));
        setUploadingFiles(false);
      }
      if (batteryManualPick) {
        try {
          await importManual(
            "batteries",
            created.id,
            batteryManualPick.source_url,
            batteryManualPick.source_name,
          );
        } catch {
          failedNames.push(batteryManualPick.title);
        }
      }
      if (batteryManualLink.trim()) {
        try {
          await importManualLink(
            "batteries",
            created.id,
            batteryManualLink.trim(),
          );
        } catch {
          failedNames.push(batteryManualLink.trim());
        }
      }
      failedFileNames.current = failedNames.length > 0 ? failedNames : null;
      await afterCreate("battery", created.id, created.name, created.category ?? "");
    } catch (err) {
      if (err instanceof ApiError && err.code === "possible_duplicate" && !force) {
        const existing = err.detail?.existing;
        setDuplicate(Array.isArray(existing) ? (existing as DuplicateHit[]) : []);
        return;
      }
      setError(err instanceof ApiError ? err.message : "Couldn't save the battery.");
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  // ---- after create: the consent-share prompt, then landing ----------
  async function afterCreate(
    kind: "tool" | "battery",
    id: string,
    name: string,
    category: string,
  ) {
    // The item exists: the typed work is saved, so the guard
    // stands down before the share prompt / landing navigation.
    guard.disarm();
    let enabled: ShareGroupState[] = [];
    try {
      const overview = await api<SharingOverview>("/core/sharing");
      enabled = enabledShareGroups(overview);
    } catch {
      enabled = [];
    }
    if (enabled.length > 0) {
      setPromptChecked(
        new Set(
          enabled
            .filter((g) => !(g.resolved_items ?? []).some((r) => r.id === id))
            .map((g) => g.recipient_group),
        ),
      );
      setPromptRuleChecked(new Set());
      setSharePrompt({ kind, id, name, category, groups: enabled });
    } else {
      landOnItem(kind, id);
    }
  }

  function landOnItem(kind: "tool" | "battery", id: string) {
    navigate(kind === "tool" ? `/inventory/${id}` : `/inventory/batteries/${id}`, {
      replace: true,
    });
    const failed = failedFileNames.current;
    failedFileNames.current = null;
    if (failed && failed.length > 0) {
      const { title, message } = fileFailureToast(kind, "file", failed);
      toast(message, { title, tone: "warning", duration: 12000 });
    }
  }

  function skipSharePrompt() {
    if (!sharePrompt) return;
    const { kind, id } = sharePrompt;
    setSharePrompt(null);
    landOnItem(kind, id);
  }

  async function confirmSharePrompt() {
    if (!sharePrompt) return;
    setPromptError(null);
    setPromptBusy(true);
    try {
      for (const group of sharePrompt.groups) {
        if (
          promptRuleChecked.has(group.recipient_group) &&
          sharePrompt.category
        ) {
          await api(`/core/sharing/${group.recipient_group}/rules`, {
            method: "POST",
            body: JSON.stringify({
              scope: "category",
              scope_value: sharePrompt.category,
              include_addons: false,
            }),
          });
        }
        if (!promptChecked.has(group.recipient_group)) continue;
        await api(`/core/sharing/${group.recipient_group}/items`, {
          method: "PUT",
          body: JSON.stringify({
            tool_ids:
              sharePrompt.kind === "tool"
                ? [...group.shared_tool_ids, sharePrompt.id]
                : group.shared_tool_ids,
            battery_ids:
              sharePrompt.kind === "battery"
                ? [...group.shared_battery_ids, sharePrompt.id]
                : group.shared_battery_ids,
            set_choices: group.set_choices,
          }),
        });
      }
      const { kind, id } = sharePrompt;
      setSharePrompt(null);
      landOnItem(kind, id);
    } catch (err) {
      setPromptError(
        err instanceof ApiError
          ? err.message
          : "Couldn't update the shared list. The item itself is saved.",
      );
    } finally {
      setPromptBusy(false);
    }
  }

  // ---- review helpers --------------------------------------------------
  const locationLabel = useMemo(() => {
    const flat = flattenLocationTree(locationNodes);
    const node = flat.find((n) => n.id === (branch === "battery" ? battery.location_id : tool.location_id));
    return node ? indentedNodeLabel(node) : "";
  }, [locationNodes, branch, battery.location_id, tool.location_id]);

  const stagedCount =
    stagedPhotos.length +
    stagedDocs.length +
    stagedReceipts.length +
    stagedManuals.length;
  const stagedDone = [
    ...stagedPhotos,
    ...stagedDocs,
    ...stagedReceipts,
    ...stagedManuals,
  ].filter((p) => p.status === "done").length;

  // ---- step titles ------------------------------------------------------
  const stepTitle = (s: StepId): string => {
    switch (s) {
      case "lookup":
        return t("wizard.lookupTitle");
      case "basics":
        return t("wizard.basicsTitle");
      case "include":
        return t("wizard.includeTitle");
      case "set":
        return t("wizard.setTitle");
      case "review":
        return t("wizard.reviewTitle");
      case "battery-pick":
        return t("wizard.batteryPickTitle");
      case "battery-lookup":
        return t("wizard.lookupTitle");
      case "battery-details":
        return t("wizard.batteryDetailsTitle");
      default: {
        const section = WIZARD_SECTIONS.find((x) => x.key === s);
        return section ? t(section.labelKey) : "";
      }
    }
  };

  // ---- step renderers -----------------------------------------------------
  function renderFork() {
    // Owner rebuild (2026-10-25, flagged twice): two tappable
    // photo rows instead of text buttons in a panel — a real
    // photo on the left, the answer beside it, the whole row is
    // the tap target. Each row wears .tv-panel — the Home
    // Overview stat cards' box skin (owner, 2026-10-25: "each
    // box should look like the overview boxes so everything
    // kind of matches"). All type is plain body type via the
    // .tv-fork-* classes (components.css) — no display face, no
    // caps, no engraved shadows. Photos: Pexels (Pexels License,
    // free to use, adaptation allowed) — battery: photo 3877525
    // by Caleb Oquendo, cropped to the 20V pack; tools: photo
    // 6789020 by Dmitry Demidov (wrenches). See
    // mobile-repro/wizard-lookup-fix/INDEX.md for the sourcing
    // note (no license-clean multi-pack group shot exists).
    return (
      <section className="tv-fork">
        <div className="tv-fork-rows">
          <button
            type="button"
            className="tv-panel tv-fork-row"
            onClick={() => chooseBranch("battery")}
          >
            <img
              className="tv-fork-img"
              src="/wizard/fork-battery-pack.webp"
              alt={t("wizard.forkBatteryAlt")}
              width={640}
              height={480}
            />
            <span className="tv-fork-text">
              <span className="tv-fork-label">{t("wizard.forkBattery")}</span>
              <span className="tv-fork-hint">{t("wizard.forkBatteryHint")}</span>
            </span>
          </button>
          <button
            type="button"
            className="tv-panel tv-fork-row"
            onClick={() => chooseBranch("tool")}
          >
            <img
              className="tv-fork-img"
              src="/wizard/fork-tools.webp"
              alt={t("wizard.forkToolAlt")}
              width={640}
              height={480}
            />
            <span className="tv-fork-text">
              <span className="tv-fork-label">{t("wizard.forkTool")}</span>
              <span className="tv-fork-hint">{t("wizard.forkToolHint")}</span>
            </span>
          </button>
        </div>
      </section>
    );
  }

  function renderLookup() {
    // Owner fix (2026-10-25): the lookup step is its own simple
    // component now — one input group, one button, an always-
    // there Skip, and one organized result card (WizardLookup).
    // The shared QuickAddPanel stays on the full forms only.
    return (
      <WizardLookup
        brand={tool.brand}
        model={tool.model_numbers[0] ?? ""}
        upc={tool.upc}
        onBrandChange={(v) => setToolField("brand", v)}
        onModelChange={(v) => setToolField("model_numbers", [v])}
        onUpcChange={(v) => setToolField("upc", v)}
        onApply={applyQuickAdd}
        onApplyPhoto={applyLookupPhoto}
        onLinkChange={setLookupLink}
        onDone={() => goTo(stepIndex + 1)}
        seedPhoto={seedPhoto}
        onSeedPhotoConsumed={() => setSeedPhoto(null)}
      />
    );
  }

  // The truck-account question (2026-10-31): rendered under the
  // price on the tool basics step and the battery details step
  // when a dealer is picked, a price is entered, and the buyer's
  // truck context for that dealer is known. Saying yes fills the
  // amount with the full price; the buyer may lower it to any
  // portion. With several active accounts the buyer picks; with
  // none, the copy says a tab will be opened (and under whose
  // name). The block states the consequence where it stands —
  // on the battery step that IS the pre-save surface; the tool
  // review repeats it as its own row.
  function truckChargeValid(): boolean {
    if (!truckYes) return true;
    const amount = Number(truckAmount);
    const price = Number(truckPrice);
    return (
      Number.isFinite(amount) &&
      amount > 0 &&
      Number.isFinite(price) &&
      amount <= price
    );
  }

  function truckPayload(): {
    amount: number;
    account_id: string | null;
    agent_user_id: string | null;
    private_agent_id: string | null;
  } | null {
    if (!truckYes) return null;
    return {
      amount: Number(truckAmount),
      account_id: truckAccountId || null,
      agent_user_id: selectedTruckAgent?.agent_user_id ?? null,
      private_agent_id: selectedTruckAgent?.private_agent_id ?? null,
    };
  }

  function renderTruckCharge() {
    const price = Number(truckPrice);
    if (!dealersAvailable || !truckCtx || !truckCompanyId || !(price > 0))
      return null;
    const dealerName = truckCtx.company_name;
    const active = truckActiveAccounts;
    const newAgentName = selectedTruckAgent
      ? selectedTruckAgent.name
      : truckCtx.new_account_agent_name;
    return (
      <div style={checkColumnStyle}>
        <Checkbox
          name="wz-truck-charge"
          label={t("wizard.truckQuestion").replace("{dealer}", dealerName)}
          checked={truckYes}
          onChange={(e) => {
            setTruckYes(e.target.checked);
            if (e.target.checked) {
              setTruckAmount(truckPrice);
              if (active.length === 1) setTruckAccountId(active[0].id);
            }
          }}
        />
        {truckYes && (
          <>
            {truckAgents.length > 1 && (
              <FormField
                label={t("wizard.truckWhichAgent")}
                htmlFor="wz-truck-agent"
              >
                <Select
                  id="wz-truck-agent"
                  value={truckAgentKey}
                  onChange={(e) => {
                    setTruckAgentKey(e.target.value);
                    setTruckAccountId("");
                  }}
                >
                  {truckAgents.map((a) => (
                    <option key={truckAgentKeyOf(a)} value={truckAgentKeyOf(a)}>
                      {a.name}
                      {a.is_preferred ? " \u2605" : ""}
                    </option>
                  ))}
                </Select>
              </FormField>
            )}
            {active.length > 1 && (
              <FormField label={t("wizard.truckWhich")} htmlFor="wz-truck-account">
                <Select
                  id="wz-truck-account"
                  value={truckAccountId}
                  onChange={(e) => setTruckAccountId(e.target.value)}
                >
                  <option value="">—</option>
                  {active.map((a) => (
                    <option key={a.id} value={a.id}>
                      {t("wizard.truckAccountOption")
                        .replace("{agent}", a.agent_name)
                        .replace("{balance}", money(a.balance))}
                    </option>
                  ))}
                </Select>
              </FormField>
            )}
            <FormField
              label={t("wizard.truckAmount")}
              htmlFor="wz-truck-amount"
              error={!truckChargeValid() ? t("wizard.truckAmountInvalid") : undefined}
            >
              <TextInput
                id="wz-truck-amount"
                type="number"
                min="0"
                step="any"
                invalid={!truckChargeValid()}
                value={truckAmount}
                onChange={(e) => setTruckAmount(e.target.value)}
              />
            </FormField>
            {truckChargeValid() && (
              <p style={mutedStyle}>
                {active.length > 0
                  ? t("wizard.truckWillCharge")
                      .replace("{amount}", money(truckAmount))
                      .replace("{dealer}", dealerName)
                  : newAgentName
                    ? t("wizard.truckWillOpenAgent")
                        .replace("{amount}", money(truckAmount))
                        .replace("{dealer}", dealerName)
                        .replace("{agent}", newAgentName)
                    : t("wizard.truckWillOpen")
                        .replace("{amount}", money(truckAmount))
                        .replace("{dealer}", dealerName)}
              </p>
            )}
            {truckCtx.invited_exists && (
              <p style={mutedStyle}>{t("wizard.truckInvitedNote")}</p>
            )}
          </>
        )}
      </div>
    );
  }

  function renderBasics() {
    return (
      <Panel title={t("wizard.basicsTitle")}>
        <div style={formGridStyle}>
          <FormField label="Name" htmlFor="wz-name" required error={fieldErrors.name}>
            <TextInput
              id="wz-name"
              invalid={Boolean(fieldErrors.name)}
              value={tool.name}
              onChange={(e) => setToolField("name", e.target.value)}
            />
          </FormField>
          <FormField label="Brand (manufacturer)" htmlFor="wz-brand">
            <FieldSuggest
              field="brand"
              id="wz-brand"
              value={tool.brand}
              onChange={(v) => setToolField("brand", v)}
            />
          </FormField>
          <FormField label="Category" htmlFor="wz-category">
            <CategoryPicker
              id="wz-category"
              value={tool.category}
              onChange={(v) => setToolField("category", v)}
            />
          </FormField>
          <FormField label="Storage location" htmlFor="wz-location">
            <LocationTreePicker
              id="wz-location"
              value={tool.location_id || null}
              onChange={(locationId) => setToolField("location_id", locationId ?? "")}
            />
          </FormField>
          <DealerPicker
            id="wz-dealer"
            label="Dealer (bought from)"
            hint="The company you bought it from — used for dealer contacts and warranty help."
            value={tool.dealer_company_id}
            onChange={(companyId) => setToolField("dealer_company_id", companyId)}
            onAvailability={setDealersAvailable}
            onCompany={(company) => {
              setDealerCompany(company);
              setDealerKnown(true);
            }}
          />
          <FormField label="Purchase price (each)" htmlFor="wz-pprice">
            <TextInput
              id="wz-pprice"
              type="number"
              min="0"
              step="any"
              value={tool.purchase_price}
              onChange={(e) => setToolField("purchase_price", e.target.value)}
            />
          </FormField>
          <FormField label="Quantity" htmlFor="wz-qty" error={fieldErrors.quantity}>
            <TextInput
              id="wz-qty"
              type="number"
              min="1"
              step="1"
              invalid={Boolean(fieldErrors.quantity)}
              value={tool.quantity}
              onChange={(e) => setToolField("quantity", e.target.value)}
            />
          </FormField>
          <FormField label="Purchase date" htmlFor="wz-pdate">
            <DatePicker
              id="wz-pdate"
              value={tool.purchase_date}
              onChange={(v) => setToolField("purchase_date", v)}
              clearable
            />
          </FormField>
        </div>
        <div style={setCheckboxRowStyle}>
          <Checkbox
            name="wz-is-set"
            label="This is a set: a kit with its own pieces (sockets, bits…)"
            checked={tool.is_set}
            onChange={(e) => setToolField("is_set", e.target.checked)}
          />
        </div>
        {/* Business use lives HERE now (Ryan, 2026-11-07): the
            wizard's first data-entry screen, bound to the same
            draft field the full form uses. It used to sit in
            the optional usage section — behind an include
            checkbox most runs never tick — and is rendered in
            exactly this one place. */}
        <div style={setCheckboxRowStyle}>
          <Checkbox
            name="wz-business-use"
            label="Business use: this tool earns its keep (used for work you charge for)"
            checked={tool.business_use}
            onChange={(e) => setToolField("business_use", e.target.checked)}
          />
        </div>
        {renderTruckCharge()}
      </Panel>
    );
  }

  function renderInclude() {
    // Select all / Clear all (Ryan, 2026-10-31): a per-run action
    // on the working include set only — it never writes the
    // saved wizard defaults (the "Save these selections"
    // affordance below keeps that job). It touches only the
    // sections this page actually offers: "custom" is absent
    // when the account has no custom fields, and a required
    // custom section is locked in, so neither is ever
    // force-checked or cleared by the bulk control.
    const visibleSections = WIZARD_SECTIONS.filter(
      (s) => s.key !== "custom" || defs.length > 0,
    );
    const selectableKeys = visibleSections
      .filter((s) => !(s.key === "custom" && customRequired))
      .map((s) => s.key);
    const allSelected =
      selectableKeys.length > 0 &&
      selectableKeys.every((k) => included.has(k));
    const toggleSelectAll = () =>
      setIncluded((prev) => {
        const next = new Set(prev);
        for (const key of selectableKeys) {
          if (allSelected) next.delete(key);
          else next.add(key);
        }
        return next;
      });
    return (
      <Panel title={t("wizard.includeTitle")}>
        <div style={checkColumnStyle}>
          <p style={mutedStyle}>{t("wizard.includeBody")}</p>
          <div>
            <Button variant="secondary" onClick={toggleSelectAll}>
              {allSelected ? t("wizard.clearAll") : t("wizard.selectAll")}
            </Button>
          </div>
          {visibleSections.map((section) => {
            const locked = section.key === "custom" && customRequired;
            return (
              <div key={section.key}>
                <Checkbox
                  name={`wz-include-${section.key}`}
                  label={`${t(section.labelKey)}: ${t(section.hintKey)}`}
                  checked={included.has(section.key)}
                  disabled={locked}
                  onChange={(e) =>
                    setIncluded((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(section.key);
                      else next.delete(section.key);
                      return next;
                    })
                  }
                />
                {locked && (
                  <p style={lockedNoteStyle}>
                    {t("wizard.includeRequiredCustom")}
                  </p>
                )}
              </div>
            );
          })}
          {selectionsDiffer && (
            <div style={saveSelectionsStyle}>
              <Checkbox
                name="wz-save-selections"
                label={t("wizard.saveSelections")}
                checked={false}
                disabled={savingSelections}
                onChange={(e) => {
                  if (e.target.checked) void saveSelectionsAsDefaults();
                }}
              />
            </div>
          )}
        </div>
      </Panel>
    );
  }

  function renderSet() {
    return (
      <Panel title={t("wizard.setTitle")}>
        <div style={checkColumnStyle}>
          <p style={mutedStyle}>
            The set's pieces — this list becomes the set's pieces
            when you save. Every piece can carry its own price —
            what that piece cost, or what it would cost to replace.
            A piece's price is its own number: it doesn't change
            the set's price.
          </p>
          <p style={mutedStyle}>{t("wizard.setStatusHelp")}</p>
          {pieces.map((piece, i) => (
            <div
              key={piece.id ?? `new-${i}`}
              style={pieceCardStyle}
            >
              <div style={pieceRowStyle}>
                <Select
                  aria-label={`Piece ${i + 1} kind`}
                  value={piece.kind}
                  onChange={(e) =>
                    setPiece(i, { kind: e.target.value as PieceDraft["kind"] })
                  }
                  style={pieceKindStyle}
                >
                  <option value="core">Core piece</option>
                  <option value="addon">Addon</option>
                </Select>
                <TextInput
                  aria-label={`Piece ${i + 1} name`}
                  value={piece.name}
                  onChange={(e) => setPiece(i, { name: e.target.value })}
                  placeholder="Piece name"
                  style={pieceNameStyle}
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
              <div style={pieceGridStyle}>
                <TextInput
                  aria-label={`Piece ${i + 1} part number`}
                  value={piece.part_number}
                  onChange={(e) => setPiece(i, { part_number: e.target.value })}
                  placeholder="Part #"
                />
                <TextInput
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
                  <option value="present">{t("wizard.pieceStatus.present")}</option>
                  <option value="missing">{t("wizard.pieceStatus.missing")}</option>
                  <option value="sold">{t("wizard.pieceStatus.sold")}</option>
                  <option value="removed">{t("wizard.pieceStatus.removed")}</option>
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
                  onChange={(v) => setPiece(i, { purchase_date: v })}
                  clearable
                />
              </div>
            </div>
          ))}
          <div style={navRowStyle}>
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
          <AttachedToolsPicker value={attachedPicks} onChange={setAttachedPicks} />
        </div>
      </Panel>
    );
  }

  function renderSection(key: string) {
    switch (key) {
      case "numbers":
        return (
          <Panel title={t("wizard.section.numbers")}>
            <div style={formGridStyle}>
              <RepeatableInputs
                idPrefix="wz-model"
                label="Model #"
                addLabel="Add model #"
                values={tool.model_numbers}
                onChange={(next) => setToolField("model_numbers", next)}
              />
              <RepeatableInputs
                idPrefix="wz-serial"
                label="Serial #"
                addLabel="Add serial #"
                values={tool.serial_numbers}
                onChange={(next) => setToolField("serial_numbers", next)}
              />
              <FormField label="UPC / barcode" htmlFor="wz-upc">
                <TextInput
                  id="wz-upc"
                  value={tool.upc}
                  onChange={(e) => setToolField("upc", e.target.value)}
                  placeholder="The number under the barcode"
                  inputMode="numeric"
                />
              </FormField>
            </div>
          </Panel>
        );
      case "warranty":
        return (
          <Panel title={t("wizard.section.warranty")}>
            <div style={formGridStyle}>
              <WarrantyFields
                idPrefix="wz"
                values={tool}
                onChange={(field, value) => setToolField(field, value)}
                dealerCompany={dealerCompany}
                dealerKnown={dealerKnown}
                resetKey="wizard-new"
              />
            </div>
          </Panel>
        );
      case "photos":
        return (
          <Panel title={t("wizard.section.photos")}>
            <StagedFilePicker
              kind="photo"
              files={stagedPhotos}
              onChange={setStagedPhotos}
              disabled={busy}
            />
          </Panel>
        );
      case "documents":
        return (
          <Panel title={t("wizard.section.documents")}>
            <StagedFilePicker
              kind="document"
              files={stagedDocs}
              onChange={setStagedDocs}
              disabled={busy}
            />
          </Panel>
        );
      case "receipts":
        return (
          <Panel title={t("wizard.section.receipts")}>
            <StagedFilePicker
              kind="receipt"
              files={stagedReceipts}
              onChange={setStagedReceipts}
              disabled={busy}
            />
          </Panel>
        );
      case "manuals":
        return (
          <Panel title={t("wizard.section.manuals")}>
            <div className="tv-manual-wizard-stack">
              <ManualFinder
                mode="wizard"
                brand={tool.brand}
                model={tool.model_numbers[0] ?? ""}
                picked={manualPick}
                onPick={setManualPick}
              />
              <StagedFilePicker
                kind="manual"
                files={stagedManuals}
                onChange={setStagedManuals}
                disabled={busy}
              />
              <FormField
                label={t("wizard.manuals.linkLabel")}
                hint={t("wizard.manuals.linkHint")}
              >
                <TextInput
                  value={wizardManualLink}
                  onChange={(e) => setWizardManualLink(e.target.value)}
                  placeholder={t("catalog.manualLink.placeholder")}
                  inputMode="url"
                  autoComplete="off"
                />
              </FormField>
            </div>
          </Panel>
        );
      case "size":
        return (
          <Panel title={t("wizard.section.size")}>
            <FormField label="Size" htmlFor="wz-size">
              <FieldSuggest
                field="size"
                id="wz-size"
                value={tool.size}
                onChange={(v) => setToolField("size", v)}
                placeholder="e.g. 1/2 in drive, 10 mm"
              />
            </FormField>
          </Panel>
        );
      case "tags":
        return (
          <Panel title={t("wizard.section.tags")}>
            {tags.length === 0 && tool.tag_ids.length === 0 ? (
              <p style={mutedStyle}>
                No tags yet — create your first below. Tags are your
                own labels for grouping and filtering (a truck box, a
                job, a warranty year…).
              </p>
            ) : (
              <div style={tagRowStyle}>
                {tags.map((tag) => {
                  const selected = tool.tag_ids.includes(tag.id);
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      aria-pressed={selected}
                      onClick={() =>
                        setToolField(
                          "tag_ids",
                          selected
                            ? tool.tag_ids.filter((x) => x !== tag.id)
                            : [...tool.tag_ids, tag.id],
                        )
                      }
                      style={tagButtonStyle}
                    >
                      <TagChip name={tag.name} color={tag.color} selected={selected} />
                    </button>
                  );
                })}
              </div>
            )}
            <div style={navRowStyle}>
              <div style={tagInputWrapStyle}>
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
        );
      case "costs":
        return (
          <Panel title={t("wizard.section.costs")}>
            <div style={formGridStyle}>
              <FormField label="Replacement cost (each)" htmlFor="wz-repl">
                <TextInput
                  id="wz-repl"
                  type="number"
                  min="0"
                  step="any"
                  value={tool.replacement_cost}
                  onChange={(e) => setToolField("replacement_cost", e.target.value)}
                />
              </FormField>
              <FormField label="MSRP (each)" htmlFor="wz-msrp">
                <TextInput
                  id="wz-msrp"
                  type="number"
                  min="0"
                  step="any"
                  value={tool.msrp}
                  onChange={(e) => setToolField("msrp", e.target.value)}
                />
              </FormField>
            </div>
            <p style={mutedStyle}>
              Replacement cost is what you'd pay today; MSRP is the
              list price. Both feed insurance valuations.
            </p>
          </Panel>
        );
      case "usage":
        return (
          <Panel title={t("wizard.section.usage")}>
            <div style={checkColumnStyle}>
              <Checkbox
                name="wz-consumable"
                label="Consumable: used up in the work (blades, bits, abrasives…)"
                checked={tool.consumable}
                onChange={(e) => setToolField("consumable", e.target.checked)}
              />
              {/* Business use is NOT rendered here anymore
                  (2026-11-07): it moved to the basics step —
                  the wizard's first screen — still bound to
                  the same tool.business_use draft field. One
                  render site, one source of truth. */}
              {tool.consumable && (
                <div style={rebuyBoxStyle}>
                  <p style={mutedStyle}>
                    Re-buy info — where the replacement comes from
                    when this runs out.
                  </p>
                  <div style={formGridStyle}>
                    <FormField label="Store" htmlFor="wz-rebuy-store">
                      <TextInput
                        id="wz-rebuy-store"
                        value={tool.rebuy_store}
                        onChange={(e) => setToolField("rebuy_store", e.target.value)}
                      />
                    </FormField>
                    <FormField label="Store SKU / part #" htmlFor="wz-rebuy-sku">
                      <TextInput
                        id="wz-rebuy-sku"
                        value={tool.rebuy_sku}
                        onChange={(e) => setToolField("rebuy_sku", e.target.value)}
                      />
                    </FormField>
                  </div>
                  <FormField label="Website" htmlFor="wz-rebuy-url">
                    <TextInput
                      id="wz-rebuy-url"
                      value={tool.rebuy_url}
                      onChange={(e) => setToolField("rebuy_url", e.target.value)}
                    />
                  </FormField>
                  <FormField label="Re-buy notes" htmlFor="wz-rebuy-notes">
                    <TextInput
                      id="wz-rebuy-notes"
                      value={tool.rebuy_notes}
                      onChange={(e) => setToolField("rebuy_notes", e.target.value)}
                    />
                  </FormField>
                </div>
              )}
            </div>
          </Panel>
        );
      case "schedule":
        return (
          <Panel title={t("wizard.section.schedule")}>
            <div style={formGridStyle}>
              <FormField label="Kind" htmlFor="wz-sched-kind">
                <Select
                  id="wz-sched-kind"
                  value={schedKind}
                  onChange={(e) =>
                    setSchedKind(e.target.value as InitialSchedule["kind"])
                  }
                >
                  <option value="calibration">Calibration</option>
                  <option value="service">Service</option>
                  <option value="inspection">Inspection</option>
                  <option value="other">Other</option>
                </Select>
              </FormField>
              <FormField label="Label" htmlFor="wz-sched-label">
                <TextInput
                  id="wz-sched-label"
                  value={schedLabel}
                  onChange={(e) => setSchedLabel(e.target.value)}
                  placeholder="e.g. Annual calibration"
                />
              </FormField>
              <FormField
                label="Every (days)"
                htmlFor="wz-sched-interval"
                hint="An interval or a due date — one of the two is required."
              >
                <TextInput
                  id="wz-sched-interval"
                  type="number"
                  min="1"
                  step="1"
                  value={schedInterval}
                  onChange={(e) => setSchedInterval(e.target.value)}
                />
              </FormField>
              <FormField label="First due date" htmlFor="wz-sched-due">
                <DatePicker
                  id="wz-sched-due"
                  value={schedDue}
                  onChange={setSchedDue}
                  clearable
                />
              </FormField>
            </div>
          </Panel>
        );
      case "notes":
        return (
          <Panel title={t("wizard.section.notes")}>
            <FormField label="Notes" htmlFor="wz-notes">
              <TextArea
                id="wz-notes"
                value={tool.notes}
                onChange={(e) => setToolField("notes", e.target.value)}
                placeholder="Anything worth remembering — searchable later."
              />
            </FormField>
          </Panel>
        );
      case "custom":
        return (
          <Panel title={t("wizard.section.custom")}>
            <div style={formGridStyle}>
              {defs.map((def) => (
                <CustomFieldInput
                  key={def.id}
                  def={def}
                  value={tool.custom_data[def.id]}
                  error={fieldErrors[def.id]}
                  onChange={(v) =>
                    setToolField("custom_data", {
                      ...tool.custom_data,
                      [def.id]: v,
                    })
                  }
                />
              ))}
            </div>
          </Panel>
        );
      default:
        return null;
    }
  }

  function reviewRow(label: string, value: ReactNode) {
    return (
      <div style={reviewRowStyle}>
        <span style={reviewLabelStyle}>{label}</span>
        <span>{value}</span>
      </div>
    );
  }

  function renderReview() {
    const qty = Number(tool.quantity);
    const unit = tool.purchase_price === "" ? null : Number(tool.purchase_price);
    const total =
      unit !== null && Number.isFinite(unit) && Number.isInteger(qty) && qty > 1
        ? money(String(unit * qty))
        : null;
    const warrantyText =
      tool.warranty_type === "lifetime"
        ? "Lifetime"
        : tool.warranty_months
          ? `${tool.warranty_months} months`
          : "";
    const cleanCount = (list: string[]) =>
      list.map((v) => v.trim()).filter(Boolean).length;
    return (
      <Panel title={t("wizard.reviewTitle")}>
        <div style={checkColumnStyle}>
          <p style={mutedStyle}>{t("wizard.reviewBody")}</p>
          {reviewRow("Name", tool.name || "—")}
          {tool.brand && reviewRow("Brand", tool.brand)}
          {tool.category && reviewRow("Category", tool.category)}
          {reviewRow("Location", locationLabel || "—")}
          {dealerCompany && tool.dealer_company_id === dealerCompany.id &&
            reviewRow("Dealer", dealerCompany.name)}
          {(tool.purchase_price || total) &&
            reviewRow(
              "Purchase price",
              <>
                {tool.purchase_price ? money(tool.purchase_price) : "—"}
                {Number(tool.quantity) > 1 && ` × ${tool.quantity}`}
                {total && (
                  <>
                    {" "}
                    — <strong>{total}</strong> total
                  </>
                )}
              </>,
            )}
          {/* Sweep B2-F15: the Review step formats the purchase
              date the way the rest of the site does ("Nov 11,
              2026") — it used to print the raw ISO string. */}
          {tool.purchase_date && reviewRow("Purchase date", displayDate(tool.purchase_date))}
          {truckYes && truckCtx && truckChargeValid() &&
            reviewRow(
              "Truck account",
              truckActiveAccounts.length > 0
                ? t("wizard.truckReviewCharge")
                    .replace("{amount}", money(truckAmount))
                    .replace("{dealer}", truckCtx.company_name)
                : selectedTruckAgent
                  ? t("wizard.truckReviewOpenAgent")
                      .replace("{amount}", money(truckAmount))
                      .replace("{dealer}", truckCtx.company_name)
                      .replace("{agent}", selectedTruckAgent.name)
                  : t("wizard.truckReviewOpen")
                      .replace("{amount}", money(truckAmount))
                      .replace("{dealer}", truckCtx.company_name),
            )}
          {tool.is_set &&
            reviewRow(
              "Set",
              `${pieces.length} piece${pieces.length === 1 ? "" : "s"}`,
            )}
          {included.has("numbers") &&
            reviewRow(
              t("wizard.section.numbers"),
              `${cleanCount(tool.model_numbers)} model · ${cleanCount(tool.serial_numbers)} serial`,
            )}
          {included.has("warranty") &&
            reviewRow(
              t("wizard.section.warranty"),
              [warrantyText, tool.warranty_provider]
                .filter(Boolean)
                .join(" — ") || "—",
            )}
          {included.has("photos") &&
            reviewRow(t("wizard.section.photos"), `${stagedPhotos.length} file${stagedPhotos.length === 1 ? "" : "s"}`)}
          {included.has("documents") &&
            reviewRow(t("wizard.section.documents"), `${stagedDocs.length} file${stagedDocs.length === 1 ? "" : "s"}`)}
          {included.has("receipts") &&
            reviewRow(t("wizard.section.receipts"), `${stagedReceipts.length} file${stagedReceipts.length === 1 ? "" : "s"}`)}
          {included.has("manuals") &&
            reviewRow(
              t("wizard.section.manuals"),
              [
                stagedManuals.length > 0 &&
                  `${stagedManuals.length} file${stagedManuals.length === 1 ? "" : "s"}`,
                manualPick && manualPick.title,
                wizardManualLink.trim() && t("wizard.manuals.linkLabel"),
              ]
                .filter(Boolean)
                .join(" · ") || "—",
            )}
          {included.has("size") && tool.size && reviewRow("Size", tool.size)}
          {included.has("tags") &&
            reviewRow(
              t("wizard.section.tags"),
              `${tool.tag_ids.length} tag${tool.tag_ids.length === 1 ? "" : "s"}`,
            )}
          {included.has("costs") &&
            (tool.replacement_cost || tool.msrp) &&
            reviewRow(
              t("wizard.section.costs"),
              [
                tool.replacement_cost && `Replacement ${money(tool.replacement_cost)}`,
                tool.msrp && `MSRP ${money(tool.msrp)}`,
              ]
                .filter(Boolean)
                .join(" · "),
            )}
          {included.has("schedule") &&
            reviewRow(
              t("wizard.section.schedule"),
              [schedKind, schedInterval && `every ${schedInterval} days`, schedDue && `due ${displayDate(schedDue)}`]
                .filter(Boolean)
                .join(" · "),
            )}
          {included.has("notes") &&
            tool.notes.trim() &&
            reviewRow("Notes", tool.notes.trim().slice(0, 90))}
        </div>
      </Panel>
    );
  }

  function renderBatteryPick() {
    const results = searchBatteryCatalog(batteryQuery);
    return (
      <Panel title={t("wizard.batteryPickTitle")}>
        <div style={checkColumnStyle}>
          <p style={mutedStyle}>{t("wizard.batteryPickBody")}</p>
          <TextInput
            value={batteryQuery}
            onChange={(e) => setBatteryQuery(e.target.value)}
            placeholder={t("wizard.batterySearchPlaceholder")}
            aria-label={t("wizard.batterySearchPlaceholder")}
          />
          <div style={batteryListStyle} role="listbox" aria-label={t("wizard.batteryPickTitle")}>
            {results.length === 0 ? (
              <p style={mutedStyle}>{t("wizard.batteryNoneFound")}</p>
            ) : (
              results.map((entry) => {
                const selected = batteryPicked === entry;
                return (
                  <button
                    key={`${entry.brand}-${entry.platform}-${entry.model}-${entry.label}`}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => pickBattery(entry)}
                    style={selected ? batteryRowSelectedStyle : batteryRowStyle}
                  >
                    <span style={batteryNameStyle}>
                      {entry.brand} {entry.platform} {entry.label}
                    </span>
                    <span style={batterySpecStyle}>
                      {[entry.model, `${entry.voltage}V`, `${entry.capacityAh}Ah`]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </button>
                );
              })
            )}
          </div>
          <div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setBatteryManual(true);
                setBatteryPicked(null);
                goTo(1);
              }}
            >
              {t("wizard.batteryManual")}
            </Button>
          </div>
        </div>
      </Panel>
    );
  }

  function renderBatteryLookup() {
    // Battery parity (2026-11-07): the SAME WizardLookup the
    // tool branch leads with — grounded chain, photo
    // identification, product-photo offer — wired to the
    // battery draft. The pick step already filled brand +
    // model for seeded packs, so the lookup can run at once;
    // hand-entered packs type (or photograph) them here.
    return (
      <WizardLookup
        brand={battery.brand}
        model={battery.model}
        upc={battery.upc}
        onBrandChange={(v) => setBatteryField("brand", v)}
        onModelChange={(v) => setBatteryField("model", v)}
        onUpcChange={(v) => setBatteryField("upc", v)}
        onApply={applyBatteryLookup}
        onApplyPhoto={applyLookupPhoto}
        onDone={() => goTo(stepIndex + 1)}
        seedPhoto={seedPhoto}
        onSeedPhotoConsumed={() => setSeedPhoto(null)}
      />
    );
  }

  function renderBatteryDetails() {
    return (
      <div style={pageStackStyle}>
        {batteryManual && (
          <Panel title={t("wizard.batteryManualTitle")}>
            <div style={formGridStyle}>
              <FormField label="Name" htmlFor="wzb-name" required error={fieldErrors.name}>
                <TextInput
                  id="wzb-name"
                  invalid={Boolean(fieldErrors.name)}
                  value={battery.name}
                  onChange={(e) => setBatteryField("name", e.target.value)}
                />
              </FormField>
              <FormField label="Brand" htmlFor="wzb-brand">
                <FieldSuggest
                  field="brand"
                  id="wzb-brand"
                  value={battery.brand}
                  onChange={(v) => setBatteryField("brand", v)}
                />
              </FormField>
              <FormField label="Platform" htmlFor="wzb-platform">
                <TextInput
                  id="wzb-platform"
                  value={battery.platform}
                  onChange={(e) => setBatteryField("platform", e.target.value)}
                  placeholder="e.g. M18, 20V MAX, LXT"
                />
              </FormField>
              <FormField label="Model" htmlFor="wzb-model">
                <TextInput
                  id="wzb-model"
                  value={battery.model}
                  onChange={(e) => setBatteryField("model", e.target.value)}
                />
              </FormField>
              <FormField label="Serial #" htmlFor="wzb-serial">
                <TextInput
                  id="wzb-serial"
                  value={battery.serial_number}
                  onChange={(e) => setBatteryField("serial_number", e.target.value)}
                />
              </FormField>
              <FormField label="Voltage" htmlFor="wzb-voltage">
                <TextInput
                  id="wzb-voltage"
                  type="number"
                  min="0"
                  step="any"
                  value={battery.voltage}
                  onChange={(e) => setBatteryField("voltage", e.target.value)}
                />
              </FormField>
              <FormField label="Capacity (Ah)" htmlFor="wzb-capacity">
                <TextInput
                  id="wzb-capacity"
                  type="number"
                  min="0"
                  step="any"
                  value={battery.capacity_ah}
                  onChange={(e) => setBatteryField("capacity_ah", e.target.value)}
                />
              </FormField>
              <FormField label="Chemistry" htmlFor="wzb-chemistry">
                <TextInput
                  id="wzb-chemistry"
                  value={battery.chemistry}
                  onChange={(e) => setBatteryField("chemistry", e.target.value)}
                  placeholder="e.g. Li-ion"
                />
              </FormField>
            </div>
          </Panel>
        )}
        <Panel title={t("wizard.batteryDetailsTitle")}>
          <div style={checkColumnStyle}>
            <p style={mutedStyle}>{t("wizard.batteryDetailsBody")}</p>
            {!batteryManual && battery.name && (
              <p style={mutedStyle}>
                {t("wizard.batteryAdding")} <strong>{battery.name}</strong>
                {battery.model && <> · {battery.model}</>}
              </p>
            )}
            <div style={formGridStyle}>
              <DealerPicker
                id="wzb-dealer"
                label="Dealer (bought from)"
                hint="The company you bought it from — used for dealer contacts and warranty help."
                value={battery.dealer_company_id}
                onChange={(companyId) => setBatteryField("dealer_company_id", companyId)}
                onAvailability={setDealersAvailable}
                onCompany={(company) => {
                  setDealerCompany(company);
                  setDealerKnown(true);
                }}
              />
              <FormField label="Category" htmlFor="wzb-category">
                <CategoryPicker
                  id="wzb-category"
                  value={battery.category}
                  onChange={(v) => setBatteryField("category", v)}
                  defaultSystemKey="batteries"
                />
              </FormField>
              <FormField label={t("wizard.batteryLocation")} htmlFor="wzb-location">
                <LocationTreePicker
                  id="wzb-location"
                  value={battery.location_id || null}
                  onChange={(locationId) =>
                    setBatteryField("location_id", locationId ?? "")
                  }
                />
              </FormField>
              <FormField label="Purchase price (each)" htmlFor="wzb-pprice">
                <TextInput
                  id="wzb-pprice"
                  type="number"
                  min="0"
                  step="any"
                  value={battery.purchase_price}
                  onChange={(e) => setBatteryField("purchase_price", e.target.value)}
                />
              </FormField>
              <FormField label="Quantity" htmlFor="wzb-qty">
                <TextInput
                  id="wzb-qty"
                  type="number"
                  min="1"
                  step="1"
                  value={battery.quantity}
                  onChange={(e) => setBatteryField("quantity", e.target.value)}
                />
              </FormField>
              <FormField label="Purchase date" htmlFor="wzb-pdate">
                <DatePicker
                  id="wzb-pdate"
                  value={battery.purchase_date}
                  onChange={(v) => setBatteryField("purchase_date", v)}
                  clearable
                />
              </FormField>
              <WarrantyFields
                idPrefix="wzb"
                values={battery}
                onChange={(field, value) => setBatteryField(field, value)}
                dealerCompany={dealerCompany}
                dealerKnown={dealerKnown}
                resetKey="wizard-battery-new"
              />
            </div>
            {/* Business use on the battery branch's first
                data-entry screen (Ryan, 2026-11-07), bound to
                the same battery.business_use the full battery
                form uses — one render site, one field. */}
            <Checkbox
              name="wzb-business-use"
              label="Business use: this battery earns its keep (used for work you charge for)"
              checked={battery.business_use}
              onChange={(e) => setBatteryField("business_use", e.target.checked)}
            />
            {renderTruckCharge()}
          </div>
        </Panel>
        {/* Manual finder parity (2026-11-07): the same finder
            the tool branch's manuals section carries — the
            pick (or a pasted link) imports the moment the
            battery is created. */}
        <Panel title={t("wizard.section.manuals")}>
          <div className="tv-manual-wizard-stack">
            <ManualFinder
              mode="wizard"
              brand={battery.brand}
              model={battery.model}
              picked={batteryManualPick}
              onPick={setBatteryManualPick}
            />
            <FormField
              label={t("wizard.manuals.linkLabel")}
              hint={t("wizard.manuals.linkHint")}
            >
              <TextInput
                value={batteryManualLink}
                onChange={(e) => setBatteryManualLink(e.target.value)}
                placeholder={t("catalog.manualLink.placeholder")}
                inputMode="url"
                autoComplete="off"
              />
            </FormField>
          </div>
        </Panel>
      </div>
    );
  }

  // ---- chrome ----------------------------------------------------------------
  const isFinalStep =
    (branch === "tool" && step === "review") ||
    (branch === "battery" && step === "battery-details");
  const canBack =
    branch !== "fork" && (stepIndex > 0 || !presetBattery);
  // Sweep B2-F14: on the tool lookup step the footer's Next is
  // hidden — the lookup panel's own two buttons ("Look it up" /
  // "Skip quick lookup") are the step's whole story. Next did
  // exactly what Skip does, so a first-time user faced two
  // competing forward paths and had to guess which was real.
  const showNext =
    branch === "tool" && step !== "review" && step !== "lookup"
      ? true
      : branch === "battery" && step === "battery-pick"
        ? batteryPicked !== null || batteryManual
        : branch === "battery" && step === "battery-lookup"
          ? true
          : false;

  function onBack() {
    if (stepIndex > 0) goTo(stepIndex - 1);
    else if (!presetBattery) setBranch("fork");
  }

  const heading =
    branch === "fork"
      ? t("wizard.forkQuestion")
      : branch === "battery"
        ? "Add a battery"
        : "Add a tool";

  return (
    <RequireAuth>
      <div className="tv-wizard" style={pageWidthStyle}>
        <div>
          <Breadcrumbs
            items={[
              { label: "Inventory", to: "/inventory" },
              { label: heading },
            ]}
          />
          <h1 style={pageTitleStyle}>{heading}</h1>
        </div>

        {branch !== "fork" && (
          <div style={checkColumnStyle}>
            <p style={mutedStyle}>
              {t("wizard.stepOf")
                .replace("{step}", String(stepIndex + 1))
                .replace("{total}", String(steps.length))}{" "}
              — {stepTitle(step)}
            </p>
            <ProgressBar
              value={Math.round(((stepIndex + 1) / steps.length) * 100)}
              label={stepTitle(step)}
            />
          </div>
        )}

        {busy && (
          <div style={checkColumnStyle} role="status">
            <ProgressBar
              value={
                stagedCount > 0
                  ? Math.round((stagedDone / Math.max(stagedCount, 1)) * 100)
                  : 50
              }
              label={
                uploadingFiles
                  ? `Uploading files (${stagedDone} of ${stagedCount})`
                  : "Saving"
              }
            />
          </div>
        )}

        {!vocabLoaded && branch === "tool" ? (
          <p style={loadingStyle}>
            <Spinner size="sm" /> Loading…
          </p>
        ) : step === "fork" ? (
          renderFork()
        ) : step === "lookup" ? (
          renderLookup()
        ) : step === "basics" ? (
          renderBasics()
        ) : step === "include" ? (
          renderInclude()
        ) : step === "set" ? (
          renderSet()
        ) : step === "review" ? (
          renderReview()
        ) : step === "battery-pick" ? (
          renderBatteryPick()
        ) : step === "battery-lookup" ? (
          renderBatteryLookup()
        ) : step === "battery-details" ? (
          renderBatteryDetails()
        ) : (
          renderSection(step)
        )}

        {duplicate.length > 0 && (
          <Panel title="You already have one like this">
            {duplicate.map((existing) => (
              <p key={existing.id} style={dupRowStyle}>
                <strong>{existing.name}</strong> — {existing.brand}{" "}
                {existing.model}
                {existing.serial_number ? `, serial ${existing.serial_number}` : ""}
                <span className="tv-muted"> (matched on the {existing.matched_on})</span>
              </p>
            ))}
            <div style={navRowStyle}>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setDuplicate([]);
                  if (branch === "battery") void saveBattery(true);
                  else void saveTool(true);
                }}
              >
                Add anyway
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  guard.requestExit(() =>
                    navigate(
                      branch === "battery"
                        ? `/inventory/batteries/${duplicate[0].id}`
                        : `/inventory/${duplicate[0].id}`,
                    ),
                  )
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

        {branch !== "fork" && (
          <div style={navRowStyle}>
            {canBack && (
              <Button type="button" variant="secondary" onClick={onBack} disabled={busy}>
                {t("wizard.back")}
              </Button>
            )}
            {showNext && (
              <Button type="button" onClick={onNext} disabled={busy}>
                {t("wizard.next")}
              </Button>
            )}
            {skippableStep && (
              <Button
                type="button"
                variant="ghost"
                onClick={skipStep}
                disabled={busy}
              >
                {t("wizard.skip")}
              </Button>
            )}
            {isFinalStep && (
              <Button
                type="button"
                loading={busy}
                onClick={() => {
                  if (branch === "battery") void saveBattery();
                  else void saveTool();
                }}
              >
                {busy
                  ? uploadingFiles
                    ? `Uploading files… (${stagedDone} of ${stagedCount})`
                    : t("wizard.saving")
                  : branch === "battery"
                    ? t("wizard.saveBattery")
                    : t("wizard.saveTool")}
              </Button>
            )}
            <LinkButton to="/inventory" variant="secondary">
              {t("common.cancel")}
            </LinkButton>
          </div>
        )}
        {branch === "fork" && (
          <div style={navRowStyle}>
            <LinkButton to="/inventory" variant="secondary">
              {t("common.cancel")}
            </LinkButton>
          </div>
        )}
      </div>

      <Modal
        open={sharePrompt !== null}
        onClose={skipSharePrompt}
        title="Add to your shared list?"
        footer={
          <>
            <Button variant="secondary" onClick={skipSharePrompt} disabled={promptBusy}>
              Not now
            </Button>
            <Button onClick={confirmSharePrompt} loading={promptBusy}>
              Add
            </Button>
          </>
        }
      >
        {sharePrompt && (
          <div style={checkColumnStyle}>
            <p style={mutedStyle}>
              You're sharing your list with{" "}
              {sharePrompt.groups
                .map((g) => accountTypeLabel(g.recipient_group))
                .join(" and ")}
              . Add "{sharePrompt.name}" to the shared items?
            </p>
            {promptError && <Alert tone="danger">{promptError}</Alert>}
            <div style={checkColumnStyle}>
              {sharePrompt.groups.map((g) => {
                const alreadyShared = (g.resolved_items ?? []).some(
                  (r) => r.id === sharePrompt.id,
                );
                const category = (sharePrompt.category ?? "").trim();
                const hasCategoryRule = (g.rules ?? []).some(
                  (r) =>
                    r.scope === "category" &&
                    r.scope_value.trim().toLowerCase() === category.toLowerCase(),
                );
                return (
                  <div key={g.recipient_group}>
                    {alreadyShared ? (
                      <p style={mutedStyle}>
                        Already shared with {accountTypeLabel(g.recipient_group)} —
                        one of your sharing rules covers it.
                      </p>
                    ) : (
                      <Checkbox
                        name={`wz-share-prompt-${g.recipient_group}`}
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
                      <div style={ruleIndentStyle}>
                        <Checkbox
                          name={`wz-share-prompt-rule-${g.recipient_group}`}
                          label={`Share by rule: the whole “${category}” category with ${accountTypeLabel(g.recipient_group)}, future items too`}
                          checked={promptRuleChecked.has(g.recipient_group)}
                          onChange={(e) =>
                            setPromptRuleChecked((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(g.recipient_group);
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
      {guard.dialog}
    </RequireAuth>
  );
}

const pageTitleStyle = { margin: "0.25rem 0 0", fontSize: "1.5rem" } as const;
const loadingStyle = {
  color: "var(--text-muted)",
  display: "flex",
  gap: "var(--space-2)",
  alignItems: "center",
} as const;
const pieceCardStyle = {
  display: "grid",
  gap: "0.5rem",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  padding: "0.7rem",
} as const;
const pieceRowStyle = { display: "flex", gap: "0.5rem", flexWrap: "wrap" } as const;
const pieceKindStyle = { flex: "0 1 130px" } as const;
const pieceNameStyle = { flex: "1 1 180px" } as const;
const pieceGridStyle = {
  display: "grid",
  gap: "0.5rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 140px), 1fr))",
} as const;
const rebuyBoxStyle = {
  display: "grid",
  gap: "0.7rem",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  padding: "0.8rem",
} as const;
const tagRowStyle = {
  display: "flex",
  gap: "0.4rem",
  flexWrap: "wrap",
  marginBottom: "0.7rem",
} as const;
const tagButtonStyle = {
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
} as const;
const tagInputWrapStyle = { flex: "1 1 180px" } as const;
const reviewRowStyle = {
  display: "flex",
  gap: "0.75rem",
  flexWrap: "wrap",
} as const;
const reviewLabelStyle = {
  flex: "0 0 150px",
  color: "var(--text-muted)",
  fontSize: "0.9rem",
} as const;
const batteryListStyle = {
  display: "grid",
  gap: "0.4rem",
  maxHeight: "340px",
  overflowY: "auto",
} as const;
const batteryRowStyle = {
  display: "grid",
  gap: "0.15rem",
  textAlign: "left",
  width: "100%",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  background: "none",
  padding: "0.55rem 0.7rem",
  cursor: "pointer",
  color: "inherit",
} as const;
const batteryRowSelectedStyle = {
  ...batteryRowStyle,
  borderColor: "var(--accent)",
  outline: "1px solid var(--accent)",
} as const;
const batteryNameStyle = { fontWeight: 600 } as const;
const batterySpecStyle = { color: "var(--text-muted)", fontSize: "0.85rem" } as const;
const ruleIndentStyle = { marginLeft: "1.6rem" } as const;
const setCheckboxRowStyle = { marginTop: "0.9rem" } as const;
const lockedNoteStyle = {
  color: "var(--text-muted)",
  fontSize: "0.9rem",
  marginLeft: "1.6rem",
} as const;
const dupRowStyle = { marginTop: 0 } as const;
const saveSelectionsStyle = {
  borderTop: "1px solid var(--edge)",
  paddingTop: "0.7rem",
} as const;

