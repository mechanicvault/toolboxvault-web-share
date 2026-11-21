import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Badge,
  Button,
  DataTable,
  DatePicker,
  EmptyState,
  FormField,
  Panel,
  Select,
  Spinner,
  TextInput,
  useToast,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { useT } from "../../../i18n/LocaleContext";
import { AdminShell } from "./AdminShell";
import { DurationPicker, ONE_MONTH, type DurationChoice } from "./DurationPicker";

/**
 * Admin → Promos (Phase A2): redeem codes, run from the panel.
 * Creating a code writes one database row and the code is live
 * IMMEDIATELY — no deploy, no restart (the create → redeem path is
 * pinned by tests). The list shows live redemption counts, and the
 * activity panel shows who redeemed what, when.
 */

interface CodeView {
  id: string;
  code: string;
  kind: string;
  amount: number;
  plan_key: string;
  max_redemptions: number | null;
  redemptions: number;
  expires_at: string | null;
  active: boolean;
  created_at: string;
}

interface RedemptionView {
  id: string;
  code: string;
  user_id: string;
  user_email: string;
  user_name: string;
  redeemed_at: string;
}

/** List labels for every kind a row can carry — including
 * trial_days, which nothing creates anymore (admin durations
 * are months, owner 2026-10-22) but old rows must still read
 * sanely. */
const KIND_OPTIONS = [
  { value: "free_months", label: "Free months" },
  { value: "free_year", label: "Free year" },
  { value: "lifetime", label: "Lifetime" },
  { value: "ai_credits", label: "AI credits" },
  { value: "trial_months", label: "Trial months" },
  { value: "trial_days", label: "Trial days" },
];

/** What the create form offers — the DURATION PICKER turns the
 * choice into a concrete code kind + amount at submit:
 *   free time  → free_months (1–11 / custom months) |
 *                free_year (the "1 year" preset) | lifetime
 *   trial      → trial_months (months; "1 year" = 12)
 *   ai_credits → ai_credits (amount = credits)              */
const GIVE_OPTIONS = [
  { value: "free_time", label: "Free time" },
  { value: "trial", label: "Trial" },
  { value: "ai_credits", label: "AI credits" },
];
const PLAN_OPTIONS = [
  { value: "pro", label: "Pro" },
  { value: "business", label: "Business" },
  { value: "free", label: "Free" },
];

