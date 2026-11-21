"""Claim amounts are the OWNER's money (currency alignment,
2026-10-26).

The defect: the claims UI labeled claim amounts with the VIEWER's
currency while the claim package PDF printed the OWNER's — a
dealer-seat reading an EUR owner's claim saw "$" on screen and
"€" in the package for the same numbers.

Pins:
- every claim serializer (detail, summary, incoming row, item /
  dealer refs) carries `owner_currency` — the claim owner's
  currency, never the viewer's;
- the package and the serializers agree: same total, owner's
  currency on both;
- the cross-currency hint contract the screen relies on
  (SellerPrice → /core/money/hint): a hint exists only when the
  viewer's currency differs from the owner's AND a rate is
  cached — same currency or unrated currency means no hint, no
  guess.
"""

import re
import uuid
import zlib
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.modules.claims import package as claims_package
from app.modules.claims import service as claims_service
from app.modules.core import money
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, *, currency="USD", name="Test User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=account_types,
        currency=currency,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _tool(db, owner, name="Impact wrench", **overrides):
    tool = inventory_models.Tool(owner_id=owner.id, name=name, **overrides)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def _company(db, name="Acme Tool Co"):
    company = dealer_models.DealerCompany(name=name, email="", is_directory=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _represent(db, company, user):
    # Agent scope (2026-10-31): the dealer seat on a warranty
    # claim is the owner's ASSIGNED agent with a VERIFIED link —
    # the representation is created verified, and _warranty_setup
    # records the dealer as the owner's agent for the company.
    row = dealer_models.CompanyRepresentation(
        company_id=company.id, agent_user_id=user.id, verified=True
    )
    db.add(row)
    db.commit()
    return row


def _seed_rates(db):
    money.store_rates(
        db,
        {
            # EUR per 1 unit: 1 USD = 0.92 EUR; 1 GBP = 1.17 EUR.
            "USD": Decimal("0.92"),
            "GBP": Decimal("1.17"),
        },
        date(2026, 10, 19),
    )


def _warranty_setup(db, *, owner_currency, dealer_currency):
    """An owner + a dealer-seat user + a company the dealer speaks
    for + the owner's tool tagged to that company (€/$250.00 of
    purchase cost — claim money is what the owner paid, ruling
    2026-11-06)."""
    owner = _make_user(
        db, "TV-M-000801", f"cc-owner-{owner_currency}@example.com",
        [MECHANIC], currency=owner_currency, name="Olivia Owner",
    )
    dealer = _make_user(
        db, "TV-D-000802", f"cc-dealer-{dealer_currency}@example.com",
        [DEALER], currency=dealer_currency, name="Dan Dealer",
    )
    company = _company(db)
    _represent(db, company, dealer)
    db.add(
        dealer_models.PreferredAgent(
            user_id=owner.id, company_id=company.id, agent_user_id=dealer.id
        )
    )
    db.commit()
    tool = _tool(
        db, owner,
        purchase_price=Decimal("250.00"),
        replacement_cost=Decimal("250.00"),
        dealer_company_id=company.id,
    )
    return owner, dealer, company, tool


def _create_warranty(client, owner, tool):
    response = client.post(
        "/api/claims/warranty",
        json={
            "target_kind": "tool",
            "target_id": str(tool.id),
            "dealer_notified": True,
            "problem": "It stopped working.",
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()["claim"]


# -- the dealer seat reads the owner's currency ---------------------------------


def test_warranty_claim_currency_reaches_every_seat(client, db):
    owner, dealer, company, tool = _warranty_setup(
        db, owner_currency="EUR", dealer_currency="USD"
    )
    _seed_rates(db)
    claim = _create_warranty(client, owner, tool)
    assert claim["owner_currency"] == "EUR"
    assert Decimal(claim["total_amount"]) == Decimal("250.00")

    # The owner's own detail + list: owner currency, unchanged
    # numbers (the owner's view behaves exactly as before).
    own_view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(owner)
    ).json()
    assert own_view["viewer_role"] == "owner"
    assert own_view["owner_currency"] == "EUR"
    assert Decimal(own_view["total_amount"]) == Decimal("250.00")
    (summary,) = client.get("/api/claims", headers=auth_headers(owner)).json()
    assert summary["owner_currency"] == "EUR"
    assert Decimal(summary["total_amount"]) == Decimal("250.00")

    # The dealer seat: same record, same numbers, labeled with
    # the OWNER's currency — not the dealer's USD.
    dealer_view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(dealer)
    ).json()
    assert dealer_view["viewer_role"] == "dealer"
    assert dealer_view["owner_currency"] == "EUR"
    assert Decimal(dealer_view["total_amount"]) == Decimal("250.00")

    # The dealer's incoming worklist carries it too.
    (incoming,) = client.get(
        "/api/claims/incoming", headers=auth_headers(dealer)
    ).json()
    assert incoming["id"] == claim["id"]
    assert incoming["owner_currency"] == "EUR"
    assert incoming["owner_name"] == "Olivia Owner"
    assert Decimal(incoming["total_amount"]) == Decimal("250.00")

    # The item-page refs (owner's corner of the triangle).
    refs = client.get(
        f"/api/claims/for-item/tool/{tool.id}", headers=auth_headers(owner)
    ).json()
    (ref,) = refs["current"]
    assert ref["owner_currency"] == "EUR"
    assert Decimal(ref["total_amount"]) == Decimal("250.00")

    # The dealer-page refs (same serializer, other caller).
    split = claims_service.claims_for_dealer(db, owner, company.id)
    (dealer_ref,) = split["current"]
    assert dealer_ref["owner_currency"] == "EUR"
    assert Decimal(dealer_ref["total_amount"]) == Decimal("250.00")

    # The screen's hint for the dealer: real, and it converts the
    # same €250.00 the dealer is looking at (250 / 0.92 ≈ $271.74).
    hint = client.get(
        "/api/core/money/hint",
        params={"amount": "250.00", "from_currency": claim["owner_currency"]},
        headers=auth_headers(dealer),
    )
    assert hint.json() == {"hint": "≈ $271.74", "viewer_currency": "USD"}


def test_same_currency_dealer_gets_owner_currency_and_no_hint(client, db):
    owner, dealer, _company, tool = _warranty_setup(
        db, owner_currency="USD", dealer_currency="USD"
    )
    _seed_rates(db)
    claim = _create_warranty(client, owner, tool)
    dealer_view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(dealer)
    ).json()
    assert dealer_view["owner_currency"] == "USD"
    hint = client.get(
        "/api/core/money/hint",
        params={"amount": "250.00", "from_currency": "USD"},
        headers=auth_headers(dealer),
    )
    assert hint.json()["hint"] is None


