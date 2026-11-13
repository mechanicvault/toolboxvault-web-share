import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  FormField,
  Panel,
  Radio,
  Select,
  Spinner,
  useToast,
  LinkButton,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import {
  confirmImport,
  discardImportSession,
  dryRunImport,
  resolveImportValues,
  suggestImportMapping,
  uploadImportFile,
  type ImportDryRun,
  type ImportField,
  type ImportKind,
  type ImportMapping,
  type ImportMappingApplied,
  type ImportResolutionDecision,
  type ImportResolveEntry,
  type ImportResolvePlan,
  type ImportResolutions,
  type ImportSession,
  type ImportSummary,
  type ImportTarget,
} from "./importApi";

/**
 * Spreadsheet importer (inventory module, 2026-10-19): upload a
 * .csv/.xlsx ONCE, say whether the rows are Tools or Batteries,
 * match each file column to an asset field, RESOLVE the values
 * (smart matching: dealers, brands, categories, tags and locations
 * are reconciled against what the user already has — exact matches
 * and remembered answers apply automatically and are listed,
 * lookalikes always ask), run a dry run that classifies every row
 * (ok / warning / error) and predicts the plan-cap impact, then
 * confirm. The server re-derives everything from the stored file
 * at confirm time, so what the check showed is what the import
 * does. Imported rows are ordinary assets.
 */

const STATUS_TONES = {
  ok: "success",
  warning: "warning",
  error: "danger",
  blank: "neutral",
} as const;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong. Try again.";
}

/** Smart value matching (2026-10-19): the Resolve matches step. */
const FIELD_NOUNS: Record<string, string> = {
  dealer_name: "dealer",
  brand: "brand",
  category: "category",
  tags: "tag",
  location: "location",
};

function targetKey(target: ImportTarget): string {
  return target.target_id ?? target.target_value ?? target.label;
}

function decisionOutcome(
  raw: string,
  decision: ImportResolutionDecision,
  options: ImportTarget[],
): string {
  if (decision.action === "unset") return "left unset";
  if (decision.action === "create") return `added as new ("${raw}")`;
  const match = options.find(
    (option) =>
      (decision.target_id && option.target_id === decision.target_id) ||
      (decision.target_value && option.target_value === decision.target_value),
  );
  return match ? match.label : (decision.target_value ?? "matched");
}

function appliedOutcome(mapping: ImportMappingApplied): string {
  if (mapping.action === "unset") return "left unset";
  if (mapping.action === "create") return `added as new ("${mapping.raw}")`;
  return mapping.target_label;
}

function appliedSourceLabel(source: string): string {
  if (source === "exact") return "matched automatically";
  if (source === "learned") return "remembered answer";
  return "your answer";
}

interface ResolveEntryCardProps {
  entry: ImportResolveEntry;
  options: ImportTarget[];
  decision: ImportResolutionDecision | undefined;
  onDecide: (decision: ImportResolutionDecision | null) => void;
}

/**
 * One distinct incoming value: either a settled line (automatic
 * match, remembered answer, or the user's answer — each with a
 * Change button, because silent never means locked) or an open
 * question card. Fuzzy candidates are OFFERED, never chosen for
 * the user: Mac Tools is not Matco Tools, and only the user can
 * say which one their file means.
 */
