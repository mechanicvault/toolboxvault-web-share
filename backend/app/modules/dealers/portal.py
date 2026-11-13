"""Dealer portal service (2026-10-19): the AGENT side of the
dealers module — profiles, company representations, public
listings, and the private -> platform agent switch.

Privacy rules (owner spec, 2026-10-18/19):
  - An agent's profile is PUBLIC only when THEY flip
    publicly_listed on (default OFF) AND they represent the
    company being viewed. There is no agent directory, no search,
    no enumeration — a profile surfaces on a company page or
    nowhere.
  - Public cards carry ONLY what the agent typed into their
    profile: display name, service area, bio, photo, and the
    contact fields they filled. The account email NEVER falls
    back in as a contact address.
  - "Preferred by" is an aggregate COUNT. No payload in this
    module ever names or lists the users who prefer an agent.
  - The private -> platform switch is manual, by exact account
    number, and lossless: the private record is archived (kept),
    preference rows re-point with provenance, and unlinking
    restores the record AND its rows. No auto-matching, ever.

Stage 2 (NOT here): truck accounts and in-app truck payments
ride on these profiles/representations when they ship.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import ALLOWED_CONTENT_TYPES, StorageError, storage
from app.modules.core import models as core_models
from app.modules.dealers import models, service
from app.modules.dealers.agent_codes import display_agent_code
from app.modules.inventory import thumbs

DEALER_GROUP = "tool_dealer"

_PROFILE_PHOTO_MAX_BYTES = settings.upload_max_mb * 1024 * 1024


# ---------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------


def get_profile(db: Session, user_id: uuid.UUID) -> models.AgentProfile | None:
    return (
        db.query(models.AgentProfile)
        .filter(models.AgentProfile.user_id == user_id)
        .first()
    )


def _photo_url(photo_key: str | None) -> str | None:
    if not photo_key:
        return None
    try:
        return storage.presigned_get_url(photo_key)
    except StorageError:
        return None


# Agent photos render SMALL everywhere they surface publicly —
# 56px on a company page's agent card, 28px in the Home
# widget's near-you strip — but uploads run to 10 MB and the
# presigned URL above serves the whole original into those
# slots (the prints-thumbnails audit, 2026-11-10: the same
# disease the 3D print shelf had). The card serializers
# therefore hand out the inventory pipeline's 128px rendition
# URL instead (signed_thumb_url — the ungated capability-URL
# endpoint, generated lazily from the preserved original).
# 128 covers both slots at 2x. _photo_url keeps the original
# for the owner's own profile editor, where the photo itself
# is being managed.
_AGENT_PHOTO_THUMB_WIDTH = 128


def _photo_thumb_url(photo_key: str | None) -> str | None:
    if not photo_key:
        return None
    return thumbs.signed_thumb_url(photo_key, _AGENT_PHOTO_THUMB_WIDTH)


def serialize_profile(user: core_models.User, profile: models.AgentProfile | None) -> dict:
    """MY profile view (the owner sees everything, including the
    listing switch and the photo's read URL). A user who never saved
    a profile gets the defaults: display name = account name,
    listing OFF. The area keys (dealer build) ride along: the
    territory geometry for the map editor, empty when unset."""
    from app.modules.dealers import areas, route_days

    if profile is None:
        return {
            "display_name": user.name,
            "phone": "",
            "contact_email": "",
            "service_area": "",
            "bio": "",
            "photo_url": None,
            "has_photo": False,
            "publicly_listed": False,
            "has_area": False,
            "route_frequency": None,
            "route_day_of_week": None,
            "route_anchor_date": None,
            "route_next_visit": None,
            **areas.area_summary(None),
        }
    return {
        "display_name": profile.display_name or user.name,
        "phone": profile.phone,
        "contact_email": profile.contact_email,
        "service_area": profile.service_area,
        "bio": profile.bio,
        "photo_url": _photo_url(profile.photo_key),
        "has_photo": bool(profile.photo_key),
        "publicly_listed": bool(profile.publicly_listed),
        "has_area": areas.profile_has_area(profile),
        "route_frequency": profile.route_frequency,
        "route_day_of_week": profile.route_day_of_week,
        "route_anchor_date": profile.route_anchor_date,
        "route_next_visit": route_days.route_next_visit_for(profile),
        **areas.area_summary(profile),
    }


def update_profile(
    db: Session, user: core_models.User, data: dict
) -> models.AgentProfile:
    """Save the profile. Area fields (dealer build) are validated
    as geometry and applied BEFORE the listing rule runs against
    the merged result — a payload may set an area and flip
    publicly_listed in one save, and the rule judges the final
    state. THE RULE (owner, 2026-10-20): a public listing REQUIRES
    a defined service area — Find-an-Agent matches geometry, so a
    listed agent with no area would be unreachable and invisible
    everywhere the listing is supposed to help."""
    from app.modules.dealers import areas

    profile = get_profile(db, user.id)
    if profile is None:
        profile = models.AgentProfile(user_id=user.id)
        db.add(profile)
    if "area_type" in data:
        # Geometry validates (and may refuse) before anything else
        # is touched, so a refused save changes nothing.
        cleaned = areas.validate_area(data)
        for key, value in cleaned.items():
            setattr(profile, key, value)
    for key in ("display_name", "phone", "contact_email", "service_area", "bio"):
        if key in data:
            setattr(profile, key, str(data[key] or "").strip())
    # Route schedule (audit A2): the schema already constrained
    # the shapes (frequency pattern, weekday range); here the
    # fields simply land (present key replaces, null clears).
    for key in ("route_frequency", "route_day_of_week", "route_anchor_date"):
        if key in data:
            setattr(profile, key, data[key])
    # The listing rule judges the FINAL state either way the save
    # got there: flipping the switch on with no area, AND clearing
    # the area out from under a live listing, both refuse.
    final_listed = (
        bool(data["publicly_listed"])
        if "publicly_listed" in data
        else bool(profile.publicly_listed)
    )
    if final_listed and not areas.profile_has_area(profile):
        db.rollback()
        raise service.DealerError(
            "Set your service area first — draw it on the map or "
            "use ZIP + radius — then turn the public listing on. "
            "A listing without an area can't be found by anyone."
        )
    if "publicly_listed" in data:
        profile.publicly_listed = final_listed
    db.commit()
    db.refresh(profile)
    return profile


# -- profile photo (shared attachment machinery: photo kind rules,
# -- presigned PUT, HEAD-verify before the key is kept) -----------------


def _photo_prefix(user_id: uuid.UUID) -> str:
    return f"{user_id}/dealer-profile/{user_id}/photo/"


def issue_profile_photo_url(user: core_models.User, data: dict) -> dict:
    content_type = str(data.get("content_type", "")).lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise service.DealerError(
            "Profile photos are JPG, PNG, or WebP images."
        )
    size = data.get("size_bytes")
    if size is not None:
        if size <= 0:
            raise service.DealerError("size_bytes must be positive")
        if size > _PROFILE_PHOTO_MAX_BYTES:
            raise service.DealerError(
                f"File too large: {size} bytes "
                f"(max {_PROFILE_PHOTO_MAX_BYTES // (1024 * 1024)} MB)"
            )
    key = storage.object_key(
        str(user.id),
        str(user.id),
        "photo",
        str(data.get("filename", "photo")),
        collection="dealer-profile",
    )
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise service.DealerError(str(exc)) from exc
    return {"upload_url": url, "key": key, "expires_in": 900}


def attach_profile_photo(
    db: Session, user: core_models.User, key: str
) -> models.AgentProfile:
    if not key.startswith(_photo_prefix(user.id)):
        raise service.DealerError("That upload doesn't belong to your profile.")
    try:
        stored = storage.head(key)
    except StorageError as exc:
        raise service.DealerError(str(exc)) from exc
    if stored.size_bytes > _PROFILE_PHOTO_MAX_BYTES:
        raise service.DealerError(
            f"File too large: {stored.size_bytes} bytes "
            f"(max {_PROFILE_PHOTO_MAX_BYTES // (1024 * 1024)} MB)"
        )
    if stored.content_type not in ALLOWED_CONTENT_TYPES["photo"]:
        raise service.DealerError(
            f"Uploaded content type '{stored.content_type}' isn't a photo."
        )
    # Content sniff (deep audit F4-06): bytes must match the declared
    # image type, not just claim it.
    try:
        storage.verify_content_matches(key, stored.content_type)
    except StorageError as exc:
        raise service.DealerError(str(exc)) from exc
    profile = get_profile(db, user.id)
    if profile is None:
        profile = models.AgentProfile(user_id=user.id)
        db.add(profile)
    old_key = profile.photo_key
    profile.photo_key = key
    db.commit()
    db.refresh(profile)
    if old_key and old_key != key:
        # Audit trail (2026-10-19): the replaced photo is
        # TOMBSTONED, not destroyed — restoring the profile brings
        # it back; the purge seam reclaims it after the window.
        from app.modules.core import journal

        journal.retire_keys(
            db, user.id, [old_key],
            entity_type="agent_profile", entity_id=profile.id,
        )
        db.commit()
    return profile


def remove_profile_photo(db: Session, user: core_models.User) -> models.AgentProfile | None:
    profile = get_profile(db, user.id)
    if profile is None or not profile.photo_key:
        return profile
    old_key = profile.photo_key
    profile.photo_key = None
    db.commit()
    # Tombstoned, not destroyed (audit trail — a restore of the
    # profile brings the photo back inside the retention window).
    from app.modules.core import journal

    journal.retire_keys(
        db, user.id, [old_key],
        entity_type="agent_profile", entity_id=profile.id,
    )
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------
# Representations
# ---------------------------------------------------------------------


def _require_dealer_group(user: core_models.User) -> None:
    if DEALER_GROUP not in (user.account_types or []):
        raise service.DealerError(
            "Company representation is for dealer accounts — add the "
            "Tool Dealer group to your account first."
        )


def serialize_representation(db: Session, row: models.CompanyRepresentation) -> dict:
    company = db.get(models.DealerCompany, row.company_id)
    return {
        "id": row.id,
        "company_id": row.company_id,
        "company_name": company.name if company else "",
        "verified": bool(row.verified),
        "created_at": row.created_at,
    }


def list_representations(
    db: Session, user_id: uuid.UUID
) -> list[models.CompanyRepresentation]:
    return (
        db.query(models.CompanyRepresentation)
        .filter(models.CompanyRepresentation.agent_user_id == user_id)
        .order_by(models.CompanyRepresentation.created_at.asc())
        .all()
    )


def add_representation(
    db: Session, user: core_models.User, company_id: uuid.UUID
) -> models.CompanyRepresentation:
    _require_dealer_group(user)
    company = service.get_directory_company(db, company_id)
    if company is None:
        # 404-shaped on purpose: private companies (mine or anyone's)
        # can't be represented and aren't confirmable here.
        raise service.DealerError("That company isn't in the directory.")
    existing = (
        db.query(models.CompanyRepresentation)
        .filter(
            models.CompanyRepresentation.agent_user_id == user.id,
            models.CompanyRepresentation.company_id == company.id,
        )
        .first()
    )
    if existing is not None:
        return existing
    row = models.CompanyRepresentation(agent_user_id=user.id, company_id=company.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_representation(db: Session, user_id: uuid.UUID, rep_id: uuid.UUID) -> bool:
    row = db.get(models.CompanyRepresentation, rep_id)
    if row is None or row.agent_user_id != user_id:
        return False
    db.delete(row)
    db.commit()
    return True


# -- operator review ----------------------------------------------------


def serialize_representation_admin(
    db: Session, row: models.CompanyRepresentation
) -> dict:
    agent = db.get(core_models.User, row.agent_user_id)
    company = db.get(models.DealerCompany, row.company_id)
    return {
        "id": row.id,
        "agent_user_id": row.agent_user_id,
        "agent_name": agent.name if agent else "",
        "agent_email": agent.email if agent else "",
        "agent_account_number": agent.account_number if agent else "",
        "company_id": row.company_id,
        "company_name": company.name if company else "",
        "verified": bool(row.verified),
        "verified_at": row.verified_at,
        "created_at": row.created_at,
    }


def list_representations_admin(db: Session) -> list[models.CompanyRepresentation]:
    return (
        db.query(models.CompanyRepresentation)
        .order_by(models.CompanyRepresentation.created_at.asc())
        .all()
    )


def set_representation_verified(
    db: Session, rep_id: uuid.UUID, verified: bool, operator_id: uuid.UUID
) -> models.CompanyRepresentation | None:
    row = db.get(models.CompanyRepresentation, rep_id)
    if row is None:
        return None
    row.verified = verified
    row.verified_by_id = operator_id if verified else None
    row.verified_at = datetime.now(timezone.utc) if verified else None
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------
# Public listing + company detail
# ---------------------------------------------------------------------


def public_agent_card(
    user: core_models.User,
    profile: models.AgentProfile,
    *,
    verified: bool,
) -> dict:
    """One agent card on a company page. EXACT key discipline: the
    identity keys are always present; every contact/display field
    appears ONLY when the agent filled it in — nothing falls back
    to account data, ever."""
    card: dict = {
        "agent_user_id": user.id,
        "display_name": profile.display_name or user.name,
        "verified": bool(verified),
    }
    if profile.service_area:
        card["service_area"] = profile.service_area
    if profile.bio:
        card["bio"] = profile.bio
    if profile.phone:
        card["phone"] = profile.phone
    if profile.contact_email:
        card["contact_email"] = profile.contact_email
    photo_url = _photo_thumb_url(profile.photo_key)
    if photo_url:
        card["photo_url"] = photo_url
    return card


def public_agents_for_company(
    db: Session, company: models.DealerCompany
) -> list[dict]:
    """The agents listed on a company page: profile publicly_listed
    ON + a representation of THIS (directory) company. Order:
    verified first, then name."""
    if not company.is_directory:
        return []
    reps = (
        db.query(models.CompanyRepresentation)
        .filter(models.CompanyRepresentation.company_id == company.id)
        .all()
    )
    cards = []
    for rep in reps:
        profile = get_profile(db, rep.agent_user_id)
        if profile is None or not profile.publicly_listed:
            continue
        user = db.get(core_models.User, rep.agent_user_id)
        if user is None or not user.is_active:
            continue
        cards.append(
            public_agent_card(user, profile, verified=bool(rep.verified))
        )
    cards.sort(key=lambda c: (not c["verified"], c["display_name"].lower()))
    return cards


def company_detail(db: Session, viewer: core_models.User, company) -> dict:
    return company_detail_for(db, viewer.id, company)


def company_detail_for(db: Session, viewer_id, company) -> dict:
    """The detail payload shaped for ONE viewer id: their
    personal layer over the directory values, the public
    agent cards (the same for every viewer), and THEIR
    preferred agents for the company."""
    return {
        "company": service.serialize_company_for_viewer(db, company, viewer_id),
        "agents": public_agents_for_company(db, company),
        "my_preferred_agents": [
            service.serialize_preferred(db, row)
            for row in service.list_preferred(db, viewer_id, company.id)
        ],
    }


def company_detail_as_visitor(db: Session, company) -> dict:
    """"View as visitor" (Sweep D5): the detail payload a
    signed-in member with NO relationship to this company
    receives — the company serialized with no viewer (the raw
    directory view: no personal layer), the public agent
    cards, and no preferred agents. Shaped by the visitor
    stand-in's nil id through the very same serializers the
    real member read runs."""
    from app.modules.core import visitor_preview

    return company_detail_for(db, visitor_preview.VISITOR_ID, company)


# ---------------------------------------------------------------------
# One-tap preferred (from a public agent card)
# ---------------------------------------------------------------------


def add_preferred_by_agent(
    db: Session,
    user_id: uuid.UUID,
    *,
    company_id: uuid.UUID,
    agent_user_id: uuid.UUID,
) -> tuple[models.PreferredAgent, bool]:
    """Add a PUBLIC agent as my preferred agent for their company.
    Refused (kindly, as a DealerError the UI words plainly) unless
    the agent is publicly listed AND represents this company — a
    one-tap add can never become a way to attach arbitrary users.
    Returns (row, created): created False = it was already there."""
    company = service.get_directory_company(db, company_id)
    if company is None:
        raise service.DealerError("That company isn't in the directory.")
    if agent_user_id == user_id:
        raise service.DealerError("You can't be your own preferred agent.")
    rep = (
        db.query(models.CompanyRepresentation)
        .filter(
            models.CompanyRepresentation.agent_user_id == agent_user_id,
            models.CompanyRepresentation.company_id == company.id,
        )
        .first()
    )
    profile = get_profile(db, agent_user_id)
    if rep is None or profile is None or not profile.publicly_listed:
        raise service.DealerError(
            "That agent isn't publicly listed for this company."
        )
    # The connection joins the roster (stage 1, 2026-11-04):
    # flagged preferred when it is the user's first agent for
    # the company, a plain connection otherwise.
    row, created = service._ensure_connection(
        db, user_id, company.id, agent_user_id=agent_user_id
    )
    db.commit()
    db.refresh(row)
    return row, created


def connect_local_agent(
    db: Session,
    user_id: uuid.UUID,
    *,
    company_id: uuid.UUID,
    agent_user_id: uuid.UUID,
) -> tuple[models.PreferredAgent, bool]:
    """Connect from Find local Agent (stage 3, 2026-11-05): the
    search-side twin of add_preferred_by_agent, held to the
    stage-3 findability bar the search itself applies — the agent
    must be publicly listed WITH a defined service area AND a
    VERIFIED representation of this company. Anything less and
    the search could never have shown him, so the connect refuses
    the same way. Returns (row, created) like its twin."""
    from app.modules.dealers import areas

    company = service.get_directory_company(db, company_id)
    if company is None:
        raise service.DealerError("That company isn't in the directory.")
    if agent_user_id == user_id:
        raise service.DealerError("You can't be your own preferred agent.")
    agent = db.get(core_models.User, agent_user_id)
    profile = get_profile(db, agent_user_id)
    if (
        agent is None
        or not agent.is_active
        or profile is None
        or not profile.publicly_listed
        or not areas.profile_has_area(profile)
    ):
        raise service.DealerError("That agent isn't listed for local search.")
    rep = (
        db.query(models.CompanyRepresentation)
        .filter(
            models.CompanyRepresentation.agent_user_id == agent_user_id,
            models.CompanyRepresentation.company_id == company.id,
            models.CompanyRepresentation.verified.is_(True),
        )
        .first()
    )
    if rep is None:
        raise service.DealerError(
            "That agent isn't a verified rep for this company."
        )
    row, created = service._ensure_connection(
        db, user_id, company.id, agent_user_id=agent_user_id
    )
    db.commit()
    db.refresh(row)
    return row, created


# ---------------------------------------------------------------------
# Private -> platform switch
# ---------------------------------------------------------------------


def serialize_private_agent_linked(db: Session, agent: models.PrivateAgent) -> dict:
    """The OWNER's view of their record — the only serializer
    family that carries the agent code and the takeover state.
    It backs owner-scoped endpoints only; nothing agent-facing
    or public ever renders it."""
    view = service.serialize_private_agent(db, agent)
    linked_number = None
    linked_name = None
    if agent.linked_user_id:
        linked = db.get(core_models.User, agent.linked_user_id)
        if linked is not None:
            linked_number = linked.account_number
            profile = db.scalar(
                select(models.AgentProfile).where(
                    models.AgentProfile.user_id == linked.id
                )
            )
            linked_name = (
                profile.display_name if profile and profile.display_name else linked.name
            )
    view.update(
        archived=bool(agent.archived),
        linked_account_number=linked_number,
        agent_code=agent.agent_code,
        agent_code_display=display_agent_code(agent.agent_code),
        link_source=agent.link_source,
        claimed_by_name=(
            linked_name if agent.link_source == "takeover" else None
        ),
        claimed_by_account_number=(
            linked_number if agent.link_source == "takeover" else None
        ),
    )
    return view


def link_private_agent(
    db: Session,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    account_number: str,
) -> models.PrivateAgent:
    """Switch one of MY private agent records to the platform
    account with this EXACT account number: my preference rows
    re-point at the platform user (with provenance), the private
    record archives. No auto-matching — the owner typed the
    number, the same one-door rule as platform linking."""
    agent = service.get_own_private_agent(db, user_id, agent_id)
    if agent is None:
        raise service.DealerError("That agent record isn't yours.")
    if agent.archived or agent.linked_user_id is not None:
        raise service.DealerError(
            "That record is already linked — unlink it first."
        )
    target = (
        db.query(core_models.User)
        .filter(
            core_models.User.account_number == account_number.strip().upper()
        )
        .first()
    )
    if target is None:
        raise service.DealerError(
            "No account with that account number — check it and try again."
        )
    if target.id == user_id:
        raise service.DealerError("You can't link an agent record to yourself.")

    rows = (
        db.query(models.PreferredAgent)
        .filter(
            models.PreferredAgent.user_id == user_id,
            models.PreferredAgent.private_agent_id == agent.id,
        )
        .all()
    )
    snapshot = []
    for row in rows:
        snapshot.append({"company_id": str(row.company_id)})
        clash = (
            db.query(models.PreferredAgent)
            .filter(
                models.PreferredAgent.user_id == user_id,
                models.PreferredAgent.company_id == row.company_id,
                models.PreferredAgent.agent_user_id == target.id,
            )
            .first()
        )
        if clash is not None:
            # Already preferred as the platform agent for this
            # company: the private-pointing row is a duplicate after
            # the switch. It goes away, but the snapshot remembers
            # it so unlink RECREATES it (lossless round trip).
            db.delete(row)
        else:
            row.agent_user_id = target.id
            row.private_agent_id = None
            row.switched_from_private_agent_id = agent.id
    agent.archived = True
    agent.linked_user_id = target.id
    agent.link_source = "switch"
    agent.link_snapshot = snapshot
    db.commit()
    db.refresh(agent)
    # The link is an IDENTITY MERGE (stage 1, 2026-11-04), not
    # an agent change: the owner declares this record IS that
    # account, so the claims seated with the record — always
    # that agent's claims, filed against his stand-in — seat
    # with the account now. Only claims seated at THIS record
    # move; the retired follow sweep moved whole dealers' worth
    # of claims on any record change, and nothing else does.
    from app.modules.claims import service as claims_service

    claims_service.repoint_claims_from_private_record(
        db, user_id, agent.id, target.id
    )
    return agent


def unlink_private_agent(
    db: Session, user_id: uuid.UUID, agent_id: uuid.UUID
) -> models.PrivateAgent:
    """Reverse a switch: rows that were re-pointed flip back to the
    private record, rows absorbed by a pre-existing platform
    preference are recreated from the link snapshot, and the
    record un-archives. Rows the owner made by OTHER paths (typed
    account number) carry no provenance and are left alone."""
    agent = service.get_own_private_agent(db, user_id, agent_id)
    if agent is None:
        raise service.DealerError("That agent record isn't yours.")
    if not agent.archived or agent.linked_user_id is None:
        raise service.DealerError("That record isn't linked to an account.")

    switched = (
        db.query(models.PreferredAgent)
        .filter(
            models.PreferredAgent.user_id == user_id,
            models.PreferredAgent.switched_from_private_agent_id == agent.id,
        )
        .all()
    )
    # Claims do NOT follow an unlink (stage 1, 2026-11-04):
    # seats never move silently — claims seated with the
    # platform account keep their seat (his verified seat still
    # reaches them), and the revived record starts fresh.
    covered_companies = set()
    for row in switched:
        row.private_agent_id = agent.id
        row.agent_user_id = None
        row.switched_from_private_agent_id = None
        covered_companies.add(row.company_id)
    for entry in agent.link_snapshot or []:
        try:
            company_id = uuid.UUID(str(entry.get("company_id")))
        except (ValueError, AttributeError):
            continue
        if company_id in covered_companies:
            continue
        already = (
            db.query(models.PreferredAgent)
            .filter(
                models.PreferredAgent.user_id == user_id,
                models.PreferredAgent.company_id == company_id,
                models.PreferredAgent.private_agent_id == agent.id,
            )
            .first()
        )
        if already is None:
            db.add(
                models.PreferredAgent(
                    user_id=user_id,
                    company_id=company_id,
                    private_agent_id=agent.id,
                )
            )
    agent.archived = False
    agent.linked_user_id = None
    agent.link_source = None
    agent.link_snapshot = []
    db.commit()
    db.refresh(agent)
    return agent


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The data export's dealers.json: everything dealer-shaped the
    user owns — private companies, private agent records (with
    their switch state), preference rows, the agent profile, and
    company representations. Directory companies are platform data
    and are referenced by name only."""
    profile = get_profile(db, owner_id)
    return {
        "private_companies": [
            service.serialize_company(c)
            for c in service.list_companies(db, owner_id)
            if not c.is_directory
        ],
        # Personal edits (2026-11-05): the user's own details
        # layered over directory dealers are HIS data — the
        # export carries the raw overrides (the directory rows
        # themselves stay platform data, referenced by name).
        "personal_company_edits": [
            service.serialize_personal_edit(db, edit)
            for edit in db.query(models.DealerCompanyPersonalEdit)
            .filter(models.DealerCompanyPersonalEdit.user_id == owner_id)
            .all()
        ],
        "private_agents": [
            serialize_private_agent_linked(db, a)
            for a in service.list_private_agents(db, owner_id)
        ],
        "preferred_agents": [
            service.serialize_preferred(db, row)
            for row in service.list_preferred(db, owner_id)
        ],
        "agent_profile": (
            serialize_profile(db.get(core_models.User, owner_id), profile)
            if profile is not None
            else None
        ),
        "representations": [
            serialize_representation(db, row)
            for row in list_representations(db, owner_id)
        ],
        # Warranty requests (dealer build): sent by me, and the
        # ones routed to / claimed by me as an agent — summaries,
        # the same snapshots the parties see in the app.
        **warranty_export(db, owner_id),
    }


def warranty_export(db: Session, owner_id: uuid.UUID) -> dict:
    from app.modules.dealers import warranty

    return warranty.export_rows(db, owner_id)


# ---------------------------------------------------------------------
# Dealer home stats
# ---------------------------------------------------------------------


def portal_stats(db: Session, user_id: uuid.UUID) -> dict:
    """The dealer home numbers for THIS agent. preferred_by is an
    aggregate count of preference rows naming this agent — the one
    number, never the identities behind it."""
    preferred_by = (
        db.query(models.PreferredAgent)
        .filter(models.PreferredAgent.agent_user_id == user_id)
        .count()
    )
    represented = (
        db.query(models.CompanyRepresentation)
        .filter(models.CompanyRepresentation.agent_user_id == user_id)
        .count()
    )
    profile = get_profile(db, user_id)
    listed = bool(profile and profile.publicly_listed)
    return {
        "preferred_by_count": int(preferred_by),
        "companies_represented_count": int(represented),
        "profile_visibility": "Public" if listed else "Private",
    }
