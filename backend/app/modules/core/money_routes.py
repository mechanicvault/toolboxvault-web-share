"""Money routes (wave 3): the chooser's vocabulary + the
cross-currency hint.

- GET /money/meta — the country + currency lists the signup and
  Profile choosers render (one source: core.money). PUBLIC: it's
  static reference data (no user facts), and the signup form —
  signed out by definition — renders from it.
- GET /money/hint?amount=&from_currency= — the approximate
  converted hint for the CALLER's currency ("≈ $X"), or null when
  the currencies match or no rate is cached. Display only.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.core import money

router = APIRouter(tags=["money"])


@router.get("/money/meta")
def money_meta():
    return {
        "countries": [
            {"code": code, "label": label} for code, label in money.COUNTRIES
        ],
        "currencies": list(money.CURRENCIES),
        "country_currencies": money.COUNTRY_CURRENCIES,
    }


@router.get("/money/hint")
def money_hint(
    amount: str,
    from_currency: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        value = Decimal(amount)
    except InvalidOperation:
        value = Decimal("0")
    return {
        "hint": money.convert_hint(db, value, from_currency, user.currency),
        "viewer_currency": money.normalize_currency(user.currency),
    }
