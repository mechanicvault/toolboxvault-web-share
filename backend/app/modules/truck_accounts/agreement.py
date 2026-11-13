"""The truck-account user agreement (wave 2, 2026-10-20).

The agreement is a VERSIONED TEMPLATE IN CODE: acceptance stores
the version + the FULL RENDERED TEXT on the account row, so what
a customer agreed to is provable forever, even after the
template moves on. The one variable line — the platform fee
disclosure — is rendered from the admin setting
`payments.truck_fee_percent` at acceptance time (default 0: no
platform fee is taken from truck payments), so the snapshot
always shows the fee terms in force when the customer agreed.

Online payments themselves ride the DARK Stripe Connect seam
(truck_payments.py): the agreement authorizes the recurring
cadence either way — manual payments at the truck today, saved-
method auto-pay when Connect activates.
"""

from app.modules.billing import entitlements

AGREEMENT_VERSION = "2026-10-20.1"

CONNECT_ENABLED_KEY = "payments.connect_enabled"
TRUCK_FEE_PERCENT_KEY = "payments.truck_fee_percent"

_TEMPLATE = """TRUCK ACCOUNT AGREEMENT — Toolbox Vault (version {version})

Between you (the Customer) and {dealer_name} (the Dealer).

1. THE ACCOUNT. The Dealer extends you a running tab for tools
   and supplies bought from the Dealer's truck. Toolbox Vault
   provides the bookkeeping only — your debt is owed to the
   Dealer, not to Toolbox Vault, and Toolbox Vault never holds
   your money.

2. PAYMENTS. You agree to pay {amount_clause} until the balance
   is paid in full. Payments may be made in person at the truck
   (cash or check, recorded by either party) or, when online
   payments are enabled for your Dealer, through the payment
   method you save in the app.

3. AUTHORIZATION. By accepting, you authorize charges and
   payments recorded on this account to be applied as described
   here. Each charge and payment is recorded in a ledger both
   you and the Dealer can see, and you are notified of every
   entry.

4. PLATFORM FEE. {fee_line}

5. ENDING THE ACCOUNT. Either party may close the account at
   any time. Closing freezes the ledger — no new charges or
   payments are recorded — but any balance still owed remains
   owed to the Dealer under your arrangements with them, and
   the ledger history is kept for both parties' records.

6. DISPUTES. If an entry looks wrong, contact the Dealer first;
   entries are never edited or deleted — a correction is
   recorded as an adjustment both parties can see.
"""


def fee_disclosure_line(db) -> str:
    """The fee line as it reads TODAY (admin-set percent)."""
    percent = entitlements.get_setting(db, TRUCK_FEE_PERCENT_KEY, 0)
    try:
        value = float(percent) if percent not in (None, "") else 0.0
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return (
            "Toolbox Vault charges no platform fee on truck-account "
            "payments. Your Dealer's payment processor may charge "
            "its own processing fees, which are the Dealer's."
        )
    pct = f"{value:g}"
    return (
        f"Toolbox Vault charges a platform fee of {pct}% on online "
        "truck-account payments, deducted from the amount the "
        "Dealer receives. Manual payments made at the truck carry "
        "no platform fee."
    )


def render_agreement(db, *, dealer_name: str, cadence: str,
                     payment_amount, currency: str = "USD") -> str:
    """The full text for one account's acceptance screen — and,
    verbatim, the snapshot stored when the customer accepts.
    Amounts render through the one formatter in the DEALER's
    currency (the dealer sets the tab's terms — v1 semantics)."""
    if payment_amount is not None:
        from app.modules.core import money as core_money

        every = "week" if cadence == "weekly" else "two weeks"
        amount_clause = (
            f"{core_money.format_money(payment_amount, currency)} every {every}"
        )
    else:
        amount_clause = "the agreed amount on the agreed schedule"
    return _TEMPLATE.format(
        version=AGREEMENT_VERSION,
        dealer_name=dealer_name or "your dealer",
        amount_clause=amount_clause,
        fee_line=fee_disclosure_line(db),
    )