function ResolveEntryCard({
  entry,
  options,
  decision,
  onDecide,
}: ResolveEntryCardProps) {
  const noun = FIELD_NOUNS[entry.field] ?? entry.field;
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState<string>("");
  const [otherKey, setOtherKey] = useState<string>("");
  const [parentKey, setParentKey] = useState<string>("");

  const showEditor = editing || (entry.status === "ask" && !decision);

  function openEditor() {
    setChoice("");
    setOtherKey("");
    setParentKey("");
    setEditing(true);
  }

  function buildDecision(): ImportResolutionDecision | null {
    if (choice.startsWith("cand:")) {
      const candidate = entry.candidates[Number(choice.slice(5))];
      if (!candidate) return null;
      return {
        action: "map",
        target_id: candidate.target_id,
        target_value: candidate.target_value,
      };
    }
    if (choice === "other") {
      const target = options.find((option) => targetKey(option) === otherKey);
      if (!target) return null;
      return {
        action: "map",
        target_id: target.target_id,
        target_value: target.target_value,
      };
    }
    if (choice === "create") {
      return {
        action: "create",
        parent_id: entry.field === "location" ? parentKey || null : undefined,
      };
    }
    if (choice === "unset") return { action: "unset" };
    return null;
  }

  if (!showEditor) {
    const effective = decision ?? entry.resolution;
    return (
      <div
        style={{
          display: "flex",
          gap: "0.6rem",
          alignItems: "center",
          flexWrap: "wrap",
          borderTop: "1px solid var(--border, #ddd)",
          paddingTop: "0.5rem",
        }}
      >
        <span>
          <strong>&ldquo;{entry.raw}&rdquo;</strong> →{" "}
          {effective
            ? decisionOutcome(entry.raw, effective, options)
            : entry.raw}
        </span>
        <Badge tone={decision ? "success" : "neutral"}>
          {decision
            ? "Your answer"
            : entry.source === "learned"
              ? "Remembered"
              : "Matched automatically"}
        </Badge>
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          {entry.rows} row{entry.rows === 1 ? "" : "s"}
        </span>
        <Button variant="ghost" onClick={openEditor}>
          Change
        </Button>
      </div>
    );
  }

  const built = buildDecision();
  return (
    <div
      style={{
        display: "grid",
        gap: "0.55rem",
        border: "1px solid var(--border, #ddd)",
        borderRadius: "0.5rem",
        padding: "0.8rem",
      }}
    >
      <div style={{ fontWeight: 600 }}>
        {entry.candidates.length > 0 ? (
          <>
            Is your {noun} &ldquo;{entry.raw}&rdquo; the same as &ldquo;
            {entry.candidates[0].label}&rdquo;?
          </>
        ) : (
          <>
            &ldquo;{entry.raw}&rdquo; doesn&apos;t match any {noun} you have
            yet.
          </>
        )}
      </div>
      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
        {entry.rows} row{entry.rows === 1 ? "" : "s"} in the file use this{" "}
        {noun}. Your answer applies to all of them — and it&apos;s remembered
        for next time.
      </p>
      <div style={{ display: "grid", gap: "0.4rem" }}>
        {entry.candidates.map((candidate, index) => (
          <Radio
            key={targetKey(candidate)}
            name={`resolve-${entry.field}-${entry.raw}`}
            value={`cand:${index}`}
            label={<>Yes — same as &ldquo;{candidate.label}&rdquo;</>}
            checked={choice === `cand:${index}`}
            onChange={() => setChoice(`cand:${index}`)}
          />
        ))}
        {options.length > 0 && (
          <Radio
            name={`resolve-${entry.field}-${entry.raw}`}
            value="other"
            label="It's a different one I already have:"
            checked={choice === "other"}
            onChange={() => setChoice("other")}
          />
        )}
        {choice === "other" && (
          <Select
            aria-label={`Pick an existing ${noun}`}
            value={otherKey}
            onChange={(e) => setOtherKey(e.target.value)}
          >
            <option value="">— Pick one —</option>
            {options.map((option) => (
              <option key={targetKey(option)} value={targetKey(option)}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
        <Radio
          name={`resolve-${entry.field}-${entry.raw}`}
          value="create"
          label={
            <>
              Add &ldquo;{entry.raw}&rdquo; as a new {noun}
              {entry.field === "dealer_name"
                ? " (your own private company)"
                : ""}
            </>
          }
          checked={choice === "create"}
          onChange={() => setChoice("create")}
        />
        {choice === "create" && entry.field === "location" && (
          <Select
            aria-label="Create the new location under"
            value={parentKey}
            onChange={(e) => setParentKey(e.target.value)}
          >
            <option value="">— Top level (a new place) —</option>
            {options.map((option) => (
              <option key={targetKey(option)} value={option.target_id ?? ""}>
                Under {option.label}
              </option>
            ))}
          </Select>
        )}
        <Radio
          name={`resolve-${entry.field}-${entry.raw}`}
          value="unset"
          label="Leave it unset for this import"
          checked={choice === "unset"}
          onChange={() => setChoice("unset")}
        />
      </div>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Button
          disabled={!built}
          onClick={() => {
            if (built) {
              onDecide(built);
              setEditing(false);
            }
          }}
        >
          Use this answer
        </Button>
        {(decision || entry.status === "auto") && (
          <Button variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
}

export default function ImportPage() {
  const { toast } = useToast();
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<ImportKind>("tool");
  const [session, setSession] = useState<ImportSession | null>(null);
  const [fields, setFields] = useState<ImportField[]>([]);
  const [mapping, setMapping] = useState<Record<number, string>>({});
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [plan, setPlan] = useState<ImportResolvePlan | null>(null);
  const [decisions, setDecisions] = useState<ImportResolutions>({});
  const [dryRun, setDryRun] = useState<ImportDryRun | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [busy, setBusy] = useState<
    "" | "upload" | "suggest" | "resolve" | "dry" | "confirm"
  >("");
  const [error, setError] = useState<string | null>(null);

  /** Any change to the columns or the answers invalidates the
   *  resolve plan and the check — both are re-derived from the
   *  current state, so they can never disagree with the import. */
  function resetResolution() {
    setPlan(null);
    setDecisions({});
    setDryRun(null);
  }

  const unanswered = useMemo(() => {
    if (!plan) return 0;
    return plan.entries.filter(
      (entry) =>
        entry.status === "ask" && !decisions[entry.field]?.[entry.raw],
    ).length;
  }, [plan, decisions]);

  function handleDecide(
    field: string,
    raw: string,
    decision: ImportResolutionDecision | null,
  ) {
    setDecisions((prev) => {
      const next: ImportResolutions = { ...prev, [field]: { ...prev[field] } };
      if (decision) next[field][raw] = decision;
      else delete next[field][raw];
      return next;
    });
    setDryRun(null);
  }

  /** One tap for the common first-import case: every value with
   *  nothing similar already on file is simply new. */
  function acceptAllNewValues() {
    if (!plan) return;
    setDecisions((prev) => {
      const next: ImportResolutions = { ...prev };
      for (const entry of plan.entries) {
        if (
          entry.status === "ask" &&
          entry.candidates.length === 0 &&
          !next[entry.field]?.[entry.raw]
        ) {
          next[entry.field] = {
            ...next[entry.field],
            [entry.raw]: { action: "create" },
          };
        }
      }
      return next;
    });
    setDryRun(null);
  }

  /** List fields (type "multi" — Model numbers, Serial numbers,
   *  Set serials) may take several columns at once; their values
   *  merge. Every other field takes exactly one column, and a
   *  second column mapped to it is the blocking duplicate the
   *  alert below names. */
  const multiFieldKeys = useMemo(
    () => new Set(fields.filter((field) => field.type === "multi").map((field) => field.key)),
    [fields],
  );

  const duplicateField = useMemo(() => {
    const seen = new Map<string, number>();
    for (const [index, key] of Object.entries(mapping)) {
      if (multiFieldKeys.has(key)) continue;
      if (seen.has(key)) return { key, first: seen.get(key)!, second: Number(index) };
      seen.set(key, Number(index));
    }
    return null;
  }, [mapping, multiFieldKeys]);

  const nameMapped = useMemo(
    () => Object.values(mapping).includes("name"),
    [mapping],
  );

  function mappingPayload(): ImportMapping {
    const out: ImportMapping = {};
    if (session) {
      session.headers.forEach((_, index) => {
        out[String(index)] = mapping[index] ?? null;
      });
    }
    return out;
  }

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Pick a .csv or .xlsx file first.");
      return;
    }
    setBusy("upload");
    setError(null);
    setSummary(null);
    resetResolution();
    try {
      const uploaded = await uploadImportFile(file, kind);
      setSession(uploaded);
      setKind(uploaded.kind);
      setFields(uploaded.fields);
      const initial: Record<number, string> = {};
      for (const [index, key] of Object.entries(uploaded.suggested_mapping)) {
        initial[Number(index)] = key;
      }
      setMapping(initial);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function handleKindChange(next: ImportKind) {
    setKind(next);
    resetResolution();
    if (!session) return;
    setBusy("suggest");
    setError(null);
    try {
      const suggestion = await suggestImportMapping(session.session_id, next);
      setFields(suggestion.fields);
      const initial: Record<number, string> = {};
      for (const [index, key] of Object.entries(suggestion.suggested_mapping)) {
        initial[Number(index)] = key;
      }
      setMapping(initial);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function handleResolve() {
    if (!session) return;
    setBusy("resolve");
    setError(null);
    try {
      const result = await resolveImportValues(
        session.session_id,
        kind,
        mappingPayload(),
      );
      setPlan(result);
      setDecisions({});
      setDryRun(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function handleDryRun() {
    if (!session) return;
    setBusy("dry");
    setError(null);
    try {
      const result = await dryRunImport(
        session.session_id,
        kind,
        mappingPayload(),
        skipDuplicates,
        decisions,
      );
      setDryRun(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function handleConfirm() {
    if (!session) return;
    setBusy("confirm");
    setError(null);
    try {
      const result = await confirmImport(
        session.session_id,
        kind,
        mappingPayload(),
        skipDuplicates,
        decisions,
      );
      setSummary(result);
      setSession(null);
      setPlan(null);
      setDecisions({});
      setDryRun(null);
      toast(`Imported ${result.imported} item${result.imported === 1 ? "" : "s"}.`, {
        title: "Import complete",
        tone: "success",
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function handleStartOver() {
    if (session) {
      try {
        await discardImportSession(session.session_id);
      } catch {
        /* an expired session is already gone — starting over is the point */
      }
    }
    setSession(null);
    setDryRun(null);
    setSummary(null);
    setMapping({});
    setPlan(null);
    setDecisions({});
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <RequireAuth>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <div
          style={{
            display: "flex",
            gap: "1rem",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Import from a spreadsheet</h1>
          <LinkButton to="/inventory" variant="secondary">Back to inventory</LinkButton>
        </div>

        {error && (
          <Alert tone="danger" title="That didn't work">
            {error}
          </Alert>
        )}

        {summary && (
          <Panel>
            <div style={{ display: "grid", gap: "0.6rem" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Import finished</h2>
              <p style={{ margin: 0 }}>
                <strong>{summary.imported}</strong> imported
                {summary.skipped_duplicates > 0 &&
                  ` · ${summary.skipped_duplicates} duplicate${summary.skipped_duplicates === 1 ? "" : "s"} skipped`}
                {summary.skipped_over_cap > 0 &&
                  ` · ${summary.skipped_over_cap} skipped — over your plan's item limit (rows ${summary.over_cap_rows.join(", ")})`}
                {summary.errors > 0 &&
                  ` · ${summary.errors} row${summary.errors === 1 ? "" : "s"} couldn't import (rows ${summary.error_rows.map((r) => r.row).join(", ")})`}
                {` · ${summary.total_rows} rows in the file.`}
              </p>
              {summary.error_rows.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                  {summary.error_rows.map((row) => (
                    <li key={row.row}>
                      Row {row.row}: {row.messages.join(" ")}
                    </li>
                  ))}
                </ul>
              )}
              {summary.mappings.length > 0 && (
                <div style={{ display: "grid", gap: "0.3rem" }}>
                  <strong>Values matched</strong>
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                    {summary.mappings.map((mapping) => (
                      <li key={`${mapping.field}:${mapping.raw}`}>
                        &ldquo;{mapping.raw}&rdquo; → {appliedOutcome(mapping)}{" "}
                        · {mapping.rows} row{mapping.rows === 1 ? "" : "s"} ·{" "}
                        {appliedSourceLabel(mapping.source)}
                      </li>
                    ))}
                  </ul>
                  <p style={{ margin: 0, color: "var(--text-muted)" }}>
                    Matched something wrong? Select the items in your
                    inventory and use Bulk edit to re-point them — and fix
                    the remembered answer in{" "}
                    <Link to="/settings/import-matching">
                      Settings → Import matching
                    </Link>
                    .
                  </p>
                </div>
              )}
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <LinkButton to="/inventory">View inventory</LinkButton>
                <Button variant="secondary" onClick={handleStartOver}>
                  Import another file
                </Button>
              </div>
            </div>
          </Panel>
        )}

        {!summary && (
          <Panel>
            <div style={{ display: "grid", gap: "0.9rem" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>1 · Choose a file</h2>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                A .csv or .xlsx file with a header row — up to 2,000 rows. The file
                stays on the server while you map and check it; nothing imports
                until you confirm.
              </p>
              <div
                style={{
                  display: "flex",
                  gap: "0.9rem",
                  alignItems: "end",
                  flexWrap: "wrap",
                }}
              >
                <FormField label="Spreadsheet" htmlFor="import-file">
                  <input
                    id="import-file"
                    ref={fileRef}
                    type="file"
                    accept=".csv,.xlsx"
                    className="tv-input"
                  />
                </FormField>
                <FormField label="These rows are" htmlFor="import-kind">
                  <Select
                    id="import-kind"
                    value={kind}
                    onChange={(e) => void handleKindChange(e.target.value as ImportKind)}
                  >
                    <option value="tool">Tools</option>
                    <option value="battery">Batteries</option>
                  </Select>
                </FormField>
                <Button onClick={handleUpload} loading={busy === "upload"}>
                  Upload &amp; preview
                </Button>
              </div>
              {session && (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  <strong>{session.filename}</strong> — {session.row_count} data row
                  {session.row_count === 1 ? "" : "s"} found. Preview of the first{" "}
                  {session.sample_rows.length}:
                </p>
              )}
              {session && (
                <div style={{ overflowX: "auto" }}>
                  <table className="tv-table">
                    <thead>
                      <tr>
                        {session.headers.map((header, index) => (
                          <th key={index}>{header || `Column ${index + 1}`}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {session.sample_rows.map((row, r) => (
                        <tr key={r}>
                          {session.headers.map((_, c) => (
                            <td key={c}>{row[c] ?? ""}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </Panel>
        )}

        {!summary && session && (
          <Panel>
            <div style={{ display: "grid", gap: "0.9rem" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>2 · Match the columns</h2>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                Tell the importer what each column is. Suggestions are pre-filled
                from the header names — change any of them. In the next step,
                dealer names, brands, categories, tags and locations are matched
                against what you already have — lookalikes always ask first, and
                nothing is created without your say-so. Model/serial/tag columns
                can hold several values split by <code>;</code> or{" "}
                <code>,</code>. List fields — Model numbers, Serial numbers and
                Set serials — can also take <em>several columns</em> at once:
                their values merge into one list, in column order. Every other
                field takes exactly one column.
              </p>
              {duplicateField && (
                <Alert tone="warning" title="One field, one column">
                  Columns {duplicateField.first + 1} and {duplicateField.second + 1}{" "}
                  are both set to{" "}
                  <strong>
                    {fields.find((field) => field.key === duplicateField.key)?.label ??
                      duplicateField.key}
                  </strong>
                  , which takes one column only. Unmap one of them — only list
                  fields (Model numbers, Serial numbers, Set serials) can combine
                  several columns.
                </Alert>
              )}
              {!nameMapped && (
                <Alert tone="warning" title="Name is required">
                  Map one column to <strong>Name</strong> — every item needs one.
                </Alert>
              )}
              <div style={{ display: "grid", gap: "0.6rem" }}>
                {/* Column headers (Ryan, 2026-10-25): name each side
                    of the mapping grid — the left is the file's own
                    columns, the right is the Toolbox Vault fields —
                    so the two can never be mistaken for each other. */}
                <div className="tv-import-map-head" aria-hidden="true">
                  <span>{t("import.fileColumn")}</span>
                  <span>{t("import.siteField")}</span>
                </div>
                {session.headers.map((header, index) => (
                  <div
                    key={index}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(140px, 1fr) minmax(180px, 1fr)",
                      gap: "0.75rem",
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600 }}>
                        {header || `Column ${index + 1}`}
                      </div>
                      <div
                        style={{
                          color: "var(--text-muted)",
                          fontSize: "0.85rem",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {session.sample_rows
                          .map((row) => row[index] ?? "")
                          .filter(Boolean)
                          .slice(0, 3)
                          .join(" · ")}
                      </div>
                    </div>
                    <Select
                      aria-label={`Field for column ${header || index + 1}`}
                      value={mapping[index] ?? ""}
                      onChange={(e) => {
                        const value = e.target.value;
                        setMapping((prev) => {
                          const next = { ...prev };
                          if (value) next[index] = value;
                          else delete next[index];
                          return next;
                        });
                        resetResolution();
                      }}
                    >
                      <option value="">— Don&apos;t import —</option>
                      {fields.map((field) => (
                        <option key={field.key} value={field.key}>
                          {field.label}
                          {field.required ? " *" : ""}
                        </option>
                      ))}
                    </Select>
                  </div>
                ))}
              </div>
            </div>
          </Panel>
        )}

        {!summary && session && (
          <Panel>
            <div style={{ display: "grid", gap: "0.9rem" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>
                3 · Resolve matches
              </h2>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                Your file&apos;s dealers, brands, categories, tags and locations
                are matched against what you already have. Spelling differences
                match automatically and remembered answers are pre-filled —
                every one is listed, and you can change any of them. Anything
                that merely <em>looks similar</em> asks first: similar is not
                the same (Mac Tools is not Matco Tools), and the importer never
                merges on a guess. Answers are remembered for next time — see{" "}
                <Link to="/settings/import-matching">
                  Settings → Import matching
                </Link>
                .
              </p>
              {!plan && (
                <div>
                  <Button
                    onClick={handleResolve}
                    loading={busy === "resolve"}
                    disabled={!!duplicateField || !nameMapped}
                  >
                    Review matches
                  </Button>
                </div>
              )}
              {plan && plan.entries.length === 0 && (
                <p style={{ margin: 0 }}>
                  Nothing to match — none of the matched columns are in this
                  import.
                </p>
              )}
              {plan &&
                plan.entries.some(
                  (entry) =>
                    entry.status === "ask" &&
                    entry.candidates.length === 0 &&
                    !decisions[entry.field]?.[entry.raw],
                ) && (
                  <div>
                    <Button variant="secondary" onClick={acceptAllNewValues}>
                      Add all brand-new values as-is
                    </Button>
                  </div>
                )}
              {plan && (
                <div style={{ display: "grid", gap: "0.7rem" }}>
                  {[...plan.entries]
                    .sort(
                      (a, b) =>
                        (a.status === "ask" ? 0 : 1) -
                        (b.status === "ask" ? 0 : 1),
                    )
                    .map((entry) => (
                      <ResolveEntryCard
                        key={`${entry.field}:${entry.raw}`}
                        entry={entry}
                        options={plan.options[entry.field] ?? []}
                        decision={decisions[entry.field]?.[entry.raw]}
                        onDecide={(decision) =>
                          handleDecide(entry.field, entry.raw, decision)
                        }
                      />
                    ))}
                </div>
              )}
              {plan && plan.entries.length > 0 && (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  {unanswered > 0
                    ? `${unanswered} value${unanswered === 1 ? "" : "s"} still need${unanswered === 1 ? "s" : ""} your answer before the check can run.`
                    : "Every value is settled — the check below can run."}
                </p>
              )}
            </div>
          </Panel>
        )}

        {!summary && session && (
          <Panel>
            <div style={{ display: "grid", gap: "0.9rem" }}>
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>4 · Check, then import</h2>
              <Checkbox
                label="Skip duplicates (same name + serial number as an item already in the vault)"
                checked={skipDuplicates}
                onChange={(e) => {
                  setSkipDuplicates(e.target.checked);
                  setDryRun(null);
                }}
              />
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <Button
                  variant="secondary"
                  onClick={handleDryRun}
                  loading={busy === "dry"}
                  disabled={!!duplicateField || !nameMapped || !plan || unanswered > 0}
                >
                  Run the check
                </Button>
                <Button
                  onClick={handleConfirm}
                  loading={busy === "confirm"}
                  disabled={!dryRun || dryRun.importable === 0}
                >
                  {dryRun
                    ? `Import ${dryRun.importable} item${dryRun.importable === 1 ? "" : "s"}`
                    : "Import"}
                </Button>
                <Button variant="ghost" onClick={handleStartOver}>
                  Start over
                </Button>
              </div>
              {!dryRun && (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  {!plan
                    ? "Review the matches in step 3 first — then the check reads every row, problems are flagged before anything is written, and the import button unlocks once it runs."
                    : unanswered > 0
                      ? "Answer the remaining match questions in step 3 — the check can't run on a guess."
                      : "The check reads every row first — problems are flagged before anything is written, and the import button unlocks once it runs."}
                </p>
              )}
              {busy === "dry" && <Spinner />}
              {dryRun && (
                <>
                  <p style={{ margin: 0 }}>
                    <strong>{dryRun.counts.ok ?? 0}</strong> ready
                    {` · `}
                    <strong>{dryRun.counts.warning ?? 0}</strong> with warnings
                    {` · `}
                    <strong>{dryRun.counts.error ?? 0}</strong> can&apos;t import
                    {` · `}
                    <strong>{dryRun.counts.blank ?? 0}</strong> blank
                    {` · `}
                    <strong>{dryRun.counts.duplicates ?? 0}</strong> duplicates
                  </p>
                  {dryRun.mappings.length > 0 && (
                    <div style={{ display: "grid", gap: "0.3rem" }}>
                      <strong>Values matched</strong>
                      <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                        {dryRun.mappings.map((mapping) => (
                          <li key={`${mapping.field}:${mapping.raw}`}>
                            &ldquo;{mapping.raw}&rdquo; →{" "}
                            {appliedOutcome(mapping)} · {mapping.rows} row
                            {mapping.rows === 1 ? "" : "s"} ·{" "}
                            {appliedSourceLabel(mapping.source)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {dryRun.cap.enforcement && dryRun.cap.would_exceed > 0 && (
                    <Alert tone="warning" title="Plan limit">
                      Your plan covers {dryRun.cap.limit} items and {dryRun.cap.current_count}{" "}
                      are in the vault, so {dryRun.cap.remaining} more fit.{" "}
                      {dryRun.cap.would_exceed} row
                      {dryRun.cap.would_exceed === 1 ? "" : "s"} would be skipped —
                      they&apos;re listed in the summary after import.
                    </Alert>
                  )}
                  <div style={{ maxHeight: "26rem", overflowY: "auto" }}>
                    <table className="tv-table">
                      <thead>
                        <tr>
                          <th>Row</th>
                          <th>Status</th>
                          <th>Item</th>
                          <th>Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dryRun.rows.map((row) => (
                          <tr key={row.row}>
                            <td>{row.row}</td>
                            <td>
                              <Badge tone={STATUS_TONES[row.status]}>{row.status}</Badge>
                            </td>
                            <td>
                              {row.name}
                              {row.preview && (
                                <>
                                  {row.preview.models.length > 0 && (
                                    <div className="tv-import-preview">
                                      Models: {row.preview.models.join(" · ")}
                                    </div>
                                  )}
                                  {row.preview.serials.length > 0 && (
                                    <div className="tv-import-preview">
                                      Serials: {row.preview.serials.join(" · ")}
                                    </div>
                                  )}
                                  {row.preview.is_set && (
                                    <div className="tv-import-preview">
                                      Set
                                      {row.preview.set_serials.length > 0 &&
                                        ` · piece serials: ${row.preview.set_serials.join(" · ")}`}
                                    </div>
                                  )}
                                </>
                              )}
                            </td>
                            <td>{row.messages.join(" ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </Panel>
        )}
      </div>
    </RequireAuth>
  );
}
