import { useCallback, useEffect, useState } from "react";
import "../claims/claims.css";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  FormField,
  Panel,
  ProgressBar,
  SectionPageHeader,
  Select,
  Spinner,
  Tabs,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import { useT } from "../../i18n/LocaleContext";
import { listCompanies } from "../dealers/api";
import type { DealerCompany } from "../dealers/types";
import { disasterClaimsApi } from "../claims/api";
import { StatusBadge } from "../claims/components";
import { SellerPrice } from "../../components/SellerPrice";
import { deadlineState, fullDate } from "../claims/format";
import type { ClaimStatus, ClaimSummary } from "../claims/types";
import { ClaimWizard } from "./ClaimWizard";

/**
 * Disaster Claims home (claims separation, 2026-11-05): the
 * owner's INSURANCE claims at a glance — where each one stands,
 * what's on it, what it's worth, how far the to-do list has
 * come, and which deadlines are close. Its own section, its own
 * module, its own claim numbers (DC-…) — nothing here touches
 * the warranty Claims section. The guided create flow opens
 * from here; everything else lives on the claim's own page.
 * (Re-homed unchanged from the pre-separation claims list's
 * insurance half.)
 *
 * Main tab layout (program lane 4, 2026-11-10): the kit header
 * (SectionPageHeader) + Steel tabs in Ryan's order — How it
 * works (the explainer) · Open claims · Closed claims. The old
 * Open | History view switch becomes the Open / Closed tabs:
 * the same split the page always made (terminal statuses and
 * archived claims are "closed"; everything else is open), the
 * same true-list, the same dealer filter and sort riding each
 * list tab. History's deep link (#history, the home widget's
 * History button rides it) now selects the Closed tab.
 *
 * The module owns no settings section (conformance map), so
 * the Actions menu — the filing door plus the three tab jumps —
 * carries NO Settings entry (recorded n/a).
 */

/**
 * One claim as a TRUE list row (list standard, 2026-11-02):
 * every fact gets its OWN column — claim · incident · status ·
 * insurer · incident date · items · to-do · amount. The insurer
 * cell also names the dealers the claim's items touch (linked),
 * and the proof-of-loss badges ride the status cell — they are
 * urgency flags on the claim's standing. The to-do progress is
 * a compact count + slim bar in its own cell, never a stacked
 * block.
 */
