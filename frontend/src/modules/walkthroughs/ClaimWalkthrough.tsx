import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Checkbox,
  FormField,
  Select,
  TextArea,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import {
  createWarrantyClaim,
  getWarrantyFilingOptions,
} from "../claims/api";
import { claimsApi } from "../claims/api";
import type {
  ClaimTarget,
  TargetKind,
  WarrantyAgent,
  WarrantyFilingOptions,
} from "../claims/types";
import { WalkthroughFooter, WalkthroughShell } from "./WalkthroughShell";
import "../claims/claims.css";

/**
 * The first-claim walkthrough (sweep D3): a guided,
 * step-at-a-time pass over the REAL warranty claim flow —
 * the same filing options read, the same three filing
 * routes, and the same createWarrantyClaim submit as the
 * item page's ClaimForm. The final step files the claim
 * for real and lands on the claim's own page.
 *
 * Steps: 1 pick the tool · 2 what happened · 3 who it's
 * filed with (dealer/agent) · 4 review & file.
 *
 * REPAIR claims only. Disaster Claims keeps its own filing
 * wizard (a do-not-lose surface that is already a guided
 * step pass) and the two claim kinds never mix — this
 * walkthrough reads and writes the warranty section alone.
 */

const TOTAL = 4;

function agentKey(agent: WarrantyAgent): string {
  return agent.agent_user_id
    ? `platform:${agent.agent_user_id}`
    : `private:${agent.private_agent_id}`;
}

export interface ClaimWalkTarget {
  kind: TargetKind;
  id: string;
  name?: string;
}

