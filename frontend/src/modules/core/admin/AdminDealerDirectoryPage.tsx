import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  CopyButton,
  DataTable,
  EmptyState,
  Panel,
  Spinner,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { ApiError } from "../../../lib/api";
import {
  createDirectoryCompany,
  deleteDirectoryCompany,
  listDirectoryAdmin,
  listRepresentationsAdmin,
  setRepresentationVerified,
  updateDirectoryCompany,
} from "../../dealers/api";
import {
  CompanyForm,
  companyToWrite,
  EMPTY_COMPANY,
} from "../../dealers/components/CompanyForm";
import { CompanyLogo } from "../../dealers/components/CompanyLogo";
import type {
  DealerCompany,
  RepresentationAdmin,
} from "../../dealers/types";
import { AdminShell } from "./AdminShell";

/**
 * Operator surface for the platform dealer directory (dealers
 * module): the companies every user can browse and tag items with.
 * Only publicly listed corporate contact data belongs here — never
 * an invented department number (owner rule, 2026-10-18).
 */
export default function AdminDealerDirectoryPage() {
  const t = useT();
  const [companies, setCompanies] = useState<DealerCompany[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<DealerCompany | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const rows = await listDirectoryAdmin();
    setCompanies(rows);
  }, []);

  useEffect(() => {
    refresh().catch((err) =>
      setError(err instanceof ApiError ? err.message : "Couldn't load the directory."),
    );
  }, [refresh]);

  async function remove(company: DealerCompany) {
    if (!window.confirm(`Remove "${company.name}" from the directory? Items tagged with it lose the displayed tag (their data is otherwise untouched).`)) return;
    setError("");
    try {
      await deleteDirectoryCompany(company.id);
      void refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the company.");
    }
  }

  return (
    <AdminShell>
      {/* 09b-F4: the section heading wears the same Panel title
          treatment as every other Admin section — no bare
          sentence-case heading floating on the page background. */}
      <Panel title="Dealer directory" style={{ marginBottom: "var(--spacing)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          The platform directory every user browses on the Dealers page
          and picks from when tagging an item. Keep contacts to publicly
          listed corporate data.
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
            initial={EMPTY_COMPANY}
            submitLabel="Add to directory"
            onSubmit={async (body) => {
              await createDirectoryCompany(body);
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
            initial={companyToWrite(editing)}
            submitLabel="Save changes"
            onSubmit={async (body) => {
              await updateDirectoryCompany(editing.id, body);
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
          description="The dealer directory starts empty by design. Add the first real dealer above — it appears on the Dealers page for every user."
        />
      ) : companies.length > 0 ? (
        /* True list (list standard, Wave 3): one company per row
         * on the shared admin DataTable (the Users-table pattern) —
         * company · kind · phone · email · website · address ·
         * warranty · actions. The detail prose that used to stack
         * inside a panel per company — directory notes, ship-to,
         * the warranty gate and process notes — is NOT a row fact:
         * every one of those fields lives in the row's own Edit
         * form (CompanyForm carries them all), one click away.
         * Copy buttons ride the cells they copy from, as before. */
        <div className="tv-table-min-lg">
          <DataTable<DealerCompany>
            columns={[
              {
                key: "company",
                header: t("admin.directory.col.company"),
                sortable: true,
                sortValue: (c) => c.name,
                render: (c) => (
                  <span className="tv-cell-actions">
                    <CompanyLogo company={c} width={66} height={28} />
                    <strong>{c.name}</strong>
                  </span>
                ),
              },
              {
                key: "kind",
                header: t("admin.directory.col.kind"),
                sortable: true,
                sortValue: (c) => c.kind,
                render: (c) => c.kind,
              },
              {
                key: "phone",
                header: t("admin.directory.col.phone"),
                render: (c) =>
                  c.phones.length === 0 ? (
                    "—"
                  ) : (
                    <span className="tv-cell-stack">
                      {c.phones.map((phone) => (
                        <span
                          key={`${phone.label}-${phone.number}`}
                          className="tv-cell-nowrap"
                        >
                          <span className="tv-muted">{phone.label}: </span>
                          {phone.number}{" "}
                          <CopyButton
                            text={phone.number}
                            ariaLabel={`Copy ${phone.label} phone number`}
                          />
                        </span>
                      ))}
                    </span>
                  ),
              },
              {
                key: "email",
                header: t("admin.directory.col.email"),
                render: (c) => c.email || "—",
              },
              {
                key: "website",
                header: t("admin.directory.col.website"),
                render: (c) =>
                  c.website ? (
                    <span className="tv-cell-ellipsis" title={c.website}>
                      {c.website}
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
                      <CopyButton
                        text={c.address}
                        label="Copy address"
                        ariaLabel="Copy company address"
                      />
                    </span>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "warranty",
                header: t("admin.directory.col.warranty"),
                render: (c) =>
                  c.warranty_url || c.warranty_phone ? (
                    <span className="tv-cell-stack">
                      {c.warranty_url && (
                        <span className="tv-cell-ellipsis" title={c.warranty_url}>
                          {c.warranty_url}
                        </span>
                      )}
                      {c.warranty_phone && (
                        <span className="tv-cell-nowrap">
                          {c.warranty_phone}{" "}
                          <CopyButton
                            text={c.warranty_phone}
                            ariaLabel="Copy warranty phone number"
                          />
                        </span>
                      )}
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
      <RepresentationsReview onError={setError} />
    </AdminShell>
  );
}

/**
 * Representation review (dealer portal): agents self-assert the
 * companies they represent; an operator verifies the claim. The
 * verified badge renders everywhere the agent appears. Verify and
 * unverify are audited server-side.
 */
function RepresentationsReview({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const [rows, setRows] = useState<RepresentationAdmin[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const data = await listRepresentationsAdmin();
    setRows(data);
  }, []);

  useEffect(() => {
    refresh().catch(() => setRows([]));
  }, [refresh]);

  async function toggle(row: RepresentationAdmin) {
    setBusyId(row.id);
    try {
      const updated = await setRepresentationVerified(row.id, !row.verified);
      setRows((prev) =>
        (prev ?? []).map((r) => (r.id === updated.id ? updated : r)),
      );
    } catch (err) {
      onError(
        err instanceof ApiError ? err.message : "Couldn't update the verification.",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Panel title="Agent representations" variant="plate">
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        Dealer-group users link themselves to directory companies.
        A link is self-asserted until you verify it — verified agents
        get the Verified badge on the company's page.
      </p>
      {rows === null ? (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> Loading…
        </p>
      ) : rows.length === 0 ? (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          No agent has claimed a company yet.
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
                <strong>{row.agent_name}</strong>{" "}
                <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                  {row.agent_account_number} · {row.agent_email}
                </span>{" "}
                → <strong>{row.company_name}</strong>{" "}
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
