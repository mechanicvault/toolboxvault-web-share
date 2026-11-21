import { CopyButton } from "../../../components";
import { formatPhone, phoneHref } from "../../../lib/format";
import { useT } from "../../../i18n/LocaleContext";
import type { DealerCompany } from "../types";

/** A company's contact facts stack (phones with copy buttons,
 *  email, website, address, and — unless `notes` is false — the
 *  notes prose). Shared by the company page and the Dealers
 *  Side List panel (moved out of DealersPage, 2026-11-13, so
 *  both can import it without a cycle). */
export function CompanyFacts({
  company,
  notes = true,
}: {
  company: DealerCompany;
  /** The directory-notes prose paragraph. On by default (the
   *  company page shows it); a list row or Side List panel
   *  that renders facts passes false so it stays short — the
   *  notes themselves live on the dealer's own page. */
  notes?: boolean;
}) {
  const t = useT();
  return (
    <div className="tv-company-facts">
      {company.phones.map((phone) => (
        <p key={`${phone.label}-${phone.number}`}>
          <span className="tv-fact-label">{phone.label}: </span>
          <a href={`tel:${phoneHref(phone.number)}`} className="tv-fact-strong">
            {formatPhone(phone.number)}
          </a>{" "}
          <CopyButton
            text={phone.number}
            label={t("dealers.facts.copy")}
            ariaLabel={t("dealers.facts.copyPhone").replace("{label}", phone.label)}
          />
        </p>
      ))}
      {company.email && (
        <p>
          <span className="tv-fact-label">{t("dealers.facts.email")}: </span>
          <a href={`mailto:${company.email}`} className="tv-fact-strong">
            {company.email}
          </a>
        </p>
      )}
      {company.website && (
        <p>
          <span className="tv-fact-label">{t("dealers.facts.web")}: </span>
          <a
            href={company.website.startsWith("http") ? company.website : `https://${company.website}`}
            target="_blank"
            rel="noreferrer"
            className="tv-fact-strong"
          >
            {company.website}
          </a>
        </p>
      )}
      {company.address && (
        <p className="tv-company-facts-address">
          {company.address}{" "}
          <CopyButton
            text={company.address}
            label={t("dealers.facts.copyAddress")}
            ariaLabel={t("dealers.facts.copyAddressAria")}
          />
        </p>
      )}
      {notes && company.notes && (
        <p className="tv-company-facts-notes">{company.notes}</p>
      )}
    </div>
  );
}
