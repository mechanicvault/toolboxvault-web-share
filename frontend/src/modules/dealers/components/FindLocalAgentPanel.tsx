import { useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  DataTable,
  EmptyState,
  FormField,
  Panel,
  Select,
  TextInput,
  useToast,
  type Column,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import "../dealers.css";
import { connectLocalAgent, findLocalAgents } from "../api";
import type { FindLocalAgentCard, FindLocalAgentResult } from "../types";

const RADIUS_PRESETS = [10, 25, 50, 100, 250];

/**
 * Find local Agent (stage 3, 2026-11-05 — the owner's reusable
 * search, 2026-11-04): ZIP + radius over registered agents'
 * service territories, results a true list — one agent per row,
 * facts in columns, nearest first. Mount it unscoped (the Find
 * an Agent page) or scoped to one dealer (companyId — that
 * dealer's Agents tab), where results narrow to agents with a
 * verified representation of the company and the one company
 * line carries the connect.
 *
 * Connect creates the stage-1 roster connection for that
 * (user, company, agent): flagged preferred when it is the
 * user's first agent for the company, a plain connection
 * otherwise, idempotent on repeat.
 */
export default function FindLocalAgentPanel({
  companyId,
  companyName,
  onConnected,
}: {
  companyId?: string;
  companyName?: string;
  onConnected?: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [zip, setZip] = useState("");
  const [preset, setPreset] = useState("25");
  const [custom, setCustom] = useState("");
  const [result, setResult] = useState<FindLocalAgentResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [connecting, setConnecting] = useState("");

  const radius = preset === "custom" ? Number(custom) : Number(preset);
  const canSearch =
    /^\d{5}(-\d{4})?$/.test(zip.trim()) &&
    Number.isFinite(radius) &&
    radius >= 1 &&
    radius <= 500;

  async function search(e: FormEvent) {
    e.preventDefault();
    if (!canSearch) return;
    setError("");
    setSearching(true);
    try {
      setResult(await findLocalAgents(zip.trim(), radius, companyId));
    } catch (err) {
      setResult(null);
      setError(
        err instanceof ApiError
          ? err.message
          : t("dealers.findLocal.loadError"),
      );
    } finally {
      setSearching(false);
    }
  }

  async function connect(card: FindLocalAgentCard, targetCompanyId: string) {
    const key = `${card.agent_user_id}:${targetCompanyId}`;
    setConnecting(key);
    try {
      const res = await connectLocalAgent({
        company_id: targetCompanyId,
        agent_user_id: card.agent_user_id,
      });
      const company = card.companies.find(
        (c) => c.company_id === targetCompanyId,
      );
      setResult((prev) =>
        prev
          ? {
              ...prev,
              results: prev.results.map((c) =>
                c.agent_user_id !== card.agent_user_id
                  ? c
                  : {
                      ...c,
                      companies: c.companies.map((co) =>
                        co.company_id === targetCompanyId
                          ? {
                              ...co,
                              connected: true,
                              is_preferred: res.preferred.is_preferred,
                            }
                          : co,
                      ),
                    },
              ),
            }
          : prev,
      );
      toast(
        (res.created
          ? t("dealers.findLocal.connectedToast")
          : t("dealers.findLocal.alreadyToast")
        )
          .replace("{name}", card.display_name)
          .replace("{company}", company?.company_name ?? ""),
        { tone: "success" },
      );
      onConnected?.();
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("dealers.findLocal.connectError"),
        { tone: "danger" },
      );
    } finally {
      setConnecting("");
    }
  }

  const shownCompanies = (card: FindLocalAgentCard) =>
    companyId
      ? card.companies.filter((c) => c.company_id === companyId)
      : card.companies;

  const columns: Column<FindLocalAgentCard>[] = [
    {
      key: "agent",
      header: t("dealers.roster.col.name"),
      render: (card) => (
        <span className="tv-find-local-agent">
          {card.photo_url && (
            <img
              className="tv-find-local-photo"
              src={card.photo_url}
              alt=""
            />
          )}
          <span>
            <span className="tv-find-local-name">{card.display_name}</span>{" "}
            <Badge tone="success">{t("dealers.findLocal.verified")}</Badge>
          </span>
        </span>
      ),
    },
    {
      key: "companies",
      header: t("dealers.findLocal.col.companies"),
      render: (card) => (
        <span className="tv-find-local-companies">
          {shownCompanies(card).map((company) => {
            const key = `${card.agent_user_id}:${company.company_id}`;
            return (
              <span key={company.company_id} className="tv-find-local-company">
                <span>{company.company_name}</span>
                {company.connected ? (
                  <span className="tv-find-local-state">
                    <Badge tone="neutral">
                      {t("dealers.findLocal.connected")}
                    </Badge>
                    {company.is_preferred && (
                      <Badge tone="accent">
                        {t("dealers.roster.preferred")}
                      </Badge>
                    )}
                  </span>
                ) : (
                  <Button
                    size="sm"
                    loading={connecting === key}
                    onClick={() => void connect(card, company.company_id)}
                  >
                    {t("dealers.findLocal.connect")}
                  </Button>
                )}
              </span>
            );
          })}
        </span>
      ),
    },
    {
      key: "area",
      header: t("dealers.roster.col.area"),
      render: (card) => card.service_area || "—",
    },
    {
      key: "distance",
      header: t("dealers.findLocal.col.distance"),
      render: (card) =>
        card.covers_zip ? (
          <Badge tone="success">{t("dealers.findLocal.coversZip")}</Badge>
        ) : (
          t("dealers.findLocal.away").replace(
            "{miles}",
            String(card.distance_miles),
          )
        ),
    },
    {
      key: "contact",
      header: t("dealers.roster.col.contact"),
      render: (card) => (
        <span className="tv-find-local-contact">
          {card.phone && <a href={`tel:${card.phone}`}>{card.phone}</a>}
          {card.contact_email && (
            <a href={`mailto:${card.contact_email}`}>{card.contact_email}</a>
          )}
          {!card.phone && !card.contact_email && "—"}
        </span>
      ),
    },
  ];

  const intro = companyId
    ? t("dealers.findLocal.scopedIntro")
        .replace("{company}", companyName ?? "")
        .replace("{company}", companyName ?? "")
    : t("dealers.findLocal.intro");

  return (
    <Panel title={t("dealers.findLocal.title")}>
      <form onSubmit={(e) => void search(e)}>
        <p className="tv-find-local-intro">{intro}</p>
        <div className="tv-find-local-form">
          <div className="tv-find-local-field-zip">
            <FormField label={t("dealers.findLocal.zipLabel")}>
              <TextInput
                value={zip}
                onChange={(e) => setZip(e.target.value)}
                placeholder="56345"
                maxLength={10}
              />
            </FormField>
          </div>
          <div className="tv-find-local-field-radius">
            <FormField label={t("dealers.findLocal.radiusLabel")}>
              <Select
                value={preset}
                onChange={(e) => setPreset(e.target.value)}
              >
                {RADIUS_PRESETS.map((miles) => (
                  <option key={miles} value={String(miles)}>
                    {t("dealers.findLocal.miles").replace(
                      "{count}",
                      String(miles),
                    )}
                  </option>
                ))}
                <option value="custom">
                  {t("dealers.findLocal.radiusCustom")}
                </option>
              </Select>
            </FormField>
          </div>
          {preset === "custom" && (
            <div className="tv-find-local-field-custom">
              <FormField label={t("dealers.findLocal.customMiles")}>
                <TextInput
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  placeholder="75"
                  maxLength={3}
                />
              </FormField>
            </div>
          )}
          <Button type="submit" loading={searching} disabled={!canSearch}>
            {t("dealers.findLocal.search")}
          </Button>
        </div>
      </form>
      {error && (
        <div className="tv-find-local-error">
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {result && (
        <div className="tv-find-local-results">
          {result.results.length === 0 ? (
            <EmptyState
              title={t("dealers.findLocal.emptyTitle")
                .replace("{radius}", String(result.radius_miles))
                .replace("{zip}", result.zip)}
              description={t("dealers.findLocal.emptyHint")}
            />
          ) : (
            <>
              <p className="tv-find-local-summary">
                {t("dealers.findLocal.resultsFor")
                  .replace("{radius}", String(result.radius_miles))
                  .replace("{place}", result.point.display_name)}
              </p>
              <DataTable
                columns={columns}
                rows={result.results}
                rowKey={(card) => card.agent_user_id}
              />
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
