import { BrandIcon, EmptyState, LinkButton, Panel } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { useAuth } from "./AuthContext";
import { SetupBanner, useOnboarding } from "./onboarding";
import HomeShell from "./HomeShell";

/**
 * Home (dashboard redesign, 2026-11-10): the signed-in page IS
 * the new shell — the widget registry (homeRegistry.tsx) renders
 * through HomeShell's chrome, with per-box ⛶/⋯ controls and
 * instant-save arrangement. The old assembly that lived here
 * (block defs + the usePageLayout draft/Edit-view stack + the
 * panel edit bridge) retired with Edit view itself; the side
 * panel reads its saved layout on its own now, as it always did
 * outside an edit session.
 *
 * Two shapes stay local, as before: the signed-out invitation
 * (no account to resolve modules or a layout for) and the bare
 * first Home for a wizard-born account that hasn't picked its
 * account types yet.
 */

/** The signed-out invitation (the old modules block's shape):
 *  there is no account to resolve modules or a layout for, so
 *  Home signed out is this one panel, as before. */
function SignedOutBlock() {
  const t = useT();
  return (
    <Panel title={t("home.modules")}>
      <EmptyState
        icon={<BrandIcon name="apps-grid" size={56} />}
        title={t("home.inventoryLiveTitle")}
        description={t("home.inventoryLiveBody")}
        action={<LinkButton to="/inventory">Inventory</LinkButton>}
      />
    </Panel>
  );
}

export default function CorePage() {
  const { user } = useAuth();
  const { plan: onboardingPlan } = useOnboarding();
  const t = useT();

  // Bare first Home (onboarding design 2026-10-31, built
  // 2026-11-07): an account born into the wizard that hasn't
  // picked its account types yet gets an intentionally bare Home
  // — no block stack (its widgets branch on groups it hasn't
  // chosen) — under the setup banner. The moment a type is
  // picked, the real Home renders.
  const bareHome =
    !!user &&
    // The downloads level is typeless BY DESIGN, not mid-setup:
    // its Home carries its downloads blocks (in the shell), so
    // the bare-banner rule must not starve it.
    user.tier !== "downloads" &&
    onboardingPlan?.flow === "wizard" &&
    user.account_types.length === 0;

  if (user && !bareHome) {
    return (
      <div className="tv-stack">
        <HomeShell />
      </div>
    );
  }

  return (
    <div className="tv-stack">
      {/* F1-19: Home joins the page-title standard (it had no H1). */}
      <div className="tv-home-head">
        <h1>{t("nav.core")}</h1>
      </div>
      {user && <SetupBanner />}
      {bareHome ? (
        <Panel>
          <div className="tv-setup-bare">
            <h2>{t("setup.bare.title" as never)}</h2>
            <p>{t("setup.bare.body" as never)}</p>
            <p>{t("setup.bare.public" as never)}</p>
          </div>
        </Panel>
      ) : (
        <div className="tv-home-blocks">
          <div className="tv-block-slot" data-size="full">
            <SignedOutBlock />
          </div>
        </div>
      )}
    </div>
  );
}
