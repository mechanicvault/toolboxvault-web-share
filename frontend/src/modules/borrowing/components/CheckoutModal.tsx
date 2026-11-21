import { useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Checkbox,
  DatePicker,
  FormField,
  Modal,
  Radio,
  Select,
  TextArea,
  TextInput,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../core/AuthContext";
import {
  CheckoutWalkthrough,
} from "../../walkthroughs/CheckoutWalkthrough";
import { shouldOfferCheckout } from "../../walkthroughs/logic";
import { WalkthroughOffer } from "../../walkthroughs/WalkthroughShell";
import {
  createCheckout,
  getBorrowingOverview,
  getCounterparties,
  listBorrowers,
} from "../api";
import { dueDateToIso } from "../format";
import type {
  BorrowerContact,
  Checkout,
  CheckoutItemKind,
  Counterparty,
} from "../types";
import "../borrowing.css";

/** The item being lent — enough for the modal to name it and post
 *  the checkout. */
export interface CheckoutTarget {
  kind: CheckoutItemKind;
  id: string;
  name: string;
  /** Sets prompt "include addon pieces?" at checkout (owner's set
   *  model): the lend then covers the set + its attached addon
   *  tools as one bundle. */
  isSet?: boolean;
}

type BorrowerMode = "book" | "person" | "manual";

/**
 * Owner-initiated check-out: lend one of my items right now.
 *
 * The borrower is picked ONE of three ways, as an explicit radio
 * choice at the top of the modal:
 *
 * - ADDRESS BOOK ("book") — one of the owner's saved borrower
 *   contacts, picked from a searchable list. The lend sends only
 *   the contact id: the server stamps the link on the ledger row
 *   and snapshots the name/contact FROM the book, so the loan
 *   rolls up under that person (their holds, history, and the
 *   nudge's account link) and the linked name can never drift
 *   from the link.
 * - LINKED PERSON ("person") — someone connected by an accepted
 *   peer-sharing grant (they get an account-side "Borrowed by me"
 *   entry and return notifications).
 * - NAME & CONTACT ("manual") — a free-typed name (+ optional
 *   contact) for people in neither list; the established manual
 *   path, unchanged.
 *
 * Due date and notes are optional; the lend starts immediately
 * (no request/approval dance — the handover is in person by
 * construction). This modal is the ONE borrower-choice control:
 * every owner check-out entry point (item pages, inventory list
 * rows and tiles, set lends) mounts it.
 */
export function CheckoutModal({
  target,
  onClose,
  onDone,
}: {
  target: CheckoutTarget | null;
  onClose: () => void;
  onDone: (checkout: Checkout) => void;
}) {
  const t = useT();
  const [people, setPeople] = useState<Counterparty[] | null>(null);
  const [book, setBook] = useState<BorrowerContact[] | null>(null);
  const [mode, setMode] = useState<BorrowerMode>("manual");
  const [personId, setPersonId] = useState("");
  const [bookPick, setBookPick] = useState("");
  const [bookQuery, setBookQuery] = useState("");
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [due, setDue] = useState("");
  const [notes, setNotes] = useState("");
  const [includeAddons, setIncludeAddons] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // The walkthrough's one-time offer (sweep D3): while the
  // ledger itself says this user has never lent, the modal
  // offers the guided pass. Completion is read from the real
  // overview — no dismiss flag — so the offer retires itself
  // the moment a first lend lands, however it was made.
  const { user } = useAuth();
  const [walkOffer, setWalkOffer] = useState(false);
  const [walkOpen, setWalkOpen] = useState(false);
  useEffect(() => {
    if (!target) {
      setWalkOffer(false);
      setWalkOpen(false);
      return;
    }
    let cancelled = false;
    getBorrowingOverview()
      .then((overview) => {
        if (!cancelled)
          setWalkOffer(shouldOfferCheckout(overview, user?.id ?? null));
      })
      .catch(() => {
        if (!cancelled) setWalkOffer(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target, user?.id]);

  // Fresh form every time the modal opens for an item. Both
  // borrower lists load together; a failure just empties that
  // list (the other choices still work). The default mode leads
  // with the address book when it has anyone — the pick the owner
  // asked for — then linked people, then type-a-name.
  //
  // Initialization runs ONCE per (item, open session): some
  // hosts build their target object inline on every render (the
  // item page's lending panel), so keying on the object's
  // identity would refetch — and reset a half-filled form — on
  // every parent re-render. Closing the modal (target → null)
  // re-arms the guard for the next open.
  const initKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!target) {
      initKeyRef.current = null;
      return;
    }
    const key = `${target.kind}:${target.id}`;
    if (initKeyRef.current === key) return;
    initKeyRef.current = key;
    setPeople(null);
    setBook(null);
    setMode("manual");
    setPersonId("");
    setBookPick("");
    setBookQuery("");
    setName("");
    setContact("");
    setDue("");
    setNotes("");
    setIncludeAddons(true);
    setError("");
    setBusy(false);
    Promise.all([
      getCounterparties().catch(() => [] as Counterparty[]),
      listBorrowers().catch(() => [] as BorrowerContact[]),
    ]).then(([peopleList, bookList]) => {
      // The picker reads alphabetically by first name (owner,
      // 2026-11-04): sort once on load so the rows, the search
      // filter (which preserves order) and the default pick all
      // follow the same A→Z order.
      const sortedBook = [...bookList].sort((a, b) =>
        a.name
          .trim()
          .localeCompare(b.name.trim(), undefined, { sensitivity: "base" }),
      );
      setPeople(peopleList);
      setBook(sortedBook);
      if (sortedBook.length > 0) {
        setMode("book");
        setBookPick(sortedBook[0].id);
      } else if (peopleList.length > 0) {
        setMode("person");
        setPersonId(peopleList[0].id);
      }
    });
  }, [target]);

  const filteredBook = useMemo(() => {
    if (book === null) return [];
    const q = bookQuery.trim().toLowerCase();
    if (!q) return book;
    return book.filter((b) =>
      `${b.name} ${b.contact}`.toLowerCase().includes(q),
    );
  }, [book, bookQuery]);

  const pickedContact =
    book?.find((b) => b.id === bookPick) ?? null;

  async function submit() {
    if (!target) return;
    setError("");
    if (mode === "book" && !pickedContact) {
      setError(t("borrowing.checkout.errPickBook"));
      return;
    }
    if (mode === "person" && !personId) {
      setError(t("borrowing.checkout.errPickPerson"));
      return;
    }
    if (mode === "manual" && !name.trim()) {
      setError(t("borrowing.checkout.errName"));
      return;
    }
    setBusy(true);
    try {
      const checkout = await createCheckout({
        item_kind: target.kind,
        item_id: target.id,
        borrower_user_id: mode === "person" ? personId : null,
        // Book picks send NO name/contact: the server snapshots
        // them from the book entry the id names.
        borrower_name: mode === "manual" ? name.trim() : null,
        borrower_contact: mode === "manual" ? contact.trim() : "",
        borrower_contact_id: mode === "book" ? bookPick : null,
        due_at: dueDateToIso(due),
        notes: notes.trim(),
        include_addons: target.isSet ? includeAddons : undefined,
      });
      onDone(checkout);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("borrowing.checkout.errGeneric"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <Modal
      open={target !== null}
      onClose={onClose}
      title={
        target
          ? t("borrowing.checkout.title").replace("{name}", target.name)
          : undefined
      }
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("borrowing.checkout.cancel")}
          </Button>
          <Button type="button" loading={busy} onClick={() => void submit()}>
            {t("borrowing.checkout.submit")}
          </Button>
        </>
      }
    >
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        {walkOffer && (
          <WalkthroughOffer
            body={t("walk.checkout.offer" as never)}
            onStart={() => setWalkOpen(true)}
            testId="walk-checkout-offer"
          />
        )}
        <div style={{ display: "grid", gap: "0.4rem" }}>
          <Radio
            name="checkout-borrower-mode"
            value="book"
            label={t("borrowing.checkout.modeBook")}
            checked={mode === "book"}
            onChange={() => setMode("book")}
          />
          <Radio
            name="checkout-borrower-mode"
            value="person"
            label={t("borrowing.checkout.modePerson")}
            checked={mode === "person"}
            disabled={people !== null && people.length === 0}
            onChange={() => setMode("person")}
          />
          <Radio
            name="checkout-borrower-mode"
            value="manual"
            label={t("borrowing.checkout.modeManual")}
            checked={mode === "manual"}
            onChange={() => setMode("manual")}
          />
        </div>

        {mode === "book" ? (
          book === null ? (
            <p className="tv-bw-muted">{t("borrowing.checkout.bookLoading")}</p>
          ) : book.length === 0 ? (
            <p className="tv-bw-muted">{t("borrowing.checkout.bookEmpty")}</p>
          ) : (
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              <FormField
                label={t("borrowing.checkout.bookSearchLabel")}
                htmlFor="co-book-search"
              >
                <TextInput
                  id="co-book-search"
                  value={bookQuery}
                  onChange={(e) => setBookQuery(e.target.value)}
                  placeholder={t("borrowing.checkout.bookSearchPlaceholder")}
                />
              </FormField>
              {filteredBook.length === 0 ? (
                <p className="tv-bw-muted">
                  {t("borrowing.checkout.bookNoMatch")}
                </p>
              ) : (
                <div className="tv-bw-book-list" role="listbox">
                  {filteredBook.map((b) => (
                    <button
                      key={b.id}
                      type="button"
                      role="option"
                      aria-selected={b.id === bookPick}
                      className={
                        b.id === bookPick
                          ? "tv-bw-book-row tv-bw-book-row--picked"
                          : "tv-bw-book-row"
                      }
                      onClick={() => setBookPick(b.id)}
                    >
                      <span className="tv-bw-book-name">{b.name}</span>
                    </button>
                  ))}
                </div>
              )}
              {pickedContact && (
                <p className="tv-bw-book-sub">
                  {t("borrowing.checkout.lendingTo")}: {pickedContact.name}
                  {pickedContact.contact
                    ? ` · ${pickedContact.contact}`
                    : ""}
                </p>
              )}
            </div>
          )
        ) : mode === "person" ? (
          people === null ? (
            <p className="tv-bw-muted">
              {t("borrowing.checkout.peopleLoading")}
            </p>
          ) : people.length === 0 ? (
            <p className="tv-bw-muted">{t("borrowing.checkout.peopleEmpty")}</p>
          ) : (
            <FormField
              label={t("borrowing.checkout.lendingTo")}
              htmlFor="co-person"
            >
              <Select
                id="co-person"
                value={personId}
                onChange={(e) => setPersonId(e.target.value)}
              >
                {people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.account_number}
                  </option>
                ))}
              </Select>
            </FormField>
          )
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
              gap: "var(--space-3)",
            }}
          >
            <FormField
              label={t("borrowing.checkout.nameLabel")}
              htmlFor="co-name"
            >
              <TextInput
                id="co-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("borrowing.checkout.namePlaceholder")}
              />
            </FormField>
            <FormField
              label={t("borrowing.checkout.contactLabel")}
              htmlFor="co-contact"
            >
              <TextInput
                id="co-contact"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                placeholder={t("borrowing.checkout.contactPlaceholder")}
              />
            </FormField>
          </div>
        )}

        {target?.isSet && (
          <div style={{ display: "grid", gap: "0.3rem" }}>
            <Checkbox
              name="co-include-addons"
              label={t("borrowing.checkout.addonsLabel")}
              checked={includeAddons}
              onChange={(e) => setIncludeAddons(e.target.checked)}
            />
            <p className="tv-bw-help">{t("borrowing.checkout.addonsHelp")}</p>
          </div>
        )}

        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
            gap: "var(--space-3)",
          }}
        >
          <FormField label={t("borrowing.checkout.dueLabel")} htmlFor="co-due">
            <DatePicker
              id="co-due"
              value={due}
              onChange={setDue}
              clearable
            />
          </FormField>
        </div>
        <FormField label={t("borrowing.checkout.notesLabel")} htmlFor="co-notes">
          <TextArea
            id="co-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t("borrowing.checkout.notesPlaceholder")}
            rows={2}
          />
        </FormField>

        {error && (
          <p role="alert" style={{ color: "var(--danger)", margin: 0 }}>
            {error}
          </p>
        )}
      </div>
    </Modal>
    <CheckoutWalkthrough
      open={walkOpen}
      initialTarget={target}
      onClose={() => setWalkOpen(false)}
      onDone={(checkout) => {
        setWalkOpen(false);
        onDone(checkout);
      }}
    />
    </>
  );
}
