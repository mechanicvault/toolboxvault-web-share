import { useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  CopyButton,
  EmptyState,
  FormField,
  Panel,
  SectionHeader,
  Select,
  TextInput,
  useToast,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { addPreferredByAgent, findAgents, findAgentsPublic } from "../api";
import type { DealerCompany, FindAgentCard, FindAgentResult } from "../types";

/**
 * Find an Agent (dealer build, 2026-10-20): enter a ZIP, city, or
 * address and see EVERY publicly listed agent whose territory
 * covers it — overlaps are normal here, nobody is hidden, and the
 * order is verified reps first, then name. One tap adds an
 * agent for any of their companies (starred preferred when the
 * viewer has none for that company yet — multi-preferred,
 * 2026-11-05).
 */
export default function FindAgentPanel({
  directory,
  onPreferredChanged,
  publicMode = false,
}: {
  directory: DealerCompany[];
  onPreferredChanged: () => void;
  /** Anonymous posture: read-only — no contact actions and no
   *  preferred adds (both need an account). */
  publicMode?: boolean;
}) {
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [result, setResult] = useState<FindAgentResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState("");

  async function search(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setError("");
    setSearching(true);
    try {
      const search = publicMode ? findAgentsPublic : findAgents;
      setResult(await search(query.trim(), companyId || undefined));
    } catch (err) {
      setResult(null);
      setError(
        err instanceof ApiError ? err.message : "That search didn't go through.",
      );
    } finally {
      setSearching(false);
    }
  }

  async function addPreferred(card: FindAgentCard, companyIdToAdd: string) {
    const key = `${card.agent_user_id}:${companyIdToAdd}`;
    setAdding(key);
    try {
      const res = await addPreferredByAgent({
        company_id: companyIdToAdd,
        agent_user_id: card.agent_user_id,
      });
      setAdded((prev) => new Set(prev).add(key));
      toast(
        !res.created
          ? `${card.display_name} is already one of your agents.`
          : res.preferred.is_preferred
            ? `${card.display_name} is now one of your preferred agents.`
            : `${card.display_name} is now one of your agents.`,
        { tone: "success" },
      );
      onPreferredChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't add that agent.",
        { tone: "danger" },
      );
    } finally {
      setAdding("");
    }
  }

  return (
    <section>
      <SectionHeader title="Find an agent" />
      <Panel className="tv-agent-panel">
        <form
          onSubmit={(e) => void search(e)}
          style={{ display: "grid", gap: "var(--space-3)" }}
        >
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            Moving, traveling, or just new in town? Enter where you
            are and see every dealer agent whose service territory
            covers it. More than one name is normal — territories
            overlap — so pick the person you like.
          </p>
          <div
            style={{
              display: "flex",
              gap: "0.5rem",
              alignItems: "end",
              flexWrap: "wrap",
            }}
          >
            {/* Flex-sized fields (supervisory polish 2026-10-23):
                unsized, both fields shrank to ~211px and the ZIP
                placeholder truncated mid-word ("Little Falls, M"). */}
            <div style={{ flex: "1 1 340px", minWidth: 0 }}>
              <FormField label="ZIP, city, or address">
                <TextInput
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. 56345 or Little Falls, MN"
                />
              </FormField>
            </div>
            <div style={{ flex: "1 1 230px", minWidth: 0 }}>
              <FormField label="Company (optional)">
                <Select
                  value={companyId}
                  onChange={(e) => setCompanyId(e.target.value)}
                >
                  <option value="">Any company</option>
                  {directory.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
            <Button type="submit" loading={searching} disabled={!query.trim()}>
              Search
            </Button>
          </div>
        </form>
        {error && (
          <div style={{ marginTop: "var(--space-3)" }}>
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        {result && (
          <div style={{ marginTop: "var(--space-4)" }}>
            <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
              Agents covering <strong>{result.point.display_name}</strong>:
            </p>
            {result.results.length === 0 ? (
              <EmptyState title="No listed agents cover that area yet" />
            ) : (
              <>
                <div style={{ display: "grid", gap: "var(--spacing)" }}>
                  {result.results.map((card) => (
                    <AgentResultCard
                      key={card.agent_user_id}
                      card={card}
                      added={added}
                      adding={adding}
                      onAdd={(cid) => void addPreferred(card, cid)}
                      publicMode={publicMode}
                    />
                  ))}
                </div>
                {publicMode && (
                  <p style={{ color: "var(--text-muted)" }}>
                    Sign in to contact an agent or save them as one
                    of your agents for their company.
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </Panel>
    </section>
  );
}

function AgentResultCard({
  card,
  added,
  adding,
  onAdd,
  publicMode = false,
}: {
  card: FindAgentCard;
  added: Set<string>;
  adding: string;
  onAdd: (companyId: string) => void;
  publicMode?: boolean;
}) {
  return (
    <div
      className="tv-agent-card"
      style={{
        display: "flex",
        gap: "1rem",
        flexWrap: "wrap",
      }}
    >
      {card.photo_url && (
        <img
          className="tv-agent-photo"
          src={card.photo_url}
          alt={card.display_name}
        />
      )}
      <div style={{ flex: "1 1 260px", minWidth: 0 }}>
        <p style={{ margin: 0, fontWeight: 600 }}>
          {card.display_name}{" "}
          {card.verified && <Badge tone="success">Verified rep</Badge>}{" "}
          <Badge tone="neutral">
            {card.area_type === "polygon" ? "Drawn territory" : "ZIP + radius"}
          </Badge>
        </p>
        {card.service_area && (
          <p style={{ color: "var(--text-muted)", margin: "0.25rem 0 0" }}>
            Covers: {card.service_area}
          </p>
        )}
        <div style={{ display: "grid", gap: "0.35rem", marginTop: "0.5rem" }}>
          {card.companies.map((company) => {
            const key = `${card.agent_user_id}:${company.company_id}`;
            const isAdded = added.has(key);
            return (
              <div
                key={company.company_id}
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <span>
                  {company.company_name}{" "}
                  {company.verified && <Badge tone="success">Verified</Badge>}
                </span>
                {!publicMode && (
                  <Button
                    size="sm"
                    variant={isAdded ? "secondary" : "primary"}
                    disabled={isAdded}
                    loading={adding === key}
                    onClick={() => onAdd(company.company_id)}
                  >
                    {isAdded ? "Your agent ✓" : "Add as my agent"}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {(card.phone || card.contact_email) && (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "start" }}>
          {card.phone && (
            <>
              <a
                href={`tel:${card.phone}`}
                style={{ color: "var(--accent)", fontWeight: 600 }}
              >
                {card.phone}
              </a>
              <CopyButton text={card.phone} ariaLabel="Copy phone number" />
            </>
          )}
          {card.contact_email && (
            <a
              href={`mailto:${card.contact_email}`}
              style={{ color: "var(--accent)", fontWeight: 600 }}
            >
              {card.contact_email}
            </a>
          )}
        </div>
      )}
    </div>
  );
}
