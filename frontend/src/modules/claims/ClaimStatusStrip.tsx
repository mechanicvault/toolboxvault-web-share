import type { ReactNode } from "react";
import { Badge, type BadgeTone } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { deadlineState, fullDate } from "./format";
import type { Claim } from "./types";
import "./claims.css";

/**
 * A claim detail page's live-status strip (sweep C3,
 * 2026-11-12): the main-tab record layout's strip seat between
 * the header and the tabs — one entry per state the claim is
 * actually in (closed, archived, to-dos still open, a repair
 * out with someone, a proof-of-loss deadline pressing), each
 * entry a jump to the tab that holds the record. No live
 * states beyond the ordinary, no strip (the component returns
 * null) — the item page's ItemStatusStrip is the model.
 *
 * Every fact here is read off the claim view the page already
 * holds; the strip computes nothing the sections below don't
 * also show.
 */
export function ClaimStatusStrip({
  claim,
  onJump,
}: {
  claim: Claim;
  onJump: (tab: string) => void;
}) {
  const t = useT();
  const entries: ReactNode[] = [];
  const closed =
    claim.kind === "warranty_repair"
      ? claim.closed_at !== null
      : claim.status === "closed";

  const entry = (
    key: string,
    tone: BadgeTone,
    label: string,
    text: string | undefined,
    tab: string,
  ) => (
    <button
      key={key}
      type="button"
      className="tv-claim-status-entry"
      onClick={() => onJump(tab)}
    >
      <Badge tone={tone} dot>
        {label}
      </Badge>
      {text && <span className="tv-claim-status-text">{text}</span>}
    </button>
  );

  if (closed) {
    entries.push(
      entry("closed", "neutral", t("claims.status.closed"), undefined, "details"),
    );
  }
  if (claim.archived) {
    entries.push(
      entry(
        "archived",
        "neutral",
        t("claims.detail.archived"),
        undefined,
        "details",
      ),
    );
  }

  if (claim.kind !== "warranty_repair") {
    const pol = deadlineState(
      claim.proof_of_loss_due,
      claim.proof_of_loss_sent_at !== null,
    );
    if (claim.proof_of_loss_due && !claim.proof_of_loss_sent_at && pol !== "ok") {
      entries.push(
        entry(
          "pol",
          pol === "overdue" ? "danger" : "warning",
          t(
            pol === "overdue"
              ? "disasterClaims.polOverdue"
              : "disasterClaims.polDueSoon",
          ),
          fullDate(claim.proof_of_loss_due),
          "details",
        ),
      );
    }
    const dep = deadlineState(claim.depreciation_deadline, closed);
    if (claim.depreciation_deadline && dep !== "ok") {
      entries.push(
        entry(
          "dep",
          dep === "overdue" ? "danger" : "warning",
          t("claims.form.depreciation"),
          fullDate(claim.depreciation_deadline),
          "details",
        ),
      );
    }
  }

  if (!closed && claim.checklist_done < claim.checklist_total) {
    entries.push(
      entry(
        "todo",
        "accent",
        t("claims.checklist.title"),
        t("claims.checklist.progress")
          .replace("{done}", String(claim.checklist_done))
          .replace("{total}", String(claim.checklist_total)),
        "details",
      ),
    );
  }

  if (claim.kind === "warranty_repair" && claim.status === "in_repair") {
    entries.push(
      entry(
        "repair",
        "warning",
        t("claims.status.in_repair"),
        claim.repair_sent_to || undefined,
        "repair",
      ),
    );
  }
  if (
    claim.kind === "warranty_repair" &&
    claim.status === "completed" &&
    claim.repair_completed_at
  ) {
    entries.push(
      entry(
        "repaired",
        "success",
        t("claims.status.completed"),
        fullDate(claim.repair_completed_at),
        "repair",
      ),
    );
  }

  if (entries.length === 0) return null;
  return <div className="tv-claim-status">{entries}</div>;
}
