import { useEffect, useState } from "react";
import { formatDate } from "../../lib/format";
import { Alert, Button, Panel, useToast } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { api, ApiError } from "../../lib/api";

/**
 * Settings → AI credits (billing module wallet): the two balances
 * (monthly allowance + banked credits), the recent ledger, and —
 * when the operator has defined credit packs — a Buy credits
 * block. Purchases check out on Stripe's hosted pages and bank
 * via the webhook; a pack without a price id yet reads "Pricing
 * opens at launch" instead of pretending to sell. Spending arrives
 * with the AI features; credits banked now (grants, redeem codes,
 * purchases) will be ready.
 */

interface CreditPack {
  id: string;
  label: string;
  credits: number;
  purchasable: boolean;
}

interface LedgerEntry {
  id: string;
  delta: number;
  bucket: string;
  reason: string;
  ref: string;
  bucket_balance_after: number;
  created_at: string;
}

interface WalletView {
  allowance_balance: number;
  banked_balance: number;
  total_balance: number;
  ledger: LedgerEntry[];
}

const REASON_KEYS: Record<string, DictKey> = {
  allowance_refill: "settings.aiCredits.reasonAllowanceRefill",
  purchase: "settings.aiCredits.reasonPurchase",
  grant: "settings.aiCredits.reasonGrant",
  redeem: "settings.aiCredits.reasonRedeem",
  spend: "settings.aiCredits.reasonSpend",
  admin_adjust: "settings.aiCredits.reasonAdminAdjust",
};

const BUCKET_KEYS: Record<string, DictKey> = {
  allowance: "settings.aiCredits.bucketAllowance",
  banked: "settings.aiCredits.bucketBanked",
};

export default function AiCreditsSettings() {
  const { toast } = useToast();
  const t = useT();
  const [view, setView] = useState<WalletView | null>(null);
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [buyingPack, setBuyingPack] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<WalletView>("/billing/ai-wallet")
      .then(setView)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : t("settings.aiCredits.loadFailed"),
        ),
      );
    // The pack list rides the billing catalog; its absence (or a
    // failure loading it) simply means no Buy block — never an
    // error on a read-only wallet panel.
    api<{ ai_credit_packs: CreditPack[] }>("/billing/catalog")
      .then((catalog) => setPacks(catalog.ai_credit_packs))
      .catch(() => setPacks([]));
  }, []);

  async function buyPack(pack: CreditPack) {
    setBuyingPack(pack.id);
    try {
      const res = await api<{ url: string }>("/billing/checkout-credits", {
        method: "POST",
        body: JSON.stringify({ pack_id: pack.id }),
      });
      window.location.assign(res.url);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.billing.checkoutFailed"),
        { tone: "danger" },
      );
      setBuyingPack(null);
    }
  }

  return (
    <Panel title={t("settings.aiCredits.title")} variant="plate">
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.aiCredits.intro")}
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        {view && (
          <>
            <div
              style={{
                display: "flex",
                gap: "var(--space-5)",
                flexWrap: "wrap",
              }}
            >
              <div>
                <div className="tv-stat-label">{t("settings.aiCredits.statTotal")}</div>
                <div className="tv-stat-value">{view.total_balance}</div>
              </div>
              <div>
                <div className="tv-stat-label">{t("settings.aiCredits.statAllowance")}</div>
                <div className="tv-stat-value">{view.allowance_balance}</div>
              </div>
              <div>
                <div className="tv-stat-label">{t("settings.aiCredits.statBanked")}</div>
                <div className="tv-stat-value">{view.banked_balance}</div>
              </div>
            </div>
            {view.ledger.length > 0 ? (
              <ul
                style={{
                  listStyle: "none",
                  margin: 0,
                  padding: 0,
                  display: "grid",
                  gap: "0.4rem",
                }}
              >
                {view.ledger.map((row) => (
                  <li
                    key={row.id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: "1rem",
                      fontSize: "0.92rem",
                    }}
                  >
                    <span>
                      {REASON_KEYS[row.reason]
                        ? t(REASON_KEYS[row.reason])
                        : row.reason}{" "}
                      <span style={{ color: "var(--text-muted)" }}>
                        ·{" "}
                        {BUCKET_KEYS[row.bucket]
                          ? t(BUCKET_KEYS[row.bucket])
                          : row.bucket}{" "}
                        ·{" "}
                        {formatDate(row.created_at)}
                      </span>
                    </span>
                    <strong
                      style={{
                        color:
                          row.delta >= 0 ? "var(--success)" : "var(--danger)",
                      }}
                    >
                      {row.delta >= 0 ? `+${row.delta}` : row.delta}
                    </strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>
                {t("settings.aiCredits.noActivity")}
              </p>
            )}
          </>
        )}
        {packs.length > 0 && (
          <div
            style={{
              borderTop: "1px solid var(--edge)",
              paddingTop: "1rem",
              display: "grid",
              gap: "var(--space-2)",
            }}
          >
            <p style={{ fontWeight: 700, margin: 0 }}>{t("settings.aiCredits.buyMore")}</p>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.aiCredits.buyIntro")}
            </p>
            {packs.map((pack) => (
              <div
                key={pack.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "var(--space-3)",
                  flexWrap: "wrap",
                }}
              >
                <span>
                  {pack.label}{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    ·{" "}
                    {t("settings.aiCredits.packCredits").replace(
                      "{count}",
                      String(pack.credits),
                    )}
                  </span>
                </span>
                {pack.purchasable ? (
                  <Button
                    size="sm"
                    loading={buyingPack === pack.id}
                    onClick={() => void buyPack(pack)}
                  >
                    {t("settings.aiCredits.buy")}
                  </Button>
                ) : (
                  <Button size="sm" variant="secondary" disabled>
                    {t("settings.billing.pricingAtLaunch")}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}
