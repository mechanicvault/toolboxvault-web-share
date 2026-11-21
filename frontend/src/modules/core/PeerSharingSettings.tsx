import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  FormField,
  Select,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import { api, ApiError } from "../../lib/api"
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { useAuth } from "./AuthContext";
import { useMyModules } from "./MyModules";
import type {
  PeerOverview,
  PeerOutgoingGrant,
} from "../peer/types";

/**
 * Settings → Sharing → People (peer sharing, owner directive
 * 2026-10-17). The management side of sharing my list with specific
 * PEOPLE — crew-mates who can browse and search it for borrowing:
 *
 *   - invite by account number or email (an invite to someone
 *     without an account waits and attaches when they sign up);
 *   - my grants with their statuses, and revoke;
 *   - the tools I withhold from every peer viewer (default: none
 *     hidden — the whole list goes).
 *
 * What people see is FIXED (identity + photos) — there are no field
 * toggles here like the group editors above; that's the point of a
 * crew list. The browsing/searching surface itself is the Shared
 * tools page. Only the tool-owning groups (mechanic, shop) can send
 * invites; anyone else gets a plain explanation instead of a form
 * whose saves would be refused.
 */

const PEER_OWNER_TYPES = ["mechanic_technician", "shop_company"];

function grantLabel(
  grant: PeerOutgoingGrant,
  t?: (key: DictKey) => string,
): string {
  if (grant.viewer) {
    return `${grant.viewer.name} · ${grant.viewer.account_number}`;
  }
  return grant.invited_email ?? (t ? t("settings.sharing.someone") : "Someone");
}

function itemsCount(t: (key: DictKey) => string, n: number): string {
  return t(
    n === 1
      ? "settings.sharing.itemsCountOne"
      : "settings.sharing.itemsCountMany",
  ).replace("{count}", String(n));
}

