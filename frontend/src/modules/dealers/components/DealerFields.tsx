import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Button,
  FormField,
  Select,
  Spinner,
  TextInput,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { createPrivateCompany, getPickList, useListEntry } from "../api";
import type { DealerCompany, DealerListEntry } from "../types";
import { EMPTY_COMPANY } from "./CompanyForm";

/** The "+ Add a private company" text-button look, shared with
 *  the "Edit my list" link beside it (style by reference — the
 *  inline-style ratchet counts literals only). */
const pickerLinkStyle = {
  background: "none",
  border: "none",
  padding: "0.35rem 0 0",
  color: "var(--accent)",
  cursor: "pointer",
  fontSize: "0.85rem",
  fontWeight: 600,
  textDecoration: "none",
} as const;

const pickErrorStyle = { marginTop: "0.4rem" } as const;

const pickerFooterStyle = {
  display: "flex",
  gap: "1rem",
  flexWrap: "wrap",
  alignItems: "baseline",
} as const;

/**
 * The item dealer picker (dealers module surfaces inside inventory):
 * the user's dealer PICK LIST — directory companies minus the ones
 * they removed from their list, their private companies, and their
 * own list entries (owner directive, 2026-10-31) — plus an inline
 * "add a private company" affordance. Picking a list entry mints
 * the private company from the entry's fields on the spot and
 * selects it; manual entry (the quick-add here, the Add Dealer
 * wizard) is unchanged. The dealer on an item is a TAG — who
 * made/sold this.
 *
 * Removability contract: when the dealers module is off/unassigned
 * the pick-list call 403s and this whole field hides. Callers use
 * `onAvailability` to know whether to include dealer_company_id in
 * their save payload at all — while the module is off the field is
 * ABSENT from the payload, so the stored tag is never cleared by an
 * unrelated edit.
 */
