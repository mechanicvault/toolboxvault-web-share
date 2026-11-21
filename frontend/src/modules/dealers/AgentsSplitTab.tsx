import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  DatePicker,
  EmptyState,
  FormField,
  HrefButton,
  LinkButton,
  Panel,
  SectionHeader,
  Select,
  SideList,
  SideListDivider,
  SideListGroup,
  SideListRow,
  TextArea,
  TextInput,
  formGridStyle,
  useToast,
} from "../../components";
import { ApiError, downloadBlob } from "../../lib/api";
import { formatPhone, phoneHref, todayLocalIso } from "../../lib/format";
import {
  addEntry,
  downloadStatement,
  getAccount,
  listAccounts,
} from "../truck-accounts/api";
import type {
  TruckAccount,
  TruckAccountDetail,
  TruckEntry,
} from "../truck-accounts/types";
import { displayDate, money } from "../inventory/format";
import { useT } from "../../i18n/LocaleContext";
import {
  addPreferred,
  createPrivateAgent,
  deletePrivateAgent,
  getRosterAgent,
  linkPrivateAgent,
  setAgentPreferred,
  unlinkPrivateAgent,
  updatePrivateAgent,
} from "./api";
import { AgentImportButton } from "./AgentCardImport";
import { ContactPickButton } from "./components/ContactPickButton";
import { dayLabel, freqLabel, tenureText } from "./rosterFormat";
import type {
  DealerCompany,
  PreferredAgent,
  PrivateAgent,
  PrivateAgentWrite,
  RosterAgentDetail,
  RosterEntry,
  RosterTruckAccount,
} from "./types";

/**
 * The Agents tab as a SIDE LIST (owner's pattern name,
 * 2026-11-13; design A2 rebuilt to act like D3): ONE list of
 * every agent the viewer has, across all his dealers — the
 * picked agent's summary on the right (who he is, how to
 * reach him, his numbers), his full record one tap away on
 * the dealer page, no page hop to see the summary.
 *
 * Current vs former is the owner's own definition (2026-11-13):
 * "a former agent is anyone not starred." The star is the
 * connection's preferred flag (multi-preferred — any number of
 * agents per dealer may be starred at once), so the list groups
 * strictly by it: starred seats on top under Current agents,
 * everyone else below the divider under Former agents. The
 * panel's star button writes the same flag the dealer-page
 * roster writes (set_agent_preferred): starring a former agent
 * moves him up; unstarring a current agent drops him down.
 *
 * The seats merge the page's two standing reads exactly the
 * way the server roster merges them per company (his own
 * records + his connections; an archived record's seat is its
 * platform connection). The list reads the flag as stored —
 * no surface-local state — so this tab, the directory row and
 * the dealer pages all resolve the same agent the same way.
 */

interface AgentSeat {
  key: string;
  kind: "private" | "platform";
  companyId: string | null;
  companyName: string | null;
  /** Roster-shaped seats carry a full entry (the panel's
   *  AgentRecord seat); record-shaped seats (a company-less
   *  record, an archived record whose connection is gone)
   *  carry the record itself. Exactly one is set. */
  entry: RosterEntry | null;
  record: PrivateAgent | null;
  starred: boolean;
  name: string;
  phone: string;
  email: string;
  location: string;
  nextVisit: string | null;
  startedAt: string | null;
  endedAt: string | null;
}

const EMPTY_AGENT: PrivateAgentWrite = {
  company_id: null,
  name: "",
  phone: "",
  email: "",
  notes: "",
};

