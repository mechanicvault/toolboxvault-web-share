import { useMemo, useRef, useState } from "react";
import "./claims.css";
import { useT } from "../../i18n/LocaleContext";
import {
  AttachmentViewer,
  Badge,
  Button,
  DatePicker,
  FormField,
  Panel,
  Select,
  TextArea,
  TextInput,
  useToast,
  type ViewableAttachment,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useAuth } from "../core";
import { todayLocalIso } from "../../lib/format";
import {
  attachmentFileError,
  typesForKind,
  type AttachmentKind,
} from "../inventory/components/photoTransfer";
import { fileIconKind } from "../inventory/components/AttachmentList";
import { FileTypeArt } from "../../components/FileTypeArt";
import {
  claimsApi,
  type ClaimsSectionApi,
} from "./api";
import {
  CHANNEL_LABELS,
  STATUS_TONES,
  deadlineState,
  fullDate,
} from "./format";
import type {
  Claim,
  ClaimHeaderInput,
  ClaimStatus,
  ClaimTargets,
  CommChannel,
  EvidenceKind,
  IncidentType,
} from "./types";

/** Shared bits of the claims surfaces: the status badge, the
 *  computed todo checklist, the incident form, and the evidence
 *  section (references + uploads + the in-place viewer). Used by
 *  the list, the create wizard, and the claim detail page so a
 *  claim reads the same everywhere it appears. */

export function StatusBadge({ status }: { status: ClaimStatus }) {
  const t = useT();
  return (
    <Badge tone={STATUS_TONES[status]} dot>
      {t(`claims.status.${status}` as never)}
    </Badge>
  );
}

const inputRow: React.CSSProperties = {
  display: "grid",
  gap: "0.9rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))",
};

/** The incident/header form. `incidentLocked` freezes the incident
 *  facts (type + date) once a claim is filed — the backend enforces
 *  the same rule; `readOnly` freezes everything (closed claims). */
