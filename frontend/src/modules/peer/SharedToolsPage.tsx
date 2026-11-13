import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  BrandIcon,
  Button,
  DatePicker,
  EmptyState,
  FormField,
  ItemThumb,
  Modal,
  Panel,
  SearchBar,
  SectionPageHeader,
  Spinner,
  Tabs,
  TextArea,
  useToast,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { createBorrowRequest } from "../borrowing/api";
import { dueDateToIso } from "../borrowing/format";
import { RequireAuth } from "../core";
import { accountTypeLabel } from "../core/accountTypes";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import SharingSettings from "../core/SharingSettings";
import type { ShareRecipientGroup, SharingSummary } from "../core/sharing";
import { PeerToolCard } from "./components/PeerToolCard";
import type {
  PeerIncomingGrant,
  PeerItem,
  PeerListResponse,
  PeerOutgoingGrant,
  PeerOverview,
  PeerPerson,
} from "./types";

/**
 * Shared tools (peer sharing, owner directive 2026-10-17).
 *
 * The borrowing-discovery surface: search across everyone who
 * shares their list with me ("who has this tool?"), browse one
 * person's list, and answer invites. What I see of a tool is the
 * fixed peer payload — identity + photos + the owner's name and
 * account number. No prices, no notes, no serials: that data never
 * leaves the owner's vault. Borrowing (2026-10-18) grows out of
 * these grants: the item detail offers "Request to borrow", which
 * files a request the owner answers from their Borrowing page.
 *
 * Managing MY side — inviting people, revoking, hiding tools —
 * lives in the Sharing settings tab (the same SharingSettings
 * component Settings → Sharing renders — one surface, two
 * seats), out of the daily flow.
 *
 * Main tab layout (program lane 1, 2026-11-09): the kit header
 * (SectionPageHeader) + Steel tabs. Sweep Phase E lane E1
 * (2026-11-12, Ryan's sharing-hub spec): the tabs are now the
 * four AUDIENCES — Employer · Insurance company · Coworkers ·
 * Employees — plus the explainer and the settings tab. Each
 * audience tab is filtered from the REAL sharing data (see the
 * audience components below): tier (consent) sharing's two
 * recipient groups ARE the Employer (shop_company) and
 * Insurance company audiences; peer grants are the Coworkers
 * audience; shop crew memberships name the actual Employer
 * (shops I belong to) and Employees (my roster), and a peer
 * counterparty is surfaced under Employer/Employees only when
 * a membership row names the same user id. The old Shared
 * with me + I am sharing tabs fold into Coworkers — that is
 * the audience they always described. The consent model is
 * untouched: this page only reads and organizes what the
 * existing endpoints already expose to this user. Deep links:
 * #employer / #insurance / #coworkers / #employees / #settings
 * pick the tab; the legacy #shared-with-me and #sharing
 * (the peer invite notifications point at them) remap to
 * Coworkers, where that content now lives.
 */

/**
 * "Your sharing" (Package C): the owner's own sharing at a glance,
 * on the page where sharing is browsed — tier sharing per group
 * (on/off + how many items resolve as shared right now, rules
 * included) and peer grant counts, with the door to the Sharing
 * settings tab where it's all managed. Read-only: no write paths
 * here. A failed summary fetch hides the panel rather than
 * breaking the page — the counts are a convenience, not the
 * surface's job. It seats on the How it works tab (E1: the
 * hub's landing tab opens with the at-a-glance picture).
 */
function YourSharingPanel({ onManage }: { onManage: () => void }) {
  const t = useT();
  const [summary, setSummary] = useState<SharingSummary | null>(null);

  useEffect(() => {
    let live = true;
    api<SharingSummary>("/core/sharing/summary")
      .then((data) => {
        if (live) setSummary(data);
      })
      .catch(() => {
        /* panel simply doesn't render */
      });
    return () => {
      live = false;
    };
  }, []);

  if (!summary) return null;
  const peer = summary.peer;
  return (
    <Panel title="Your sharing" variant="plate">
      <div style={{ display: "grid", gap: "0.5rem" }}>
        {summary.groups.map((g) => (
          <p key={g.recipient_group} style={{ margin: 0 }}>
            <strong>{accountTypeLabel(g.recipient_group)}:</strong>{" "}
            {g.enabled ? (
              <>
                sharing on — {g.shared_count} item
                {g.shared_count === 1 ? "" : "s"} shared
                {g.rule_count > 0 &&
                  ` (${g.rule_count} rule${g.rule_count === 1 ? "" : "s"})`}
              </>
            ) : (
              <span style={{ color: "var(--text-muted)" }}>sharing off</span>
            )}
          </p>
        ))}
        <p style={{ margin: 0 }}>
          <strong>People:</strong>{" "}
          {peer.given_accepted} {peer.given_accepted === 1 ? "person sees" : "people see"}{" "}
          your list
          {peer.given_pending > 0 && ` · ${peer.given_pending} invited`}
          {" · "}
          {peer.received_accepted}{" "}
          {peer.received_accepted === 1 ? "list is" : "lists are"} shared
          with you
          {peer.received_pending > 0 &&
            ` · ${peer.received_pending} waiting for your answer`}
        </p>
        <div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onManage}
          >
            {t("shared.sharing.manage")}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

function ItemGrid({
  items,
  showOwner,
  onOpen,
}: {
  items: PeerItem[];
  showOwner: boolean;
  onOpen: (item: PeerItem) => void;
}) {
  return (
    <div
      style={{
        display: "grid",
        gap: "var(--space-3)",
        gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 260px), 1fr))",
      }}
    >
      {items.map((item) => (
        <PeerToolCard
          key={`${item.owner.id}-${item.id}`}
          item={item}
          showOwner={showOwner}
          onOpen={() => onOpen(item)}
        />
      ))}
    </div>
  );
}

