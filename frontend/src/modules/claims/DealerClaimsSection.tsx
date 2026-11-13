import { useEffect, useState } from "react";
import "./claims.css";
import { Link } from "react-router-dom";
import { Spinner } from "../../components";
import { SellerPrice } from "../../components/SellerPrice";
import { useT } from "../../i18n/LocaleContext";
import { listIncomingClaims } from "./api";
import { StatusBadge } from "./components";
import { fullDateTime } from "./format";
import type { IncomingClaim } from "./types";

/**
 * The agent side's warranty worklist (two-types build 2026-10-25;
 * agent scope 2026-10-31): warranty claims currently routed to
 * the signed-in user as an AGENT — a claim addressed to their
 * company but routed to a different agent (or no agent) never
 * appears here; the company itself has no seat. Self-fetching
 * like every dashboard section; renders nothing when the read
 * fails (the dealers module gate lives server-side) so the
 * dashboard stands on its own. Each row opens the claim itself —
 * the two-party page both seats drive.
 */
export function DealerClaimsSection() {
  const t = useT();
  const [claims, setClaims] = useState<IncomingClaim[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listIncomingClaims()
      .then((rows) => {
        if (!cancelled) setClaims(rows);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) return null;
  if (claims === null) {
    return (
      <p className="tv-broken-muted">
        <Spinner size="sm" /> Loading…
      </p>
    );
  }
  if (claims.length === 0) {
    return <p className="tv-broken-muted">{t("claims.incoming.empty")}</p>;
  }
  return (
    <div className="tv-ix-rows">
      {claims.map((claim) => (
        <div key={claim.id} className="tv-ix-row">
          <span className="tv-ix-row-main">
            <Link to={`/claims/${claim.id}`} className="tv-ix-link">
              {claim.claim_number}
            </Link>
            <StatusBadge status={claim.status} />
            <span className="tv-ix-facts">
              {t("claims.incoming.from")} {claim.owner_name}
              {claim.dealer_name ? ` · ${claim.dealer_name}` : ""}
              {` · ${fullDateTime(claim.created_at)}`}
            </span>
          </span>
          <strong>
            <SellerPrice amount={claim.total_amount} currency={claim.owner_currency} />
          </strong>
        </div>
      ))}
    </div>
  );
}
