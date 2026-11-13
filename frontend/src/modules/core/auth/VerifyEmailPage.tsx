import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Spinner } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useAuth } from "../AuthContext";
import { AuthLayout } from "./AuthLayout";

/** Verify email: the landing page of the signup verification link
 *  (/verify-email?token=…). The endpoint is the plumbing that
 *  existed since signup shipped; this page is its front door —
 *  without it the emailed link landed on the home page and the
 *  address was never actually confirmed from a browser. */
export default function VerifyEmailPage() {
  const { user, refreshUser } = useAuth();
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    if (!token) {
      setState("failed");
      setMessage(
        "This verification link is missing its code — it may have been copied incompletely.",
      );
      return;
    }
    api<{ detail: string }>(`/core/verify-email?token=${encodeURIComponent(token)}`)
      .then(async () => {
        setState("done");
        if (user) await refreshUser().catch(() => undefined);
      })
      .catch((err: unknown) => {
        setState("failed");
        setMessage(
          err instanceof ApiError
            ? err.message
            : "Couldn't verify your email. Try again.",
        );
      });
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthLayout
      title="Verify your email"
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
          <Spinner size="sm" /> Verifying your email address…
        </p>
      )}
      {state === "done" && (
        <div className="tv-auth-stack">
          <Alert tone="success">Your email address is verified.</Alert>
          <Link
            to={user ? "/" : "/login"}
            className="tv-auth-link tv-auth-link-strong"
          >
            {user ? "Go to your vault →" : "Go to log in →"}
          </Link>
        </div>
      )}
      {state === "failed" && (
        <div className="tv-auth-stack">
          <Alert tone="danger">{message}</Alert>
          <p className="tv-auth-muted0">
            Sign in and resend a fresh link from{" "}
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
