import { useEffect, useState } from "react";
import { formatDate } from "../../lib/format";
import { Alert, Button, Panel, useToast } from "../../components";
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

const REASON_COPY: Record<string, string> = {
  allowance_refill: "Monthly allowance",
  purchase: "Purchased",
  grant: "Granted",
  redeem: "Redeem code",
  spend: "AI use",
  admin_adjust: "Adjustment",
};

export default function AiCreditsSettings() {
  const { toast } = useToast();
  const [view, setView] = useState<WalletView | null>(null);
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [buyingPack, setBuyingPack] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<WalletView>("/billing/ai-wallet")
      .then(setView)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Couldn't load your AI credits.",
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
        err instanceof ApiError ? err.message : "Checkout couldn't be started.",
        { tone: "danger" },
      );
      setBuyingPack(null);
    }
  }

  return (
    <Panel title="AI credits" variant="plate">
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Credits power the AI features (item identification and
          assist) when they arrive. Your plan's monthly allowance
          refills each month and doesn't roll over; purchased,
          granted, and redeemed credits are banked and never expire.
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
                <div className="tv-stat-label">total credits</div>
                <div className="tv-stat-value">{view.total_balance}</div>
              </div>
              <div>
                <div className="tv-stat-label">monthly allowance</div>
                <div className="tv-stat-value">{view.allowance_balance}</div>
              </div>
              <div>
                <div className="tv-stat-label">banked</div>
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
                      {REASON_COPY[row.reason] ?? row.reason}{" "}
                      <span style={{ color: "var(--text-muted)" }}>
                        · {row.bucket} ·{" "}
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
                No credit activity yet.
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
            <p style={{ fontWeight: 700, margin: 0 }}>Buy more credits</p>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Purchased credits are banked — they never expire and
              are spent only after your monthly allowance.
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
                    · {pack.credits} credits
                  </span>
                </span>
                {pack.purchasable ? (
                  <Button
                    size="sm"
                    loading={buyingPack === pack.id}
                    onClick={() => void buyPack(pack)}
                  >
                    Buy
                  </Button>
                ) : (
                  <Button size="sm" variant="secondary" disabled>
                    Pricing opens at launch
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
