import { useEffect, useRef } from "react";
import { FormField, Select, TextInput } from "../../../components";
import type { DealerCompany } from "../../dealers/types";

/**
 * The warranty field group shared by the tool and battery forms
 * (import + warranty round, 2026-10-25 — Ryan's flow):
 *
 * - TERM is one dropdown on a fixed ladder: 1..11 months, then
 *   1..5 years, then Lifetime. Lifetime sets the record's lifetime
 *   warranty type (no end date, ever) and clears the months; a
 *   stored off-ladder value (e.g. 18 months) shows as its own
 *   option in numeric position — never rounded or dropped.
 * - PROVIDER and CONTACT prefill from the selected dealer
 *   (provider = the dealer's name, contact = the dealer's contact
 *   info) and stay fully editable: buy at a store, warranty through
 *   the manufacturer = type the manufacturer over the prefill.
 *   A field the user has personally typed in is NEVER overwritten;
 *   changing the dealer re-prefills only fields still showing the
 *   previous dealer's values (or still empty).
 */

export interface WarrantyValues {
  warranty_months: string;
  warranty_provider: string;
  warranty_contact: string;
  warranty_terms: string;
  warranty_type: string;
}

export type WarrantyField = keyof WarrantyValues;

const LADDER: { months: number; label: string }[] = [
  ...Array.from({ length: 11 }, (_, i) => ({
    months: i + 1,
    label: i === 0 ? "1 month" : `${i + 1} months`,
  })),
  { months: 12, label: "1 year" },
  { months: 24, label: "2 years" },
  { months: 36, label: "3 years" },
  { months: 48, label: "4 years" },
  { months: 60, label: "5 years" },
];

/** The dealer's contact info as one line for the warranty contact
 *  field: their warranty phone (else customer-service phone, else
 *  first listed phone), then their email. */
export function dealerContactText(company: DealerCompany): string {
  const phone =
    company.warranty_phone ??
    company.customer_service_phone ??
    company.phones?.[0]?.number ??
    "";
  return [phone, company.email ?? ""].filter(Boolean).join(" · ");
}

export function WarrantyFields({
  idPrefix,
  values,
  onChange,
  dealerCompany,
  dealerKnown,
  resetKey,
}: {
  idPrefix: string;
  values: WarrantyValues;
  onChange: (field: WarrantyField, value: string) => void;
  /** The dealer currently picked on the form (null = none). */
  dealerCompany: DealerCompany | null;
  /** True once the dealer picker has reported at least once —
   *  before that the dealer state is unknown and nothing prefills. */
  dealerKnown: boolean;
  /** Changes when the form switches records, resetting the
   *  touched/prefill bookkeeping with the values. */
  resetKey: string;
}) {
  const touchedRef = useRef({ provider: false, contact: false });
  const prefilledRef = useRef({ provider: "", contact: "" });
  const valuesRef = useRef(values);
  valuesRef.current = values;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    touchedRef.current = { provider: false, contact: false };
    prefilledRef.current = { provider: "", contact: "" };
  }, [resetKey]);

  useEffect(() => {
    if (!dealerKnown) return;
    const want = {
      provider: dealerCompany?.name ?? "",
      contact: dealerCompany ? dealerContactText(dealerCompany) : "",
    };
    const fields = [
      ["provider", "warranty_provider"],
      ["contact", "warranty_contact"],
    ] as const;
    for (const [short, field] of fields) {
      if (touchedRef.current[short]) continue;
      const current = valuesRef.current[field];
      if (current === want[short]) {
        // Already showing this dealer's value (stored that way, or
        // prefilled by us): adopt it as the prefill baseline, so a
        // later dealer change may replace it.
        prefilledRef.current[short] = current;
        continue;
      }
      if (current === "" || current === prefilledRef.current[short]) {
        prefilledRef.current[short] = want[short];
        onChangeRef.current(field, want[short]);
      }
      // Otherwise the field holds a value that is neither empty nor
      // a dealer's prefill — the user's own. Never overwrite it.
    }
  }, [dealerCompany, dealerKnown, resetKey]);

  const isLifetime = values.warranty_type === "lifetime";
  const months = values.warranty_months;
  const offLadder =
    !isLifetime &&
    /^\d+$/.test(months) &&
    !LADDER.some((option) => String(option.months) === months);
  const options = [...LADDER];
  if (offLadder) {
    const n = Number(months);
    const at = options.findIndex((option) => option.months > n);
    const entry = { months: n, label: `${n} months` };
    if (at === -1) options.push(entry);
    else options.splice(at, 0, entry);
  }
  const termValue = isLifetime ? "lifetime" : months;

  function handleTerm(next: string) {
    if (next === "lifetime") {
      onChange("warranty_months", "");
      onChange("warranty_type", "lifetime");
      return;
    }
    onChange("warranty_months", next);
    if (values.warranty_type === "lifetime") {
      onChange("warranty_type", next === "" ? "" : "term");
    }
  }

  function handleTyped(field: "warranty_provider" | "warranty_contact", value: string) {
    touchedRef.current[field === "warranty_provider" ? "provider" : "contact"] = true;
    onChange(field, value);
  }

  return (
    <>
      <FormField
        label="Warranty term"
        htmlFor={`${idPrefix}-warranty-term`}
        hint="Pick the length — with a purchase date, the warranty status is worked out automatically. Lifetime never expires."
      >
        <Select
          id={`${idPrefix}-warranty-term`}
          value={termValue}
          onChange={(e) => handleTerm(e.target.value)}
        >
          <option value="">No warranty term</option>
          {options.map((option) => (
            <option key={option.months} value={String(option.months)}>
              {option.label}
            </option>
          ))}
          <option value="lifetime">Lifetime</option>
        </Select>
      </FormField>
      <FormField
        label="Warranty provider"
        htmlFor={`${idPrefix}-warranty-provider`}
        hint="Prefilled with the dealer you bought it from — type over it if the warranty is through someone else, like the manufacturer."
      >
        <TextInput
          id={`${idPrefix}-warranty-provider`}
          value={values.warranty_provider}
          onChange={(e) => handleTyped("warranty_provider", e.target.value)}
        />
      </FormField>
      <FormField
        label="Warranty contact"
        htmlFor={`${idPrefix}-warranty-contact`}
        hint="Prefilled with the dealer's contact info — type over it if claims go somewhere else."
      >
        <TextInput
          id={`${idPrefix}-warranty-contact`}
          value={values.warranty_contact}
          onChange={(e) => handleTyped("warranty_contact", e.target.value)}
        />
      </FormField>
      <FormField label="Warranty terms / notes" htmlFor={`${idPrefix}-warranty-terms`}>
        <TextInput
          id={`${idPrefix}-warranty-terms`}
          value={values.warranty_terms}
          onChange={(e) => onChange("warranty_terms", e.target.value)}
        />
      </FormField>
    </>
  );
}
