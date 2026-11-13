import { Fragment, useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Breadcrumbs,
  Button,
  FormField,
  formGridStyle,
  LinkButton,
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
import { ApiError } from "../../lib/api";
import { focusFirstInvalid } from "../../lib/focusFirstInvalid";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import {
  addPreferred,
  createPrivateAgent,
  createPrivateCompany,
  listPrivateAgents,
  updatePrivateAgent,
} from "./api";
import { EMPTY_COMPANY, PHONE_LABELS } from "./components/CompanyForm";
import { ContactPickButton } from "./components/ContactPickButton";
import type {
  DealerCompanyWrite,
  DealerPhone,
  PrivateAgent,
  PrivateAgentWrite,
} from "./types";

/**
 * The Add Dealer wizard (Wizard Phase 2, 2026-10-25 — Ryan's
 * confirmed model, mirroring the Phase 1 tool wizard). Every
 * user-facing "Add dealer / Add a company" affordance lands here
 * (/dealers/new); EDITING an existing dealer stays on the full
 * CompanyForm on the Dealers page.
 *
 * Steps:
 *  1. Basics — the dealer record's own fields, exactly as the
 *     creation form defines them (name required; kind, email,
 *     website, address, phone rows, notes). The corporate
 *     warranty-directory fieldset stays on the full form — it is
 *     operator research data, not a private company's basics.
 *  2. The agent step (Ryan's fork): ADD a new authorized agent
 *     for this dealer, PICK one from the user's existing agent
 *     records, or skip — a dealer doesn't have to have an agent.
 *     Attaching = the same writes the Dealers page makes: a new
 *     agent becomes a private record FOR this company plus a
 *     preferred-agent row; a picked agent gains a preferred row
 *     for this company. An agent record belongs to ONE company
 *     (the backend refuses a cross-company preference), so a
 *     picked agent recorded for a different company is first
 *     re-homed to this dealer — the backend's own prescribed
 *     remedy — and the pick step and the review both say so
 *     before the user saves.
 *  3. Review, then save. Save lands on the company's own page,
 *     where the preferred agent shows.
 *
 * Text rides the .tv-wizard class block (theme/components.css):
 * plain body type for prose, questions and buttons in every
 * theme — the Phase 1 text standard.
 */

type StepId = "basics" | "agent" | "review";
type AgentMode = "" | "new" | "pick" | "skip";

const STEPS: StepId[] = ["basics", "agent", "review"];

const pageWidthStyle = {
  maxWidth: "760px",
  margin: "0 auto",
  display: "grid",
  gap: "var(--spacing)",
} as const;
const pageTitleStyle = { margin: "0.25rem 0 0", fontSize: "1.5rem" } as const;
const stackStyle = { display: "grid", gap: "var(--spacing)" } as const;
const mutedStyle = { margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" } as const;
const navRowStyle = {
  display: "flex",
  gap: "0.75rem",
  flexWrap: "wrap",
  alignItems: "center",
} as const;
const choiceColumnStyle = { display: "grid", gap: "0.7rem" } as const;
const choiceRowStyle = {
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
const choiceRowSelectedStyle = {
  ...choiceRowStyle,
  borderColor: "var(--accent)",
  outline: "1px solid var(--accent)",
} as const;
const choiceLabelStyle = { fontWeight: 600 } as const;
const choiceHintStyle = { color: "var(--text-muted)", fontSize: "0.85rem" } as const;
const phoneRowStyle = { display: "flex", gap: "0.5rem", flexWrap: "wrap" } as const;
const phoneLabelStyle = { maxWidth: "180px" } as const;
const phoneNumberStyle = { flex: "1 1 180px" } as const;
const phonesLabelStyle = { fontWeight: 600, fontSize: "0.9rem" } as const;
const reviewNoteStyle = {
  display: "block",
  color: "var(--text-muted)",
  fontSize: "0.85rem",
} as const;
const reviewRowStyle = { display: "flex", gap: "0.75rem", flexWrap: "wrap" } as const;
const reviewLabelStyle = {
  flex: "0 0 150px",
  color: "var(--text-muted)",
  fontSize: "0.9rem",
} as const;
const loadingStyle = {
  color: "var(--text-muted)",
  display: "flex",
  gap: "var(--space-2)",
  alignItems: "center",
} as const;

const EMPTY_AGENT: PrivateAgentWrite = {
  company_id: null,
  name: "",
  phone: "",
  email: "",
  notes: "",
};

export default function AddDealerWizardPage() {
  const t = useT();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [stepIndex, setStepIndex] = useState(0);
  const step: StepId = STEPS[Math.min(stepIndex, STEPS.length - 1)];

  // ---- dealer basics draft --------------------------------------
  const [name, setName] = useState("");
  const [kind, setKind] = useState<DealerCompanyWrite["kind"]>("manufacturer");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [address, setAddress] = useState("");
  const [phones, setPhones] = useState<DealerPhone[]>([]);
  const [notes, setNotes] = useState("");

  // ---- agent step -------------------------------------------------
  const [agents, setAgents] = useState<PrivateAgent[] | null>(null);
  const [agentsError, setAgentsError] = useState("");
  const [agentMode, setAgentMode] = useState<AgentMode>("");
  const [agentDraft, setAgentDraft] = useState<PrivateAgentWrite>(EMPTY_AGENT);
  const [pickedAgentId, setPickedAgentId] = useState("");

  // ---- shared chrome state -----------------------------------------
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // ---- unsaved-work guard (B-08) -----------------------------------
  // The whole draft, serialized: basics fields, phone rows, and
  // the agent step's mode + draft + pick. Nothing async pre-fills
  // this draft (the agents list is reference data, never copied
  // into it), so the baseline settles on mount; anything past it
  // asks before an exit discards it — the claim wizard's rule,
  // via components/UnsavedWorkGuard. Step moves are state, not
  // exits, and never come near the guard.
  const draftSerialized = JSON.stringify({
    name,
    kind,
    email,
    website,
    address,
    phones,
    notes,
    agentMode,
    agentDraft,
    pickedAgentId,
  });
  const wizardDirty = useDraftDirty(draftSerialized, true);
  const guard = useUnsavedWorkGuard(wizardDirty, "/dealers");

  useEffect(() => {
    let live = true;
    listPrivateAgents()
      .then((rows) => {
        if (live) setAgents(rows.filter((a) => !a.archived));
      })
      .catch((err) => {
        if (!live) return;
        setAgents([]);
        setAgentsError(
          err instanceof ApiError ? err.message : "Couldn't load your agents.",
        );
      });
    return () => {
      live = false;
    };
  }, []);

  // Step changes are page changes: land at the top.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [stepIndex]);

  function goTo(index: number) {
    setError("");
    setStepIndex(Math.max(0, Math.min(index, STEPS.length - 1)));
  }

  /** The plain-words warning for a picked agent whose record
   *  belongs to a different company: saving re-homes the record
   *  to this dealer (see save()). Empty when no move happens. */
  function pickMoveNote(picked: PrivateAgent | null): string {
    if (!picked || !picked.company_id) return "";
    return t("dealerWizard.pickMoveNote")
      .replace("{agent}", picked.name)
      .replace("{company}", picked.company_name ?? "")
      .replace("{dealer}", name.trim() || "this dealer");
  }

  function setPhone(index: number, patch: Partial<DealerPhone>) {
    setPhones((rows) => rows.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  function setAgentField<K extends keyof PrivateAgentWrite>(
    key: K,
    value: PrivateAgentWrite[K],
  ) {
    setAgentDraft((v) => ({ ...v, [key]: value }));
    if (key === "name") {
      setFieldErrors((prev) => {
        if (!prev.agentName) return prev;
        const next = { ...prev };
        delete next.agentName;
        return next;
      });
    }
  }

  // ---- per-step validation (runs on Next) ---------------------------
  function validateBasics(): boolean {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = t("dealerWizard.nameRequired");
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function validateAgent(): boolean {
    if (agentMode === "") {
      setError(t("dealerWizard.agentChoiceRequired"));
      return false;
    }
    if (agentMode === "new" && !agentDraft.name.trim()) {
      setFieldErrors({ agentName: t("dealerWizard.agentNameRequired") });
      return false;
    }
    if (agentMode === "pick" && !pickedAgentId) {
      setError(t("dealerWizard.agentPickRequired"));
      return false;
    }
    return true;
  }

  function onNext() {
    setError("");
    // B-05: a failed Next moves focus to the first invalid field
    // (shared wizard validation — lib/focusFirstInvalid). The
    // agent-choice errors are step-level (no owning field), so
    // focus stays put for those, as before.
    if (step === "basics" && !validateBasics()) { focusFirstInvalid(); return; }
    if (step === "agent" && !validateAgent()) { focusFirstInvalid(); return; }
    goTo(stepIndex + 1);
  }

  // ---- save -----------------------------------------------------------
  async function save() {
    if (busy) return;
    if (!validateBasics()) {
      goTo(0);
      focusFirstInvalid();
      return;
    }
    if (!validateAgent()) {
      goTo(1);
      focusFirstInvalid();
      return;
    }
    setBusy(true);
    setError("");
    const body: DealerCompanyWrite = {
      ...EMPTY_COMPANY,
      name: name.trim(),
      kind,
      email: email.trim(),
      website: website.trim(),
      address,
      phones: phones
        .filter((p) => p.number.trim())
        .map((p) => ({ label: p.label, number: p.number.trim() })),
      notes,
    };
    let company;
    try {
      company = await createPrivateCompany(body);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the dealer.");
      setBusy(false);
      return;
    }
    // The dealer is saved — even if the agent attach below
    // fails, save() still lands on the company's page, so the
    // guard stands down here, not at the navigate.
    guard.disarm();
    // The dealer is saved. Attaching the agent is the second
    // write; if IT fails the dealer still stands — land on its
    // page with a plain warning instead of stranding the user
    // here, where a retry would duplicate the company.
    let agentFailed = false;
    try {
      if (agentMode === "new") {
        const created = await createPrivateAgent({
          company_id: company.id,
          name: agentDraft.name.trim(),
          phone: agentDraft.phone.trim(),
          email: agentDraft.email.trim(),
          notes: agentDraft.notes,
        });
        await addPreferred({
          company_id: company.id,
          private_agent_id: created.id,
        });
      } else if (agentMode === "pick" && pickedAgentId) {
        const picked = (agents ?? []).find((a) => a.id === pickedAgentId);
        if (picked && picked.company_id && picked.company_id !== company.id) {
          // Re-home first (see the header note): the record's
          // contact fields ride along untouched; only its
          // company changes, then the preference can attach.
          await updatePrivateAgent(picked.id, {
            company_id: company.id,
            name: picked.name,
            phone: picked.phone,
            email: picked.email,
            notes: picked.notes,
          });
        }
        await addPreferred({
          company_id: company.id,
          private_agent_id: pickedAgentId,
        });
      }
    } catch {
      agentFailed = true;
    }
    if (agentFailed) {
      toast(t("dealerWizard.agentWarning"), { tone: "warning", duration: 12000 });
    } else {
      toast(t("dealerWizard.savedToast").replace("{name}", company.name), {
        tone: "success",
      });
    }
    navigate(`/dealers/${company.id}`, { replace: true });
  }

  // ---- step titles ------------------------------------------------------
  const stepTitle = (s: StepId): string => {
    switch (s) {
      case "basics":
        return t("wizard.basicsTitle");
      case "agent":
        return t("dealerWizard.agentTitle");
      case "review":
        return t("wizard.reviewTitle");
    }
  };

  // ---- step renderers -----------------------------------------------------
  function renderBasics() {
    return (
      <Panel title={t("wizard.basicsTitle")}>
        <div style={stackStyle}>
          <div style={formGridStyle}>
            <FormField label="Company name" htmlFor="dw-name" required error={fieldErrors.name}>
              <TextInput
                id="dw-name"
                invalid={Boolean(fieldErrors.name)}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setFieldErrors((prev) => {
                    if (!prev.name) return prev;
                    const next = { ...prev };
                    delete next.name;
                    return next;
                  });
                }}
              />
            </FormField>
            <FormField label="Kind" htmlFor="dw-kind">
              <Select
                id="dw-kind"
                value={kind}
                onChange={(e) =>
                  setKind(e.target.value as DealerCompanyWrite["kind"])
                }
              >
                <option value="manufacturer">Manufacturer</option>
                <option value="retailer">Retailer</option>
              </Select>
            </FormField>
            <FormField label="Email" htmlFor="dw-email">
              <TextInput
                id="dw-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </FormField>
            <FormField label="Website" htmlFor="dw-website">
              <TextInput
                id="dw-website"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                placeholder="https://…"
              />
            </FormField>
          </div>
          <FormField label="Address" htmlFor="dw-address">
            <TextArea id="dw-address" value={address} onChange={(e) => setAddress(e.target.value)} rows={2} />
          </FormField>
          <div style={choiceColumnStyle}>
            <span style={phonesLabelStyle}>Phone numbers</span>
            {phones.map((phone, i) => (
              <div key={i} style={phoneRowStyle}>
                <Select
                  value={phone.label}
                  onChange={(e) => setPhone(i, { label: e.target.value })}
                  aria-label="Phone department"
                  style={phoneLabelStyle}
                >
                  {PHONE_LABELS.map((label) => (
                    <option key={label} value={label}>
                      {label}
                    </option>
                  ))}
                </Select>
                <TextInput
                  value={phone.number}
                  onChange={(e) => setPhone(i, { number: e.target.value })}
                  placeholder="Phone number"
                  aria-label="Phone number"
                  style={phoneNumberStyle}
                />
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setPhones((rows) => rows.filter((_, idx) => idx !== i))}
                >
                  Remove
                </Button>
              </div>
            ))}
            <div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() =>
                  setPhones((rows) => [
                    ...rows,
                    { label: "Customer Service", number: "" },
                  ])
                }
              >
                Add a phone number
              </Button>
            </div>
          </div>
          <FormField label="Notes" htmlFor="dw-notes">
            <TextArea id="dw-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </FormField>
        </div>
      </Panel>
    );
  }

  function choiceRow(
    mode: Exclude<AgentMode, "">,
    label: string,
    hint: string,
  ) {
    const selected = agentMode === mode;
    return (
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => {
          setAgentMode(mode);
          setError("");
        }}
        style={selected ? choiceRowSelectedStyle : choiceRowStyle}
      >
        <span style={choiceLabelStyle}>{label}</span>
        <span style={choiceHintStyle}>{hint}</span>
      </button>
    );
  }

  function renderAgent() {
    return (
      <Panel title={t("dealerWizard.agentTitle")}>
        <div style={choiceColumnStyle}>
          <p style={mutedStyle}>{t("dealerWizard.agentBody")}</p>
          {choiceRow("new", t("dealerWizard.agentNew"), t("dealerWizard.agentNewHint"))}
          {choiceRow("pick", t("dealerWizard.agentPick"), t("dealerWizard.agentPickHint"))}
          {choiceRow("skip", t("dealerWizard.agentSkip"), t("dealerWizard.agentSkipHint"))}

          {agentMode === "new" && (
            <div style={stackStyle}>
              <div style={formGridStyle}>
                <FormField label="Name" htmlFor="dw-agent-name" required error={fieldErrors.agentName}>
                  <TextInput
                    id="dw-agent-name"
                    invalid={Boolean(fieldErrors.agentName)}
                    value={agentDraft.name}
                    onChange={(e) => setAgentField("name", e.target.value)}
                  />
                </FormField>
                <FormField label="Phone" htmlFor="dw-agent-phone">
                  <TextInput
                    id="dw-agent-phone"
                    value={agentDraft.phone}
                    onChange={(e) => setAgentField("phone", e.target.value)}
                  />
                </FormField>
                <FormField label="Email" htmlFor="dw-agent-email">
                  <TextInput
                    id="dw-agent-email"
                    type="email"
                    value={agentDraft.email}
                    onChange={(e) => setAgentField("email", e.target.value)}
                  />
                </FormField>
              </div>
              <FormField label="Notes" htmlFor="dw-agent-notes">
                <TextArea
                  id="dw-agent-notes"
                  value={agentDraft.notes}
                  onChange={(e) => setAgentField("notes", e.target.value)}
                  rows={2}
                />
              </FormField>
              <div>
                <ContactPickButton
                  onPick={(contact) =>
                    setAgentDraft((current) => ({
                      ...current,
                      name: contact.name ?? current.name,
                      phone: contact.phone ?? current.phone,
                      email: contact.email ?? current.email,
                    }))
                  }
                />
              </div>
            </div>
          )}

          {agentMode === "pick" &&
            (agents === null ? (
              <p style={loadingStyle}>
                <Spinner size="sm" /> Loading…
              </p>
            ) : agentsError ? (
              <Alert tone="danger">{agentsError}</Alert>
            ) : agents.length === 0 ? (
              <p style={mutedStyle}>{t("dealerWizard.noAgents")}</p>
            ) : (
              <div style={choiceColumnStyle}>
                {agents.map((agent) => {
                  const selected = pickedAgentId === agent.id;
                  return (
                    <button
                      key={agent.id}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => {
                        setPickedAgentId(agent.id);
                        setError("");
                      }}
                      style={selected ? choiceRowSelectedStyle : choiceRowStyle}
                    >
                      <span style={choiceLabelStyle}>
                        {agent.name}{" "}
                        {agent.company_name && (
                          <Badge tone="neutral">{agent.company_name}</Badge>
                        )}
                      </span>
                      <span style={choiceHintStyle}>
                        {[agent.phone, agent.email].filter(Boolean).join(" · ")}
                      </span>
                    </button>
                  );
                })}
                <p style={mutedStyle}>{t("dealerWizard.pickNote")}</p>
                {pickMoveNote((agents ?? []).find((a) => a.id === pickedAgentId) ?? null) && (
                  <p style={mutedStyle}>
                    {pickMoveNote((agents ?? []).find((a) => a.id === pickedAgentId) ?? null)}
                  </p>
                )}
              </div>
            ))}
        </div>
      </Panel>
    );
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
    const keptPhones = phones.filter((p) => p.number.trim());
    const picked = (agents ?? []).find((a) => a.id === pickedAgentId) ?? null;
    return (
      <Panel title={t("wizard.reviewTitle")}>
        <div style={choiceColumnStyle}>
          <p style={mutedStyle}>{t("wizard.reviewBody")}</p>
          {reviewRow("Company name", name.trim() || "—")}
          {reviewRow("Kind", kind === "retailer" ? "Retailer" : "Manufacturer")}
          {email.trim() && reviewRow("Email", email.trim())}
          {website.trim() && reviewRow("Website", website.trim())}
          {address.trim() && reviewRow("Address", address.trim())}
          {keptPhones.map((p) => (
            <Fragment key={`${p.label}-${p.number}`}>
              {reviewRow(p.label, p.number.trim())}
            </Fragment>
          ))}
          {notes.trim() && reviewRow("Notes", notes.trim().slice(0, 90))}
          {reviewRow(
            t("dealerWizard.reviewAgent"),
            agentMode === "new" ? (
              <>
                {agentDraft.name.trim() || "—"}
                {[agentDraft.phone.trim(), agentDraft.email.trim()]
                  .filter(Boolean)
                  .join(" · ") &&
                  ` — ${[agentDraft.phone.trim(), agentDraft.email.trim()]
                    .filter(Boolean)
                    .join(" · ")}`}
              </>
            ) : agentMode === "pick" ? (
              <>
                {picked?.name ?? "—"}
                {pickMoveNote(picked) && (
                  <span style={reviewNoteStyle}>{pickMoveNote(picked)}</span>
                )}
              </>
            ) : (
              t("dealerWizard.reviewNone")
            ),
          )}
        </div>
      </Panel>
    );
  }

  // ---- chrome ---------------------------------------------------------------
  const heading = t("dealerWizard.title");

  return (
    <RequireAuth>
      <div className="tv-wizard" style={pageWidthStyle}>
        <div>
          <Breadcrumbs
            items={[
              { label: "Dealers", to: "/dealers" },
              { label: heading },
            ]}
          />
          <h1 style={pageTitleStyle}>{heading}</h1>
        </div>

        <div style={choiceColumnStyle}>
          <p style={mutedStyle}>
            {t("wizard.stepOf")
              .replace("{step}", String(stepIndex + 1))
              .replace("{total}", String(STEPS.length))}{" "}
            — {stepTitle(step)}
          </p>
          <ProgressBar
            value={Math.round(((stepIndex + 1) / STEPS.length) * 100)}
            label={stepTitle(step)}
          />
        </div>

        {step === "basics"
          ? renderBasics()
          : step === "agent"
            ? renderAgent()
            : renderReview()}

        {error && <Alert tone="danger">{error}</Alert>}

        <div style={navRowStyle}>
          {stepIndex > 0 && (
            <Button
              type="button"
              variant="secondary"
              onClick={() => goTo(stepIndex - 1)}
              disabled={busy}
            >
              {t("wizard.back")}
            </Button>
          )}
          {step !== "review" ? (
            <Button type="button" onClick={onNext} disabled={busy}>
              {t("wizard.next")}
            </Button>
          ) : (
            <Button type="button" loading={busy} onClick={() => void save()}>
              {busy ? t("wizard.saving") : t("dealerWizard.save")}
            </Button>
          )}
          <LinkButton to="/dealers" variant="secondary">
            {t("common.cancel")}
          </LinkButton>
        </div>
        {guard.dialog}
      </div>
    </RequireAuth>
  );
}
