import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Badge,
  Button,
  EmptyState,
  FormField,
  Panel,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { ApiError, api } from "../../lib/api";
import { activeLocale } from "../../lib/format";
import { formatMoney } from "../../lib/money";

/**
 * MY CREW (wave 3): the shop owner's crew surface. Invite techs
 * by email (they attach when they sign up — no account needs to
 * exist yet) or by exact account number; the roster shows who's
 * in, who's invited, and who's left (with their 30-day grace
 * counting down). The bracket line reads the subscription's
 * STORED business bracket and notes a mismatch — display only,
 * nothing is enforced here.
 *
 * Membership by itself shares NOTHING: a crew member sees the
 * shop's tools only through Sharing (the shop-group tier), which
 * stays the one data gate.
 *
 * MEMBER TOOLS (claims-ownership lane, 2026-11-07): each active
 * member's row can open their tool list AS THE SHOP SEES IT —
 * read-only, exactly the member's own shop-group sharing
 * projection (their items, their chosen fields), for the shop's
 * reporting. There is no action of any kind on that list: no
 * edit, no claim, no checkout — viewing is all it does.
 */

interface CrewMembership {
  id: string;
  shop_name: string;
  employee_user_id: string | null;
  employee_name: string;
  employee_email: string;
  employee_account_number: string;
  invite_email: string;
  role_label: string;
  status: "invited" | "active" | "left" | "declined";
  invited_at: string;
  accepted_at: string | null;
  left_at: string | null;
  grace_days_left: number | null;
}

/** One row of a member's shared projection (core.sharing):
 * identity always; the rest only when the member chose to
 * share that field — absent keys render as "—", never as a
 * recorded empty. Money arrives as decimal strings in the
 * MEMBER's currency. */
interface CrewMemberTool {
  id: string;
  kind?: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  category?: string;
  location?: string;
  purchase_price?: string;
  purchase_date?: string;
  replacement_cost?: string;
}

interface CrewMemberTools {
  member_user_id: string;
  member_name: string;
  member_account_number: string;
  member_currency: string;
  sharing_enabled: boolean;
  items: CrewMemberTool[];
}

interface CrewSummary {
  active_count: number;
  invited_count: number;
  bracket: {
    plan_key: string;
    bracket_key: string;
    up_to_employees: number | null;
    label: string;
  } | null;
  bracket_note: string;
}

const STATUS_TONES: Record<CrewMembership["status"], "success" | "warning" | "neutral" | "danger"> = {
  active: "success",
  invited: "warning",
  left: "neutral",
  declined: "danger",
};

