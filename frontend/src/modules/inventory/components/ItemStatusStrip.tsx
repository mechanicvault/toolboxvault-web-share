import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { Badge, type BadgeTone } from "../../../components";
import { api } from "../../../lib/api";
import { getItemLending } from "../../borrowing/api";
import { standingText } from "../../borrowing/format";
import type { Checkout } from "../../borrowing/types";
import { getItemClaims } from "../../claims/api";
import type { ItemClaims } from "../../claims/types";
import { displayDate } from "../format";
import {
  STANDING_LABELS,
  type LossReport,
  type Standing,
} from "../types";
import { STANDING_TONES } from "./StandingBadge";
import "../itemPage.css";

/**
 * The item page's live-status strip (owner spec, 2026-10-31):
 * between the header zone and the tabs, one entry per state the
 * item is actually in — marked lost/stolen (its loss report),
 * borrowed or requested (the loan), broken (its claim when one
 * exists), in repair, sold, replaced — each entry a link to the
 * record itself or a jump to the tab/panel that holds it. No
 * states, no strip.
 *
 * The three record reads are best-effort and independent, the
 * same discipline as the panels: a module that isn't effective
 * for the viewer (borrowing / claims) simply contributes no
 * entry. The loss reports ride the inventory module itself.
 */
export interface ItemStatusData {
  /** The OPEN loss/stolen report, when one exists. */
  lossReport: LossReport | null;
  /** The current loan (requested / checked out), when one exists. */
  checkout: Checkout | null;
  /** The item's claims; null = the read didn't answer (module
   *  off for the viewer, or a failure) — the strip then treats
   *  broken as claimless rather than guessing. */
  claims: ItemClaims | null;
}

const EMPTY: ItemStatusData = { lossReport: null, checkout: null, claims: null };

/** Loads the strip's three record sets for one item. Reloads
 *  when `refreshSignal` changes (the page passes its active tab
 *  + the item's updated stamp), on the standing-changed event
 *  the repairs panel fires, and whenever the page calls the
 *  returned `reload` — the lending panel's onChanged, since a
 *  checkout never touches the item row itself, so no item
 *  refetch ever signals it. */
export function useItemStatus(
  itemKind: "tool" | "battery",
  itemId: string,
  refreshSignal: string,
): { data: ItemStatusData; reload: () => void } {
  const [data, setData] = useState<ItemStatusData>(EMPTY);

  const load = useCallback(() => {
    if (!itemId) return;
    api<LossReport[]>(`/inventory/${itemKind}/${itemId}/loss-reports`)
      .then((rows) =>
        setData((d) => ({
          ...d,
          lossReport: rows.find((r) => r.status === "active") ?? null,
        })),
      )
      .catch(() => undefined);
    getItemLending(itemKind, itemId)
      .then((lending) =>
        setData((d) => ({ ...d, checkout: lending.current })),
      )
      .catch(() => undefined);
    getItemClaims(itemKind, itemId)
      .then((claims) => setData((d) => ({ ...d, claims })))
      .catch(() => undefined);
  }, [itemKind, itemId]);

  useEffect(() => {
    load();
  }, [load, refreshSignal]);

  useEffect(() => {
    window.addEventListener("tv:item-standing-changed", load);
    return () => window.removeEventListener("tv:item-standing-changed", load);
  }, [load]);

  return { data, reload: load };
}

function Entry({
  tone,
  label,
  text,
  to,
  onJump,
}: {
  tone: BadgeTone;
  label: string;
  text?: string;
  /** A real record elsewhere (a claim) — a router link. */
  to?: string;
  /** The record lives on this page, in a tab — a jump. */
  onJump?: () => void;
}) {
  const inner: ReactNode = (
    <>
      <Badge tone={tone} dot>
        {label}
      </Badge>
      {text && <span className="tv-item-status-text">{text}</span>}
    </>
  );
  if (to) {
    return (
      <Link to={to} className="tv-item-status-entry">
        {inner}
      </Link>
    );
  }
  if (onJump) {
    return (
      <button type="button" className="tv-item-status-entry" onClick={onJump}>
        {inner}
      </button>
    );
  }
  return <span className="tv-item-status-entry">{inner}</span>;
}

