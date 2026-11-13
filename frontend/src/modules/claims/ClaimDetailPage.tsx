import { useCallback, useEffect, useState, type ReactNode } from "react";
import "./claims.css";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Modal,
  Panel,
  SectionPageHeader,
  Select,
  Spinner,
  Tabs,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import type { TabItem } from "../../components/Tabs";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import { useT } from "../../i18n/LocaleContext";
import { usePageCrumbs } from "../../lib/navTrail";
import {
  archiveClaim,
  deleteClaim,
  getClaim,
  getClaimTargets,
  setClaimAgent,
  transitionClaim,
  updateClaim,
} from "./api";
import {
  ChecklistPanel,
  CommsPanel,
  EvidenceSection,
  StatusBadge,
  headerInputFrom,
} from "./components";
import { ClaimActionsMenu, type ClaimMenuEntry } from "./ClaimActionsMenu";
import { ClaimStatusStrip } from "./ClaimStatusStrip";
import { SellerPrice } from "../../components/SellerPrice";
import DealerWarrantyBox from "../dealers/components/DealerWarrantyBox";
import { fullDate } from "./format";
import { WARRANTY_STATUSES } from "./types";
import type {
  Claim,
  ClaimHeaderInput,
  ClaimTargets,
  WarrantyAgent,
} from "./types";

function warrantyAgentKey(agent: WarrantyAgent): string {
  return agent.agent_user_id
    ? `platform:${agent.agent_user_id}`
    : `private:${agent.private_agent_id}`;
}

/**
 * One WARRANTY claim's home (sweep C3, 2026-11-12: rebuilt on
 * the main-tab record layout, matching the tool and dealer
 * record pages): a header with the claim number, its facts and
 * ONE state-aware Actions dropdown; a live-status strip when
 * the claim carries live states; then REAL tabs — Details
 * (to-do list + the claim record), Items, Evidence, Repair,
 * Communications. Every fact, section and action from the old
 * stacked page is rehoused here; nothing was added or dropped.
 *
 * The claim IS the repair since the 2026-11-04 merge, and the
 * communications log is the whole paper trail the repair
 * conversation needs. Claims separation (2026-11-05): this
 * page serves warranty claims only; disaster (insurance)
 * claims live on their own page in Disaster Claims. Two seats
 * read it: the owner, and the claim's assigned agent
 * (viewer_role="dealer" — customer named, everything read-only
 * except the shared lanes: status, log, evidence adds).
 */

/** The repair working end of a warranty claim (repairs ∪ claims
 *  merge, 2026-11-04): the claim IS the repair, so this panel is
 *  where the item is sent out and marked fixed — the moves ride
 *  the claim's own ladder transitions, carrying where it went
 *  and what it cost ON the claim. Both seats work it per their
 *  allowed transitions (the agent can say "we have it" and "it's
 *  done"; the owner drives everything). Once completed, the
 *  facts stay on the record — closing the claim keeps them. */
