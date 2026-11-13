import { useEffect, useState } from "react";
import { HrefButton } from "../../../components";
import { api } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";

interface OAuthProviders {
  google: boolean;
  facebook: boolean;
}

/** "Continue with …" buttons for whichever social providers the server
 *  has configured (GET /core/auth/providers). Renders nothing when none
 *  are — the email form stays the only path, exactly as before.
 *
 *  Plain <a> links, not API calls: the start endpoints are full-page
 *  redirects out to the provider and back.
 *
 *  Sweep C2 completion: when the sign-in door was reached with a
 *  kept destination, it rides the start URL as ?next= — the server
 *  validates it and seals it inside the signed OAuth state token,
 *  the one channel that survives the provider round trip, and the
 *  callback hands it to OAuthCallbackPage in the token fragment.
 *  No destination (a plain /login or /signup arrival) renders the
 *  bare start URLs exactly as before. */
export function SocialButtons({ next }: { next?: string | null }) {
  const t = useT();
  const nextQuery = next ? `?next=${encodeURIComponent(next)}` : "";
  const [providers, setProviders] = useState<OAuthProviders | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<OAuthProviders>("/core/auth/providers")
      .then((p) => {
        if (!cancelled) setProviders(p);
      })
      .catch(() => {
        if (!cancelled) setProviders({ google: false, facebook: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!providers || (!providers.google && !providers.facebook)) return null;

  return (
    <div className="tv-auth-social">
      <p className="tv-auth-or">
        {t("auth.or")}
      </p>
      {providers.google && (
        <HrefButton href={`/api/core/auth/google/start${nextQuery}`} className="tv-auth-social-btn" variant="secondary" block>{t("auth.continueGoogle")}</HrefButton>
      )}
      {providers.facebook && (
        <HrefButton href={`/api/core/auth/facebook/start${nextQuery}`} className="tv-auth-social-btn" variant="secondary" block>{t("auth.continueFacebook")}</HrefButton>
      )}
    </div>
  );
}
