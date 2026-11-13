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
        err instanceof ApiError ? err.message : "Couldn't load policyholders.",
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
            err instanceof ApiError ? err.message : "Couldn't load your profile.",
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
      setError("Pick the company you work for.");
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
      toast("Insurer profile saved.", { tone: "success" });
      void loadHolders(saved.verified);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save your profile.");
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
      toast("Insurer profile removed.", { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the profile.");
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
        err instanceof ApiError ? err.message : "Couldn't load that preview.",
      );
      setPreviewFor(null);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Panel title="Insurer profile" variant="plate">
        {error && <Alert tone="danger">{error}</Alert>}
        {!loaded && !error && <Spinner />}
        {loaded && (
          <form onSubmit={onSave} style={{ display: "grid", gap: "var(--space-3)" }}>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              The company you work for, from the platform directory.
              An operator verifies the affiliation before the
              Policyholders view opens — until then it reads pending.
            </p>
            {affiliation &&
              (affiliation.verified ? (
                <span>
                  <Badge tone="success">Verified</Badge>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    You represent {affiliation.company_name}.
                  </span>
                </span>
              ) : (
                <span>
                  <Badge tone="warning">Pending verification</Badge>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    An operator reviews new affiliations — the
                    Policyholders view opens once yours is verified.
                  </span>
                </span>
              ))}
            <FormField label="Company" htmlFor="insurer-company-pick">
              <Select
                id="insurer-company-pick"
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}
              >
                <option value="">Pick your company…</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
            {companies.length === 0 && (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                The directory is empty for now — companies appear
                here as they're added.
              </p>
            )}
            <FormField label="Your role there" htmlFor="insurer-role">
              <TextInput
                id="insurer-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                maxLength={200}
                placeholder="e.g. Claims adjuster, Agent"
              />
            </FormField>
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <Button type="submit" loading={saving}>
                Save insurer profile
              </Button>
              {affiliation && (
                <Button type="button" variant="ghost" onClick={() => void onClear()}>
                  Clear profile
                </Button>
              )}
            </div>
          </form>
        )}
      </Panel>

      {affiliation?.verified && (
        <Panel title="Policyholders">
          {holdersError && <Alert tone="danger">{holdersError}</Alert>}
          {!holders && !holdersError && <Spinner />}
          {holders && holders.length === 0 && (
            <EmptyState
              title="No policyholders sharing yet"
              description="A customer appears here when they pick your company in their My Insurance AND share toward the insurance group. Picking a company alone shares nothing."
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
                      · {holder.account_number} · {holder.item_count} shared
                      item{holder.item_count === 1 ? "" : "s"}
                    </span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => void openPreview(holder)}
                  >
                    View shared items
                  </Button>
                </div>
                {previewFor === holder.user_id &&
                  (preview === null ? (
                    <Spinner />
                  ) : (
                    <ul style={{ margin: "var(--space-2) 0", paddingLeft: "1.2rem" }}>
                      {preview.map((row, i) => (
                        <li key={String(row.id ?? i)}>
                          <strong>{String(row.name ?? "Item")}</strong>
                          {[row.brand, row.model, row.serial_number]
                            .filter(Boolean)
                            .map((v) => ` · ${String(v)}`)
                            .join("")}
                        </li>
                      ))}
                      {preview.length === 0 && <li>Nothing shared.</li>}
                    </ul>
                  ))}
              </div>
            ))}
        </Panel>
      )}
    </div>
  );
}
