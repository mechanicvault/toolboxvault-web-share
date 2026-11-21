import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";
import type { DictKey } from "../i18n/dictionaries";

/**
 * Unique meta titles + descriptions for the public pages
 * (sheet rows 87 + 88, SEO plan). The app ships one HTML shell
 * whose tags can only name one page, so this component keeps
 * document.title and the meta description set from the route
 * on every navigation — keyword-led copy for the pages we
 * want found (landing, Downloads, the 3D print shelf, signup),
 * in the reader's own language, and the plain brand treatment
 * everywhere else (the signed-in app, unchanged).
 *
 * A print file's own page (/3dprints/:id) is deliberately not
 * matched for either tag: the detail page sets both from the
 * file itself once it loads. Mounted once inside the router
 * (App.tsx Shell), next to CanonicalTag.
 */
function titleKeyFor(pathname: string): DictKey {
  if (pathname === "/" || pathname === "/landing") return "seo.title.home";
  if (pathname === "/downloads") return "seo.title.downloads";
  if (pathname === "/3dprints") return "seo.title.prints";
  if (pathname === "/signup") return "seo.title.signup";
  return "seo.title.default";
}

function descriptionKeyFor(pathname: string): DictKey {
  if (pathname === "/" || pathname === "/landing") return "seo.description.home";
  if (pathname === "/downloads") return "seo.description.downloads";
  if (pathname === "/3dprints") return "seo.description.prints";
  if (pathname === "/signup") return "seo.description.signup";
  return "seo.description.default";
}

const PRINT_DETAIL = /^\/3dprints\/[^/]+$/;

export default function PageTitleTag() {
  const { pathname } = useLocation();
  const t = useT();
  const title = t(titleKeyFor(pathname));
  const description = t(descriptionKeyFor(pathname));
  const printDetail = PRINT_DETAIL.test(pathname);

  useEffect(() => {
    document.title = title;
  }, [title]);

  useEffect(() => {
    if (printDetail) return; // the detail page owns this tag there
    let meta = document.querySelector<HTMLMetaElement>(
      'meta[name="description"]',
    );
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "description";
      document.head.appendChild(meta);
    }
    meta.content = description;
  }, [description, printDetail]);

  return null;
}
