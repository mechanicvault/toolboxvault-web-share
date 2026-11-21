import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Panel } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { displayDate, money } from "../inventory/format";
import { listAccounts } from "./api";
import { SelfOpenModal } from "./TruckModals";
import type { TruckAccount } from "./types";
import "./truck.css";

/**
 * "Your tabs at a glance" — the retired standalone Truck
 * Accounts page's overview panel, rehomed on the Dealers
 * page (owner order, 2026-11-17: the standalone page is
 * retired; everything it held lives under the agent
 * window). ONE ROW PER AGENT the user owes — his total
 * across every open tab he holds, the next payment coming
 * due, and his plan. A row opens that agent's company panel
 * on its Truck section with the account's workbench open —
 * the agent window is the account's home now. The needs-
 * attention chips ride on top, and the self-kept open door
 * sits under the list. Renders nothing when the user owes
 * on no account.
 */

const STATUS_ORDER: Record<TruckAccount["status"], number> = {
  active: 0,
  invited: 1,
  closed: 2,
};

export default function TruckGlance() {
  const t = useT();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<TruckAccount[] | null>(null);
  const [selfOpen, setSelfOpen] = useState(false);

  const refresh = useCallback(() => {
    listAccounts()
      .then(setAccounts)
      .catch(() => setAccounts([]));
  }, []);
  useEffect(refresh, [refresh]);

  const theirs = useMemo(
    () =>
      (accounts ?? [])
        .filter((a) => a.my_role === "customer")
        .sort(
          (x, y) =>
            STATUS_ORDER[x.status] - STATUS_ORDER[y.status] ||
            (x.dealer_company_name ?? "").localeCompare(
              y.dealer_company_name ?? "",
            ) ||
            x.agent_name.localeCompare(y.agent_name),
        ),
    [accounts],
  );

  const owedAccounts = theirs.filter((a) => a.status !== "closed");
  const totalOwed = owedAccounts.reduce(
    (sum, a) => sum + Number(a.balance),
    0,
  );
  const missedTotal = owedAccounts.reduce((s, a) => s + a.missed_payments, 0);
  const pastDueTotal = owedAccounts.reduce(
    (s, a) => s + Number(a.amount_past_due),
    0,
  );
  const attention = theirs.filter(
    (a) => a.missed_payments > 0 || a.status === "invited",
  );

  function planOf(account: TruckAccount): string {
    const scheduled =
      account.status === "active" &&
      account.payment_amount != null &&
      account.next_due_date != null;
    if (!scheduled) return t("truck.planManual");
    return account.payment_cadence === "weekly"
      ? t("truck.planWeekly")
      : t("truck.planBiweekly");
  }

  interface AgentGlance {
    key: string;
    name: string;
    companies: string[];
    total: number;
    dueAmount: string | null;
    dueDate: string | null;
    plans: string[];
    target: TruckAccount;
  }

  const glance: AgentGlance[] = useMemo(() => {
    const groups = new Map<string, TruckAccount[]>();
    for (const account of theirs) {
      if (account.status === "closed") continue;
      const key =
        account.agent_kind === "platform" && account.dealer_user_id
          ? `platform:${account.dealer_user_id}`
          : account.private_agent_id
            ? `private:${account.private_agent_id}`
            : "records";
      const rows = groups.get(key) ?? [];
      rows.push(account);
      groups.set(key, rows);
    }
    const out: AgentGlance[] = [];
    for (const [key, rows] of groups) {
      const due = rows
        .filter(
          (a) =>
            a.status === "active" &&
            Number(a.balance) > 0 &&
            a.payment_amount != null &&
            a.next_due_date != null,
        )
        .sort((x, y) =>
          (x.next_due_date as string).localeCompare(
            y.next_due_date as string,
          ),
        )[0];
      const target =
        due ??
        [...rows].sort((x, y) => Number(y.balance) - Number(x.balance))[0];
      out.push({
        key,
        name:
          key === "records"
            ? t("truck.yourRecords")
            : rows[0].agent_name || t("truck.yourRecords"),
        companies: [
          ...new Set(
            rows
              .map((a) => a.dealer_company_name ?? "")
              .filter((n) => n !== ""),
          ),
        ],
        total: rows.reduce((s, a) => s + Number(a.balance), 0),
        dueAmount: due?.payment_amount ?? null,
        dueDate: due?.next_due_date ?? null,
        plans: [...new Set(rows.map(planOf))],
        target,
      });
    }
    return out.sort((x, y) => y.total - x.total || x.name.localeCompare(y.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theirs]);

  function openAccount(account: TruckAccount) {
    if (account.dealer_company_id) {
      navigate(
        `/dealers?dealer=${account.dealer_company_id}&section=truck&account=${account.id}`,
      );
    } else {
      navigate("/dealers#agents");
    }
  }

  if (accounts === null || glance.length === 0) return null;

  return (
    <div className="tv-truck-glance-wrap" id="truck-glance">
      <Panel title={t("truck.glanceTitle")} variant="accent-edge">
        {attention.length > 0 && (
          <div
            className="tv-truck-strip"
            role="group"
            aria-label={t("truck.needsAttention")}
            style={{ marginBottom: "0.75rem" }}
          >
            <span className="tv-truck-strip-label">{t("truck.needsAttention")}</span>
            {attention.map((account) => (
              <Button
                key={account.id}
                size="sm"
                variant="secondary"
                onClick={() => openAccount(account)}
              >
                {account.dealer_company_name ?? t("truck.dealerFallback")} ·{" "}
                {account.agent_name || t("truck.yourRecords")} —{" "}
                {account.status === "invited"
                  ? t("truck.attentionInvite")
                  : t("truck.attentionMissed").replace(
                      "{count}",
                      String(account.missed_payments),
                    )}
              </Button>
            ))}
          </div>
        )}
        <p className="tv-truck-glance-total">
          {t("dealers.truck.totalOwed")}{" "}
          <strong>{money(String(totalOwed))}</strong>
          {missedTotal > 0 && (
            <>
              {t("truck.glanceMissed")
                .replace("{missed}", String(missedTotal))
                .replace("{amount}", money(String(pastDueTotal)))}
            </>
          )}
        </p>
        <div className="tv-truck-glance">
          <div className="tv-truck-glance-thead" aria-hidden="true">
            <span>{t("dealers.truck.col.agent")}</span>
            <span>{t("truck.glanceColTotalOwed")}</span>
            <span>{t("truck.glanceColNextPayment")}</span>
            <span>{t("truck.glanceColDueDate")}</span>
            <span>{t("truck.glanceColPlan")}</span>
          </div>
          {glance.map((row) => (
            <button
              key={row.key}
              type="button"
              className="tv-truck-glance-row"
              onClick={() => openAccount(row.target)}
              aria-label={t("truck.glanceRowAria").replace("{name}", row.name).replace("{amount}", money(String(row.total)))}
            >
              <span className="tv-truck-glance-agent">
                {row.name}
                {row.companies.length > 1 && (
                  <span className="tv-truck-glance-companies">
                    {row.companies.join(" · ")}
                  </span>
                )}
              </span>
              <span className="tv-truck-glance-owed">
                {money(String(row.total))}
              </span>
              <span>
                {row.dueAmount != null ? money(row.dueAmount) : "—"}
              </span>
              <span>
                {row.dueDate ? displayDate(row.dueDate) : "—"}
              </span>
              <span>{row.plans.join(" · ")}</span>
            </button>
          ))}
        </div>
        <p style={{ margin: "0.75rem 0 0" }}>
          <Button size="sm" variant="secondary" onClick={() => setSelfOpen(true)}>
            {t("truck.openSelfKept")}
          </Button>
        </p>
      </Panel>
      <SelfOpenModal
        open={selfOpen}
        onClose={() => setSelfOpen(false)}
        onOpened={(account) => {
          refresh();
          openAccount(account);
        }}
      />
    </div>
  );
}