export function AgentsSplitTab({
  companies,
  pickerCompanies,
  agents,
  preferred,
  onChanged,
}: {
  companies: DealerCompany[];
  pickerCompanies: DealerCompany[];
  agents: PrivateAgent[];
  preferred: PreferredAgent[];
  onChanged: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [mode, setMode] = useState<"detail" | "add">("detail");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [starBusy, setStarBusy] = useState(false);
  const [error, setError] = useState("");

  const companyName = useMemo(() => {
    const byId = new Map(companies.map((c) => [c.id, c.name]));
    return (id: string | null) => (id ? (byId.get(id) ?? null) : null);
  }, [companies]);

  const seats = useMemo<AgentSeat[]>(() => {
    const out: AgentSeat[] = [];
    const connByPrivate = new Map(
      preferred
        .filter((p) => p.private_agent_id)
        .map((p) => [p.private_agent_id as string, p]),
    );
    // His own records first (never archived ones — an archived
    // record's seat is its platform connection, below).
    for (const record of agents) {
      if (record.archived) continue;
      const conn = connByPrivate.get(record.id) ?? null;
      const entry: RosterEntry = {
        key: `private:${record.id}`,
        kind: "private",
        connection_id: conn?.id ?? null,
        private_agent_id: record.id,
        agent_user_id: null,
        name: record.name,
        phone: record.phone,
        email: record.email,
        account_number: null,
        location: record.location,
        route_frequency: record.route_frequency,
        route_day_of_week: record.route_day_of_week,
        route_anchor_date: record.route_anchor_date,
        next_visit: conn?.next_visit ?? null,
        started_at: record.started_at,
        ended_at: record.ended_at,
        is_preferred: conn?.is_preferred ?? false,
        claimed_by_name: record.claimed_by_name,
        claimed_by_account_number: record.claimed_by_account_number,
      };
      out.push({
        key: `${record.company_id ?? "none"}:private:${record.id}`,
        kind: "private",
        companyId: record.company_id,
        companyName: companyName(record.company_id),
        entry,
        record: null,
        starred: entry.is_preferred,
        name: record.name,
        phone: record.phone,
        email: record.email,
        location: record.location,
        nextVisit: entry.next_visit,
        startedAt: record.started_at,
        endedAt: record.ended_at,
      });
    }
    // Platform connections.
    for (const row of preferred) {
      if (row.kind !== "platform" || !row.agent_user_id) continue;
      const entry: RosterEntry = {
        key: `platform:${row.agent_user_id}`,
        kind: "platform",
        connection_id: row.id,
        private_agent_id: null,
        agent_user_id: row.agent_user_id,
        name: row.name,
        phone: row.phone,
        email: row.email,
        account_number: row.account_number,
        location: "",
        route_frequency: null,
        route_day_of_week: null,
        route_anchor_date: null,
        next_visit: row.next_visit,
        started_at: row.tenure_started_at,
        ended_at: row.tenure_ended_at,
        is_preferred: row.is_preferred,
        claimed_by_name: null,
        claimed_by_account_number: null,
      };
      out.push({
        key: `${row.company_id}:platform:${row.agent_user_id}`,
        kind: "platform",
        companyId: row.company_id,
        companyName: companyName(row.company_id),
        entry,
        record: null,
        starred: row.is_preferred,
        name: row.name,
        phone: row.phone,
        email: row.email,
        location: "",
        nextVisit: row.next_visit,
        startedAt: row.tenure_started_at,
        endedAt: row.tenure_ended_at,
      });
    }
    // Archived records whose platform connection is gone: the
    // record itself is the only seat left, and its Unlink /
    // Delete must stay reachable (the old tab's Linked block).
    for (const record of agents) {
      if (!record.archived) continue;
      const matched =
        record.link_source === "switch" &&
        record.linked_account_number &&
        preferred.some(
          (p) =>
            p.kind === "platform" &&
            p.company_id === record.company_id &&
            p.account_number === record.linked_account_number,
        );
      if (matched) continue;
      out.push({
        key: `record:${record.id}`,
        kind: "private",
        companyId: record.company_id,
        companyName: companyName(record.company_id),
        entry: null,
        record,
        starred: false,
        name: record.name,
        phone: record.phone,
        email: record.email,
        location: record.location,
        nextVisit: null,
        startedAt: record.started_at,
        endedAt: record.ended_at,
      });
    }
    return out;
  }, [agents, preferred, companyName]);

  // AT2 (owner's pick, 2026-11-16): every roster row carries
  // its truck balance, so the money shows without opening
  // anything. One best-effort read of the viewer's accounts,
  // matched to seats by the same ids the roster runs on;
  // truckTick re-reads after an in-window entry lands.
  const [accounts, setAccounts] = useState<TruckAccount[]>([]);
  const [truckTick, setTruckTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    listAccounts()
      .then((rows) => {
        if (!cancelled) setAccounts(rows);
      })
      .catch(() => {
        /* rows just carry no balance */
      });
    return () => {
      cancelled = true;
    };
  }, [truckTick]);
  const balanceFor = (seat: AgentSeat): number | null => {
    if (!seat.entry) return null;
    let found = false;
    let total = 0;
    for (const acc of accounts) {
      if (acc.status === "closed") continue;
      const matches =
        seat.entry.kind === "private"
          ? acc.private_agent_id === seat.entry.private_agent_id
          : acc.dealer_user_id === seat.entry.agent_user_id;
      if (!matches) continue;
      if (
        seat.companyId &&
        acc.dealer_company_id &&
        acc.dealer_company_id !== seat.companyId
      )
        continue;
      found = true;
      total += Number(acc.balance) || 0;
    }
    return found ? total : null;
  };

  const current = seats
    .filter((s) => s.starred)
    .sort(
      (a, b) =>
        (a.nextVisit ?? "9999").localeCompare(b.nextVisit ?? "9999") ||
        a.name.localeCompare(b.name),
    );
  const former = seats
    .filter((s) => !s.starred)
    .sort((a, b) => a.name.localeCompare(b.name));
  const ordered = [...current, ...former];
  const selected =
    ordered.find((s) => s.key === selectedKey) ?? ordered[0] ?? null;

  async function toggleStar(seat: AgentSeat) {
    if (!seat.entry || !seat.companyId) return;
    setStarBusy(true);
    setError("");
    try {
      await setAgentPreferred({
        company_id: seat.companyId,
        ...(seat.entry.kind === "private"
          ? { private_agent_id: seat.entry.private_agent_id as string }
          : { agent_user_id: seat.entry.agent_user_id as string }),
        is_preferred: !seat.starred,
      });
      toast(
        t(seat.starred ? "dealers.roster.unstarred" : "dealers.roster.starred")
          .replace("{name}", seat.name),
        { tone: "success" },
      );
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.roster.starError"),
      );
    } finally {
      setStarBusy(false);
    }
  }

  const rowFor = (seat: AgentSeat) => {
    const balance = balanceFor(seat);
    const dateLine =
      seat.starred && seat.nextVisit
        ? displayDate(seat.nextVisit)
        : !seat.starred && seat.endedAt
          ? displayDate(seat.endedAt)
          : null;
    return (
      <SideListRow
        key={seat.key}
        selected={mode === "detail" && selected?.key === seat.key}
        muted={!seat.starred}
        onSelect={() => {
          setMode("detail");
          setSelectedKey(seat.key);
        }}
        leading={<Avatar name={seat.name} size="md" />}
        title={
          <>
            {seat.name}
            {seat.starred && (
              <>
                {" "}
                <span className="tv-side-star" aria-hidden="true">
                  ★
                </span>
              </>
            )}
          </>
        }
        sub={
          [
            seat.companyName ?? "",
            seat.starred
              ? seat.location
              : seat.endedAt
                ? t("dealers.roster.ended").replace(
                    "{date}",
                    displayDate(seat.endedAt),
                  )
                : seat.location,
          ]
            .filter(Boolean)
            .join(" · ") || undefined
        }
        trailing={
          dateLine || balance != null ? (
            <span className="tv-side-rowmeta">
              {dateLine && <span>{dateLine}</span>}
              {balance != null && (
                <span
                  className={
                    balance > 0 ? "tv-side-rowbal tv-side-rowbal--owed" : "tv-side-rowbal"
                  }
                >
                  {money(balance.toFixed(2))}
                  {balance > 0 ? ` ${t("dealers.side.owed")}` : ""}
                </span>
              )}
            </span>
          ) : undefined
        }
      />
    );
  };

  return (
    <section>
      <div className="tv-dir-head">
        <SectionHeader title={t("dealers.myAgents.title")} />
        <div className="tv-dir-toggle tv-side-head-actions">
          {mode === "add" ? (
            <Button size="sm" variant="secondary" onClick={() => setMode("detail")}>
              {t("common.cancel")}
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => setMode("add")}
            >
              {t("dealers.myAgents.add")}
            </Button>
          )}{" "}
          <AgentImportButton onImported={onChanged} />
        </div>
      </div>
      <p className="tv-side-note">{t("dealers.myAgents.intro")}</p>
      <p className="tv-side-note">{t("dealers.side.pickAgentNote")}</p>
      {error && <Alert tone="danger">{error}</Alert>}

      {seats.length === 0 && mode === "detail" ? (
        <EmptyState title={t("dealers.myAgents.empty")} />
      ) : (
        <SideList
          listLabel={t("dealers.side.agentsListLabel")}
          list={
            <>
              <SideListGroup label={t("dealers.side.currentAgents")}>
                {current.length === 0 ? (
                  <p className="tv-sidelist-empty">
                    {t("dealers.roster.sectionEmpty")}
                  </p>
                ) : (
                  current.map(rowFor)
                )}
              </SideListGroup>
              <SideListDivider label={t("dealers.side.formerAgents")} />
              {former.length === 0 ? (
                <p className="tv-sidelist-empty">
                  {t("dealers.roster.sectionEmpty")}
                </p>
              ) : (
                former.map(rowFor)
              )}
            </>
          }
          panel={
            mode === "add" ? (
              <AddAgentPanel
                companies={companies}
                pickerCompanies={pickerCompanies}
                onChanged={onChanged}
                onDone={(seatKey) => {
                  setMode("detail");
                  if (seatKey) setSelectedKey(seatKey);
                }}
              />
            ) : selected ? (
              selected.entry && selected.companyId ? (
                <RosterSeatPanel
                  seat={selected}
                  starBusy={starBusy}
                  onToggleStar={() => void toggleStar(selected)}
                  onTruckChanged={() => setTruckTick((n) => n + 1)}
                />
              ) : selected.record ? (
                <RecordSeatPanel
                  seat={selected}
                  companies={companies}
                  pickerCompanies={pickerCompanies}
                  onChanged={onChanged}
                  onGone={() => {
                    setSelectedKey(null);
                    onChanged();
                  }}
                />
              ) : (
                <Panel>
                  <p className="tv-side-note">{t("dealers.myAgents.empty")}</p>
                </Panel>
              )
            ) : (
              <Panel>
                <p className="tv-side-note">{t("dealers.myAgents.empty")}</p>
              </Panel>
            )
          }
        />
      )}
    </section>
  );
}

