import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Badge,
  BrandIcon,
  Button,
  Checkbox,
  CopyButton,
  EmptyState,
  FormField,
  Modal,
  Panel,
  SectionPageHeader,
  Spinner,
  Tabs,
  TextArea,
  TextInput,
  useToast,
  HrefButton,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { RequireAuth, useAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import {
  approveCheckout,
  cancelCheckout,
  createBorrower,
  declineCheckout,
  deleteBorrower,
  getBorrowerRollup,
  getBorrowingOverview,
  listBorrowers,
  nudgeCheckout,
  returnCheckout,
} from "./api";
import {
  STATE_LABELS,
  STATE_TONES,
  fullDate,
  itemPath,
} from "./format";
import { BorrowerBookTools, BorrowerCardButton } from "./ContactCards";
import { LendingHistoryList } from "./components/LendingHistoryList";
import { CheckoutWalkthrough } from "../walkthroughs/CheckoutWalkthrough";
import { shouldOfferCheckout } from "../walkthroughs/logic";
import { WalkthroughDoor } from "../walkthroughs/WalkthroughShell";
import type {
  BorrowerContact,
  BorrowerRollup,
  BorrowingOverview,
  Checkout,
  NudgeResult,
} from "./types";
import "./borrowing.css";

/**
 * Borrowing (module doctrine build, 2026-10-18): the check-out
 * ledger's home.
 *
 * Main tab layout (program lane 3, 2026-11-10): the kit header
 * (SectionPageHeader) + Steel tabs — Lent out · Address book ·
 * History (owner's tab list, 2026-11-09). The sections the old
 * stacked page carried keep their settled order (2026-11-05)
 * INSIDE the tabs: the Lent out tab is the lending workflow's
 * home — lent out first, then requests waiting on me, my
 * outgoing requests, and what I'm holding; the Address book
 * tab holds the Add borrower box over the book; finished lends
 * settle into the History tab with their full paper trail.
 * Rows never disappear.
 *
 * The page has no settings of its own (conformance map: the
 * only borrowing-adjacent prefs are the per-category email
 * rows in Settings → Notifications) — the Actions menu is the
 * three tab jumps and carries NO Settings entry (recorded n/a).
 *
 * Actions apply the server's confirmed answer to the screen by
 * reloading the overview (one read, always consistent) — the same
 * discipline the peer surfaces use.
 */

/** The page's three tabs (Ryan's spec, 2026-11-09). */
type BorrowingTabId = "lent-out" | "address-book" | "history";

/** Deep links pick the opening tab — #address-book / #history,
 *  the way /shared-tools and /repairs hashes pick theirs.
 *  Anything else opens on Lent out. (The notification
 *  click-through rides ?checkout= instead — see the landing
 *  effect in BorrowingContent, which routes to the tab that
 *  holds the target row.) */
function tabFromHash(hash: string): BorrowingTabId {
  const raw = hash.replace(/^#/, "");
  if (raw === "address-book") return "address-book";
  if (raw === "history") return "history";
  return "lent-out";
}

function ItemLink({ row }: { row: Checkout }) {
  return (
    <span style={{ display: "inline-flex", gap: "0.45rem", alignItems: "center", flexWrap: "wrap" }}>
      <Link
        to={itemPath(row)}
        style={{ color: "var(--accent)", fontWeight: 600 }}
      >
        {row.item_name}
      </Link>
      {row.group_id && (
        <Badge tone="neutral">Part of a set lend — returns together</Badge>
      )}
    </span>
  );
}

/** List tables (list-standard wave 6, 2026-11-02): every ledger
 *  list is a TRUE list — one checkout per row under a header row,
 *  each fact in its own column (Item · the other person · the
 *  dates · Status · Actions), the dealer DirectoryTable pattern.
 *  Notes never ride a list face (owner, 2026-11-12) — a loan's
 *  notes are read on the item page's Borrowing tab, a contact's
 *  inside their book entry. Rows are two-way doors (same order):
 *  the row opens the item's Borrowing tab, the item's name opens
 *  the item page (CheckoutRow). The click-through landing flash
 *  (notification spec 2026-10-25) outlines the ?checkout= row in
 *  the accent briefly, as before. */
function TableHead({ cols }: { cols: (string | null)[] }) {
  return (
    <div className="tv-bw-thead" role="row">
      {cols.map((col, i) =>
        col === null ? (
          <span key={i} aria-hidden="true" />
        ) : (
          <span key={i} role="columnheader">
            {col}
          </span>
        ),
      )}
    </div>
  );
}

function Cell({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div role="cell" className={className}>
      {children}
    </div>
  );
}

/** A date fact cell (sweep B4, F7): on desktop the column
 *  header names the fact; at phone width the header row hides
 *  and the restacked row would show bare dates side by side —
 *  so the cell carries its header's word as a label span the
 *  phone CSS seats in front of the value. Same word as the
 *  column it sits under, never a second vocabulary. */
function DatedCell({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Cell>
      <span className="tv-bw-cell-label" aria-hidden="true">
        {label}
      </span>
      {children}
    </Cell>
  );
}

/** The item cell's content: the name link (the door to the item
 *  page) + the overdue flag. Shared by the ledger rows and the
 *  History tab's Main list rows. */
function ItemNameBits({ row }: { row: Checkout }) {
  return (
    <>
      <ItemLink row={row} />
      {row.overdue && (
        <Badge tone="danger" dot>
          Overdue
        </Badge>
      )}
    </>
  );
}

function ItemCell({ row }: { row: Checkout }) {
  return (
    <Cell className="tv-bw-cell-item">
      <ItemNameBits row={row} />
    </Cell>
  );
}

/** A ledger row — a two-way door (owner, 2026-11-12). The ROW
 *  opens the item's Borrowing tab (the detail page's #borrowing
 *  hash); the item's NAME, a plain link inside the row, opens
 *  the item page itself. The click guard steps aside for every
 *  real control inside the row (links, the action buttons), so
 *  nothing double-fires; the row itself is focusable and
 *  Enter/Space activate it, and the theme sheet's ROWS family
 *  gives it the main highlight (inset outline + glow, no lift)
 *  on hover and focus-within. */
function CheckoutRow({
  row,
  flash,
  children,
  actions,
}: {
  row: Checkout;
  flash?: boolean;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  const navigate = useNavigate();
  const open = () => navigate(`${itemPath(row)}#borrowing`);
  return (
    <div
      id={`checkout-${row.id}`}
      className={`tv-bw-row tv-bw-row--link${flash ? " tv-bw-row--flash" : ""}`}
      role="row"
      tabIndex={0}
      onClick={(e) => {
        const el = e.target as HTMLElement;
        if (
          el.closest("a, button, input, select, textarea, [role='button']")
        )
          return;
        open();
      }}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
    >
      {children}
      {actions ? (
        <div className="tv-bw-actions" role="cell">
          {actions}
        </div>
      ) : null}
    </div>
  );
}

/** Add borrower + the borrower address book (gap wave 1):
 *  reusable borrower contacts with their roll-up over the
 *  ledger. Deleting a contact NEVER touches checkout history —
 *  the lends keep their snapshots. The add form stands in its
 *  OWN box directly above the book (owner, settled 2026-11-05);
 *  one component keeps the shared state, so a borrower saved
 *  in the box lands in the book below without a reload. */
function BorrowersPanel({
  expandContactId,
}: {
  /** The ?borrower= landing (lending-history borrower links,
   *  2026-11-12): open this contact's entry once the book
   *  loads, the way ?checkout= lands on a ledger row. */
  expandContactId?: string | null;
}) {
  const t = useT();
  const { toast } = useToast();
  const [contacts, setContacts] = useState<BorrowerContact[] | null>(null);
  const [rollupBusy, setRollupBusy] = useState<string | null>(null);
  // F1-20: borrower suggestions from lending HISTORY — people the
  // owner already lent to (manual checkouts carry name+contact
  // snapshots) who aren't in the book yet, one tap to save.
  const [historyPeople, setHistoryPeople] = useState<{ name: string; contact: string }[]>([]);
  useEffect(() => {
    getBorrowingOverview()
      .then((o) => {
        const seen = new Map<string, { name: string; contact: string }>();
        for (const row of [...o.lent_out, ...o.history]) {
          const name = (row.borrower_name ?? "").trim();
          if (!name || row.borrower_contact_id) continue;
          const key = name.toLowerCase();
          if (!seen.has(key)) seen.set(key, { name, contact: row.borrower_contact ?? "" });
        }
        setHistoryPeople([...seen.values()]);
      })
      .catch(() => setHistoryPeople([]));
  }, []);
  const [expanded, setExpanded] = useState<BorrowerRollup | null>(null);
  const [name, setName] = useState("");
  const [contactInfo, setContactInfo] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listBorrowers()
      .then(setContacts)
      .catch(() => setContacts([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function onAdd(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await createBorrower({
        name: name.trim(),
        contact: contactInfo.trim(),
        notes: notes.trim(),
      });
      setName("");
      setContactInfo("");
      setNotes("");
      toast("Borrower saved to your address book.", { tone: "success" });
      load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save that borrower.", {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onToggle(contact: BorrowerContact) {
    if (expanded?.contact.id === contact.id) {
      setExpanded(null);
      return;
    }
    try {
      setExpanded(await getBorrowerRollup(contact.id));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't load their history.", {
        tone: "danger",
      });
    }
  }

  // The ?borrower= landing: expand the linked contact's entry
  // once, when the book has loaded — a history row's borrower
  // link lands ON that borrower's own surface, not the tab's
  // top. Fires once per id; the reader can still collapse it.
  const autoExpanded = useRef<string | null>(null);
  useEffect(() => {
    if (!expandContactId || contacts === null) return;
    if (autoExpanded.current === expandContactId) return;
    const contact = contacts.find((c) => c.id === expandContactId);
    if (!contact) return;
    autoExpanded.current = expandContactId;
    void onToggle(contact);
    // onToggle is this render's closure over `expanded`; the
    // guard ref keeps the landing to one expansion per id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandContactId, contacts]);

  /** Mark one of this borrower's current loans returned, right
   *  here on the borrower's own surface (sweep B4, F2 — the
   *  return door belongs where that person's loans are managed,
   *  not only on the Lent out list). Refreshes the rollup and
   *  the book's counts from the server's confirmed state. */
  async function onRollupReturn(contact: BorrowerContact, row: Checkout) {
    setRollupBusy(row.id);
    try {
      await returnCheckout(row.id);
      toast(`“${row.item_name}” is back.`, { tone: "success", title: "Borrowing" });
      setExpanded(await getBorrowerRollup(contact.id));
      load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That didn't work. Try again.", {
        tone: "danger",
      });
    } finally {
      setRollupBusy(null);
    }
  }

  async function onDelete(contact: BorrowerContact) {
    if (
      !window.confirm(
        `Remove “${contact.name}” from your address book? Their lending history stays exactly as it is — only the book entry goes.`,
      )
    )
      return;
    try {
      await deleteBorrower(contact.id);
      if (expanded?.contact.id === contact.id) setExpanded(null);
      toast("Borrower removed from the book.", { tone: "success" });
      load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't remove them.", {
        tone: "danger",
      });
    }
  }

  return (
    <>
      <Panel title="Add borrower" variant="plate" className="tv-bw-panel">
        <form
          onSubmit={(e) => void onAdd(e)}
          style={{ display: "grid", gap: "0.6rem" }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
              gap: "0.6rem",
            }}
          >
            <FormField label="Name" htmlFor="bw-name">
              <TextInput
                id="bw-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Neighbor Nate"
              />
            </FormField>
            <FormField label="Contact info" htmlFor="bw-contact">
              <TextInput
                id="bw-contact"
                value={contactInfo}
                onChange={(e) => setContactInfo(e.target.value)}
                placeholder="Phone or email"
              />
            </FormField>
          </div>
          <FormField label="Notes (optional)" htmlFor="bw-notes">
            <TextArea
              id="bw-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
            />
          </FormField>
          <div>
            <Button type="submit" loading={busy} disabled={!name.trim()}>
              Add borrower
            </Button>
          </div>
        </form>
      </Panel>
      <Panel title="Borrowers — address book" variant="plate" className="tv-bw-panel">
        <div style={{ display: "grid", gap: "0.8rem" }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            People you lend to, saved once — pick them at check-out
            instead of typing their details every time.
          </p>
          <BorrowerBookTools
            hasContacts={contacts !== null && contacts.length > 0}
            onImported={load}
          />
          {contacts !== null &&
            historyPeople.filter(
              (h) => !contacts.some((c) => c.name.toLowerCase() === h.name.toLowerCase()),
            ).length > 0 && (
              <div style={{ display: "grid", gap: "0.4rem" }}>
                <span style={{ fontWeight: 600 }}>From your lending history</span>
                {historyPeople
                  .filter(
                    (h) => !contacts.some((c) => c.name.toLowerCase() === h.name.toLowerCase()),
                  )
                  .map((h) => (
                    <span key={h.name} style={{ display: "inline-flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
                      <span>
                        {h.name}
                        {h.contact ? ` · ${h.contact}` : ""}
                      </span>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={async () => {
                          try {
                            await createBorrower({ name: h.name, contact: h.contact, notes: "" });
                            toast("Borrower saved to your address book.", { tone: "success" });
                            load();
                          } catch (err) {
                            toast(err instanceof ApiError ? err.message : "Couldn't save that borrower.", { tone: "danger" });
                          }
                        }}
                      >
                        Save to address book
                      </Button>
                    </span>
                  ))}
              </div>
            )}
          {contacts === null ? (
            <Spinner size="sm" />
          ) : contacts.length === 0 ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              {historyPeople.length > 0
                ? "Nobody saved yet — save someone from your lending history above, or add a borrower in the box above."
                : "Nobody saved yet — add your first borrower in the box above."}
            </p>
          ) : (
            <div className="tv-bw-table tv-bw-table--contacts" role="table">
              <TableHead cols={["Name", "Contact", "Out now", "Lends total", null]} />
              {contacts.map((contact) => (
                <div key={contact.id}>
                  <div className="tv-bw-row" role="row">
                    <Cell>
                      <strong>{contact.name}</strong>
                    </Cell>
                    <Cell>{contact.contact || "—"}</Cell>
                    <Cell>
                      <Badge tone={contact.current_holds > 0 ? "accent" : "neutral"} dot>
                        {contact.current_holds} out now
                      </Badge>
                    </Cell>
                    <Cell>
                      {contact.total_lends} lend{contact.total_lends === 1 ? "" : "s"} total
                    </Cell>
                    <div className="tv-bw-actions" role="cell">
                      <BorrowerCardButton contact={contact} />
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={() => void onToggle(contact)}
                      >
                        {expanded?.contact.id === contact.id ? "Hide history" : "History"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="danger"
                        onClick={() => void onDelete(contact)}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                  {expanded?.contact.id === contact.id && (
                    <div className="tv-bw-detail">
                      {/* The contact's own notes live INSIDE
                          their entry (owner, 2026-11-12: notes
                          never ride a list face) — the book's
                          table no longer carries them, so they
                          are read here, over their loans. */}
                      {expanded.contact.notes && (
                        <>
                          <p className="tv-bw-detail-label">Notes:</p>
                          <p className="tv-bw-muted">{expanded.contact.notes}</p>
                        </>
                      )}
                      {expanded.history.length === 0 ? (
                        <span style={{ color: "var(--text-muted)" }}>
                          No lends linked to this contact yet — pick them
                          at check-out and their lends gather here.
                        </span>
                      ) : (
                        <>
                          {/* The borrower's own lending surface
                              (sweep B4, F1/F2/F3/F6): what is out
                              with them right now as a TRUE list —
                              each loan's standing as the module's
                              pill, its due line in words, and the
                              return door on the row — over their
                              finished history, a Main list layout
                              list (2026-11-12). (The rollup's
                              history carries every lend; the
                              finished section shows the terminal
                              states, the current section the rest
                              of the story.) */}
                          <p className="tv-bw-detail-label">
                            {t("borrowing.rollup.outNow")}
                          </p>
                          {expanded.current.length === 0 ? (
                            <p className="tv-bw-muted">
                              {t("borrowing.rollup.nothingOut")}
                            </p>
                          ) : (
                            <div className="tv-bw-table tv-bw-table--rollup" role="table">
                              <TableHead cols={["Item", "Out", "Due", "Status", null]} />
                              {expanded.current.map((row) => (
                                <CheckoutRow
                                  key={row.id}
                                  row={row}
                                  actions={
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="secondary"
                                      loading={rollupBusy === row.id}
                                      onClick={() => void onRollupReturn(contact, row)}
                                    >
                                      Mark returned
                                    </Button>
                                  }
                                >
                                  <ItemCell row={row} />
                                  <DatedCell label="Out">
                                    {fullDate(row.checked_out_at)}
                                  </DatedCell>
                                  <DatedCell label="Due">
                                    {row.due_at ? fullDate(row.due_at) : t("borrowing.dueNone")}
                                  </DatedCell>
                                  <Cell>
                                    <Badge tone={STATE_TONES[row.state]}>
                                      {STATE_LABELS[row.state]}
                                    </Badge>
                                  </Cell>
                                </CheckoutRow>
                              ))}
                            </div>
                          )}
                          {expanded.history.some((r) =>
                            ["returned", "declined", "cancelled"].includes(r.state),
                          ) && (
                            <>
                              <p className="tv-bw-detail-label">
                                {t("borrowing.rollup.history")}
                              </p>
                              {/* The same lending history as the
                                  item page's and the History tab's
                                  (owner, 2026-11-12): a Main list
                                  layout list — Item · Checked out ·
                                  Returned. The borrower is this
                                  entry's subject, not a column. */}
                              <LendingHistoryList
                                variant="rollup"
                                rows={expanded.history.filter((r) =>
                                  ["returned", "declined", "cancelled"].includes(r.state),
                                )}
                                emptyText="No finished lends yet."
                                renderItem={(row) => <ItemNameBits row={row} />}
                              />
                            </>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Panel>
    </>
  );
}

function BorrowingContent() {
  const t = useT();
  const { toast } = useToast();
  const { user } = useAuth();
  const { hash } = useLocation();
  const [tab, setTab] = useState<BorrowingTabId>(() =>
    tabFromHash(window.location.hash),
  );

  // The mount read covers fresh arrivals. An in-app link can
  // also change the hash while this page stays mounted — no
  // remount happens, so follow later hash changes too, or the
  // deep link lands on whatever tab was already open (the
  // lane 1 lesson).
  useEffect(() => {
    const wanted = tabFromHash(hash);
    if (wanted !== "lent-out") setTab(wanted);
  }, [hash]);

  const [overview, setOverview] = useState<BorrowingOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [nudgeCopy, setNudgeCopy] = useState<{
    row: Checkout;
    result: NudgeResult;
  } | null>(null);
  const [walkOpen, setWalkOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setOverview(await getBorrowingOverview());
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load your lending.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Notification click-through landing (owner spec 2026-10-25):
  // ?checkout=<id> scrolls to that lend's row and flashes it
  // once the overview lands. A lend that has left the lists
  // (or never existed) simply never matches — the page stands
  // as-is, no error, no dead end. Under the tab layout the row
  // lives on exactly one tab (finished lends on History, every
  // live list on Lent out), so the landing first selects that
  // tab, then scrolls once the row is actually mounted.
  const [searchParams] = useSearchParams();
  const checkoutParam = searchParams.get("checkout");
  // Borrower landing (2026-11-12): a lending-history borrower
  // link points at ?borrower=<contact id> — land on the Address
  // book tab; BorrowersPanel expands that contact's entry.
  const borrowerParam = searchParams.get("borrower");
  useEffect(() => {
    if (borrowerParam) setTab("address-book");
  }, [borrowerParam]);
  const [flashId, setFlashId] = useState<string | null>(null);
  const landedCheckout = useRef<string | null>(null);
  useEffect(() => {
    if (!checkoutParam || overview === null) return;
    if (landedCheckout.current === checkoutParam) return;
    const inHistory = overview.history.some((r) => r.id === checkoutParam);
    const inLive =
      overview.lent_out.some((r) => r.id === checkoutParam) ||
      overview.requests_for_me.some((r) => r.id === checkoutParam) ||
      overview.my_requests.some((r) => r.id === checkoutParam) ||
      overview.borrowed_by_me.some((r) => r.id === checkoutParam);
    if (!inHistory && !inLive) return;
    const home: BorrowingTabId = inHistory ? "history" : "lent-out";
    if (tab !== home) {
      setTab(home);
      return;
    }
    const el = document.getElementById(`checkout-${checkoutParam}`);
    if (!el) return;
    landedCheckout.current = checkoutParam;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    setFlashId(checkoutParam);
    const tId = window.setTimeout(() => setFlashId(null), 2600);
    return () => window.clearTimeout(tId);
  }, [checkoutParam, overview, tab]);

  async function act(
    row: Checkout,
    action: "approve" | "decline" | "cancel" | "return",
  ) {
    setBusy(row.id);
    try {
      if (action === "approve") await approveCheckout(row.id);
      else if (action === "decline") await declineCheckout(row.id);
      else if (action === "cancel") await cancelCheckout(row.id);
      else await returnCheckout(row.id);
      toast(
        action === "approve"
          ? `“${row.item_name}” is checked out to ${row.borrower_name}.`
          : action === "decline"
            ? "Request declined."
            : action === "cancel"
              ? "Request cancelled."
              : `“${row.item_name}” is back.`,
        { tone: "success", title: "Borrowing" },
      );
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "That didn't work. Try again.",
        { tone: "danger" },
      );
    } finally {
      setBusy(null);
    }
  }

  async function onNudge(row: Checkout) {
    setBusy(row.id);
    try {
      const result = await nudgeCheckout(row.id);
      if (result.delivered_via === "message") {
        toast("Nudge sent — it's in your Messages.", {
          tone: "success",
          title: "Borrowing",
        });
      } else {
        setNudgeCopy({ row, result });
      }
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't compose that nudge.",
        { tone: "danger" },
      );
    } finally {
      setBusy(null);
    }
  }

  const counts = overview?.counts;
  // A click-through target row is never filtered out by the
  // overdue toggle — the landing must be able to show it.
  const lentOut = (overview?.lent_out ?? []).filter(
    (r) => !overdueOnly || r.overdue || r.id === checkoutParam,
  );
  const borrowedByMe = (overview?.borrowed_by_me ?? []).filter(
    (r) => !overdueOnly || r.overdue || r.id === checkoutParam,
  );
  const allEmpty =
    overview !== null &&
    overview.requests_for_me.length === 0 &&
    overview.my_requests.length === 0 &&
    overview.lent_out.length === 0 &&
    overview.borrowed_by_me.length === 0 &&
    overview.history.length === 0;

  // Header facts (kit anatomy): the old summary badges' counts,
  // carried as standing facts — lent out · requests waiting ·
  // borrowed by me, with overdue joining as a danger badge only
  // while something is actually overdue.
  const facts: SectionPageFact[] | undefined =
    overview && counts
      ? [
          { label: t("borrowing.fact.lentOut"), value: counts.checked_out },
          {
            label: t("borrowing.fact.requestsWaiting"),
            value: counts.pending_requests,
          },
          { label: t("borrowing.fact.borrowedByMe"), value: counts.borrowed },
          ...(counts.overdue > 0
            ? [
                {
                  label: t("borrowing.fact.overdue"),
                  value: (
                    <Badge tone="danger" dot>
                      {counts.overdue}
                    </Badge>
                  ),
                },
              ]
            : []),
        ]
      : undefined;

  const tabLabel = (id: BorrowingTabId) =>
    id === "lent-out"
      ? t("borrowing.tab.lentOut")
      : id === "address-book"
        ? t("borrowing.tab.addressBook")
        : t("borrowing.tab.history");

  const loadingLine = (
    <p
      style={{
        color: "var(--text-muted)",
        display: "flex",
        gap: "var(--space-2)",
        alignItems: "center",
        margin: 0,
      }}
    >
      <Spinner size="sm" /> Loading…
    </p>
  );

  // The Lent out tab — the lending workflow's home: lent out
  // first, then requests waiting on me, my outgoing requests,
  // and what I'm holding (the settled section order). The
  // overdue filter rides here because both lists it filters
  // live on this tab.
  const lentOutTab = (
    <div className="tv-bw-tabgrid">
      {!overview && !loadError && loadingLine}
      {overview && counts && (
        <>
          {shouldOfferCheckout(overview, user?.id ?? null) && (
            <WalkthroughDoor
              title={t("walk.checkout.doorTitle" as never)}
              body={t("walk.checkout.doorBody" as never)}
              onStart={() => setWalkOpen(true)}
              testId="walk-checkout-door"
            />
          )}

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <Checkbox
              label="Overdue only"
              checked={overdueOnly}
              onChange={(e) => setOverdueOnly(e.target.checked)}
            />
          </div>

          {allEmpty && (
            <Panel>
              <EmptyState
                icon={<BrandIcon name="briefcase" size={52} />}
                title="Nothing lent out right now"
                description="Open any tool or battery in Inventory and hit Check out to lend it — or ask a coworker for one of theirs from Shared tools. Everything you lend or borrow will be tracked here."
              />
            </Panel>
          )}

          {lentOut.length > 0 && (
            <Panel title="Lent out" variant="plate" className="tv-bw-panel">
              <div className="tv-bw-table" role="table">
                <TableHead cols={["Item", "Borrower", "Out", "Due", "Status", null]} />
                {lentOut.map((row) => (
                  <CheckoutRow
                    key={row.id}
                    row={row}
                    flash={flashId === row.id}
                    actions={
                      <>
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={busy === row.id}
                          onClick={() => void onNudge(row)}
                        >
                          Nudge
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          loading={busy === row.id}
                          onClick={() => void act(row, "return")}
                        >
                          Mark returned
                        </Button>
                      </>
                    }
                  >
                    <ItemCell row={row} />
                    <Cell>
                      {row.borrower_name}
                      {row.borrower_contact && (
                        <span className="tv-bw-cell-sub">{row.borrower_contact}</span>
                      )}
                    </Cell>
                    <DatedCell label="Out">{fullDate(row.checked_out_at)}</DatedCell>
                    <DatedCell label="Due">
                      {row.due_at ? fullDate(row.due_at) : t("borrowing.dueNone")}
                    </DatedCell>
                    <Cell>
                      <Badge tone={STATE_TONES[row.state]}>{STATE_LABELS[row.state]}</Badge>
                    </Cell>
                  </CheckoutRow>
                ))}
              </div>
            </Panel>
          )}

          {overview.requests_for_me.length > 0 && (
            <Panel title="Requests for me" variant="plate" className="tv-bw-panel">
              <div className="tv-bw-table" role="table">
                <TableHead cols={["Item", "Requester", "Requested", "Due back", "Status", null]} />
                {overview.requests_for_me.map((row) => (
                  <CheckoutRow
                    key={row.id}
                    row={row}
                    flash={flashId === row.id}
                    actions={
                      <>
                        <Button
                          type="button"
                          size="sm"
                          loading={busy === row.id}
                          onClick={() => void act(row, "approve")}
                        >
                          Approve
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={busy === row.id}
                          onClick={() => void act(row, "decline")}
                        >
                          Decline
                        </Button>
                      </>
                    }
                  >
                    <ItemCell row={row} />
                    <Cell>{row.borrower_name}</Cell>
                    <DatedCell label="Requested">{fullDate(row.requested_at)}</DatedCell>
                    <DatedCell label="Due back">
                      {row.due_at ? fullDate(row.due_at) : t("borrowing.dueNone")}
                    </DatedCell>
                    <Cell>
                      <Badge tone={STATE_TONES[row.state]}>{STATE_LABELS[row.state]}</Badge>
                    </Cell>
                  </CheckoutRow>
                ))}
              </div>
            </Panel>
          )}

          {overview.my_requests.length > 0 && (
            <Panel title="My requests" variant="plate" className="tv-bw-panel">
              <div className="tv-bw-table" role="table">
                <TableHead cols={["Item", "Owner", "Requested", "Due back", "Status", null]} />
                {overview.my_requests.map((row) => (
                  <CheckoutRow
                    key={row.id}
                    row={row}
                    flash={flashId === row.id}
                    actions={
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        loading={busy === row.id}
                        onClick={() => void act(row, "cancel")}
                      >
                        Cancel request
                      </Button>
                    }
                  >
                    <ItemCell row={row} />
                    <Cell>{row.owner_name ?? "the owner"}</Cell>
                    <DatedCell label="Requested">{fullDate(row.requested_at)}</DatedCell>
                    <DatedCell label="Due back">
                      {row.due_at ? fullDate(row.due_at) : t("borrowing.dueNone")}
                    </DatedCell>
                    <Cell>
                      <Badge tone={STATE_TONES[row.state]}>{STATE_LABELS[row.state]}</Badge>
                      <span className="tv-bw-cell-sub">Waiting for an answer</span>
                    </Cell>
                  </CheckoutRow>
                ))}
              </div>
            </Panel>
          )}

          {borrowedByMe.length > 0 && (
            <Panel title="Borrowed by me" variant="plate" className="tv-bw-panel">
              <div className="tv-bw-table" role="table">
                <TableHead cols={["Item", "Owner", "Out", "Due", "Status", null]} />
                {borrowedByMe.map((row) => (
                  <CheckoutRow
                    key={row.id}
                    row={row}
                    flash={flashId === row.id}
                    actions={
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        loading={busy === row.id}
                        onClick={() => void act(row, "return")}
                      >
                        Mark returned
                      </Button>
                    }
                  >
                    <ItemCell row={row} />
                    <Cell>{row.owner_name ?? "the owner"}</Cell>
                    <DatedCell label="Out">{fullDate(row.checked_out_at)}</DatedCell>
                    <DatedCell label="Due">
                      {row.due_at ? fullDate(row.due_at) : t("borrowing.dueNone")}
                    </DatedCell>
                    <Cell>
                      <Badge tone={STATE_TONES[row.state]}>{STATE_LABELS[row.state]}</Badge>
                    </Cell>
                  </CheckoutRow>
                ))}
              </div>
            </Panel>
          )}

          {overdueOnly &&
            lentOut.length === 0 &&
            borrowedByMe.length === 0 && (
              <Panel>
                <EmptyState
                  icon={<BrandIcon name="info" size={48} />}
                  title="Nothing overdue"
                  description="Everything that's out is still inside its due date."
                />
              </Panel>
            )}

        </>
      )}
    </div>
  );

  // The History tab — finished lends with their full paper
  // trail. The old stacked page simply omitted the panel when
  // history was empty; a tab must say something, so an empty
  // history gets an empty state in the page's own words.
  const historyTab = (
    <>
      {!overview && !loadError && loadingLine}
      {overview && counts && overview.history.length === 0 && (
        <Panel>
          <EmptyState
            icon={<BrandIcon name="briefcase" size={52} />}
            title="No finished lends yet"
            description="When a lend comes back — or a request is declined or cancelled — it settles here with its full paper trail."
          />
        </Panel>
      )}
      {overview && counts && overview.history.length > 0 && (
        <Panel title="History" variant="plate" className="tv-bw-panel">
          {/* The same lending history as the item page's box
              (owner, 2026-11-12): a Main list layout list — the
              item plus Checked out · Returned · Borrower, the
              borrower a link to that borrower. Rows keep this
              page's two-way click and the ?checkout= flash. */}
          <LendingHistoryList
            variant="page"
            rows={overview.history}
            emptyText="No finished lends yet."
            viewerId={user?.id ?? null}
            rowOpen
            flashId={flashId}
            renderItem={(row) => <ItemNameBits row={row} />}
          />
        </Panel>
      )}
    </>
  );

  const tabs: TabItem[] = [
    { id: "lent-out", label: tabLabel("lent-out"), content: lentOutTab },
    {
      id: "address-book",
      label: tabLabel("address-book"),
      content: (
        <div className="tv-bw-tabgrid">
          <BorrowersPanel expandContactId={borrowerParam} />
        </div>
      ),
    },
    { id: "history", label: tabLabel("history"), content: historyTab },
  ];

  return (
    <div className="tv-stack">
      <SectionPageHeader
        thumb={<ArtIcon name="borrowing" size={96} />}
        title={t("nav.borrowing")}
        subtitle={t("borrowing.subtitle")}
        facts={facts}
        actions={
          <SettingsActionsMenu
            ariaLabel={t("nav.borrowing")}
            buttonLabel={t("inventory.actions")}
            entries={(["lent-out", "address-book", "history"] as const).map(
              (id) => ({
                key: id,
                label: tabLabel(id),
                run: () => setTab(id),
              }),
            )}
          />
        }
      />

      {loadError && <Alert tone="danger">{loadError}</Alert>}

      <Tabs
        tabs={tabs}
        activeId={tab}
        onChange={(id) => setTab(id as BorrowingTabId)}
      />

      <CheckoutWalkthrough
        open={walkOpen}
        onClose={() => setWalkOpen(false)}
        onDone={(checkout) => {
          setWalkOpen(false);
          toast(
            `“${checkout.item_name}” is checked out to ${checkout.borrower_name}.`,
            { tone: "success", title: "Borrowing" },
          );
          void load();
        }}
      />

      <Modal
        open={nudgeCopy !== null}
        onClose={() => setNudgeCopy(null)}
        title={nudgeCopy ? `Nudge ${nudgeCopy.row.borrower_name}` : undefined}
        footer={
          <Button type="button" variant="secondary" onClick={() => setNudgeCopy(null)}>
            Close
          </Button>
        }
      >
        {nudgeCopy && (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              {nudgeCopy.row.borrower_name} isn't linked to a Toolbox
              Vault account we can message — here's the reminder,
              ready to send your usual way:
            </p>
            <div
              style={{
                border: "1px solid var(--edge)",
                borderRadius: "var(--radius)",
                padding: "0.7rem 0.9rem",
                whiteSpace: "pre-wrap",
                overflowWrap: "anywhere",
              }}
            >
              {nudgeCopy.result.message}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <CopyButton text={nudgeCopy.result.message} label="Copy message" />
              {(() => {
                const contact = nudgeCopy.row.borrower_contact || "";
                const email = contact.match(/[\w.+-]+@[\w-]+\.[\w.]+/)?.[0];
                const phone = contact.replace(/[^\d+]/g, "");
                return (
                  <>
                    {phone.length >= 7 && (
                      <>
                        <HrefButton href={`tel:${phone}`} variant="secondary">Call</HrefButton>
                        <HrefButton href={`sms:${phone}?&body=${encodeURIComponent(nudgeCopy.result.message)}`} variant="secondary">Text it</HrefButton>
                      </>
                    )}
                    {email && (
                      <HrefButton href={`mailto:${email}?subject=${encodeURIComponent("Friendly reminder")}&body=${encodeURIComponent(nudgeCopy.result.message)}`} variant="secondary">Email it</HrefButton>
                    )}
                  </>
                );
              })()}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function BorrowingPage() {
  return (
    <RequireAuth>
      <BorrowingContent />
    </RequireAuth>
  );
}
