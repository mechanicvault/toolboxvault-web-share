import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { PageSkeleton } from "../../../components";
import { useAuth } from "../AuthContext";

/** Gate for pages that need a signed-in user. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    // F1-01: while the stored token validates, the content area
    // holds a page-shaped skeleton — never a lone spinner on an
    // empty page (this state is what a reload shows first).
    return <PageSkeleton />;
  }
  if (!user) {
    // W-02: the redirect-back keeps the FULL intended destination —
    // pathname + search + hash. It used to keep only the pathname,
    // so an explicit URL like /inventory?q=… or …#repairs lost its
    // query/anchor across the sign-in round-trip.
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search + location.hash }}
      />
    );
  }
  return <>{children}</>;
}
