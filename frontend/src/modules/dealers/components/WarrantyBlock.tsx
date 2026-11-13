import { Alert, CopyButton } from "../../../components";
import type { DealerCompany } from "../types";

/**
 * The "Warranty service" block on a company page (corporate
 * directory, 2026-10-19). Rendering rules, from the researched
 * data's discipline:
 *  - a ship-to block renders ONLY when the brand officially
 *    publishes a warranty mail-in address; a scoped address always
 *    renders WITH its scope warning, never as a general address;
 *  - gated brands show their gate ("Before you ship: …") and never
 *    an address;
 *  - every phone and the ship-to address carry a one-tap copy
 *    button; the ship-to copies as a clean multi-line mailing
 *    block.
 * Renders nothing when the company carries no warranty data.
 */
export function WarrantyBlock({ company }: { company: DealerCompany }) {
  const process = company.warranty_process;
  const hasShipTo = Boolean(company.ship_to_address);
  const hasContent = Boolean(
    company.warranty_phone ||
      company.customer_service_phone ||
      hasShipTo ||
      process?.gate ||
      (process?.notes.length ?? 0) > 0 ||
      company.warranty_url,
  );
  if (!hasContent) return null;

  const mailingBlock = [company.ship_to_name, company.ship_to_address]
    .filter(Boolean)
    .join("\n");
  const showCs =
    company.customer_service_phone &&
    company.customer_service_phone !== company.warranty_phone;

  return (
    <div style={{ display: "grid", gap: "0.7rem" }}>
      {company.warranty_phone && (
        <p style={{ margin: 0 }}>
          <span style={{ color: "var(--text-muted)" }}>Warranty line: </span>
          <a
            href={`tel:${company.warranty_phone}`}
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {company.warranty_phone}
          </a>{" "}
          <CopyButton text={company.warranty_phone} ariaLabel="Copy warranty phone number" />
        </p>
      )}
      {showCs && (
        <p style={{ margin: 0 }}>
          <span style={{ color: "var(--text-muted)" }}>Customer service: </span>
          <a
            href={`tel:${company.customer_service_phone}`}
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {company.customer_service_phone}
          </a>{" "}
          <CopyButton
            text={company.customer_service_phone as string}
            ariaLabel="Copy customer service phone number"
          />
        </p>
      )}

      {process?.gate && (
        <Alert tone="warning" title="Before you ship">
          {process.gate}
        </Alert>
      )}

      {hasShipTo && (
        <div>
          <p style={{ margin: "0 0 0.3rem", fontWeight: 600 }}>
            Ship warranty returns to{" "}
            <CopyButton text={mailingBlock} label="Copy address" ariaLabel="Copy ship-to address" />
          </p>
          <p style={{ margin: 0, whiteSpace: "pre-line" }}>
            {company.ship_to_name && (
              <>
                {company.ship_to_name}
                {"\n"}
              </>
            )}
            {company.ship_to_address}
          </p>
          {company.ship_to_scope === "scoped" && company.ship_to_scope_note && (
            <div style={{ marginTop: "0.5rem" }}>
              <Alert tone="warning" title="This address is limited">
                {company.ship_to_scope_note}
              </Alert>
            </div>
          )}
        </div>
      )}

      {(process?.notes.length ?? 0) > 0 && (
        <ul style={{ margin: 0, paddingLeft: "1.2rem", display: "grid", gap: "0.3rem" }}>
          {process?.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      {company.warranty_url && (
        <p style={{ margin: 0 }}>
          <a
            href={company.warranty_url}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {company.kind === "retailer" ? "Returns page" : "Warranty page"} ↗
          </a>
        </p>
      )}
    </div>
  );
}

/** True when the company carries anything the warranty block shows. */
export function hasWarrantyData(company: DealerCompany): boolean {
  return Boolean(
    company.warranty_phone ||
      company.customer_service_phone ||
      company.ship_to_address ||
      company.warranty_process?.gate ||
      (company.warranty_process?.notes.length ?? 0) > 0 ||
      company.warranty_url,
  );
}
