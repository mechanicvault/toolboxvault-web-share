import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Badge,
  Button,
  EmptyState,
  FormField,
  Panel,
  Select,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { ApiError, api } from "../../lib/api";

/**
 * INSURER PROFILE + POLICYHOLDERS (wave 3): an insurance-group
 * account names the directory company it works for and its role
 * there. An operator verifies the affiliation (the dealer
 * representation pattern); until then the profile reads
 * "pending" and the Policyholders surface stays closed.
 *
 * A policyholder appears ONLY when both doors are open: they
 * picked THIS company in their My Insurance AND they share
 * toward the insurance group. The item list itself is their
 * sharing preview — the same payload their own Sharing settings
 * show — never a second data path.
 */

export interface InsurerCompany {
  id: string;
  name: string;
  website: string;
  phones: { label: string; number: string }[];
  address: string;
  notes: string;
}

interface Affiliation {
  id: string;
  company_id: string;
  company_name: string;
  role_at_company: string;
  verified: boolean;
}

interface Policyholder {
  user_id: string;
  name: string;
  account_number: string;
  item_count: number;
}

type PreviewRow = Record<string, unknown>;

export default function InsurerProfileSettings() {
  const { toast } = useToast();
  const t = useT();
  const [companies, setCompanies] = useState<InsurerCompany[]>([]);
  const [affiliation, setAffiliation] = useState<Affiliation | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [companyId, setCompanyId] = useState("");
  const [role, setRole] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [holders, setHolders] = useState<Policyholder[] | null>(null);
  const [holdersError, setHoldersError] = useState<string | null>(null);
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);

  const loadHolders = useCallback(async (verified: boolean) => {
    if (!verified) {
      setHolders(null);
      return;
    }
    try {
      setHolders(await api<Policyholder[]>("/core/insurers/policyholders"));
      setHoldersError(null);
    } catch (err) {
      setHoldersError(
        err instanceof ApiError ? err.message : t("settings.insurer.holdersLoadFailed"),
      );
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [directory, mine] = await Promise.all([
          api<InsurerCompany[]>("/core/insurers/directory"),
          api<Affiliation | null>("/core/insurers/affiliation"),
        ]);
        if (cancelled) return;
        setCompanies(directory);
        setAffiliation(mine);
        if (mine) {
          setCompanyId(mine.company_id);
          setRole(mine.role_at_company);
        }
        setLoaded(true);
        void loadHolders(Boolean(mine?.verified));
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof ApiError ? err.message : t("settings.insurer.loadFailed"),
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadHolders]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!companyId) {
      setError(t("settings.insurer.pickCompany"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await api<Affiliation>("/core/insurers/affiliation", {
        method: "PUT",
        body: JSON.stringify({
          company_id: companyId,
          role_at_company: role.trim(),
        }),
      });
      setAffiliation(saved);
      toast(t("settings.insurer.savedToast"), { tone: "success" });
      void loadHolders(saved.verified);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.insurer.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function onClear() {
    setError(null);
    try {
      await api("/core/insurers/affiliation", { method: "DELETE" });
      setAffiliation(null);
      setCompanyId("");
      setRole("");
      setHolders(null);
      toast(t("settings.insurer.removedToast"), { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.insurer.removeFailed"));
    }
  }

  async function openPreview(holder: Policyholder) {
    setPreviewFor(holder.user_id);
    setPreview(null);
    try {
      setPreview(
        await api<PreviewRow[]>(
          `/core/insurers/policyholders/${holder.user_id}/preview`,
        ),
      );
    } catch (err) {
      setHoldersError(
        err instanceof ApiError ? err.message : t("settings.insurer.previewFailed"),
      );
      setPreviewFor(null);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Panel title={t("settings.insurer.title")} variant="plate">
        {error && <Alert tone="danger">{error}</Alert>}
        {!loaded && !error && <Spinner />}
        {loaded && (
          <form onSubmit={onSave} style={{ display: "grid", gap: "var(--space-3)" }}>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.insurer.intro")}
            </p>
            {affiliation &&
              (affiliation.verified ? (
                <span>
                  <Badge tone="success">{t("settings.insurer.verifiedBadge")}</Badge>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    {t("settings.insurer.youRepresent").replace(
                      "{name}",
                      affiliation.company_name,
                    )}
                  </span>
                </span>
              ) : (
                <span>
                  <Badge tone="warning">{t("settings.insurer.pendingBadge")}</Badge>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    {t("settings.insurer.pendingNote")}
                  </span>
                </span>
              ))}
            <FormField label={t("settings.insurer.companyLabel")} htmlFor="insurer-company-pick">
              <Select
                id="insurer-company-pick"
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}
              >
                <option value="">{t("settings.insurer.pickCompanyOption")}</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
            {companies.length === 0 && (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t("settings.insurer.directoryEmpty")}
              </p>
            )}
            <FormField label={t("settings.insurer.roleLabel")} htmlFor="insurer-role">
              <TextInput
                id="insurer-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                maxLength={200}
                placeholder={t("settings.insurer.rolePlaceholder")}
              />
            </FormField>
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <Button type="submit" loading={saving}>
                {t("settings.insurer.saveProfile")}
              </Button>
              {affiliation && (
                <Button type="button" variant="ghost" onClick={() => void onClear()}>
                  {t("settings.insurer.clearProfile")}
                </Button>
              )}
            </div>
          </form>
        )}
      </Panel>

      {affiliation?.verified && (
        <Panel title={t("settings.insurer.holdersTitle")}>
          {holdersError && <Alert tone="danger">{holdersError}</Alert>}
          {!holders && !holdersError && <Spinner />}
          {holders && holders.length === 0 && (
            <EmptyState
              title={t("settings.insurer.noHoldersTitle")}
              description={t("settings.insurer.noHoldersDesc")}
            />
          )}
          {holders &&
            holders.map((holder) => (
              <div key={holder.user_id} style={{ padding: "var(--space-2) 0" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "var(--space-3)",
                    flexWrap: "wrap",
                  }}
                >
                  <span>
                    <strong>{holder.name}</strong>
                    <span style={{ color: "var(--text-muted)" }}>
                      {" "}
                      · {holder.account_number}
                      {t(
                        holder.item_count === 1
                          ? "settings.insurer.sharedSuffixOne"
                          : "settings.insurer.sharedSuffixMany",
                      ).replace("{count}", String(holder.item_count))}
                    </span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => void openPreview(holder)}
                  >
                    {t("settings.insurer.viewShared")}
                  </Button>
                </div>
                {previewFor === holder.user_id &&
                  (preview === null ? (
                    <Spinner />
                  ) : (
                    <ul style={{ margin: "var(--space-2) 0", paddingLeft: "1.2rem" }}>
                      {preview.map((row, i) => (
                        <li key={String(row.id ?? i)}>
                          <strong>{String(row.name ?? t("settings.insurer.itemFallback"))}</strong>
                          {[row.brand, row.model, row.serial_number]
                            .filter(Boolean)
                            .map((v) => ` · ${String(v)}`)
                            .join("")}
                        </li>
                      ))}
                      {preview.length === 0 && <li>{t("settings.insurer.nothingShared")}</li>}
                    </ul>
                  ))}
              </div>
            ))}
        </Panel>
      )}
    </div>
  );
}
