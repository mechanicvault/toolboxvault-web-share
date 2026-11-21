import { useEffect, useState } from "react";
import "./claims.css";
import { Link } from "react-router-dom";
import { Alert, Badge, LinkButton, Panel, Spinner } from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { SellerPrice } from "../../components/SellerPrice";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { getClaim } from "./api";
import { CHECKLIST_KEYS, StatusBadge } from "./components";
import { fullDate } from "./format";
import type { Claim, ClaimStatus, ClaimSummary } from "./types";

/**
 * The Side List (owner's name for the split pattern, 2026-11-13;
 * R2 pick for Repair claims): a scrolling claim list on the
 * LEFT, the picked claim's whole story on the RIGHT — no page
 * hop to understand a claim. The owner picked this layout for
 * BOTH Repairs tabs: open claims lead with the tool, what
 * broke, the status, the cost and the days open, and the panel
 * answers "how far along is it" (a plain-words stepper) and
 * "what is left for me to do" (the claim's real computed
 * to-do list, spelled out — the mystery "3/4" bar is gone);
 * history claims show the finished story instead: the stepper
 * complete, the outcome in plain words, the final cost, the
 * opened → closed dates, and the notes the record carries.
 * The checklist is the server's computed list (never stored,
 * derived from the claim itself), so the panel renders it
 * read-only exactly as the claim page does — warranty items
 * complete themselves as the claim moves, there is no toggle.
 *
 * Geometry carries the shared Side List values (list column
 * minmax(17rem, 24rem), the shared gap, list max-height 74vh,
 * the 56rem stack breakpoint) — the same numbers as the
 * Dealers Side List's .tv-sidelist-* frame. The claims rows
 * and panel are richer than the shared SideListRow slots, so
 * this surface keeps its own markup on those values; the
 * frame-component unification rides the merge (INDEX flags
 * it).
 */

const STAGES = [
  { name: "claims.step.reported", sub: "claims.step.reportedSub" },
  { name: "claims.step.sentIn", sub: "claims.step.sentInSub" },
  { name: "claims.step.waiting", sub: "claims.step.waitingSub" },
  { name: "claims.step.resolved", sub: "claims.step.resolvedSub" },
] as const;

/** Where a warranty status sits on the four plain stages:
 *  the index of the stage the claim is currently IN (stages
 *  before it render done; 4 = past the last one). The ladder
 *  order is Ryan's (WARRANTY_STATUSES): a claim that has only
 *  been reported is still IN the reported stage; waiting on
 *  the agent IS the send-in happening; agent_has_tool is the
 *  resolved stage arriving — repaired, with the agent, on its
 *  way back. */
function stageIndex(status: ClaimStatus): number {
  switch (status) {
    case "reported":
      return 0;
    case "waiting_on_agent":
      return 1;
    case "waiting_on_parts":
    case "in_repair":
    case "backordered":
      return 2;
    case "agent_has_tool":
      return 3;
    case "completed":
      return 4;
    default:
      return 0;
  }
}

/** Whole days from an ISO timestamp to today (date-only math,
 *  the deadlineState convention). */
function daysSince(iso: string): number {
  const start = new Date(`${iso.slice(0, 10)}T12:00:00`);
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  return Math.max(0, Math.round((today.getTime() - start.getTime()) / 86400000));
}

type T = ReturnType<typeof useT>;

function daysOpenLabel(t: T, claim: ClaimSummary): string {
  const days = daysSince(claim.reported_at ?? claim.created_at);
  return days === 1
    ? t("claims.split.dayOpen")
    : t("claims.split.daysOpen").replace("{days}", String(days));
}

function toolTitle(claim: ClaimSummary): string {
  return claim.first_item_name || claim.claim_number;
}

/** A finished claim's repaired date: when the repair
 *  completed, else when it closed, else its last change.
 *  (Owner, 2026-11-14: Date Claimed and Date Repaired are
 *  the main dates on every claim area.) */
function repairedIso(claim: ClaimSummary, detail: Claim | null): string {
  return (
    claim.repair_completed_at ??
    detail?.repair_completed_at ??
    claim.closed_at ??
    claim.updated_at
  );
}

