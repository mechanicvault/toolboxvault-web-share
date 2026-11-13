import { useCallback, useEffect, useRef, useState } from "react";
import "./claims.css";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Checkbox,
  FormField,
  Panel,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import {
  createWarrantyClaim,
  getClaimsStats,
  getWarrantyFilingOptions,
  listClaims,
  replaceItem,
} from "./api";
import { ClaimWalkthrough } from "../walkthroughs/ClaimWalkthrough";
import { shouldOfferClaim } from "../walkthroughs/logic";
import { WalkthroughOffer } from "../walkthroughs/WalkthroughShell";
import type { TargetKind, WarrantyAgent, WarrantyFilingOptions } from "./types";

/**
 * The Claims / Replace tab's action panels (owner model,
 * 2026-10-25; merged model, 2026-11-04). Exactly ONE panel shows
 * per item state:
 *
 *  - BROKEN: the broken prompt — marking an item broken is not
 *    the end of the story; the item asks what happens next:
 *    start a warranty claim, replace it, or delete it.
 *  - NOT BROKEN: the default panel — Start a claim AND Replace
 *    item side by side. A claim is how a repair happens now
 *    (warranty or paid, it runs through the claim); a replace
 *    needs no claim and works on a healthy item too.
 *
 * On a SET, any single piece can be claimed on its own from
 * here too (piece claims are the normal case — the claim names
 * the piece and the set it came from).
 *
 * Best-effort like its sibling panels: it self-fetches the item,
 * hides entirely when the claims module doesn't answer, and
 * re-reads the item when an action elsewhere on the page
 * changes its standing (the "tv:item-standing-changed" event).
 */

interface PieceShape {
  id: string;
  name: string;
  part_number: string;
  status: string;
  repair_state?: string;
}

interface ItemShape {
  id: string;
  name: string;
  standing: string;
  is_set?: boolean;
  set?: {
    core_pieces: PieceShape[];
    addon_pieces: PieceShape[];
  } | null;
}

export interface ClaimFormData {
  problem: string;
  dealer_notified: boolean;
  include_addons: boolean;
  /* Agent choice (agent scope, 2026-10-31): all three stay
   * undefined when the options fetch didn't answer — the claim
   * then takes the backend default (the agent on record). */
  agent_user_id?: string | null;
  private_agent_id?: string | null;
  no_agent?: boolean;
  /* Filing route (claims overhaul, 2026-11-06): Ryan's three
   * routes — through the agent, on your own, or straight with
   * the dealer company. Undefined only when the options fetch
   * didn't answer (backend default then applies). */
  filed_with?: "agent" | "self" | "corporate";
}

function agentKey(agent: WarrantyAgent): string {
  return agent.agent_user_id
    ? `platform:${agent.agent_user_id}`
    : `private:${agent.private_agent_id}`;
}

/** The warranty claim form — shared by the Claims / Replace
 *  tab's panels below and the dealer page's claim picker, so
 *  every entry point rides the identical flow: the agent step
 *  with the agent on record as the default, the told-them
 *  question, the addons choice for sets. */
