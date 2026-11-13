import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useT } from "../../../i18n/LocaleContext";
import { getPreferredSummary, listCompanies } from "../../dealers/api";
import type { PreferredSummary } from "../../dealers/types";
import "../itemPage.css";

/**
 * The Warranty tab's provider resolution (owner amendment,
 * 2026-10-31): the provider renders as a LINK to the dealer's
 * page when it resolves to one of the user's own dealers, and
 * as plain text when it's only a name (an external provider).
 *
 * Resolution is a real record match, never a guess:
 *  1. the item's own dealer linkage — the provider is prefilled
 *     from the picked dealer, so when the provider text equals
 *     the linked dealer's name, it links to that dealer;
 *  2. otherwise the user's dealer list: an exact (trimmed,
 *     case-insensitive) name match against their companies, and
 *     only when EXACTLY ONE company carries that name — an
 *     ambiguous name stays plain text.
 * The list read is best-effort: any failure leaves plain text.
 */
export function useWarrantyDealerMatch(
  provider: string,
  dealerCompanyId: string | null,
  dealerCompanyName: string | null,
): string | null {
  const [matchId, setMatchId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMatchId(null);
    const wanted = provider.trim().toLowerCase();
    if (!wanted) return;
    if (
      dealerCompanyId &&
      dealerCompanyName &&
      dealerCompanyName.trim().toLowerCase() === wanted
    ) {
      setMatchId(dealerCompanyId);
      return;
    }
    listCompanies()
      .then((companies) => {
        if (cancelled) return;
        const hits = companies.filter(
          (c) => c.name.trim().toLowerCase() === wanted,
        );
        setMatchId(hits.length === 1 ? hits[0].id : null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [provider, dealerCompanyId, dealerCompanyName]);

  return matchId;
}

export function WarrantyProviderValue({
  provider,
  dealerCompanyId,
  dealerCompanyName,
}: {
  provider: string;
  dealerCompanyId: string | null;
  dealerCompanyName: string | null;
}) {
  const matchId = useWarrantyDealerMatch(
    provider,
    dealerCompanyId,
    dealerCompanyName,
  );

  if (matchId) {
    return (
      <Link to={`/dealers/${matchId}`} className="tv-item-link">
        {provider}
      </Link>
    );
  }
  return <>{provider}</>;
}

/** The provider-gated agent line: resolves the SAME dealer
 *  match the provider link uses and renders the agent row only
 *  for a genuine match — an outside-name provider never reaches
 *  the agent read at all. */
export function WarrantyAgentForProvider({
  provider,
  dealerCompanyId,
  dealerCompanyName,
  rowClassName,
}: {
  provider: string;
  dealerCompanyId: string | null;
  dealerCompanyName: string | null;
  rowClassName: string;
}) {
  const matchId = useWarrantyDealerMatch(
    provider,
    dealerCompanyId,
    dealerCompanyName,
  );
  if (!matchId) return null;
  return <WarrantyAgentRow companyId={matchId} rowClassName={rowClassName} />;
}

/**
 * The Warranty tab's current-agent line (owner ruling
 * 2026-11-03): beside the provider, the owner's CURRENT agent
 * for that dealer, read as the preferred-agent SUMMARY
 * through the dealers module's on-record endpoint. The
 * display rule (owner, 2026-11-06): exactly ONE preferred
 * agent renders as below — the name, its dealer account line
 * for a platform agent, and one-tap call / text / email links
 * when the record carries them; MORE THAN ONE preferred
 * agent shows no specifics — the row carries only a
 * "Multiple Agents" link to the dealer's Agents tab.
 * Rendered ONLY when the caller has a genuine dealer-record
 * match (the provider's own gate) AND an agent summary
 * exists: an outside-name provider and a matched dealer with
 * no agent both show nothing extra — no empty placeholder.
 */
export function WarrantyAgentRow({
  companyId,
  rowClassName,
}: {
  companyId: string;
  /** The page's own row shape ("tv-item-row" on the tool page,
   *  "tv-item-cell" on the battery page). */
  rowClassName: string;
}) {
  const t = useT();
  const [summary, setSummary] = useState<PreferredSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSummary(null);
    getPreferredSummary(companyId)
      .then((row) => {
        if (!cancelled) setSummary(row);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (!summary || summary.state === "none") return null;
  if (summary.state === "many") {
    return (
      <div className={rowClassName}>
        <dt>Current agent</dt>
        <dd>
          <Link to={`/dealers/${companyId}#agents`} className="tv-item-link">
            {t("dealers.directory.multipleAgents")}
          </Link>
        </dd>
      </div>
    );
  }
  const agent = summary.agent;
  if (!agent) return null;
  return (
    <div className={rowClassName}>
      <dt>Current agent</dt>
      <dd>
        <strong>{agent.name}</strong>
        {agent.kind === "platform" && agent.account_number && (
          <span className="tv-item-agentmeta">
            {" "}
            · Toolbox Vault dealer · {agent.account_number}
          </span>
        )}{" "}
        {agent.phone && (
          <>
            <a href={`tel:${agent.phone}`} className="tv-item-link">
              Call
            </a>{" "}
            <a href={`sms:${agent.phone}`} className="tv-item-link">
              Text
            </a>{" "}
          </>
        )}
        {agent.email && (
          <a href={`mailto:${agent.email}`} className="tv-item-link">
            Email
          </a>
        )}
      </dd>
    </div>
  );
}