/** Who the claim runs through, for the row's party line:
 *  the dealer, and the agent when the claim names one. */
function partyLine(claim: ClaimSummary): string {
  return [claim.dealer_name, claim.warranty_agent_name]
    .filter((x) => x && x.trim() !== "")
    .join(" · ");
}

function ClaimSplitRow({
  claim,
  view,
  selected,
  onSelect,
}: {
  claim: ClaimSummary;
  view: "open" | "history";
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  return (
    <button
      type="button"
      className={`tv-claim-split-row${selected ? " tv-claim-split-row--selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="tv-claim-split-row-top">
        <strong className="tv-claim-split-row-tool">
          {toolTitle(claim)}
          {claim.line_count > 1 && (
            <span className="tv-claim-split-row-more">
              {" "}
              {t("claims.split.plusMore").replace(
                "{count}",
                String(claim.line_count - 1),
              )}
            </span>
          )}
        </strong>
        <StatusBadge status={claim.status} />
      </span>
      <span className="tv-claim-split-row-mid">
        <span className="tv-claim-split-row-meta">
          {t("claims.split.claimedOn").replace(
            "{date}",
            fullDate((claim.reported_at ?? claim.created_at).slice(0, 10)),
          )}
          {view === "history" &&
            (claim.repair_completed_at
              ? ` · ${t("claims.split.repairedOn").replace(
                  "{date}",
                  fullDate(claim.repair_completed_at.slice(0, 10)),
                )}`
              : ` · ${t("claims.split.closedOn").replace(
                  "{date}",
                  fullDate(
                    (claim.closed_at ?? claim.updated_at).slice(0, 10),
                  ),
                )}`)}
        </span>
        <strong className="tv-claim-amount">
          <SellerPrice
            amount={claim.total_amount}
            currency={claim.owner_currency}
          />
        </strong>
      </span>
      <span className="tv-claim-split-row-party">
        <span className="tv-claim-split-row-partyname">
          {partyLine(claim)}
        </span>
        <span className="tv-claim-split-row-num">{claim.claim_number}</span>
      </span>
      {claim.description && (
        <span className="tv-claim-split-row-desc">{claim.description}</span>
      )}
    </button>
  );
}

function Stepper({
  claim,
  finished,
}: {
  claim: Claim;
  finished: boolean;
}) {
  const t = useT();
  const current = finished ? STAGES.length : stageIndex(claim.status);
  return (
    <div>
      <h3 className="tv-claim-split-h">{t("claims.split.howFar")}</h3>
      <ol className="tv-claim-split-steps">
        {STAGES.map((stage, i) => {
          const state =
            i < current ? "done" : i === current ? "current" : "todo";
          return (
            <li
              key={stage.name}
              className={`tv-claim-split-step tv-claim-split-step--${state}`}
            >
              <span className="tv-claim-split-step-dot" aria-hidden="true">
                {state === "done" ? "✓" : i + 1}
              </span>
              <span className="tv-claim-split-step-text">
                <span className="tv-claim-split-step-name">
                  {t(stage.name as never)}
                  {state === "current" && (
                    <span className="tv-claim-split-here">
                      {t("claims.step.here")}
                    </span>
                  )}
                </span>
                <span className="tv-claim-split-step-sub">
                  {t(stage.sub as never)}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Fact({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="tv-claim-split-fact">
      <span className="tv-claim-split-fact-label">{label}</span>
      <span className="tv-claim-split-fact-value">{children}</span>
    </div>
  );
}

function ClaimDetailPanel({
  summary,
  view,
}: {
  summary: ClaimSummary;
  view: "open" | "history";
}) {
  const t = useT();
  const [detail, setDetail] = useState<Claim | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    getClaim(summary.id)
      .then((claim) => {
        if (!cancelled) setDetail(claim);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : t("claims.detail.couldntLoad"),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [summary.id, t]);

  const finished = view === "history";
  const firstLine = detail?.lines[0];
  const title = firstLine?.target_name || toolTitle(summary);
  const openedIso = summary.reported_at ?? summary.created_at;

  return (
    <div className="tv-claim-split-detail">
      <div className="tv-claim-split-detail-head">
        <span className="tv-claim-split-detail-art" aria-hidden="true">
          <ArtIcon name="claims" size={44} />
        </span>
        <div className="tv-claim-split-detail-title">
          <span className="tv-claim-split-detail-name">
            {title}
            <StatusBadge status={summary.status} />
            {summary.archived && (
              <Badge tone="neutral">{t("claims.detail.archived")}</Badge>
            )}
          </span>
          <span className="tv-claim-split-detail-meta">
            {t("claims.split.claimedOn").replace(
              "{date}",
              fullDate(openedIso.slice(0, 10)),
            )}
            {!finished && ` · ${daysOpenLabel(t, summary)}`}
            {finished &&
              (summary.repair_completed_at ?? detail?.repair_completed_at
                ? ` · ${t("claims.split.repairedOn").replace(
                    "{date}",
                    fullDate(repairedIso(summary, detail).slice(0, 10)),
                  )}`
                : ` · ${t("claims.split.closedOn").replace(
                    "{date}",
                    fullDate(
                      (summary.closed_at ?? summary.updated_at).slice(0, 10),
                    ),
                  )}`)}
          </span>
        </div>
        <div className="tv-claim-split-detail-amount">
          <span className="tv-claim-split-fact-label">
            {t("claims.detail.claimTotal")}
          </span>
          <strong className="tv-claim-split-detail-total">
            <SellerPrice
              amount={summary.total_amount}
              currency={summary.owner_currency}
            />
          </strong>
          <span className="tv-claim-split-detail-num">
            {summary.claim_number}
          </span>
        </div>
      </div>

      {error && <Alert tone="danger">{error}</Alert>}
      {!detail && !error && (
        <div className="tv-claim-loading">
          <Spinner />
        </div>
      )}

      {detail && (
        <>
          {detail.description && (
            <p className="tv-claim-split-broke">
              <span className="tv-claim-split-broke-label">
                {t("claims.split.whatBroke")}:
              </span>{" "}
              {detail.description}
            </p>
          )}

          <div className="tv-claim-split-cols">
            <Stepper claim={detail} finished={finished} />
            {!finished && (
              <div>
                <h3 className="tv-claim-split-h">
                  {t("claims.split.whatsLeft")} —{" "}
                  {t("claims.checklist.progress")
                    .replace("{done}", String(detail.checklist_done))
                    .replace("{total}", String(detail.checklist_total))}
                </h3>
                <div className="tv-claim-split-checks">
                  {detail.checklist.map((item) => (
                    <div
                      key={item.key}
                      className={`tv-claim-split-check${item.done ? " tv-claim-split-check--done" : ""}`}
                    >
                      <span
                        className="tv-claim-split-check-box"
                        aria-hidden="true"
                      >
                        {item.done ? "✓" : ""}
                      </span>
                      <span>
                        {(() => {
                          const key =
                            CHECKLIST_KEYS[
                              `${detail.kind === "warranty_repair" ? "warranty" : "insurance"}:${item.key}`
                            ];
                          return key ? t(key as never) : item.label;
                        })()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="tv-claim-split-facts">
            <Fact label={t("claims.split.dateClaimed")}>
              {fullDate(openedIso.slice(0, 10))}
            </Fact>
            {finished && (
              <Fact label={t("claims.split.outcome")}>
                {summary.archived
                  ? t("claims.detail.archived")
                  : summary.closed_at
                    ? t("claims.split.outcomeClosedWord")
                    : t(`claims.status.${summary.status}` as never)}
              </Fact>
            )}
            <Fact label={t("claims.col.parties")}>
              {detail.dealer_company_id ? (
                <Link
                  className="tv-claim-split-link"
                  to={`/dealers?dealer=${detail.dealer_company_id}`}
                >
                  {detail.dealer_name || "—"}
                </Link>
              ) : (
                detail.dealer_name || "—"
              )}
            </Fact>
            <Fact label={t("claims.split.filedThrough")}>
              {detail.warranty_agent
                ? detail.warranty_agent.name
                : detail.filed_with === "corporate"
                  ? t("claims.filedWith.corporateShort")
                  : detail.filed_with === "self"
                    ? t("claims.filedWith.self")
                    : "—"}
            </Fact>
            {detail.manufacturer_case_number && (
              <Fact label={t("claims.warranty.caseNumber")}>
                {detail.manufacturer_case_number}
              </Fact>
            )}
            {detail.repair_sent_to && (
              <Fact label={t("claims.repair.sentTo")}>
                {detail.repair_sent_to}
              </Fact>
            )}
            {detail.repair_cost !== null && (
              <Fact label={t("claims.repair.cost")}>
                <SellerPrice
                  amount={detail.repair_cost}
                  currency={detail.owner_currency}
                />
              </Fact>
            )}
            {finished && detail.repair_completed_at && (
              <Fact label={t("claims.split.dateRepaired")}>
                {fullDate(detail.repair_completed_at.slice(0, 10))}
              </Fact>
            )}
          </div>

          {detail.lines.length > 0 && (
            <div className="tv-claim-lines">
              {detail.lines.map((line) => (
                <div key={line.id} className="tv-claim-line">
                  <span>
                    <Link
                      className="tv-claim-split-link"
                      to={
                        line.target_kind === "battery"
                          ? `/inventory/battery/${line.target_id}`
                          : `/inventory/tool/${line.target_kind === "piece" && line.set_id ? line.set_id : line.target_id}`
                      }
                    >
                      {line.target_name}
                    </Link>
                    {line.target_kind === "piece" && line.set_name && (
                      <span className="tv-claim-mut-sm">
                        {" "}
                        {t("claims.detail.linePieceOf").replace(
                          "{name}",
                          line.set_name,
                        )}
                      </span>
                    )}
                  </span>
                  {line.amount !== null && (
                    <strong>
                      <SellerPrice
                        amount={line.amount}
                        currency={detail.owner_currency}
                      />
                    </strong>
                  )}
                </div>
              ))}
            </div>
          )}

          {finished && detail.communications.length > 0 && (
            <div>
              <h3 className="tv-claim-split-h">
                {t("claims.split.notesTitle")}
              </h3>
              <div className="tv-claim-split-notes">
                {detail.communications.map((entry) => (
                  <p key={entry.id} className="tv-claim-split-note">
                    <span className="tv-claim-mut-sm">
                      {fullDate(entry.occurred_at)} —{" "}
                    </span>
                    {entry.summary}
                  </p>
                ))}
              </div>
            </div>
          )}

          <div className="tv-claim-split-open">
            <LinkButton to={`/claims/${summary.id}`}>
              {t("claims.split.openFullClaim")} →
            </LinkButton>
          </div>
        </>
      )}
    </div>
  );
}

export function ClaimsSplit({
  claims,
  view,
}: {
  claims: ClaimSummary[];
  view: "open" | "history";
}) {
  const t = useT();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected =
    claims.find((claim) => claim.id === selectedId) ?? claims[0];

  return (
    <Panel
      title={
        view === "history" ? t("claims.historyTitle") : t("claims.yours")
      }
      className="tv-claims-panel"
    >
      <p className="tv-claim-split-hint">
        {t(
          view === "history"
            ? "claims.split.pickHintHistory"
            : "claims.split.pickHint",
        )}
      </p>
      <div className="tv-claim-split">
        <div
          className="tv-claim-split-list"
          role="list"
          aria-label={
            view === "history" ? t("claims.historyTitle") : t("claims.yours")
          }
        >
          {claims.map((claim) => (
            <ClaimSplitRow
              key={claim.id}
              claim={claim}
              view={view}
              selected={selected?.id === claim.id}
              onSelect={() => setSelectedId(claim.id)}
            />
          ))}
        </div>
        {selected && (
          <ClaimDetailPanel
            key={selected.id}
            summary={selected}
            view={view}
          />
        )}
      </div>
    </Panel>
  );
}
