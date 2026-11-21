import { useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Button,
  FormField,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { ApiError, api } from "../../lib/api";
import type { InsurerCompany } from "./InsurerProfileSettings";

/**
 * MY INSURANCE (Package C, owner review round 1 item 17): the
 * user's own insurer + agent, saved once here instead of retyped
 * on every claim. The claim form pre-fills insurer + policy number
 * from this profile, and each claim snapshots the agent block when
 * it's created — so editing this profile later never rewrites a
 * claim already filed. Nothing here is shared with anyone; it's
 * the owner's own record, visible only to them.
 */

interface InsuranceProfile {
  has_profile: boolean;
  insurer_company: string;
  agent_name: string;
  agent_phone: string;
  agent_email: string;
  policy_number: string;
  notes: string;
  /** Wave 3: the directory link — picking a company fills the
   * name above (still editable); null = typed by hand. */
  insurer_company_id: string | null;
  insurer_company_name: string | null;
  // Policy depth (audit A9): the owner's own policy facts.
  // Money rides as cents; null = not declared.
  policy_type: string;
  deductible_cents: number | null;
  coverage_limit_cents: number | null;
  valuation_basis: string;
  business_sub_limit_cents: number | null;
  how_to_file: string;
  updated_at: string | null;
}

const POLICY_TYPE_VALUES: string[] = [
  "",
  "homeowners",
  "renters",
  "commercial",
  "dedicated_tool",
  "other",
];

const POLICY_TYPE_KEYS: Record<string, DictKey> = {
  "": "settings.insurance.notRecorded",
  homeowners: "settings.insurance.policyTypeHomeowners",
  renters: "settings.insurance.policyTypeRenters",
  commercial: "settings.insurance.policyTypeCommercial",
  dedicated_tool: "settings.insurance.policyTypeDedicated",
  other: "settings.insurance.policyTypeOther",
};

function dollarsOf(cents: number | null): string {
  return cents === null ? "" : String(cents / 100);
}
function centsOf(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null;
}

const inputRow: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))",
};

