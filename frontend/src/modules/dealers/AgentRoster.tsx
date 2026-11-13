import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  DataTable,
  DatePicker,
  EmptyState,
  FormField,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  type Column,
} from "../../components";
import { ApiError } from "../../lib/api";
import { todayLocalIso } from "../../lib/format";
import { useT } from "../../i18n/LocaleContext";
import { createPrivateAgent, getRoster, setAgentPreferred } from "./api";
import type { RosterEntry } from "./types";
import { AgentRecord } from "./AgentRecord";
import { AgentImportButton } from "./AgentCardImport";
import { tenureText } from "./rosterFormat";

/**
 * The dealer Agents tab's roster (stage 1, 2026-11-04;
 * multi-preferred, 2026-11-05): a true list of every agent the
 * viewer has for this company — his own entered records plus
 * the platform agents he is connected with. ANY of them can be
 * starred preferred at once: the star on each row toggles that
 * agent's own mark, nothing else — no switch, no tenure
 * stamp, no claim ever moves. Opening a row shows the agent's
 * full record (AgentRecord).
 *
 * Grouping (owner, 2026-11-04 21:11): the list renders as TWO
 * labeled sections — "Your agents" (the viewer's own entered
 * records) first, the dealer's "Listed agents" (the connected
 * registered agents) below. Membership and in-section order are
 * the roster read's own, unchanged; the preferred badge stays
 * on its holder in whichever section he sits. A section with
 * nobody in it says so plainly under its heading; a wholly
 * empty roster keeps the single empty line it always had.
 *
 * Layout (dealer page pass, 2026-11-06 — owner's redesign):
 * the tab opens on the LIST, bare — the Panel with its grey
 * header band that used to wrap the roster is gone — and
 * selecting an agent opens his CONTACT CARD (the full
 * AgentRecord) UNDER the list, on the same page; the list
 * never goes away. The card's Back button closes the card.
 * On phones the card stacks below the list, which is the
 * same single column.
 */