export function ClaimForm({
  showAddons,
  busy,
  targetKind,
  targetId,
  onCreate,
  onCancel,
}: {
  showAddons: boolean;
  busy: boolean;
  targetKind: TargetKind;
  targetId: string;
  onCreate: (data: ClaimFormData) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [problem, setProblem] = useState("");
  const [notified, setNotified] = useState(false);
  const [includeAddons, setIncludeAddons] = useState(false);
  /* The agent step: the owner's agents on record for this item's
   * dealer, fetched per target. "" = untouched (the default
   * agent stays selected); "none" = the owner's explicit
   * no-agent pick. */
  const [options, setOptions] = useState<WarrantyFilingOptions | null>(null);
  const [picked, setPicked] = useState("");
  /* The filing route (claims overhaul, 2026-11-06): "" =
   * untouched — the route then defaults to the agent route when
   * an agent is on record, else the owner's own route. */
  const [route, setRoute] = useState<"" | "agent" | "self" | "corporate">("");
  /* The walkthrough's one-time offer (sweep D3): while the
   * warranty list itself (archived included) says this user
   * has never filed, the form offers the guided pass. Real
   * data, no dismiss flag — the offer retires itself when a
   * first claim exists. Piece claims skip it: the guided pass
   * files whole items. */
  const [walkOffer, setWalkOffer] = useState(false);
  const [walkOpen, setWalkOpen] = useState(false);
  useEffect(() => {
    if (targetKind === "piece") return;
    let cancelled = false;
    listClaims(true)
      .then((rows) => {
        if (!cancelled) setWalkOffer(shouldOfferClaim(rows));
      })
      .catch(() => {
        if (!cancelled) setWalkOffer(false);
      });
    return () => {
      cancelled = true;
    };
  }, [targetKind, targetId]);
  useEffect(() => {
    let cancelled = false;
    setOptions(null);
    setPicked("");
    setRoute("");
    getWarrantyFilingOptions(targetKind, targetId)
      .then((result) => {
        if (!cancelled) setOptions(result);
      })
      .catch(() => {
        if (!cancelled) setOptions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [targetKind, targetId]);

  const agents = options?.agents ?? [];
  /* The pick list groups the same way the dealer roster does
   * (owner, 2026-11-04): the owner's own entered agents first,
   * the dealer's listed (registered) agents below — the filing
   * options read carries each agent's kind, so the grouping is
   * a partition of the same list, order preserved inside each
   * group. */
  const yourAgents = agents.filter((a) => a.kind === "private");
  const listedAgents = agents.filter((a) => a.kind === "platform");
  const defaultKey = options
    ? options.default_agent_user_id
      ? `platform:${options.default_agent_user_id}`
      : options.default_private_agent_id
        ? `private:${options.default_private_agent_id}`
        : "none"
    : "none";
  const selectedKey = picked || defaultKey;
  const selectedAgent =
    agents.find((agent) => agentKey(agent) === selectedKey) ?? null;
  const agentOption = (agent: WarrantyAgent) => (
    <option key={agentKey(agent)} value={agentKey(agent)}>
      {agent.name}
      {agentKey(agent) === defaultKey
        ? t("claims.broken.agentDefaultSuffix")
        : ""}
    </option>
  );
  const showAgentStep = Boolean(
    options && options.dealer_company_id && agents.length > 0,
  );
  /* Ryan's three filing routes (2026-11-05 #6): offered when the
   * item names a dealer (no dealer = no agent to pick and no
   * company to file with — the claim is the owner's alone, as
   * ever). The agent route needs at least one agent on record;
   * the default route is the agent's when an agent is on record
   * (the multi-preferred default: the earliest flagged), else
   * the owner's own. */
  const showRouteStep = Boolean(options && options.dealer_company_id);
  const activeRoute: "agent" | "self" | "corporate" =
    route ||
    (options?.default_agent_user_id || options?.default_private_agent_id
      ? "agent"
      : "self");
  const routeAgent = activeRoute === "agent" ? selectedAgent : null;

  return (
    <div className="tv-broken-form">
      {walkOffer && (
        <>
          <WalkthroughOffer
            body={t("walk.claim.offer" as never)}
            onStart={() => setWalkOpen(true)}
            testId="walk-claim-offer"
          />
          <ClaimWalkthrough
            open={walkOpen}
            initialTarget={{ kind: targetKind, id: targetId }}
            onClose={() => setWalkOpen(false)}
          />
        </>
      )}
      <FormField label={t("claims.broken.problem")}>
        <TextArea
          rows={2}
          value={problem}
          onChange={(e) => setProblem(e.target.value)}
        />
      </FormField>
      {showAddons && (
        <Checkbox
          checked={includeAddons}
          onChange={(e) => setIncludeAddons(e.target.checked)}
          label={t("claims.broken.includeAddons")}
        />
      )}
      {showRouteStep && (
        <FormField label={t("claims.broken.filedWith")}>
          <div className="tv-broken-choices">
            <label className="tv-broken-choice">
              <input
                type="radio"
                name="filed-with"
                checked={activeRoute === "agent"}
                disabled={agents.length === 0}
                onChange={() => {
                  setRoute("agent");
                  // Coming back from a "no agent" pick: the
                  // default agent re-selects.
                  if (picked === "none") setPicked("");
                }}
              />
              {t("claims.broken.routeAgent")}
            </label>
            <label className="tv-broken-choice">
              <input
                type="radio"
                name="filed-with"
                checked={activeRoute === "self"}
                onChange={() => setRoute("self")}
              />
              {t("claims.broken.routeSelf")}
            </label>
            <label className="tv-broken-choice">
              <input
                type="radio"
                name="filed-with"
                checked={activeRoute === "corporate"}
                onChange={() => setRoute("corporate")}
              />
              {t("claims.broken.routeCorporate")}
            </label>
          </div>
        </FormField>
      )}
      {showAgentStep && activeRoute === "agent" && (
        <FormField label={t("claims.broken.agent")}>
          <Select
            value={selectedKey}
            onChange={(e) => {
              setPicked(e.target.value);
              // "No agent" in the picker IS the owner's own
              // route — the radio follows the substance.
              if (e.target.value === "none") setRoute("self");
            }}
          >
            {yourAgents.length > 0 && (
              <optgroup label={t("dealers.roster.yoursTitle")}>
                {yourAgents.map(agentOption)}
              </optgroup>
            )}
            {listedAgents.length > 0 && (
              <optgroup label={t("dealers.roster.listedTitle")}>
                {listedAgents.map(agentOption)}
              </optgroup>
            )}
            <option value="none">{t("claims.broken.agentNone")}</option>
          </Select>
        </FormField>
      )}
      {/* The told-them question exists when there is somebody to
          have told: the picked agent, or the dealer company on
          the corporate route (or the options fetch failed and
          the classic flow applies). On the owner's own route
          there is nobody to notify — he tracks the claim himself. */}
      {(!options || routeAgent || activeRoute === "corporate") && (
        <FormField
          label={
            routeAgent
              ? t("claims.broken.notifiedAgent")
              : t("claims.broken.notified")
          }
        >
          <div className="tv-broken-choices">
            <label className="tv-broken-choice">
              <input
                type="radio"
                name="dealer-notified"
                checked={notified}
                onChange={() => setNotified(true)}
              />
              {t("claims.broken.notifiedYes")}
            </label>
            <label className="tv-broken-choice">
              <input
                type="radio"
                name="dealer-notified"
                checked={!notified}
                onChange={() => setNotified(false)}
              />
              {t("claims.broken.notifiedNo")}
            </label>
          </div>
        </FormField>
      )}
      <div className="tv-broken-actions">
        <Button
          size="sm"
          disabled={busy}
          onClick={() =>
            onCreate({
              problem: problem.trim(),
              /* Nobody to have told on the owner's own route; the
               * owner tracks the claim himself from
               * not_reported. */
              dealer_notified:
                activeRoute === "self" && options ? false : notified,
              include_addons: includeAddons,
              ...(options
                ? {
                    filed_with: activeRoute,
                    agent_user_id: routeAgent?.agent_user_id ?? null,
                    private_agent_id: routeAgent?.private_agent_id ?? null,
                    no_agent: activeRoute !== "agent" || !routeAgent,
                  }
                : {}),
            })
          }
        >
          {t("claims.broken.createClaim")}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          {t("claims.broken.cancel")}
        </Button>
      </div>
    </div>
  );
}

/** The replace flow, shared by the broken prompt and the
 *  default panel: exact-same (the new item carries the old
 *  one's data; price becomes what was spent, date becomes
 *  today) or different/upgraded (the old item retires and the
 *  normal add flow opens). A replace never creates a claim. */
function ReplaceForm({
  busy,
  onReplace,
  onCancel,
}: {
  busy: boolean;
  onReplace: (mode: "same" | "different", amount: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [replaceMode, setReplaceMode] = useState<"same" | "different">("same");
  const [amount, setAmount] = useState("");
  return (
    <div className="tv-broken-form">
      <FormField label={t("claims.broken.sameOrDifferent")}>
        <div className="tv-broken-choices">
          <label className="tv-broken-choice">
            <input
              type="radio"
              name="replace-mode"
              checked={replaceMode === "same"}
              onChange={() => setReplaceMode("same")}
            />
            {t("claims.broken.same")}
          </label>
          <label className="tv-broken-choice">
            <input
              type="radio"
              name="replace-mode"
              checked={replaceMode === "different"}
              onChange={() => setReplaceMode("different")}
            />
            {t("claims.broken.different")}
          </label>
        </div>
      </FormField>
      {replaceMode === "same" && (
        <FormField label={t("claims.broken.amountSpent")}>
          <TextInput
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="15.00"
          />
        </FormField>
      )}
      <div className="tv-broken-actions">
        <Button size="sm" disabled={busy} onClick={() => onReplace(replaceMode, amount)}>
          {t("claims.broken.replace")}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          {t("claims.broken.cancel")}
        </Button>
      </div>
    </div>
  );
}

export function BrokenItemActions({
  itemKind,
  itemId,
  openSignal = 0,
}: {
  itemKind: "tool" | "battery";
  itemId: string;
  /** The Actions menu's "Start a claim" bump: opens the claim
   *  form in whichever panel is showing (the folded-in job of
   *  the old standalone start-claim action, merge 2026-11-04). */
  openSignal?: number;
}) {
  const t = useT();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [item, setItem] = useState<ItemShape | null>(null);
  const [claimsOff, setClaimsOff] = useState(false);
  const [view, setView] = useState<"choices" | "claim" | "replace" | "delete">(
    "choices",
  );
  const [pieceClaim, setPieceClaim] = useState<PieceShape | null>(null);
  const [busy, setBusy] = useState(false);
  /* B-02/B-03 (Deep Audit Round 2): the F2-21 synchronous ref
   * guards. React `busy` state cannot stop same-task triple
   * clicks — the re-render that disables the buttons lands after
   * all three handlers have already read busy=false — so each
   * write path carries a ref set SYNCHRONOUSLY before its first
   * await. One guard per path: a claim in flight must not block
   * a replace, and vice versa. The shared ClaimForm below routes
   * BOTH the whole-item claim and the set-piece claims through
   * startClaim, so the claim guard covers the set-piece path too. */
  const claimBusyRef = useRef(false);
  const replaceBusyRef = useRef(false);
  const deleteBusyRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const path =
        itemKind === "tool"
          ? `/inventory/${itemId}`
          : `/inventory/batteries/${itemId}`;
      setItem(await api<ItemShape>(path));
    } catch {
      setItem(null);
    }
  }, [itemKind, itemId]);

  useEffect(() => {
    void load();
    const onStanding = () => void load();
    window.addEventListener("tv:item-standing-changed", onStanding);
    return () => window.removeEventListener("tv:item-standing-changed", onStanding);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    getClaimsStats()
      .catch(() => {
        if (!cancelled) setClaimsOff(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /* The Actions menu asked for the claim form: open it in the
   * panel on screen (broken prompt and default panel alike). */
  const firstSignal = useRef(openSignal);
  useEffect(() => {
    if (openSignal !== firstSignal.current) {
      firstSignal.current = openSignal;
      setView("claim");
    }
  }, [openSignal ]);

  if (claimsOff || item === null) return null;

  const pieces: PieceShape[] =
    itemKind === "tool" && item.set
      ? [...item.set.core_pieces, ...item.set.addon_pieces]
      : [];
  const broken = item.standing === "broken";

  /* A piece follows the item rule (merge, 2026-11-04): it can
   * sit broken with no claim — Mark broken / Back in service are
   * the piece's own steps, written through the piece update (the
   * move into in_repair stays the claim lifecycle's alone). */
  async function setPieceStanding(
    piece: PieceShape,
    next: "broken" | "in_service",
  ) {
    try {
      await api(`/inventory/pieces/${piece.id}`, {
        method: "PUT",
        body: JSON.stringify({ repair_state: next }),
      });
      toast(
        next === "broken"
          ? t("claims.broken.pieceMarkedBroken")
          : t("claims.broken.pieceBack"),
        { tone: "success" },
      );
      window.dispatchEvent(new Event("tv:item-standing-changed"));
      void load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That didn't work.", {
        tone: "danger",
      });
    }
  }

  async function startClaim(
    targetKind: TargetKind,
    targetId: string,
    data: ClaimFormData,
  ) {
    if (claimBusyRef.current) return;
    claimBusyRef.current = true;
    setBusy(true);
    try {
      const result = await createWarrantyClaim({
        target_kind: targetKind,
        target_id: targetId,
        include_addons: data.include_addons,
        dealer_notified: data.dealer_notified,
        problem: data.problem,
        agent_user_id: data.agent_user_id,
        private_agent_id: data.private_agent_id,
        no_agent: data.no_agent,
        filed_with: data.filed_with,
      });
      toast(
        result.reported
          ? t("claims.broken.claimReported")
          : t("claims.broken.claimNotReported"),
        { tone: "success", title: result.claim.claim_number },
      );
      navigate(`/claims/${result.claim.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't start that claim.", {
        tone: "danger",
        title: "Claims",
      });
      claimBusyRef.current = false;
      setBusy(false);
    }
  }

  async function doReplace(mode: "same" | "different", amount: string) {
    if (replaceBusyRef.current) return;
    replaceBusyRef.current = true;
    setBusy(true);
    try {
      const spent = amount.trim() ? Number(amount) : null;
      const result = await replaceItem({
        item_kind: itemKind,
        item_id: itemId,
        mode,
        amount_spent: spent !== null && Number.isFinite(spent) ? spent : null,
      });
      if (result.new_item) {
        toast(t("claims.broken.replaced"), {
          tone: "success",
          title: result.new_item.name,
        });
        navigate(
          itemKind === "tool"
            ? `/inventory/${result.new_item.id}`
            : `/inventory/batteries/${result.new_item.id}`,
        );
      } else {
        toast(t("claims.broken.retired"), { tone: "success" });
        navigate("/inventory/new");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't replace that item.", {
        tone: "danger",
        title: "Claims",
      });
      replaceBusyRef.current = false;
      setBusy(false);
    }
  }

  async function doDelete() {
    if (deleteBusyRef.current) return;
    deleteBusyRef.current = true;
    setBusy(true);
    try {
      const path =
        itemKind === "tool"
          ? `/inventory/${itemId}`
          : `/inventory/batteries/${itemId}`;
      await api(path, { method: "DELETE" });
      navigate("/inventory");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't delete that item.", {
        tone: "danger",
        title: "Claims",
      });
      deleteBusyRef.current = false;
      setBusy(false);
    }
  }

  const claimForm = (
    <ClaimForm
      showAddons={Boolean(item.is_set)}
      busy={busy}
      targetKind={item.is_set ? "set" : itemKind}
      targetId={itemId}
      onCancel={() => setView("choices")}
      onCreate={(data) =>
        startClaim(item.is_set ? "set" : itemKind, itemId, data)
      }
    />
  );

  return (
    <>
      {broken ? (
        <Panel title={t("claims.broken.title")}>
          {view === "choices" && (
            <div className="tv-broken-form">
              <p className="tv-broken-muted">{t("claims.broken.body")}</p>
              <div className="tv-broken-actions">
                <Button size="sm" onClick={() => setView("claim")}>
                  {t("claims.broken.startClaim")}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setView("replace")}
                >
                  {t("claims.broken.replace")}
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => setView("delete")}
                >
                  {t("claims.broken.delete")}
                </Button>
              </div>
            </div>
          )}
          {view === "claim" && claimForm}
          {view === "replace" && (
            <ReplaceForm
              busy={busy}
              onReplace={doReplace}
              onCancel={() => setView("choices")}
            />
          )}
          {view === "delete" && (
            <div className="tv-broken-form">
              <p className="tv-broken-muted">{t("claims.broken.deleteConfirm")}</p>
              <div className="tv-broken-actions">
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy}
                  onClick={doDelete}
                >
                  {t("claims.broken.deleteNow")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => setView("choices")}
                >
                  {t("claims.broken.cancel")}
                </Button>
              </div>
            </div>
          )}
        </Panel>
      ) : (
        <Panel title={t("claims.tab.defaultTitle")}>
          {view === "choices" && (
            <div className="tv-broken-form">
              <p className="tv-broken-muted">{t("claims.tab.defaultBody")}</p>
              <div className="tv-broken-actions">
                <Button size="sm" onClick={() => setView("claim")}>
                  {t("claims.tab.startClaim")}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setView("replace")}
                >
                  {t("claims.tab.replaceItem")}
                </Button>
              </div>
            </div>
          )}
          {view === "claim" && claimForm}
          {view === "replace" && (
            <ReplaceForm
              busy={busy}
              onReplace={doReplace}
              onCancel={() => setView("choices")}
            />
          )}
        </Panel>
      )}

      {pieces.length > 0 && (
        <Panel title={t("claims.broken.piecesTitle")}>
          <div className="tv-broken-pieces">
            <p className="tv-broken-muted">{t("claims.broken.piecesBody")}</p>
            {pieces.map((piece) => (
              <div key={piece.id} className="tv-broken-piece-row">
                <span>
                  <strong>{piece.name}</strong>
                  {piece.part_number && (
                    <span className="tv-broken-muted">
                      {" "}
                      · {t("claims.line.partNumber")} {piece.part_number}
                    </span>
                  )}
                  {piece.repair_state === "broken" && (
                    <>
                      {" "}
                      <Badge tone="danger" dot>
                        {t("inventory.status.broken" as never)}
                      </Badge>
                    </>
                  )}
                  {piece.repair_state === "in_repair" && (
                    <>
                      {" "}
                      <Badge tone="warning" dot>
                        {t("inventory.status.sentOut" as never)}
                      </Badge>
                    </>
                  )}
                </span>
                <span className="tv-broken-actions">
                  {piece.repair_state === "in_service" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void setPieceStanding(piece, "broken")}
                    >
                      {t("claims.broken.markPieceBroken")}
                    </Button>
                  )}
                  {piece.repair_state === "broken" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void setPieceStanding(piece, "in_service")}
                    >
                      {t("claims.broken.pieceBackInService")}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => setPieceClaim(piece)}
                  >
                    {t("claims.broken.startPieceClaim")}
                  </Button>
                </span>
              </div>
            ))}
            {pieceClaim && (
              <ClaimForm
                showAddons={false}
                busy={busy}
                targetKind="piece"
                targetId={pieceClaim.id}
                onCancel={() => setPieceClaim(null)}
                onCreate={(data) => startClaim("piece", pieceClaim.id, data)}
              />
            )}
          </div>
        </Panel>
      )}
    </>
  );
}
