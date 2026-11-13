import { useCallback, useEffect, useState, type CSSProperties } from "react";

import {
  Alert,
  Badge,
  Button,
  DataTable,
  EmptyState,
  FormField,
  Modal,
  Pagination,
  Panel,
  SearchBar,
  Select,
  Spinner,
  TextInput,
  Toggle,
  useToast,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { accountTypeLabel, type AccountType } from "../accountTypes";
import {
  markerTitle,
  markerWhen,
  type JournalEntry,
  type RestoreMarker,
  type RestoreResult,
} from "../history";
import { useAuth } from "../AuthContext";
import { RequireAuth } from "../auth/RequireAuth";
import { useT } from "../../../i18n/LocaleContext";
import { AdminShell } from "./AdminShell";
import { DurationPicker, ONE_MONTH, type DurationChoice } from "./DurationPicker";

/**
 * Admin → Users (Phase A2): the operator directory. Search by name,
 * email, or account number; open an account for its full picture
 * (profile, groups, entitlement with its source, AI wallet,
 * sessions, referrals) and every God-mode action: grant/revoke
 * operator, start a trial, grant a free period, grant AI credits,
 * set the community role, deactivate/reactivate. Every action posts
 * to /api/admin/users/* and the panel re-renders from the server's
 * answer; the backend writes the audit row.
 */

interface AdminUserSummary {
  id: string;
  account_number: string;
  name: string;
  email: string;
  account_types: string[];
  plan_key: string;
  plan_name: string;
  is_operator: boolean;
  role: string;
  /** Account tier (2026-10-31): the rung the account sits on
   *  (normal | moderator | moderator_admin | god) plus the
   *  stackable beta flag. The tier drives role server-side. */
  tier: string;
  beta_tester: boolean;
  is_active: boolean;
  created_at: string;
}

interface AdminUserDetail extends AdminUserSummary {
  email_verified: boolean;
  referred_by_id: string | null;
  entitlement: {
    plan_key: string;
    plan_name: string;
    source: string;
    is_paid: boolean;
    status: string | null;
    current_period_end: string | null;
    trial_end: string | null;
    grace_until: string | null;
  };
  wallet: { allowance_balance: number; banked_balance: number };
  session_count: number;
  referral_count: number;
}

interface UserPage {
  items: AdminUserSummary[];
  total: number;
  limit: number;
  offset: number;
}

const PAGE_SIZE = 25;
const PLAN_OPTIONS = [
  { value: "pro", label: "Pro" },
  { value: "business", label: "Business" },
  { value: "free", label: "Free" },
];
/** Account tiers (2026-10-31): the rungs an admin may SET. God is
 *  deliberately absent — the god rung is never granted or removed
 *  from this panel; it exists only as a display state. */
const TIER_OPTIONS = [
  { value: "downloads", label: "Downloads" },
  { value: "normal", label: "User" },
  { value: "moderator", label: "Moderator" },
  { value: "moderator_admin", label: "Moderator admin" },
];

function tierLabel(tier: string): string {
  if (tier === "god") return "God";
  return TIER_OPTIONS.find((o) => o.value === tier)?.label ?? tier;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Muted helper note under a control (module-level so the page
 *  adds no new inline style literals). */
const MUTED_NOTE_STYLE: CSSProperties = {
  color: "var(--text-muted)",
  fontSize: "var(--font-size-sm)",
};

/** Stack + label for a toggle field (same story as above). */
const TOGGLE_STACK_STYLE: CSSProperties = {
  display: "grid",
  gap: "var(--space-1)",
};
const FIELD_LABEL_STYLE: CSSProperties = { fontWeight: 600 };

// -- history & restore (audit trail, operator on-behalf) -------------------------

interface AdminUserHistory {
  markers: RestoreMarker[];
  entries: JournalEntry[];
  entries_total: number;
}

function UserHistoryBlock({ userId }: { userId: string }) {
  const { toast } = useToast();
  const [data, setData] = useState<AdminUserHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(
        await api<AdminUserHistory>(`/admin/users/${userId}/history?limit=25`),
      );
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't load the history.",
      );
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function createMarker() {
    setBusy("marker");
    try {
      await api(`/admin/users/${userId}/history/markers`, {
        method: "POST",
        body: JSON.stringify({ label: "" }),
      });
      toast("Restore point saved for this account.", { tone: "success" });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save a restore point.",
        { tone: "danger" },
      );
    } finally {
      setBusy(null);
    }
  }

  async function restore(marker: RestoreMarker) {
    setBusy(`restore-${marker.id}`);
    try {
      const result = await api<RestoreResult>(
        `/admin/users/${userId}/history/restore`,
        {
          method: "POST",
          body: JSON.stringify({ marker_id: marker.id }),
        },
      );
      setConfirmId(null);
      toast(
        `Account restored to “${markerTitle(marker)}”: ${result.restored} change` +
          `${result.restored === 1 ? "" : "s"} undone, ${result.not_changed} shared ` +
          `record${result.not_changed === 1 ? "" : "s"} left as they were.`,
        { tone: "success", duration: 8000 },
      );
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : "The restore didn't go through — nothing was changed.",
        { tone: "danger" },
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-2)" }}>
      <div
        style={{
          display: "flex",
          gap: "var(--space-2)",
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <p style={{ fontWeight: 700, margin: 0, flex: "1 1 auto" }}>
          History &amp; restore
        </p>
        <Button
          size="sm"
          variant="secondary"
          loading={busy === "marker"}
          onClick={() => void createMarker()}
        >
          Create restore point
        </Button>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {!data && !error && (
        <p style={{ margin: 0, color: "var(--text-muted)" }}>Loading history…</p>
      )}
      {data && data.markers.length === 0 && (
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          No restore points yet — this account's history starts at
          its baseline.
        </p>
      )}
      {data &&
        data.markers.map((marker) => (
          <div
            key={marker.id}
            style={{
              display: "grid",
              gap: "var(--space-1)",
              borderTop: "1px solid var(--edge)",
              paddingTop: "var(--space-2)",
            }}
          >
            <div
              style={{
                display: "flex",
                gap: "var(--space-2)",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span style={{ fontWeight: 600, flex: "1 1 10rem", minWidth: 0 }}>
                {markerTitle(marker)}
              </span>
              <span
                style={{
                  color: "var(--text-muted)",
                  fontSize: "var(--font-size-sm)",
                }}
              >
                {markerWhen(marker.created_at)}
              </span>
              {confirmId !== marker.id && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setConfirmId(marker.id)}
                >
                  Restore
                </Button>
              )}
            </div>
            {confirmId === marker.id && (
              <div
                style={{
                  display: "flex",
                  gap: "var(--space-2)",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <span style={{ flex: "1 1 14rem", minWidth: 0 }}>
                  Restore this account to this point? Every change
                  after it is undone; shared records stay. A
                  pre-restore point is saved first, and the action
                  is written to the audit log.
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  loading={busy === `restore-${marker.id}`}
                  onClick={() => void restore(marker)}
                >
                  Yes, restore
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmId(null)}
                >
                  Cancel
                </Button>
              </div>
            )}
          </div>
        ))}
      {data && data.entries.length > 0 && (
        <div style={{ display: "grid", gap: "var(--space-1)" }}>
          <p
            style={{
              color: "var(--text-muted)",
              fontSize: "var(--font-size-sm)",
              fontWeight: 700,
              margin: "var(--space-2) 0 0",
            }}
          >
            Recent activity ({data.entries_total} total)
          </p>
          {data.entries.slice(0, 10).map((entry) => (
            <div
              key={entry.id}
              style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}
            >
              <span>{entry.label}</span>
              {!entry.restorable && entry.action !== "restore" && (
                <span
                  style={{
                    color: "var(--text-muted)",
                    fontSize: "var(--font-size-sm)",
                  }}
                >
                  shared — not rewound
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// -- the detail drawer ---------------------------------------------------------

function UserDetailModal({
  userId,
  onClose,
  onChanged,
}: {
  userId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const tt = useT();
  const { user: me } = useAuth();
  const [tierNonce, setTierNonce] = useState(0);
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [trialPlan, setTrialPlan] = useState("pro");
  const [trialDuration, setTrialDuration] = useState<DurationChoice>(ONE_MONTH);
  const [freePlan, setFreePlan] = useState("pro");
  const [freeDuration, setFreeDuration] = useState<DurationChoice>(ONE_MONTH);
  const [creditAmount, setCreditAmount] = useState("100");
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await api<AdminUserDetail>(`/admin/users/${userId}`));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load this account.",
      );
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(
    key: string,
    path: string,
    body: unknown,
    success: string,
  ): Promise<void> {
    setBusy(key);
    try {
      const updated = await api<AdminUserDetail>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setDetail(updated);
      onChanged();
      toast(success, { tone: "success", duration: 8000 });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "That action didn't go through.",
        { tone: "danger" },
      );
    } finally {
      setBusy(null);
    }
  }

  const isSelf = detail !== null && me !== null && detail.id === me.id;

  return (
    <Modal open onClose={onClose} title={detail ? detail.name || detail.email : "Account"} size="lg">
      {loadError && <Alert tone="danger">{loadError}</Alert>}
      {!detail && !loadError && (
        <p style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", margin: 0 }}>
          <Spinner size="sm" /> Loading account…
        </p>
      )}
      {detail && (
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {detail.is_operator && <Badge tone="accent">Operator</Badge>}
            <Badge tone="neutral">{tierLabel(detail.tier)}</Badge>
            {detail.beta_tester && <Badge tone="accent">Beta tester</Badge>}
            <Badge tone={detail.is_active ? "success" : "danger"}>
              {detail.is_active ? "Active" : "Deactivated"}
            </Badge>
            <Badge tone="neutral">{detail.entitlement.plan_name}</Badge>
          </div>

          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: "var(--space-2) var(--space-4)",
              margin: 0,
            }}
          >
            {[
              ["Email", detail.email],
              ["Account number", detail.account_number],
              ["Groups", detail.account_types.map((t) => accountTypeLabel(t as AccountType)).join(", ") || "Not chosen yet"],
              ["Joined", formatDate(detail.created_at)],
              ["Email verified", detail.email_verified ? "Yes" : "No"],
              ["Plan source", detail.entitlement.source ? detail.entitlement.source.charAt(0).toUpperCase() + detail.entitlement.source.slice(1) : detail.entitlement.source],
              ["Period end", formatDate(detail.entitlement.current_period_end ?? detail.entitlement.trial_end)],
              ["AI credits — allowance", String(detail.wallet.allowance_balance)],
              ["AI credits — banked", String(detail.wallet.banked_balance)],
              ["Live sessions", String(detail.session_count)],
              ["Referrals", String(detail.referral_count)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>{label}</dt>
                <dd style={{ margin: 0, fontWeight: 600 }}>{value}</dd>
              </div>
            ))}
          </dl>

          <div
            style={{
              borderTop: "1px solid var(--edge)",
              paddingTop: "var(--space-3)",
              display: "grid",
              gap: "var(--space-4)",
            }}
          >
            <div style={{ display: "grid", gap: "var(--space-2)" }}>
              <p style={{ fontWeight: 700, margin: 0 }}>Start a trial</p>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "end" }}>
                <FormField label="Plan">
                  <Select value={trialPlan} onChange={(e) => setTrialPlan(e.target.value)}>
                    {PLAN_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="Duration" htmlFor="user-trial-duration">
                  <DurationPicker
                    id="user-trial-duration"
                    value={trialDuration}
                    onChange={setTrialDuration}
                    allowLifetime={false}
                  />
                </FormField>
                <Button
                  size="sm"
                  loading={busy === "trial"}
                  onClick={() =>
                    void act(
                      "trial",
                      `/admin/users/${detail.id}/trial`,
                      { plan_key: trialPlan, months: trialDuration.months },
                      "Trial started.",
                    )
                  }
                >
                  Start trial
                </Button>
              </div>
            </div>

            <div style={{ display: "grid", gap: "var(--space-2)" }}>
              <p style={{ fontWeight: 700, margin: 0 }}>Grant a free period</p>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "end" }}>
                <FormField label="Plan">
                  <Select value={freePlan} onChange={(e) => setFreePlan(e.target.value)}>
                    {PLAN_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="Duration" htmlFor="user-free-duration">
                  <DurationPicker
                    id="user-free-duration"
                    value={freeDuration}
                    onChange={setFreeDuration}
                  />
                </FormField>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busy === "free"}
                  onClick={() =>
                    void act(
                      "free",
                      `/admin/users/${detail.id}/free-period`,
                      freeDuration.lifetime
                        ? { plan_key: freePlan, lifetime: true }
                        : { plan_key: freePlan, months: freeDuration.months },
                      "Free period granted.",
                    )
                  }
                >
                  Grant free period
                </Button>
              </div>
            </div>

            <div style={{ display: "grid", gap: "var(--space-2)" }}>
              <p style={{ fontWeight: 700, margin: 0 }}>Grant AI credits</p>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "end" }}>
                <FormField label="Credits (banked; they persist)">
                  <TextInput
                    type="number"
                    min={1}
                    value={creditAmount}
                    onChange={(e) => setCreditAmount(e.target.value)}
                    style={{ width: "8rem" }}
                  />
                </FormField>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busy === "credits"}
                  onClick={() =>
                    void act(
                      "credits",
                      `/admin/users/${detail.id}/ai-credits`,
                      { amount: Number(creditAmount) || 0 },
                      "AI credits granted.",
                    )
                  }
                >
                  Grant credits
                </Button>
              </div>
            </div>

            <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
              <FormField label="Account tier">
                {detail.tier === "god" ? (
                  <>
                    <Select value="god" disabled>
                      <option value="god">God</option>
                    </Select>
                    <span style={MUTED_NOTE_STYLE}>
                      The God rung is never granted or removed here — only the God
                      account itself can edit this account.
                    </span>
                  </>
                ) : (
                  <Select
                    key={tierNonce}
                    value={detail.tier}
                    disabled={busy === "tier" || isSelf}
                    onChange={(e) => {
                      /* A privilege change confirms first; declining
                       * remounts the select on the stored tier so the
                       * control never lies (the F2-15 pattern). The
                       * server enforces the grant rules — who may set
                       * Moderator Admin, no self-changes — and its
                       * refusal surfaces as the toast. */
                      const nextTier = e.target.value;
                      const label = tierLabel(nextTier);
                      if (!window.confirm(tt("admin.confirm.tierChange").replace("{name}", detail.name || detail.email).replace("{tier}", label))) {
                        setTierNonce((n) => n + 1);
                        return;
                      }
                      void act(
                        "tier",
                        `/admin/users/${detail.id}/tier`,
                        { tier: nextTier },
                        "Account tier updated.",
                      );
                    }}
                  >
                    {TIER_OPTIONS.map((o) => (
                      <option
                        key={o.value}
                        value={o.value}
                        disabled={o.value === "moderator_admin" && me?.tier !== "god"}
                      >
                        {o.label}
                      </option>
                    ))}
                  </Select>
                )}
                {isSelf && detail.tier !== "god" && (
                  <span style={MUTED_NOTE_STYLE}>
                    You can't change your own account tier.
                  </span>
                )}
              </FormField>
              <div style={TOGGLE_STACK_STYLE}>
                <span style={FIELD_LABEL_STYLE}>Beta tester</span>
                <Toggle
                  checked={detail.beta_tester}
                  disabled={busy === "beta" || isSelf}
                  label={detail.beta_tester ? "Beta tester" : "Not a beta tester"}
                  onChange={(enabled) => {
                    if (!window.confirm(tt(enabled ? "admin.confirm.betaOn" : "admin.confirm.betaOff").replace("{name}", detail.name || detail.email))) return;
                    void act(
                      "beta",
                      `/admin/users/${detail.id}/beta`,
                      { beta_tester: enabled },
                      enabled ? "Beta tester access granted." : "Beta tester access removed.",
                    );
                  }}
                />
                <span style={MUTED_NOTE_STYLE}>
                  Early access to anything lit for the beta tier.
                </span>
              </div>
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span style={{ fontWeight: 600 }}>Operator (God access)</span>
                <Toggle
                  checked={detail.is_operator}
                  disabled={busy === "operator" || (isSelf && detail.is_operator)}
                  label={detail.is_operator ? "Operator" : "Not an operator"}
                  onChange={(enabled) => {
                    if (!window.confirm(tt(enabled ? "admin.confirm.operatorGrant" : "admin.confirm.operatorRevoke").replace("{name}", detail.name || detail.email))) return;
                    void act(
                      "operator",
                      `/admin/users/${detail.id}/operator`,
                      { is_operator: enabled },
                      enabled ? "Operator access granted." : "Operator access revoked.",
                    );
                  }}
                />
                {isSelf && detail.is_operator && (
                  <span style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>
                    You can't revoke your own operator access.
                  </span>
                )}
              </div>
            </div>

            <div
              style={{
                borderTop: "1px solid var(--edge)",
                paddingTop: "var(--space-3)",
              }}
            >
              <UserHistoryBlock userId={detail.id} />
            </div>

            <div
              style={{
                borderTop: "1px solid var(--edge)",
                paddingTop: "var(--space-3)",
                display: "flex",
                gap: "var(--space-2)",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              {detail.is_active ? (
                confirmDeactivate ? (
                  <>
                    <span>
                      Deactivate this account? Sign-in stops and sessions end.
                      Nothing is deleted — reactivation restores it.
                    </span>
                    <Button
                      size="sm"
                      variant="danger"
                      loading={busy === "deactivate"}
                      onClick={() =>
                        void act(
                          "deactivate",
                          `/admin/users/${detail.id}/deactivate`,
                          {},
                          "Account deactivated.",
                        ).then(() => setConfirmDeactivate(false))
                      }
                    >
                      Yes, deactivate
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmDeactivate(false)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={isSelf}
                    onClick={() => setConfirmDeactivate(true)}
                  >
                    Deactivate account
                  </Button>
                )
              ) : (
                <Button
                  size="sm"
                  loading={busy === "reactivate"}
                  onClick={() =>
                    void act(
                      "reactivate",
                      `/admin/users/${detail.id}/reactivate`,
                      {},
                      "Account reactivated.",
                    )
                  }
                >
                  Reactivate account
                </Button>
              )}
              {isSelf && detail.is_active && (
                <span style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>
                  You can't deactivate your own account.
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

// -- the directory ---------------------------------------------------------------

function UsersSection() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<UserPage | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(query);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
      });
      if (debounced.trim()) params.set("q", debounced.trim());
      setData(await api<UserPage>(`/admin/users?${params.toString()}`));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load the user directory.",
      );
    }
  }, [debounced, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: Column<AdminUserSummary>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      sortValue: (row) => row.name || row.email,
      render: (row) => (
        <span style={{ display: "inline-flex", gap: "var(--space-2)", alignItems: "center" }}>
          {row.name || "—"}
          {row.is_operator && <Badge tone="accent">Operator</Badge>}
          {row.beta_tester && <Badge tone="accent">Beta</Badge>}
          {!row.is_active && <Badge tone="danger">Deactivated</Badge>}
        </span>
      ),
    },
    { key: "email", header: "Email", sortable: true, sortValue: (row) => row.email, render: (row) => row.email },
    { key: "account_number", header: "Account", render: (row) => row.account_number },
    {
      key: "groups",
      header: "Groups",
      render: (row) =>
        row.account_types.map((t) => accountTypeLabel(t as AccountType)).join(", ") || "Not chosen",
    },
    { key: "plan", header: "Plan", render: (row) => row.plan_name },
    { key: "role", header: "Tier", render: (row) => tierLabel(row.tier) },
    { key: "joined", header: "Joined", sortable: true, sortValue: (row) => row.created_at, render: (row) => formatDate(row.created_at) },
  ];

  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <AdminShell>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <Panel title="Users">
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <SearchBar
              value={query}
              onChange={setQuery}
              placeholder="Search by name, email, or account number…"
              ariaLabel="Search users"
            />
            {loadError && <Alert tone="danger">{loadError}</Alert>}
            {!data && !loadError && (
              <p style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", margin: 0 }}>
                <Spinner size="sm" /> Loading users…
              </p>
            )}
            {data && (
              <>
                <div className="tv-admin-users">
                  <DataTable
                    columns={columns}
                    rows={data.items}
                    rowKey={(row) => row.id}
                    onRowClick={(row) => setSelectedId(row.id)}
                    emptyState={
                      <EmptyState
                        title="No accounts match"
                        description="Try a different name, email, or account number."
                      />
                    }
                  />
                </div>
                <Pagination
                  page={page}
                  pageCount={pageCount}
                  onChange={setPage}
                  summary={`${data.total} account${data.total === 1 ? "" : "s"}`}
                />
              </>
            )}
          </div>
        </Panel>
      </div>
      {selectedId && (
        <UserDetailModal
          userId={selectedId}
          onClose={() => setSelectedId(null)}
          onChanged={() => void load()}
        />
      )}
    </AdminShell>
  );
}

export default function AdminUsersPage() {
  return (
    <RequireAuth>
      <UsersSection />
    </RequireAuth>
  );
}
