import { Navigate, useLocation, useParams } from "react-router-dom";

/**
 * The retired standalone company page's address
 * (/dealers/:companyId) lands here now (owner, 2026-11-14):
 * the dealer lives in the Dealers tab's panel, so the old
 * address translates to the panel's deep link and replaces
 * itself — /dealers?dealer=<id>, with the old page's hash
 * scheme carried across (&section=… / &agent=…) so saved
 * links and printed material keep opening the same section
 * of the same dealer they always did.
 */
const SECTION_BY_HASH: Record<string, string> = {
  "#agents": "agents",
  "#claims": "claims-open",
  "#open-claims": "claims-open",
  "#claims-history": "claims-history",
  "#history-claims": "claims-history",
  "#warranty": "warranty",
  "#flyers": "flyers",
  "#tools": "tools",
  "#truck-accounts": "truck",
  "#truck": "truck",
};

export default function DealerPageRedirect() {
  const { companyId } = useParams();
  const { hash } = useLocation();
  const params = new URLSearchParams();
  if (companyId) params.set("dealer", companyId);
  if (hash.startsWith("#agent=")) {
    params.set("agent", hash.slice("#agent=".length));
  } else if (SECTION_BY_HASH[hash]) {
    params.set("section", SECTION_BY_HASH[hash]);
  }
  const query = params.toString();
  return <Navigate to={query ? `/dealers?${query}` : "/dealers"} replace />;
}
