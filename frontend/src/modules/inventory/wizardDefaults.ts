import type { DictKey } from "../../i18n/dictionaries";

/**
 * Wizard defaults (Wizard Phase 1, 2026-10-25 — Ryan's model):
 * the user's Add wizard setup, held by the ACCOUNT (the
 * `wizard_defaults` JSON document on the user row, migration
 * 0058 — see the migration for why a new column instead of the
 * page-layout or prefs tables). This module owns the document's
 * shape on the client:
 *
 *   sections          — the optional tool sections pre-checked
 *                       on the wizard's "What do you want to
 *                       include?" step (section keys below)
 *   location_id       — the usual storage location, pre-filled
 *                       on the basics step ("" = none)
 *   dealer_company_id — the usual dealer / bought-from company,
 *                       pre-filled the same way ("" = none)
 *
 * A null document (never saved) reads as the SHIPPED defaults:
 * the claim-critical sections pre-checked (sweep B2-F17 — model
 * & serial numbers, photos, receipts: the gaps the Health check
 * otherwise has to nag about after a bare Next-through), no
 * usual values. A saved document — an empty sections list
 * included — is the user's explicit setup and wins on every
 * device: the shipped pre-checks only ever describe a user who
 * has never made the choice themselves.
 */

export interface WizardDefaults {
  sections: string[];
  location_id: string;
  dealer_company_id: string;
}

export const SHIPPED_WIZARD_DEFAULTS: WizardDefaults = {
  // Sweep B2-F17: claim-critical three, pre-checked for a user
  // who has never saved defaults of their own.
  sections: ["numbers", "photos", "receipts"],
  location_id: "",
  dealer_company_id: "",
};

/**
 * The wizard's optional tool sections, in the order their pages
 * run. This registry is the single source for the include step's
 * checkbox column, the Settings defaults page's checkbox column,
 * and the wizard's page order — the three can never drift.
 * (The set-pieces page is NOT here: it is driven by the basics
 * step's is-a-set checkbox, not by an include choice.)
 */
export interface WizardSection {
  key: string;
  labelKey: DictKey;
  hintKey: DictKey;
}

export const WIZARD_SECTIONS: WizardSection[] = [
  { key: "numbers", labelKey: "wizard.section.numbers", hintKey: "wizard.section.numbersHint" },
  { key: "warranty", labelKey: "wizard.section.warranty", hintKey: "wizard.section.warrantyHint" },
  { key: "photos", labelKey: "wizard.section.photos", hintKey: "wizard.section.photosHint" },
  { key: "documents", labelKey: "wizard.section.documents", hintKey: "wizard.section.documentsHint" },
  { key: "receipts", labelKey: "wizard.section.receipts", hintKey: "wizard.section.receiptsHint" },
  { key: "manuals", labelKey: "wizard.section.manuals", hintKey: "wizard.section.manualsHint" },
  { key: "size", labelKey: "wizard.section.size", hintKey: "wizard.section.sizeHint" },
  { key: "tags", labelKey: "wizard.section.tags", hintKey: "wizard.section.tagsHint" },
  { key: "costs", labelKey: "wizard.section.costs", hintKey: "wizard.section.costsHint" },
  { key: "usage", labelKey: "wizard.section.usage", hintKey: "wizard.section.usageHint" },
  { key: "schedule", labelKey: "wizard.section.schedule", hintKey: "wizard.section.scheduleHint" },
  { key: "notes", labelKey: "wizard.section.notes", hintKey: "wizard.section.notesHint" },
  { key: "custom", labelKey: "wizard.section.custom", hintKey: "wizard.section.customHint" },
];

export const WIZARD_SECTION_KEYS = WIZARD_SECTIONS.map((s) => s.key);

/** Read the account's wizard-defaults document into the client
 *  shape. Unknown section keys (saved by a newer client) are
 *  dropped; anything malformed falls back to the shipped
 *  defaults — a saved document can never break the wizard. */
export function parseWizardDefaults(
  raw: Record<string, unknown> | null | undefined,
): WizardDefaults {
  if (!raw || typeof raw !== "object") return { ...SHIPPED_WIZARD_DEFAULTS };
  const sections = Array.isArray(raw.sections)
    ? raw.sections.filter(
        (s): s is string =>
          typeof s === "string" && WIZARD_SECTION_KEYS.includes(s),
      )
    : [];
  return {
    sections,
    location_id: typeof raw.location_id === "string" ? raw.location_id : "",
    dealer_company_id:
      typeof raw.dealer_company_id === "string" ? raw.dealer_company_id : "",
  };
}