export function ItemStatusStrip({
  standing,
  replacedOn,
  replacedByName,
  data,
  claimsEffective,
  onJump,
  onOpenLoss,
  onOpenSale,
}: {
  standing: Standing;
  replacedOn: string | null;
  replacedByName: string | null;
  data: ItemStatusData;
  /** Tab availability, so a jump never targets a hidden tab —
   *  an entry whose home tab is switched off renders as a plain
   *  statement instead of a link. */
  claimsEffective: boolean;
  /** Kept for the pages' call shape; the strip's entries no
   *  longer target the Maintenance tab (repairs moved to claims
   *  in the 2026-11-04 merge). */
  maintenanceEffective: boolean;
  onJump: (tab: string, anchor?: string) => void;
  /** The lost/stolen report and the sale record live in their
   *  own modal windows now (owner correction, 2026-10-31), not
   *  in Details-tab panels — the page hands over the openers;
   *  without them the entries fall back to the old panel jump. */
  onOpenLoss?: () => void;
  onOpenSale?: () => void;
}) {
  const entries: ReactNode[] = [];

  if (standing === "lost" || standing === "stolen") {
    entries.push(
      <Entry
        key="loss"
        tone={STANDING_TONES[standing]}
        label={STANDING_LABELS[standing]}
        text={
          data.lossReport?.reported_date
            ? `Reported ${displayDate(data.lossReport.reported_date)} — see the report`
            : "See the report"
        }
        onJump={onOpenLoss ?? (() => onJump("details", "loss-report"))}
      />,
    );
  }

  if (standing === "broken") {
    const claim = data.claims?.current[0];
    if (claim) {
      entries.push(
        <Entry
          key="broken"
          tone="danger"
          label={STANDING_LABELS.broken}
          text={`Claim ${claim.claim_number}`}
          to={`/claims/${claim.id}`}
        />,
      );
    } else if (claimsEffective) {
      entries.push(
        <Entry
          key="broken"
          tone="danger"
          label={STANDING_LABELS.broken}
          text="Marked broken"
          onJump={() => onJump("claims")}
        />,
      );
    } else {
      entries.push(
        <Entry key="broken" tone="danger" label={STANDING_LABELS.broken} />,
      );
    }
  }

  if (standing === "in_repair") {
    // Sent out (merge, 2026-11-04): the repair IS the item's open
    // claim now — the entry links the claim itself, falling back
    // to the Claims / Replace tab when the claim read didn't
    // answer or claims is the viewer's route in.
    const claim =
      data.claims?.current.find((c) => c.status === "in_repair") ??
      data.claims?.current[0];
    if (claim) {
      entries.push(
        <Entry
          key="repair"
          tone={STANDING_TONES.in_repair}
          label={STANDING_LABELS.in_repair}
          text={`Claim ${claim.claim_number}`}
          to={`/claims/${claim.id}`}
        />,
      );
    } else if (claimsEffective) {
      entries.push(
        <Entry
          key="repair"
          tone={STANDING_TONES.in_repair}
          label={STANDING_LABELS.in_repair}
          text="See the claim"
          onJump={() => onJump("claims")}
        />,
      );
    } else {
      entries.push(
        <Entry
          key="repair"
          tone={STANDING_TONES.in_repair}
          label={STANDING_LABELS.in_repair}
        />,
      );
    }
  }

  if (standing === "sold") {
    entries.push(
      <Entry
        key="sold"
        tone={STANDING_TONES.sold}
        label={STANDING_LABELS.sold}
        text="See the sale record"
        onJump={onOpenSale ?? (() => onJump("details", "sale"))}
      />,
    );
  }

  if (standing === "replaced" || replacedOn) {
    entries.push(
      <Entry
        key="replaced"
        tone={STANDING_TONES.replaced}
        label={STANDING_LABELS.replaced}
        text={
          [
            replacedOn ? displayDate(replacedOn) : "",
            replacedByName ? `by ${replacedByName}` : "",
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
        onJump={() => onJump("audit")}
      />,
    );
  }

  if (data.checkout) {
    entries.push(
      <Entry
        key="loan"
        tone={data.checkout.overdue ? "danger" : "accent"}
        // Sweep B2-F8: one word for the state everywhere — the
        // header pill, the list pill and the Borrowing tab all say
        // "Checked out"; the strip used to say "Borrowed" for the
        // same state.
        label={data.checkout.state === "requested" ? "Requested" : "Checked out"}
        text={
          data.checkout.state === "requested"
            ? `by ${data.checkout.borrower_name}`
            : standingText(data.checkout)
        }
        onJump={() => onJump("borrowing", "lending")}
      />,
    );
  }

  if (entries.length === 0) return null;
  return (
    <div className="tv-item-status" role="region" aria-label="Item status">
      {entries}
    </div>
  );
}
