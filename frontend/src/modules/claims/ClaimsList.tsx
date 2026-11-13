import { useCallback, useEffect, useState } from "react";
import "./claims.css";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  EmptyState,
  FormField,
  Panel,
  ProgressBar,
  Select,
  Spinner,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { ClaimWalkthrough } from "../walkthroughs/ClaimWalkthrough";
import { WalkthroughDoor } from "../walkthroughs/WalkthroughShell";
import { listCompanies } from "../dealers/api";
import type { DealerCompany } from "../dealers/types";
import { listClaims } from "./api";
import { StatusBadge } from "./components";
import { SellerPrice } from "../../components/SellerPrice";
import { fullDate } from "./format";
import type { ClaimSummary } from "./types";

/**
 * The warranty claims list (blueprint §15): the owner's
 * WARRANTY & REPAIR claims at a glance — where each one stands,
 * which dealer and agent it runs through, what's on it, and how
 * far the to-do list has come. Claims separation (2026-11-05):
 * this list is warranty ONLY — insurance claims live in
 * Disaster Claims, and nothing insurance-shaped appears here.
 * A warranty claim is born from its item (the broken prompt on
 * the tool/battery/set pages), so there is no filing wizard
 * here; everything else lives on the claim's own page.
 *
 * Repairs & Maintenance merge (2026-11-05): the list no longer
 * carries its own page — the merged page's tabs drive it, one
 * instance per view (`open` on the Repair claims tab, `history`
 * on the Repair history tab) — the old in-page Open/History
 * switch is retired with the standalone Claims page. Content
 * and behavior are exactly what the Claims page showed.
 */

/**
 * One claim as a TRUE list row (list standard, 2026-11-02):
 * every fact gets its OWN column — claim · status · dealer ·
 * agent · opened · items · to-do · amount. The to-do progress
 * is a compact count + slim bar in its own cell, never a
 * stacked block.
 */
function ClaimRow({ claim }: { claim: ClaimSummary }) {
  const t = useT();
  return (
    <div className="tv-claims-trow" role="row">
      <div className="tv-claims-cell-claim" role="cell">
        <Link to={`/claims/${claim.id}`} className="tv-claim-id">
          {claim.claim_number}
        </Link>
        {claim.archived && (
          <Badge tone="neutral">{t("claims.detail.archived")}</Badge>
        )}
      </div>
      <div className="tv-claims-cell-status" role="cell">
        <StatusBadge status={claim.status} />
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.col.parties")}</span>
        {claim.dealer_name || "—"}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.warranty.agent")}</span>
        {claim.warranty_agent_name ||
          (claim.filed_with === "corporate"
            ? t("claims.filedWith.corporateShort")
            : "—")}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.col.opened")}</span>
        {fullDate((claim.reported_at ?? claim.created_at).slice(0, 10))}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.col.items")}</span>
        {claim.line_count}{" "}
        {claim.line_count === 1 ? t("claims.itemOne") : t("claims.itemMany")}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.todo")}</span>
        <span className="tv-claims-todo">
          <span>
            {claim.checklist_done}/{claim.checklist_total}
          </span>
          <ProgressBar
            value={
              claim.checklist_total
                ? (claim.checklist_done / claim.checklist_total) * 100
                : 0
            }
            tone={
              claim.checklist_done === claim.checklist_total
                ? "success"
                : "accent"
            }
            label={`${t("claims.todo")}: ${claim.checklist_done} ${t("inventory.of")} ${claim.checklist_total}`}
          />
        </span>
      </div>
      <div className="tv-claims-cell-amount" role="cell">
        <span className="tv-claims-cell-label">{t("claims.col.amount")}</span>
        <strong className="tv-claim-amount">
          <SellerPrice amount={claim.total_amount} currency={claim.owner_currency} />
        </strong>
      </div>
    </div>
  );
}

/** A warranty claim is HISTORY once it is Repaired (the
 *  ladder's terminal — finished work), once the owner CLOSES
 *  it (closing is its own layer since the claims overhaul,
 *  2026-11-06, and shelves a claim from ANY status), or once
 *  it is archived, whatever its status: filed away is filed
 *  away. Everything else is open. */
function isHistoryClaim(claim: ClaimSummary): boolean {
  return (
    claim.archived || claim.closed_at !== null || claim.status === "completed"
  );
}