def test_unrated_owner_currency_labels_truthfully_and_never_hints(client, db):
    # CAD is a real currency with NO cached rate in this seed:
    # the label still tells the truth (CAD), and no hint is
    # invented for the USD dealer.
    owner, dealer, _company, tool = _warranty_setup(
        db, owner_currency="CAD", dealer_currency="USD"
    )
    _seed_rates(db)
    claim = _create_warranty(client, owner, tool)
    dealer_view = client.get(
        f"/api/claims/{claim['id']}", headers=auth_headers(dealer)
    ).json()
    assert dealer_view["owner_currency"] == "CAD"
    (incoming,) = client.get(
        "/api/claims/incoming", headers=auth_headers(dealer)
    ).json()
    assert incoming["owner_currency"] == "CAD"
    hint = client.get(
        "/api/core/money/hint",
        params={"amount": "250.00", "from_currency": "CAD"},
        headers=auth_headers(dealer),
    )
    assert hint.json()["hint"] is None


# -- the package agrees with the screen ------------------------------------------


def _pdf_text(pdf_bytes: bytes) -> str:
    """The package's text layer: decompress the content streams
    and read them as cp1252 (fpdf2's core-font encoding)."""
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        raw = match.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        chunks.append(raw.decode("cp1252", errors="ignore"))
    return "\n".join(chunks)


def test_insurance_package_prints_owner_currency_matching_serializer(
    client, db, monkeypatch
):
    owner = _make_user(
        db, "TV-M-000803", "cc-package@example.com",
        [MECHANIC], currency="EUR", name="Olivia Owner",
    )
    tool = _tool(db, owner)
    other_tool = _tool(db, owner, name="Torque wrench")
    created = client.post("/api/disaster-claims", json={}, headers=auth_headers(owner))
    assert created.status_code == 201, created.text
    claim_id = created.json()["id"]
    for target, amount in ((tool, "250.00"), (other_tool, "50.00")):
        line = client.post(
            f"/api/disaster-claims/{claim_id}/lines",
            json={
                "target_kind": "tool",
                "target_id": str(target.id),
                "value_basis": "entered",
                "amount": amount,
            },
            headers=auth_headers(owner),
        )
        assert line.status_code == 201, line.text

    view = client.get(
        f"/api/disaster-claims/{claim_id}", headers=auth_headers(owner)
    ).json()
    assert view["owner_currency"] == "EUR"
    assert Decimal(view["total_amount"]) == Decimal("300.00")

    # Every amount the package formats is formatted in the
    # owner's currency — spy on the one formatter it uses.
    calls = []
    real_format = claims_package.money.format_money

    def spy(amount, currency):
        calls.append((Decimal(str(amount)), currency))
        return real_format(amount, currency)

    monkeypatch.setattr(claims_package.money, "format_money", spy)
    claim = db.scalars(
        select(claims_service.models.Claim).where(
            claims_service.models.Claim.id == uuid.UUID(claim_id)
        )
    ).one()
    pdf_bytes = claims_package.build_package(db, owner, claim)
    assert calls, "the package formatted no amounts"
    assert {currency for _amount, currency in calls} == {"EUR"}
    assert (Decimal("300.00"), "EUR") in calls

    # And the printed document itself says €300.00 — the same
    # number the screen carries — never a $ label.
    text = _pdf_text(pdf_bytes)
    assert "€300.00" in text
    assert "$300.00" not in text