function ItemDetailModal({
  item,
  onClose,
}: {
  item: PeerItem | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  // The borrow-request form lives inside the detail modal: "info"
  // shows the item; "form" asks for an optional return-by date and
  // note, then files the request with the borrowing module. The
  // server re-checks the grant, the exclusions, and the one-active-
  // lend rule — this form is a convenience, not the gate.
  const [mode, setMode] = useState<"info" | "form">("info");
  const [due, setDue] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setMode("info");
    setDue("");
    setNotes("");
    setError("");
    setBusy(false);
  }, [item?.id, item?.owner.id]);

  async function sendRequest() {
    if (!item) return;
    setBusy(true);
    setError("");
    try {
      await createBorrowRequest({
        owner_id: item.owner.id,
        item_kind: item.kind === "battery" ? "battery" : "tool",
        item_id: item.id,
        due_at: dueDateToIso(due),
        notes: notes.trim(),
      });
      toast(
        `${item.owner.name.split(" ")[0] || "The owner"} will see your request in their Borrowing list.`,
        { tone: "success", title: "Request sent" },
      );
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't send that request.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={item !== null}
      onClose={onClose}
      title={item?.name}
      size="lg"
      footer={
        mode === "form" ? (
          <>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setMode("info")}
              disabled={busy}
            >
              Back
            </Button>
            <Button type="button" loading={busy} onClick={() => void sendRequest()}>
              Send request
            </Button>
          </>
        ) : (
          <>
            <Button type="button" variant="secondary" onClick={onClose}>
              Close
            </Button>
            <Button type="button" onClick={() => setMode("form")}>
              Request to borrow
            </Button>
          </>
        )
      }
    >
      {item && (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <ItemThumb
            src={item.photos[0] ?? null}
            name={item.name}
            aspectRatio="16 / 9"
            fit="cover"
          />
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr",
              gap: "0.45rem 0.75rem",
              margin: 0,
            }}
          >
            <dt style={{ color: "var(--text-muted)" }}>Brand</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{item.brand || "—"}</dd>
            <dt style={{ color: "var(--text-muted)" }}>Model</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{item.model || "—"}</dd>
            <dt style={{ color: "var(--text-muted)" }}>Category</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>
              {item.category || "—"}
            </dd>
            <dt style={{ color: "var(--text-muted)" }}>Owner</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>
              {item.owner.name} · {item.owner.account_number}
            </dd>
          </dl>
          {item.is_set && item.set && (
            <div style={{ display: "grid", gap: "0.5rem" }}>
              <p style={{ fontWeight: 600, margin: 0 }}>
                Inside this set
              </p>
              {item.set.core_pieces.length > 0 && (
                <div>
                  <p style={{ margin: "0 0 0.25rem", color: "var(--text-muted)", fontSize: "0.9rem" }}>
                    Core pieces
                  </p>
                  <ul style={{ margin: 0, paddingLeft: "1.1rem", display: "grid", gap: "0.2rem" }}>
                    {item.set.core_pieces.map((piece, i) => (
                      <li key={i}>
                        {piece.name}
                        {piece.part_number && (
                          <span style={{ color: "var(--text-muted)" }}>
                            {" "}· {piece.part_number}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {item.set.include_addons &&
                (item.set.addon_pieces.length > 0 || item.set.attached_tools.length > 0) && (
                  <div>
                    <p style={{ margin: "0 0 0.25rem", color: "var(--text-muted)", fontSize: "0.9rem" }}>
                      Addons included
                    </p>
                    <ul style={{ margin: 0, paddingLeft: "1.1rem", display: "grid", gap: "0.2rem" }}>
                      {item.set.addon_pieces.map((piece, i) => (
                        <li key={`ap-${i}`}>
                          {piece.name}
                          {piece.part_number && (
                            <span style={{ color: "var(--text-muted)" }}>
                              {" "}· {piece.part_number}
                            </span>
                          )}
                        </li>
                      ))}
                      {item.set.attached_tools.map((t) => (
                        <li key={t.id}>
                          {t.name}
                          {(t.brand || t.model) && (
                            <span style={{ color: "var(--text-muted)" }}>
                              {" "}· {[t.brand, t.model].filter(Boolean).join(" ")}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              {!item.set.include_addons && (
                <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
                  The owner keeps this set's addons out of the shared view.
                </p>
              )}
            </div>
          )}
          {mode === "form" ? (
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                Ask {item.owner.name} to lend you this{" "}
                {item.kind === "battery" ? "battery" : "tool"}. They'll
                get the request in their Borrowing list and in their
                notifications — approving checks it out to you.
                {item.is_set &&
                  " It's a set: the core pieces always come; whether the addons come along is the owner's saved choice for this set."}
              </p>
              <FormField label="I'd return it by (optional)" htmlFor="br-due">
                <DatePicker
                  id="br-due"
                  value={due}
                  onChange={setDue}
                  clearable
                />
              </FormField>
              <FormField label="Note for the owner (optional)" htmlFor="br-notes">
                <TextArea
                  id="br-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="What you need it for…"
                  rows={2}
                />
              </FormField>
              {error && (
                <p role="alert" style={{ color: "var(--danger)", margin: 0 }}>
                  {error}
                </p>
              )}
            </div>
          ) : (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Need it for a job? Hit “Request to borrow” —{" "}
              {item.owner.name.split(" ")[0] || "the owner"} approves
              it from their Borrowing list and it checks out to you.
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}

/** The page's tabs (E1, 2026-11-12): the explainer, Ryan's
 *  four audiences, and the settings seat. */
type SharedTabId =
  | "how"
  | "employer"
  | "insurance"
  | "coworkers"
  | "employees"
  | "settings";

/** Deep links pick the opening tab — the peer invite
 *  notifications point at #shared-with-me (received) and
 *  #sharing (accepted / declined), the way /flyers and
 *  /repairs hashes pick theirs; both remap to Coworkers,
 *  where the peer content now lives. Anything else opens
 *  on the explainer. */
function tabFromHash(hash: string): SharedTabId {
  const raw = hash.replace(/^#/, "");
  if (raw === "employer") return "employer";
  if (raw === "insurance") return "insurance";
  if (raw === "coworkers") return "coworkers";
  if (raw === "employees") return "employees";
  if (raw === "shared-with-me" || raw === "sharing") return "coworkers";
  if (raw === "settings") return "settings";
  return "how";
}

/** The explainer tab (new in lane 1): how the shared tools
 *  system works, in four short sections, with doors to the
 *  two places a reader most likely wants next. */
function ExplainerTab({ onGo }: { onGo: (tab: SharedTabId) => void }) {
  const t = useT();
  const sections = [
    { title: t("shared.how.whatTitle"), body: t("shared.how.whatBody") },
    { title: t("shared.how.seeTitle"), body: t("shared.how.seeBody") },
    { title: t("shared.how.shareTitle"), body: t("shared.how.shareBody") },
    { title: t("shared.how.borrowTitle"), body: t("shared.how.borrowBody") },
    {
      title: t("shared.how.audiencesTitle"),
      body: t("shared.how.audiencesBody"),
    },
  ];
  return (
    <Panel title={t("shared.tab.how")} variant="plate">
      <div className="tv-peer-how">
        {sections.map((s) => (
          <div key={s.title}>
            <p className="tv-peer-how-title">{s.title}</p>
            <p className="tv-peer-note">{s.body}</p>
          </div>
        ))}
        <div className="tv-peer-doors">
          <Button type="button" onClick={() => onGo("coworkers")}>
            {t("shared.how.seeWithMe")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => onGo("settings")}
          >
            {t("shared.how.openSettings")}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

/* -- E1 audience tabs --------------------------------------------------
 *
 * The four audiences, each filtered from the real sharing data
 * through endpoints that already exist (design + evidence in the
 * lane INDEX):
 *
 *   Employer / Insurance company — tier (consent) sharing's two
 *   recipient groups (shop_company / insurance), read from the
 *   sharing summary, joined with the relationship that gives the
 *   group a face: crew memberships (my shops) for the Employer,
 *   the My Insurance directory pick for Insurance.
 *   Coworkers — peer grants, whole and unfiltered.
 *   Employees — my crew roster, joined with peer grants by
 *   viewer id to answer "sees my list".
 *
 * Every gate sentence below restates a gate the SERVER already
 * enforces (crew.member_tools, insurers.list_policyholders,
 * peer accept-before-visible): the tabs organize and surface the
 * existing consent model, they do not change it.
 */

/** GET /core/crew + /core/crew/my-shops row (CrewMembershipView). */
interface CrewMembershipRow {
  id: string;
  shop_user_id: string;
  shop_name: string;
  employee_user_id: string | null;
  employee_name: string;
  employee_email: string;
  employee_account_number: string;
  invite_email: string;
  role_label: string;
  status: "invited" | "active" | "left" | "declined";
}

/** The slice of GET /core/insurance the Insurance tab reads. */
interface InsuranceProfileLite {
  has_profile: boolean;
  insurer_company: string;
  insurer_company_id: string | null;
  insurer_company_name: string | null;
  agent_name: string;
}

type TFn = ReturnType<typeof useT>;

function crewStatusLabel(t: TFn, status: CrewMembershipRow["status"]): string {
  if (status === "active") return t("shared.aud.statusActive");
  if (status === "invited") return t("shared.aud.statusInvited");
  if (status === "left") return t("shared.aud.statusLeft");
  return t("shared.aud.statusDeclined");
}

function crewStatusTone(
  status: CrewMembershipRow["status"],
): "success" | "warning" | "neutral" {
  if (status === "active") return "success";
  if (status === "invited") return "warning";
  return "neutral";
}

/** One tier group's state line: on/off badge + the live shared
 *  count + rule count, all from the sharing summary (the same
 *  numbers the Your sharing panel shows). Renders nothing while
 *  the summary is in flight — the panel's own copy carries the
 *  state in words either way. */
function TierStateLine({
  group,
  summary,
}: {
  group: ShareRecipientGroup;
  summary: SharingSummary | null;
}) {
  const t = useT();
  const state = summary?.groups.find((g) => g.recipient_group === group);
  if (!state) {
    return (
      <p className="tv-peer-loading">
        <Spinner size="sm" /> {t("shared.aud.loading")}
      </p>
    );
  }
  return (
    <p className="tv-peer-rowtext">
      <Badge tone={state.enabled ? "success" : "neutral"}>
        {state.enabled ? t("shared.aud.on") : t("shared.aud.off")}
      </Badge>{" "}
      <span className="tv-peer-muted">
        {t("shared.aud.itemsShared").replace(
          "{count}",
          String(state.shared_count),
        )}
        {state.rule_count > 0 &&
          ` · ${t("shared.aud.rulesCount").replace("{count}", String(state.rule_count))}`}
      </span>
    </p>
  );
}

function EmployerTab({
  myShops,
  summary,
  employerGrants,
  onBrowse,
  onManage,
}: {
  myShops: CrewMembershipRow[] | null;
  summary: SharingSummary | null;
  employerGrants: PeerIncomingGrant[];
  onBrowse: (person: PeerPerson) => void;
  onManage: () => void;
}) {
  const t = useT();
  const hasActiveCrew = (myShops ?? []).some((r) => r.status === "active");
  const shopState = summary?.groups.find(
    (g) => g.recipient_group === "shop_company",
  );
  return (
    <div className="tv-peer-tabgrid">
      <Panel title={t("shared.emp.shopsTitle")} variant="plate">
        {myShops === null && (
          <p className="tv-peer-loading">
            <Spinner size="sm" /> {t("shared.aud.loading")}
          </p>
        )}
        {myShops !== null && myShops.length === 0 && (
          <p className="tv-peer-note">{t("shared.emp.shopsEmpty")}</p>
        )}
        {myShops !== null && myShops.length > 0 && (
          <div className="tv-table-wrap">
            <table className="tv-table">
              <thead>
                <tr>
                  <th>{t("shared.emp.colShop")}</th>
                  <th>{t("shared.aud.colRole")}</th>
                  <th>{t("shared.aud.colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {myShops.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.shop_name || "—"}</strong>
                    </td>
                    <td>{row.role_label || "—"}</td>
                    <td>
                      <Badge tone={crewStatusTone(row.status)}>
                        {crewStatusLabel(t, row.status)}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title={t("shared.emp.seesTitle")} variant="plate">
        <div className="tv-peer-stack">
          <TierStateLine group="shop_company" summary={summary} />
          {shopState && (
            <p className="tv-peer-note">
              {!shopState.enabled
                ? t("shared.emp.seesOff")
                : hasActiveCrew
                  ? t("shared.emp.seesOnCrew")
                  : t("shared.emp.seesOnNoCrew")}
            </p>
          )}
          <div>
            <Button type="button" variant="secondary" size="sm" onClick={onManage}>
              {t("shared.sharing.manage")}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title={t("shared.emp.fromTitle")} variant="plate">
        {employerGrants.length === 0 ? (
          <p className="tv-peer-note">{t("shared.emp.fromEmpty")}</p>
        ) : (
          <div className="tv-peer-list">
            {employerGrants.map((grant) => (
              <div key={grant.id} className="tv-peer-row">
                <p className="tv-peer-rowtext">
                  <strong>{grant.owner.name}</strong>{" "}
                  <span className="tv-peer-muted">
                    · {grant.owner.account_number}
                  </span>{" "}
                  <Badge tone="success">
                    {t("shared.sharing.badgeSharing")}
                  </Badge>
                </p>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => onBrowse(grant.owner)}
                >
                  {t("shared.aud.browse")}
                </Button>
              </div>
            ))}
            <p className="tv-peer-note">{t("shared.emp.fromNote")}</p>
          </div>
        )}
      </Panel>
    </div>
  );
}

function InsuranceTab({
  profile,
  summary,
  onManage,
}: {
  profile: InsuranceProfileLite | null;
  summary: SharingSummary | null;
  onManage: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const insState = summary?.groups.find(
    (g) => g.recipient_group === "insurance",
  );
  const pickedName = profile
    ? profile.insurer_company_name || profile.insurer_company
    : "";
  const matched = Boolean(profile?.insurer_company_id);
  return (
    <div className="tv-peer-tabgrid">
      <Panel title={t("shared.ins.companyTitle")} variant="plate">
        <div className="tv-peer-stack">
          {profile === null && (
            <p className="tv-peer-loading">
              <Spinner size="sm" /> {t("shared.aud.loading")}
            </p>
          )}
          {profile !== null && matched && (
            <p className="tv-peer-rowtext">
              {t("shared.ins.companyPicked").replace("{name}", pickedName)}
            </p>
          )}
          {profile !== null && !matched && profile.insurer_company && (
            <p className="tv-peer-note">
              {t("shared.ins.companyTyped").replace(
                "{name}",
                profile.insurer_company,
              )}
            </p>
          )}
          {profile !== null && !matched && !profile.insurer_company && (
            <p className="tv-peer-note">{t("shared.ins.companyNone")}</p>
          )}
          {profile !== null && profile.agent_name && (
            <p className="tv-peer-rowtext">
              {t("shared.ins.agentLine").replace("{name}", profile.agent_name)}
            </p>
          )}
          <div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => navigate("/settings/insurance")}
            >
              {t("shared.ins.openProfile")}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title={t("shared.ins.seesTitle")} variant="plate">
        <div className="tv-peer-stack">
          <TierStateLine group="insurance" summary={summary} />
          {insState && profile !== null && (
            <p className="tv-peer-note">
              {!insState.enabled
                ? t("shared.ins.seesOff")
                : matched
                  ? t("shared.ins.seesOnMatched").replace("{name}", pickedName)
                  : t("shared.ins.seesOnUnmatched")}
            </p>
          )}
          <div>
            <Button type="button" variant="secondary" size="sm" onClick={onManage}>
              {t("shared.sharing.manage")}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title={t("shared.ins.stateTitle")} variant="plate">
        <p className="tv-peer-note">{t("shared.ins.stateBody")}</p>
      </Panel>
    </div>
  );
}

type RosterState =
  | { kind: "loading" }
  | { kind: "ok"; rows: CrewMembershipRow[] }
  | { kind: "not-shop" };

function EmployeesTab({
  roster,
  grants,
}: {
  roster: RosterState;
  grants: PeerOutgoingGrant[];
}) {
  const t = useT();
  const navigate = useNavigate();
  if (roster.kind === "not-shop") {
    return (
      <Panel title={t("shared.empl.notShopTitle")} variant="plate">
        <p className="tv-peer-note">{t("shared.empl.notShopBody")}</p>
      </Panel>
    );
  }
  const rows = roster.kind === "ok" ? roster.rows : [];
  const seesMine = (row: CrewMembershipRow): string => {
    if (!row.employee_user_id) return t("shared.empl.seesNo");
    const grant = grants.find((g) => g.viewer?.id === row.employee_user_id);
    if (!grant) return t("shared.empl.seesNo");
    return grant.status === "accepted"
      ? t("shared.empl.seesYes")
      : t("shared.empl.seesInvited");
  };
  return (
    <div className="tv-peer-tabgrid">
      <Panel title={t("shared.empl.title")} variant="plate">
        {roster.kind === "loading" && (
          <p className="tv-peer-loading">
            <Spinner size="sm" /> {t("shared.aud.loading")}
          </p>
        )}
        {roster.kind === "ok" && rows.length === 0 && (
          <p className="tv-peer-note">{t("shared.empl.empty")}</p>
        )}
        {rows.length > 0 && (
          <div className="tv-table-wrap">
            <table className="tv-table">
              <thead>
                <tr>
                  <th>{t("shared.empl.colEmployee")}</th>
                  <th>{t("shared.aud.colRole")}</th>
                  <th>{t("shared.aud.colStatus")}</th>
                  <th>{t("shared.empl.colSeesMine")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>
                        {row.employee_name || row.invite_email || "—"}
                      </strong>
                      {row.employee_account_number && (
                        <span className="tv-peer-muted">
                          {" "}
                          · {row.employee_account_number}
                        </span>
                      )}
                    </td>
                    <td>{row.role_label || "—"}</td>
                    <td>
                      <Badge tone={crewStatusTone(row.status)}>
                        {crewStatusLabel(t, row.status)}
                      </Badge>
                    </td>
                    <td>{seesMine(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel title={t("shared.how.seeTitle")} variant="plate">
        <div className="tv-peer-stack">
          <p className="tv-peer-note">{t("shared.empl.gateNote")}</p>
          <div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => navigate("/settings/crew")}
            >
              {t("shared.empl.openCrew")}
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function SharedContent() {
  const t = useT();
  const { toast } = useToast();
  const { hash } = useLocation();
  const [tab, setTab] = useState<SharedTabId>(() =>
    tabFromHash(window.location.hash),
  );

  // The mount read covers fresh arrivals. A notification
  // click (or any in-app link) can also change the hash
  // while this page stays mounted — no remount happens, so
  // follow later hash changes too, or the deep link lands
  // on whatever tab was already open.
  useEffect(() => {
    const wanted = tabFromHash(hash);
    if (wanted !== "how") setTab(wanted);
  }, [hash]);
  const [overview, setOverview] = useState<PeerOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // E1 audience data: the tier summary (Employer/Insurance state),
  // my crew memberships both directions, and my insurance pick.
  // Each fetch fails soft — a failed read empties only its own
  // panel, never the page (the YourSharingPanel rule).
  const [summary, setSummary] = useState<SharingSummary | null>(null);
  const [myShops, setMyShops] = useState<CrewMembershipRow[] | null>(null);
  const [roster, setRoster] = useState<RosterState>({ kind: "loading" });
  const [insProfile, setInsProfile] = useState<InsuranceProfileLite | null>(
    null,
  );

  useEffect(() => {
    let live = true;
    api<SharingSummary>("/core/sharing/summary")
      .then((data) => {
        if (live) setSummary(data);
      })
      .catch(() => {
        /* tier panels show their loading line */
      });
    api<CrewMembershipRow[]>("/core/crew/my-shops")
      .then((data) => {
        if (live) setMyShops(data);
      })
      .catch(() => {
        if (live) setMyShops([]);
      });
    api<CrewMembershipRow[]>("/core/crew")
      .then((data) => {
        if (live) setRoster({ kind: "ok", rows: data });
      })
      .catch((err) => {
        if (!live) return;
        // The roster route refuses non-shop accounts with a 422 —
        // that refusal IS the "not a shop" answer for the tab.
        if (err instanceof ApiError && err.status === 422) {
          setRoster({ kind: "not-shop" });
        } else {
          setRoster({ kind: "ok", rows: [] });
        }
      });
    api<InsuranceProfileLite>("/core/insurance")
      .then((data) => {
        if (live) setInsProfile(data);
      })
      .catch(() => {
        /* insurance panel shows its loading line */
      });
    return () => {
      live = false;
    };
  }, []);

  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounced(query.trim(), 350);
  const [results, setResults] = useState<PeerItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  // Bumped whenever a grant action changes whose tools are
  // searchable (accept / leave) so an on-screen search re-runs
  // against the new availability instead of going stale until the
  // query text changes.
  const [searchVersion, setSearchVersion] = useState(0);

  const [browsing, setBrowsing] = useState<PeerListResponse | null>(null);
  const [browsingId, setBrowsingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PeerItem | null>(null);
  const [busyGrant, setBusyGrant] = useState<string | null>(null);

  async function loadOverview() {
    try {
      const data = await api<PeerOverview>("/core/sharing/peer");
      setOverview(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load shared tools.",
      );
    }
  }

  useEffect(() => {
    void loadOverview();
  }, []);

  useEffect(() => {
    if (!debouncedQuery) {
      setResults(null);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    api<PeerItem[]>(
      `/core/sharing/peer/search?q=${encodeURIComponent(debouncedQuery)}`,
    )
      .then((data) => {
        if (!cancelled) setResults(data);
      })
      .catch(() => {
        if (!cancelled) setResults([]);
      })
      .finally(() => {
        if (!cancelled) setSearching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, searchVersion]);

  async function browse(person: PeerPerson) {
    setBrowsingId(person.id);
    try {
      const data = await api<PeerListResponse>(
        `/core/sharing/peer/lists/${person.id}`,
      );
      setBrowsing(data);
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : "Couldn't load that list. Try again.",
        { tone: "danger" },
      );
    } finally {
      setBrowsingId(null);
    }
  }

  async function actOnGrant(
    grant: PeerIncomingGrant,
    action: "accept" | "decline" | "leave",
  ) {
    setBusyGrant(grant.id);
    try {
      await api(`/core/sharing/peer/${grant.id}/${action}`, { method: "POST" });
      // Apply the confirmed transition to the visible lists right
      // away — accept moves the grant from "Invites for you" to
      // "Sharing with me", decline drops the invite, leave drops
      // the person — instead of leaving the old arrangement on
      // screen until the refetch lands (the stale-UI pattern
      // browser QA caught in Settings → Sharing → People,
      // 2026-10-17). The refetch below still runs to reconcile.
      setOverview((o) => {
        if (!o) return o;
        if (action === "accept") {
          return {
            ...o,
            pending_for_me: o.pending_for_me.filter((g) => g.id !== grant.id),
            shared_with_me: [
              { ...grant, status: "accepted" as const },
              ...o.shared_with_me.filter((g) => g.id !== grant.id),
            ],
          };
        }
        if (action === "decline") {
          return {
            ...o,
            pending_for_me: o.pending_for_me.filter((g) => g.id !== grant.id),
          };
        }
        return {
          ...o,
          shared_with_me: o.shared_with_me.filter((g) => g.id !== grant.id),
        };
      });
      if (action === "accept") {
        toast(`You can now browse ${grant.owner.name}'s tools.`, {
          tone: "success",
          title: "Invite accepted",
        });
        // Their tools just became searchable — refresh any
        // on-screen search results.
        setSearchVersion((v) => v + 1);
      } else if (action === "decline") {
        toast("Invite declined.", { tone: "info" });
      } else {
        toast(`Removed ${grant.owner.name}'s list.`, { tone: "info" });
        if (browsing?.owner.id === grant.owner.id) setBrowsing(null);
        // Their tools just stopped being searchable.
        setSearchVersion((v) => v + 1);
      }
      await loadOverview();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "That didn't work. Try again.",
        { tone: "danger" },
      );
    } finally {
      setBusyGrant(null);
    }
  }

  const sharingWithMe = overview?.shared_with_me ?? [];
  const pending = overview?.pending_for_me ?? [];
  const sharingWith = overview?.sharing_with ?? [];

  const tabLabel = (id: SharedTabId): string =>
    id === "how"
      ? t("shared.tab.how")
      : id === "employer"
        ? t("shared.tab.employer")
        : id === "insurance"
          ? t("shared.tab.insurance")
          : id === "coworkers"
            ? t("shared.tab.coworkers")
            : id === "employees"
              ? t("shared.tab.employees")
              : t("shared.tab.settings");

  // Employer audience join: incoming peer grants whose owner is
  // one of my shops (an active or invited crew membership names
  // the shop's user id). A grant from anyone else stays a plain
  // coworker grant — the join is by membership row, never a guess.
  const myShopIds = new Set(
    (myShops ?? [])
      .filter((r) => r.status === "active" || r.status === "invited")
      .map((r) => r.shop_user_id),
  );
  const employerGrants = sharingWithMe.filter((g) => myShopIds.has(g.owner.id));

  /** Browse a person's list from an audience tab: the browse
   *  surface lives in Coworkers, so the door lands there with
   *  the list already opening. */
  function browseFromAudience(person: PeerPerson) {
    setTab("coworkers");
    void browse(person);
  }

  // Header facts ride the peer overview the page already
  // loads; until it lands there is nothing true to show, so
  // the facts row stays empty (the kit's rule).
  const facts: SectionPageFact[] | undefined = overview
    ? [
        { label: t("home.widget.sharedWithYou"), value: sharingWithMe.length },
        {
          label: t("home.widget.youShareWith"),
          value: sharingWith.filter((g) => g.status === "accepted").length,
        },
        ...(pending.length > 0
          ? [{ label: t("shared.fact.invitesWaiting"), value: pending.length }]
          : []),
      ]
    : undefined;

  const tabs: TabItem[] = [
    {
      id: "how",
      label: tabLabel("how"),
      content: (
        <div className="tv-peer-tabgrid">
          <ExplainerTab onGo={setTab} />
          <YourSharingPanel onManage={() => setTab("settings")} />
        </div>
      ),
    },
    {
      id: "employer",
      label: tabLabel("employer"),
      content: (
        <EmployerTab
          myShops={myShops}
          summary={summary}
          employerGrants={employerGrants}
          onBrowse={browseFromAudience}
          onManage={() => setTab("settings")}
        />
      ),
    },
    {
      id: "insurance",
      label: tabLabel("insurance"),
      content: (
        <InsuranceTab
          profile={insProfile}
          summary={summary}
          onManage={() => setTab("settings")}
        />
      ),
    },
    {
      id: "coworkers",
      label: tabLabel("coworkers"),
      content: (
        <div className="tv-peer-tabgrid">
          <p className="tv-peer-note">{t("shared.cow.intro")}</p>
      <Panel title="Search shared tools" variant="plate">
        <SearchBar
          value={query}
          onChange={setQuery}
          placeholder="Search by name, brand, model, or category…"
          ariaLabel="Search shared tools"
        />
        {!debouncedQuery && (
          <p style={{ color: "var(--text-muted)", margin: "0.75rem 0 0" }}>
            {sharingWithMe.length === 0
              ? "Nobody is sharing a list with you yet — when a coworker shares theirs, their tools become searchable here."
              : "Start typing to search across everyone sharing with you."}
          </p>
        )}
        {debouncedQuery && searching && (
          <p
            style={{
              color: "var(--text-muted)",
              display: "flex",
              gap: "var(--space-2)",
              alignItems: "center",
              margin: "0.75rem 0 0",
            }}
          >
            <Spinner size="sm" /> Searching…
          </p>
        )}
        {debouncedQuery && !searching && results !== null && (
          <div style={{ marginTop: "var(--space-3)" }}>
            {results.length === 0 ? (
              <EmptyState
                icon={<BrandIcon name="search" size={48} />}
                title="Nobody sharing with you has that"
                description="Try a different name, brand, or category — or browse a person's full list below."
              />
            ) : (
              <ItemGrid items={results} showOwner onOpen={setDetail} />
            )}
          </div>
        )}
      </Panel>

      {pending.length > 0 && (
        <Panel title="Invites for you" variant="plate">
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {pending.map((grant) => (
              <div
                key={grant.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                  flexWrap: "wrap",
                }}
              >
                <p style={{ margin: 0 }}>
                  <strong>{grant.owner.name}</strong>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    · {grant.owner.account_number} wants to share their
                    tool list with you
                  </span>
                </p>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Button
                    type="button"
                    size="sm"
                    loading={busyGrant === grant.id}
                    onClick={() => void actOnGrant(grant, "accept")}
                  >
                    Accept
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={busyGrant === grant.id}
                    onClick={() => void actOnGrant(grant, "decline")}
                  >
                    Decline
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="Sharing with me" variant="plate">
        {!overview && !loadError && (
          <p
            style={{
              color: "var(--text-muted)",
              display: "flex",
              gap: "var(--space-2)",
              alignItems: "center",
              margin: 0,
            }}
          >
            <Spinner size="sm" /> Loading…
          </p>
        )}
        {overview && sharingWithMe.length === 0 && (
          <EmptyState
            icon={<BrandIcon name="share-green" size={52} />}
            title="No lists shared with you yet"
            description="When a coworker invites you and you accept, their list appears here — and their tools become searchable above."
          />
        )}
        {sharingWithMe.length > 0 && (
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {sharingWithMe.map((grant) => (
              <div
                key={grant.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                  flexWrap: "wrap",
                }}
              >
                <p style={{ margin: 0 }}>
                  <strong>{grant.owner.name}</strong>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    · {grant.owner.account_number}
                  </span>{" "}
                  <Badge tone="success">Sharing</Badge>
                </p>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Button
                    type="button"
                    size="sm"
                    loading={browsingId === grant.owner.id}
                    onClick={() => void browse(grant.owner)}
                  >
                    Browse tools
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={busyGrant === grant.id}
                    onClick={() => void actOnGrant(grant, "leave")}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
        {browsing && (
          <div
            style={{
              borderTop: "1px solid var(--edge)",
              marginTop: "var(--space-3)",
              paddingTop: "var(--space-3)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
                marginBottom: "var(--space-3)",
              }}
            >
              <p style={{ fontWeight: 700, margin: 0 }}>
                {browsing.owner.name}'s tools
              </p>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => setBrowsing(null)}
              >
                Close list
              </Button>
            </div>
            {browsing.items.length === 0 ? (
              <EmptyState
                icon={<BrandIcon name="briefcase" size={48} />}
                title="Nothing on this list"
                description={`${browsing.owner.name} hasn't put any tools on their shared list.`}
              />
            ) : (
              <ItemGrid items={browsing.items} showOwner={false} onOpen={setDetail} />
            )}
          </div>
        )}
      </Panel>
          <Panel title={t("shared.sharing.peopleTitle")} variant="plate">
            {!overview && !loadError && (
              <p className="tv-peer-loading">
                <Spinner size="sm" /> Loading…
              </p>
            )}
            {overview && sharingWith.length === 0 && (
              <EmptyState
                icon={<BrandIcon name="share-green" size={52} />}
                title={t("shared.sharing.empty")}
                description={t("shared.sharing.manageNote")}
              />
            )}
            {sharingWith.length > 0 && (
              <div className="tv-peer-list">
                {sharingWith.map((grant) => (
                  <div key={grant.id} className="tv-peer-row">
                    <p className="tv-peer-rowtext">
                      <strong>
                        {grant.viewer
                          ? grant.viewer.name
                          : (grant.invited_email ?? "Someone")}
                      </strong>{" "}
                      <span className="tv-peer-muted">
                        ·{" "}
                        {grant.viewer
                          ? grant.viewer.account_number
                          : t("shared.sharing.emailNote")}
                      </span>{" "}
                      <Badge
                        tone={
                          grant.status === "accepted" ? "success" : "warning"
                        }
                      >
                        {grant.status === "accepted"
                          ? t("shared.sharing.badgeSharing")
                          : t("shared.sharing.badgeInvited")}
                      </Badge>
                    </p>
                  </div>
                ))}
                <p className="tv-peer-note">{t("shared.sharing.manageNote")}</p>
              </div>
            )}
          </Panel>
        </div>
      ),
    },
    {
      id: "employees",
      label: tabLabel("employees"),
      content: <EmployeesTab roster={roster} grants={sharingWith} />,
    },
    {
      id: "settings",
      label: tabLabel("settings"),
      // The settings tab renders the Settings → Sharing section
      // component itself — one surface, two seats, so the tab
      // and Settings can never drift (the map's shape).
      content: <SharingSettings />,
    },
  ];

  return (
    <div className="tv-stack">
      <SectionPageHeader
        thumb={<ArtIcon name="shared" size={96} />}
        title={t("nav.peer-shared-tools")}
        subtitle={t("shared.subtitle")}
        facts={facts}
        actions={
          <SettingsActionsMenu
            ariaLabel={t("nav.peer-shared-tools")}
            buttonLabel={t("inventory.actions")}
            entries={(
              ["how", "employer", "insurance", "coworkers", "employees"] as const
            ).map(
              (id) => ({
                key: id,
                label: tabLabel(id),
                run: () => setTab(id),
              }),
            )}
            settingsEntry={{
              key: "settings",
              label: t("shell.settings"),
              run: () => setTab("settings"),
            }}
          />
        }
      />

      {loadError && <Alert tone="danger">{loadError}</Alert>}

      <Tabs
        tabs={tabs}
        activeId={tab}
        onChange={(id) => setTab(id as SharedTabId)}
      />

      <ItemDetailModal item={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

export default function SharedToolsPage() {
  return (
    <RequireAuth>
      <SharedContent />
    </RequireAuth>
  );
}