/** The right-hand panel for a roster seat (approved design
 *  A2, rebuilt to the Side List pattern; AT2, owner's pick
 *  2026-11-16): identity first, the star control the owner's
 *  definition runs on, his facts as labeled lines (dealer,
 *  route area, next visit, phone, email), worded contact
 *  buttons for a CURRENT agent, the four tiles (next visit,
 *  truck balance, tools tagged, open claims), the WHOLE
 *  truck account in place (balance, due, record a payment /
 *  add a charge, the ledger, print statement — no separate
 *  page), the "With {agent}" line, and ONE door to his full
 *  record on the dealer page for the record's own management
 *  (facts, edit, agent code, claims, delete). */
function RosterSeatPanel({
  seat,
  starBusy,
  onToggleStar,
  onTruckChanged,
}: {
  seat: AgentSeat;
  starBusy: boolean;
  onToggleStar: () => void;
  onTruckChanged: () => void;
}) {
  const t = useT();
  const entry = seat.entry as RosterEntry;
  const firstName = seat.name.split(/\s+/)[0] ?? seat.name;
  const refId =
    entry.kind === "private" ? entry.private_agent_id : entry.agent_user_id;

  // The panel's own read for the tiles — the same roster
  // record read the dealer page's record view makes. Best
  // effort: when it fails, the tiles simply never appear.
  // tick re-reads after an in-window truck entry lands.
  const [detail, setDetail] = useState<RosterAgentDetail | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    setDetail(null);
    if (!seat.companyId || !refId) return;
    let cancelled = false;
    getRosterAgent(seat.companyId, entry.kind, refId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        /* the tiles just stay off for this agent */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seat.key, tick]);
  const truckTotal = detail
    ? detail.truck_accounts.reduce(
        (sum, a) => sum + (Number(a.balance) || 0),
        0,
      )
    : null;
  const openClaims = detail
    ? detail.claims.filter((c) => c.is_open).length
    : null;

  // AT2: the whole truck account lives in this window — each
  // slotted account's full detail (entries + schedule) rides
  // alongside the roster read.
  const [accountDetails, setAccountDetails] = useState<
    Record<string, TruckAccountDetail>
  >({});
  useEffect(() => {
    setAccountDetails({});
    if (!detail || detail.truck_accounts.length === 0) return;
    let cancelled = false;
    Promise.all(
      detail.truck_accounts.map((slot) =>
        getAccount(slot.id)
          .then((data) => [slot.id, data] as const)
          .catch(() => null),
      ),
    ).then((pairs) => {
      if (cancelled) return;
      const next: Record<string, TruckAccountDetail> = {};
      for (const pair of pairs) if (pair) next[pair[0]] = pair[1];
      setAccountDetails(next);
    });
    return () => {
      cancelled = true;
    };
  }, [detail, tick]);

  const refreshTruck = () => {
    setTick((n) => n + 1);
    onTruckChanged();
  };

  const nextVisitLine = entry.ended_at
    ? `${t("dealers.side.tile.endedOn")}: ${displayDate(entry.ended_at)}`
    : entry.next_visit
      ? t("dealers.roster.nextVisit").replace(
          "{date}",
          displayDate(entry.next_visit),
        ) +
        (entry.route_frequency
          ? ` · ${freqLabel(t, entry.route_frequency)}`
          : "")
      : null;

  return (
    <Panel>
      <div className="tv-side-panelbody">
        <div className="tv-side-agent-head">
          <Avatar name={seat.name} size="lg" />
          <div className="tv-side-dealer-id">
            <h3 className="tv-side-panel-name">{seat.name}</h3>
            <p className="tv-side-badges">
              {entry.kind === "platform" ? (
                <Badge tone="neutral">{t("dealers.roster.kindPlatform")}</Badge>
              ) : entry.claimed_by_name ? (
                <Badge tone="success">
                  {t("dealers.myAgents.claimedBy")
                    .replace("{name}", entry.claimed_by_name)
                    .replace("{number}", entry.claimed_by_account_number ?? "")}
                </Badge>
              ) : (
                <Badge tone="neutral">{t("dealers.myAgents.onlyYours")}</Badge>
              )}
              {entry.account_number && (
                <span className="tv-agent-meta">{entry.account_number}</span>
              )}
            </p>
            <p className="tv-side-agent-sub">
              {[seat.companyName ?? "", entry.location, tenureText(t, entry)]
                .filter((part) => Boolean(part) && part !== "—")
                .join(" · ")}
            </p>
          </div>
          <div className="tv-side-head-actions">
            <Button
              size="sm"
              variant={seat.starred ? "secondary" : "primary"}
              loading={starBusy}
              onClick={onToggleStar}
            >
              {t(seat.starred ? "dealers.side.unstar" : "dealers.side.star")}
            </Button>
          </div>
        </div>

        <div className="tv-side-factlines">
          {seat.companyName && (
            <p>
              <span className="tv-fact-label">
                {t("dealers.side.fact.dealer")}:{" "}
              </span>
              <span className="tv-side-link">{seat.companyName}</span>
            </p>
          )}
          {entry.location && (
            <p>
              <span className="tv-fact-label">
                {t("dealers.roster.locationLabel")}:{" "}
              </span>
              {entry.location}
            </p>
          )}
          {nextVisitLine && (
            <p>
              <span className="tv-side-link">{nextVisitLine}</span>
            </p>
          )}
          {seat.phone && (
            <p>
              <span className="tv-fact-label">
                {t("dealers.myAgents.phoneLabel")}:{" "}
              </span>
              <a className="tv-side-link" href={`tel:${phoneHref(seat.phone)}`}>
                {formatPhone(seat.phone)}
              </a>
            </p>
          )}
          {seat.email && (
            <p>
              <span className="tv-fact-label">
                {t("dealers.myAgents.emailLabel")}:{" "}
              </span>
              <a className="tv-side-link" href={`mailto:${seat.email}`}>
                {seat.email}
              </a>
            </p>
          )}
        </div>

        {seat.starred && (seat.phone || seat.email) && (
          <div className="tv-side-contact-actions">
            {seat.phone && (
              <HrefButton
                href={`tel:${phoneHref(seat.phone)}`}
                variant="primary"
                size="sm"
              >
                {t("dealers.side.callName").replace("{name}", firstName)} —{" "}
                {formatPhone(seat.phone)}
              </HrefButton>
            )}
            {seat.phone && (
              <HrefButton
                href={`sms:${phoneHref(seat.phone)}`}
                variant="secondary"
                size="sm"
              >
                {t("dealers.side.textName").replace("{name}", firstName)}
              </HrefButton>
            )}
            {seat.email && (
              <HrefButton
                href={`mailto:${seat.email}`}
                variant="secondary"
                size="sm"
              >
                {t("dealers.side.emailName").replace("{name}", firstName)}
              </HrefButton>
            )}
          </div>
        )}

        {detail && (
          <div className="tv-side-tiles">
            <div className="tv-side-tile">
              <span className="tv-side-tile-label">
                {t("dealers.side.tile.nextVisit")}
              </span>
              <span className="tv-side-tile-value">
                {entry.next_visit ? displayDate(entry.next_visit) : "—"}
              </span>
              {entry.route_frequency && (
                <span className="tv-side-tile-sub">
                  {freqLabel(t, entry.route_frequency)}
                </span>
              )}
            </div>
            <div className="tv-side-tile">
              <span className="tv-side-tile-label">
                {t("dealers.side.tile.truckBalance")}
              </span>
              <span className="tv-side-tile-value tv-side-money">
                {detail.truck_accounts.length > 0
                  ? money((truckTotal ?? 0).toFixed(2))
                  : "—"}
              </span>
              {detail.truck_accounts.length === 0 && (
                <span className="tv-side-tile-sub">
                  {t("dealers.record.truckEmpty")}
                </span>
              )}
            </div>
            <div className="tv-side-tile">
              <span className="tv-side-tile-label">
                {t("dealers.side.tile.toolsTagged")}
              </span>
              <span className="tv-side-tile-value">{detail.tools_tagged}</span>
            </div>
            <div className="tv-side-tile">
              <span className="tv-side-tile-label">
                {t("dealers.side.tile.openClaims")}
              </span>
              <span className="tv-side-tile-value">{openClaims ?? 0}</span>
            </div>
          </div>
        )}

        {detail &&
          detail.truck_accounts.map((slot) => (
            <AgentTruckSection
              key={slot.id}
              slot={slot}
              data={accountDetails[slot.id] ?? null}
              onChanged={refreshTruck}
            />
          ))}

        {detail && (
          <AgentWithLine
            detail={detail}
            accountDetails={accountDetails}
            companyName={seat.companyName}
            firstName={firstName}
          />
        )}

        {seat.companyId && refId && (
          <div>
            <LinkButton
              variant="secondary"
              block
              to={`/dealers?dealer=${seat.companyId}&agent=${entry.kind}:${refId}`}
            >
              {t("dealers.side.openFullRecord")}
              {" →"}
            </LinkButton>
          </div>
        )}
      </div>
    </Panel>
  );
}

