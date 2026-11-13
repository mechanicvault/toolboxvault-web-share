import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Panel, TextInput } from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { enterAgentCode, getTakeoverMine } from "./api";
import type { TakeoverEnterResult, TakeoverMine } from "./types";

/**
 * "Claim a customer's agent record" (agent takeover,
 * 2026-11-03) — the agent side of the agent code. A customer
 * hands their agent the code on their private agent record;
 * the agent enters it here and ASKS to take the record over.
 * Nothing links until the customer accepts; on accept the
 * agent steps into the record — its claims and truck account
 * become theirs to work, in that customer's context only. The
 * card also carries the agent's own asks and the records they
 * already work, so the state of every handover is visible.
 */
export function ClaimCodeCard() {
  const t = useT();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<TakeoverEnterResult | null>(null);
  const [mine, setMine] = useState<TakeoverMine | null>(null);

  const loadMine = useCallback(async () => {
    try {
      setMine(await getTakeoverMine());
    } catch {
      setMine(null);
    }
  }, []);

  useEffect(() => {
    void loadMine();
  }, [loadMine]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    if (!code.trim()) return;
    setBusy(true);
    try {
      const outcome = await enterAgentCode(code.trim());
      setResult(outcome);
      setCode("");
      await loadMine();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.claimCode.error"),
      );
    } finally {
      setBusy(false);
    }
  }

  const statusTone = (status: string): "success" | "neutral" | "danger" | "accent" =>
    status === "accepted"
      ? "success"
      : status === "pending"
        ? "accent"
        : status === "declined"
          ? "danger"
          : "neutral";
  const statusLabel = (status: string) =>
    status === "accepted"
      ? t("dealers.claimCode.statusAccepted")
      : status === "pending"
        ? t("dealers.claimCode.statusPending")
        : status === "declined"
          ? t("dealers.claimCode.statusDeclined")
          : t("dealers.claimCode.statusSuperseded");

  return (
    <section>
      <Panel title={t("dealers.claimCode.title")}>
        <p className="tv-agent-notes">{t("dealers.claimCode.intro")}</p>
        <ol className="tv-agent-steps">
          <li>{t("dealers.claimCode.step1")}</li>
          <li>{t("dealers.claimCode.step2")}</li>
          <li>{t("dealers.claimCode.step3")}</li>
        </ol>
        {error && <Alert tone="danger">{error}</Alert>}
        {result?.status === "pending" && (
          <Alert tone="success">
            {t("dealers.claimCode.pendingResult")
              .replace("{agent}", result.agent_name)
              .replace("{company}", result.company_name || "—")}
          </Alert>
        )}
        {result?.status === "already_claimed" && (
          <Alert tone="info">{t("dealers.claimCode.alreadyClaimed")}</Alert>
        )}
        {result?.status === "own_record" && (
          <Alert tone="info">{t("dealers.claimCode.ownRecord")}</Alert>
        )}
        <form onSubmit={(e) => void submit(e)} className="tv-claimcode-form">
          <span className="tv-claimcode-input">
            <TextInput
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={t("dealers.claimCode.placeholder").replace(
                "{example}",
                "K7QX-3MZD",
              )}
              aria-label={t("dealers.claimCode.title")}
              autoComplete="off"
            />
          </span>
          <Button type="submit" loading={busy} disabled={!code.trim()}>
            {busy ? t("dealers.claimCode.sending") : t("dealers.claimCode.button")}
          </Button>
        </form>

        {mine && mine.claimed.length > 0 && (
          <div className="tv-agents-list">
            <h4>{t("dealers.claimCode.myClaimed")}</h4>
            {mine.claimed.map((row) => (
              <div key={row.private_agent_id} className="tv-agent-req">
                <p>
                  {t("dealers.claimCode.claimedLine")
                    .replace("{agent}", row.agent_name)
                    .replace("{owner}", row.owner_name)
                    .replace("{company}", row.company_name || "—")}
                </p>
                {row.company_id && (
                  <Link
                    to={`/dealers/${row.company_id}#agents`}
                    className="tv-agent-meta"
                  >
                    {t("dealers.claimCode.viewCompany")}
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}

        {mine && mine.requests.length > 0 && (
          <div className="tv-agents-list">
            <h4>{t("dealers.claimCode.myRequests")}</h4>
            {mine.requests.map((req) => (
              <div key={req.id} className="tv-agent-req">
                <p>
                  {t("dealers.claimCode.claimedLine")
                    .replace("{agent}", req.agent_name)
                    .replace("{owner}", req.owner_name)
                    .replace("{company}", req.company_name || "—")}
                </p>
                <Badge tone={statusTone(req.status)}>{statusLabel(req.status)}</Badge>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </section>
  );
}