export function AgentRoster({
  companyId,
  onChanged,
  initialSelectedKey,
  asVisitor = false,
}: {
  companyId: string;
  onChanged: () => void;
  /** Deep link (#agent=<kind>:<id>, from an item page's
   *  "Dealer Agent:" line): open this roster entry's record
   *  as soon as the roster loads. Applied once — backing out
   *  to the list never re-opens it. */
  initialSelectedKey?: string | null;
  /** "View as visitor" preview (Sweep D5): the roster read
   *  is the preview fetch (a member with no agents here —
   *  the roster reads empty) and the viewer's own write
   *  doors (add / import an agent) do not render at all:
   *  in preview there is no roster of one's own to build. */
  asVisitor?: boolean;
}) {
  const t = useT();
  const { toast } = useToast();
  const [entries, setEntries] = useState<RosterEntry[] | null>(null);
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  /* A new agent starts on today (owner's date rule, 2026-11-04) —
   * started_at prefilled, clearable back to null. The route
   * anchor deliberately stays empty: it is a factual "a day the
   * route ran" reference, and a guessed today could phase-shift
   * the computed visits. */
  const blankAgentForm = () => ({
    name: "",
    phone: "",
    email: "",
    location: "",
    notes: "",
    route_frequency: "",
    route_day_of_week: "",
    route_anchor_date: "",
    started_at: todayLocalIso(),
  });
  const [form, setForm] = useState(blankAgentForm);
  const [saving, setSaving] = useState(false);
  const [settingPref, setSettingPref] = useState<string | null>(null);

  const [version, setVersion] = useState(0);
  const load = useCallback(async () => {
    setEntries(await getRoster(companyId, asVisitor));
    setVersion((v) => v + 1);
  }, [companyId, asVisitor]);

  useEffect(() => {
    load().catch((err) => {
      setError(
        err instanceof ApiError ? err.message : t("dealers.roster.loadError"),
      );
    });
  }, [load, t]);

  const selected = entries?.find((e) => e.key === selectedKey) ?? null;

  // The deep link's record opens once the roster has loaded
  // (once only — see the prop note). A key that matches no
  // entry (the record is gone) simply leaves the list up.
  const initialApplied = useRef(false);
  useEffect(() => {
    if (initialApplied.current || !initialSelectedKey || entries === null)
      return;
    initialApplied.current = true;
    if (entries.some((e) => e.key === initialSelectedKey)) {
      setSelectedKey(initialSelectedKey);
    }
  }, [entries, initialSelectedKey]);

  // The contact card lives under the list (redesign,
  // 2026-11-06): when a selection lands, bring the card into
  // view — gently (nearest) so a click on a visible row never
  // yanks the page further than it must.
  const cardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (selectedKey) cardRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedKey]);

  function targetBody(entry: RosterEntry) {
    return entry.kind === "private"
      ? { company_id: companyId, private_agent_id: entry.private_agent_id as string }
      : { company_id: companyId, agent_user_id: entry.agent_user_id as string };
  }

  async function togglePreferred(entry: RosterEntry) {
    setSettingPref(entry.key);
    try {
      await setAgentPreferred({
        ...targetBody(entry),
        is_preferred: !entry.is_preferred,
      });
      toast(
        t(
          entry.is_preferred
            ? "dealers.roster.unstarred"
            : "dealers.roster.starred",
        ).replace("{name}", entry.name),
        { tone: "success" },
      );
      await load();
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.roster.starError"),
        { tone: "danger" },
      );
    } finally {
      setSettingPref(null);
    }
  }

  async function saveAgent(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!form.name.trim()) {
      setError(t("dealers.myAgents.saveError"));
      return;
    }
    setSaving(true);
    try {
      await createPrivateAgent({
        company_id: companyId,
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
      });
      setForm(blankAgentForm());
      setFormOpen(false);
      await load();
      onChanged();
      toast(t("dealers.roster.savedNext"), { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("dealers.myAgents.saveError"),
      );
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<RosterEntry>[] = [
    {
      key: "name",
      header: t("dealers.roster.col.name"),
      render: (entry) => (
        <span className="tv-roster-namecell">
          <strong>{entry.name}</strong>
          {entry.is_preferred && (
            <Badge tone="accent">{t("dealers.roster.preferred")}</Badge>
          )}
          {entry.kind === "platform" ? (
            <Badge tone="neutral">{t("dealers.roster.kindPlatform")}</Badge>
          ) : entry.claimed_by_name ? (
            <Badge tone="success">
              {t("dealers.myAgents.claimedBy")
                .replace("{name}", entry.claimed_by_name)
                .replace("{number}", entry.claimed_by_account_number ?? "")}
            </Badge>
          ) : (
            <Badge tone="neutral">{t("dealers.myAgents.onlyYours")}</Badge>
          )}
        </span>
      ),
    },
    {
      key: "area",
      header: t("dealers.roster.col.area"),
      render: (entry) => entry.location || "—",
    },
    {
      key: "contact",
      header: t("dealers.roster.col.contact"),
      render: (entry) =>
        [entry.phone, entry.email].filter(Boolean).join(" · ") || "—",
    },
    {
      key: "tenure",
      header: t("dealers.roster.col.tenure"),
      render: (entry) => tenureText(t, entry),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (entry) => (
        <Button
          size="sm"
          variant="secondary"
          loading={settingPref === entry.key}
          onClick={(e) => {
            e.stopPropagation();
            void togglePreferred(entry);
          }}
        >
          {t(
            entry.is_preferred
              ? "dealers.roster.removePreferred"
              : "dealers.roster.makePreferred",
          )}
        </Button>
      ),
    },
  ];

  /* The two roster sections (owner, 2026-11-04): the viewer's
   * own entered records first, the dealer's listed (connected
   * registered) agents below. Partitioning the roster read
   * preserves its order inside each section — preferred agents
   * lead their section, badges and all. */
  const rosterGroups: {
    title: "dealers.roster.yoursTitle" | "dealers.roster.listedTitle";
    rows: RosterEntry[];
  }[] = [
    {
      title: "dealers.roster.yoursTitle",
      rows: (entries ?? []).filter((e) => e.kind === "private"),
    },
    {
      title: "dealers.roster.listedTitle",
      rows: (entries ?? []).filter((e) => e.kind === "platform"),
    },
  ];

  return (
    <>
      {error && <Alert tone="danger">{error}</Alert>}
      {entries === null && !error ? (
        <p className="tv-agent-meta">
          <Spinner size="sm" /> Loading…
        </p>
      ) : (
        <>
          {(entries ?? []).length === 0 ? (
            <EmptyState
              title={t("dealers.roster.emptyTitle")}
              description={t("dealers.roster.empty")}
            />
          ) : (
            rosterGroups.map((group) => (
              <div key={group.title} className="tv-roster-group">
                <h4 className="tv-roster-group-title">
                  {t(group.title)}
                </h4>
                {group.rows.length > 0 ? (
                  <DataTable
                    columns={columns}
                    rows={group.rows}
                    rowKey={(entry) => entry.key}
                    onRowClick={(entry) => setSelectedKey(entry.key)}
                  />
                ) : (
                  <p className="tv-agent-meta">
                    {t("dealers.roster.sectionEmpty")}
                  </p>
                )}
              </div>
            ))
          )}
          {selected && (
            <div className="tv-roster-card" ref={cardRef}>
              <AgentRecord
                key={`${selected.key}:${version}`}
                companyId={companyId}
                entry={selected}
                onBack={() => setSelectedKey(null)}
                onChanged={() => {
                  void load();
                  onChanged();
                }}
                onTogglePreferred={(entry) => void togglePreferred(entry)}
                onGone={() => {
                  setSelectedKey(null);
                  void load();
                  onChanged();
                }}
              />
            </div>
          )}
          {!asVisitor &&
            (formOpen ? (
                <form
                  onSubmit={(e) => void saveAgent(e)}
                  className="tv-agents-list"
                >
                  <FormField
                    label={t("dealers.myAgents.nameLabel")}
                    htmlFor="roster-agent-name"
                    required
                  >
                    <TextInput
                      id="roster-agent-name"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                    />
                  </FormField>
                  <FormField
                    label={t("dealers.myAgents.phoneLabel")}
                    htmlFor="roster-agent-phone"
                  >
                    <TextInput
                      id="roster-agent-phone"
                      value={form.phone}
                      onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    />
                  </FormField>
                  <FormField
                    label={t("dealers.myAgents.emailLabel")}
                    htmlFor="roster-agent-email"
                  >
                    <TextInput
                      id="roster-agent-email"
                      type="email"
                      value={form.email}
                      onChange={(e) => setForm({ ...form, email: e.target.value })}
                    />
                  </FormField>
                  <FormField
                    label={t("dealers.roster.locationLabel")}
                    htmlFor="roster-agent-location"
                  >
                    <TextInput
                      id="roster-agent-location"
                      value={form.location}
                      onChange={(e) =>
                        setForm({ ...form, location: e.target.value })
                      }
                    />
                  </FormField>
                  <FormField
                    label={t("dealers.roster.routeLabel")}
                    htmlFor="roster-agent-freq"
                  >
                    <Select
                      id="roster-agent-freq"
                      value={form.route_frequency}
                      onChange={(e) =>
                        setForm({ ...form, route_frequency: e.target.value })
                      }
                    >
                      <option value="">{t("dealers.roster.freq.na")}</option>
                      <option value="weekly">
                        {t("dealers.roster.freq.weekly")}
                      </option>
                      <option value="biweekly">
                        {t("dealers.roster.freq.biweekly")}
                      </option>
                      <option value="monthly">
                        {t("dealers.roster.freq.monthly")}
                      </option>
                    </Select>
                  </FormField>
                  {form.route_frequency !== "" && (
                    <>
                      <FormField
                        label={t("dealers.roster.routeDayLabel")}
                        htmlFor="roster-agent-day"
                      >
                        <Select
                          id="roster-agent-day"
                          value={form.route_day_of_week}
                          onChange={(e) =>
                            setForm({
                              ...form,
                              route_day_of_week: e.target.value,
                            })
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
                      <FormField
                        label={t("dealers.roster.anchorLabel")}
                        htmlFor="roster-agent-anchor"
                      >
                        <DatePicker
                          id="roster-agent-anchor"
                          value={form.route_anchor_date}
                          onChange={(v) =>
                            setForm({
                              ...form,
                              route_anchor_date: v,
                            })
                          }
                          clearable
                        />
                      </FormField>
                    </>
                  )}
                  <FormField
                    label={t("dealers.roster.startedLabel")}
                    htmlFor="roster-agent-started"
                  >
                    <DatePicker
                      id="roster-agent-started"
                      value={form.started_at}
                      onChange={(v) =>
                        setForm({ ...form, started_at: v })
                      }
                      clearable
                    />
                  </FormField>
                  <FormField
                    label={t("dealers.myAgents.notesLabel")}
                    htmlFor="roster-agent-notes"
                  >
                    <TextArea
                      id="roster-agent-notes"
                      value={form.notes}
                      onChange={(e) => setForm({ ...form, notes: e.target.value })}
                      rows={2}
                    />
                  </FormField>
                  <div className="tv-form-actions">
                    <Button type="submit" loading={saving}>
                      {t("dealers.myAgents.save")}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => setFormOpen(false)}
                    >
                      {t("common.cancel")}
                    </Button>
                  </div>
                </form>
              ) : (
                <div className="tv-form-actions">
                  <Button size="sm" onClick={() => setFormOpen(true)}>
                    {t("dealers.myAgents.add")}
                  </Button>
                  <AgentImportButton
                    defaultCompanyId={companyId}
                    onImported={() => {
                      void load();
                      onChanged();
                    }}
                  />
                </div>
              ))}
        </>
      )}
    </>
  );
}
