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
import { plural } from "../../lib/format";
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

function grantLabel(grant: PeerOutgoingGrant): string {
  if (grant.viewer) {
    return `${grant.viewer.name} · ${grant.viewer.account_number}`;
  }
  return grant.invited_email ?? "Someone";
}

export default function PeerSharingSettings() {
  const { toast } = useToast();
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
      toast("Withholding rule saved — matching items are hidden now.", {
        tone: "success",
        title: "Saved",
        duration: 8000,
      });
    } catch (err) {
      setRuleError(
        err instanceof ApiError ? err.message : "Couldn't save that rule.",
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
      toast("Withholding rule removed.", {
        tone: "success",
        title: "Saved",
        duration: 8000,
      });
    } catch (err) {
      setRuleError(
        err instanceof ApiError ? err.message : "Couldn't remove that rule.",
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
      toast("Set sharing choice saved.", {
        tone: "success",
        title: "Saved",
        duration: 8000,
      });
    } catch (err) {
      setSetChoiceError(
        err instanceof ApiError ? err.message : "Couldn't save that choice.",
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
        err instanceof ApiError ? err.message : "Couldn't load peer sharing.",
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
          ? `Invite sent to ${value}.`
          : "Invite sent — they'll see it under Shared tools.",
        { tone: "success", title: "Invite sent" },
      );
      await load();
    } catch (err) {
      setInviteError(
        err instanceof ApiError ? err.message : "Couldn't send that invite.",
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
      toast(`Sharing removed for ${grantLabel(grant)}.`, {
        tone: "success",
        title: "Saved",
        duration: 8000,
      });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't remove that grant.",
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
      toast("Your hidden-items list is saved.", {
        tone: "success",
        title: "Saved",
        duration: 8000,
      });
    } catch (err) {
      setHiddenError(
        err instanceof ApiError
          ? err.message
          : "Couldn't save the hidden items. Try again.",
      );
    } finally {
      setSavingHidden(false);
    }
  }

  if (peerOff) {
    return (
      <div>
        <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>People</p>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          The Shared tools module isn't enabled for your account right
          now, so there's nothing to manage here. Your existing sharing
          relationships are kept — if the module is switched back on,
          they pick up right where they left off.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>People</p>
      <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
        Share your list with specific people — your crew — so they can
        search "who has this tool?" and browse what you've got.
        People see a simple list: name, brand, model, category,
        and photos. Never prices, notes, or serial
        numbers. They see nothing until they accept your invite.
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
          <Spinner size="sm" /> Loading people sharing…
        </p>
      )}

      {overview && !canOwn && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Sharing a tool list is for the tool-owning groups — Mechanic
          / Technician and Shop / Company. Add one of those groups
          under Profile above and this section opens up. (Invites
          other people send you still appear under Shared tools.)
        </p>
      )}

      {overview && canOwn && (
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <form
            onSubmit={onInvite}
            style={{ display: "grid", gap: "var(--space-2)" }}
          >
            <p className="tv-setting-row-name">Invite someone</p>
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
                  placeholder="Account number (TV-…) or email"
                  aria-label="Account number or email to invite"
                />
              </div>
              <Button type="submit" loading={inviting} disabled={!target.trim()}>
                Send invite
              </Button>
            </div>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Inviting by email works even if they don't have an
              account yet — the invite waits and attaches when they
              sign up with that email.
            </p>
          </form>

          <div>
            <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
              People you share with
            </p>
            {overview.sharing_with.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                You're not sharing your list with anyone yet.
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
                      {grantLabel(grant)}{" "}
                      <Badge tone={grant.status === "accepted" ? "success" : "warning"}>
                        {grant.status === "accepted" ? "Sharing" : "Invited"}
                      </Badge>
                    </p>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      loading={busyGrant === grant.id}
                      onClick={() => void onRevoke(grant)}
                    >
                      Revoke
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
              <p className="tv-setting-row-name">Hidden items</p>
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {hidden?.size ?? 0} items hidden from people you share with
              </p>
            </div>
            <p
              style={{
                color: "var(--text-muted)",
                margin: "var(--space-1) 0 var(--space-2)",
              }}
            >
              Everything on your list is shared unless you hide it
              here. Hidden items don't appear in anyone's browsing or
              search — this applies to everyone you share with.
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
                  placeholder="Search your items…"
                  aria-label="Search your items"
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setHidden(new Set(myItems.map((t) => t.id)))}
              >
                Hide all
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setHidden(new Set())}
              >
                Hide none
              </Button>
            </div>
            {myItems.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                You don't have any items yet — add tools or batteries in
                Inventory and they'll show up here.
              </p>
            ) : visibleTools.length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                No items match that search.
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
                            · Battery
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
                Save hidden items
              </Button>
            </div>
          </div>

          <div>
            <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
              Hidden by rule
            </p>
            <p
              style={{
                color: "var(--text-muted)",
                margin: "var(--space-1) 0 var(--space-2)",
              }}
            >
              Hide whole groups of items at once: everything in a
              category, everything filed under a location (a toolbox
              and all its drawers), or everything with a tag. Rules
              apply the moment an item matches — including items you
              file there later.
            </p>
            {ruleError && <Alert tone="danger">{ruleError}</Alert>}
            {(overview.exclusion_rules ?? []).length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
                No withholding rules yet.
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
                          ? "Category"
                          : rule.scope === "location"
                            ? "Location"
                            : "Tag"}
                      </strong>{" "}
                      — {rule.scope_label}
                      <span style={{ color: "var(--text-muted)" }}>
                        {" "}
                        · hiding {rule.match_count} item
                        {rule.match_count === 1 ? "" : "s"} now
                      </span>
                    </p>
                    <button
                      type="button"
                      className="tv-list-remove-btn"
                      aria-label="Remove rule"
                      title="Remove rule"
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
              <FormField label="Rule type">
                <Select
                  value={ruleScope}
                  onChange={(e) =>
                    setRuleScope(
                      e.target.value as "category" | "location" | "tag",
                    )
                  }
                  aria-label="Rule type"
                >
                  <option value="category">Category</option>
                  <option value="location">Location</option>
                  <option value="tag">Tag</option>
                </Select>
              </FormField>
              {ruleScope === "category" && (
                <>
                  {(overview.categories ?? []).length > 0 && (
                    <FormField label="Category">
                      <Select
                        value={ruleCategoryChoice}
                        onChange={(e) => setRuleCategoryChoice(e.target.value)}
                        aria-label="Category"
                      >
                        <option value="">Choose a category…</option>
                        {(overview.categories ?? []).map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                        <option value="__new__">Type a new category…</option>
                      </Select>
                    </FormField>
                  )}
                  {(ruleCategoryChoice === "__new__" ||
                    (overview.categories ?? []).length === 0) && (
                    <FormField label="New category">
                      <TextInput
                        value={ruleCategoryText}
                        onChange={(e) => setRuleCategoryText(e.target.value)}
                        placeholder="e.g. Personal"
                        aria-label="New category"
                      />
                    </FormField>
                  )}
                </>
              )}
              {ruleScope === "location" && (
                <FormField label="Location">
                  <Select
                    value={ruleRefId}
                    onChange={(e) => setRuleRefId(e.target.value)}
                    aria-label="Location"
                  >
                    <option value="">Choose a location…</option>
                    {(overview.locations ?? []).map((loc) => (
                      <option key={loc.id} value={loc.id}>
                        {loc.path} ({plural(loc.subtree_item_count, "item")})
                      </option>
                    ))}
                  </Select>
                </FormField>
              )}
              {ruleScope === "tag" && (
                <FormField label="Tag">
                  <Select
                    value={ruleRefId}
                    onChange={(e) => setRuleRefId(e.target.value)}
                    aria-label="Tag"
                  >
                    <option value="">Choose a tag…</option>
                    {(overview.tags ?? []).map((tag) => (
                      <option key={tag.id} value={tag.id}>
                        {tag.name} ({plural(tag.item_count, "item")})
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
                Add rule
              </Button>
            </div>
          </div>

          {(overview.set_choices ?? []).length > 0 && (
            <div>
              <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
                Your sets
              </p>
              <p
                style={{
                  color: "var(--text-muted)",
                  margin: "var(--space-1) 0 var(--space-2)",
                }}
              >
                When someone browses your list, a set always shows its
                core pieces. Addon pieces and attached tools show only
                if you include them — decide per set.
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
                    label={`“${choice.name}” — include addon pieces & attached tools`}
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
