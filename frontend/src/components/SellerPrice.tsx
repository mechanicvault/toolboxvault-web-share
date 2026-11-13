import { formatMoney, useMoneyHint } from "../lib/money";

/**
 * A cross-user price (wave 3): the amount in the SELLER's
 * currency — labeled by the one formatter — plus, when the
 * viewer's currency differs and rates are cached, the
 * approximate converted hint ("≈ $108.70"). The hint is
 * display-only; the stored amount never changes.
 */
export function SellerPrice({
  amount,
  currency,
}: {
  amount: string | number | null | undefined;
  currency: string | null | undefined;
}) {
  const hint = useMoneyHint(amount, currency);
  return (
    <>
      {formatMoney(amount, currency)}
      {hint && (
        <span
          style={{ color: "var(--text-muted)", fontWeight: 400, fontSize: "0.85em" }}
          title="Approximate conversion at the latest cached rates"
        >
          {" "}
          ({hint})
        </span>
      )}
    </>
  );
}
