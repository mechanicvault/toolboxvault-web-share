import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../../components";
import { SellerPrice } from "../../components/SellerPrice";
import { useT } from "../../i18n/LocaleContext";
import { getItemClaims } from "./api";
import { StatusBadge } from "./components";
import { fullDate } from "./format";
import type { ItemClaims, LinkedClaim } from "./types";

/**
 * The item page's corner of the dealer triangle (intermingling,
 * 2026-10-25): this item's claims — current first, then history —
 * each linking through to the claim itself.
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
      <div className="tv-ix-rows">
        {claims.map((claim) => (
          <div key={claim.id} className="tv-ix-row">
            <span className="tv-ix-row-main">
              <Link to={`/claims/${claim.id}`} className="tv-ix-link">
                {claim.claim_number}
              </Link>
              <StatusBadge status={claim.status} />
              <span className="tv-ix-facts">
                {claim.kind === "warranty_repair" ? (
                  <>
                    {t("claims.kind.warranty")}
                    {claim.dealer_name ? ` · ${claim.dealer_name}` : ""}
                    {claim.repair_sent_to
                      ? ` · ${t("claims.repair.sentTo")}: ${claim.repair_sent_to}`
                      : ""}
                    {claim.repair_cost ? (
                      <>
                        {` · ${t("claims.repair.cost")}: `}
                        <SellerPrice
                          amount={claim.repair_cost}
                          currency={claim.owner_currency}
                        />
                      </>
                    ) : (
                      ""
                    )}
                  </>
                ) : (
                  <>
                    {t(`claims.incident.${claim.incident_type}` as never)}
                    {claim.incident_date
                      ? ` · ${fullDate(claim.incident_date)}`
                      : ""}
                    {claim.insurer_name ? ` · ${claim.insurer_name}` : ""}
                  </>
                )}
              </span>
            </span>
            <strong>
              <SellerPrice amount={claim.total_amount} currency={claim.owner_currency} />
            </strong>
          </div>
        ))}
      </div>
    </div>
  );
}
