import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useT } from "../../../i18n/LocaleContext";
import { getPreferredSummary } from "../../dealers/api";
import type { PreferredSummary } from "../../dealers/types";

/**
 * The Details tab's "Dealer Agent:" segment: the item's
 * dealer's preferred agent, read as the preferred-agent
 * SUMMARY (the dealers module's on-record endpoint) — the
 * same summary the Warranty tab's agent row reads.
 *
 * The display rule (owner, 2026-11-06): with exactly ONE
 * preferred agent the segment names him as a LINK into his
 * own record on the dealer's Agents tab (the `#agent=<kind>:<id>`
 * deep link opens the record); with MORE THAN ONE preferred
 * agent it shows NO specifics — the words "Multiple Agents"
 * as a link to the dealer's Agents tab (`#agents`). With no
 * agent at all (or a failed read) it renders nothing — the
 * segment exists only when it has somewhere real to point,
 * never as a placeholder.
 *
 * It never renders as its own row: the owner's layout puts
 * the agent ON the Dealer row, indented a little to the
 * right of the dealer name. `layout` matches the host page's
 * dialect: "inline" rides inside the tool page's Dealer
 * value cell, on the same line as the dealer name; "subline"
 * rides inside the battery page's Dealer cell, as an indented
 * line under the dealer name.
 */
export function DealerAgentLine({
  companyId,
  layout,
}: {
  companyId: string;
  layout: "inline" | "subline";
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
  const linkStyle = { color: "var(--accent)", fontWeight: 600 } as const;
  let link: ReactNode;
  if (summary.state === "many") {
    link = (
      <Link to={`/dealers/${companyId}#agents`} style={linkStyle}>
        {t("dealers.directory.multipleAgents")}
      </Link>
    );
  } else {
    const agent = summary.agent;
    if (!agent) return null;
    const ref =
      agent.kind === "private" ? agent.private_agent_id : agent.agent_user_id;
    if (!ref) return null;
    link = (
      <Link
        to={`/dealers/${companyId}#agent=${agent.kind}:${ref}`}
        style={linkStyle}
      >
        {agent.name}
      </Link>
    );
  }
  const label = t("inventory.details.dealerAgent");

  if (layout === "subline") {
    return (
      <div className="tv-dealer-agent-subline">
        <span className="tv-dealer-agent-label">{label}</span> {link}
      </div>
    );
  }
  return (
    <span className="tv-dealer-agent-inline">
      <span className="tv-dealer-agent-label">{label}</span> {link}
    </span>
  );
}