export function IncidentForm({
  value,
  onChange,
  incidentLocked,
  readOnly,
}: {
  value: ClaimHeaderInput;
  onChange: (next: ClaimHeaderInput) => void;
  incidentLocked: boolean;
  readOnly: boolean;
}) {
  const t = useT();
  const set = (patch: Partial<ClaimHeaderInput>) =>
    onChange({ ...value, ...patch });
  const dateOrNull = (v: string) => (v ? v : null);
  return (
    <div style={{ display: "grid", gap: "0.9rem" }}>
      <div style={inputRow}>
        <FormField label={t("claims.form.insurer")}>
          <TextInput
            value={value.insurer_name ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ insurer_name: e.target.value })}
            placeholder={t("claims.form.insurerPlaceholder")}
          />
        </FormField>
        <FormField label={t("claims.form.policyNumber")}>
          <TextInput
            value={value.policy_number ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ policy_number: e.target.value })}
          />
        </FormField>
      </div>
      <div style={inputRow}>
        <FormField
          label={t("claims.form.agentName")}
          hint={t("claims.form.agentHint")}
        >
          <TextInput
            value={value.agent_name ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ agent_name: e.target.value })}
          />
        </FormField>
        <FormField label={t("claims.form.agentPhone")}>
          <TextInput
            value={value.agent_phone ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ agent_phone: e.target.value })}
          />
        </FormField>
        <FormField label={t("claims.form.agentEmail")}>
          <TextInput
            type="email"
            value={value.agent_email ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ agent_email: e.target.value })}
          />
        </FormField>
      </div>
      <div style={inputRow}>
        <FormField
          label={t("claims.form.incidentType")}
          hint={incidentLocked ? t("claims.form.lockedHint") : undefined}
        >
          <Select
            value={value.incident_type ?? "other"}
            disabled={readOnly || incidentLocked}
            onChange={(e) =>
              set({ incident_type: e.target.value as IncidentType })
            }
          >
            <option value="theft">{t("claims.incident.theft")}</option>
            <option value="loss">{t("claims.incident.loss")}</option>
            <option value="damage">{t("claims.incident.damage")}</option>
            <option value="fire">{t("claims.incident.fire")}</option>
            <option value="other">{t("claims.incident.other")}</option>
          </Select>
        </FormField>
        <FormField
          label={t("claims.form.incidentDate")}
          hint={incidentLocked ? t("claims.form.lockedHint") : undefined}
        >
          <DatePicker
            value={value.incident_date ?? ""}
            disabled={readOnly || incidentLocked}
            onChange={(v) => set({ incident_date: dateOrNull(v) })}
            clearable
          />
        </FormField>
      </div>
      <FormField label={t("claims.form.description")}>
        <TextArea
          value={value.description ?? ""}
          disabled={readOnly}
          rows={3}
          onChange={(e) => set({ description: e.target.value })}
          placeholder={t("claims.form.descriptionPlaceholder")}
        />
      </FormField>
      <div style={inputRow}>
        <FormField
          label={t("claims.form.policeNumber")}
          hint={
            value.incident_type === "theft"
              ? t("claims.form.policeHint")
              : undefined
          }
        >
          <TextInput
            value={value.police_report_number ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ police_report_number: e.target.value })}
          />
        </FormField>
        <FormField label={t("claims.form.policeDept")}>
          <TextInput
            value={value.police_department ?? ""}
            disabled={readOnly}
            onChange={(e) => set({ police_department: e.target.value })}
          />
        </FormField>
        <FormField label={t("claims.form.reportDate")}>
          <DatePicker
            value={value.police_report_date ?? ""}
            disabled={readOnly}
            onChange={(v) =>
              set({ police_report_date: dateOrNull(v) })
            }
            clearable
          />
        </FormField>
      </div>
      <div style={inputRow}>
        <FormField label={t("claims.form.polDue")}>
          <DatePicker
            value={value.proof_of_loss_due ?? ""}
            disabled={readOnly}
            onChange={(v) =>
              set({ proof_of_loss_due: dateOrNull(v) })
            }
            clearable
          />
        </FormField>
        <FormField
          label={t("claims.form.depreciation")}
          hint={t("claims.form.depreciationHint")}
        >
          <DatePicker
            value={value.depreciation_deadline ?? ""}
            disabled={readOnly}
            onChange={(v) =>
              set({ depreciation_deadline: dateOrNull(v) })
            }
            clearable
          />
        </FormField>
      </div>
    </div>
  );
}

/** The claim form state built from a claim view. */
export function headerInputFrom(claim: Claim): ClaimHeaderInput {
  return {
    insurer_name: claim.insurer_name,
    policy_number: claim.policy_number,
    manufacturer_case_number: claim.manufacturer_case_number,
    agent_name: claim.agent_name,
    agent_phone: claim.agent_phone,
    agent_email: claim.agent_email,
    incident_type: claim.incident_type,
    incident_date: claim.incident_date,
    description: claim.description,
    police_report_number: claim.police_report_number,
    police_department: claim.police_department,
    police_report_date: claim.police_report_date,
    proof_of_loss_due: claim.proof_of_loss_due,
    depreciation_deadline: claim.depreciation_deadline,
  };
}

/** The computed todo checklist, with the mark-proof-of-loss-sent
 *  action inline when it's the open item. */
const CHECKLIST_KEYS: Record<string, string> = {
  "warranty:items": "claims.checklist.wItems",
  "warranty:dealer": "claims.checklist.wDealer",
  "warranty:reported": "claims.checklist.wReported",
  "warranty:reported_agent": "claims.checklist.wReportedAgent",
  "warranty:resolved": "claims.checklist.wResolved",
  "insurance:incident": "claims.checklist.iIncident",
  "insurance:items": "claims.checklist.iItems",
  "insurance:evidence": "claims.checklist.iEvidence",
  "insurance:police_report": "claims.checklist.iPolice",
  "insurance:proof_of_loss": "claims.checklist.iProof",
};