export function ClaimsList({ view }: { view: "open" | "history" }) {
  const t = useT();
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Dealer intermingling: filter + sort by the claim's dealer.
  // The dealer options ride the dealers module; when it doesn't
  // answer (off/unassigned) the controls hide, like every other
  // dealer surface.
  const [dealerFilter, setDealerFilter] = useState("");
  const [sortMode, setSortMode] = useState<"newest" | "dealer">("newest");
  const [dealerOptions, setDealerOptions] = useState<DealerCompany[] | null>(
    null,
  );
  const [walkOpen, setWalkOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      // The history view reads with archived claims included
      // (they are part of its population); the open view reads
      // the default list, as the page always has.
      setClaims(await listClaims(view === "history"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load claims.");
    }
  }, [view]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    listCompanies()
      .then((rows) => {
        if (!cancelled) setDealerOptions(rows);
      })
      .catch(() => {
        if (!cancelled) setDealerOptions(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const inView = (claims ?? []).filter((claim) =>
    view === "history" ? isHistoryClaim(claim) : !isHistoryClaim(claim),
  );
  const visibleClaims = inView.filter(
    (claim) =>
      !dealerFilter ||
      claim.dealers.some((dealer) => dealer.id === dealerFilter),
  );
  const orderedClaims =
    sortMode === "dealer"
      ? [...visibleClaims].sort((a, b) => {
          // By dealer name; claims naming no dealer trail,
          // newest first inside each group — the inventory sort
          // convention.
          const aName = a.dealer_name?.toLowerCase();
          const bName = b.dealer_name?.toLowerCase();
          if (aName && bName && aName !== bName)
            return aName < bName ? -1 : 1;
          if (aName && !bName) return -1;
          if (!aName && bName) return 1;
          return b.created_at.localeCompare(a.created_at);
        })
      : visibleClaims;

  return (
    <div className="tv-claims-page">
      {error && <Alert tone="danger">{error}</Alert>}
      {claims === null && !error && (
        <div className="tv-claim-loading">
          <Spinner />
        </div>
      )}
      {claims !== null && claims.length === 0 && view === "open" && (
        <>
          {/* The first-claim walkthrough's door (sweep D3):
              shown only while the warranty list itself is
              empty — real data, so the door retires itself
              the moment a first claim exists. */}
          <WalkthroughDoor
            title={t("walk.claim.doorTitle" as never)}
            body={t("walk.claim.doorBody" as never)}
            onStart={() => setWalkOpen(true)}
            testId="walk-claim-door"
          />
          <Panel>
            <EmptyState
              title={t("claims.empty.title")}
              description={t("claims.empty.body")}
            />
          </Panel>
          <ClaimWalkthrough
            open={walkOpen}
            onClose={() => setWalkOpen(false)}
            onDone={() => void load()}
          />
        </>
      )}
      {claims !== null && inView.length === 0 && !(claims.length === 0 && view === "open") && (
        <Panel>
          <EmptyState
            title={
              view === "history"
                ? t("claims.historyEmpty.title")
                : t("claims.openEmpty.title")
            }
            description={
              view === "history"
                ? t("claims.historyEmpty.body")
                : t("claims.openEmpty.body")
            }
          />
        </Panel>
      )}
      {claims !== null && inView.length > 0 && dealerOptions !== null && (
        <div className="tv-claims-controls">
          <div className="tv-claims-control">
            <FormField label={t("claims.filter.dealer")} htmlFor="claims-dealer">
              <Select
                id="claims-dealer"
                value={dealerFilter}
                onChange={(e) => setDealerFilter(e.target.value)}
              >
                <option value="">{t("claims.filter.allDealers")}</option>
                {dealerOptions.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
          <div className="tv-claims-control">
            <FormField label={t("claims.sort.label")} htmlFor="claims-sort">
              <Select
                id="claims-sort"
                value={sortMode}
                onChange={(e) =>
                  setSortMode(e.target.value as "newest" | "dealer")
                }
              >
                <option value="newest">{t("claims.sort.newest")}</option>
                <option value="dealer">{t("claims.sort.dealer")}</option>
              </Select>
            </FormField>
          </div>
        </div>
      )}
      {claims !== null && inView.length > 0 && orderedClaims.length === 0 && (
        <Panel>
          <EmptyState
            title={t("claims.filter.noneTitle")}
            description={t("claims.filter.noneBody")}
          />
        </Panel>
      )}
      {claims !== null && orderedClaims.length > 0 && (
        <Panel
          title={view === "history" ? t("claims.historyTitle") : t("claims.yours")}
          className="tv-claims-panel"
        >
          <div className="tv-claims-tablewrap">
            <div className="tv-claims-table" role="table">
              <div className="tv-claims-thead" role="row">
                <span role="columnheader">{t("claims.col.claim")}</span>
                <span role="columnheader">{t("claims.col.status")}</span>
                <span role="columnheader">{t("claims.col.parties")}</span>
                <span role="columnheader">{t("claims.warranty.agent")}</span>
                <span role="columnheader">{t("claims.col.opened")}</span>
                <span role="columnheader">{t("claims.col.items")}</span>
                <span role="columnheader">{t("claims.todo")}</span>
                <span
                  role="columnheader"
                  className="tv-claims-th-amount"
                >
                  {t("claims.col.amount")}
                </span>
              </div>
              {orderedClaims.map((claim) => (
                <ClaimRow key={claim.id} claim={claim} />
              ))}
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
