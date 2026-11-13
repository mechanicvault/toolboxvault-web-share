import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  DatePicker,
  FormField,
  HrefButton,
  LinkButton,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { ApiError, downloadBlob } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { displayDate, money } from "../inventory/format";
import { StatusBadge } from "../claims/components";
import type { ClaimStatus } from "../claims/types";
import {
  acceptTakeoverRequest,
  declineTakeoverRequest,
  deletePrivateAgent,
  exportAgentCardFile,
  getRosterAgent,
  listTakeoverRequests,
  removePreferred,
  updatePrivateAgent,
} from "./api";
import type {
  RosterAgentDetail,
  RosterEntry,
  TakeoverRequest,
} from "./types";
import { routeText } from "./rosterFormat";

/**
 * One agent's full record, opened from the roster (stage 1,
 * 2026-11-04): contact actions, route schedule with the
 * computed next visit, tenure, the claims seated with him
 * (open + history, each linking to the claim), the truck
 * account slot Stage 2 fills in, and — for the viewer's own
 * records — in-place editing, the agent-code handover guidance
 * with its takeover requests, and deletion under the stage-1
 * rules (a linked record refuses, with the reason shown).
 */
export function AgentRecord({
  companyId,
  entry,
  onBack,
  onChanged,
  onTogglePreferred,
  onGone,
}: {
  companyId: string;
  entry: RosterEntry;
  onBack: () => void;
  onChanged: () => void;
  onTogglePreferred: (entry: RosterEntry) => void;
  onGone: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [detail, setDetail] = useState<RosterAgentDetail | null>(null);
  const [error, setError] = useState("");
  const [requests, setRequests] = useState<TakeoverRequest[]>([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: "",
    phone: "",
    email: "",
    location: "",
    notes: "",
    route_frequency: "",
    route_day_of_week: "",
    route_anchor_date: "",
    started_at: "",
    ended_at: "",
  });
  const [saving, setSaving] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [answering, setAnswering] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const refId =
    entry.kind === "private" ? entry.private_agent_id : entry.agent_user_id;

  const load = useCallback(async () => {
    if (!refId) return;
    const data = await getRosterAgent(companyId, entry.kind, refId);
    setDetail(data);
    const record = data.record;
    if (
      record &&
      record.link_source !== "takeover" &&
      !record.linked_account_number
    ) {
      try {
        setRequests(await listTakeoverRequests(record.id));
      } catch {
        setRequests([]);
      }
    } else {
      setRequests([]);
    }
  }, [companyId, entry.kind, refId]);

  useEffect(() => {
    load().catch((err) => {
      setError(
        err instanceof ApiError ? err.message : t("dealers.roster.loadError"),
      );
    });
  }, [load, t]);

  const [exportingCard, setExportingCard] = useState(false);

  async function exportCard() {
    if (!refId) return;
    setExportingCard(true);
    try {
      const blob = await exportAgentCardFile(companyId, entry.kind, refId);
      const slug =
        entry.name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "") || "agent";
      downloadBlob(blob, `${slug}.vcf`);
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("dealers.record.exportCardError"),
        { tone: "danger" },
      );
    } finally {
      setExportingCard(false);
    }
  }

  async function copyText(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 2000);
    } catch {
      toast("Copy didn't work here — select the text and copy it by hand.", {
        tone: "danger",
      });
    }
  }

  function startEditing() {
    const record = detail?.record;
    if (!record) return;
    setForm({
      name: record.name,
      phone: record.phone,
      email: record.email,
      location: record.location,
      notes: record.notes,
      route_frequency: record.route_frequency ?? "",
      route_day_of_week:
        record.route_day_of_week === null
          ? ""
          : String(record.route_day_of_week),
      route_anchor_date: record.route_anchor_date ?? "",
      started_at: record.started_at ?? "",
      ended_at: record.ended_at ?? "",
    });
    setEditing(true);
  }

  async function saveRecord(e: FormEvent) {
    e.preventDefault();
    const record = detail?.record;
    if (!record) return;
    if (!form.name.trim()) {
      setError(t("dealers.myAgents.saveError"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await updatePrivateAgent(record.id, {
        company_id: record.company_id,
        name: form.name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        notes: form.notes.trim(),
        location: form.location.trim(),
        route_frequency:
          form.route_frequency === ""
            ? null
            : (form.route_frequency as "weekly" | "biweekly" | "monthly"),
        route_day_of_week:
          form.route_day_of_week === "" ? null : Number(form.route_day_of_week),
        route_anchor_date: form.route_anchor_date || null,
        started_at: form.started_at || null,
        ended_at: form.ended_at || null,
      });
      setEditing(false);
      await load();
      onChanged();
      toast(t("dealers.record.saved"), { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.saveError"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function answer(requestId: string, accept: boolean) {
    setAnswering(requestId);
    try {
      if (accept) {
        await acceptTakeoverRequest(requestId);
        toast(t("dealers.myAgents.accepted"), { tone: "success" });
      } else {
        await declineTakeoverRequest(requestId);
        toast(t("dealers.myAgents.declined"), { tone: "success" });
      }
      await load();
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.myAgents.answerError"),
        { tone: "danger" },
      );
    } finally {
      setAnswering(null);
    }
  }

  async function doDelete() {
    const record = detail?.record;
    if (!record) return;
    setDeleting(true);
    try {
      await deletePrivateAgent(record.id);
      toast(t("dealers.record.deleted"), { tone: "success" });
      onGone();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.roster.loadError"),
        { tone: "danger" },
      );
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  async function doDisconnect() {
    if (!detail?.entry.connection_id) return;
    setDisconnecting(true);
    try {
      await removePreferred(detail.entry.connection_id);
      toast(
        t("dealers.record.disconnected").replace("{name}", detail.entry.name),
        { tone: "success" },
      );
      onGone();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.roster.loadError"),
        { tone: "danger" },
      );
      setDisconnecting(false);
    }
  }

  const shown = detail?.entry ?? entry;
  const record = detail?.record ?? null;
  const claimed = record?.link_source === "takeover";
  const message = record
    ? t("dealers.myAgents.message")
        .replace("{agent}", record.name)
        .replace("{code}", record.agent_code_display)
    : "";

  return (
    <Panel
      title={shown.name}
      actions={
        <>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onTogglePreferred(shown)}
          >
            {t(
              shown.is_preferred
                ? "dealers.roster.removePreferred"
                : "dealers.roster.makePreferred",
            )}
          </Button>
          {record && !editing && (
            <Button size="sm" variant="secondary" onClick={startEditing}>
              {t("dealers.record.edit")}
            </Button>
          )}
          {!editing && (
            <Button
              size="sm"
              variant="secondary"
              loading={exportingCard}
              onClick={() => void exportCard()}
            >
              {t("dealers.record.exportCard")}
            </Button>
          )}
        </>
      }
    >
      <div className="tv-form-actions">
        <Button size="sm" variant="secondary" onClick={onBack}>
          {t("dealers.record.back")}
        </Button>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {detail === null && !error ? (
        <p className="tv-agent-meta">
          <Spinner size="sm" /> Loading…
        </p>
      ) : detail ? (
        <div className="tv-agents-list">
          <p className="tv-agent-name">
            {shown.is_preferred && (
              <Badge tone="accent">{t("dealers.roster.preferred")}</Badge>
            )}{" "}
            {shown.kind === "platform" ? (
              <Badge tone="neutral">{t("dealers.roster.kindPlatform")}</Badge>
            ) : claimed && record ? (
              <Badge tone="success">
                {t("dealers.myAgents.claimedBy")
                  .replace("{name}", record.claimed_by_name ?? "")
                  .replace("{number}", record.claimed_by_account_number ?? "")}
              </Badge>
            ) : (
              <Badge tone="neutral">{t("dealers.myAgents.onlyYours")}</Badge>
            )}
            {shown.account_number && (
              <span className="tv-agent-meta"> · {shown.account_number}</span>
            )}
          </p>

          {(shown.phone || shown.email) && (
            <p className="tv-record-contact">
              {shown.phone && (
                <>
                  <HrefButton href={`tel:${shown.phone}`} size="sm" variant="secondary">
                    {t("dealers.roster.call")}
                  </HrefButton>
                  <HrefButton href={`sms:${shown.phone}`} size="sm" variant="secondary">
                    {t("dealers.roster.text")}
                  </HrefButton>
                </>
              )}
              {shown.email && (
                <HrefButton
                  href={`mailto:${shown.email}`}
                  size="sm"
                  variant="secondary"
                >
                  {t("dealers.roster.email")}
                </HrefButton>
              )}
            </p>
          )}

          {editing && record ? (
            <form onSubmit={(e) => void saveRecord(e)} className="tv-agents-list">
              <FormField label={t("dealers.myAgents.nameLabel")} htmlFor="rec-name" required>
                <TextInput
                  id="rec-name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.myAgents.phoneLabel")} htmlFor="rec-phone">
                <TextInput
                  id="rec-phone"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.myAgents.emailLabel")} htmlFor="rec-email">
                <TextInput
                  id="rec-email"
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.roster.locationLabel")} htmlFor="rec-location">
                <TextInput
                  id="rec-location"
                  value={form.location}
                  onChange={(e) => setForm({ ...form, location: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.roster.routeLabel")} htmlFor="rec-freq">
                <Select
                  id="rec-freq"
                  value={form.route_frequency}
                  onChange={(e) =>
                    setForm({ ...form, route_frequency: e.target.value })
                  }
                >
                  <option value="">{t("dealers.roster.freq.na")}</option>
                  <option value="weekly">{t("dealers.roster.freq.weekly")}</option>
                  <option value="biweekly">
                    {t("dealers.roster.freq.biweekly")}
                  </option>
                  <option value="monthly">{t("dealers.roster.freq.monthly")}</option>
                </Select>
              </FormField>
              {form.route_frequency !== "" && (
                <>
                  <FormField label={t("dealers.roster.routeDayLabel")} htmlFor="rec-day">
                    <Select
                      id="rec-day"
                      value={form.route_day_of_week}
                      onChange={(e) =>
                        setForm({ ...form, route_day_of_week: e.target.value })
                      }
                    >
                      <option value="">—</option>
                      {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                        <option key={d} value={d}>
                          {t(`dealers.roster.day.${d}` as never)}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                  <FormField label={t("dealers.roster.anchorLabel")} htmlFor="rec-anchor">
                    <DatePicker
                      id="rec-anchor"
                      value={form.route_anchor_date}
                      onChange={(v) =>
                        setForm({ ...form, route_anchor_date: v })
                      }
                      clearable
                    />
                  </FormField>
                </>
              )}
              <FormField label={t("dealers.roster.startedLabel")} htmlFor="rec-started">
                <DatePicker
                  id="rec-started"
                  value={form.started_at}
                  onChange={(v) => setForm({ ...form, started_at: v })}
                  clearable
                />
              </FormField>
              <FormField label={t("dealers.roster.endedLabel")} htmlFor="rec-ended">
                <DatePicker
                  id="rec-ended"
                  value={form.ended_at}
                  onChange={(v) => setForm({ ...form, ended_at: v })}
                  clearable
                />
              </FormField>
              <FormField label={t("dealers.myAgents.notesLabel")} htmlFor="rec-notes">
                <TextArea
                  id="rec-notes"
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  rows={2}
                />
              </FormField>
              <div className="tv-form-actions">
                <Button type="submit" loading={saving}>
                  {t("dealers.record.saveChanges")}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setEditing(false)}
                >
                  {t("common.cancel")}
                </Button>
              </div>
            </form>
          ) : (
            <>
              <dl className="tv-record-facts">
                <div>
                  <dt>{t("dealers.roster.locationLabel")}</dt>
                  <dd>{shown.location || "—"}</dd>
                </div>
                <div>
                  <dt>{t("dealers.record.routeTitle")}</dt>
                  <dd>
                    {routeText(t, shown)}
                    {shown.next_visit && (
                      <>
                        {" · "}
                        {t("dealers.roster.nextVisit").replace(
                          "{date}",
                          displayDate(shown.next_visit),
                        )}
                      </>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{t("dealers.roster.startedLabel")}</dt>
                  <dd>{displayDate(shown.started_at)}</dd>
                </div>
                <div>
                  <dt>{t("dealers.roster.endedLabel")}</dt>
                  <dd>{displayDate(shown.ended_at)}</dd>
                </div>
                {shown.phone && (
                  <div>
                    <dt>{t("dealers.myAgents.phoneLabel")}</dt>
                    <dd>{shown.phone}</dd>
                  </div>
                )}
                {shown.email && (
                  <div>
                    <dt>{t("dealers.myAgents.emailLabel")}</dt>
                    <dd>{shown.email}</dd>
                  </div>
                )}
              </dl>
              {detail.notes && <p className="tv-agent-notes">{detail.notes}</p>}
              {shown.kind === "platform" && (
                <p className="tv-agent-notes">{t("dealers.record.platformNote")}</p>
              )}
            </>
          )}

          {record &&
            (claimed ? (
              <div className="tv-agent-codebox">
                <p className="tv-agent-message">{t("dealers.myAgents.claimedNote")}</p>
              </div>
            ) : (
              <div className="tv-agent-codebox">
                <h4>{t("dealers.myAgents.codeTitle")}</h4>
                <div className="tv-agent-coderow">
                  <span className="tv-agent-meta">{t("dealers.myAgents.codeLabel")}</span>
                  <span className="tv-agent-code">{record.agent_code_display}</span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void copyText("code", record.agent_code_display)}
                  >
                    {copiedKey === "code"
                      ? t("dealers.myAgents.copied")
                      : t("dealers.myAgents.copyCode")}
                  </Button>
                </div>
                <ol className="tv-agent-steps">
                  <li>{t("dealers.myAgents.step1")}</li>
                  <li>{t("dealers.myAgents.step2")}</li>
                  <li>{t("dealers.myAgents.step3")}</li>
                  <li>{t("dealers.myAgents.step4")}</li>
                </ol>
                <p className="tv-agent-message">{message}</p>
                <div className="tv-row-actions">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void copyText("msg", message)}
                  >
                    {copiedKey === "msg"
                      ? t("dealers.myAgents.copied")
                      : t("dealers.myAgents.copyMessage")}
                  </Button>
                </div>
              </div>
            ))}

          {requests.length > 0 && (
            <div>
              <h4>{t("dealers.myAgents.requestsTitle")}</h4>
              {requests.map((req) => (
                <div key={req.id} className="tv-agent-req">
                  <p>
                    {t("dealers.myAgents.requestLine")
                      .replace("{name}", req.requester_name)
                      .replace("{number}", req.requester_account_number)}
                  </p>
                  <span className="tv-row-actions">
                    <Button
                      size="sm"
                      loading={answering === req.id}
                      onClick={() => void answer(req.id, true)}
                    >
                      {t("dealers.myAgents.accept")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={answering === req.id}
                      onClick={() => void answer(req.id, false)}
                    >
                      {t("dealers.myAgents.decline")}
                    </Button>
                  </span>
                </div>
              ))}
            </div>
          )}

          <div>
            <h4>{t("dealers.record.claimsTitle")}</h4>
            {detail.claims.length === 0 ? (
              <p className="tv-agent-meta">{t("dealers.record.claimsEmpty")}</p>
            ) : (
              <div className="tv-agents-list">
                {detail.claims.map((claim) => (
                  <div key={claim.id} className="tv-agent-req">
                    <p>
                      <Link to={`/claims/${claim.id}`} className="tv-ix-link">
                        {claim.claim_number}
                      </Link>
                      {claim.item_name && (
                        <span className="tv-agent-meta"> · {claim.item_name}</span>
                      )}
                    </p>
                    <span className="tv-row-actions">
                      {claim.is_open && (
                        <Badge tone="accent">{t("dealers.record.openBadge")}</Badge>
                      )}
                      <StatusBadge status={claim.status as ClaimStatus} />
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h4>{t("dealers.record.truckTitle")}</h4>
            {detail.truck_accounts.length === 0 ? (
              <>
                <p className="tv-agent-meta">{t("dealers.record.truckEmpty")}</p>
                <p>
                  <LinkButton
                    to={`/truck-accounts?open=self&company=${companyId}&agent=${entry.kind}:${entry.private_agent_id ?? entry.agent_user_id ?? ""}`}
                    size="sm"
                  >
                    {t("dealers.record.truckOpen")}
                  </LinkButton>
                </p>
              </>
            ) : (
              <div className="tv-agents-list">
                {detail.truck_accounts.map((account) => (
                  <div key={account.id} className="tv-agent-req">
                    <p>
                      {t("dealers.record.truckBalance").replace(
                        "{balance}",
                        money(account.balance),
                      )}
                      {account.status === "active" && account.next_due_date
                        ? ` · ${t("dealers.record.truckNextDue").replace(
                            "{date}",
                            displayDate(account.next_due_date),
                          )}`
                        : ""}
                      {account.missed_payments > 0 ? (
                        <span className="tv-agent-missed">
                          {" · "}
                          {t("dealers.record.truckMissed").replace(
                            "{count}",
                            String(account.missed_payments),
                          )}{" "}
                          ({money(account.amount_past_due)})
                        </span>
                      ) : null}
                    </p>
                    <span className="tv-row-actions">
                      <Badge
                        tone={
                          account.status === "active"
                            ? "success"
                            : account.status === "invited"
                              ? "warning"
                              : "neutral"
                        }
                      >
                        {account.status}
                      </Badge>
                      <LinkButton
                        to={`/truck-accounts#account=${account.id}`}
                        size="sm"
                        variant="secondary"
                      >
                        {t("dealers.record.truckTitle")}
                      </LinkButton>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {record ? (
            <div className="tv-record-danger">
              {detail.can_delete ? (
                confirmDelete ? (
                  <>
                    <p className="tv-agent-notes">
                      {t("dealers.record.deleteConfirm")}
                    </p>
                    <span className="tv-row-actions">
                      <Button
                        size="sm"
                        variant="danger"
                        loading={deleting}
                        onClick={() => void doDelete()}
                      >
                        {t("dealers.record.delete")}
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => setConfirmDelete(false)}
                      >
                        {t("common.cancel")}
                      </Button>
                    </span>
                  </>
                ) : (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setConfirmDelete(true)}
                  >
                    {t("dealers.record.delete")}
                  </Button>
                )
              ) : (
                detail.delete_block_reason && (
                  <p className="tv-agent-notes">{detail.delete_block_reason}</p>
                )
              )}
            </div>
          ) : (
            detail.entry.connection_id && (
              <div className="tv-record-danger">
                <p className="tv-agent-notes">
                  {t("dealers.record.disconnectNote")}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={disconnecting}
                  onClick={() => void doDisconnect()}
                >
                  {t("dealers.record.disconnect")}
                </Button>
              </div>
            )
          )}
        </div>
      ) : null}
    </Panel>
  );
}