function kindLabel(kind: string): string {
  return KIND_OPTIONS.find((o) => o.value === kind)?.label ?? kind;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function PromosSection() {
  const { toast } = useToast();
  const tt = useT();
  const [codes, setCodes] = useState<CodeView[] | null>(null);
  const [redemptions, setRedemptions] = useState<RedemptionView[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [codeText, setCodeText] = useState("");
  const [give, setGive] = useState("free_time");
  const [duration, setDuration] = useState<DurationChoice>(ONE_MONTH);
  const [credits, setCredits] = useState("100");
  const [planKey, setPlanKey] = useState("pro");
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [codeRows, redemptionRows] = await Promise.all([
        api<CodeView[]>("/admin/codes"),
        api<RedemptionView[]>("/admin/redemptions?limit=20"),
      ]);
      setCodes(codeRows);
      setRedemptions(redemptionRows);
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load promo codes.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Picker → concrete code kind + amount (the mapping the
   *  duration-picker brief pins). */
  function codePayload(): { kind: string; amount: number } {
    if (give === "ai_credits") {
      return { kind: "ai_credits", amount: Number(credits) || 0 };
    }
    if (give === "trial") {
      return { kind: "trial_months", amount: duration.months };
    }
    if (duration.lifetime) return { kind: "lifetime", amount: 0 };
    if (duration.oneYear) return { kind: "free_year", amount: 0 };
    return { kind: "free_months", amount: duration.months };
  }

  async function createCode(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await api<CodeView>("/admin/codes", {
        method: "POST",
        body: JSON.stringify({
          code: codeText.trim(),
          ...codePayload(),
          plan_key: planKey,
          max_redemptions: maxRedemptions ? Number(maxRedemptions) : null,
          expires_at: expiresOn ? new Date(`${expiresOn}T23:59:59`).toISOString() : null,
        }),
      });
      toast(`Code ${codeText.trim().toUpperCase()} is live now.`, {
        tone: "success",
        duration: 8000,
      });
      setCodeText("");
      setMaxRedemptions("");
      setExpiresOn("");
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't create that code.",
        { tone: "danger" },
      );
    } finally {
      setCreating(false);
    }
  }

  async function deactivate(row: CodeView) {
    if (!window.confirm(tt("admin.confirm.promoDeactivate").replace("{code}", row.code))) return;
    setBusyId(row.id);
    try {
      await api<CodeView>(`/admin/codes/${row.id}/deactivate`, { method: "POST" });
      toast(`Code ${row.code} deactivated.`, { tone: "success", duration: 8000 });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't deactivate that code.",
        { tone: "danger" },
      );
    } finally {
      setBusyId(null);
    }
  }

  const codeColumns: Column<CodeView>[] = [
    { key: "code", header: "Code", sortable: true, sortValue: (row) => row.code, render: (row) => <strong>{row.code}</strong> },
    { key: "kind", header: "Kind", render: (row) => kindLabel(row.kind) },
    {
      key: "amount",
      header: "Amount / plan",
      render: (row) => {
        if (row.kind === "ai_credits") return `${row.amount} credits`;
        if (row.kind === "free_months" || row.kind === "trial_months")
          return `${row.amount} mo · ${row.plan_key}`;
        if (row.kind === "trial_days") return `${row.amount} d · ${row.plan_key}`;
        return row.plan_key;
      },
    },
    {
      key: "redemptions",
      header: "Redeemed",
      render: (row) =>
        `${row.redemptions}${row.max_redemptions ? ` / ${row.max_redemptions}` : ""}`,
    },
    { key: "expires", header: "Expires", render: (row) => formatDateTime(row.expires_at) },
    {
      key: "status",
      header: "Status",
      render: (row) =>
        row.active ? (
          <Badge tone="success">Live</Badge>
        ) : (
          <Badge tone="neutral">Deactivated</Badge>
        ),
    },
    {
      key: "actions",
      header: "",
      render: (row) =>
        row.active ? (
          <Button
            size="sm"
            variant="secondary"
            loading={busyId === row.id}
            onClick={() => void deactivate(row)}
          >
            Deactivate
          </Button>
        ) : null,
    },
  ];

  const redemptionColumns: Column<RedemptionView>[] = [
    { key: "code", header: "Code", sortable: true, sortValue: (row) => row.code, render: (row) => <strong>{row.code}</strong> },
    {
      key: "user",
      header: "Redeemed by",
      render: (row) => row.user_name || row.user_email,
    },
    { key: "email", header: "Email", render: (row) => row.user_email },
    { key: "when", header: "When", sortable: true, sortValue: (row) => row.redeemed_at, render: (row) => formatDateTime(row.redeemed_at) },
  ];

  return (
    <AdminShell>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <Panel title="Create a code">
          <form onSubmit={createCode} style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
              <FormField label="Code">
                <TextInput
                  value={codeText}
                  onChange={(e) => setCodeText(e.target.value)}
                  placeholder="e.g. LAUNCH50"
                  required
                />
              </FormField>
              <FormField label="Gives">
                <Select value={give} onChange={(e) => setGive(e.target.value)}>
                  {GIVE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </Select>
              </FormField>
              {give === "ai_credits" ? (
                <FormField label="Credits">
                  <TextInput
                    type="number"
                    min={1}
                    value={credits}
                    onChange={(e) => setCredits(e.target.value)}
                    style={{ width: "7rem" }}
                  />
                </FormField>
              ) : (
                <FormField label="Duration" htmlFor="promo-duration">
                  <DurationPicker
                    id="promo-duration"
                    value={duration}
                    onChange={setDuration}
                    allowLifetime={give === "free_time"}
                  />
                </FormField>
              )}
              {give !== "ai_credits" && (
                <FormField label="Plan">
                  <Select value={planKey} onChange={(e) => setPlanKey(e.target.value)}>
                    {PLAN_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </Select>
                </FormField>
              )}
              <FormField label="Max redemptions (optional)">
                <TextInput
                  type="number"
                  min={1}
                  value={maxRedemptions}
                  onChange={(e) => setMaxRedemptions(e.target.value)}
                  style={{ width: "8rem" }}
                />
              </FormField>
              <FormField label="Expires on (optional)">
                <DatePicker
                  value={expiresOn}
                  onChange={setExpiresOn}
                  clearable
                />
              </FormField>
            </div>
            <div>
              <Button type="submit" loading={creating}>
                Create code — live immediately
              </Button>
            </div>
          </form>
        </Panel>

        <Panel title="Codes">
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {loadError && <Alert tone="danger">{loadError}</Alert>}
            {!codes && !loadError && (
              <p style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", margin: 0 }}>
                <Spinner size="sm" /> Loading codes…
              </p>
            )}
            {codes && (
              <DataTable
                columns={codeColumns}
                rows={codes}
                rowKey={(row) => row.id}
                emptyState={
                  <EmptyState
                    title="No codes yet"
                    description="Create the first one above — it will be redeemable the moment it exists."
                  />
                }
              />
            )}
          </div>
        </Panel>

        <Panel title="Recent redemptions">
          {redemptions && (
            <DataTable
              columns={redemptionColumns}
              rows={redemptions}
              rowKey={(row) => row.id}
              emptyState={
                <EmptyState
                  title="No redemptions yet"
                  description="When someone redeems a code, it shows up here."
                />
              }
            />
          )}
        </Panel>
      </div>
    </AdminShell>
  );
}

export default function AdminPromosPage() {
  return (
    <RequireAuth>
      <PromosSection />
    </RequireAuth>
  );
}
