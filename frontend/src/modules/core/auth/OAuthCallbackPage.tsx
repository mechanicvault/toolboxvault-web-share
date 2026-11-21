import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Spinner } from "../../../components";
import { storeTokens } from "../../../lib/api";
import { AuthLayout } from "./AuthLayout";

/** Landing page for social login. The API redirects here with the token
 *  pair in the URL fragment (#access_token=…&refresh_token=…): store
 *  them, then hand off to the app home. Anything else — a missing or
 *  malformed fragment — goes back to /login, which shows the OAuth
 *  failure message.
 *
 *  Sweep C2 completion: when the round trip started at the sign-in
 *  door, the fragment also carries the kept destination (&next=…,
 *  sealed server-side in the signed OAuth state token). It is
 *  honoured only as a same-site path — the mirror of the server's
 *  own check — and anything else falls back to the home hand-off,
 *  exactly as before. */
function safeLocalNext(value: string | null): string | null {
  if (!value) return null;
  if (!value.startsWith("/") || value.startsWith("//")) return null;
  if (value.includes("\\")) return null;
  return value;
}

export default function OAuthCallbackPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const accessToken = fragment.get("access_token");
    const refreshToken = fragment.get("refresh_token");
    if (accessToken && refreshToken) {
      storeTokens(accessToken, refreshToken);
      // Full reload on purpose: AuthProvider reads the stored tokens
      // once, on mount — this is the clean moment to let it do that,
      // and it drops the token-bearing URL from history.
      window.location.replace(safeLocalNext(fragment.get("next")) ?? "/");
    } else {
      navigate("/login?error=oauth", { replace: true });
    }
  }, [navigate]);

  return (
    <AuthLayout title="Signing you in">
      <p className="tv-auth-inline-row">
        <Spinner size="sm" /> One moment — finishing your sign-in…
      </p>
    </AuthLayout>
  );
}
