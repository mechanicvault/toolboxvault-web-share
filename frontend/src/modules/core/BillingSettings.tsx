import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Panel,
  Select,
  TextInput,
  useToast,
} from "../../components";
import { useLocale, useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { api, ApiError } from "../../lib/api";

/**
 * Settings → Plan & billing + Redeem & referrals (billing module).
 * Two registry sections since the settings restructure (owner
 * review round 1, 2026-10-19): BillingPlanSettings renders the
 * effective plan (GET /api/billing/me — the entitlement engine's
 * one answer) and the plan cards (GET /api/billing/catalog);
 * RedeemReferralsSettings carries the redeem-code form and the
 * referral block. They used to be one stacked panel.
 *
 * Money rules (owner decisions, 2026-10-18): prices are DEFERRED
 * and are never shown or hardcoded here — a plan whose Stripe
 * price id the operator hasn't set yet simply reads "Pricing
 * opens at launch". Checkout happens on Stripe's hosted pages
 * (cards, wallets, Cash App Pay, Link, ACH — whatever the account
 * enables); paid state arrives ONLY via webhook, so the success
 * return just refreshes the entitlement and says so honestly.
 * While no Stripe keys exist at all, the catalog reports
 * payments_configured=false and every purchase control is the
 * launch copy — dark, not broken.
 */

interface SubscriptionView {
  status: string;
  plan_key: string;
  source: string;
  current_period_end: string | null;
  grace_until: string | null;
  trial_end: string | null;
}

interface EntitlementView {
  plan_key: string;
  plan_name: string;
  source: string;
  is_paid: boolean;
  item_limit: number | null;
  items_total: number;
  items_active: number;
  enforcement_enabled: boolean;
  has_stripe_customer: boolean;
  subscription: SubscriptionView | null;
  referral_paying_count: number;
  referral_free_months: number;
}

interface CatalogPlan {
  plan_key: string;
  name: string;
  item_limit: number | null;
  is_paid: boolean;
  checkout_available: Record<string, boolean>;
}

interface CatalogBracket {
  bracket_key: string;
  up_to_employees: number | null;
  price_configured: boolean;
}

interface BillingCatalog {
  payments_configured: boolean;
  plans: CatalogPlan[];
  brackets: CatalogBracket[];
  ai_credit_packs: unknown[];
}

type Period = "monthly" | "yearly";

const SOURCE_KEYS: Record<string, DictKey> = {
  free: "settings.billing.sourceFree",
  subscription: "settings.billing.sourceSubscription",
  subscription_grace: "settings.billing.sourceGrace",
  trial: "settings.billing.sourceTrial",
  redeem_code: "settings.billing.sourceRedeem",
  admin: "settings.billing.sourceAdmin",
  lifetime: "settings.billing.sourceLifetime",
  referral: "settings.billing.sourceReferral",
};

function fmtDate(iso: string | null, locale: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(locale, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function bracketLabel(
  bracket: CatalogBracket,
  t: (key: DictKey) => string,
): string {
  return bracket.up_to_employees === null
    ? t("settings.billing.bracketUnlimited")
    : t("settings.billing.bracketUpTo").replace(
        "{count}",
        String(bracket.up_to_employees),
      );
}

export function BillingPlanSettings() {
  const { toast } = useToast();
  const t = useT();
  const { locale } = useLocale();
  const [view, setView] = useState<EntitlementView | null>(null);
  const [catalog, setCatalog] = useState<BillingCatalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>("monthly");
  const [bracket, setBracket] = useState("");
  const [checkoutPlan, setCheckoutPlan] = useState<string | null>(null);
  const [portalBusy, setPortalBusy] = useState(false);
  const returnHandled = useRef(false);

  const load = useCallback(async () => {
    try {
      const [entitlement, cat] = await Promise.all([
        api<EntitlementView>("/billing/me"),
        api<BillingCatalog>("/billing/catalog"),
      ]);
      setView(entitlement);
      setCatalog(cat);
      setBracket((current) =>
        current ||
        (cat.brackets.length > 0 ? cat.brackets[0].bracket_key : ""),
      );
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("settings.billing.loadFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  // Stripe sends the browser back to /settings/billing?checkout=…
  // (older returns used /settings#billing?checkout=… — the shell
  // redirects those here with the outcome preserved in the query).
  // The outcome is informational only — the webhook is what
  // actually changes the plan — so: toast it, scrub the marker
  // from the URL, and refresh the entitlement.
  useEffect(() => {
    if (returnHandled.current) return;
    const match =
      window.location.search.match(/[?&]checkout=(success|cancelled)/) ??
      window.location.hash.match(/[?&]checkout=(success|cancelled)/);
    if (!match) return;
    returnHandled.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    if (match[1] === "success") {
      toast(t("settings.billing.checkoutSuccess"), {
        tone: "success",
        duration: 8000,
      });
    } else {
      toast(t("settings.billing.checkoutCancelled"), {
        duration: 8000,
      });
    }
    void load();
  }, [load, toast, t]);

  async function startCheckout(planKey: string) {
    setCheckoutPlan(planKey);
    try {
      const res = await api<{ url: string }>("/billing/checkout", {
        method: "POST",
        body: JSON.stringify({
          plan_key: planKey,
          period,
          bracket: planKey === "business" ? bracket || null : null,
        }),
      });
      window.location.assign(res.url);
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("settings.billing.checkoutFailed"),
        { tone: "danger" },
      );
      setCheckoutPlan(null);
    }
  }

  async function openPortal() {
    setPortalBusy(true);
    try {
      const res = await api<{ url: string }>("/billing/portal", {
        method: "POST",
      });
      window.location.assign(res.url);
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("settings.billing.portalFailed"),
        { tone: "danger" },
      );
      setPortalBusy(false);
    }
  }

  function planCard(plan: CatalogPlan) {
    const isCurrent = view?.plan_key === plan.plan_key;
    const available = Boolean(
      catalog?.payments_configured && plan.checkout_available[period],
    );
    return (
      <div
        key={plan.plan_key}
        style={{
          border: "1px solid var(--edge)",
          borderRadius: "var(--radius)",
          padding: "var(--space-4)",
          display: "grid",
          gap: "var(--space-2)",
          alignContent: "start",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "var(--space-2)",
            flexWrap: "wrap",
          }}
        >
          <strong style={{ fontSize: "1.05rem" }}>{plan.name}</strong>
          {isCurrent && <Badge tone="success">{t("settings.billing.currentPlan")}</Badge>}
        </div>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {plan.item_limit === null
            ? t("settings.billing.unlimitedItems")
            : t("settings.billing.upToItems").replace(
                "{count}",
                String(plan.item_limit),
              )}
          {plan.plan_key === "business" && t("settings.billing.businessSuffix")}
          {plan.plan_key === "free" && t("settings.billing.freeSuffix")}
        </p>
        {plan.is_paid &&
          !isCurrent &&
          plan.plan_key === "business" &&
          catalog && (
            <FormField label={t("settings.billing.employeeBracket")} htmlFor="billing-bracket">
              <Select
                id="billing-bracket"
                value={bracket}
                onChange={(e) => setBracket(e.target.value)}
              >
                {catalog.brackets.map((b) => (
                  <option key={b.bracket_key} value={b.bracket_key}>
                    {bracketLabel(b, t)}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
        {plan.is_paid &&
          !isCurrent &&
          (available ? (
            <div>
              <Button
                loading={checkoutPlan === plan.plan_key}
                onClick={() => void startCheckout(plan.plan_key)}
              >
                {t("settings.billing.upgrade")}
              </Button>
            </div>
          ) : (
            <div>
              {/* A label, not a control (sheet row 129): pricing is
                  not open yet, so this renders as a flat badge —
                  a disabled button here read as a broken button. */}
              <span className="tv-badge">
                {t("settings.billing.pricingAtLaunch")}
              </span>
            </div>
          ))}
        {plan.is_paid && isCurrent && (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("settings.billing.youreOnThisPlan")}
          </p>
        )}
      </div>
    );
  }

  return (
    <Panel title={t("settings.billing.title")} variant="plate">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        {loadError && <Alert tone="danger">{loadError}</Alert>}
        {view && (
          <>
            <div
              className="tv-plan-box"
              style={{
                display: "flex",
                gap: "var(--space-3)",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span style={{ fontSize: "1.15rem", fontWeight: 700 }}>
                {t("settings.billing.planName").replace("{name}", view.plan_name)}
              </span>
              <Badge tone={view.is_paid ? "success" : "neutral"}>
                {SOURCE_KEYS[view.source]
                  ? t(SOURCE_KEYS[view.source])
                  : view.source}
              </Badge>
            </div>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {view.item_limit === null
                ? t(
                    view.items_total === 1
                      ? "settings.billing.itemsNoLimitOne"
                      : "settings.billing.itemsNoLimitMany",
                  ).replace("{count}", String(view.items_total))
                : t("settings.billing.itemsOfLimit")
                    .replace("{active}", String(view.items_active))
                    .replace("{limit}", String(view.item_limit))
                    .replace("{total}", String(view.items_total))}
              {!view.enforcement_enabled && t("settings.billing.notEnforced")}
            </p>
            {view.subscription?.status === "trialing" &&
              view.subscription.trial_end && (
                <p style={{ margin: 0 }}>
                  {t("settings.billing.trialEnds").replace(
                    "{date}",
                    fmtDate(view.subscription.trial_end, locale),
                  )}
                </p>
              )}
            {view.subscription?.current_period_end && (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t("settings.billing.periodEnds").replace(
                  "{date}",
                  fmtDate(view.subscription.current_period_end, locale),
                )}
                {view.subscription.grace_until &&
                  t("settings.billing.graceSuffix").replace(
                    "{date}",
                    fmtDate(view.subscription.grace_until, locale),
                  )}
                .
              </p>
            )}
            {view.has_stripe_customer && (
              <div>
                <Button
                  variant="secondary"
                  loading={portalBusy}
                  onClick={() => void openPortal()}
                >
                  {t("settings.billing.manageSubscription")}
                </Button>{" "}
                <span style={{ color: "var(--text-muted)" }}>
                  {t("settings.billing.portalNote")}
                </span>
              </div>
            )}
          </>
        )}

        {catalog && catalog.plans.length > 0 && (
          <div
            style={{
              borderTop: "1px solid var(--edge)",
              paddingTop: "1rem",
              display: "grid",
              gap: "var(--space-3)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "var(--space-2)",
              }}
            >
              <p style={{ fontWeight: 700, margin: 0 }}>{t("settings.billing.plans")}</p>
              <div
                style={{ display: "flex", gap: "var(--space-2)" }}
                role="group"
                aria-label={t("settings.billing.billingPeriod")}
              >
                <Button
                  size="sm"
                  variant={period === "monthly" ? "primary" : "secondary"}
                  aria-pressed={period === "monthly"}
                  onClick={() => setPeriod("monthly")}
                >
                  {t("settings.billing.monthly")}
                </Button>
                <Button
                  size="sm"
                  variant={period === "yearly" ? "primary" : "secondary"}
                  aria-pressed={period === "yearly"}
                  onClick={() => setPeriod("yearly")}
                >
                  {t("settings.billing.annual")}
                </Button>
              </div>
            </div>
            <div
              style={{
                display: "grid",
                gap: "var(--space-3)",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(min(200px, 100%), 1fr))",
              }}
            >
              {catalog.plans.map(planCard)}
            </div>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.billing.annualNote")}
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}

/** The redeem-code form + the referral block (split out of the old
 *  stacked billing panel by the settings restructure). Referral
 *  counts read the same /billing/me answer; a successful redeem
 *  refreshes them in place. */
export function RedeemReferralsSettings({
  accountNumber,
}: {
  accountNumber: string;
}) {
  const { toast } = useToast();
  const t = useT();
  const [view, setView] = useState<EntitlementView | null>(null);
  const [code, setCode] = useState("");
  const [redeemError, setRedeemError] = useState<string | null>(null);
  const [redeeming, setRedeeming] = useState(false);

  const load = useCallback(async () => {
    try {
      setView(await api<EntitlementView>("/billing/me"));
    } catch {
      /* the referral line just stays generic without the answer */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onRedeem(e: FormEvent) {
    e.preventDefault();
    setRedeemError(null);
    if (!code.trim()) {
      setRedeemError(t("settings.billing.codeRequired"));
      return;
    }
    setRedeeming(true);
    try {
      const res = await api<{ message: string }>("/core/redeem", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      toast(res.message, { tone: "success" });
      setCode("");
      await load();
    } catch (err) {
      setRedeemError(
        err instanceof ApiError ? err.message : t("settings.billing.redeemFailed"),
      );
    } finally {
      setRedeeming(false);
    }
  }

  return (
    <Panel title={t("settings.billing.redeemTitle")} variant="plate">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.billing.redeemHeading")}
          </p>
          <form
            onSubmit={onRedeem}
            style={{ display: "grid", gap: "var(--space-3)" }}
          >
            {redeemError && <Alert tone="danger">{redeemError}</Alert>}
            <FormField
              label={t("settings.billing.codeLabel")}
              htmlFor="billing-redeem-code"
              hint={t("settings.billing.codeHint")}
            >
              <TextInput
                id="billing-redeem-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="off"
                placeholder={t("settings.billing.codePlaceholder")}
              />
            </FormField>
            <div>
              <Button type="submit" loading={redeeming}>
                {t("settings.billing.redeemButton")}
              </Button>
            </div>
          </form>
        </div>

        <div
          style={{
            borderTop: "1px solid var(--edge)",
            paddingTop: "1rem",
          }}
        >
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.billing.referHeading")}
          </p>
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("settings.billing.referIntroLead")}{" "}
            <strong style={{ color: "var(--text)" }}>{accountNumber}</strong>
            {t("settings.billing.referIntroTail")}
            {view &&
              t(
                view.referral_paying_count === 1
                  ? "settings.billing.referNowOne"
                  : "settings.billing.referNowMany",
              ).replace("{count}", String(view.referral_paying_count))}
            {view &&
              (view.referral_free_months > 0
                ? t(
                    view.referral_free_months === 1
                      ? "settings.billing.referMonthsOne"
                      : "settings.billing.referMonthsMany",
                  ).replace("{count}", String(view.referral_free_months))
                : ".")}
          </p>
        </div>
      </div>
    </Panel>
  );
}
