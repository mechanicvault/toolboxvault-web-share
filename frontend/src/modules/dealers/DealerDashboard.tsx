import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Panel, Spinner } from "../../components";
import { ApiError } from "../../lib/api";
import { formatMoney } from "../../lib/money";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import { getDealerStats, getMyProfile, listIncomingWarrantyRequests, warrantyCounts } from "./api";
import { DealerClaimsSection } from "../claims/DealerClaimsSection";
import type { AgentProfile, DealerPortalStats, WarrantyCounts, WarrantyRequest } from "./types";

const ROUTE_WEEKDAYS = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
];
const ROUTE_FREQUENCY_LABELS: Record<string, string> = {
  weekly: "Every week",
  biweekly: "Every two weeks",
  monthly: "Monthly",
};

function formatRouteDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

/** Route section (audit A2): the agent's fixed route + the next
 *  visit the backend computes from it. No schedule -> a pointer
 *  at the settings editor. Self-fetching like every section. */
function RouteSection() {
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  useEffect(() => {
    getMyProfile().then(setProfile).catch(() => setProfile(null));
  }, []);
  if (profile === null) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        <Spinner size="sm" /> Loading…
      </p>
    );
  }
  const hasRoute =
    profile.route_frequency !== null &&
    profile.route_day_of_week !== null &&
    profile.route_anchor_date !== null;
  if (!hasRoute) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        No route schedule set.{" "}
        <Link to="/settings/dealer-profile" style={{ color: "var(--accent)", fontWeight: 600 }}>
          Set your route days →
        </Link>
      </p>
    );
  }
  return (
    <div style={{ display: "grid", gap: "0.35rem" }}>
      <p style={{ margin: 0 }}>
        {ROUTE_FREQUENCY_LABELS[profile.route_frequency!] ?? profile.route_frequency} ·{" "}
        {ROUTE_WEEKDAYS[profile.route_day_of_week!]}
      </p>
      {profile.route_next_visit && (
        <p style={{ margin: 0 }}>
          Next visit: <strong>{formatRouteDate(profile.route_next_visit)}</strong>
        </p>
      )}
      <p style={{ margin: 0 }}>
        <Link to="/settings/dealer-profile" style={{ color: "var(--accent)", fontWeight: 600 }}>
          Edit route →
        </Link>
      </p>
    </div>
  );
}

/**
 * The DEALER DASHBOARD (dealer build, 2026-10-20): the dealer
 * group's home overview, restructured from loose stats into a
 * dashboard of SECTIONS. Warranty Requests was the first section;
 * Wave 2 (2026-10-20) plugged Truck Accounts + Payments in as
 * further entries in DEALER_DASHBOARD_SECTIONS below — each
 * section is a self-fetching component with its own title; the
 * dashboard shell (profile strip + section stack) doesn't change.
 */

interface DashboardSection {
  key: string;
  title: string;
  render: () => ReactNode;
}

function WarrantySection() {
  const [counts, setCounts] = useState<WarrantyCounts | null>(null);
  const [queue, setQueue] = useState<WarrantyRequest[]>([]);

  useEffect(() => {
    Promise.all([warrantyCounts(), listIncomingWarrantyRequests()])
      .then(([c, list]) => {
        setCounts(c);
        setQueue(list.filter((r) => !r.mine).slice(0, 4));
      })
      .catch(() => setCounts(null));
  }, []);

  if (counts === null) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        <Spinner size="sm" /> Loading warranty requests…
      </p>
    );
  }

  return (
    <div style={{ display: "grid", gap: "0.5rem" }}>
      <p style={{ margin: 0 }}>
        <strong>{counts.incoming_unclaimed}</strong> waiting to be
        claimed · <strong>{counts.claimed_open}</strong> you're
        working · <strong>{counts.resolved}</strong> resolved
      </p>
      {queue.length === 0 ? (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Nothing in your queue right now. When a customer sends a
          broken tool to your company, it lands here — first agent
          to claim the job owns it.
        </p>
      ) : (
        queue.map((request) => (
          <p key={request.id} style={{ margin: 0 }}>
            <Badge
              tone={request.status === "resolved" ? "success" : "accent"}
            >
              {request.status_label}
            </Badge>{" "}
            {request.item_name} — {request.requester_name} (
            {request.company_name})
          </p>
        ))
      )}
      <p style={{ margin: 0 }}>
        <Link to="/dealers" style={{ color: "var(--accent)", fontWeight: 600 }}>
          Open the warranty queue →
        </Link>
      </p>
    </div>
  );
}

interface TruckDashboardData {
  open_accounts: number;
  total_outstanding: string;
  due_this_week: { account_id: string; customer_name: string; amount: string | null; balance: string; next_due_date: string }[];
  overdue: { account_id: string; customer_name: string; amount: string | null; balance: string; next_due_date: string }[];
}

function useTruckDashboard(): TruckDashboardData | null | undefined {
  const [data, setData] = useState<TruckDashboardData | null | undefined>(undefined);
  useEffect(() => {
    import("../truck-accounts/api")
      .then((m) => m.getDealerDashboard())
      .then((d) => setData(d as TruckDashboardData))
      .catch(() => setData(null));
  }, []);
  return data;
}

function moneyText(value: string): string {
  return formatMoney(value);
}