function DisasterClaimRow({ claim }: { claim: ClaimSummary }) {
  const t = useT();
  const pol = deadlineState(
    claim.proof_of_loss_due,
    claim.proof_of_loss_sent_at !== null,
  );
  const open = ["filed", "in_review", "approved"].includes(claim.status);
  return (
    <div className="tv-claims-trow" role="row">
      <div className="tv-claims-cell-claim" role="cell">
        <Link to={`/disaster-claims/${claim.id}`} className="tv-claim-id">
          {claim.claim_number}
        </Link>
        {claim.archived && (
          <Badge tone="neutral">{t("claims.detail.archived")}</Badge>
        )}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.col.incident")}</span>
        {t(`claims.incident.${claim.incident_type}` as never)}
      </div>
      <div className="tv-claims-cell-status" role="cell">
        <StatusBadge status={claim.status} />
        {open && pol === "overdue" && (
          <Badge tone="danger">{t("disasterClaims.polOverdue")}</Badge>
        )}
        {open && pol === "soon" && (
          <Badge tone="warning">{t("disasterClaims.polDueSoon")}</Badge>
        )}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("disasterClaims.col.insurer")}</span>
        {claim.insurer_name || t("claims.noInsurer")}
        {claim.dealers.map((dealer) => (
          <span key={dealer.id}>
            {" · "}
            <Link to={`/dealers/${dealer.id}`} className="tv-ix-link">
              {dealer.name}
            </Link>
          </span>
        ))}
      </div>
      <div role="cell">
        <span className="tv-claims-cell-label">{t("claims.form.incidentDate")}</span>
        {claim.incident_date ? fullDate(claim.incident_date) : "—"}
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

/** A disaster claim is CLOSED once the process is over —
 *  denied / paid / closed. Archived claims are closed too,
 *  whatever their status. Everything else is open. (This is
 *  the split the old History view always showed.) */
const TERMINAL_STATUSES: ClaimStatus[] = ["denied", "paid", "closed"];

function isHistoryClaim(claim: ClaimSummary): boolean {
  return claim.archived || TERMINAL_STATUSES.includes(claim.status);
}

/** The page's three tabs (Ryan's spec, 2026-11-09). */
type DisasterTabId = "how" | "open" | "closed";

/** Deep links pick the opening tab — #history (the home
 *  widget's History button) and #closed select Closed,
 *  #open selects Open. Anything else opens on the explainer,
 *  the page's main tab. */
function tabFromHash(hash: string): DisasterTabId {
  const raw = hash.replace(/^#/, "");
  if (raw === "history" || raw === "closed") return "closed";
  if (raw === "open") return "open";
  return "how";
}

/** The explainer tab (new in lane 4): what this module is,
 *  how it differs from repair claims — the standing 100%
 *  separation, said plainly — and the doors to the work. */
function ExplainerTab({
  onGo,
  onFile,
}: {
  onGo: (tab: DisasterTabId) => void;
  onFile: () => void;
}) {
  const t = useT();
  const sections = [
    { title: t("disasterClaims.how.whatTitle"), body: t("disasterClaims.how.whatBody") },
    { title: t("disasterClaims.how.sepTitle"), body: t("disasterClaims.how.sepBody") },
    { title: t("disasterClaims.how.runTitle"), body: t("disasterClaims.how.runBody") },
    { title: t("disasterClaims.how.valueTitle"), body: t("disasterClaims.how.valueBody") },
  ];
  return (
    <Panel title={t("disasterClaims.tab.how")} variant="plate">
      <div className="tv-dc-how">
        {sections.map((s) => (
          <div key={s.title}>
            <p className="tv-dc-how-title">{s.title}</p>
            <p className="tv-dc-note">{s.body}</p>
          </div>
        ))}
        <div className="tv-dc-doors">
          <Button type="button" onClick={onFile}>
            {t("disasterClaims.new")}
          </Button>
          <Button type="button" variant="secondary" onClick={() => onGo("open")}>
            {t("disasterClaims.how.seeOpen")}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

export default function DisasterClaimsPage() {
  const t = useT();
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [tab, setTab] = useState<DisasterTabId>(() =>
    tabFromHash(window.location.hash),
  );
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  // Dealer intermingling: filter + sort by the dealers a claim
  // touches (through its items' tags, named on each summary).
  const [dealerFilter, setDealerFilter] = useState("");
  const [sortMode, setSortMode] = useState<"newest" | "dealer">("newest");
  const [dealerOptions, setDealerOptions] = useState<DealerCompany[] | null>(
    null,
  );

  // The mount read covers fresh arrivals. A hash change while
  // the page stays mounted (the home widget's buttons, an
  // in-app link) must land on its tab too — the Lane 1 hash-
  // follow discipline — so follow explicit deep links here.
  // Only the two list targets are followed; an unknown hash
  // never yanks the reader back to the explainer.
  useEffect(() => {
    const wanted = tabFromHash(hash);
    if (wanted !== "how") setTab(wanted);
  }, [hash]);

  // One read of the whole ledger (archived included); the two
  // list tabs split it with the same isHistoryClaim test the
  // old views applied after their per-view fetches.
  const load = useCallback(async () => {
    try {
      setClaims(await disasterClaimsApi.listClaims(true));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't load disaster claims.",
      );
    }
  }, []);

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

  const openClaims = (claims ?? []).filter((claim) => !isHistoryClaim(claim));
  const closedClaims = (claims ?? []).filter((claim) => isHistoryClaim(claim));

  const tabLabel = (id: DisasterTabId): string =>
    id === "how"
      ? t("disasterClaims.tab.how")
      : id === "open"
        ? t("disasterClaims.tab.open")
        : t("disasterClaims.tab.closed");

  /** One list tab's body — the old view, verbatim: the dealer
   *  filter + sort controls over the true-list, with the
   *  view's own empty states. `split` is the tab's claims
   *  before the dealer filter. */
  function listTab(split: ClaimSummary[], which: "open" | "closed") {
    if (claims === null) {
      return (
        <div className="tv-claim-loading">
          <Spinner />
        </div>
      );
    }
    if (which === "open" && claims.length === 0) {
      return (
        <Panel>
          <EmptyState
            title={t("disasterClaims.empty.title")}
            description={t("disasterClaims.empty.body")}
            action={
              <Button onClick={() => setWizardOpen(true)}>
                {t("disasterClaims.startFirst")}
              </Button>
            }
          />
        </Panel>
      );
    }
    if (split.length === 0) {
      return (
        <Panel>
          <EmptyState
            title={
              which === "closed"
                ? t("disasterClaims.historyEmpty.title")
                : t("disasterClaims.openEmpty.title")
            }
            description={
              which === "closed"
                ? t("disasterClaims.historyEmpty.body")
                : t("disasterClaims.openEmpty.body")
            }
          />
        </Panel>
      );
    }
    const visibleClaims = split.filter(
      (claim) =>
        !dealerFilter ||
        claim.dealers.some((dealer) => dealer.id === dealerFilter),
    );
    const orderedClaims =
      sortMode === "dealer"
        ? [...visibleClaims].sort((a, b) => {
            const aName = a.dealers[0]?.name.toLowerCase();
            const bName = b.dealers[0]?.name.toLowerCase();
            if (aName && bName && aName !== bName)
              return aName < bName ? -1 : 1;
            if (aName && !bName) return -1;
            if (!aName && bName) return 1;
            return b.created_at.localeCompare(a.created_at);
          })
        : visibleClaims;
    return (
      <div className="tv-dc-tabgrid">
        {dealerOptions !== null && (
          <div className="tv-claims-controls">
            <div className="tv-claims-control">
              <FormField label={t("claims.filter.dealer")} htmlFor="disaster-dealer">
                <Select
                  id="disaster-dealer"
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
              <FormField label={t("claims.sort.label")} htmlFor="disaster-sort">
                <Select
                  id="disaster-sort"
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
        {orderedClaims.length === 0 ? (
          <Panel>
            <EmptyState
              title={t("disasterClaims.filter.noneTitle")}
              description={t("disasterClaims.filter.noneBody")}
            />
          </Panel>
        ) : (
          <Panel
            title={
              which === "closed"
                ? t("disasterClaims.closedTitle")
                : t("disasterClaims.yours")
            }
            className="tv-claims-panel"
          >
            <div className="tv-claims-tablewrap">
              <div className="tv-claims-table tv-claims-table--disaster" role="table">
                <div className="tv-claims-thead" role="row">
                  <span role="columnheader">{t("claims.col.claim")}</span>
                  <span role="columnheader">{t("claims.col.incident")}</span>
                  <span role="columnheader">{t("claims.col.status")}</span>
                  <span role="columnheader">{t("disasterClaims.col.insurer")}</span>
                  <span role="columnheader">{t("claims.form.incidentDate")}</span>
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
                  <DisasterClaimRow key={claim.id} claim={claim} />
                ))}
              </div>
            </div>
          </Panel>
        )}
      </div>
    );
  }

  // Header facts (kit anatomy): the two list tabs' counts,
  // carried as standing facts once the ledger lands — nothing
  // true to show before that.
  const facts: SectionPageFact[] | undefined =
    claims !== null
      ? [
          { label: t("disasterClaims.fact.open"), value: openClaims.length },
          { label: t("disasterClaims.fact.closed"), value: closedClaims.length },
        ]
      : undefined;

  const openTab = (
    <div className="tv-dc-tabgrid">
      <div className="tv-dc-actions">
        <Button onClick={() => setWizardOpen(true)}>
          {t("disasterClaims.new")}
        </Button>
      </div>
      {listTab(openClaims, "open")}
    </div>
  );

  const tabs: TabItem[] = [
    {
      id: "how",
      label: tabLabel("how"),
      content: (
        <ExplainerTab onGo={setTab} onFile={() => setWizardOpen(true)} />
      ),
    },
    { id: "open", label: tabLabel("open"), content: openTab },
    { id: "closed", label: tabLabel("closed"), content: listTab(closedClaims, "closed") },
  ];

  return (
    <RequireAuth>
      <div className="tv-stack">
        <SectionPageHeader
          thumb={<ArtIcon name="disaster" size={96} />}
          title={t("disasterClaims.title")}
          subtitle={t("disasterClaims.subtitle")}
          facts={facts}
          actions={
            <SettingsActionsMenu
              ariaLabel={t("disasterClaims.title")}
              buttonLabel={t("inventory.actions")}
              entries={[
                {
                  key: "new",
                  label: t("disasterClaims.new"),
                  run: () => setWizardOpen(true),
                },
                ...(["how", "open", "closed"] as const).map((id) => ({
                  key: id,
                  label: tabLabel(id),
                  run: () => setTab(id),
                })),
              ]}
            />
          }
        />

        {error && <Alert tone="danger">{error}</Alert>}

        <Tabs
          tabs={tabs}
          activeId={tab}
          onChange={(id) => setTab(id as DisasterTabId)}
        />
      </div>
      <ClaimWizard
        open={wizardOpen}
        onClose={() => {
          setWizardOpen(false);
          void load();
        }}
        onFinished={(claimId) => {
          setWizardOpen(false);
          navigate(`/disaster-claims/${claimId}`);
        }}
      />
    </RequireAuth>
  );
}
