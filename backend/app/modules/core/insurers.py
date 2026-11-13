"""Insurer directory + affiliations service (core, wave 3).

Ryan's scope ruling (2026-10-20): insurer accounts are a
DIRECTORY + PROFILES + PICK-YOUR-INSURER — not direct claim
filing. Three pieces:

1. THE DIRECTORY (insurer_companies): platform rows curated by
   operators in Admin → Insurer directory. Starts EMPTY — no
   invented seed data. Every user may READ it (it's the pick
   list behind My Insurance and the affiliation form).
2. INSURER PROFILES (insurer_affiliations): an insurance-group
   user picks a directory company + their role at it. The link
   is UNVERIFIED until an operator verifies it (the dealer
   representation flow, audit rows included).
3. POLICYHOLDERS: a VERIFIED insurer user sees the users who
   BOTH picked their company in My Insurance AND enabled tier
   sharing toward the insurance group. The data itself comes
   through the EXISTING sharing.build_preview machinery — no new
   data path is built here, and picking a company alone shares
   NOTHING (pinned by test).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import models, sharing

INSURANCE_GROUP = "insurance"


class InsurerError(ValueError):
    """A refusal with a user-facing reason (routes answer 422)."""


class InsurerNotFound(InsurerError):
    """The company / affiliation doesn't exist (or isn't yours)."""


# -- directory ---------------------------------------------------------------------


def list_companies(db: Session) -> list[models.InsurerCompany]:
    return list(
        db.scalars(
            select(models.InsurerCompany).order_by(models.InsurerCompany.name.asc())
        )
    )


def get_company(db: Session, company_id: uuid.UUID) -> models.InsurerCompany | None:
    return db.get(models.InsurerCompany, company_id)


def _clean_phones(raw) -> list[dict]:
    phones = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        number = str(entry.get("number") or "").strip()
        if not number:
            continue
        phones.append(
            {"label": str(entry.get("label") or "").strip(), "number": number}
        )
    return phones


def create_company(db: Session, data: dict) -> models.InsurerCompany:
    name = (data.get("name") or "").strip()
    if not name:
        raise InsurerError("The company needs a name.")
    company = models.InsurerCompany(
        name=name,
        website=(data.get("website") or "").strip(),
        phones=_clean_phones(data.get("phones")),
        address=(data.get("address") or "").strip(),
        notes=(data.get("notes") or "").strip(),
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def update_company(
    db: Session, company: models.InsurerCompany, data: dict
) -> models.InsurerCompany:
    name = (data.get("name") or "").strip()
    if not name:
        raise InsurerError("The company needs a name.")
    company.name = name
    company.website = (data.get("website") or "").strip()
    company.phones = _clean_phones(data.get("phones"))
    company.address = (data.get("address") or "").strip()
    company.notes = (data.get("notes") or "").strip()
    db.commit()
    db.refresh(company)
    return company


def delete_company(db: Session, company: models.InsurerCompany) -> None:
    """Directory delete: affiliations CASCADE (they named this
    company), My Insurance links SET NULL (the typed name on the
    profile survives — the dealer-directory rule: names stay).
    Both effects are applied EXPLICITLY here rather than left to
    the FK actions alone, so the behavior is identical on every
    database (and provable in tests)."""
    db.query(models.InsurerAffiliation).filter(
        models.InsurerAffiliation.company_id == company.id
    ).delete(synchronize_session=False)
    db.query(models.InsuranceProfile).filter(
        models.InsuranceProfile.insurer_company_id == company.id
    ).update(
        {models.InsuranceProfile.insurer_company_id: None},
        synchronize_session=False,
    )
    db.delete(company)
    db.commit()


def company_view(company: models.InsurerCompany) -> dict:
    return {
        "id": company.id,
        "name": company.name,
        "website": company.website,
        "phones": company.phones or [],
        "address": company.address,
        "notes": company.notes,
        "created_at": company.created_at,
        "updated_at": company.updated_at,
    }


# -- affiliations ---------------------------------------------------------------------


def _require_insurance_group(user: models.User) -> None:
    if INSURANCE_GROUP not in (user.account_types or []):
        raise InsurerError(
            "Insurer profiles belong to accounts in the Insurance group."
        )


def my_affiliation(
    db: Session, user_id: uuid.UUID
) -> models.InsurerAffiliation | None:
    return db.scalars(
        select(models.InsurerAffiliation)
        .where(models.InsurerAffiliation.user_id == user_id)
        .order_by(models.InsurerAffiliation.created_at.asc())
    ).first()


def set_affiliation(
    db: Session, user: models.User, company_id: uuid.UUID, role_at_company: str
) -> models.InsurerAffiliation:
    """Pick (or change) my company. ONE affiliation per user in
    v1 — the profile names the company they represent; changing
    the company resets verification (a fresh claim to review)."""
    _require_insurance_group(user)
    company = get_company(db, company_id)
    if company is None:
        raise InsurerNotFound("That insurer isn't in the directory.")
    row = my_affiliation(db, user.id)
    if row is None:
        row = models.InsurerAffiliation(user_id=user.id, company_id=company.id)
        db.add(row)
    else:
        if row.company_id != company.id:
            row.verified = False
            row.verified_by_id = None
            row.verified_at = None
        row.company_id = company.id
    row.role_at_company = (role_at_company or "").strip()
    db.commit()
    db.refresh(row)
    return row


def clear_affiliation(db: Session, user: models.User) -> bool:
    row = my_affiliation(db, user.id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def affiliation_view(db: Session, row: models.InsurerAffiliation) -> dict:
    company = get_company(db, row.company_id)
    return {
        "id": row.id,
        "company_id": row.company_id,
        "company_name": company.name if company else "",
        "role_at_company": row.role_at_company,
        "verified": bool(row.verified),
        "created_at": row.created_at,
    }


def list_affiliations_admin(db: Session) -> list[models.InsurerAffiliation]:
    return list(
        db.scalars(
            select(models.InsurerAffiliation).order_by(
                models.InsurerAffiliation.created_at.asc()
            )
        )
    )


def affiliation_admin_view(db: Session, row: models.InsurerAffiliation) -> dict:
    view = affiliation_view(db, row)
    user = db.get(models.User, row.user_id)
    view.update(
        {
            "user_id": row.user_id,
            "user_name": user.name if user else "",
            "user_email": user.email if user else "",
            "user_account_number": user.account_number if user else "",
            "verified_at": row.verified_at,
        }
    )
    return view


def set_affiliation_verified(
    db: Session, affiliation_id: uuid.UUID, verified: bool, operator_id: uuid.UUID
) -> models.InsurerAffiliation | None:
    from datetime import datetime, timezone

    row = db.get(models.InsurerAffiliation, affiliation_id)
    if row is None:
        return None
    row.verified = bool(verified)
    row.verified_by_id = operator_id if verified else None
    row.verified_at = datetime.now(timezone.utc) if verified else None
    db.commit()
    db.refresh(row)
    return row


def verified_affiliation(
    db: Session, user_id: uuid.UUID
) -> models.InsurerAffiliation | None:
    row = my_affiliation(db, user_id)
    if row is not None and row.verified:
        return row
    return None


# -- policyholders -----------------------------------------------------------------------


def list_policyholders(db: Session, insurer_user: models.User) -> list[dict]:
    """The verified insurer's policyholder directory: users who
    picked THIS company in My Insurance AND have tier sharing
    enabled toward the insurance group. Unverified affiliation →
    InsurerError (the surface simply doesn't exist for them)."""
    affiliation = verified_affiliation(db, insurer_user.id)
    if affiliation is None:
        raise InsurerError(
            "Policyholders unlock once an operator verifies your "
            "insurer affiliation."
        )
    profiles = list(
        db.scalars(
            select(models.InsuranceProfile).where(
                models.InsuranceProfile.insurer_company_id == affiliation.company_id
            )
        )
    )
    out = []
    for profile in profiles:
        if profile.user_id == insurer_user.id:
            continue
        config = db.scalars(
            select(models.ShareConfig).where(
                models.ShareConfig.owner_id == profile.user_id,
                models.ShareConfig.recipient_group == INSURANCE_GROUP,
            )
        ).first()
        if config is None or not config.enabled:
            continue  # picked us, but sharing is OFF — nothing shows
        owner = db.get(models.User, profile.user_id)
        if owner is None:
            continue
        preview = sharing.build_preview(db, profile.user_id, INSURANCE_GROUP)
        out.append(
            {
                "user_id": profile.user_id,
                "name": owner.name or "",
                "account_number": owner.account_number,
                "item_count": len(preview),
            }
        )
    out.sort(key=lambda r: (r["name"] or "").lower())
    return out


def policyholder_preview(
    db: Session, insurer_user: models.User, policyholder_id: uuid.UUID
) -> list[dict]:
    """One policyholder's shared preview — through the EXISTING
    build_preview machinery, gated by the same BOTH conditions
    as the directory listing (picked this company + sharing on).
    Anything else answers as if it doesn't exist."""
    affiliation = verified_affiliation(db, insurer_user.id)
    if affiliation is None:
        raise InsurerError(
            "Policyholders unlock once an operator verifies your "
            "insurer affiliation."
        )
    profile = db.scalars(
        select(models.InsuranceProfile).where(
            models.InsuranceProfile.user_id == policyholder_id,
            models.InsuranceProfile.insurer_company_id == affiliation.company_id,
        )
    ).first()
    if profile is None:
        raise InsurerNotFound("That policyholder isn't in your book.")
    config = db.scalars(
        select(models.ShareConfig).where(
            models.ShareConfig.owner_id == policyholder_id,
            models.ShareConfig.recipient_group == INSURANCE_GROUP,
        )
    ).first()
    if config is None or not config.enabled:
        # Picked us, but sharing is OFF — reads as not-in-book,
        # exactly like the directory listing's gate.
        raise InsurerNotFound("That policyholder isn't in your book.")
    return sharing.build_preview(db, policyholder_id, INSURANCE_GROUP)