function TruckAccountsSection() {
  const data = useTruckDashboard();
  if (data === undefined) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        <Spinner size="sm" /> Loading truck accounts…
      </p>
    );
  }
  if (data === null) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        Truck Accounts isn't enabled for your account.
      </p>
    );
  }
  return (
    <div style={{ display: "grid", gap: "0.5rem" }}>
      <p style={{ margin: 0 }}>
        <strong>{data.open_accounts}</strong> open account
        {data.open_accounts === 1 ? "" : "s"} ·{" "}
        <strong>{moneyText(data.total_outstanding)}</strong> outstanding
        across your customers
      </p>
      <p style={{ margin: 0 }}>
        <Link to="/truck-accounts" style={{ color: "var(--accent)", fontWeight: 600 }}>
          Open Truck Accounts →
        </Link>
      </p>
    </div>
  );
}

function TruckPaymentsSection() {
  const data = useTruckDashboard();
  if (data === undefined) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        <Spinner size="sm" /> Loading payments…
      </p>
    );
  }
  if (data === null) {
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        Truck Accounts isn't enabled for your account.
      </p>
    );
  }
  return (
    <div style={{ display: "grid", gap: "0.5rem" }}>
      {data.overdue.length === 0 && data.due_this_week.length === 0 && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Nothing due this week and nothing overdue. Payments land
          here as your customers' due dates approach.
        </p>
      )}
      {data.overdue.map((row) => (
        <p key={row.account_id} style={{ margin: 0 }}>
          <Badge tone="danger">Overdue</Badge>{" "}
          <Link
            to={`/truck-accounts/${row.account_id}`}
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {row.customer_name}
          </Link>{" "}
          — {row.amount ? moneyText(row.amount) : "payment"} was due{" "}
          {row.next_due_date} · balance {moneyText(row.balance)}
        </p>
      ))}
      {data.due_this_week.map((row) => (
        <p key={row.account_id} style={{ margin: 0 }}>
          <Badge tone="warning">Due this week</Badge>{" "}
          <Link
            to={`/truck-accounts/${row.account_id}`}
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {row.customer_name}
          </Link>{" "}
          — {row.amount ? moneyText(row.amount) : "payment"} due{" "}
          {row.next_due_date} · balance {moneyText(row.balance)}
        </p>
      ))}
      <p style={{ margin: 0, color: "var(--text-muted)" }}>
        Online payouts to your bank arrive when online payments are
        enabled for your account — until then, payments are recorded
        at the truck.
      </p>
    </div>
  );
}

/** Wave 2 (2026-10-20): Truck Accounts + Payments sections,
 *  registered into the same section list as Warranty Requests. */
export const DEALER_DASHBOARD_SECTIONS: DashboardSection[] = [
  { key: "warranty_requests", title: "Warranty requests", render: () => <WarrantySection /> },
  // Two-types build (2026-10-25): real warranty CLAIMS addressed
  // to this dealer's companies — the two-party record, distinct
  // from the lighter maintenance-side requests above.
  { key: "warranty_claims", title: "Warranty claims", render: () => <DealerClaimsSection /> },
  { key: "truck_accounts", title: "Truck Accounts", render: () => <TruckAccountsSection /> },
  { key: "truck_payments", title: "Payments due", render: () => <TruckPaymentsSection /> },
  { key: "route", title: "Route", render: () => <RouteSection /> },
];

/** Widget options Wave 4 batch A: the dashboard's section
 *  show/hide choices ride the Home block's options bundle
 *  (registered in core's widgetOptions under "dealer_dashboard").
 *  Every section defaults ON — absence is today's full stack —
 *  and the read is the store's unset rule restated locally
 *  (this module stays on its own side of the core fence). */
const SECTION_SETTINGS: Record<string, string> = {
  warranty_requests: "showWarrantyRequests",
  warranty_claims: "showWarrantyClaims",
  truck_accounts: "showTruckAccounts",
  truck_payments: "showPaymentsDue",
  route: "showRoute",
};

function sectionOn(
  settings: Record<string, BlockSettingValue> | undefined,
  name: string,
): boolean {
  const v = settings?.[name];
  return typeof v === "boolean" ? v : true;
}

export default function DealerDashboard({
  settings,
}: {
  settings?: Record<string, BlockSettingValue>;
} = {}) {
  const [stats, setStats] = useState<DealerPortalStats | null>(null);
  const [moduleOff, setModuleOff] = useState(false);

  useEffect(() => {
    getDealerStats()
      .then(setStats)
      .catch((err) => {
        if (err instanceof ApiError && err.code === "module_unavailable") {
          setModuleOff(true);
        }
      });
  }, []);

  if (moduleOff) return null;

  const sections = DEALER_DASHBOARD_SECTIONS.filter((section) =>
    sectionOn(settings, SECTION_SETTINGS[section.key] ?? ""),
  );

  return (
    <div style={{ display: "grid", gap: "var(--spacing)" }}>
      {sectionOn(settings, "showProfile") && (
      <Panel title="Your dealer profile">
        {stats === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            <Spinner size="sm" /> Loading…
          </p>
        ) : (
          <div style={{ display: "grid", gap: "0.35rem" }}>
            <p style={{ margin: 0 }}>
              Listing: <strong>{stats.profile_visibility}</strong> ·
              Preferred by <strong>{stats.preferred_by_count}</strong>{" "}
              mechanic{stats.preferred_by_count === 1 ? "" : "s"} ·{" "}
              <strong>{stats.companies_represented_count}</strong>{" "}
              compan{stats.companies_represented_count === 1 ? "y" : "ies"}{" "}
              represented
            </p>
            <p style={{ margin: 0 }}>
              <Link
                to="/settings/dealer-profile"
                style={{ color: "var(--accent)", fontWeight: 600 }}
              >
                Edit profile &amp; service area →
              </Link>
            </p>
          </div>
        )}
      </Panel>
      )}
      {sections.map((section) => (
        <Panel key={section.key} title={section.title}>
          {section.render()}
        </Panel>
      ))}
    </div>
  );
}