function RepairPanel({
  claim,
  busy,
  onTransition,
}: {
  claim: Claim;
  busy: boolean;
  onTransition: (
    to: Claim["status"],
    repair?: { repair_sent_to?: string; repair_cost?: string },
  ) => Promise<void>;
}) {
  const t = useT();
  const [sendOpen, setSendOpen] = useState(false);
  const [sentTo, setSentTo] = useState("");
  const [cost, setCost] = useState("");
  const canSend = claim.allowed_transitions.includes("in_repair");
  const canFix = claim.allowed_transitions.includes("completed");
  const finished = claim.status === "completed";
  const factRow = (label: string, children: ReactNode) => (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "1rem",
        flexWrap: "wrap",
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{children}</span>
    </div>
  );
  return (
    <Panel title={t("claims.repair.title")}>
      <div style={{ display: "grid", gap: "0.7rem" }}>
        {claim.repair_sent_to
          ? factRow(t("claims.repair.sentTo"), claim.repair_sent_to)
          : !finished && (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {t("claims.repair.notSentYet")}
              </p>
            )}
        {claim.repair_cost !== null &&
          claim.repair_cost !== undefined &&
          factRow(
            t("claims.repair.cost"),
            <SellerPrice
              amount={claim.repair_cost}
              currency={claim.owner_currency}
            />,
          )}
        {claim.repair_completed_at &&
          factRow(
            t("claims.repair.completedOn"),
            fullDate(claim.repair_completed_at),
          )}
        {canSend && !sendOpen && (
          <div>
            <Button
              size="sm"
              disabled={busy}
              onClick={() => setSendOpen(true)}
            >
              {t("claims.repair.send")}
            </Button>
          </div>
        )}
        {canSend && sendOpen && (
          <div className="tv-claim-lines">
            <FormField label={t("claims.repair.sendLabel")}>
              <TextInput
                value={sentTo}
                onChange={(e) => setSentTo(e.target.value)}
                placeholder={t("claims.repair.sendPlaceholder")}
              />
            </FormField>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <Button
                size="sm"
                disabled={busy}
                onClick={() =>
                  void onTransition("in_repair", {
                    repair_sent_to: sentTo.trim(),
                  })
                }
              >
                {t("claims.repair.send")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => setSendOpen(false)}
              >
                {t("claims.broken.cancel")}
              </Button>
            </div>
          </div>
        )}
        {canFix && (
          <div className="tv-claim-lines">
            <FormField label={t("claims.repair.costLabel")}>
              <TextInput
                type="number"
                min="0"
                step="0.01"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                placeholder={t("claims.repair.costPlaceholder")}
              />
            </FormField>
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.88rem" }}>
              {t("claims.repair.costHelp")}
            </p>
            <div>
              <Button
                size="sm"
                disabled={busy}
                onClick={() =>
                  void onTransition("completed", {
                    repair_cost: cost.trim() ? cost.trim() : undefined,
                  })
                }
              >
                {t("claims.repair.markFixed")}
              </Button>
            </div>
          </div>
        )}
        {finished && (
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.88rem" }}>
            {t("claims.repair.doneNote")}
          </p>
        )}
        {claim.viewer_role === "owner" && !finished && (
          <DealerWarrantyBox claimId={claim.id} />
        )}
      </div>
    </Panel>
  );
}
export default function ClaimDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const t = useT();
  const [claim, setClaim] = useState<Claim | null>(null);
  // Link tree (owner directive 2026-11-02): this page carries
  // no trail of its own, so it registers one with the shell's
  // page navigation bar — Claims › <claim number>.
  usePageCrumbs(
    claim
      ? [
          { label: t("repairs.tab.claims"), to: "/repairs#repair-claims" },
          { label: claim.claim_number },
        ]
      : null,
  );
  const [targets, setTargets] = useState<ClaimTargets | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ClaimHeaderInput>({});
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [activeTab, setActiveTab] = useState("details");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [view, picker] = await Promise.all([
        getClaim(id),
        getClaimTargets().catch(() => null),
      ]);
      setClaim(view);
      setForm(headerInputFrom(view));
      setTargets(picker);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("claims.detail.couldntLoad"));
    }
  }, [id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <RequireAuth>
        <Alert tone="danger">{error}</Alert>
        <p>
          <Link to="/repairs#repair-claims" style={{ color: "var(--accent)" }}>
            {t("claims.detail.backAll")}
          </Link>
        </p>
      </RequireAuth>
    );
  }
  if (!claim) {
    return (
      <RequireAuth>
        <div className="tv-claim-loading">
          <Spinner />
        </div>
      </RequireAuth>
    );
  }

  // Closing is a LAYER since the overhaul (2026-11-06): the
  // claim is closed when closed_at is stamped, whatever status
  // it keeps — the status badge beside it still names its rung.
  const closed = claim.closed_at !== null;
  const isDraft = claim.status === "draft";
  const isDealerViewer = claim.viewer_role === "dealer";
  /* Agent scope (2026-10-31): the agent pick list is the owner's
   * agents on record for the dealer; the claim's current agent
   * is folded in when they have since left the record, so the
   * select always shows the true current value. */
  const agentChoices: WarrantyAgent[] = (() => {
    const list = [...claim.agent_options];
    if (
      claim.warranty_agent &&
      !list.some(
        (a) => warrantyAgentKey(a) === warrantyAgentKey(claim.warranty_agent!),
      )
    ) {
      list.unshift(claim.warranty_agent);
    }
    return list;
  })();
  const currentAgentKey = claim.warranty_agent
    ? warrantyAgentKey(claim.warranty_agent)
    : "none";
  /* The re-point pick list groups the same way the dealer
   * roster and the filing picker do (owner, 2026-11-04): the
   * owner's own entered agents first, the dealer's listed
   * (registered) agents below — a partition of the same
   * choices, so the folded-in current agent lands in its own
   * kind's group. */
  const yourChoices = agentChoices.filter((a) => a.kind === "private");
  const listedChoices = agentChoices.filter((a) => a.kind === "platform");
  const agentChoiceOption = (agent: WarrantyAgent) => (
    <option key={warrantyAgentKey(agent)} value={warrantyAgentKey(agent)}>
      {agent.name}
    </option>
  );

  async function saveWarrantyDetails() {
    if (!claim) return;
    setBusy(true);
    try {
      const updated = await updateClaim(claim.id, {
        description: form.description ?? "",
        manufacturer_case_number: form.manufacturer_case_number ?? "",
      });
      setClaim(updated);
      setForm(headerInputFrom(updated));
      toast(t("claims.detail.savedToast"), { tone: "success", title: claim.claim_number });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntSave"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  /* Agent scope (2026-10-31): re-point the claim at another of
   * the owner's agents for this dealer — or at no agent. The
   * pick list is the owner's agents on record; a claim whose
   * agent left the record keeps them as its current value until
   * the owner picks otherwise. */
  async function changeAgent(value: string) {
    if (!claim) return;
    setBusy(true);
    try {
      const body =
        value === "none"
          ? {}
          : value.startsWith("platform:")
            ? { agent_user_id: value.slice("platform:".length) }
            : { private_agent_id: value.slice("private:".length) };
      const updated = await setClaimAgent(claim.id, body);
      setClaim(updated);
      setForm(headerInputFrom(updated));
      toast(t("claims.detail.savedToast"), {
        tone: "success",
        title: claim.claim_number,
      });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntSave"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doTransition(
    to: Claim["status"],
    repair?: { repair_sent_to?: string; repair_cost?: string },
  ) {
    if (!claim) return;
    setBusy(true);
    try {
      setClaim(await transitionClaim(claim.id, to, repair));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDo"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doArchive() {
    if (!claim) return;
    setBusy(true);
    try {
      const updated = await archiveClaim(claim.id, !claim.archived);
      setClaim(updated);
      toast(
        updated.archived
          ? t("claims.detail.archivedToast")
          : t("claims.detail.unarchivedToast"),
        { tone: "success", title: claim.claim_number },
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDo"), {
        tone: "danger",
        title: t("claims.title"),
      });
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    if (!claim) return;
    setBusy(true);
    try {
      await deleteClaim(claim.id);
      toast(t("claims.detail.draftDeletedToast").replace("{number}", claim.claim_number), {
        tone: "success",
        title: t("claims.title"),
      });
      navigate("/repairs#repair-claims");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("claims.detail.couldntDelete"), {
        tone: "danger",
        title: t("claims.title"),
      });
      setBusy(false);
    }
  }

  /* The ONE Actions menu (sweep C3): every control the old
   * headbar scattered — the status ladder, Close claim,
   * Archive, Delete draft — rehoused in the header's top-right
   * dropdown, with the same state rules the loose controls
   * carried. The status picker (claims overhaul, 2026-11-06):
   * Ryan's ladder is free-form — either seat may move the
   * claim to ANY of the 8 statuses; the menu offers every rung
   * but the current one, and the backend keeps each seat's own
   * ladder (the dealer's has no Close). The repair moves with
   * their captures (send / mark fixed) still ride the Repair
   * tab. Closing is its own thing: the owner's entry stamps
   * the closed layer, the status stays where it was, and the
   * claim moves to Repair history. */
  const menuEntries: ClaimMenuEntry[] = [];
  if (!closed) {
    for (const status of WARRANTY_STATUSES) {
      if (status === claim.status) continue;
      menuEntries.push({
        key: `status-${status}`,
        kind: "action",
        label: t(`claims.transition.${status}` as never),
        run: () => void doTransition(status),
      });
    }
  }
  const utilityEntries: ClaimMenuEntry[] = [];
  if (
    !closed &&
    !isDealerViewer &&
    claim.allowed_transitions.includes("closed")
  ) {
    utilityEntries.push({
      key: "close",
      kind: "action",
      label: t("claims.transition.closed"),
      danger: true,
      run: () => void doTransition("closed"),
    });
  }
  if (!isDealerViewer) {
    utilityEntries.push({
      key: "archive",
      kind: "action",
      label: claim.archived
        ? t("claims.detail.unarchive")
        : t("claims.detail.archive"),
      run: () => void doArchive(),
    });
  }
  if (isDraft && !isDealerViewer) {
    utilityEntries.push({
      key: "delete",
      kind: "action",
      label: t("claims.detail.deleteDraft"),
      danger: true,
      run: () => setConfirmDelete(true),
    });
  }
  if (utilityEntries.length > 0) {
    if (menuEntries.length > 0) {
      menuEntries.push({ key: "sep-utility", kind: "separator" });
    }
    menuEntries.push(...utilityEntries);
  }

  const headerFacts = [
    {
      label: t("claims.filter.dealer"),
      value:
        claim.dealer_company_id && !isDealerViewer ? (
          <Link
            to={`/dealers/${claim.dealer_company_id}`}
            className="tv-ix-link"
          >
            {claim.dealer_name || "—"}
          </Link>
        ) : (
          claim.dealer_name || "—"
        ),
    },
    ...(claim.reported_at
      ? [
          {
            label: t("claims.col.opened"),
            value: fullDate(claim.reported_at),
          },
        ]
      : []),
    { label: t("claims.col.items"), value: String(claim.lines.length) },
    {
      label: t("claims.detail.claimTotal"),
      value: (
        <SellerPrice
          amount={claim.total_amount}
          currency={claim.owner_currency}
        />
      ),
    },
  ];

  const tabs: TabItem[] = [
    {
      id: "details",
      label: t("claims.detailTab.details"),
      content: (
        <div className="tv-claim-cols">
          <ChecklistPanel claim={claim} onClaimChange={setClaim} />
          <Panel
            title={t("claims.detail.title")}
            actions={
              !closed && !isDealerViewer ? (
                <Button size="sm" variant="secondary" disabled={busy} onClick={saveWarrantyDetails}>
                  {t("claims.detail.saveChanges")}
                </Button>
              ) : undefined
            }
          >
            <div className="tv-warranty-grid">
              <p className="tv-warranty-p">
                <span className="tv-claim-muted">
                  {t("claims.filter.dealer")}:{" "}
                </span>
                <strong>{claim.dealer_name || "—"}</strong>
              </p>
              {claim.filed_with !== "agent" && (
                <p className="tv-warranty-p">
                  <span className="tv-claim-muted">
                    {t("claims.filedWith.label")}:{" "}
                  </span>
                  <strong>
                    {claim.filed_with === "corporate"
                      ? t("claims.filedWith.corporate").replace(
                          "{dealer}",
                          claim.dealer_name || "—",
                        )
                      : t("claims.filedWith.self")}
                  </strong>
                </p>
              )}
              {isDealerViewer && (
                <p className="tv-warranty-p">
                  <span className="tv-claim-muted">
                    {t("claims.warranty.customer")}:{" "}
                  </span>
                  <strong>{claim.owner_name}</strong>
                  {claim.owner_email ? ` · ${claim.owner_email}` : ""}
                </p>
              )}
              {isDealerViewer || closed ? (
                <p className="tv-warranty-p">
                  <span className="tv-claim-muted">
                    {t("claims.warranty.agent")}:{" "}
                  </span>
                  <strong>{claim.warranty_agent?.name || "—"}</strong>
                </p>
              ) : (
                <FormField label={t("claims.warranty.agent")}>
                  <Select
                    value={currentAgentKey}
                    disabled={busy}
                    onChange={(e) => void changeAgent(e.target.value)}
                  >
                    {yourChoices.length > 0 && (
                      <optgroup label={t("dealers.roster.yoursTitle")}>
                        {yourChoices.map(agentChoiceOption)}
                      </optgroup>
                    )}
                    {listedChoices.length > 0 && (
                      <optgroup label={t("dealers.roster.listedTitle")}>
                        {listedChoices.map(agentChoiceOption)}
                      </optgroup>
                    )}
                    <option value="none">
                      {t("claims.broken.agentNone")}
                    </option>
                  </Select>
                </FormField>
              )}
              {claim.warranty_agent &&
                !claim.warranty_agent.has_access &&
                !isDealerViewer && (
                  <p className="tv-warranty-p">
                    <span className="tv-claim-muted">
                      {t("claims.warranty.agentCantSee")}
                    </span>
                  </p>
                )}
              {closed || isDealerViewer ? (
                claim.manufacturer_case_number ? (
                  <p className="tv-warranty-p">
                    <span className="tv-claim-muted">
                      {t("claims.warranty.caseNumber")}:{" "}
                    </span>
                    <strong>{claim.manufacturer_case_number}</strong>
                  </p>
                ) : null
              ) : (
                <FormField label={t("claims.warranty.caseNumber")}>
                  <TextInput
                    value={form.manufacturer_case_number ?? ""}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        manufacturer_case_number: e.target.value,
                      })
                    }
                  />
                </FormField>
              )}
              <FormField label={t("claims.warranty.problem")}>
                {closed || isDealerViewer ? (
                  <p className="tv-warranty-problem">
                    {claim.description || "—"}
                  </p>
                ) : (
                  <TextArea
                    rows={3}
                    value={form.description ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, description: e.target.value })
                    }
                  />
                )}
              </FormField>
              {closed && (
                <p className="tv-warranty-closed">
                  {t("claims.detail.closedNote")}
                </p>
              )}
            </div>
          </Panel>
        </div>
      ),
    },
    {
      id: "items",
      label: t("claims.detailTab.items"),
      content: (
        <Panel title={t("claims.detail.itemsTitle")}>
          <div className="tv-claim-lines">
            {claim.lines.length === 0 && (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {t("claims.detail.noItems")}
              </p>
            )}
            {claim.lines.map((line) => (
              <div key={line.id} className="tv-claim-line">
                <span>
                  <strong>{line.target_name}</strong>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    {line.target_kind === "set" &&
                      `· ${t("claims.detail.lineWholeSet")}${line.include_addons ? `, ${t("claims.detail.lineAddonsIncluded")}` : `, ${t("claims.detail.lineAddonsNotIncluded")}`}`}
                    {line.target_kind === "piece" &&
                      `· ${t("claims.detail.linePieceOf").replace("{name}", line.set_name ?? "")}`}
                    {line.target_kind === "piece" &&
                      line.target_part_number &&
                      ` · ${t("claims.line.partNumber")} ${line.target_part_number}`}
                    {line.target_kind === "piece" &&
                      line.set_model_number &&
                      ` · ${t("claims.line.setModelNumber")} ${line.set_model_number}`}
                    {line.target_kind === "battery" && `· ${t("claims.detail.lineBattery")}`}
                    {" "}· {t(`claims.basis.${line.value_basis}` as never)} —{" "}
                    {t("claims.detail.lineRecordedNote")}
                  </span>
                </span>
                <strong>
                  <SellerPrice amount={line.amount} currency={claim.owner_currency} />
                </strong>
              </div>
            ))}
            <div className="tv-claim-total">
              <strong>{t("claims.detail.claimTotal")}</strong>
              <strong>
                <SellerPrice amount={claim.total_amount} currency={claim.owner_currency} />
              </strong>
            </div>
          </div>
        </Panel>
      ),
    },
    {
      id: "evidence",
      label: t("claims.detailTab.evidence"),
      content: (
        <Panel title={t("claims.detail.evidenceTitle")}>
          <EvidenceSection
            claim={claim}
            targets={targets}
            editable={!closed}
            canRemove={claim.viewer_role === "owner" && !closed}
            onClaimChange={setClaim}
            layout="tiles"
          />
        </Panel>
      ),
    },
    {
      id: "repair",
      label: t("claims.detailTab.repair"),
      content: <RepairPanel claim={claim} busy={busy} onTransition={doTransition} />,
    },
    {
      id: "comms",
      label: t("claims.detailTab.comms"),
      content: <CommsPanel claim={claim} onClaimChange={setClaim} />,
    },
  ];

  return (
    <RequireAuth>
      <div className="tv-claims-page">
        <div>
          {isDealerViewer ? (
            <Link to="/" className="tv-claim-backlink">
              {t("claims.detail.backToDashboard")}
            </Link>
          ) : (
            <Link to="/repairs#repair-claims" className="tv-claim-backlink">
              {t("claims.detail.backAll")}
            </Link>
          )}
          <SectionPageHeader
            thumb={<ArtIcon name="repairs" size={96} />}
            title={claim.claim_number}
            facts={headerFacts}
            factsExtra={
              <span className="tv-claim-headmeta">
                <StatusBadge status={claim.status} />
                <Badge tone="accent">{t("claims.kind.warranty")}</Badge>
                {claim.archived && (
                  <Badge tone="neutral">{t("claims.detail.archived")}</Badge>
                )}
                {claim.reported_at && (
                  <span className="tv-claim-muted">
                    {claim.report_method === "system"
                      ? t("claims.warranty.reportedBySystem")
                      : t("claims.warranty.reportedByUser")}
                    {" · "}
                    {fullDate(claim.reported_at)}
                  </span>
                )}
              </span>
            }
            actions={
              <ClaimActionsMenu
                claimNumber={claim.claim_number}
                entries={menuEntries}
                disabled={busy}
              />
            }
            statusStrip={
              <ClaimStatusStrip claim={claim} onJump={setActiveTab} />
            }
          />
        </div>

        <Tabs tabs={tabs} activeId={activeTab} onChange={setActiveTab} />
      </div>

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("claims.detail.deleteTitle").replace("{number}", claim.claim_number)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              {t("claims.detail.keepIt")}
            </Button>
            <Button variant="danger" disabled={busy} onClick={doDelete}>
              {t("claims.detail.deleteDraft")}
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>
          {t("claims.detail.deleteBody")}
        </p>
      </Modal>
    </RequireAuth>
  );
}
