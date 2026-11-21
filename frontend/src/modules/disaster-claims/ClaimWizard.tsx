import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  FormField,
  Modal,
  Panel,
  ProgressBar,
  Select,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { disasterClaimsApi } from "../claims/api";
import {
  ChecklistPanel,
  EvidenceSection,
  IncidentForm,
  headerInputFrom,
} from "../claims/components";
import { money } from "../claims/format";
import type {
  Claim,
  ClaimHeaderInput,
  ClaimTarget,
  ClaimTargets,
  TargetKind,
  ValueBasis,
} from "../claims/types";

/**
 * The guided DISASTER claim flow (blueprint §15): Target →
 * Incident → Evidence → Review, with a progress bar over the
 * steps. The wizard opens a real DRAFT claim first, so every
 * step works on the claim itself — closing the wizard mid-way
 * simply leaves a draft in the list, never lost work. (Claims
 * separation, 2026-11-05: this wizard lives in the Disaster
 * Claims section and files through its API only.)
 */

/* Step labels by dictionary key (sweep B5: the wizard rendered
 * hardcoded English under ES — every string in this file now
 * resolves through the dictionary). */
const STEP_KEYS = [
  "claims.wizard.stepTarget",
  "claims.wizard.stepIncident",
  "claims.wizard.stepEvidence",
  "claims.wizard.stepReview",
] as const;

/** Pre-draft stand-in (F2-05): before the first real input there
 *  is no server claim; the picker renders against this empty-lines
 *  shape and TargetPicker's ensureClaim callback mints the real
 *  draft the moment the first item is actually added. */
const NO_CLAIM = {
  id: "",
  claim_number: "",
  lines: [],
  evidence: [],
  total_amount: "0",
  owner_currency: "",
} as unknown as Claim;

interface DraftLineState {
  basis: ValueBasis;
  amount: string;
  includeAddons: boolean;
}

const DEFAULT_LINE: DraftLineState = {
  basis: "purchase",
  amount: "",
  includeAddons: false,
};

function lineKey(kind: string, id: string): string {
  return `${kind}:${id}`;
}

/** The target picker: every asset the owner can claim, each with
 *  its value basis controls; sets expand to their pieces (entered
 *  amounts) and ask the addons question. Shared by the wizard and
 *  the draft claim's "add items" editor. */
