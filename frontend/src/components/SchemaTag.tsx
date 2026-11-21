import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";

const SITE = "https://toolboxvault.com";
const SCRIPT_ID = "tv-schema";

/**
 * Structured data for the landing page (sheet row 92, SEO
 * plan): Organization + WebSite + SoftwareApplication as one
 * JSON-LD graph, so Google can show rich results. The facts
 * are the site's own — name, URL, the served logo, the social
 * profiles the footer links, and the free tier as the offer
 * (first tools free; no rating is claimed because none is
 * published). No public page carries a real Q&A section, so
 * no FAQ schema is emitted anywhere.
 *
 * Landing only, per the row: the script is present on / and
 * /landing and removed on every other route. Mounted once
 * inside the router (App.tsx Shell), next to PageTitleTag.
 */
export default function SchemaTag() {
  const { pathname } = useLocation();
  const t = useT();
  const onLanding = pathname === "/" || pathname === "/landing";
  const description = t("seo.description.home");

  useEffect(() => {
    let script = document.getElementById(
      SCRIPT_ID,
    ) as HTMLScriptElement | null;
    if (!onLanding) {
      script?.remove();
      return;
    }
    if (!script) {
      script = document.createElement("script");
      script.id = SCRIPT_ID;
      script.type = "application/ld+json";
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "Organization",
          "@id": `${SITE}/#organization`,
          name: "Toolbox Vault",
          url: `${SITE}/`,
          logo: `${SITE}/brand/logo-256.webp`,
          sameAs: [
            "https://facebook.com/toolboxvault",
            "https://instagram.com/toolboxvault",
          ],
        },
        {
          "@type": "WebSite",
          "@id": `${SITE}/#website`,
          name: "Toolbox Vault",
          url: `${SITE}/`,
          publisher: { "@id": `${SITE}/#organization` },
        },
        {
          "@type": "SoftwareApplication",
          name: "Toolbox Vault",
          applicationCategory: "BusinessApplication",
          operatingSystem: "Web",
          url: `${SITE}/`,
          description,
          publisher: { "@id": `${SITE}/#organization` },
          offers: {
            "@type": "Offer",
            price: "0",
            priceCurrency: "USD",
          },
        },
      ],
    });
  }, [onLanding, description]);

  return null;
}