export function DealerPicker({
  id,
  value,
  valueLabel,
  onChange,
  onAvailability,
  onCompany,
  label = "Dealer / brand company",
  hint,
}: {
  id: string;
  value: string;
  /** Display name of the current value, when the caller already
   *  knows it (the edit forms hold the item's dealer_company_name).
   *  Deep audit F1-07: while the companies list is loading the
   *  select must still SHOW the item's real dealer, never fall
   *  back to displaying "No dealer tagged" for a tagged item. */
  valueLabel?: string;
  onChange: (companyId: string) => void;
  onAvailability?: (available: boolean) => void;
  /** The resolved company OBJECT for the current value, fired when
   *  it changes (selection, list load, inline create). Callers that
   *  need more than the id — the item forms prefill the warranty
   *  provider/contact from the dealer's own data — use this. Never
   *  fires while the companies list hasn't answered. */
  onCompany?: (company: DealerCompany | null) => void;
  /** Field caption + helper line; defaults keep the original
   *  wording for existing callers. */
  label?: string;
  hint?: string;
}) {
  const [companies, setCompanies] = useState<DealerCompany[] | null>(null);
  const [entries, setEntries] = useState<DealerListEntry[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState("");
  const [usingEntry, setUsingEntry] = useState(false);
  const [pickError, setPickError] = useState("");

  useEffect(() => {
    // F1-07: the load must RESOLVE or FAIL GRACEFULLY — a hung
    // request used to leave "Loading companies…" spinning forever
    // beside a select that misreported the item's dealer. Ten
    // seconds without an answer is a failure: the field hides
    // (the unavailable path), and onAvailability(false) keeps the
    // stored tag out of the save payload, so nothing is lost.
    let live = true;
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("companies load timed out")), 10000),
    );
    Promise.race([getPickList(), timeout])
      .then((result) => {
        if (!live) return;
        setCompanies(result.companies);
        setEntries(result.entries);
        onAvailability?.(true);
      })
      .catch(() => {
        if (!live) return;
        setUnavailable(true);
        onAvailability?.(false);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // onCompany emission: resolve the current value against the
  // loaded list whenever either moves, and fire only on a real
  // change of the resolved company (the ref holds the last id).
  const emittedCompanyRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (companies === null || !onCompany) return;
    const company = companies.find((c) => c.id === value) ?? null;
    const key = company?.id ?? null;
    if (emittedCompanyRef.current !== key) {
      emittedCompanyRef.current = key;
      onCompany(company);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companies, value]);

  async function addPrivate() {
    if (!newName.trim()) return;
    setAddBusy(true);
    setAddError("");
    try {
      const created = await createPrivateCompany({
        ...EMPTY_COMPANY,
        name: newName.trim(),
      });
      setCompanies((rows) => [...(rows ?? []), created]);
      onChange(created.id);
      setNewName("");
      setAdding(false);
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : "Couldn't add the company.");
    } finally {
      setAddBusy(false);
    }
  }

  /** Picking a list entry: mint its company (once — the backend
   *  returns the same company on later picks), fold it into the
   *  companies list, drop the spent entry, and select the company
   *  like any other pick. A failure leaves the current selection
   *  untouched and says so under the field. */
  async function pickEntry(entryId: string) {
    setUsingEntry(true);
    setPickError("");
    try {
      const company = await useListEntry(entryId);
      setCompanies((rows) =>
        rows?.some((c) => c.id === company.id) ? rows : [...(rows ?? []), company],
      );
      setEntries((rows) => rows.filter((e) => e.id !== entryId));
      onChange(company.id);
    } catch (err) {
      setPickError(
        err instanceof ApiError ? err.message : "Couldn't add that dealer.",
      );
    } finally {
      setUsingEntry(false);
    }
  }

  function handleSelect(next: string) {
    if (next.startsWith("entry:")) {
      void pickEntry(next.slice("entry:".length));
      return;
    }
    onChange(next);
  }

  if (unavailable) return null;
  // No filter box (owner ruling 2026-10-25): most users have only
  // a few dealers, so the full list is the picker — choose one, or
  // add one below. No narrowing means the list can never silently
  // hide or change the current pick either. (The pick list itself
  // is the user's customized one — brands they removed from their
  // list are absent BY THEIR CHOICE, and a current value outside
  // the list still renders via the fallback option below.)
  const directory = (companies ?? []).filter((c) => c.is_directory);
  const mine = (companies ?? []).filter((c) => !c.is_directory);

  return (
    <FormField label={label} htmlFor={id} hint={hint}>
      <Select
        id={id}
        value={value}
        disabled={usingEntry}
        onChange={(e) => handleSelect(e.target.value)}
      >
        <option value="">No dealer tagged</option>
        {value &&
          !(companies ?? []).some((c) => c.id === value) && (
            <option value={value}>{valueLabel || "Selected company"}</option>
          )}
        {directory.length > 0 && (
          <optgroup label="Directory">
            {directory.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </optgroup>
        )}
        {mine.length > 0 && (
          <optgroup label="My companies">
            {mine.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </optgroup>
        )}
        {entries.length > 0 && (
          <optgroup label="My list">
            {entries.map((entry) => (
              <option key={entry.id} value={`entry:${entry.id}`}>
                {entry.name}
              </option>
            ))}
          </optgroup>
        )}
      </Select>
      {pickError && (
        <div style={pickErrorStyle}>
          <Alert tone="danger">{pickError}</Alert>
        </div>
      )}
      {companies === null ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: "0.35rem 0 0" }}>
          <Spinner size="sm" /> Loading companies…
        </p>
      ) : adding ? (
        <div style={{ display: "grid", gap: "0.4rem", marginTop: "0.4rem" }}>
          <TextInput
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New private company name"
            aria-label="New private company name"
          />
          {addError && <Alert tone="danger">{addError}</Alert>}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Button type="button" size="sm" onClick={() => void addPrivate()} loading={addBusy}>
              Add company
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => setAdding(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div style={pickerFooterStyle}>
          <button
            type="button"
            onClick={() => setAdding(true)}
            style={{
              background: "none",
              border: "none",
              padding: "0.35rem 0 0",
              color: "var(--accent)",
              cursor: "pointer",
              fontSize: "0.85rem",
              fontWeight: 600,
            }}
          >
            + Add a private company
          </button>
          <Link to="/settings/dealer-list" style={pickerLinkStyle}>
            Edit my list
          </Link>
        </div>
      )}
    </FormField>
  );
}
