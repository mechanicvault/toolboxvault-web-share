import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { getItemClaims } from "./api";
import { StatusBadge } from "./components";
import { fullDate } from "./format";
import type { ItemClaims, LinkedClaim } from "./types";
import "./claims.css";

/**
 * The item page's corner of the dealer triangle (intermingling,
 * 2026-10-25): this item's claims — current first, then history.
 *
 * The list itself follows the owner's sheet row (2026-11-16):
 * a claim is listed FROM THE ITEM'S NAME, not the claim
 * number, in a true list — CLAIM ITEM NAME · DEALER · AGENT ·
 * DATE CLAIMED · DATE REPAIRED · CURRENT STATUS, the status
 * pill in its own column — and everything else (amounts, where
 * it was sent, the repair cost) lives within the claim itself,
 * which the whole row opens. This supersedes the 2026-11-04
 * rows that led with the claim number and carried the repair
 * facts inline.
 *
 * Best-effort by design, like the lending panel beside it: if
 * the claims module isn't effective for this user (403
 * module_unavailable) — or the read fails — the panel renders
 * nothing and the item page stands on its own. An item with no
 * claims renders nothing either: the panel exists to surface
 * records that exist, not to announce their absence on every
 * item in the vault.
 */
export function ItemClaimsPanel({
  itemKind,
  itemId,
}: {
  itemKind: "tool" | "battery";
  itemId: string;
}) {
  const t = useT();
  const [data, setData] = useState<ItemClaims | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getItemClaims(itemKind, itemId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setHidden(true);
      });
    return () => {
      cancelled = true;
    };
  }, [itemKind, itemId]);

  if (hidden || data === null) return null;
  if (data.current.length === 0 && data.history.length === 0) return null;

  return (
    <Panel title={t("claims.title")}>
      <div className="tv-ix-groups">
        {data.current.length > 0 && (
          <ClaimGroup
            heading={t("claims.itemPanel.current")}
            claims={data.current}
          />
        )}
        {data.history.length > 0 && (
          <ClaimGroup
            heading={t("claims.itemPanel.history")}
            claims={data.history}
          />
        )}
      </div>
    </Panel>
  );
}

function ClaimGroup({
  heading,
  claims,
}: {
  heading: string;
  claims: LinkedClaim[];
}) {
  const t = useT();
  return (
    <div className="tv-ix-group">
      <p className="tv-ix-heading">{heading}</p>
      <div className="tv-claim-table" role="table">
        <div className="tv-claim-thead" role="row">
          <span role="columnheader">{t("claims.itemPanel.colItem")}</span>
          <span role="columnheader">{t("claims.col.parties")}</span>
          <span role="columnheader">{t("claims.warranty.agent")}</span>
          <span role="columnheader">{t("claims.split.dateClaimed")}</span>
          <span role="columnheader">{t("claims.split.dateRepaired")}</span>
          <span role="columnheader">{t("claims.itemPanel.colStatus")}</span>
        </div>
        {claims.map((claim) => (
          <ClaimRow key={claim.id} claim={claim} />
        ))}
      </div>
    </div>
  );
}

function ClaimRow({ claim }: { claim: LinkedClaim }) {
  const t = useT();
  const claimed = claim.reported_at ?? claim.created_at;
  const repaired = claim.repair_completed_at ?? claim.closed_at;
  const [firstItem, ...moreItems] = claim.items;
  return (
    <Link
      to={`/claims/${claim.id}`}
      className="tv-claim-row"
      role="row"
      aria-label={firstItem ?? claim.claim_number}
    >
      <span className="tv-claim-cell-item">
        {firstItem ?? claim.claim_number}
        {moreItems.length > 0 && (
          <span className="tv-claim-cell-more">
            {" "}
            {t("claims.split.plusMore").replace(
              "{count}",
              String(moreItems.length),
            )}
          </span>
        )}
      </span>
      <span>{claim.dealer_name || "—"}</span>
      <span>{claim.warranty_agent_name || "—"}</span>
      <span>{fullDate(claimed.slice(0, 10))}</span>
      <span>{repaired ? fullDate(repaired.slice(0, 10)) : "—"}</span>
      <span>
        <StatusBadge status={claim.status} />
      </span>
    </Link>
  );
}
