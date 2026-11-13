import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Badge,
  Button,
  CopyButton,
  DataTable,
  EmptyState,
  FormField,
  Panel,
  Spinner,
  TextArea,
  TextInput,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { api, ApiError } from "../../../lib/api";
import type { InsurerCompany } from "../InsurerProfileSettings";
import { AdminShell } from "./AdminShell";

/**
 * Operator surface for the platform INSURER directory (wave 3 —
 * mirrors the dealer directory): the companies insurance-group
 * users affiliate with and every user can pick in My Insurance.
 * The directory starts EMPTY on purpose — rows land here as real
 * insurers are added; nothing is seeded or invented.
 *
 * Below the directory: affiliation review — insurance-group
 * users claim a company + role; an operator verifies the claim
 * (audited server-side, like dealer representations). Only
 * VERIFIED affiliations can open the Policyholders view.
 */

interface InsurerCompanyWrite {
  name: string;
  website: string;
  phones: { label: string; number: string }[];
  address: string;
  notes: string;
}

interface AffiliationAdmin {
  id: string;
  user_id: string;
  company_id: string;
  company_name: string;
  role_at_company: string;
  verified: boolean;
  user_name: string;
  user_email: string;
  user_account_number: string;
  verified_at: string | null;
  created_at: string;
}

const EMPTY_WRITE: InsurerCompanyWrite = {
  name: "",
  website: "",
  phones: [],
  address: "",
  notes: "",
};

function CompanyForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: InsurerCompanyWrite;
  submitLabel: string;
  onSubmit: (body: InsurerCompanyWrite) => Promise<void>;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<InsurerCompanyWrite>(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onSubmit({
        ...values,
        name: values.name.trim(),
        phones: values.phones.filter((p) => p.number.trim()),
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the company.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label="Company name" htmlFor="ins-co-name" required>
        <TextInput
          id="ins-co-name"
          value={values.name}
          onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
          required
          maxLength={300}
        />
      </FormField>
      <FormField label="Website" htmlFor="ins-co-website">
        <TextInput
          id="ins-co-website"
          value={values.website}
          onChange={(e) => setValues((v) => ({ ...v, website: e.target.value }))}
          maxLength={500}
          placeholder="https://…"
        />
      </FormField>
      <div style={{ display: "grid", gap: "var(--space-2)" }}>
        <span style={{ fontWeight: 600 }}>Phone numbers</span>
        {values.phones.map((phone, i) => (
          <div key={i} style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <TextInput
              value={phone.label}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  phones: v.phones.map((p, idx) =>
                    idx === i ? { ...p, label: e.target.value } : p,
                  ),
                }))
              }
              placeholder="Label (e.g. Claims)"
              maxLength={60}
            />
            <TextInput
              value={phone.number}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  phones: v.phones.map((p, idx) =>
                    idx === i ? { ...p, number: e.target.value } : p,
                  ),
                }))
              }
              placeholder="800-555-0100"
              maxLength={60}
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                setValues((v) => ({
                  ...v,
                  phones: v.phones.filter((_, idx) => idx !== i),
                }))
              }
            >
              Remove
            </Button>
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              setValues((v) => ({
                ...v,
                phones: [...v.phones, { label: "Claims", number: "" }],
              }))
            }
          >
            Add a phone
          </Button>
        </div>
      </div>
      <FormField label="Address" htmlFor="ins-co-address">
        <TextArea
          id="ins-co-address"
          value={values.address}
          onChange={(e) => setValues((v) => ({ ...v, address: e.target.value }))}
          rows={2}
        />
      </FormField>
      <FormField label="Notes" htmlFor="ins-co-notes">
        <TextArea
          id="ins-co-notes"
          value={values.notes}
          onChange={(e) => setValues((v) => ({ ...v, notes: e.target.value }))}
          rows={3}
        />
      </FormField>
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <Button type="submit" loading={busy}>
          {submitLabel}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export default function AdminInsurerDirectoryPage() {
  const t = useT();
  const [companies, setCompanies] = useState<InsurerCompany[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<InsurerCompany | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setCompanies(await api<InsurerCompany[]>("/admin/insurer-companies"));
  }, []);

  useEffect(() => {
    refresh().catch((err) =>
      setError(err instanceof ApiError ? err.message : "Couldn't load the directory."),
    );
  }, [refresh]);

  async function remove(company: InsurerCompany) {
    if (
      !window.confirm(
        `Remove "${company.name}" from the directory? Affiliations naming it are removed; My Insurance profiles keep their typed name but lose the link.`,
      )
    )
      return;
    setError("");
    try {
      await api(`/admin/insurer-companies/${company.id}`, { method: "DELETE" });
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the company.");
    }
  }

  return (
    <AdminShell>
      {/* 09b-F4: same Panel title treatment as every other Admin
          section (see the dealer directory). */}
      <Panel title="Insurer directory" style={{ marginBottom: "var(--spacing)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          The platform directory insurance-group users affiliate with
          and every user can pick from in My Insurance. It starts
          empty — add real insurers as they're verified; nothing here
          is seeded.
        </p>
      </Panel>
      {error && <Alert tone="danger">{error}</Alert>}

      {!adding && !editing && (
        <div style={{ marginBottom: "var(--spacing)" }}>
          <Button onClick={() => setAdding(true)}>Add a directory company</Button>
        </div>
      )}
      {adding && (
        <Panel title="New directory company">
          <CompanyForm
            initial={EMPTY_WRITE}
            submitLabel="Add to directory"
            onSubmit={async (body) => {
              await api("/admin/insurer-companies", {
                method: "POST",
                body: JSON.stringify(body),
              });
              setAdding(false);
              void refresh();
            }}
            onCancel={() => setAdding(false)}
          />
        </Panel>
      )}
      {editing && (
        <Panel title={`Edit ${editing.name}`}>
          <CompanyForm
            initial={{
              name: editing.name,
              website: editing.website,
              phones: editing.phones.map((p) => ({ ...p })),
              address: editing.address,
              notes: editing.notes,
            }}
            submitLabel="Save changes"
            onSubmit={async (body) => {
              await api(`/admin/insurer-companies/${editing.id}`, {
                method: "PUT",
                body: JSON.stringify(body),
              });
              setEditing(null);
              void refresh();
            }}
            onCancel={() => setEditing(null)}
          />
        </Panel>
      )}

      {companies === null ? (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> Loading…
        </p>
      ) : companies.length === 0 && !adding ? (
        <EmptyState
          title="No directory companies yet"
          description="The insurer directory starts empty by design. Add the first real insurer above."
        />
      ) : companies.length > 0 ? (
        /* True list (list standard, Wave 3): one company per row
         * on the shared admin DataTable, mirroring the dealer
         * directory — company · phone · website · address ·
         * actions. Notes are not a row fact: they live in the
         * row's own Edit form, one click away. The website stays
         * a real link and the copy buttons ride their cells, as
         * the panels had them. */
        <div className="tv-table-min">
          <DataTable<InsurerCompany>
            columns={[
              {
                key: "company",
                header: t("admin.directory.col.company"),
                sortable: true,
                sortValue: (c) => c.name,
                render: (c) => <strong>{c.name}</strong>,
              },
              {
                key: "phone",
                header: t("admin.directory.col.phone"),
                render: (c) =>
                  c.phones.length === 0 ? (
                    "—"
                  ) : (
                    <span className="tv-cell-stack">
                      {c.phones.map((phone, i) => (
                        <span key={i} className="tv-cell-nowrap">
                          {phone.label ? `${phone.label}: ` : ""}
                          {phone.number}{" "}
                          <CopyButton text={phone.number} label="Copy" />
                        </span>
                      ))}
                    </span>
                  ),
              },
              {
                key: "website",
                header: t("admin.directory.col.website"),
                render: (c) =>
                  c.website ? (
                    <span className="tv-cell-ellipsis" title={c.website}>
                      <a href={c.website} target="_blank" rel="noreferrer">
                        {c.website}
                      </a>
                    </span>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "address",
                header: t("admin.directory.col.address"),
                render: (c) =>
                  c.address ? (
                    <span className="tv-cell-actions">
                      <span className="tv-cell-ellipsis" title={c.address}>
                        {c.address}
                      </span>
                      <CopyButton text={c.address} label="Copy" />
                    </span>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "actions",
                header: t("admin.directory.col.actions"),
                render: (c) => (
                  <span className="tv-cell-actions">
                    <Button size="sm" variant="secondary" onClick={() => setEditing(c)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => void remove(c)}>
                      Remove
                    </Button>
                  </span>
                ),
              },
            ]}
            rows={companies}
            rowKey={(c) => c.id}
          />
        </div>
      ) : null}

      <AffiliationsReview onError={setError} />
    </AdminShell>
  );
}

function AffiliationsReview({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const [rows, setRows] = useState<AffiliationAdmin[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setRows(await api<AffiliationAdmin[]>("/admin/insurer-affiliations"));
  }, []);

  useEffect(() => {
    refresh().catch(() => setRows([]));
  }, [refresh]);

  async function toggle(row: AffiliationAdmin) {
    setBusyId(row.id);
    try {
      const updated = await api<AffiliationAdmin>(
        `/admin/insurer-affiliations/${row.id}/verified`,
        { method: "PUT", body: JSON.stringify({ verified: !row.verified }) },
      );
      setRows((prev) => (prev ?? []).map((r) => (r.id === updated.id ? updated : r)));
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Couldn't update the verification.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Panel title="Insurer affiliations" variant="plate">
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        Insurance-group users link themselves to a directory
        company. A link is self-asserted until you verify it — only
        verified affiliations can open the Policyholders view.
      </p>
      {rows === null ? (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> Loading…
        </p>
      ) : rows.length === 0 ? (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          No insurer has claimed a company yet.
        </p>
      ) : (
        <div style={{ display: "grid", gap: "0.5rem" }}>
          {rows.map((row) => (
            <div
              key={row.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: "1rem",
                flexWrap: "wrap",
                alignItems: "center",
              }}
            >
              <p style={{ margin: 0 }}>
                <strong>{row.user_name}</strong>{" "}
                <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                  {row.user_account_number} · {row.user_email}
                </span>{" "}
                → <strong>{row.company_name}</strong>
                {row.role_at_company && ` (${row.role_at_company})`}{" "}
                {row.verified ? (
                  <Badge tone="success">Verified</Badge>
                ) : (
                  <Badge tone="neutral">Unverified</Badge>
                )}
              </p>
              <Button
                size="sm"
                variant="secondary"
                loading={busyId === row.id}
                onClick={() => void toggle(row)}
              >
                {row.verified ? "Unverify" : "Verify"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