export default function PeerSharingSettings({
  onSharingChanged,
}: {
  /** Fired after every successful peer mutation below, so a
   *  host page whose other tabs derive from peer sharing state
   *  (the Shared Tools page) can refresh them in-session
   *  (trio fix, 2026-11-12 — see SharingSettings). */
  onSharingChanged?: () => void;
} = {}) {
  const { toast } = useToast();
  const t = useT();
  const { user } = useAuth();
  const canOwn = (user?.account_types ?? []).some((t) =>
    PEER_OWNER_TYPES.includes(t),
  );
  // Module control (module doctrine, owner 2026-10-18): when the
  // shared_tools module isn't effective for this account — switched
  // off, unassigned, or dependency-blocked — this section explains
  // that instead of rendering forms whose saves would be refused.
  const { loading: modulesLoading, has } = useMyModules();
  const peerOff = !!user && !modulesLoading && !has("shared_tools");

  const [overview, setOverview] = useState<PeerOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [target, setTarget] = useState("");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [busyGrant, setBusyGrant] = useState<string | null>(null);

  const [hidden, setHidden] = useState<Set<string> | null>(null);
  const [savedHidden, setSavedHidden] = useState<Set<string>>(new Set());
  const [pickerQuery, setPickerQuery] = useState("");
  const [savingHidden, setSavingHidden] = useState(false);
  const [hiddenError, setHiddenError] = useState<string | null>(null);
  const [setChoiceBusy, setSetChoiceBusy] = useState<string | null>(null);
  const [setChoiceError, setSetChoiceError] = useState<string | null>(null);

  // Package C: withholding rules (category / location / tag).
  const [ruleScope, setRuleScope] = useState<"category" | "location" | "tag">(
    "category",
  );
  const [ruleCategoryChoice, setRuleCategoryChoice] = useState("");
  const [ruleCategoryText, setRuleCategoryText] = useState("");
  const [ruleRefId, setRuleRefId] = useState("");
  const [ruleBusy, setRuleBusy] = useState(false);
  const [ruleError, setRuleError] = useState<string | null>(null);

  async function onAddRule() {
    if (!overview) return;
    const body: Record<string, unknown> = { scope: ruleScope };
    if (ruleScope === "category") {
      body.scope_value = (
        ruleCategoryChoice === "__new__"
          ? ruleCategoryText
          : ruleCategoryChoice
      ).trim();
      if (!body.scope_value) return;
    } else {
      if (!ruleRefId) return;
      body.scope_ref_id = ruleRefId;
    }
    setRuleError(null);
    setRuleBusy(true);
    try {
      await api("/core/sharing/peer/exclusion-rules", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setRuleCategoryChoice("");
      setRuleCategoryText("");
      setRuleRefId("");
      await load();
      onSharingChanged?.();
      toast(t("settings.sharing.ruleSaved"), {
        tone: "success",
        title: t("settings.publicProfile.savedTitle"),
        duration: 8000,
      });
    } catch (err) {
      setRuleError(
        err instanceof ApiError ? err.message : t("settings.sharing.ruleSaveFailed"),
      );
    } finally {
      setRuleBusy(false);
    }
  }

  async function onRemoveRule(ruleId: string) {
    setRuleError(null);
    setRuleBusy(true);
    try {
      await api(`/core/sharing/peer/exclusion-rules/${ruleId}`, {
        method: "DELETE",
      });
      await load();
      onSharingChanged?.();
      toast(t("settings.sharing.ruleRemovedToast"), {
        tone: "success",
        title: t("settings.publicProfile.savedTitle"),
        duration: 8000,
      });
    } catch (err) {
      setRuleError(
        err instanceof ApiError ? err.message : t("settings.sharing.ruleRemoveFailed"),
      );
    } finally {
      setRuleBusy(false);
    }
  }

  /** Peer set addon choices save immediately (one toggle = one
   *  stored decision); the overview reloads with the server's answer. */
  async function onSetChoice(toolId: string, include: boolean) {
    setSetChoiceError(null);
    setSetChoiceBusy(toolId);
    try {
      await api("/core/sharing/peer/set-choices", {
        method: "PUT",
        body: JSON.stringify({ tool_id: toolId, include_addons: include }),
      });
      await load();
      onSharingChanged?.();
      toast(t("settings.sharing.setChoiceSaved"), {
        tone: "success",
        title: t("settings.publicProfile.savedTitle"),
        duration: 8000,
      });
    } catch (err) {
      setSetChoiceError(
        err instanceof ApiError ? err.message : t("settings.sharing.setChoiceFailed"),
      );
    } finally {
      setSetChoiceBusy(null);
    }
  }

  async function load() {
    try {
      const data = await api<PeerOverview>("/core/sharing/peer");
      setOverview(data);
      // One hidden set for both kinds — ids are UUIDs, unique
      // across tools and batteries; the split happens at save.
      const excluded = new Set([
        ...data.excluded_tool_ids,
        ...data.excluded_battery_ids,
      ]);
      setHidden(excluded);
      setSavedHidden(excluded);
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("settings.sharing.peerLoadFailed"),
      );
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const myItems = useMemo(
    () => [
      ...(overview?.my_tools ?? []).map((t) => ({ ...t, kind: "tool" })),
      ...(overview?.my_batteries ?? []).map((b) => ({ ...b, kind: "battery" })),
    ],
    [overview?.my_tools, overview?.my_batteries],
  );

  const visibleTools = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    if (!q) return myItems;
    return myItems.filter((t) =>
      [t.name, t.brand, t.model, t.serial_number]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [myItems, pickerQuery]);

  async function onInvite(e: FormEvent) {
    e.preventDefault();
    const value = target.trim();
    if (!value) return;
    setInviteError(null);
    setInviting(true);
    try {
      const body = value.includes("@")
        ? { email: value }
        : { account_number: value };
      const grant = await api<PeerOutgoingGrant>(
        "/core/sharing/peer/invite",
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      // Apply the server's answer immediately. The POST returns the
      // created grant (201 — or the existing one; invites are
      // idempotent), so clear the field and put the grant in the
      // list from THAT payload. These visible effects must not wait
      // on the follow-up refetch: if the GET stalls or fails, the
      // section would keep showing the pre-invite state until a
      // full page reload (browser QA, 2026-10-17). The refetch
      // below still runs — it reconciles the rest of the overview
      // (tools, exclusions) — but nothing the user sees depends on
      // it landing.
      setTarget("");
      setOverview((o) =>
        o
          ? {
              ...o,
              sharing_with: [
                grant,
                ...o.sharing_with.filter((g) => g.id !== grant.id),
              ],
            }
          : o,
      );
      toast(
        value.includes("@")
          ? t("settings.sharing.inviteSentTo").replace("{value}", value)
          : t("settings.sharing.inviteSent"),
        { tone: "success", title: t("settings.sharing.inviteSentTitle") },
      );
      await load();
      onSharingChanged?.();
    } catch (err) {
      setInviteError(
        err instanceof ApiError ? err.message : t("settings.sharing.inviteFailed"),
      );
    } finally {
      setInviting(false);
    }
  }

  async function onRevoke(grant: PeerOutgoingGrant) {
    setBusyGrant(grant.id);
    try {
      await api(`/core/sharing/peer/${grant.id}/revoke`, { method: "POST" });
      // Same rule as invite: the entry leaves the list from the
      // confirmed action itself, not from the refetch (which still
      // runs to reconcile).
      setOverview((o) =>
        o
          ? {
              ...o,
              sharing_with: o.sharing_with.filter((g) => g.id !== grant.id),
            }
          : o,
      );
      toast(
        t("settings.sharing.removedFor").replace("{label}", grantLabel(grant, t)),
        {
          tone: "success",
          title: t("settings.publicProfile.savedTitle"),
          duration: 8000,
        },
      );
      await load();
      onSharingChanged?.();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.sharing.revokeFailed"),
        { tone: "danger" },
      );
    } finally {
      setBusyGrant(null);
    }
  }

  function toggleHidden(id: string, on: boolean) {
    setHidden((h) => {
      if (!h) return h;
      const next = new Set(h);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const hiddenDirty =
    hidden !== null &&
    (hidden.size !== savedHidden.size ||
      [...hidden].some((id) => !savedHidden.has(id)));

  async function onSaveHidden() {
    if (!hidden) return;
    setHiddenError(null);
    setSavingHidden(true);
    try {
      const batteryIds = new Set(
        (overview?.my_batteries ?? []).map((b) => b.id),
      );
      const result = await api<{
        excluded_tool_ids: string[];
        excluded_battery_ids: string[];
      }>("/core/sharing/peer/exclusions", {
        method: "PUT",
        body: JSON.stringify({
          tool_ids: [...hidden].filter((id) => !batteryIds.has(id)),
          battery_ids: [...hidden].filter((id) => batteryIds.has(id)),
        }),
      });
      const saved = new Set([
        ...result.excluded_tool_ids,
        ...result.excluded_battery_ids,
      ]);
      setHidden(saved);
      setSavedHidden(saved);
      onSharingChanged?.();
      toast(t("settings.sharing.hiddenSaved"), {
        tone: "success",
        title: t("settings.publicProfile.savedTitle"),
        duration: 8000,
      });
    } catch (err) {
      setHiddenError(
        err instanceof ApiError
          ? err.message
          : t("settings.sharing.hiddenSaveFailed"),
      );
    } finally {
      setSavingHidden(false);
    }
  }

  if (peerOff) {
    return (
      <div>
        <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>{t("settings.sharing.people")}</p>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.sharing.moduleOff")}
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>{t("settings.sharing.people")}</p>
      <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
        {t("settings.sharing.peopleIntro")}
      </p>

      {loadError && <Alert tone="danger">{loadError}</Alert>}
      {!overview && !loadError && (
        <p
          style={{
            color: "var(--text-muted)",
            display: "flex",
            gap: "var(--space-2)",
            alignItems: "center",
            margin: 0,
          }}
        >
          <Spinner size="sm" /> {t("settings.sharing.loadingPeople")}
        </p>
      )}

      {overview && !canOwn && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.sharing.notOwner")}
        </p>
      )}

      {overview && canOwn && (
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <form
            onSubmit={onInvite}
            style={{ display: "grid", gap: "var(--space-2)" }}
          >
            <p className="tv-setting-row-name">{t("settings.sharing.inviteSomeone")}</p>
            {inviteError && <Alert tone="danger">{inviteError}</Alert>}
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                alignItems: "flex-start",
                flexWrap: "wrap",
              }}
            >
              <div style={{ flex: "1 1 240px" }}>
                <TextInput
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder={t("settings.sharing.invitePlaceholder")}
                  aria-label={t("settings.sharing.inviteAria")}
                />
              </div>
              <Button type="submit" loading={inviting} disabled={!target.trim()}>
                {t("settings.sharing.sendInvite")}
              </Button>
            </div>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.sharing.inviteNote")}
            </p>
          </form>

          <div>
            <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
              {t("settings.sharing.peopleYouShareWith")}
            </p>
            {overview.sharing_with.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t("settings.sharing.notSharingYet")}
              </p>
            ) : (
              <div style={{ display: "grid", gap: "0.5rem" }}>
                {overview.sharing_with.map((grant) => (
                  <div
                    key={grant.id}
                    className="tv-share-box"
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "1rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <p style={{ margin: 0 }}>
                      {grantLabel(grant, t)}{" "}
                      <Badge tone={grant.status === "accepted" ? "success" : "warning"}>
                        {grant.status === "accepted"
                          ? t("settings.sharing.statusSharing")
                          : t("settings.sharing.statusInvited")}
                      </Badge>
                    </p>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      loading={busyGrant === grant.id}
                      onClick={() => void onRevoke(grant)}
                    >
                      {t("settings.sharing.revoke")}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
                flexWrap: "wrap",
              }}
            >
              <p className="tv-setting-row-name">{t("settings.sharing.hiddenItems")}</p>
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t(
                  (hidden?.size ?? 0) === 1
                    ? "settings.sharing.hiddenCountOne"
                    : "settings.sharing.hiddenCountMany",
                ).replace("{count}", String(hidden?.size ?? 0))}
              </p>
            </div>
            <p
              style={{
                color: "var(--text-muted)",
                margin: "var(--space-1) 0 var(--space-2)",
              }}
            >
              {t("settings.sharing.hiddenIntro")}
            </p>
            {hiddenError && <Alert tone="danger">{hiddenError}</Alert>}
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                alignItems: "center",
                margin: "var(--space-2) 0",
                flexWrap: "wrap",
              }}
            >
              <div style={{ flex: "1 1 200px" }}>
                <TextInput
                  value={pickerQuery}
                  onChange={(e) => setPickerQuery(e.target.value)}
                  placeholder={t("settings.sharing.searchItemsPlaceholder")}
                  aria-label={t("settings.sharing.searchItemsAria")}
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setHidden(new Set(myItems.map((t) => t.id)))}
              >
                {t("settings.sharing.hideAll")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setHidden(new Set())}
              >
                {t("settings.sharing.hideNone")}
              </Button>
            </div>
            {myItems.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t("settings.sharing.noItemsYet")}
              </p>
            ) : visibleTools.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t("settings.sharing.noItemsMatch")}
              </p>
            ) : (
              <div
                style={{
                  display: "grid",
                  gap: "0.35rem",
                  maxHeight: "260px",
                  overflowY: "auto",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.6rem 0.75rem",
                }}
              >
                {visibleTools.map((tool) => (
                  <Checkbox
                    key={tool.id}
                    name={`peer-hidden-${tool.id}`}
                    checked={hidden?.has(tool.id) ?? false}
                    onChange={(e) => toggleHidden(tool.id, e.target.checked)}
                    label={
                      <>
                        {tool.name}
                        {tool.kind === "battery" && (
                          <span style={{ color: "var(--text-muted)" }}>
                            {" "}
                            {t("settings.sharing.batterySuffix")}
                          </span>
                        )}
                        {(tool.brand || tool.model) && (
                          <span style={{ color: "var(--text-muted)" }}>
                            {" "}
                            — {[tool.brand, tool.model]
                              .filter(Boolean)
                              .join(" ")}
                          </span>
                        )}
                      </>
                    }
                  />
                ))}
              </div>
            )}
            <div style={{ marginTop: "var(--space-3)" }}>
              <Button
                type="button"
                loading={savingHidden}
                disabled={!hiddenDirty}
                onClick={() => void onSaveHidden()}
              >
                {t("settings.sharing.saveHidden")}
              </Button>
            </div>
          </div>

          <div>
            <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
              {t("settings.sharing.hiddenByRule")}
            </p>
            <p
              style={{
                color: "var(--text-muted)",
                margin: "var(--space-1) 0 var(--space-2)",
              }}
            >
              {t("settings.sharing.hiddenByRuleIntro")}
            </p>
            {ruleError && <Alert tone="danger">{ruleError}</Alert>}
            {(overview.exclusion_rules ?? []).length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
                {t("settings.sharing.noWithholdingRules")}
              </p>
            ) : (
              <div style={{ display: "grid", gap: "0.5rem", marginBottom: "var(--space-2)" }}>
                {(overview.exclusion_rules ?? []).map((rule) => (
                  <div
                    key={rule.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "1rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <p style={{ margin: 0 }}>
                      <strong>
                        {rule.scope === "category"
                          ? t("settings.sharing.scopeCategory")
                          : rule.scope === "location"
                            ? t("settings.sharing.scopeLocation")
                            : t("settings.sharing.scopeTag")}
                      </strong>{" "}
                      — {rule.scope_label}
                      <span style={{ color: "var(--text-muted)" }}>
                        {" "}
                        {t(
                          rule.match_count === 1
                            ? "settings.sharing.hidingNowOne"
                            : "settings.sharing.hidingNowMany",
                        ).replace("{count}", String(rule.match_count))}
                      </span>
                    </p>
                    <button
                      type="button"
                      className="tv-list-remove-btn"
                      aria-label={t("settings.sharing.removeRule")}
                      title={t("settings.sharing.removeRule")}
                      disabled={ruleBusy}
                      onClick={() => void onRemoveRule(rule.id)}
                    >
                      {"−"}
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                alignItems: "flex-end",
                flexWrap: "wrap",
              }}
            >
              <FormField label={t("settings.sharing.ruleType")}>
                <Select
                  value={ruleScope}
                  onChange={(e) =>
                    setRuleScope(
                      e.target.value as "category" | "location" | "tag",
                    )
                  }
                  aria-label={t("settings.sharing.ruleType")}
                >
                  <option value="category">{t("settings.sharing.scopeCategory")}</option>
                  <option value="location">{t("settings.sharing.scopeLocation")}</option>
                  <option value="tag">{t("settings.sharing.scopeTag")}</option>
                </Select>
              </FormField>
              {ruleScope === "category" && (
                <>
                  {(overview.categories ?? []).length > 0 && (
                    <FormField label={t("settings.sharing.scopeCategory")}>
                      <Select
                        value={ruleCategoryChoice}
                        onChange={(e) => setRuleCategoryChoice(e.target.value)}
                        aria-label={t("settings.sharing.scopeCategory")}
                      >
                        <option value="">{t("settings.sharing.chooseCategory")}</option>
                        {(overview.categories ?? []).map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                        <option value="__new__">{t("settings.sharing.typeNewCategory")}</option>
                      </Select>
                    </FormField>
                  )}
                  {(ruleCategoryChoice === "__new__" ||
                    (overview.categories ?? []).length === 0) && (
                    <FormField label={t("settings.sharing.newCategory")}>
                      <TextInput
                        value={ruleCategoryText}
                        onChange={(e) => setRuleCategoryText(e.target.value)}
                        placeholder={t("settings.sharing.newCategoryPlaceholderPeer")}
                        aria-label={t("settings.sharing.newCategory")}
                      />
                    </FormField>
                  )}
                </>
              )}
              {ruleScope === "location" && (
                <FormField label={t("settings.sharing.scopeLocation")}>
                  <Select
                    value={ruleRefId}
                    onChange={(e) => setRuleRefId(e.target.value)}
                    aria-label={t("settings.sharing.scopeLocation")}
                  >
                    <option value="">{t("settings.sharing.chooseLocation")}</option>
                    {(overview.locations ?? []).map((loc) => (
                      <option key={loc.id} value={loc.id}>
                        {loc.path} ({itemsCount(t, loc.subtree_item_count)})
                      </option>
                    ))}
                  </Select>
                </FormField>
              )}
              {ruleScope === "tag" && (
                <FormField label={t("settings.sharing.scopeTag")}>
                  <Select
                    value={ruleRefId}
                    onChange={(e) => setRuleRefId(e.target.value)}
                    aria-label={t("settings.sharing.scopeTag")}
                  >
                    <option value="">{t("settings.sharing.chooseTag")}</option>
                    {(overview.tags ?? []).map((tag) => (
                      <option key={tag.id} value={tag.id}>
                        {tag.name} ({itemsCount(t, tag.item_count)})
                      </option>
                    ))}
                  </Select>
                </FormField>
              )}
              <Button
                type="button"
                variant="secondary"
                loading={ruleBusy}
                disabled={
                  ruleScope === "category"
                    ? (
                        ruleCategoryChoice === "__new__"
                          ? ruleCategoryText
                          : ruleCategoryChoice
                      ).trim() === ""
                    : ruleRefId === ""
                }
                onClick={() => void onAddRule()}
              >
                {t("settings.sharing.addRule")}
              </Button>
            </div>
          </div>

          {(overview.set_choices ?? []).length > 0 && (
            <div>
              <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
                {t("settings.sharing.yourSets")}
              </p>
              <p
                style={{
                  color: "var(--text-muted)",
                  margin: "var(--space-1) 0 var(--space-2)",
                }}
              >
                {t("settings.sharing.yourSetsIntro")}
              </p>
              {setChoiceError && <Alert tone="danger">{setChoiceError}</Alert>}
              <div style={{ display: "grid", gap: "0.35rem" }}>
                {(overview.set_choices ?? []).map((choice) => (
                  <Checkbox
                    key={choice.tool_id}
                    name={`peer-set-addons-${choice.tool_id}`}
                    checked={choice.include_addons}
                    disabled={setChoiceBusy === choice.tool_id}
                    onChange={(e) =>
                      void onSetChoice(choice.tool_id, e.target.checked)
                    }
                    label={t("settings.sharing.setAddonsLabel").replace(
                      "{name}",
                      choice.name,
                    )}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
