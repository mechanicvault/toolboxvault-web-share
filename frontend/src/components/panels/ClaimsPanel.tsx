import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { activeLocale } from "../../lib/format";
import { listClaims } from "../../modules/claims/api";
import { deadlineState, money } from "../../modules/claims/format";
import type { ClaimStatus, ClaimSummary } from "../../modules/claims/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Claims panel (Rail Steel conversion, Phase 2a).
 *
 * Honesty standard (Phase 1): the claims list's only filter is a
 * LOCAL archived toggle — there is no status route or query the
 * page reads, so the panel invents no status deep-links. What it
 * carries instead, all derived from the ONE list call the page
 * itself makes (GET /claims, archived excluded):
 *  - the All claims link with the live count,
 *  - an amounts list (open total, paid total) summed from the
 *    list rows' own total_amount fields,
 *  - a per-status count list (statuses present only),
 *  - a "Waiting on you" note when a claim in flight has open
 *    to-dos or a proof-of-loss deadline due/overdue — both facts
 *    ride the list payload (checklist_done/total,
 *    proof_of_loss_due/sent_at, deadlineState is the list page's
 *    own helper).
 */

const OPEN: ClaimStatus[] = [
  // Drafts count as open — the ONE definition (C-02, Deep Audit
  // Round 2): the backend's HOME_STATUSES (claims/models.py, used
  // by /claims/stats and the Home stat) includes draft, so the
  // panel's "Open claims" must too, or the same label reads two
  // numbers on the same account at the same moment.
  "draft",
  "filed",
  "in_review",
  "approved",
  // Warranty & repair open rungs (claims two-types, 2026-10-25).
  "not_reported",
  "reported",
  "in_repair",
];
const STATUS_ORDER: ClaimStatus[] = [
  "draft",
  "filed",
  "in_review",
  "approved",
  "denied",
  "paid",
  "not_reported",
  "reported",
  "in_repair",
  "completed",
  "closed",
];

function sum(rows: ClaimSummary[]): number {
  return rows.reduce((acc, c) => acc + (Number(c.total_amount) || 0), 0);
}

export function ClaimsPanel() {
  const t = useT();
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);

  useEffect(() => {
    let live = true;
    listClaims(false)
      .then((rows) => {
        if (live) setClaims(rows);
      })
      .catch(() => {
        if (live) setClaims([]);
      });
    return () => {
      live = false;
    };
  }, []);

  const rows = claims ?? [];
  const open = rows.filter((c) => OPEN.includes(c.status));
  const paid = rows.filter((c) => c.status === "paid");
  const waiting = rows.filter((c) => {
    if (c.status !== "draft" && !OPEN.includes(c.status)) return false;
    const todoOpen = c.checklist_total > 0 && c.checklist_done < c.checklist_total;
    const polHot =
      OPEN.includes(c.status) &&
      deadlineState(c.proof_of_loss_due, c.proof_of_loss_sent_at !== null) !==
        "ok";
    return todoOpen || polHot;
  });
  const byStatus = STATUS_ORDER.map((status) => ({
    status,
    count: rows.filter((c) => c.status === status).length,
  })).filter((row) => row.count > 0);

  return (
    <>
      <p className="tv-sp-kicker">{t("claims.title")}</p>
      <h2 className="tv-sp-title">{t("claims.title")}</h2>
      <PanelUtility />
      <p className="tv-sp-group">{t("panel.views")}</p>
      <div className="tv-sp-list">
        <NavLink
          to="/repairs#repair-claims"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>{t("panel.claims.all")}</span>
          {claims !== null && (
            <span className="tv-sp-count">
              {rows.length.toLocaleString(activeLocale())}
            </span>
          )}
        </NavLink>
      </div>
      {claims !== null && rows.length > 0 && (
        <>
          <p className="tv-sp-group">{t("panel.claims.amounts")}</p>
          <ul className="tv-sp-stats">
            <li>
              <span>{t("stat.claims.open_claims")}</span>
              <strong>{open.length.toLocaleString(activeLocale())}</strong>
            </li>
            <li>
              <span>{t("panel.claims.openTotal")}</span>
              <strong>{money(String(sum(open)), rows[0]?.owner_currency)}</strong>
            </li>
            <li>
              <span>{t("panel.claims.paidOut")}</span>
              <strong>{money(String(sum(paid)), rows[0]?.owner_currency)}</strong>
            </li>
          </ul>
          {byStatus.length > 0 && (
            <>
              <p className="tv-sp-group">{t("panel.claims.byStatus")}</p>
              <ul className="tv-sp-stats">
                {byStatus.map((row) => (
                  <li key={row.status}>
                    <span>{t(`claims.status.${row.status}` as never)}</span>
                    <strong>{row.count.toLocaleString(activeLocale())}</strong>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
      {waiting.length > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">{t("panel.claims.waitingTitle")}</p>
          <p>
            {t(
              waiting.length === 1
                ? "panel.claims.waitingOne"
                : "panel.claims.waitingMany",
            )
              .replace("{count}", String(waiting.length))
              .replace("{number}", waiting[0].claim_number)}
          </p>
        </div>
      )}
    </>
  );
}
