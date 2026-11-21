import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Self-referencing canonical tag (sheet row 86, SEO plan).
 *
 * The app ships as one HTML shell for every route, so the
 * canonical cannot be baked per page: this component keeps the
 * document's <link rel="canonical"> pointed at the page's own
 * clean URL — origin + pathname, no query string, no hash, no
 * trailing slash except the root — on every navigation. That
 * stops duplicate URLs (tracking parameters, trailing-slash
 * twins, legacy redirects) from splitting a public page's
 * ranking. index.html carries the root canonical as the
 * pre-script default; this takes over as soon as the app boots.
 *
 * Mounted once inside the router (App.tsx Shell), next to
 * ScrollManager, so it covers every route uniformly.
 */
const ORIGIN = "https://toolboxvault.com";

export default function CanonicalTag() {
  const { pathname } = useLocation();

  useEffect(() => {
    const clean =
      pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
    let link = document.querySelector<HTMLLinkElement>(
      'link[rel="canonical"]',
    );
    if (!link) {
      link = document.createElement("link");
      link.rel = "canonical";
      document.head.appendChild(link);
    }
    link.href = `${ORIGIN}${clean}`;
  }, [pathname]);

  return null;
}
