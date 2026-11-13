import { useEffect, useMemo, useState } from "react";
import {
  Checkbox,
  DatePicker,
  FormField,
  Radio,
  Select,
  TextArea,
  TextInput,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { createCheckout, getCounterparties, listBorrowers } from "../borrowing/api";
import { dueDateToIso } from "../borrowing/format";
import type {
  BorrowerContact,
  Checkout,
  CheckoutItemKind,
  Counterparty,
} from "../borrowing/types";
import type { CheckoutTarget } from "../borrowing/components/CheckoutModal";
import { WalkthroughFooter, WalkthroughShell } from "./WalkthroughShell";

/**
 * The first-checkout walkthrough (sweep D3): a guided,
 * step-at-a-time pass over the REAL checkout — the same
 * borrower choices, the same due-date rule, and the same
 * createCheckout submit as the CheckoutModal. Nothing here
 * is a slideshow: the final step's button lends the tool
 * for real, through the ledger's own API.
 *
 * Steps: 1 pick the tool · 2 who it's going to · 3 the
 * return-by choice (empty = open-ended, taught in words —
 * the standing due-date rule) · 4 review & lend.
 *
 * Launched from the Borrowing page's door (no tool picked
 * yet — step 1 is a real picker over the vault) or from the
 * checkout modal's one-time offer (the item page's tool
 * rides in as the step-1 pick).
 */

interface PickableItem {
  kind: CheckoutItemKind;
  id: string;
  name: string;
  isSet: boolean;
}

type BorrowerMode = "book" | "person" | "manual";

const TOTAL = 4;

export function CheckoutWalkthrough({
  open,
  initialTarget,
  onClose,
  onDone,
}: {
  open: boolean;
  initialTarget?: CheckoutTarget | null;
  onClose: () => void;
  onDone: (checkout: Checkout) => void;
}) {
  const t = useT();
  const [step, setStep] = useState(0);
  const [items, setItems] = useState<PickableItem[] | null>(null);
  const [pick, setPick] = useState<PickableItem | null>(null);
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

  // Fresh pass every open (the restart-on-exit decision):
  // state resets, the picker's lists reload, and a tool
  // launched from an item page pre-picks step 1.
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setError("");
    setBusy(false);
    setDue("");
    setNotes("");
    setIncludeAddons(true);
    setName("");
    setContact("");
    setBookQuery("");
    setPick(
      initialTarget
        ? {
            kind: initialTarget.kind,
            id: initialTarget.id,
            name: initialTarget.name,
            isSet: Boolean(initialTarget.isSet),
          }
        : null,
    );
    setItems(null);
    Promise.all([
      api<{ id: string; name: string; is_set?: boolean }[]>(
        "/inventory?limit=200",
      ).catch(() => []),
      api<{ id: string; name: string }[]>(
        "/inventory/batteries?limit=1000",
      ).catch(() => []),
    ]).then(([tools, batteries]) => {
      setItems([
        ...tools.map((row) => ({
          kind: "tool" as const,
          id: row.id,
          name: row.name,
          isSet: Boolean(row.is_set),
        })),
        ...batteries.map((row) => ({
          kind: "battery" as const,
          id: row.id,
          name: row.name,
          isSet: false,
        })),
      ]);
    });
    Promise.all([
      getCounterparties().catch(() => [] as Counterparty[]),
      listBorrowers().catch(() => [] as BorrowerContact[]),
    ]).then(([peopleList, bookList]) => {
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
      } else {
        setMode("manual");
      }
    });
  }, [open, initialTarget]);

  const filteredBook = useMemo(() => {
    if (book === null) return [];
    const q = bookQuery.trim().toLowerCase();
    if (!q) return book;
    return book.filter((b) =>
      `${b.name} ${b.contact}`.toLowerCase().includes(q),
    );
  }, [book, bookQuery]);

  const pickedContact = book?.find((b) => b.id === bookPick) ?? null;
  const borrowerSummary =
    mode === "book"
      ? (pickedContact?.name ?? "")
      : mode === "person"
        ? (people?.find((p) => p.id === personId)?.name ?? "")
        : name.trim();

  const stepValid =
    step === 0
      ? pick !== null
      : step === 1
        ? mode === "book"
          ? pickedContact !== null
          : mode === "person"
            ? personId !== ""
            : name.trim() !== ""
        : true;

  async function submit() {
    if (!pick) return;
    setError("");
    setBusy(true);
    try {
      const checkout = await createCheckout({
        item_kind: pick.kind,
        item_id: pick.id,
        borrower_user_id: mode === "person" ? personId : null,
        borrower_name: mode === "manual" ? name.trim() : null,
        borrower_contact: mode === "manual" ? contact.trim() : "",
        borrower_contact_id: mode === "book" ? bookPick : null,
        due_at: dueDateToIso(due),
        notes: notes.trim(),
        include_addons: pick.isSet ? includeAddons : undefined,
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

  const footer = (
    <WalkthroughFooter
      onBack={step > 0 ? () => setStep(step - 1) : undefined}
      onExit={onClose}
      onSkip={step === 2 ? () => setStep(3) : undefined}
      onContinue={() => {
        if (step < TOTAL - 1) setStep(step + 1);
        else void submit();
      }}
      continueLabel={
        step < TOTAL - 1
          ? t("walk.continue" as never)
          : t("borrowing.checkout.submit")
      }
      continueDisabled={!stepValid}
      busy={busy}
    />
  );

  return (
    <WalkthroughShell
      open={open}
      title={t("walk.checkout.title" as never)}
      stepIndex={step}
      totalSteps={TOTAL}
      onExit={onClose}
      footer={footer}
    >
      {step === 0 && (
        <div className="tv-setup-step">
          <h2>{t("walk.checkout.s1.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.checkout.s1.intro" as never)}</p>
          {items === null ? (
            <p className="tv-walk-muted">{t("walk.loading" as never)}</p>
          ) : items.length === 0 && !pick ? (
            <p className="tv-walk-muted">{t("walk.checkout.s1.empty" as never)}</p>
          ) : (
            <div className="tv-walk-picklist" role="listbox">
              {(items ?? []).map((item) => (
                <button
                  key={`${item.kind}:${item.id}`}
                  type="button"
                  role="option"
                  aria-selected={pick?.id === item.id && pick?.kind === item.kind}
                  className={
                    pick?.id === item.id && pick?.kind === item.kind
                      ? "tv-walk-pickrow is-picked"
                      : "tv-walk-pickrow"
                  }
                  onClick={() => setPick(item)}
                >
                  <span className="tv-walk-pickrow-name">{item.name}</span>
                  <span className="tv-walk-pickrow-sub">
                    {t(
                      (item.kind === "battery"
                        ? "walk.kind.battery"
                        : item.isSet
                          ? "walk.kind.set"
                          : "walk.kind.tool") as never,
                    )}
                  </span>
                </button>
              ))}
              {pick && !(items ?? []).some((i) => i.id === pick.id && i.kind === pick.kind) && (
                <button
                  type="button"
                  role="option"
                  aria-selected
                  className="tv-walk-pickrow is-picked"
                >
                  <span className="tv-walk-pickrow-name">{pick.name}</span>
                  <span className="tv-walk-pickrow-sub">
                    {t("walk.kind.tool" as never)}
                  </span>
                </button>
              )}
            </div>
          )}
          {pick === null && items !== null && items.length > 0 && (
            <p className="tv-setup-hint">{t("walk.pickFirst" as never)}</p>
          )}
        </div>
      )}

      {step === 1 && (
        <div className="tv-setup-step">
          <h2>{t("walk.checkout.s2.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.checkout.s2.intro" as never)}</p>
          <div className="tv-setup-form">
            <div>
              <Radio
                name="walk-checkout-borrower-mode"
                value="book"
                label={t("borrowing.checkout.modeBook")}
                checked={mode === "book"}
                onChange={() => setMode("book")}
              />
              <Radio
                name="walk-checkout-borrower-mode"
                value="person"
                label={t("borrowing.checkout.modePerson")}
                checked={mode === "person"}
                disabled={people !== null && people.length === 0}
                onChange={() => setMode("person")}
              />
              <Radio
                name="walk-checkout-borrower-mode"
                value="manual"
                label={t("borrowing.checkout.modeManual")}
                checked={mode === "manual"}
                onChange={() => setMode("manual")}
              />
            </div>

            {mode === "book" ? (
              book === null ? (
                <p className="tv-walk-muted">
                  {t("borrowing.checkout.bookLoading")}
                </p>
              ) : book.length === 0 ? (
                <p className="tv-walk-muted">
                  {t("borrowing.checkout.bookEmpty")}
                </p>
              ) : (
                <>
                  <FormField
                    label={t("borrowing.checkout.bookSearchLabel")}
                    htmlFor="walk-co-book-search"
                  >
                    <TextInput
                      id="walk-co-book-search"
                      value={bookQuery}
                      onChange={(e) => setBookQuery(e.target.value)}
                      placeholder={t("borrowing.checkout.bookSearchPlaceholder")}
                    />
                  </FormField>
                  {filteredBook.length === 0 ? (
                    <p className="tv-walk-muted">
                      {t("borrowing.checkout.bookNoMatch")}
                    </p>
                  ) : (
                    <div className="tv-walk-picklist" role="listbox">
                      {filteredBook.map((b) => (
                        <button
                          key={b.id}
                          type="button"
                          role="option"
                          aria-selected={b.id === bookPick}
                          className={
                            b.id === bookPick
                              ? "tv-walk-pickrow is-picked"
                              : "tv-walk-pickrow"
                          }
                          onClick={() => setBookPick(b.id)}
                        >
                          <span className="tv-walk-pickrow-name">{b.name}</span>
                          {b.contact && (
                            <span className="tv-walk-pickrow-sub">{b.contact}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )
            ) : mode === "person" ? (
              people === null ? (
                <p className="tv-walk-muted">
                  {t("borrowing.checkout.peopleLoading")}
                </p>
              ) : people.length === 0 ? (
                <p className="tv-walk-muted">
                  {t("borrowing.checkout.peopleEmpty")}
                </p>
              ) : (
                <FormField
                  label={t("borrowing.checkout.lendingTo")}
                  htmlFor="walk-co-person"
                >
                  <Select
                    id="walk-co-person"
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
              <>
                <FormField
                  label={t("borrowing.checkout.nameLabel")}
                  htmlFor="walk-co-name"
                >
                  <TextInput
                    id="walk-co-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("borrowing.checkout.namePlaceholder")}
                  />
                </FormField>
                <FormField
                  label={t("borrowing.checkout.contactLabel")}
                  htmlFor="walk-co-contact"
                >
                  <TextInput
                    id="walk-co-contact"
                    value={contact}
                    onChange={(e) => setContact(e.target.value)}
                    placeholder={t("borrowing.checkout.contactPlaceholder")}
                  />
                </FormField>
              </>
            )}
          </div>
          <div className="tv-setup-example">
            <span className="tv-setup-example-label">
              {t("setup.example.label" as never)}
            </span>
            <p>{t("walk.checkout.s2.example" as never)}</p>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="tv-setup-step">
          <h2>{t("walk.checkout.s3.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.checkout.s3.intro" as never)}</p>
          <div className="tv-setup-form">
            <FormField label={t("borrowing.checkout.dueLabel")} htmlFor="walk-co-due">
              <DatePicker id="walk-co-due" value={due} onChange={setDue} clearable />
            </FormField>
            <FormField label={t("borrowing.checkout.notesLabel")} htmlFor="walk-co-notes">
              <TextArea
                id="walk-co-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t("borrowing.checkout.notesPlaceholder")}
                rows={2}
              />
            </FormField>
            {pick?.isSet && (
              <Checkbox
                name="walk-co-include-addons"
                label={t("borrowing.checkout.addonsLabel")}
                checked={includeAddons}
                onChange={(e) => setIncludeAddons(e.target.checked)}
              />
            )}
          </div>
          <div className="tv-setup-example">
            <span className="tv-setup-example-label">
              {t("setup.example.label" as never)}
            </span>
            <p>{t("walk.checkout.s3.example" as never)}</p>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="tv-setup-step">
          <h2>{t("walk.checkout.s4.title" as never)}</h2>
          <p className="tv-setup-intro">{t("walk.checkout.s4.intro" as never)}</p>
          <div className="tv-walk-review">
            <div className="tv-walk-review-row">
              <span className="tv-walk-review-label">
                {t("walk.review.tool" as never)}
              </span>
              <span className="tv-walk-review-value">{pick?.name ?? "—"}</span>
            </div>
            <div className="tv-walk-review-row">
              <span className="tv-walk-review-label">
                {t("walk.review.borrower" as never)}
              </span>
              <span className="tv-walk-review-value">{borrowerSummary || "—"}</span>
            </div>
            <div className="tv-walk-review-row">
              <span className="tv-walk-review-label">
                {t("walk.review.due" as never)}
              </span>
              <span className="tv-walk-review-value">
                {due || t("borrowing.dueNone")}
              </span>
            </div>
            {notes.trim() && (
              <div className="tv-walk-review-row">
                <span className="tv-walk-review-label">
                  {t("walk.review.notes" as never)}
                </span>
                <span className="tv-walk-review-value">{notes.trim()}</span>
              </div>
            )}
          </div>
          {error && (
            <p role="alert" className="tv-walk-error">
              {error}
            </p>
          )}
        </div>
      )}
    </WalkthroughShell>
  );
}
