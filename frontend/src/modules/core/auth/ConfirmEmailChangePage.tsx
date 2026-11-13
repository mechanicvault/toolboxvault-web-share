import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Spinner } from "../../../components";
import { api, ApiError, REFRESH_TOKEN_KEY } from "../../../lib/api";
import { useAuth } from "../AuthContext";
import { AuthLayout } from "./AuthLayout";

/** Confirm email change: the landing page of the link sent to the
 *  NEW address (/confirm-email-change?token=…). The token is the
 *  whole credential — no sign-in is required — but when this
 *  browser IS signed in it passes its refresh token so its own
 *  session survives the move (every other session is revoked),
 *  then refreshes the profile so the UI shows the new address. */
export default function ConfirmEmailChangePage() {
  const { user, refreshUser } = useAuth();
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [message, setMessage] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    if (!token) {
      setState("failed");
      setMessage(
        "This confirmation link is missing its code — it may have been copied incompletely.",
      );
      return;
    }
    api<{ detail: string; email: string }>("/core/email-change/confirm", {
      method: "POST",
      body: JSON.stringify({
        token,
        refresh_token: localStorage.getItem(REFRESH_TOKEN_KEY) ?? undefined,
      }),
    })
      .then(async (res) => {
        setNewEmail(res.email);
        setState("done");
        // If this browser holds a session for the account, pull
        // the fresh profile (new email, verified) into the UI.
        if (user) await refreshUser().catch(() => undefined);
      })
      .catch((err: unknown) => {
        setState("failed");
        setMessage(
          err instanceof ApiError
            ? err.message
            : "Couldn't confirm the change. Try again from Settings.",
        );
      });
    // Run once on mount; `user`/`refreshUser` are read at mount
    // time on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthLayout
      title="Confirm email change"
      footer={
        <>
          Back to{" "}
          <Link to="/login" className="tv-auth-link">
            Log in
          </Link>
        </>
      }
    >
      {state === "working" && (
        <p className="tv-auth-inline-row">
          <Spinner size="sm" /> Confirming your new email address…
        </p>
      )}
      {state === "done" && (
        <div className="tv-auth-stack">
          <Alert tone="success">
            Your email address has been changed to {newEmail}. Use
            it the next time you sign in — a notice was also sent
            to your old address.
          </Alert>
          <Link
            to={user ? "/settings" : "/login"}
            className="tv-auth-link tv-auth-link-strong"
          >
            {user ? "Back to settings →" : "Go to log in →"}
          </Link>
        </div>
      )}
      {state === "failed" && (
        <div className="tv-auth-stack">
          <Alert tone="danger">{message}</Alert>
          <p className="tv-auth-muted0">
            You can start the change again from{" "}
            <Link to="/settings" className="tv-auth-link">
              Settings → Profile
            </Link>
            .
          </p>
        </div>
      )}
    </AuthLayout>
  );
}