export function ClaimWalkthrough({
  open,
  initialTarget,
  onClose,
  onDone,
}: {
  open: boolean;
  initialTarget?: ClaimWalkTarget | null;
  onClose: () => void;
  onDone?: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [step, setStep] = useState(0);
  const [targets, setTargets] = useState<ClaimTarget[] | null>(null);
  const [pick, setPick] = useState<ClaimTarget | null>(null);
  const [problem, setProblem] = useState("");
  const [includeAddons, setIncludeAddons] = useState(false);
  const [options, setOptions] = useState<WarrantyFilingOptions | null>(null);
  const [picked, setPicked] = useState("");
  const [route, setRoute] = useState<"" | "agent" | "self" | "corporate">("");
  const [notified, setNotified] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Fresh pass every open (the restart-on-exit decision).
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setProblem("");
    setIncludeAddons(false);
    setError("");
    setBusy(false);
    setTargets(null);
    setPick(null);
    claimsApi
      .getClaimTargets()
      .then((result) => {
        const all = [...result.tools, ...result.batteries];
        setTargets(all);
        if (initialTarget) {
          const found = all.find(
            (row) => row.id === initialTarget.id && row.kind === initialTarget.kind,
          );
          setPick(
            found ?? {
              kind: initialTarget.kind === "piece" ? "tool" : initialTarget.kind,
              id: initialTarget.id,
              name: initialTarget.name ?? "",
              brand: "",
              model: "",
              serial_number: "",
              quantity: 1,
              purchase_price: null,
              replacement_cost: null,
              msrp: null,
              attachments: [],
              pieces: [],
            },
          );
        }
      })
      .catch(() => setTargets([]));
  }, [open, initialTarget ]);

  // The filing-options read follows the pick, exactly as the
  // ClaimForm's agent step does.
  useEffect(() => {
    if (!pick) {
      setOptions(null);
      return;
    }
    let cancelled = false;
    setOptions(null);
    setPicked("");
    setRoute("");
    setNotified(false);
    getWarrantyFilingOptions(pick.kind, pick.id)
      .then((result) => {
        if (!cancelled) setOptions(result);
      })
      .catch(() => {
        if (!cancelled) setOptions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pick]);

  const agents = options?.agents ?? [];
  const yourAgents = agents.filter((a) => a.kind === "private");
  const listedAgents = agents.filter((a) => a.kind === "platform");
  const defaultKey = options
    ? options.default_agent_user_id
      ? `platform:${options.default_agent_user_id}`
      : options.default_private_agent_id
        ? `private:${options.default_private_agent_id}`
        : "none"
    : "none";
  const selectedKey = picked || defaultKey;
  const selectedAgent =
    agents.find((agent) => agentKey(agent) === selectedKey) ?? null;
  const showAgentStep = Boolean(
    options && options.dealer_company_id && agents.length > 0,
  );
  const showRouteStep = Boolean(options && options.dealer_company_id);
  const activeRoute: "agent" | "self" | "corporate" =
    route ||
    (options?.default_agent_user_id || options?.default_private_agent_id
      ? "agent"
      : "self");
  const routeAgent = activeRoute === "agent" ? selectedAgent : null;
  const agentOption = (agent: WarrantyAgent) => (
    <option key={agentKey(agent)} value={agentKey(agent)}>
      {agent.name}
      {agentKey(agent) === defaultKey
        ? t("claims.broken.agentDefaultSuffix")
        : ""}
    </option>
  );

  const filedWithSummary = !showRouteStep
    ? t("walk.claim.review.selfTrack" as never)
    : activeRoute === "agent"
      ? (routeAgent?.name ?? t("claims.broken.routeAgent"))
      : activeRoute === "corporate"
        ? t("claims.broken.routeCorporate")
        : t("claims.broken.routeSelf");

  async function submit() {
    if (!pick) return;
    setError("");
    setBusy(true);
    try {
      const result = await createWarrantyClaim({
        target_kind: pick.kind,
        target_id: pick.id,
        include_addons: includeAddons,
        dealer_notified:
          activeRoute === "self" && options ? false : notified,
        problem: problem.trim(),
        ...(options
          ? {
              filed_with: activeRoute,
              agent_user_id: routeAgent?.agent_user_id ?? null,
              private_agent_id: routeAgent?.private_agent_id ?? null,
              no_agent: activeRoute !== "agent" || !routeAgent,
            }
          : {}),
      });
      toast(
        result.reported
          ? t("claims.broken.claimReported")
          : t("claims.broken.claimNotReported"),
        { tone: "success", title: result.claim.claim_number },
      );
      onDone?.();
      navigate(`/claims/${result.claim.id}`);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("walk.claim.errGeneric" as never),
      );
    } finally {
      setBusy(false);
    }
  }

  const footer = (
    <WalkthroughFooter
      onBack={step > 0 ? () => setStep(step - 1) : undefined}
      onExit={onClose}
      onSkip={step === 1 ? () => setStep(2) : undefined}
      onContinue={() => {
        if (step < TOTAL - 1) setStep(step + 1);
        else void submit();
      }}
      continueLabel={
        step < TOTAL - 1
          ? t("walk.continue" as never)
          : t("claims.broken.createClaim")
      }
      continueDisabled={step === 0 && pick === null}
      busy={busy}
    />
  );

  return (
    <WalkthroughShell
      open={open}
      title={t("walk.claim.title" as never)}
      stepIndex={step}
      totalSteps={TOTAL}
      onExit={onClose}
      footer={footer}
    >
      {step === 0 && (
        <div className="tv-setup-step">
          <h2>{t("walk.claim.s1.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.claim.s1.intro" as never)}</p>
          {targets === null ? (
            <p className="tv-walk-muted">{t("walk.loading" as never)}</p>
          ) : targets.length === 0 && !pick ? (
            <p className="tv-walk-muted">{t("walk.claim.s1.empty" as never)}</p>
          ) : (
            <div className="tv-walk-picklist" role="listbox">
              {(targets ?? []).map((row) => (
                <button
                  key={`${row.kind}:${row.id}`}
                  type="button"
                  role="option"
                  aria-selected={pick?.id === row.id && pick?.kind === row.kind}
                  className={
                    pick?.id === row.id && pick?.kind === row.kind
                      ? "tv-walk-pickrow is-picked"
                      : "tv-walk-pickrow"
                  }
                  onClick={() => setPick(row)}
                >
                  <span className="tv-walk-pickrow-name">{row.name}</span>
                  <span className="tv-walk-pickrow-sub">
                    {[row.brand, row.model].filter(Boolean).join(" ") ||
                      t(
                        (row.kind === "battery"
                          ? "walk.kind.battery"
                          : row.kind === "set"
                            ? "walk.kind.set"
                            : "walk.kind.tool") as never,
                      )}
                  </span>
                </button>
              ))}
              {pick &&
                !(targets ?? []).some(
                  (row) => row.id === pick.id && row.kind === pick.kind,
                ) && (
                  <button
                    type="button"
                    role="option"
                    aria-selected
                    className="tv-walk-pickrow is-picked"
                  >
                    <span className="tv-walk-pickrow-name">{pick.name}</span>
                  </button>
                )}
            </div>
          )}
          {pick === null && targets !== null && targets.length > 0 && (
            <p className="tv-setup-hint">{t("walk.pickFirst" as never)}</p>
          )}
        </div>
      )}

      {step === 1 && (
        <div className="tv-setup-step">
          <h2>{t("walk.claim.s2.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.claim.s2.intro" as never)}</p>
          <div className="tv-setup-form">
            <FormField label={t("claims.broken.problem")}>
              <TextArea
                rows={3}
                value={problem}
                onChange={(e) => setProblem(e.target.value)}
              />
            </FormField>
            {pick?.kind === "set" && (
              <Checkbox
                checked={includeAddons}
                onChange={(e) => setIncludeAddons(e.target.checked)}
                label={t("claims.broken.includeAddons")}
              />
            )}
          </div>
          <div className="tv-setup-example">
            <span className="tv-setup-example-label">
              {t("setup.example.label" as never)}
            </span>
            <p>{t("walk.claim.s2.example" as never)}</p>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="tv-setup-step">
          <h2>{t("walk.claim.s3.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.claim.s3.intro" as never)}</p>
          {!showRouteStep ? (
            <p className="tv-walk-muted">{t("walk.claim.s3.noDealer" as never)}</p>
          ) : (
            <div className="tv-setup-form">
              <FormField label={t("claims.broken.filedWith")}>
                <div className="tv-broken-choices">
                  <label className="tv-broken-choice">
                    <input
                      type="radio"
                      name="walk-filed-with"
                      checked={activeRoute === "agent"}
                      disabled={agents.length === 0}
                      onChange={() => {
                        setRoute("agent");
                        if (picked === "none") setPicked("");
                      }}
                    />
                    {t("claims.broken.routeAgent")}
                  </label>
                  <label className="tv-broken-choice">
                    <input
                      type="radio"
                      name="walk-filed-with"
                      checked={activeRoute === "self"}
                      onChange={() => setRoute("self")}
                    />
                    {t("claims.broken.routeSelf")}
                  </label>
                  <label className="tv-broken-choice">
                    <input
                      type="radio"
                      name="walk-filed-with"
                      checked={activeRoute === "corporate"}
                      onChange={() => setRoute("corporate")}
                    />
                    {t("claims.broken.routeCorporate")}
                  </label>
                </div>
              </FormField>
              {showAgentStep && activeRoute === "agent" && (
                <FormField label={t("claims.broken.agent")}>
                  <Select
                    value={selectedKey}
                    onChange={(e) => {
                      setPicked(e.target.value);
                      if (e.target.value === "none") setRoute("self");
                    }}
                  >
                    {yourAgents.length > 0 && (
                      <optgroup label={t("dealers.roster.yoursTitle")}>
                        {yourAgents.map(agentOption)}
                      </optgroup>
                    )}
                    {listedAgents.length > 0 && (
                      <optgroup label={t("dealers.roster.listedTitle")}>
                        {listedAgents.map(agentOption)}
                      </optgroup>
                    )}
                    <option value="none">{t("claims.broken.agentNone")}</option>
                  </Select>
                </FormField>
              )}
              {(!options || routeAgent || activeRoute === "corporate") && (
                <FormField
                  label={
                    routeAgent
                      ? t("claims.broken.notifiedAgent")
                      : t("claims.broken.notified")
                  }
                >
                  <div className="tv-broken-choices">
                    <label className="tv-broken-choice">
                      <input
                        type="radio"
                        name="walk-dealer-notified"
                        checked={notified}
                        onChange={() => setNotified(true)}
                      />
                      {t("claims.broken.notifiedYes")}
                    </label>
                    <label className="tv-broken-choice">
                      <input
                        type="radio"
                        name="walk-dealer-notified"
                        checked={!notified}
                        onChange={() => setNotified(false)}
                      />
                      {t("claims.broken.notifiedNo")}
                    </label>
                  </div>
                </FormField>
              )}
            </div>
          )}
          <div className="tv-setup-example">
            <span className="tv-setup-example-label">
              {t("setup.example.label" as never)}
            </span>
            <p>{t("walk.claim.s3.example" as never)}</p>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="tv-setup-step">
          <h2>{t("walk.claim.s4.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.claim.s4.intro" as never)}</p>
          <div className="tv-walk-review">
            <div className="tv-walk-review-row">
              <span className="tv-walk-review-label">
                {t("walk.review.tool" as never)}
              </span>
              <span className="tv-walk-review-value">{pick?.name ?? "—"}</span>
            </div>
            <div className="tv-walk-review-row">
              <span className="tv-walk-review-label">
                {t("walk.review.problem" as never)}
              </span>
              <span className="tv-walk-review-value">
                {problem.trim() || t("walk.claim.review.noProblem" as never)}
              </span>
            </div>
            <div className="tv-walk-review-row">
              <span className="tv-walk-review-label">
                {t("walk.review.filedWith" as never)}
              </span>
              <span className="tv-walk-review-value">{filedWithSummary}</span>
            </div>
          </div>
          {error && (
            <p role="alert" className="tv-walk-error">
              {error}
            </p>
          )}
        </div>
      )}
    </WalkthroughShell>
  );
}