export default function CrewSettings() {
  const { toast } = useToast();
  const t = useT();
  const [roster, setRoster] = useState<CrewMembership[] | null>(null);
  const [summary, setSummary] = useState<CrewSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"email" | "account">("email");
  const [email, setEmail] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [roleLabel, setRoleLabel] = useState("");
  const [inviting, setInviting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [rows, sum] = await Promise.all([
        api<CrewMembership[]>("/core/crew"),
        api<CrewSummary>("/core/crew/summary"),
      ]);
      setRoster(rows);
      setSummary(sum);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.crew.loadFailed"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onInvite(e: FormEvent) {
    e.preventDefault();
    setInviting(true);
    setError(null);
    try {
      await api<CrewMembership>("/core/crew/invite", {
        method: "POST",
        body: JSON.stringify(
          mode === "email"
            ? { email: email.trim(), role_label: roleLabel.trim() }
            : { account_number: accountNumber.trim(), role_label: roleLabel.trim() },
        ),
      });
      setEmail("");
      setAccountNumber("");
      setRoleLabel("");
      toast(t("settings.crew.inviteSent"), { tone: "success" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.crew.inviteFailed"));
    } finally {
      setInviting(false);
    }
  }

  const [toolsFor, setToolsFor] = useState<string | null>(null);
  const [memberTools, setMemberTools] = useState<CrewMemberTools | null>(null);
  const [toolsBusy, setToolsBusy] = useState(false);

  async function onViewTools(row: CrewMembership) {
    if (!row.employee_user_id) return;
    setToolsFor(row.employee_user_id);
    setMemberTools(null);
    setToolsBusy(true);
    try {
      const data = await api<CrewMemberTools>(
        `/core/crew/members/${row.employee_user_id}/tools`,
      );
      setMemberTools(data);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("settings.crew.toolsLoadFailed"),
      );
      setToolsFor(null);
    } finally {
      setToolsBusy(false);
    }
  }

  async function onRemove(row: CrewMembership) {
    setError(null);
    try {
      await api(`/core/crew/${row.id}/remove`, { method: "POST" });
      toast(t("settings.crew.removedToast"), { tone: "success" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.crew.removeFailed"));
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <Panel title={t("settings.crew.myCrew")} variant="plate">
        {error && <Alert tone="danger">{error}</Alert>}
        {!summary && !error && <Spinner />}
        {summary && (
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <p style={{ margin: 0 }}>
              {t(
                summary.active_count === 1
                  ? "settings.crew.activeCountOne"
                  : "settings.crew.activeCountMany",
              ).replace("{count}", String(summary.active_count))}
              {summary.invited_count > 0 &&
                t(
                  summary.invited_count === 1
                    ? "settings.crew.invitesOutOne"
                    : "settings.crew.invitesOutMany",
                ).replace("{count}", String(summary.invited_count))}
              {summary.bracket &&
                t("settings.crew.bracketPart").replace(
                  "{label}",
                  summary.bracket.label,
                )}
            </p>
            {summary.bracket_note && (
              <Alert tone="warning">{summary.bracket_note}</Alert>
            )}
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.crew.sharesNothing")}
            </p>
          </div>
        )}
      </Panel>

      <Panel title={t("settings.crew.inviteMember")}>
        <form onSubmit={onInvite} style={{ display: "grid", gap: "var(--space-3)" }}>
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <Button
              type="button"
              variant={mode === "email" ? "primary" : "ghost"}
              onClick={() => setMode("email")}
            >
              {t("settings.crew.byEmail")}
            </Button>
            <Button
              type="button"
              variant={mode === "account" ? "primary" : "ghost"}
              onClick={() => setMode("account")}
            >
              {t("settings.crew.byAccount")}
            </Button>
          </div>
          {mode === "email" ? (
            <FormField
              label={t("settings.crew.emailLabel")}
              htmlFor="crew-invite-email"
              hint={t("settings.crew.emailHint")}
            >
              <TextInput
                id="crew-invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={320}
                autoComplete="email"
              />
            </FormField>
          ) : (
            <FormField
              label={t("settings.accountNumber")}
              htmlFor="crew-invite-account"
              hint={t("settings.crew.accountHint")}
            >
              <TextInput
                id="crew-invite-account"
                value={accountNumber}
                onChange={(e) => setAccountNumber(e.target.value)}
                required
                maxLength={16}
              />
            </FormField>
          )}
          <FormField label={t("settings.crew.roleLabel")} htmlFor="crew-invite-role">
            <TextInput
              id="crew-invite-role"
              value={roleLabel}
              onChange={(e) => setRoleLabel(e.target.value)}
              maxLength={120}
              placeholder={t("settings.crew.rolePlaceholder")}
            />
          </FormField>
          <div>
            <Button type="submit" loading={inviting}>
              {t("settings.sharing.sendInvite")}
            </Button>
          </div>
        </form>
      </Panel>

      <Panel title={t("settings.crew.roster")}>
        {!roster && !error && <Spinner />}
        {roster && roster.length === 0 && (
          <EmptyState
            title={t("settings.crew.noCrewTitle")}
            description={t("settings.crew.noCrewDesc")}
          />
        )}
        {roster && roster.length > 0 && (
          <div className="tv-table-wrap">
            <table className="tv-table">
              <thead>
                <tr>
                  <th>{t("settings.crew.thMember")}</th>
                  <th>{t("settings.crew.thRole")}</th>
                  <th>{t("settings.crew.thStatus")}</th>
                  <th>{t("settings.crew.thSince")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {roster.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.employee_name || row.invite_email}
                      {row.employee_account_number && (
                        <span style={{ color: "var(--text-muted)" }}>
                          {" "}
                          · {row.employee_account_number}
                        </span>
                      )}
                      {row.status === "invited" && !row.employee_user_id && (
                        <span style={{ color: "var(--text-muted)" }}>
                          {t("settings.crew.invitedAtPart").replace(
                            "{email}",
                            row.invite_email,
                          )}
                        </span>
                      )}
                    </td>
                    <td>{row.role_label || "—"}</td>
                    <td>
                      <Badge tone={STATUS_TONES[row.status]}>
                        {t(
                          (
                            {
                              active: "settings.crew.statusActive",
                              invited: "settings.crew.statusInvited",
                              left: "settings.crew.statusLeft",
                              declined: "settings.crew.statusDeclined",
                            } as Record<string, DictKey>
                          )[row.status],
                        )}
                      </Badge>
                      {row.status === "left" && row.grace_days_left !== null && (
                        <span style={{ color: "var(--text-muted)" }}>
                          {t(
                            row.grace_days_left === 1
                              ? "settings.crew.graceOne"
                              : "settings.crew.graceMany",
                          ).replace("{count}", String(row.grace_days_left))}
                        </span>
                      )}
                    </td>
                    <td>
                      {new Date(
                        row.accepted_at ?? row.invited_at,
                      ).toLocaleDateString(activeLocale())}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {row.status === "active" && row.employee_user_id && (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => void onViewTools(row)}
                        >
                          {t("settings.crew.viewTools")}
                        </Button>
                      )}
                      {(row.status === "active" || row.status === "invited") && (
                        <button
                          type="button"
                          className="tv-list-remove-btn"
                          aria-label={t("settings.crew.removeAria").replace(
                            "{label}",
                            row.employee_name || row.invite_email,
                          )}
                          title={t("settings.crew.removeTitle")}
                          onClick={() => void onRemove(row)}
                        >
                          {"−"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {toolsFor && (
        <Panel
          title={
            memberTools
              ? t("settings.crew.toolsTitle").replace(
                  "{name}",
                  memberTools.member_name || t("settings.crew.memberFallback"),
                )
              : t("settings.crew.toolsTitleLoading")
          }
        >
          {toolsBusy && <Spinner />}
          {memberTools && !memberTools.sharing_enabled && (
            <div className="tv-crew-tools">
              <p>
                {t("settings.crew.notSharing").replace(
                  "{name}",
                  memberTools.member_name || t("settings.crew.thisMember"),
                )}
              </p>
            </div>
          )}
          {memberTools && memberTools.sharing_enabled && (
            <div className="tv-crew-tools">
              {memberTools.items.length === 0 ? (
                <p>
                  {t("settings.crew.sharingEmpty")}
                </p>
              ) : (
                <div className="tv-table-wrap">
                  <table className="tv-table">
                    <thead>
                      <tr>
                        <th>{t("settings.crew.thItem")}</th>
                        <th>{t("settings.sharing.field.brand")}</th>
                        <th>{t("settings.sharing.field.model")}</th>
                        <th>{t("settings.crew.thSerial")}</th>
                        <th>{t("settings.sharing.field.category")}</th>
                        <th>{t("settings.sharing.field.location")}</th>
                        <th>{t("settings.sharing.field.purchase_price")}</th>
                        <th>{t("settings.crew.thPurchased")}</th>
                        <th>{t("settings.sharing.field.replacement_cost")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {memberTools.items.map((item) => (
                        <tr key={`${item.kind ?? "tool"}-${item.id}`}>
                          <td>
                            {item.name}
                            {item.kind === "battery" && (
                              <span className="tv-crew-batt">
                                {" "}
                                {t("settings.sharing.batterySuffix")}
                              </span>
                            )}
                          </td>
                          <td>{item.brand || "—"}</td>
                          <td>{item.model || "—"}</td>
                          <td>{item.serial_number || "—"}</td>
                          <td>{item.category || "—"}</td>
                          <td>{item.location || "—"}</td>
                          <td>
                            {item.purchase_price != null
                              ? formatMoney(
                                  item.purchase_price,
                                  memberTools.member_currency,
                                )
                              : "—"}
                          </td>
                          <td>
                            {item.purchase_date
                              ? new Date(
                                  `${item.purchase_date}T00:00:00`,
                                ).toLocaleDateString(activeLocale())
                              : "—"}
                          </td>
                          <td>
                            {item.replacement_cost != null
                              ? formatMoney(
                                  item.replacement_cost,
                                  memberTools.member_currency,
                                )
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="tv-crew-note">
                {t("settings.crew.noteText").replace(
                  "{name}",
                  memberTools.member_name || t("settings.crew.thisMember"),
                )}
              </p>
              <div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setToolsFor(null);
                    setMemberTools(null);
                  }}
                >
                  {t("settings.crew.closeList")}
                </Button>
              </div>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
