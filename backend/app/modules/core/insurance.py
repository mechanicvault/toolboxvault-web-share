"""My Insurance profile service (core module, Package C).

One profile per user: their insurer company, their agent's contact
block, their policy number, and free notes — the details a claim
needs, kept ONCE in Settings → My Insurance instead of retyped on
every claim (owner review round 1, item 17).

Consumers read through here, never the model (module law):
  - the claims module pre-fills a new claim's insurer + policy
    from the profile and SNAPSHOTS the agent block onto the claim
    at creation (claims owns that snapshot; later profile edits
    never rewrite a filed claim);
  - the data export ships the profile as insurance.json.

Everything is the user's own free text about their own policy —
nothing is verified against an insurer and nothing is ever shared;
the profile is visible only to its owner.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import models

_PROFILE_FIELDS = (
    "insurer_company",
    "agent_name",
    "agent_phone",
    "agent_email",
    "policy_number",
    "notes",
    # Policy depth (audit A9): strings ride the same strip path;
    # the money fields are typed and handled separately below.
    "policy_type",
    "valuation_basis",
    "how_to_file",
)

# The policy-type vocabulary (audit A9). "dedicated_tool" is a
# policy bought FOR the tools (inland marine / tool floater) —
# the one type the business-use sub-limit guidance never fires
# for, because covering business tools is its whole point.
POLICY_TYPES = ("homeowners", "renters", "commercial", "dedicated_tool", "other")
VALUATION_BASES = ("acv", "rcv")
_MONEY_FIELDS = ("deductible_cents", "coverage_limit_cents", "business_sub_limit_cents")


def _depth_view(profile: models.InsuranceProfile | None) -> dict:
    """The A9 depth fields as the API ships them (defaults when
    there is no profile yet)."""
    if profile is None:
        return {
            "policy_type": "",
            "deductible_cents": None,
            "coverage_limit_cents": None,
            "valuation_basis": "",
            "business_sub_limit_cents": None,
            "how_to_file": "",
        }
    return {
        "policy_type": profile.policy_type,
        "deductible_cents": profile.deductible_cents,
        "coverage_limit_cents": profile.coverage_limit_cents,
        "valuation_basis": profile.valuation_basis,
        "business_sub_limit_cents": profile.business_sub_limit_cents,
        "how_to_file": profile.how_to_file,
    }


def get_profile(db: Session, user_id: uuid.UUID) -> models.InsuranceProfile | None:
    return db.scalar(
        select(models.InsuranceProfile).where(
            models.InsuranceProfile.user_id == user_id
        )
    )


def profile_view(
    profile: models.InsuranceProfile | None, db: Session | None = None
) -> dict:
    """The profile as the API ships it. No profile yet reads as
    empty strings with has_profile=False — the settings form and
    the claim pre-fill both treat that as 'nothing to fill in'.

    Wave 3: the directory link rides along — insurer_company_id
    (None = free text only) plus the directory company's CURRENT
    name when a db handle is passed, so the form can show what
    the link points at even after the owner edited the name."""
    if profile is None:
        return {
            "has_profile": False,
            "insurer_company": "",
            "insurer_company_id": None,
            "insurer_company_name": "",
            "agent_name": "",
            "agent_phone": "",
            "agent_email": "",
            "policy_number": "",
            "notes": "",
            **_depth_view(None),
            "updated_at": None,
        }
    company_name = ""
    if profile.insurer_company_id is not None and db is not None:
        company = db.get(models.InsurerCompany, profile.insurer_company_id)
        company_name = company.name if company else ""
    return {
        "has_profile": True,
        "insurer_company": profile.insurer_company,
        "insurer_company_id": profile.insurer_company_id,
        "insurer_company_name": company_name,
        "agent_name": profile.agent_name,
        "agent_phone": profile.agent_phone,
        "agent_email": profile.agent_email,
        "policy_number": profile.policy_number,
        "notes": profile.notes,
        **_depth_view(profile),
        "updated_at": profile.updated_at,
    }


def upsert_profile(
    db: Session, user: models.User, **fields
) -> models.InsuranceProfile:
    """Create or replace the user's profile (the settings form
    edits the whole record at once). Unknown fields are ignored;
    known fields are stripped of padding the form didn't mean.

    Wave 3 directory pick: when insurer_company_id is sent, it
    must name a real directory company — picking FILLS
    insurer_company from the directory name (an explicit name in
    the same write wins, so the owner can adjust it in one save);
    sending None unlinks and the typed name stays as the free-text
    fallback."""
    profile = get_profile(db, user.id)
    if profile is None:
        profile = models.InsuranceProfile(user_id=user.id)
        db.add(profile)
    for field in _PROFILE_FIELDS:
        if field in fields:
            setattr(profile, field, (fields[field] or "").strip())
    # A9 depth: validate the two vocabularies, then the money.
    if profile.policy_type and profile.policy_type not in POLICY_TYPES:
        raise ValueError("Unknown policy type.")
    if profile.valuation_basis and profile.valuation_basis not in VALUATION_BASES:
        raise ValueError("Unknown valuation basis.")
    for field in _MONEY_FIELDS:
        if field in fields:
            value = fields[field]
            if value is not None and int(value) < 0:
                raise ValueError("Amounts can't be negative.")
            setattr(profile, field, None if value is None else int(value))
    if "insurer_company_id" in fields:
        company_id = fields["insurer_company_id"]
        if company_id is None:
            profile.insurer_company_id = None
        else:
            company = db.get(models.InsurerCompany, company_id)
            if company is None:
                raise ValueError("That insurer isn't in the directory.")
            profile.insurer_company_id = company.id
            if not (fields.get("insurer_company") or "").strip():
                profile.insurer_company = company.name
    db.commit()
    db.refresh(profile)
    return profile


def export_payload(db: Session, user_id: uuid.UUID) -> dict:
    """The export's insurance.json: the profile, or an explicit
    null-profile record so the file always exists and says so."""
    profile = get_profile(db, user_id)
    if profile is None:
        return {"profile": None}
    company_name = ""
    if profile.insurer_company_id is not None:
        company = db.get(models.InsurerCompany, profile.insurer_company_id)
        company_name = company.name if company else ""
    return {
        "profile": {
            "insurer_company": profile.insurer_company,
            # Wave 3: the directory link exports with the profile.
            "insurer_company_id": profile.insurer_company_id,
            "insurer_company_name": company_name,
            "agent_name": profile.agent_name,
            "agent_phone": profile.agent_phone,
            "agent_email": profile.agent_email,
            "policy_number": profile.policy_number,
            "notes": profile.notes,
            **_depth_view(profile),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }
    }