export function ChecklistPanel({
  claim,
  onClaimChange,
  claimApi = claimsApi,
}: {
  claim: Claim;
  onClaimChange: (claim: Claim) => void;
  /** The section's API (claims separation, 2026-11-05): the
   *  Disaster Claims detail page passes its own section API so
   *  the mark-sent action never crosses sections. */
  claimApi?: ClaimsSectionApi;
}) {
  const t = useT();
  const { toast } = useToast();
  const [sentDate, setSentDate] = useState(() => todayLocalIso());
  const [busy, setBusy] = useState(false);
  // Separation is absolute (sweep C3, finishing 05-F3): the
  // proof-of-loss / depreciation blocks under the checklist are
  // INSURANCE machinery. A warranty claim's statuses never enter
  // the mark-sent set and it carries no such deadlines, so they
  // never rendered — gate them on kind anyway, so the shared
  // panel can never speak insurance on a repair claim.
  const isInsurance = claim.kind !== "warranty_repair";
  const canMarkSent =
    isInsurance && ["filed", "in_review", "approved"].includes(claim.status);
  const polState = deadlineState(
    claim.proof_of_loss_due,
    claim.proof_of_loss_sent_at !== null,
  );

  async function markSent() {
    setBusy(true);
    try {
      onClaimChange(await claimApi.markProofOfLossSent(claim.id, sentDate || null));
      toast(t("claims.checklist.sentToast"), {
        tone: "success",
        title: claim.claim_number,
      });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.comms.couldntSaveThat"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  const firstOpenKey = claim.checklist.find((item) => !item.done)?.key;
  return (
    <Panel
      className="tv-claim-nextstep"
      title={t("claims.checklist.title")}
      actions={
        <Badge tone={claim.checklist_done === claim.checklist_total ? "success" : "neutral"}>
          {t("claims.checklist.progress")
            .replace("{done}", String(claim.checklist_done))
            .replace("{total}", String(claim.checklist_total))}
        </Badge>
      }
    >
      <div style={{ display: "grid", gap: "0.55rem" }}>
        {claim.checklist.map((item) => (
          <div
            key={item.key}
            className={`tv-tl-item${item.done ? " tv-tl-item--done" : ""}${item.key === firstOpenKey ? " tv-tl-item--current" : ""}`}
            style={{ display: "flex", gap: "0.6rem", alignItems: "baseline" }}
          >
            <span className="tv-tl-dot" aria-hidden style={{ color: item.done ? "var(--accent)" : "var(--text-muted)" }}>
              {item.done ? "✓" : "○"}
            </span>
            <span
              style={{
                color: item.done ? "var(--text-muted)" : "var(--text)",
                textDecoration: item.done ? "line-through" : "none",
              }}
            >
              {(() => {
                const key =
                  CHECKLIST_KEYS[
                    `${claim.kind === "warranty_repair" ? "warranty" : "insurance"}:${item.key}`
                  ];
                return key ? t(key as never) : item.label;
              })()}
            </span>
          </div>
        ))}
        {isInsurance && claim.proof_of_loss_due && (
          <p style={{ margin: "0.35rem 0 0", color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {t("claims.checklist.polDueLine").replace(
              "{date}",
              fullDate(claim.proof_of_loss_due),
            )}
            {claim.proof_of_loss_sent_at
              ? t("claims.checklist.polSentSuffix").replace(
                  "{date}",
                  fullDate(claim.proof_of_loss_sent_at),
                )
              : polState === "overdue"
                ? t("claims.checklist.polOverdueSuffix")
                : polState === "soon"
                  ? t("claims.checklist.polSoonSuffix")
                  : ""}
            .
          </p>
        )}
        {isInsurance && claim.depreciation_deadline && (
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {t("claims.checklist.depreciationLine").replace(
              "{date}",
              fullDate(claim.depreciation_deadline),
            )}
          </p>
        )}
        {canMarkSent && !claim.proof_of_loss_sent_at && (
          <div
            style={{
              display: "flex",
              gap: "0.6rem",
              alignItems: "end",
              flexWrap: "wrap",
              marginTop: "0.4rem",
            }}
          >
            <FormField label={t("claims.checklist.sentOnLabel")}>
              <DatePicker
                value={sentDate}
                onChange={setSentDate}
                clearable
              />
            </FormField>
            <Button size="sm" variant="secondary" onClick={markSent} disabled={busy}>
              {t("claims.checklist.markSent")}
            </Button>
          </div>
        )}
      </div>
    </Panel>
  );
}

interface ReferenceOption {
  itemKind: "tool" | "battery" | "piece";
  itemId: string;
  itemName: string;
  key: string;
  filename: string;
  kind: EvidenceKind;
}

/** Every attachment the claim's lines can offer as evidence
 *  references: line targets' own files, plus a set line's pieces'
 *  files (their receipts are evidence for the set). */
export function referenceOptions(
  claim: Claim,
  targets: ClaimTargets | null,
): ReferenceOption[] {
  if (!targets) return [];
  const byId = new Map<string, (typeof targets.tools)[number]>();
  for (const t of targets.tools) byId.set(t.id, t);
  for (const b of targets.batteries) byId.set(b.id, b);
  const options: ReferenceOption[] = [];
  const push = (
    itemKind: ReferenceOption["itemKind"],
    itemId: string,
    itemName: string,
    attachments: { key: string; filename: string; kind: EvidenceKind }[],
  ) => {
    for (const a of attachments)
      options.push({
        itemKind,
        itemId,
        itemName,
        key: a.key,
        filename: a.filename,
        kind: a.kind,
      });
  };
  for (const line of claim.lines) {
    if (line.target_kind === "piece") {
      for (const t of targets.tools) {
        const piece = t.pieces.find((p) => p.id === line.target_id);
        if (piece) push("piece", piece.id, piece.name, piece.attachments);
      }
      continue;
    }
    const target = byId.get(line.target_id);
    if (!target) continue;
    push(
      line.target_kind === "battery" ? "battery" : "tool",
      target.id,
      target.name,
      target.attachments,
    );
    if (line.target_kind === "set") {
      for (const piece of target.pieces)
        push("piece", piece.id, `${target.name} — ${piece.name}`, piece.attachments);
    }
  }
  return options;
}

/** The documents standard's below-the-tile delete (owner,
 *  2026-11-05): a plain accent "Delete file" link under the
 *  tile; tapping it swaps in the confirm row in the same spot.
 *  Same treatment as the item documents' control — but an
 *  evidence row is not an item attachment, so the delete rides
 *  the section's own remove callback (the claims API path). */
function EvidenceDeleteLink({
  busy,
  onDelete,
}: {
  busy: boolean;
  onDelete: () => void;
}) {
  const t = useT();
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return (
      <span className="tv-doc-del">
        <button
          type="button"
          className="tv-doc-del-link"
          onClick={() => setConfirming(true)}
        >
          {t("claims.evidence.deleteFile")}
        </button>
      </span>
    );
  }
  return (
    <span className="tv-doc-del">
      <span className="tv-doc-del-confirm">
        {t("claims.evidence.deleteFileConfirm")}
      </span>
      <Button size="sm" variant="danger" disabled={busy} onClick={onDelete}>
        {t("common.delete")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
        {t("common.cancel")}
      </Button>
    </span>
  );
}

/** The evidence section: what's attached (viewable in place),
 *  reference-adding from the targeted items' files, and
 *  claim-specific uploads. `editable` is false on closed claims.
 *  `canRemove` splits off for a warranty claim's dealer viewer:
 *  both parties ADD files, but removing one is the owner's call
 *  (the backend enforces the same split).
 *
 *  `layout="tiles"` (claims overhaul, 2026-11-06, owner order
 *  #7): the evidence renders as icon TILES — the shared
 *  FileTypeArt artwork in the documents tiles treatment (uniform
 *  cells, name below, click opens the viewer, "Delete file" link
 *  below the tile). The warranty claim page passes it; the
 *  default list rendering is the Disaster Claims page's, whose
 *  surfaces this lane does not touch. */
export function EvidenceSection({
  claim,
  targets,
  editable,
  canRemove,
  onClaimChange,
  claimApi = claimsApi,
  layout,
}: {
  claim: Claim;
  targets: ClaimTargets | null;
  editable: boolean;
  canRemove?: boolean;
  onClaimChange: (claim: Claim) => void;
  /** The section's API (claims separation, 2026-11-05). */
  claimApi?: ClaimsSectionApi;
  layout?: "list" | "tiles";
}) {
  const t = useT();
  const { toast } = useToast();
  const [viewer, setViewer] = useState<ViewableAttachment | null>(null);
  const [uploadKind, setUploadKind] = useState<EvidenceKind>("document");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const options = useMemo(
    () => referenceOptions(claim, targets),
    [claim, targets],
  );
  const referencedKeys = useMemo(
    () =>
      new Set(
        claim.evidence
          .filter((e) => e.source === "reference")
          .map((e) => e.attachment_key),
      ),
    [claim.evidence],
  );

  async function refresh() {
    onClaimChange(await claimApi.getClaim(claim.id));
  }

  async function addReference(option: ReferenceOption) {
    setBusyKey(option.key);
    try {
      await claimApi.addEvidenceReference(claim.id, {
        item_kind: option.itemKind,
        item_id: option.itemId,
        attachment_key: option.key,
      });
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.evidence.addError"), {
        tone: "danger",
        title: t("claims.detail.evidenceTitle"),
      });
    } finally {
      setBusyKey(null);
    }
  }

  async function remove(evidenceId: string) {
    setBusyKey(evidenceId);
    try {
      await claimApi.removeEvidence(claim.id, evidenceId);
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.evidence.removeError"), {
        tone: "danger",
        title: t("claims.detail.evidenceTitle"),
      });
    } finally {
      setBusyKey(null);
    }
  }

  async function onFilePicked(file: File | undefined) {
    if (!file) return;
    const problem = attachmentFileError(uploadKind as AttachmentKind, file);
    if (problem) {
      toast(problem, { tone: "danger", title: t("claims.detail.evidenceTitle") });
      return;
    }
    setBusyKey("upload");
    try {
      await claimApi.uploadClaimEvidence(claim.id, uploadKind, file);
      await refresh();
      toast(t("claims.evidence.addedToast").replace("{name}", file.name), {
        tone: "success",
        title: t("claims.detail.evidenceTitle"),
      });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.evidence.uploadFailed"), {
        tone: "danger",
        title: t("claims.detail.evidenceTitle"),
      });
    } finally {
      setBusyKey(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div style={{ display: "grid", gap: "0.8rem" }}>
      {claim.evidence.length === 0 && (
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          {t("claims.evidence.empty")}
        </p>
      )}
      {layout === "tiles" && claim.evidence.length > 0 && (
        <div className="tv-doc-tiles">
          {claim.evidence.map((row) => (
            <div key={row.id} className="tv-doc-tile-cell">
              <div className="tv-doc-tile tv-hoverable">
                <button
                  type="button"
                  className="tv-doc-tile-btn"
                  title={row.filename}
                  disabled={!row.available || !row.url}
                  onClick={() =>
                    row.url &&
                    setViewer({
                      key: row.attachment_key,
                      filename: row.filename,
                      kind: row.kind,
                      content_type: row.content_type,
                      size_bytes: row.size_bytes,
                      url: row.url,
                    })
                  }
                >
                  <span className="tv-doc-tile-art" aria-hidden="true">
                    <FileTypeArt
                      kind={fileIconKind(row.content_type, row.filename)}
                    />
                  </span>
                  <span className="tv-doc-tile-name">{row.filename}</span>
                  <span className="tv-doc-tile-meta">
                    {t(
                      (row.kind === "photo"
                        ? "claims.evidence.kindPhoto"
                        : row.kind === "receipt"
                          ? "claims.evidence.kindReceipt"
                          : "claims.evidence.kindDocument") as never,
                    )}
                    {" · "}
                    {row.source === "reference"
                      ? t("claims.evidence.fromItem")
                      : t("claims.evidence.uploaded")}
                    {!row.available && ` · ${t("claims.evidence.goneShort")}`}
                  </span>
                </button>
              </div>
              {(canRemove ?? editable) && (
                <div className="tv-doc-tile-del">
                  <EvidenceDeleteLink
                    busy={busyKey === row.id}
                    onDelete={() => void remove(row.id)}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {layout !== "tiles" &&
        claim.evidence.map((row) => (
        <div
          key={row.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "1rem",
            alignItems: "center",
            flexWrap: "wrap",
            borderTop: "1px solid var(--edge)",
            paddingTop: "0.6rem",
          }}
        >
          <div style={{ display: "grid", gap: "0.15rem" }}>
            <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
              <strong>{row.filename}</strong>
              <Badge tone="neutral">
                {t(
                  (row.kind === "photo"
                    ? "claims.evidence.kindPhoto"
                    : row.kind === "receipt"
                      ? "claims.evidence.kindReceipt"
                      : "claims.evidence.kindDocument") as never,
                )}
              </Badge>
              <Badge tone="neutral">
                {row.source === "reference"
                  ? t("claims.evidence.fromItem")
                  : t("claims.evidence.uploaded")}
              </Badge>
            </span>
            <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
              {row.available
                ? t("claims.evidence.ready")
                : t("claims.evidence.gone")}
            </span>
          </div>
          <span style={{ display: "inline-flex", gap: "0.5rem" }}>
            {row.available && row.url && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setViewer({
                    key: row.attachment_key,
                    filename: row.filename,
                    kind: row.kind,
                    content_type: row.content_type,
                    size_bytes: row.size_bytes,
                    url: row.url as string,
                  })
                }
              >
                {t("claims.evidence.view")}
              </Button>
            )}
            {(canRemove ?? editable) && (
              <button
                type="button"
                className="tv-list-remove-btn"
                aria-label={`${t("claims.evidence.remove")}: ${row.filename}`}
                title={t("claims.evidence.remove")}
                disabled={busyKey === row.id}
                onClick={() => remove(row.id)}
              >
                {"−"}
              </button>
            )}
          </span>
        </div>
      ))}

      {editable && options.length > 0 && (
        <div style={{ display: "grid", gap: "0.4rem" }}>
          <strong style={{ fontSize: "0.95rem" }}>{t("claims.evidence.fromItems")}</strong>
          {options.map((option) => {
            const added = referencedKeys.has(option.key);
            return (
              <div
                key={option.key}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "1rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <span style={{ color: "var(--text-muted)", fontSize: "0.92rem" }}>
                  {option.itemName} — {option.filename}
                  <Badge tone="neutral">
                    {t(
                      (option.kind === "photo"
                        ? "claims.evidence.kindPhoto"
                        : option.kind === "receipt"
                          ? "claims.evidence.kindReceipt"
                          : "claims.evidence.kindDocument") as never,
                    )}
                  </Badge>
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={added || busyKey === option.key}
                  onClick={() => addReference(option)}
                >
                  {added ? t("claims.evidence.attached") : t("claims.evidence.attach")}
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {editable && (
        <div
          style={{
            display: "flex",
            gap: "0.6rem",
            alignItems: "end",
            flexWrap: "wrap",
            borderTop: "1px solid var(--edge)",
            paddingTop: "0.7rem",
          }}
        >
          <FormField label={t("claims.evidence.uploadLabel")}>
            <Select
              value={uploadKind}
              onChange={(e) => setUploadKind(e.target.value as EvidenceKind)}
            >
              <option value="document">{t("claims.evidence.kindDocument")}</option>
              <option value="photo">{t("claims.evidence.kindPhoto")}</option>
              <option value="receipt">{t("claims.evidence.kindReceipt")}</option>
            </Select>
          </FormField>
          <input
            ref={fileRef}
            type="file"
            accept={typesForKind(uploadKind as AttachmentKind).join(",")}
            style={{ display: "none" }}
            onChange={(e) => onFilePicked(e.target.files?.[0])}
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={busyKey === "upload"}
            onClick={() => fileRef.current?.click()}
          >
            {busyKey === "upload" ? t("claims.evidence.uploading") : t("claims.evidence.chooseFile")}
          </Button>
          <span style={{ color: "var(--text-muted)", fontSize: "0.88rem" }}>
            {t("claims.evidence.limitsNote")}
          </span>
        </div>
      )}

      <AttachmentViewer
        attachment={viewer}
        onClose={() => setViewer(null)}
      />
    </div>
  );
}

export function CommsPanel({
  claim,
  onClaimChange,
  claimApi = claimsApi,
}: {
  claim: Claim;
  onClaimChange: (claim: Claim) => void;
  /** The section's API (claims separation, 2026-11-05): the
   *  Disaster Claims detail page passes its own section API. */
  claimApi?: ClaimsSectionApi;
}) {
  const t = useT();
  const { toast } = useToast();
  const { user } = useAuth();
  // Separation (sweep B5): the log's own words follow the
  // claim's kind — a warranty claim talks to the dealer about
  // the repair; "adjuster / adjustment" belongs to disaster
  // claims only.
  const isWarranty = claim.kind === "warranty_repair";
  // Closed is final for the log: a warranty claim's closing is
  // the closed_at layer (overhaul, 2026-11-06), an insurance
  // claim's is its status — either stamp ends editing.
  const editable = claim.closed_at === null && claim.status !== "closed";
  // Two-party log (warranty claims): an entry can be edited or
  // deleted by its author, or by the claim's owner — the same
  // rule the backend keeps. Legacy rows (no author) are the
  // owner's.
  const canEditEntry = (entry: Claim["communications"][number]) =>
    claim.viewer_role === "owner" ||
    (entry.author_id !== null && entry.author_id === user?.id);
  const [channel, setChannel] = useState<CommChannel>("phone");
  const [contact, setContact] = useState("");
  // DATE ONLY (owner order, 2026-11-05 #9): the log takes the
  // day, never a time — the shared calendar picker, defaulting
  // to today like every date field on the site.
  const [when, setWhen] = useState(() => todayLocalIso());
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editSummary, setEditSummary] = useState("");
  const [editContact, setEditContact] = useState("");

  async function refresh() {
    onClaimChange(await claimApi.getClaim(claim.id));
  }

  async function add() {
    setBusy(true);
    try {
      await claimApi.addCommunication(claim.id, {
        channel,
        contact,
        summary,
        occurred_at: when || null,
      });
      setContact("");
      setSummary("");
      setWhen(todayLocalIso());
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.comms.couldntLog"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit(entryId: string) {
    setBusy(true);
    try {
      await claimApi.updateCommunication(claim.id, entryId, {
        contact: editContact,
        summary: editSummary,
      });
      setEditingId(null);
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.comms.couldntSaveThat"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function remove(entryId: string) {
    setBusy(true);
    try {
      await claimApi.deleteCommunication(claim.id, entryId);
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.comms.couldntDeleteThat"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={t("claims.comms.title")}>
      <div style={{ display: "grid", gap: "0.8rem" }}>
        {claim.communications.length === 0 && (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            {t(isWarranty ? "claims.comms.emptyWarranty" : "claims.comms.empty")}
          </p>
        )}
        {claim.communications.map((entry) => (
          <div
            key={entry.id}
            style={{ borderTop: "1px solid var(--edge)", paddingTop: "0.6rem", display: "grid", gap: "0.3rem" }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
              <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                <Badge tone="neutral">
                  {t(`claims.channel.${entry.channel}` as never)}
                </Badge>
                <strong>{entry.contact || "—"}</strong>
                {entry.author_name && (
                  <span className="tv-claim-mut-sm">
                    {t(
                      entry.author_role === "dealer"
                        ? "claims.comms.byDealer"
                        : "claims.comms.by",
                    ).replace("{name}", entry.author_name)}
                  </span>
                )}
                <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                  {fullDate(entry.occurred_at)}
                </span>
              </span>
              {editable && editingId !== entry.id && canEditEntry(entry) && (
                <span style={{ display: "inline-flex", gap: "0.4rem" }}>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setEditingId(entry.id);
                      setEditSummary(entry.summary);
                      setEditContact(entry.contact);
                    }}
                  >
                    {t("claims.comms.edit")}
                  </Button>
                  <button
                    type="button"
                    className="tv-list-remove-btn"
                    aria-label={t("claims.comms.delete")}
                    title={t("claims.comms.delete")}
                    disabled={busy}
                    onClick={() => remove(entry.id)}
                  >
                    {"−"}
                  </button>
                </span>
              )}
            </div>
            {editingId === entry.id ? (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                <FormField label={t("claims.comms.withWhom")}>
                  <TextInput
                    value={editContact}
                    onChange={(e) => setEditContact(e.target.value)}
                  />
                </FormField>
                <FormField label={t("claims.comms.whatSaid")}>
                  <TextArea
                    rows={3}
                    value={editSummary}
                    onChange={(e) => setEditSummary(e.target.value)}
                  />
                </FormField>
                <span style={{ display: "inline-flex", gap: "0.5rem" }}>
                  <Button size="sm" variant="secondary" disabled={busy} onClick={() => saveEdit(entry.id)}>
                    {t("claims.comms.save")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                    {t("common.cancel")}
                  </Button>
                </span>
              </div>
            ) : (
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{entry.summary}</p>
            )}
          </div>
        ))}
        {editable && (
          <div
            style={{
              display: "grid",
              gap: "0.6rem",
              borderTop: "1px solid var(--edge)",
              paddingTop: "0.8rem",
            }}
          >
            <div
              style={{
                display: "grid",
                gap: "0.9rem",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))",
              }}
            >
              <FormField label={t("claims.comms.channel")}>
                <Select
                  value={channel}
                  onChange={(e) => setChannel(e.target.value as CommChannel)}
                >
                  {(
                    Object.keys(CHANNEL_LABELS) as CommChannel[]
                  ).map((key) => (
                    <option key={key} value={key}>
                      {t(`claims.channel.${key}` as never)}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label={t("claims.comms.withWhom")}>
                <TextInput
                  value={contact}
                  onChange={(e) => setContact(e.target.value)}
                  placeholder={t(
                    isWarranty
                      ? "claims.comms.contactPlaceholderWarranty"
                      : "claims.comms.contactPlaceholder",
                  )}
                />
              </FormField>
              <FormField label={t("claims.comms.when")}>
                <DatePicker value={when} onChange={setWhen} />
              </FormField>
            </div>
            <FormField label={t("claims.comms.whatSaid")}>
              <TextArea
                rows={2}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
              />
            </FormField>
            <div>
              <Button size="sm" variant="secondary" disabled={busy || !summary.trim()} onClick={add}>
                {t("claims.comms.logEntry")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}