export default function InsuranceSettings() {
  const { toast } = useToast();
  const t = useT();
  const [profile, setProfile] = useState<InsuranceProfile | null>(null);
  const [directory, setDirectory] = useState<InsurerCompany[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api<InsuranceProfile>("/core/insurance");
        if (!cancelled) setProfile(data);
        // The directory pick is best-effort: without it the form
        // still works as free text (the fallback).
        try {
          const companies = await api<InsurerCompany[]>("/core/insurers/directory");
          if (!cancelled) setDirectory(companies);
        } catch {
          if (!cancelled) setDirectory([]);
        }
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof ApiError
              ? err.message
              : t("settings.insurance.loadFailed"),
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const set = (patch: Partial<InsuranceProfile>) =>
    setProfile((prev) => (prev ? { ...prev, ...patch } : prev));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setError(null);
    setSubmitting(true);
    try {
      const saved = await api<InsuranceProfile>("/core/insurance", {
        method: "PUT",
        body: JSON.stringify({
          insurer_company: profile.insurer_company,
          insurer_company_id: profile.insurer_company_id,
          agent_name: profile.agent_name,
          agent_phone: profile.agent_phone,
          agent_email: profile.agent_email,
          policy_number: profile.policy_number,
          notes: profile.notes,
          policy_type: profile.policy_type,
          deductible_cents: profile.deductible_cents,
          coverage_limit_cents: profile.coverage_limit_cents,
          valuation_basis: profile.valuation_basis,
          business_sub_limit_cents: profile.business_sub_limit_cents,
          how_to_file: profile.how_to_file,
        }),
      });
      setProfile(saved);
      toast(t("settings.insurance.savedToast"), {
        title: t("settings.publicProfile.savedTitle"),
        tone: "success",
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("settings.insurance.saveFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Panel title={t("settings.insurance.title")} variant="plate">
      {error && <Alert tone="danger">{error}</Alert>}
      {!profile && !error && <Spinner />}
      {profile && (
        <form
          onSubmit={onSubmit}
          style={{ display: "grid", gap: "var(--space-3)" }}
        >
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("settings.insurance.intro")}
          </p>
          {directory.length > 0 && (
            <FormField
              label={t("settings.insurance.directoryPick")}
              htmlFor="insurance-directory-pick"
              hint={t("settings.insurance.directoryHint")}
            >
              <Select
                id="insurance-directory-pick"
                value={profile.insurer_company_id ?? ""}
                onChange={(e) => {
                  const picked = directory.find((c) => c.id === e.target.value);
                  if (picked) {
                    set({
                      insurer_company_id: picked.id,
                      insurer_company: picked.name,
                    });
                  } else {
                    set({ insurer_company_id: null });
                  }
                }}
              >
                <option value="">{t("settings.insurance.typeItMyself")}</option>
                {directory.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
          <div style={inputRow}>
            <FormField label={t("settings.insurance.company")} htmlFor="insurance-company">
              <TextInput
                id="insurance-company"
                value={profile.insurer_company}
                onChange={(e) => set({ insurer_company: e.target.value })}
                placeholder={t("settings.insurance.companyPlaceholder")}
                maxLength={300}
              />
            </FormField>
            <FormField label={t("settings.insurance.policyNumber")} htmlFor="insurance-policy">
              <TextInput
                id="insurance-policy"
                value={profile.policy_number}
                onChange={(e) => set({ policy_number: e.target.value })}
                maxLength={200}
              />
            </FormField>
          </div>
          <div style={inputRow}>
            <FormField label={t("settings.insurance.agentName")} htmlFor="insurance-agent-name">
              <TextInput
                id="insurance-agent-name"
                value={profile.agent_name}
                onChange={(e) => set({ agent_name: e.target.value })}
                maxLength={300}
                autoComplete="name"
              />
            </FormField>
            <FormField label={t("settings.insurance.agentPhone")} htmlFor="insurance-agent-phone">
              <TextInput
                id="insurance-agent-phone"
                value={profile.agent_phone}
                onChange={(e) => set({ agent_phone: e.target.value })}
                maxLength={60}
                autoComplete="tel"
              />
            </FormField>
            <FormField label={t("settings.insurance.agentEmail")} htmlFor="insurance-agent-email">
              <TextInput
                id="insurance-agent-email"
                type="email"
                value={profile.agent_email}
                onChange={(e) => set({ agent_email: e.target.value })}
                maxLength={320}
                autoComplete="email"
              />
            </FormField>
          </div>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <p style={{ fontWeight: 700, margin: 0 }}>{t("settings.insurance.policyDetails")}</p>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.insurance.policyDetailsIntro")}
            </p>
            <div style={inputRow}>
              <FormField label={t("settings.insurance.policyType")} htmlFor="insurance-policy-type">
                <Select
                  id="insurance-policy-type"
                  value={profile.policy_type}
                  onChange={(e) => set({ policy_type: e.target.value })}
                >
                  {POLICY_TYPE_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {t(POLICY_TYPE_KEYS[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label={t("settings.insurance.valuationBasis")} htmlFor="insurance-valuation">
                <Select
                  id="insurance-valuation"
                  value={profile.valuation_basis}
                  onChange={(e) => set({ valuation_basis: e.target.value })}
                >
                  <option value="">{t("settings.insurance.notRecorded")}</option>
                  <option value="rcv">{t("settings.insurance.valuationRcv")}</option>
                  <option value="acv">{t("settings.insurance.valuationAcv")}</option>
                </Select>
              </FormField>
            </div>
            <div style={inputRow}>
              <FormField label={t("settings.insurance.deductible")} htmlFor="insurance-deductible">
                <TextInput
                  id="insurance-deductible"
                  type="number"
                  min="0"
                  step="any"
                  value={dollarsOf(profile.deductible_cents)}
                  onChange={(e) => set({ deductible_cents: centsOf(e.target.value) })}
                />
              </FormField>
              <FormField label={t("settings.insurance.coverageLimit")} htmlFor="insurance-coverage">
                <TextInput
                  id="insurance-coverage"
                  type="number"
                  min="0"
                  step="any"
                  value={dollarsOf(profile.coverage_limit_cents)}
                  onChange={(e) =>
                    set({ coverage_limit_cents: centsOf(e.target.value) })
                  }
                />
              </FormField>
              <FormField
                label={t("settings.insurance.businessSubLimit")}
                htmlFor="insurance-sublimit"
                hint={t("settings.insurance.businessSubLimitHint")}
              >
                <TextInput
                  id="insurance-sublimit"
                  type="number"
                  min="0"
                  step="any"
                  value={dollarsOf(profile.business_sub_limit_cents)}
                  onChange={(e) =>
                    set({ business_sub_limit_cents: centsOf(e.target.value) })
                  }
                />
              </FormField>
            </div>
            <FormField label={t("settings.insurance.howToFile")} htmlFor="insurance-howto">
              <TextArea
                id="insurance-howto"
                value={profile.how_to_file}
                onChange={(e) => set({ how_to_file: e.target.value })}
                rows={3}
                placeholder={t("settings.insurance.howToFilePlaceholder")}
              />
            </FormField>
          </div>
          <FormField label={t("settings.insurance.notes")} htmlFor="insurance-notes">
            <TextArea
              id="insurance-notes"
              value={profile.notes}
              onChange={(e) => set({ notes: e.target.value })}
              rows={3}
              placeholder={t("settings.insurance.notesPlaceholder")}
            />
          </FormField>
          <div>
            <Button type="submit" loading={submitting}>{t("settings.insurance.save")}</Button>
          </div>
        </form>
      )}
    </Panel>
  );
}