export function TargetPicker({
  claim,
  targets,
  onClaimChange,
  ensureClaim,
}: {
  claim: Claim;
  targets: ClaimTargets;
  onClaimChange: (claim: Claim) => void;
  /** F2-05 lazy draft: when the claim does not exist yet (empty
   *  id), the first real Add creates it through this callback and
   *  the line lands on the real claim. Absent on the detail page,
   *  where the claim always exists. */
  ensureClaim?: () => Promise<Claim>;
}) {
  const { toast } = useToast();
  const tt = useT();
  const [drafts, setDrafts] = useState<Record<string, DraftLineState>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [itemQuery, setItemQuery] = useState("");

  const draftFor = (kind: string, id: string): DraftLineState =>
    drafts[lineKey(kind, id)] ?? DEFAULT_LINE;
  const setDraft = (kind: string, id: string, patch: Partial<DraftLineState>) =>
    setDrafts((prev) => ({
      ...prev,
      [lineKey(kind, id)]: { ...draftFor(kind, id), ...patch },
    }));

  async function add(kind: TargetKind, id: string) {
    const draft = draftFor(kind, id);
    setBusyKey(lineKey(kind, id));
    try {
      let owner = claim;
      if (!owner.id && ensureClaim) owner = await ensureClaim();
      await disasterClaimsApi.addClaimLine(owner.id, {
        target_kind: kind,
        target_id: id,
        include_addons: kind === "set" ? draft.includeAddons : undefined,
        value_basis: kind === "piece" ? "entered" : draft.basis,
        amount:
          kind === "piece" || draft.basis === "entered"
            ? draft.amount || null
            : undefined,
      });
      onClaimChange(await disasterClaimsApi.getClaim(owner.id));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : tt("claims.wizard.couldntAdd"), {
        tone: "danger",
        title: tt("disasterClaims.title"),
      });
    } finally {
      setBusyKey(null);
    }
  }

  async function remove(lineId: string, key: string) {
    setBusyKey(key);
    try {
      await disasterClaimsApi.removeClaimLine(claim.id, lineId);
      onClaimChange(await disasterClaimsApi.getClaim(claim.id));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : tt("claims.wizard.couldntRemove"), {
        tone: "danger",
        title: tt("disasterClaims.title"),
      });
    } finally {
      setBusyKey(null);
    }
  }

  function targetRow(target: ClaimTarget) {
    const kind = target.kind as TargetKind;
    const key = lineKey(kind, target.id);
    const draft = draftFor(kind, target.id);
    const line = claim.lines.find(
      (l) => l.target_kind === kind && l.target_id === target.id,
    );
    return (
      <div
        key={key}
        style={{
          borderTop: "1px solid var(--edge)",
          paddingTop: "0.7rem",
          display: "grid",
          gap: "0.5rem",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "1rem",
            flexWrap: "wrap",
            alignItems: "baseline",
          }}
        >
          <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
            <strong>{target.name}</strong>
            {target.kind === "set" && <Badge tone="accent">{tt("claims.wizard.kindSet")}</Badge>}
            {target.kind === "battery" && <Badge tone="neutral">{tt("claims.wizard.kindBattery")}</Badge>}
            <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
              {[target.brand, target.model].filter(Boolean).join(" ")}
              {target.quantity > 1
                ? ` · ${tt("claims.wizard.qty").replace("{count}", String(target.quantity))}`
                : ""}
            </span>
          </span>
          {line ? (
            <span style={{ display: "inline-flex", gap: "0.6rem", alignItems: "center" }}>
              <span>
                {money(line.amount, claim.owner_currency)} · {tt(`claims.basis.${line.value_basis}` as never)}
                {line.target_kind === "set" &&
                  ` · ${tt(line.include_addons ? "claims.wizard.addonsIncluded" : "claims.wizard.addonsNotIncluded")}`}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={busyKey === key}
                onClick={() => remove(line.id, key)}
              >
                {tt("claims.wizard.remove")}
              </Button>
            </span>
          ) : (
            <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "end", flexWrap: "wrap" }}>
              <FormField label={tt("claims.wizard.valueLabel")}>
                <Select
                  value={draft.basis}
                  onChange={(e) =>
                    setDraft(kind, target.id, {
                      basis: e.target.value as ValueBasis,
                    })
                  }
                >
                  <option value="purchase">
                    {tt("claims.wizard.basisPurchase")}{target.purchase_price ? ` (${money(target.purchase_price)}${target.quantity > 1 ? ` ${tt("claims.wizard.each")}` : ""})` : tt("claims.wizard.basisNotRecorded")}
                  </option>
                  <option value="entered">{tt("claims.wizard.enterAmount")}</option>
                </Select>
              </FormField>
              {draft.basis === "entered" && (
                <FormField label={tt("claims.wizard.amountLabel")}>
                  <TextInput
                    inputMode="decimal"
                    placeholder="0.00"
                    value={draft.amount}
                    onChange={(e) =>
                      setDraft(kind, target.id, { amount: e.target.value })
                    }
                  />
                </FormField>
              )}
              <Button
                size="sm"
                disabled={busyKey === key}
                onClick={() => add(kind, target.id)}
              >
                {tt("claims.wizard.add")}
              </Button>
            </span>
          )}
        </div>
        {target.kind === "set" && !line && (
          <Checkbox
            checked={draft.includeAddons}
            onChange={(e) =>
              setDraft(kind, target.id, { includeAddons: e.target.checked })
            }
            label={tt("claims.wizard.includeAddons")}
          />
        )}
        {target.kind === "set" && target.pieces.length > 0 && (
          <div style={{ display: "grid", gap: "0.35rem", paddingLeft: "1rem" }}>
            <span style={{ color: "var(--text-muted)", fontSize: "0.88rem" }}>
              {tt("claims.wizard.pieceIntro")}
            </span>
            {target.pieces.map((piece) => {
              const pKey = lineKey("piece", piece.id);
              const pDraft = draftFor("piece", piece.id);
              const pLine = claim.lines.find(
                (l) => l.target_kind === "piece" && l.target_id === piece.id,
              );
              return (
                <div
                  key={piece.id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <span>
                    {piece.name}
                    <span style={{ color: "var(--text-muted)", fontSize: "0.88rem" }}>
                      {piece.part_number ? ` · ${piece.part_number}` : ""}
                      {` · ${tt(piece.kind === "core" ? "claims.wizard.corePiece" : "claims.wizard.addonPiece")}`}
                    </span>
                  </span>
                  {pLine ? (
                    <span style={{ display: "inline-flex", gap: "0.6rem", alignItems: "center" }}>
                      <span>{money(pLine.amount, claim.owner_currency)}</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busyKey === pKey}
                        onClick={() => remove(pLine.id, pKey)}
                      >
                        {tt("claims.wizard.remove")}
                      </Button>
                    </span>
                  ) : (
                    <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center" }}>
                      <TextInput
                        inputSize="sm"
                        inputMode="decimal"
                        placeholder={tt("claims.wizard.amountLabel")}
                        value={pDraft.amount}
                        onChange={(e) =>
                          setDraft("piece", piece.id, { amount: e.target.value })
                        }
                      />
                      <Button
                        size="sm"
                        disabled={busyKey === pKey}
                        onClick={() => add("piece", piece.id)}
                      >
                        {tt("claims.wizard.addPiece")}
                      </Button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  const all = [...targets.tools, ...targets.batteries];
  if (all.length === 0) {
    return (
      <Alert tone="warning">
        {tt("claims.wizard.emptyVault")}
      </Alert>
    );
  }
  /* F1-29: the picker is searchable — a 50-item vault is not a
   * scroll-and-hunt exercise. */
  const q = itemQuery.trim().toLowerCase();
  const visible = q
    ? all.filter((target) =>
        [target.name, target.brand, target.model]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(q),
      )
    : all;
  return (
    <div style={{ display: "grid", gap: "0.7rem" }}>
      <TextInput
        type="search"
        value={itemQuery}
        onChange={(e) => setItemQuery(e.target.value)}
        placeholder={tt("claims.wizard.searchItems")}
        aria-label={tt("claims.wizard.searchItems")}
      />
      {visible.length === 0 ? (
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          {tt("claims.wizard.noItemMatch")}
        </p>
      ) : (
        visible.map(targetRow)
      )}
    </div>
  );
}

export function ClaimWizard({
  open,
  onClose,
  onFinished,
}: {
  open: boolean;
  onClose: () => void;
  /** Called with the claim id when the wizard files the claim or
   *  the owner chooses "finish in the claim" — the parent routes
   *  to the detail page. Drafts closed any other way stay in the
   *  list. */
  onFinished: (claimId: string) => void;
}) {
  const { toast } = useToast();
  const tt = useT();
  const [step, setStep] = useState(0);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [targets, setTargets] = useState<ClaimTargets | null>(null);
  const [incident, setIncident] = useState<ClaimHeaderInput>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const [closeBusy, setCloseBusy] = useState(false);

  /* F2-05 lazy draft: opening the wizard mints NOTHING on the
   * server. The draft is created on the first real input — the
   * first item added, or the incident step being saved — through
   * ensureClaim(). An open-and-close with no input leaves the
   * claims list exactly as it was. */
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setStep(0);
    setError(null);
    setClaim(null);
    setTargets(null);
    setIncident({});
    setConfirmClose(false);
    (async () => {
      try {
        const picker = await disasterClaimsApi.getClaimTargets();
        if (cancelled) return;
        setTargets(picker);
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof ApiError ? err.message : tt("claims.wizard.couldntStart"),
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open ]);

  const hasIncidentContent = Object.values(incident).some(
    (v) => v !== null && v !== undefined && String(v).trim() !== "",
  );
  const incidentDirty =
    claim !== null &&
    JSON.stringify(incident) !== JSON.stringify(headerInputFrom(claim));

  async function ensureClaim(): Promise<Claim> {
    if (claim) return claim;
    const created = await disasterClaimsApi.createClaim({});
    setClaim(created);
    setIncident((prev) =>
      Object.values(prev).some(
        (v) => v !== null && v !== undefined && String(v).trim() !== "",
      )
        ? prev
        : headerInputFrom(created),
    );
    return created;
  }

  async function saveIncidentAndContinue() {
    // B-07 (Deep Audit Round 2): paging through with NO input
    // must not mint a permanent empty draft. The draft is minted
    // on first REAL input only — a target added (TargetPicker's
    // ensureClaim) or incident content actually typed (below).
    // An input-free Continue simply advances the step; steps 2/3
    // render their no-draft state and File stays gated.
    if (!claim && !hasIncidentContent) {
      setStep(2);
      return;
    }
    setBusy(true);
    try {
      const owner = await ensureClaim();
      const updated = await disasterClaimsApi.updateClaim(owner.id, incident);
      setClaim(updated);
      setIncident(headerInputFrom(updated));
      setStep(2);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : tt("claims.wizard.couldntSave"), {
        tone: "danger",
        title: tt("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  /* Close paths (Escape / backdrop / × all route here through the
   * Modal's onClose): typed-but-unsaved step work is NEVER silently
   * discarded — the user is asked to save it or discard it. Work
   * already saved to the draft (added items, saved incident,
   * uploaded evidence) closes straight away, as "Save draft &
   * close" promises. */
  function requestClose() {
    if (confirmClose) return;
    if (incidentDirty || (!claim && hasIncidentContent)) {
      setConfirmClose(true);
      return;
    }
    onClose();
  }

  async function saveAndClose() {
    if (!claim && !hasIncidentContent) {
      // Nothing meaningful to save: closing mints no draft.
      setConfirmClose(false);
      onClose();
      return;
    }
    setCloseBusy(true);
    try {
      const owner = await ensureClaim();
      if (incidentDirty || hasIncidentContent) {
        const updated = await disasterClaimsApi.updateClaim(owner.id, incident);
        setClaim(updated);
      }
      setConfirmClose(false);
      onClose();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : tt("claims.wizard.couldntSave"), {
        tone: "danger",
        title: tt("disasterClaims.title"),
      });
    } finally {
      setCloseBusy(false);
    }
  }

  async function discardAndClose() {
    setCloseBusy(true);
    try {
      // A draft minted during THIS wizard session is removed, so
      // discarding really discards; unsaved local work simply goes
      // away with the wizard.
      if (claim) await disasterClaimsApi.deleteClaim(claim.id).catch(() => undefined);
      setConfirmClose(false);
      onClose();
    } finally {
      setCloseBusy(false);
    }
  }

  async function fileClaim() {
    if (!claim) return;
    setBusy(true);
    try {
      await disasterClaimsApi.transitionClaim(claim.id, "filed");
      toast(
        tt("claims.wizard.filedToast").replace("{number}", claim.claim_number),
        {
          tone: "success",
          title: tt("disasterClaims.title"),
        },
      );
      onFinished(claim.id);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : tt("claims.wizard.couldntFile"), {
        tone: "danger",
        title: tt("disasterClaims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  const canFile = (claim?.lines.length ?? 0) > 0;

  return (
    <>
    <Modal
      open={open}
      onClose={requestClose}
      title={claim ? tt("claims.wizard.titleWithNumber").replace("{number}", claim.claim_number) : tt("claims.wizard.title")}
      size="lg"
      footer={
        claim || targets ? (
          <>
            {step > 0 && (
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                {tt("claims.wizard.back")}
              </Button>
            )}
            <span style={{ flex: 1 }} />
            <Button variant="ghost" onClick={() => void saveAndClose()} disabled={closeBusy}>
              {tt("claims.wizard.saveDraftClose")}
            </Button>
            {step < 3 && (
              <Button
                onClick={() =>
                  step === 1 ? saveIncidentAndContinue() : setStep(step + 1)
                }
                disabled={busy}
              >
                {tt("claims.wizard.continue")}
              </Button>
            )}
            {step === 3 && (
              <Button onClick={fileClaim} disabled={busy || !canFile}>
                {tt("claims.wizard.fileClaim")}
              </Button>
            )}
          </>
        ) : undefined
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      {!error && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: "0.5rem",
                marginBottom: "0.4rem",
              }}
            >
              {STEP_KEYS.map((key, i) => (
                <span
                  key={key}
                  style={{
                    fontWeight: i === step ? 700 : 400,
                    color: i === step ? "var(--text)" : "var(--text-muted)",
                  }}
                >
                  {i + 1}. {tt(key)}
                </span>
              ))}
            </div>
            <ProgressBar
              value={((step + 1) / STEP_KEYS.length) * 100}
              label={`${tt("wizard.stepOf").replace("{step}", String(step + 1)).replace("{total}", String(STEP_KEYS.length))}: ${tt(STEP_KEYS[step])}`}
            />
          </div>

          {step === 0 && (
            <>
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {tt("claims.wizard.targetIntro")}
              </p>
              {targets ? (
                <TargetPicker
                  claim={claim ?? NO_CLAIM}
                  targets={targets}
                  onClaimChange={setClaim}
                  ensureClaim={ensureClaim}
                />
              ) : (
                <Spinner />
              )}
            </>
          )}

          {step === 1 && (
            <>
              <IncidentForm
                value={incident}
                onChange={setIncident}
                incidentLocked={false}
                readOnly={false}
              />
              {(claim?.insurer_name || claim?.agent_name) && (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  {tt("claims.wizard.insurerProfileNote")}
                </p>
              )}
            </>
          )}

          {step === 2 && claim && (
            <Panel title={tt("claims.wizard.stepEvidence")}>
              <EvidenceSection
                claim={claim}
                targets={targets}
                editable
                onClaimChange={setClaim}
                claimApi={disasterClaimsApi}
              />
            </Panel>
          )}

          {step === 2 && !claim && (
            <p className="tv-muted">
              {tt("claims.wizard.evidenceNoDraft")}
            </p>
          )}

          {step === 3 && !claim && (
            <Alert tone="warning">
              {tt("claims.wizard.reviewNoClaim")}
            </Alert>
          )}

          {step === 3 && claim && (
            <div style={{ display: "grid", gap: "1rem" }}>
              <Panel title={tt("claims.wizard.stepReview")}>
                <div style={{ display: "grid", gap: "0.4rem" }}>
                  {claim.lines.length === 0 && (
                    <Alert tone="warning">
                      {tt("claims.wizard.reviewNoItems")}
                    </Alert>
                  )}
                  {claim.lines.map((line) => (
                    <div
                      key={line.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: "1rem",
                        flexWrap: "wrap",
                      }}
                    >
                      <span>
                        {line.target_name}
                        {line.target_kind === "piece" &&
                          ` ${tt("claims.wizard.pieceOf").replace("{set}", line.set_name ?? "")}`}
                        {line.target_kind === "set" &&
                          ` ${tt(line.include_addons ? "claims.wizard.setAddonsSuffix" : "claims.wizard.setSuffix")}`}
                        <span style={{ color: "var(--text-muted)" }}>
                          {" "}· {tt(`claims.basis.${line.value_basis}` as never)}
                        </span>
                      </span>
                      <strong>{money(line.amount, claim.owner_currency)}</strong>
                    </div>
                  ))}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      borderTop: "1px solid var(--edge)",
                      paddingTop: "0.5rem",
                    }}
                  >
                    <strong>{tt("claims.detail.claimTotal")}</strong>
                    <strong>{money(claim.total_amount, claim.owner_currency)}</strong>
                  </div>
                  <p style={{ margin: 0, color: "var(--text-muted)" }}>
                    {claim.insurer_name || tt("claims.noInsurer")}
                    {claim.incident_date
                      ? ` · ${tt("claims.wizard.incidentOn")
                          .replace("{type}", tt(`claims.incident.${claim.incident_type}` as never))
                          .replace("{date}", claim.incident_date)}`
                      : ""}
                    {" "}· {claim.evidence.length === 1
                      ? tt("claims.wizard.evidenceOne")
                      : tt("claims.wizard.evidenceMany").replace("{count}", String(claim.evidence.length))}
                  </p>
                </div>
              </Panel>
              <ChecklistPanel claim={claim} onClaimChange={setClaim} claimApi={disasterClaimsApi} />
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {tt("claims.wizard.filingNote")}
              </p>
            </div>
          )}
        </div>
      )}
    </Modal>
    <Modal
      open={confirmClose}
      onClose={() => setConfirmClose(false)}
      title={tt("claims.wizard.unsavedTitle")}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => setConfirmClose(false)} disabled={closeBusy}>
            {tt("claims.wizard.keepEditing")}
          </Button>
          <span style={{ flex: 1 }} />
          <Button variant="danger" onClick={() => void discardAndClose()} disabled={closeBusy}>
            {tt("claims.wizard.discard")}
          </Button>
          <Button onClick={() => void saveAndClose()} disabled={closeBusy}>
            {tt("claims.wizard.saveAndClose")}
          </Button>
        </>
      }
    >
      <p style={{ margin: 0 }}>{tt("claims.wizard.unsavedBody")}</p>
    </Modal>
    </>
  );
}
