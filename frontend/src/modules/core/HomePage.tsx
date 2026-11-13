import { TOKEN_KEY } from "../../lib/api";
import { useAuth } from "./AuthContext";
import CorePage from "./CorePage";
import LandingComboPage from "./LandingComboPage";
import { useTeaser } from "./teaser";
import TeaserPage, { TeaserSplash } from "./TeaserPage";

/**
 * The "/" route: signed-in users get their home EXACTLY as it
 * always was (CorePage, untouched); signed-out visitors get the
 * public front door — which one depends on the operator's
 * teaser switch (2026-10-26):
 *
 * - Teaser ON: the teaser page (brand, one line, the countdown,
 *   two doors — nothing of the product behind it).
 * - Teaser OFF: the official landing page — the Combination
 *   (LandingComboPage), promoted from the landing tests on
 *   2026-11-08 on the owner's order; it replaced the merged
 *   landing, which served here from 2026-10-24 to 2026-11-08
 *   and is removed. The original pre-merge landing
 *   (LandingPage.tsx) still stays in the repo unrouted,
 *   reversible like the retired themes. The landing also has
 *   its own seat at "/landing" (registry: core-landing) so a
 *   signed-in user can open it — here, signed in means home.
 *
 * While a stored token is still being validated, CorePage
 * renders — the same thing the route did before this split — so
 * a returning user never flashes marketing copy on the way to
 * their vault. While the teaser posture itself is still being
 * read, the brand-only splash renders: the landing's features
 * must never flash to a teaser-world visitor, and the splash is
 * neutral in the off state too (the landing needs the same
 * config read for its prices).
 */
export default function HomePage() {
  const { user, loading } = useAuth();
  const { known, teaserMode } = useTeaser();
  if (user) return <CorePage />;
  if (loading && localStorage.getItem(TOKEN_KEY)) return <CorePage />;
  if (!known) return <TeaserSplash />;
  if (teaserMode) return <TeaserPage />;
  return <LandingComboPage />;
}
