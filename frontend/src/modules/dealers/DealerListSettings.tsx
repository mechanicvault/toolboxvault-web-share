import { useCallback, useEffect, useState, type FormEvent } from "react";
import "./dealers.css";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  FormField,
  formGridStyle,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../components";
import { AddBlockMenu } from "../../components/AddBlockMenu";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import {
  createListEntry,
  deleteListEntry,
  getDealerListSettings,
  hideDirectoryCompany,
  restoreDealerList,
  unhideDirectoryCompany,
  updateListEntry,
} from "./api";
import { PHONE_LABELS } from "./components/CompanyForm";
import type {
  DealerListEntry,
  DealerListEntryWrite,
  DealerListSettings as DealerListSettingsData,
  DealerPhone,
} from "./types";

const stackStyle = { display: "grid", gap: "var(--spacing)" } as const;
const hintStyle = { margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" } as const;
const loadingStyle = {
  color: "var(--text-muted)",
  display: "flex",
  gap: "var(--space-2)",
  alignItems: "center",
} as const;
const phoneLabelStyle = { maxWidth: "180px" } as const;
const phoneNumberStyle = { flex: "1 1 180px" } as const;

const EMPTY_ENTRY: DealerListEntryWrite = {
  name: "",
  kind: "manufacturer",
  email: "",
  website: "",
  address: "",
  phones: [],
  notes: "",
};

function entryToWrite(entry: DealerListEntry): DealerListEntryWrite {
  return {
    name: entry.name,
    kind: entry.kind,
    email: entry.email,
    website: entry.website,
    address: entry.address,
    phones: entry.phones.map((p) => ({ ...p })),
    notes: entry.notes,
  };
}

/** Home Edit view's remove disc (owner pattern, 2026-10-24;
 *  glyph − since the site-wide list +/− rule, 2026-11-10): the
 *  same .tv-box-x treatment Home's boxes and stats carry — one
 *  remove control, every seat. Exported for the Dealers page
 *  directory, whose customize mode puts the same disc on its
 *  rows in place (owner correction, 2026-11-01). */
export function RemoveX({
  name,
  removeLabel,
  busy,
  onRemove,
}: {
  name: string;
  removeLabel: string;
  busy?: boolean;
  onRemove: () => void;
}) {
  return (
    <button
      type="button"
      className="tv-box-x"
      aria-label={`${removeLabel}: ${name}`}
      title={removeLabel}
      disabled={busy}
      onClick={onRemove}
    >
      −
    </button>
  );
}

/** The list-entry form — the Add menu's new-dealer path and the
 *  entry rows' Edit — one form, every seat: the Settings manager
 *  below renders it inline; the Dealers page renders it in a
 *  Modal over the directory it adds to. Owns its draft; the
 *  caller owns the write (create vs update) and whatever
 *  happens once it lands. */
export function ListEntryForm({
  initial,
  onSave,
  onCancel,
}: {
  /** Prefill (an existing entry being edited); omitted = a
   *  blank new-dealer form. */
  initial?: DealerListEntryWrite;
  onSave: (body: DealerListEntryWrite) => Promise<void>;
  onCancel: () => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState<DealerListEntryWrite>(
    initial ?? EMPTY_ENTRY,
  );
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  function setPhone(index: number, patch: Partial<DealerPhone>) {
    setDraft((v) => ({
      ...v,
      phones: v.phones.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!draft.name.trim()) {
      setFormError(t("dealerList.entryNameRequired"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    try {
      await onSave({
        ...draft,
        name: draft.name.trim(),
        phones: draft.phones.filter((p) => p.number.trim()),
      });
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Couldn't save the entry.",
      );
    } finally {
      setFormBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)}>
      <div style={stackStyle}>
        <div style={formGridStyle}>
          <FormField label={t("dealerList.entryName")} htmlFor="dlist-name" required>
            <TextInput
              id="dlist-name"
              value={draft.name}
              onChange={(e) => setDraft((v) => ({ ...v, name: e.target.value }))}
            />
          </FormField>
          <FormField label={t("dealerList.entryKind")} htmlFor="dlist-kind">
            <Select
              id="dlist-kind"
              value={draft.kind}
              onChange={(e) =>
                setDraft((v) => ({
                  ...v,
                  kind: e.target.value as DealerListEntryWrite["kind"],
                }))
              }
            >
              <option value="manufacturer">
                {t("dealerList.kindManufacturer")}
              </option>
              <option value="retailer">{t("dealerList.kindRetailer")}</option>
            </Select>
          </FormField>
          <FormField label={t("dealerList.entryEmail")} htmlFor="dlist-email">
            <TextInput
              id="dlist-email"
              type="email"
              value={draft.email}
              onChange={(e) => setDraft((v) => ({ ...v, email: e.target.value }))}
            />
          </FormField>
          <FormField label={t("dealerList.entryWebsite")} htmlFor="dlist-website">
            <TextInput
              id="dlist-website"
              value={draft.website}
              onChange={(e) => setDraft((v) => ({ ...v, website: e.target.value }))}
              placeholder="https://…"
            />
          </FormField>
        </div>
        <FormField label={t("dealerList.entryAddress")} htmlFor="dlist-address">
          <TextArea
            id="dlist-address"
            value={draft.address}
            onChange={(e) => setDraft((v) => ({ ...v, address: e.target.value }))}
            rows={2}
          />
        </FormField>
        <div style={stackStyle}>
          <span>{t("dealerList.entryPhones")}</span>
          {draft.phones.map((phone, i) => (
            <div key={i} className="tv-dlist-phone-row">
              <Select
                value={phone.label}
                onChange={(e) => setPhone(i, { label: e.target.value })}
                aria-label="Phone department"
                style={phoneLabelStyle}
              >
                {PHONE_LABELS.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </Select>
              <TextInput
                value={phone.number}
                onChange={(e) => setPhone(i, { number: e.target.value })}
                placeholder="Phone number"
                aria-label="Phone number"
                style={phoneNumberStyle}
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() =>
                  setDraft((v) => ({
                    ...v,
                    phones: v.phones.filter((_, idx) => idx !== i),
                  }))
                }
              >
                {t("dealerList.entryRemovePhone")}
              </Button>
            </div>
          ))}
          <div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                setDraft((v) => ({
                  ...v,
                  phones: [
                    ...v.phones,
                    { label: "Customer Service", number: "" },
                  ],
                }))
              }
            >
              {t("dealerList.entryAddPhone")}
            </Button>
          </div>
        </div>
        <FormField label={t("dealerList.entryNotes")} htmlFor="dlist-notes">
          <TextArea
            id="dlist-notes"
            value={draft.notes}
            onChange={(e) => setDraft((v) => ({ ...v, notes: e.target.value }))}
            rows={2}
          />
        </FormField>
        {formError && <Alert tone="danger">{formError}</Alert>}
        <div className="tv-dlist-actions">
          <Button type="submit" loading={formBusy}>
            {t("dealerList.entrySave")}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </form>
  );
}

/**
 * My dealer list (owner directive, 2026-10-31): the per-user
 * customization of the prefilled dealer pick list. Its home is
 * Settings → My dealer list; the Dealers page's Customize edits
 * the same overlay IN PLACE on the directory itself (owner
 * correction, 2026-11-01 — a separate manager list swapped in
 * over there was rejected), reusing this file's RemoveX and
 * ListEntryForm. The list is an overlay on the live directory:
 * taking a prefilled brand off only takes it off THIS user's
 * lists (their pick lists, the Dealers page directory, and their
 * other dealer choosers — never their records, never anyone
 * else's list), and the user's own additions are templates —
 * picking one while entering a dealer mints it into My companies
 * with the details filled in. Restore returns the list to the
 * shipped defaults.
 *
 * Edit pattern (owner directive, 2026-11-01): the manager mirrors
 * Home's Edit view. At rest the list is clean — what's on the
 * user's list, nothing else. Edit mode puts a red − disc on every
 * removable row and an Add menu at the TOP holding the removed
 * prefilled dealers (tap one to bring it back) plus the new-dealer
 * path. The component carries its own Edit/Done.
 */
export default function DealerListSettings() {
  const t = useT();
  const { toast } = useToast();
  const [settings, setSettings] = useState<DealerListSettingsData | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [editing, setEditing] = useState(false);
  // Entry form: null = closed, "new" = adding, otherwise the id
  // of the entry being edited. The form itself (ListEntryForm,
  // above) owns the draft.
  const [formFor, setFormFor] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const data = await getDealerListSettings();
    setSettings(data);
  }, []);

  useEffect(() => {
    refresh().catch((err) =>
      setLoadError(
        err instanceof ApiError ? err.message : t("dealerList.loadError"),
      ),
    );
  }, [refresh, t]);

  async function toggleHidden(companyId: string, hidden: boolean) {
    setError("");
    setBusyKey(companyId);
    try {
      const next = hidden
        ? await unhideDirectoryCompany(companyId)
        : await hideDirectoryCompany(companyId);
      setSettings(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update your list.");
    } finally {
      setBusyKey("");
    }
  }

  async function restore() {
    if (!window.confirm(t("dealerList.restoreConfirm"))) return;
    setError("");
    setBusyKey("restore");
    try {
      const result = await restoreDealerList();
      setSettings(result.settings);
      setFormFor(null);
      toast(t("dealerList.restored"), { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't restore the defaults.");
    } finally {
      setBusyKey("");
    }
  }

  function openAdd() {
    setFormFor("new");
  }

  function openEdit(entry: DealerListEntry) {
    setFormFor(entry.id);
  }

  /** The entry form's write: create for a new entry, update for
   *  the one being edited; the form closes and the list re-reads
   *  once the write lands. A throw surfaces in the form. */
  async function saveEntryBody(body: DealerListEntryWrite) {
    if (formFor === "new") await createListEntry(body);
    else if (formFor) await updateListEntry(formFor, body);
    setFormFor(null);
    await refresh();
  }

  async function removeEntry(entry: DealerListEntry) {
    if (
      !window.confirm(
        t("dealerList.removeEntryConfirm").replace("{name}", entry.name),
      )
    )
      return;
    setError("");
    setBusyKey(entry.id);
    try {
      await deleteListEntry(entry.id);
      if (formFor === entry.id) setFormFor(null);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove the entry.");
    } finally {
      setBusyKey("");
    }
  }

  if (loadError) {
    return <Alert tone="danger">{loadError}</Alert>;
  }
  if (settings === null) {
    return (
      <p style={loadingStyle}>
        <Spinner size="sm" /> Loading…
      </p>
    );
  }

  const onList = settings.directory.filter((row) => !row.hidden);
  const offList = settings.directory.filter((row) => row.hidden);
  // The Add menu (Home's pattern): what is NOT on the list — the
  // removed prefilled dealers first (tap = back on the list),
  // then the new-dealer path into the entry form.
  const addItems = [
    ...offList.map(({ company }) => ({
      key: `co:${company.id}`,
      title: company.name,
    })),
    { key: "__new__", title: t("dealerList.addEntry") },
  ];

  function handleAdd(key: string) {
    if (key === "__new__") {
      openAdd();
      return;
    }
    if (key.startsWith("co:")) {
      void toggleHidden(key.slice("co:".length), true);
    }
  }

  // The entry the form is editing (formFor "new" = a blank form).
  const formEntry =
    formFor && formFor !== "new"
      ? settings.entries.find((e) => e.id === formFor)
      : undefined;

  return (
    <div style={stackStyle}>
      <p style={hintStyle}>{t("dealerList.intro")}</p>
      {error && <Alert tone="danger">{error}</Alert>}

      <div className="tv-dlist-toolbar">
        {editing && (
          <>
            <AddBlockMenu
              items={addItems}
              onAdd={handleAdd}
              menuLabel={t("dealerList.addMenuLabel")}
            />
            <Button
              size="sm"
              variant="secondary"
              loading={busyKey === "restore"}
              onClick={() => void restore()}
            >
              {t("dealerList.restore")}
            </Button>
          </>
        )}
        <span className="tv-dlist-toolbar-spacer" />
        {editing ? (
          <Button size="sm" onClick={() => setEditing(false)}>
            {t("dealerList.done")}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setEditing(true)}
          >
            {t("dealerList.editEntry")}
          </Button>
        )}
      </div>

      <Panel title={t("dealerList.directoryTitle")}>
        <div style={stackStyle}>
          {editing && <p style={hintStyle}>{t("dealerList.directoryBody")}</p>}
          {onList.length === 0 ? (
            <p style={hintStyle}>{t("dealerList.noneOnList")}</p>
          ) : (
            <div className="tv-dlist-rows">
              {onList.map(({ company }) => (
                <div key={company.id} className="tv-dlist-row">
                  <p className="tv-dlist-main">
                    <strong>{company.name}</strong>{" "}
                    {company.kind === "retailer" && (
                      <Badge tone="accent">{t("dealerList.kindRetailer")}</Badge>
                    )}
                  </p>
                  {editing && (
                    <RemoveX
                      name={company.name}
                      removeLabel={t("home.remove")}
                      busy={busyKey === company.id}
                      onRemove={() => void toggleHidden(company.id, false)}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Panel>

      <Panel title={t("dealerList.entriesTitle")}>
        <div style={stackStyle}>
          {editing && <p style={hintStyle}>{t("dealerList.entriesBody")}</p>}
          {settings.entries.length === 0 && formFor === null ? (
            <EmptyState title={t("dealerList.entriesEmpty")} />
          ) : (
            <div className="tv-dlist-rows">
              {settings.entries.map((entry) => (
                <div key={entry.id} className="tv-dlist-row">
                  <p className="tv-dlist-main">
                    <strong>{entry.name}</strong>{" "}
                    <span className="tv-dlist-note">
                      {[entry.email, entry.website].filter(Boolean).join(" · ")}
                    </span>
                    {entry.created_company_id && (
                      <>
                        {" "}
                        <Badge tone="success">
                          {t("dealerList.entryInCompanies").replace(
                            "{name}",
                            entry.created_company_name,
                          )}
                        </Badge>
                      </>
                    )}
                  </p>
                  {editing && (
                    <div className="tv-dlist-actions">
                      {!entry.created_company_id && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => openEdit(entry)}
                        >
                          {t("dealerList.editEntry")}
                        </Button>
                      )}
                      <RemoveX
                        name={entry.name}
                        removeLabel={t("home.remove")}
                        busy={busyKey === entry.id}
                        onRemove={() => void removeEntry(entry)}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {editing && formFor === "new" && (
            <ListEntryForm
              key="new"
              onSave={saveEntryBody}
              onCancel={() => setFormFor(null)}
            />
          )}
          {editing && formEntry && (
            <ListEntryForm
              key={formEntry.id}
              initial={entryToWrite(formEntry)}
              onSave={saveEntryBody}
              onCancel={() => setFormFor(null)}
            />
          )}
        </div>
      </Panel>
    </div>
  );
}