const ENTRY_LABEL_KEYS: Record<TruckEntry["kind"], string> = {
  charge: "truck.wb.kindCharge",
  payment: "truck.wb.kindPayment",
  adjustment: "truck.wb.kindAdjustment",
};

function entryItemPath(entry: TruckEntry): string | null {
  if (!entry.item_link_id) return null;
  return entry.item_kind === "battery"
    ? `/inventory/batteries/${entry.item_link_id}`
    : `/inventory/${entry.item_link_id}`;
}

/** AT2 (owner's pick, 2026-11-16): one truck account living
 *  INSIDE the agent's window — balance and what's due,
 *  Record a payment / Add a charge in place (the workbench's
 *  own rules: a charge needs the customer-kept tab and a
 *  note), Print statement, and the ledger in the owner's
 *  columns (DATE · TYPE · NAME · AMOUNT · BALANCE), newest
 *  first, six rows until "See the full history" opens the
 *  rest in place. The separate truck-account page trip is
 *  gone. */
function AgentTruckSection({
  slot,
  data,
  onChanged,
}: {
  slot: RosterTruckAccount;
  data: TruckAccountDetail | null;
  onChanged: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [form, setForm] = useState<null | "payment" | "charge">(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [entryDate, setEntryDate] = useState(() => todayLocalIso());
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const account = data?.account ?? null;
  const entries = data?.entries ?? [];
  let runningCents = 0;
  const rows = entries.map((entry) => {
    runningCents += Math.round(Number(entry.amount) * 100);
    return { entry, balanceAfter: runningCents / 100 };
  });
  const shown = [...rows].reverse().slice(0, showAll ? undefined : 6);
  const canCharge = account?.customer_maintained ?? false;
  const isActive = account?.status === "active";
  const chargeNeedsNote = form === "charge" && note.trim() === "";

  async function submit() {
    if (!form || amount === "" || chargeNeedsNote) return;
    setBusy(true);
    try {
      await addEntry(slot.id, {
        kind: form,
        amount,
        note: note.trim(),
        item_link_id: null,
        entry_date: entryDate || null,
      });
      toast(
        t(
          form === "payment"
            ? "truck.wb.toastPaymentRecorded"
            : "truck.wb.toastEntryRecorded",
        ),
        { tone: "success" },
      );
      setForm(null);
      setAmount("");
      setNote("");
      setEntryDate(todayLocalIso());
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("truck.wb.genericFailed"),
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  async function printStatement() {
    try {
      const blob = await downloadStatement(slot.id, "pdf");
      downloadBlob(blob, `truck-statement-${slot.id}.pdf`);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("truck.wb.toastStatementFailed"),
        { tone: "danger" },
      );
    }
  }

  const dueBits: string[] = [];
  if (Number(slot.amount_past_due) > 0) {
    dueBits.push(
      t("dealers.side.pastDueLine").replace(
        "{amount}",
        money(slot.amount_past_due),
      ),
    );
  } else if (slot.payment_amount && slot.next_due_date) {
    dueBits.push(
      t("dealers.side.dueLine")
        .replace("{amount}", money(slot.payment_amount))
        .replace("{date}", displayDate(slot.next_due_date)),
    );
  }
  if (account?.payment_amount) {
    dueBits.push(
      t(
        account.payment_cadence === "weekly"
          ? "dealers.side.paysWeekly"
          : "dealers.side.paysBiweekly",
      ).replace("{amount}", money(account.payment_amount)),
    );
  }

  return (
    <div className="tv-agent-truck">
      <p className="tv-agent-truck-title">{t("dealers.side.truckAccount")}</p>
      <p className="tv-agent-truck-balance">
        <span className="tv-fact-label">{t("dealers.side.balanceWord")}: </span>
        <strong>{money(slot.balance)}</strong>
        {dueBits.length > 0 && (
          <span className="tv-agent-truck-due"> · {dueBits.join(" · ")}</span>
        )}
      </p>
      {isActive && (
        <div className="tv-agent-truck-actions">
          <Button
            size="sm"
            variant={form === "payment" ? "secondary" : "primary"}
            onClick={() => setForm(form === "payment" ? null : "payment")}
          >
            {t("dealers.side.recordPayment")}
          </Button>
          {canCharge && (
            <Button
              size="sm"
              variant={form === "charge" ? "primary" : "secondary"}
              onClick={() => setForm(form === "charge" ? null : "charge")}
            >
              {t("dealers.side.addCharge")}
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={() => void printStatement()}>
            {t("dealers.side.printStatement")}
          </Button>
        </div>
      )}
      {form && (
        <div className="tv-agent-truck-form">
          <div className="tv-agent-truck-formgrid">
            <FormField label={t("truck.wb.amountLabel")} htmlFor="at2-amount">
              <TextInput
                id="at2-amount"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0.00"
              />
            </FormField>
            <FormField label={t("truck.wb.dateLabel")} htmlFor="at2-date">
              <DatePicker
                id="at2-date"
                value={entryDate}
                onChange={setEntryDate}
                clearable
              />
            </FormField>
          </div>
          <FormField
            label={t("truck.wb.noteLabel")}
            htmlFor="at2-note"
            hint={
              form === "charge"
                ? t("truck.wb.chargeNoteHint")
                : t("truck.wb.paymentNoteHint")
            }
          >
            <TextInput
              id="at2-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={
                form === "charge"
                  ? t("truck.wb.chargeNotePlaceholder")
                  : t("truck.wb.paymentNotePlaceholder")
              }
            />
          </FormField>
          <div className="tv-agent-truck-formbtns">
            <Button
              size="sm"
              loading={busy}
              disabled={amount === "" || chargeNeedsNote}
              onClick={() => void submit()}
            >
              {t(
                form === "payment"
                  ? "dealers.side.recordPayment"
                  : "dealers.side.addCharge",
              )}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setForm(null)}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}
      {entries.length > 0 ? (
        <div className="tv-agent-ledger" role="table">
          <div className="tv-agent-ledger-thead" role="row">
            <span role="columnheader">{t("truck.wb.colDate")}</span>
            <span role="columnheader">{t("dealers.side.colType")}</span>
            <span role="columnheader">{t("dealers.side.colName")}</span>
            <span role="columnheader">{t("truck.wb.colAmount")}</span>
            <span role="columnheader">{t("truck.wb.colBalance")}</span>
          </div>
          {shown.map(({ entry, balanceAfter }) => {
            const negative = Number(entry.amount) < 0;
            const path = entryItemPath(entry);
            return (
              <div className="tv-agent-ledger-row" role="row" key={entry.id}>
                <div role="cell">{displayDate(entry.entry_date)}</div>
                <div role="cell">
                  <Badge
                    tone={
                      entry.kind === "payment"
                        ? "success"
                        : entry.kind === "charge"
                          ? "accent"
                          : "neutral"
                    }
                  >
                    {t(ENTRY_LABEL_KEYS[entry.kind] as never)}
                  </Badge>
                </div>
                <div role="cell">
                  {path ? (
                    <Link to={path} className="tv-agent-ledger-itemlink">
                      {entry.item_name ?? entry.note}
                    </Link>
                  ) : (
                    (entry.item_name ?? entry.note) || "—"
                  )}
                </div>
                <div
                  role="cell"
                  className={negative ? "tv-agent-ledger-amount-neg" : "tv-agent-ledger-amount"}
                >
                  {negative ? "−" : "+"}
                  {money(String(Math.abs(Number(entry.amount))))}
                </div>
                <div role="cell" className="tv-agent-ledger-balance">
                  {money(String(balanceAfter))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        data && <p className="tv-side-note">{t("truck.wb.ledgerEmptyBody")}</p>
      )}
      {rows.length > 6 && (
        <div>
          <Button variant="secondary" size="sm" onClick={() => setShowAll(!showAll)}>
            {t(showAll ? "dealers.side.showLess" : "dealers.side.seeFullHistory")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** AT2's "With {agent}" line: the relationship at a glance —
 *  tools tagged with his company, the last purchase on the
 *  tab, and any open claim, each only when it's real. */
function AgentWithLine({
  detail,
  accountDetails,
  companyName,
  firstName,
}: {
  detail: RosterAgentDetail;
  accountDetails: Record<string, TruckAccountDetail>;
  companyName: string | null;
  firstName: string;
}) {
  const t = useT();
  const parts: string[] = [];
  if (companyName) {
    parts.push(
      t(
        detail.tools_tagged === 1
          ? "dealers.side.withToolOne"
          : "dealers.side.withTools",
      )
        .replace("{count}", String(detail.tools_tagged))
        .replace("{company}", companyName),
    );
  }
  let last: TruckEntry | null = null;
  for (const data of Object.values(accountDetails)) {
    for (const entry of data.entries) {
      if (entry.kind !== "charge") continue;
      if (!last || entry.entry_date > last.entry_date) last = entry;
    }
  }
  if (last) {
    const named = last.item_name ?? (last.note || null);
    if (named) {
      parts.push(
        t("dealers.side.lastPurchase")
          .replace("{date}", displayDate(last.entry_date))
          .replace("{item}", named)
          .replace("{amount}", money(last.amount)),
      );
    }
  }
  const open = detail.claims.filter((c) => c.is_open);
  if (open.length === 1) {
    parts.push(
      t("dealers.side.openClaimOne")
        .replace("{item}", open[0].item_name)
        .replace("{date}", displayDate(open[0].created_at.slice(0, 10))),
    );
  } else if (open.length > 1) {
    parts.push(
      t("dealers.side.openClaimsMany").replace("{count}", String(open.length)),
    );
  }
  if (parts.length === 0) return null;
  return (
    <p className="tv-agent-withline">
      <span className="tv-fact-label">
        {t("dealers.side.withName").replace("{name}", firstName)}:{" "}
      </span>
      {parts.join(" · ")}
    </p>
  );
}

/** The right-hand panel for a record seat — a company-less
 *  record, or an archived record whose connection is gone.
 *  There is no company seat, so there are no claims/truck
 *  tiles and no star (the star lives on a company connection);
 *  the panel carries the record's own facts and the management
 *  the old tab offered it: edit, link, unlink, delete. */
function RecordSeatPanel({
  seat,
  companies,
  pickerCompanies,
  onChanged,
  onGone,
}: {
  seat: AgentSeat;
  companies: DealerCompany[];
  pickerCompanies: DealerCompany[];
  onChanged: () => void;
  onGone: () => void;
}) {
  const t = useT();
  const record = seat.record as PrivateAgent;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<PrivateAgentWrite>(EMPTY_AGENT);
  const [linking, setLinking] = useState(false);
  const [linkNumber, setLinkNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const optionsFor = (currentId: string | null): DealerCompany[] => {
    if (currentId && !pickerCompanies.some((c) => c.id === currentId)) {
      const current = companies.find((c) => c.id === currentId);
      if (current) return [...pickerCompanies, current];
    }
    return pickerCompanies;
  };

  function startEditing() {
    setForm({
      company_id: record.company_id,
      name: record.name,
      phone: record.phone,
      email: record.email,
      notes: record.notes,
    });
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!form.name.trim()) {
      setError(t("dealers.myAgents.nameRequired"));
      return;
    }
    setBusy(true);
    try {
      await updatePrivateAgent(record.id, form);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.saveError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function doLink() {
    setError("");
    if (!linkNumber.trim()) {
      setError(t("dealers.myAgents.linkNumberRequired"));
      return;
    }
    setBusy(true);
    try {
      await linkPrivateAgent(record.id, linkNumber.trim());
      setLinking(false);
      setLinkNumber("");
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.linkError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function doUnlink() {
    setError("");
    try {
      await unlinkPrivateAgent(record.id);
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.unlinkError"),
      );
    }
  }

  async function doDelete() {
    if (
      !window.confirm(
        t("dealers.myAgents.deleteConfirm").replace("{name}", record.name),
      )
    )
      return;
    try {
      await deletePrivateAgent(record.id);
      onGone();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.deleteError"),
      );
    }
  }

  const routeLine = record.route_frequency
    ? `${freqLabel(t, record.route_frequency)}${
        dayLabel(t, record.route_day_of_week)
          ? ` · ${dayLabel(t, record.route_day_of_week)}`
          : ""
      }`
    : t("dealers.roster.routeNone");

  return (
    <Panel>
      <div className="tv-side-panelbody">
        <div className="tv-side-agent-head">
          <Avatar name={record.name} size="lg" />
          <div className="tv-side-dealer-id">
            <h3 className="tv-side-panel-name">{record.name}</h3>
            <p className="tv-side-badges">
              {record.archived ? (
                <Badge tone="neutral">{t("dealers.myAgents.linkedTitle")}</Badge>
              ) : (
                <Badge tone="neutral">{t("dealers.myAgents.onlyYours")}</Badge>
              )}
            </p>
            <p className="tv-side-agent-sub">
              {seat.companyName ?? t("dealers.myAgents.noCompany")}
            </p>
          </div>
        </div>
        {error && <Alert tone="danger">{error}</Alert>}
        {editing ? (
          <form onSubmit={(e) => void save(e)} className="tv-side-form">
            <div style={formGridStyle}>
              <FormField label={t("dealers.myAgents.nameLabel")} required>
                <TextInput
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.myAgents.company")}>
                <Select
                  value={form.company_id ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, company_id: e.target.value || null })
                  }
                >
                  <option value="">{t("dealers.myAgents.noCompany")}</option>
                  {optionsFor(form.company_id).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label={t("dealers.myAgents.phoneLabel")}>
                <TextInput
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.myAgents.emailLabel")}>
                <TextInput
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </FormField>
            </div>
            <FormField label={t("dealers.myAgents.notesLabel")}>
              <TextArea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                rows={2}
              />
            </FormField>
            <div className="tv-side-form-actions">
              <Button type="submit" loading={busy}>
                {t("dealers.myAgents.saveChanges")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditing(false)}
              >
                {t("common.cancel")}
              </Button>
              <ContactPickButton
                onPick={(contact) =>
                  setForm((current) => ({
                    ...current,
                    name: contact.name ?? current.name,
                    phone: contact.phone ?? current.phone,
                    email: contact.email ?? current.email,
                  }))
                }
              />
            </div>
          </form>
        ) : (
          <>
            <dl className="tv-record-facts">
              <div>
                <dt>{t("dealers.roster.locationLabel")}</dt>
                <dd>{record.location || "—"}</dd>
              </div>
              <div>
                <dt>{t("dealers.record.routeTitle")}</dt>
                <dd>{routeLine}</dd>
              </div>
              <div>
                <dt>{t("dealers.roster.startedLabel")}</dt>
                <dd>{displayDate(record.started_at)}</dd>
              </div>
              <div>
                <dt>{t("dealers.roster.endedLabel")}</dt>
                <dd>{displayDate(record.ended_at)}</dd>
              </div>
              {record.phone && (
                <div>
                  <dt>{t("dealers.myAgents.phoneLabel")}</dt>
                  <dd>{formatPhone(record.phone)}</dd>
                </div>
              )}
              {record.email && (
                <div>
                  <dt>{t("dealers.myAgents.emailLabel")}</dt>
                  <dd>{record.email}</dd>
                </div>
              )}
            </dl>
            {record.notes && <p className="tv-agent-notes">{record.notes}</p>}
            {record.archived ? (
              <p className="tv-agent-meta">
                {t("dealers.myAgents.linkedLine").replace(
                  "{number}",
                  record.linked_account_number ??
                    t("dealers.myAgents.linkedFallback"),
                )}
              </p>
            ) : record.link_source === "takeover" ? (
              <p className="tv-agent-meta">
                {t("dealers.myAgents.claimedBy")
                  .replace("{name}", record.claimed_by_name ?? "")
                  .replace("{number}", record.claimed_by_account_number ?? "")}
              </p>
            ) : (
              <p className="tv-agent-meta">
                {t("dealers.myAgents.codeLabel")}:{" "}
                <span className="tv-agent-code-sm">
                  {record.agent_code_display}
                </span>
              </p>
            )}
            <div className="tv-side-form-actions">
              <Button size="sm" variant="secondary" onClick={startEditing}>
                {t("dealers.myAgents.editButton")}
              </Button>
              {record.archived ? (
                <Button size="sm" variant="secondary" onClick={() => void doUnlink()}>
                  {t("dealers.myAgents.unlink")}
                </Button>
              ) : (
                record.link_source !== "takeover" && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setLinking((v) => !v)}
                  >
                    {t("dealers.myAgents.linkAccount")}
                  </Button>
                )
              )}
              <Button size="sm" variant="danger" onClick={() => void doDelete()}>
                {t("common.delete")}
              </Button>
            </div>
            {linking && (
              <div className="tv-side-form">
                <p className="tv-side-note">
                  {t("dealers.myAgents.linkIntro").replace("{name}", record.name)}
                </p>
                <div className="tv-side-form-actions">
                  <FormField label={t("dealers.myAgents.theirAccountNumber")}>
                    <TextInput
                      value={linkNumber}
                      onChange={(e) => setLinkNumber(e.target.value)}
                      placeholder="TV-D-000123"
                    />
                  </FormField>
                  <Button onClick={() => void doLink()} loading={busy}>
                    {t("dealers.myAgents.linkSubmit")}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

/** The Add panel: the private-record form the tab has always
 *  carried (with its contact pick), plus the connect-by-account-
 *  number door that used to ride the Preferred panel — type a
 *  registered agent's number for a company and he lands on the
 *  list at once. */
function AddAgentPanel({
  companies,
  pickerCompanies,
  onChanged,
  onDone,
}: {
  companies: DealerCompany[];
  pickerCompanies: DealerCompany[];
  onChanged: () => void;
  onDone: (seatKey: string | null) => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [form, setForm] = useState<PrivateAgentWrite>(EMPTY_AGENT);
  const [connCompany, setConnCompany] = useState("");
  const [connAccount, setConnAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const optionsFor = (currentId: string | null): DealerCompany[] => {
    if (currentId && !pickerCompanies.some((c) => c.id === currentId)) {
      const current = companies.find((c) => c.id === currentId);
      if (current) return [...pickerCompanies, current];
    }
    return pickerCompanies;
  };

  async function saveAgent(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!form.name.trim()) {
      setError(t("dealers.myAgents.nameRequired"));
      return;
    }
    setBusy(true);
    try {
      const created = await createPrivateAgent(form);
      onChanged();
      toast(t("dealers.myAgents.savedNext"), { tone: "success" });
      onDone(
        `${created.company_id ?? "none"}:private:${created.id}`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.saveError"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function connect() {
    setError("");
    if (!connCompany) {
      setError(t("dealers.myAgents.prefCompanyRequired"));
      return;
    }
    if (!connAccount.trim()) {
      setError(t("dealers.myAgents.prefPickRequired"));
      return;
    }
    setBusy(true);
    try {
      const row = await addPreferred({
        company_id: connCompany,
        agent_account_number: connAccount.trim(),
      });
      onChanged();
      onDone(
        row.agent_user_id
          ? `${row.company_id}:platform:${row.agent_user_id}`
          : null,
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.prefAddError"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={t("dealers.myAgents.new")}>
      <div className="tv-side-panelbody">
        {error && <Alert tone="danger">{error}</Alert>}
        <form onSubmit={(e) => void saveAgent(e)} className="tv-side-form">
          <div style={formGridStyle}>
            <FormField label={t("dealers.myAgents.nameLabel")} required>
              <TextInput
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </FormField>
            <FormField label={t("dealers.myAgents.company")}>
              <Select
                value={form.company_id ?? ""}
                onChange={(e) =>
                  setForm({ ...form, company_id: e.target.value || null })
                }
              >
                <option value="">{t("dealers.myAgents.noCompany")}</option>
                {optionsFor(form.company_id).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label={t("dealers.myAgents.phoneLabel")}>
              <TextInput
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
            </FormField>
            <FormField label={t("dealers.myAgents.emailLabel")}>
              <TextInput
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </FormField>
          </div>
          <FormField label={t("dealers.myAgents.notesLabel")}>
            <TextArea
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              rows={2}
            />
          </FormField>
          <div className="tv-side-form-actions">
            <Button type="submit" loading={busy}>
              {t("dealers.myAgents.addSubmit")}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onDone(null)}
            >
              {t("common.cancel")}
            </Button>
            <ContactPickButton
              onPick={(contact) =>
                setForm((current) => ({
                  ...current,
                  name: contact.name ?? current.name,
                  phone: contact.phone ?? current.phone,
                  email: contact.email ?? current.email,
                }))
              }
            />
          </div>
        </form>

        <div className="tv-side-connect">
          <h4 className="tv-side-connect-title">
            {t("dealers.side.connectTitle")}
          </h4>
          <p className="tv-side-note">{t("dealers.side.connectNote")}</p>
          <div style={formGridStyle}>
            <FormField label={t("dealers.myAgents.company")}>
              <Select
                value={connCompany}
                onChange={(e) => setConnCompany(e.target.value)}
              >
                <option value="">{t("dealers.myAgents.pickCompany")}</option>
                {optionsFor(connCompany || null).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label={t("dealers.myAgents.dealerAccountNumber")}>
              <TextInput
                value={connAccount}
                onChange={(e) => setConnAccount(e.target.value)}
                placeholder="TV-D-000123"
              />
            </FormField>
          </div>
          <div className="tv-side-form-actions">
            <Button onClick={() => void connect()} loading={busy}>
              {t("dealers.side.connectSubmit")}
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  );
}
