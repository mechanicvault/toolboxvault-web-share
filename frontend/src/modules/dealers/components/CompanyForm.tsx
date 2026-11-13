import { useState, type CSSProperties, type FormEvent } from "react";
import {
  Alert,
  Button,
  FormField,
  formGridStyle,
  Select,
  TextArea,
  TextInput,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { ApiError } from "../../../lib/api";
import type { DealerCompany, DealerCompanyWrite, DealerPhone } from "../types";

export const EMPTY_COMPANY: DealerCompanyWrite = {
  name: "",
  email: "",
  website: "",
  address: "",
  phones: [],
  notes: "",
  kind: "manufacturer",
  warranty_url: "",
  warranty_phone: null,
  ship_to_name: null,
  ship_to_address: null,
  ship_to_scope: null,
  ship_to_scope_note: null,
  warranty_process: null,
  logo_key: null,
  logo_tile: null,
};

export function companyToWrite(company: DealerCompany): DealerCompanyWrite {
  return {
    name: company.name,
    email: company.email,
    website: company.website,
    address: company.address,
    phones: company.phones.map((p) => ({ ...p })),
    notes: company.notes,
    kind: company.kind,
    warranty_url: company.warranty_url,
    warranty_phone: company.warranty_phone,
    ship_to_name: company.ship_to_name,
    ship_to_address: company.ship_to_address,
    ship_to_scope: company.ship_to_scope,
    ship_to_scope_note: company.ship_to_scope_note,
    warranty_process: company.warranty_process
      ? {
          gate: company.warranty_process.gate,
          notes: [...company.warranty_process.notes],
        }
      : null,
    logo_key: company.logo_key,
    logo_tile: company.logo_tile,
  };
}

export const PHONE_LABELS = ["Customer Service", "Technical Service", "Billing", "General"];

// Personal-mode chrome (2026-11-05), by reference on purpose:
// the build's inline-style ratchet counts literal style objects,
// and these two mirror the warranty fieldset's own frame.
const PERSONAL_FIELDSET_STYLE: CSSProperties = {
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  padding: "0.9rem",
  display: "grid",
  gap: "var(--space-3)",
  margin: 0,
};

const PERSONAL_LEGEND_STYLE: CSSProperties = {
  fontWeight: 600,
  padding: "0 0.4rem",
};

const PERSONAL_NOTE_STYLE: CSSProperties = {
  color: "var(--text-muted)",
  margin: 0,
  fontSize: "0.92rem",
};

/** Company editor shared by the user's private companies and the
 *  operator's directory management: identity fields + a phones list
 *  (department label + number rows).
 *
 *  `personal` (2026-11-05): the same editor saving the viewer's
 *  PERSONAL layer over a directory dealer. The corporate warranty
 *  fieldset is directory data and disappears — except the logo
 *  pair, which is part of the dealer's identity the viewer sees —
 *  and the form carries the plain-words note that these details
 *  are his alone. `onReset` (offered only when a personal layer
 *  exists) renders the "Use the directory details" action; the
 *  page owns the confirm + the call. */
export function CompanyForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  personal = false,
  onReset,
}: {
  initial: DealerCompanyWrite;
  submitLabel: string;
  onSubmit: (body: DealerCompanyWrite) => Promise<void>;
  onCancel?: () => void;
  personal?: boolean;
  onReset?: () => void;
}) {
  const t = useT();
  const [values, setValues] = useState<DealerCompanyWrite>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function setPhone(index: number, patch: Partial<DealerPhone>) {
    setValues((v) => ({
      ...v,
      phones: v.phones.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!values.name.trim()) {
      setError("Give the company a name.");
      return;
    }
    setBusy(true);
    try {
      await onSubmit({
        ...values,
        name: values.name.trim(),
        phones: values.phones.filter((p) => p.number.trim()),
        warranty_phone: values.warranty_phone?.trim() || null,
        ship_to_name: values.ship_to_name?.trim() || null,
        ship_to_address: values.ship_to_address?.trim() || null,
        ship_to_scope_note: values.ship_to_scope_note?.trim() || null,
        logo_key: values.logo_key?.trim() || null,
        warranty_process: (() => {
          const gateClean = gateText.trim() || null;
          const notesClean = notesText
            .split("\n")
            .map((n) => n.trim())
            .filter(Boolean);
          return gateClean || notesClean.length
            ? { gate: gateClean, notes: notesClean }
            : null;
        })(),
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the company.");
    } finally {
      setBusy(false);
    }
  }

  // Gate + process notes edit as raw text (parsed on submit, so
  // typing line breaks in the notes box behaves normally).
  const [gateText, setGateText] = useState(initial.warranty_process?.gate ?? "");
  const [notesText, setNotesText] = useState(
    (initial.warranty_process?.notes ?? []).join("\n"),
  );

  // The logo pair renders inside the warranty fieldset normally,
  // and on its own in personal mode (the logo is part of the
  // dealer's identity the viewer sees; the rest of the fieldset
  // is corporate directory data).
  const logoFields = (
    <>
      <FormField label="Logo storage key (blank = text tile)">
        <TextInput
          value={values.logo_key ?? ""}
          onChange={(e) =>
            setValues((v) => ({ ...v, logo_key: e.target.value || null }))
          }
          placeholder="platform/logos/brand.png"
        />
      </FormField>
      <FormField label="Logo tile">
        <Select
          value={values.logo_tile ?? ""}
          onChange={(e) =>
            setValues((v) => ({ ...v, logo_tile: e.target.value || null }))
          }
        >
          <option value="">Standard (neutral)</option>
          <option value="dark">Dark (white-glyph logo)</option>
          <option value="light">Light</option>
        </Select>
      </FormField>
    </>
  );

  return (
    <form onSubmit={(e) => void submit(e)} style={{ display: "grid", gap: "var(--space-3)" }}>
      {personal && (
        <p style={PERSONAL_NOTE_STYLE}>{t("dealers.personal.formNote")}</p>
      )}
      <div style={formGridStyle}>
        <FormField label="Company name" required>
          <TextInput
            value={values.name}
            onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
          />
        </FormField>
        <FormField label="Email">
          <TextInput
            type="email"
            value={values.email}
            onChange={(e) => setValues((v) => ({ ...v, email: e.target.value }))}
          />
        </FormField>
        <FormField label="Website">
          <TextInput
            value={values.website}
            onChange={(e) => setValues((v) => ({ ...v, website: e.target.value }))}
            placeholder="https://…"
          />
        </FormField>
      </div>
      <FormField label="Address">
        <TextArea
          value={values.address}
          onChange={(e) => setValues((v) => ({ ...v, address: e.target.value }))}
          rows={2}
        />
      </FormField>
      <div style={{ display: "grid", gap: "0.5rem" }}>
        <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>Phone numbers</span>
        {values.phones.map((phone, i) => (
          <div key={i} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Select
              value={phone.label}
              onChange={(e) => setPhone(i, { label: e.target.value })}
              aria-label="Phone department"
              style={{ maxWidth: "180px" }}
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
              style={{ flex: "1 1 180px" }}
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                setValues((v) => ({ ...v, phones: v.phones.filter((_, idx) => idx !== i) }))
              }
            >
              Remove
            </Button>
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() =>
              setValues((v) => ({
                ...v,
                phones: [...v.phones, { label: "Customer Service", number: "" }],
              }))
            }
          >
            Add a phone number
          </Button>
        </div>
      </div>
      <FormField label="Notes">
        <TextArea
          value={values.notes}
          onChange={(e) => setValues((v) => ({ ...v, notes: e.target.value }))}
          rows={2}
        />
      </FormField>

      {personal ? (
        <fieldset style={PERSONAL_FIELDSET_STYLE}>
          <legend style={PERSONAL_LEGEND_STYLE}>Logo</legend>
          <div style={formGridStyle}>{logoFields}</div>
        </fieldset>
      ) : (
      <fieldset
        style={{
          border: "1px solid var(--edge)",
          borderRadius: "var(--radius)",
          padding: "0.9rem",
          display: "grid",
          gap: "var(--space-3)",
          margin: 0,
        }}
      >
        <legend style={{ fontWeight: 600, padding: "0 0.4rem" }}>
          Warranty service (corporate directory)
        </legend>
        <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "0.88rem" }}>
          Ship-to is ONLY for an address the brand officially
          publishes for warranty mail-in — never a headquarters or
          contact address. Brands with no mail-in route get a gate
          (the required first step) instead.
        </p>
        <div style={formGridStyle}>
          <FormField label="Kind">
            <Select
              value={values.kind}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  kind: e.target.value as DealerCompanyWrite["kind"],
                }))
              }
            >
              <option value="manufacturer">Manufacturer</option>
              <option value="retailer">Retailer</option>
            </Select>
          </FormField>
          <FormField label="Warranty page URL">
            <TextInput
              value={values.warranty_url}
              onChange={(e) => setValues((v) => ({ ...v, warranty_url: e.target.value }))}
              placeholder="https://…"
            />
          </FormField>
          <FormField label="Warranty phone (only if distinct from customer service)">
            <TextInput
              value={values.warranty_phone ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, warranty_phone: e.target.value || null }))
              }
            />
          </FormField>
          {logoFields}
        </div>
        <div style={formGridStyle}>
          <FormField label="Ship-to name / attention line">
            <TextInput
              value={values.ship_to_name ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, ship_to_name: e.target.value || null }))
              }
            />
          </FormField>
          <FormField label="Ship-to scope">
            <Select
              value={values.ship_to_scope ?? ""}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  ship_to_scope: (e.target.value || null) as DealerCompanyWrite["ship_to_scope"],
                }))
              }
            >
              <option value="">No ship-to address</option>
              <option value="general">General warranty mail-in</option>
              <option value="scoped">Scoped (limited — needs the scope note)</option>
            </Select>
          </FormField>
        </div>
        <FormField label="Ship-to address (one line per row, as it should print on a label)">
          <TextArea
            value={values.ship_to_address ?? ""}
            onChange={(e) =>
              setValues((v) => ({ ...v, ship_to_address: e.target.value || null }))
            }
            rows={3}
          />
        </FormField>
        <FormField label="Scope note (renders WITH a scoped address, always)">
          <TextArea
            value={values.ship_to_scope_note ?? ""}
            onChange={(e) =>
              setValues((v) => ({ ...v, ship_to_scope_note: e.target.value || null }))
            }
            rows={2}
          />
        </FormField>
        <FormField label="Gate (the required first step when there is no mail-in)">
          <TextArea
            value={gateText}
            onChange={(e) => setGateText(e.target.value)}
            rows={2}
            placeholder="e.g. RGA required — call customer care first…"
          />
        </FormField>
        <FormField label="Process notes (one per line)">
          <TextArea
            value={notesText}
            onChange={(e) => setNotesText(e.target.value)}
            rows={3}
          />
        </FormField>
      </fieldset>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Button type="submit" loading={busy}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        {personal && onReset && (
          <Button type="button" variant="danger" onClick={onReset}>
            {t("dealers.personal.reset")}
          </Button>
        )}
      </div>
    </form>
  );
}
