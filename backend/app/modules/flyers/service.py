"""Flyers service — sources, posting rights, visibility, the
three intake routes, and the standing-pull job.

THE MODEL (owner order, 2026-11-05 19:09 #10/10a/10b):

- A SOURCE is one flyer spot: a dealer COMPANY, or one AGENT
  (a platform agent — a site user — or a private agent record).
- POSTING RIGHTS (owner, tightened 2026-11-06 22:15: "only a
  registered dealer or agent should be able to upload the
  flyer, not a mechanic, and even if the mechanic adds their
  own agent, that should not give them the access to upload
  flyers. Mechanics should only be able to view flyers."):
  a company's flyers are posted by the company-owning DEALER
  account or by a user with a VERIFIED representation of that
  company; a platform agent posts his OWN agent flyers for a
  company he represents — nobody posts for him; a private
  (unclaimed) agent record confers NO posting rights on
  anyone, whoever created it, and neither does a private
  company owned by a non-dealer account. Private spots stay
  visible to their owner — only posting is gone. Each
  dealer/source is responsible for its own flyers — nobody
  else can post to a spot. The platform's official flyer link
  pull (run_standing_pulls) is a SYSTEM actor, not a user,
  and is not gated by these rights.
- VISIBILITY (who counts as CONNECTED to a source):
  - company source: users whose dealer list carries the
    company (a directory company they haven't hidden, or
    their own company);
  - platform agent source: users with a connection row to
    that agent at that company (the dealers roster);
  - private agent source: the record's owner alone (a private
    record is one user's own book).
  The SAME audience receives the new-flyer notification —
  what you can see is what you can be alerted about — minus
  the poster, and minus anyone who flipped the flyer alert's
  own off switch.
- A source's `visible` switch turns its whole spot off;
  `history_visible` gates past flyers for viewers (posters
  always see their own full history).
- CURRENT = the live flyer whose window covers today
  (newest posted wins an overlap). Expired flyers come down
  on their own: every read filters on the window.
"""

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import StorageError, storage
from app.modules.core import inbox
from app.modules.dealers import models as dealer_models
from app.modules.dealers import service as dealers_service
from app.modules.flyers import models, render, scan

PDF_MAX_BYTES = 25 * 1024 * 1024  # the documents cap (attachments)
PHOTO_MAX_BYTES = 10 * 1024 * 1024  # the photo cap
MAX_SCAN_PAGES = 12

_KIND_LABEL = {models.KIND_COMPANY: "company", models.KIND_AGENT: "agent"}


class FlyerError(ValueError):
    """Caller turns this into a 4xx."""


class FlyerNotFound(FlyerError):
    """Routes answer 404 for this subclass."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now().date()


# ---------------------------------------------------------------- sources


def source_key(source: models.FlyerSource) -> str:
    """The stable tab/widget identity of a source. The company
    rides in every key: one agent can serve several dealers,
    and each of those spots is its own tab."""
    if source.kind == models.KIND_COMPANY:
        return f"company:{source.company_id}"
    if source.agent_user_id is not None:
        return f"agent:{source.company_id}:{source.agent_user_id}"
    return f"private:{source.company_id}:{source.private_agent_id}"


def _company(db: Session, company_id: uuid.UUID) -> dealer_models.DealerCompany:
    company = db.get(dealer_models.DealerCompany, company_id)
    if company is None:
        raise FlyerNotFound("That dealer no longer exists.")
    return company


def _representation(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> dealer_models.CompanyRepresentation | None:
    return db.scalar(
        select(dealer_models.CompanyRepresentation).where(
            dealer_models.CompanyRepresentation.agent_user_id == user_id,
            dealer_models.CompanyRepresentation.company_id == company_id,
        )
    )


def _is_dealer_account(user) -> bool:
    """A REGISTERED dealer account: the tool_dealer group is on
    the account (the dealers portal's DEALER_GROUP test)."""
    return "tool_dealer" in (user.account_types or [])


def can_post_source(db: Session, user, source: models.FlyerSource) -> bool:
    """May THIS user post to / manage this source? (The gate,
    owner 2026-11-06 22:15 — see the module docstring.)"""
    if source.kind == models.KIND_COMPANY:
        company = db.get(dealer_models.DealerCompany, source.company_id)
        if (
            company is not None
            and company.owner_id == user.id
            and _is_dealer_account(user)
        ):
            return True
        rep = _representation(db, user.id, source.company_id)
        return bool(rep and rep.verified)
    if source.agent_user_id is not None:
        return source.agent_user_id == user.id
    # A private-agent spot: posting was removed entirely — a
    # private record confers no posting rights, whoever owns it.
    return False


def _assert_postable_shape(
    db: Session,
    user,
    *,
    kind: str,
    company_id: uuid.UUID,
    agent_user_id: uuid.UUID | None,
    private_agent_id: uuid.UUID | None,
) -> dealer_models.DealerCompany:
    """Validate a would-be source's identity + the caller's
    right to run it. Returns the company."""
    company = _company(db, company_id)
    if kind == models.KIND_COMPANY:
        if company.owner_id == user.id and _is_dealer_account(user):
            return company
        rep = _representation(db, user.id, company_id)
        if rep is None or not rep.verified:
            raise FlyerError(
                "Only the dealer's own account or a verified "
                "representative of this dealer can post its flyers."
            )
        return company
    if kind != models.KIND_AGENT:
        raise FlyerError("A flyer spot is a dealer's or an agent's.")
    if (agent_user_id is None) == (private_agent_id is None):
        raise FlyerError("An agent spot names exactly one agent.")
    if agent_user_id is not None:
        if agent_user_id != user.id:
            raise FlyerError("An agent posts his own flyers — nobody else's.")
        if _representation(db, user.id, company_id) is None:
            raise FlyerError(
                "You can only post agent flyers for a dealer you represent."
            )
        return company
    # A private (unclaimed) agent record opens no spot anymore:
    # posting belongs to registered dealers and agents only,
    # and adding your own agent record confers none of it.
    raise FlyerError(
        "Flyers are posted by a registered dealer or the agent "
        "himself — an agent record you added yourself can't post."
    )


def get_or_create_source(
    db: Session,
    user,
    *,
    kind: str,
    company_id: uuid.UUID,
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
) -> models.FlyerSource:
    _assert_postable_shape(
        db,
        user,
        kind=kind,
        company_id=company_id,
        agent_user_id=agent_user_id,
        private_agent_id=private_agent_id,
    )
    query = select(models.FlyerSource).where(
        models.FlyerSource.kind == kind,
        models.FlyerSource.company_id == company_id,
    )
    if kind == models.KIND_AGENT:
        if agent_user_id is not None:
            query = query.where(
                models.FlyerSource.agent_user_id == agent_user_id
            )
        else:
            query = query.where(
                models.FlyerSource.private_agent_id == private_agent_id
            )
    source = db.scalar(query)
    if source is None:
        source = models.FlyerSource(
            kind=kind,
            company_id=company_id,
            agent_user_id=agent_user_id,
            private_agent_id=private_agent_id,
            created_by_id=user.id,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
    return source


def get_source(db: Session, source_id: uuid.UUID) -> models.FlyerSource:
    source = db.get(models.FlyerSource, source_id)
    if source is None:
        raise FlyerNotFound("That flyer spot no longer exists.")
    return source


def update_source_settings(
    db: Session,
    user,
    source: models.FlyerSource,
    *,
    visible: bool | None = None,
    history_visible: bool | None = None,
    standing_url: str | None = None,
) -> models.FlyerSource:
    if not can_post_source(db, user, source):
        raise FlyerError("Only the flyer's owner can change its settings.")
    if visible is not None:
        source.visible = visible
    if history_visible is not None:
        source.history_visible = history_visible
    if standing_url is not None:
        url = standing_url.strip()
        if url and "://" not in url:
            url = "https://" + url
        source.standing_url = url
        # A changed address starts the dedupe fresh: whatever
        # the new spot holds is a new flyer waiting to post.
        source.standing_hash = None
        source.standing_checked_at = None
    source.updated_at = _now()
    db.commit()
    db.refresh(source)
    return source


# ------------------------------------------------------------- visibility


def _user_company_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """The companies in the user's dealer list: directory
    companies they haven't hidden + their own companies."""
    hidden = dealers_service.hidden_company_ids(db, user_id)
    rows = db.scalars(
        select(dealer_models.DealerCompany.id).where(
            (dealer_models.DealerCompany.is_directory.is_(True))
            | (dealer_models.DealerCompany.owner_id == user_id)
        )
    ).all()
    return {row for row in rows if row not in hidden}


def source_visible_to(
    db: Session, user_id: uuid.UUID, source: models.FlyerSource
) -> bool:
    """The CONNECTED test for one source (see the module
    docstring). The source's own switch comes first."""
    if not source.visible:
        return False
    if source.kind == models.KIND_COMPANY:
        return source.company_id in _user_company_ids(db, user_id)
    if source.agent_user_id is not None:
        connection = db.scalar(
            select(dealer_models.PreferredAgent.id).where(
                dealer_models.PreferredAgent.user_id == user_id,
                dealer_models.PreferredAgent.company_id == source.company_id,
                dealer_models.PreferredAgent.agent_user_id
                == source.agent_user_id,
            )
        )
        return connection is not None
    record = db.get(dealer_models.PrivateAgent, source.private_agent_id)
    return bool(record and record.owner_id == user_id)


def visible_sources(db: Session, user_id: uuid.UUID) -> list[models.FlyerSource]:
    """Every source this user is connected to (spot on)."""
    sources = db.scalars(
        select(models.FlyerSource).order_by(models.FlyerSource.created_at)
    ).all()
    return [s for s in sources if source_visible_to(db, user_id, s)]


def audience_user_ids(
    db: Session, source: models.FlyerSource, *, exclude: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Every user connected to this source — the notification
    audience. Mirrors source_visible_to over all users."""
    if not source.visible:
        return []
    ids: set[uuid.UUID] = set()
    if source.kind == models.KIND_COMPANY:
        from app.modules.core import models as core_models

        hidden_pairs = db.execute(
            select(
                dealer_models.DealerListHidden.user_id,
            ).where(
                dealer_models.DealerListHidden.company_id == source.company_id
            )
        ).scalars()
        hidden = set(hidden_pairs)
        company = db.get(dealer_models.DealerCompany, source.company_id)
        if company is not None and company.is_directory:
            ids = set(
                db.scalars(select(core_models.User.id)).all()
            ) - hidden
        elif company is not None and company.owner_id is not None:
            ids = {company.owner_id}
    elif source.agent_user_id is not None:
        ids = set(
            db.scalars(
                select(dealer_models.PreferredAgent.user_id).where(
                    dealer_models.PreferredAgent.company_id
                    == source.company_id,
                    dealer_models.PreferredAgent.agent_user_id
                    == source.agent_user_id,
                )
            ).all()
        )
    else:
        record = db.get(dealer_models.PrivateAgent, source.private_agent_id)
        if record is not None:
            ids = {record.owner_id}
    if exclude is not None:
        ids.discard(exclude)
    return sorted(ids, key=str)


# ------------------------------------------------------------ flyer reads


def current_flyer(
    db: Session, source_id: uuid.UUID, today: date | None = None
) -> models.Flyer | None:
    today = today or _today()
    return db.scalar(
        select(models.Flyer)
        .where(
            models.Flyer.source_id == source_id,
            models.Flyer.starts_on <= today,
            models.Flyer.ends_on >= today,
        )
        .order_by(models.Flyer.created_at.desc(), models.Flyer.id.desc())
        .limit(1)
    )


def source_history(
    db: Session, source: models.FlyerSource, today: date | None = None
) -> list[models.Flyer]:
    """Past flyers, newest first — everything that isn't the
    current one (expired, superseded, or not yet started)."""
    current = current_flyer(db, source.id, today)
    rows = db.scalars(
        select(models.Flyer)
        .where(models.Flyer.source_id == source.id)
        .order_by(models.Flyer.created_at.desc(), models.Flyer.id.desc())
    ).all()
    return [row for row in rows if current is None or row.id != current.id]


def _agent_name(db: Session, source: models.FlyerSource) -> str:
    if source.agent_user_id is not None:
        facts = dealers_service._platform_facts(db, source.agent_user_id)
        return facts.get("name") or ""
    if source.private_agent_id is not None:
        record = db.get(dealer_models.PrivateAgent, source.private_agent_id)
        return record.name if record is not None else ""
    return ""


def _signed(key: str | None) -> str | None:
    if not key:
        return None
    try:
        return storage.presigned_get_url(key)
    except StorageError:
        return None


def flyer_view(flyer: models.Flyer, *, is_current: bool) -> dict:
    return {
        "id": flyer.id,
        "label": flyer.label,
        "page_count": flyer.page_count,
        "origin": flyer.origin,
        "starts_on": flyer.starts_on,
        "ends_on": flyer.ends_on,
        "thumb_url": _signed(flyer.thumb_key),
        "pdf_url": _signed(flyer.pdf_key),
        "is_current": is_current,
        "created_at": flyer.created_at,
    }


def source_view(
    db: Session,
    user,
    source: models.FlyerSource,
    *,
    with_history: bool = False,
    today: date | None = None,
) -> dict:
    company = db.get(dealer_models.DealerCompany, source.company_id)
    company_name = ""
    if company is not None:
        view = dealers_service.serialize_company_for_viewer(
            db, company, user.id
        )
        company_name = view.get("name") or company.name
    current = current_flyer(db, source.id, today)
    mine = can_post_source(db, user, source)
    view = {
        "id": source.id,
        "key": source_key(source),
        "kind": source.kind,
        "company_id": source.company_id,
        "company_name": company_name,
        "agent_user_id": source.agent_user_id,
        "private_agent_id": source.private_agent_id,
        "agent_name": _agent_name(db, source) if source.kind == "agent" else "",
        "visible": source.visible,
        "history_visible": source.history_visible,
        "standing_url": source.standing_url,
        "can_post": mine,
        "current": flyer_view(current, is_current=True) if current else None,
        "history": [],
    }
    if with_history and (mine or source.history_visible):
        view["history"] = [
            flyer_view(row, is_current=False)
            for row in source_history(db, source, today)
        ]
    return view


def feed(db: Session, user) -> list[dict]:
    """The Home widget / flyer page feed: connected sources
    WITH a current flyer, freshest first."""
    views = []
    for source in visible_sources(db, user.id):
        current = current_flyer(db, source.id)
        if current is None:
            continue
        views.append(source_view(db, user, source))
    views.sort(
        key=lambda v: (v["current"]["created_at"], str(v["id"])),
        reverse=True,
    )
    return views


def postable_sources(db: Session, user) -> list[dict]:
    """The spots this user may post to or manage — existing
    sources they control, plus the spots they could open
    (returned with id None so the UI can offer them)."""
    out: list[dict] = []
    existing = db.scalars(select(models.FlyerSource)).all()
    by_identity: dict[tuple, models.FlyerSource] = {}
    for source in existing:
        by_identity[
            (
                source.kind,
                source.company_id,
                source.agent_user_id,
                source.private_agent_id,
            )
        ] = source

    def _entry(kind, company, agent_user_id=None, private_agent_id=None, agent_name=""):
        source = by_identity.get(
            (kind, company.id, agent_user_id, private_agent_id)
        )
        if source is not None:
            return source_view(db, user, source, with_history=True)
        return {
            "id": None,
            "key": (
                f"company:{company.id}"
                if kind == models.KIND_COMPANY
                else (
                    f"agent:{company.id}:{agent_user_id}"
                    if agent_user_id is not None
                    else f"private:{company.id}:{private_agent_id}"
                )
            ),
            "kind": kind,
            "company_id": company.id,
            "company_name": company.name,
            "agent_user_id": agent_user_id,
            "private_agent_id": private_agent_id,
            "agent_name": agent_name,
            "visible": True,
            "history_visible": True,
            "standing_url": "",
            "can_post": True,
            "current": None,
            "history": [],
        }

    # Company spots: verified representations + own companies
    # (the own-company seat posts only as a DEALER account —
    # a private company owned by a non-dealer confers nothing).
    reps = db.scalars(
        select(dealer_models.CompanyRepresentation).where(
            dealer_models.CompanyRepresentation.agent_user_id == user.id,
            dealer_models.CompanyRepresentation.verified.is_(True),
        )
    ).all()
    company_ids = {rep.company_id for rep in reps}
    if _is_dealer_account(user):
        own = db.scalars(
            select(dealer_models.DealerCompany).where(
                dealer_models.DealerCompany.owner_id == user.id
            )
        ).all()
        company_ids.update(c.id for c in own)
    for company_id in sorted(company_ids, key=str):
        company = db.get(dealer_models.DealerCompany, company_id)
        if company is not None:
            out.append(_entry(models.KIND_COMPANY, company))
    # My own agent spots: one per company I represent.
    my_reps = db.scalars(
        select(dealer_models.CompanyRepresentation).where(
            dealer_models.CompanyRepresentation.agent_user_id == user.id
        )
    ).all()
    facts_name = None
    for rep in sorted(my_reps, key=lambda r: str(r.company_id)):
        company = db.get(dealer_models.DealerCompany, rep.company_id)
        if company is None:
            continue
        if facts_name is None:
            facts_name = dealers_service._platform_facts(db, user.id).get(
                "name"
            ) or user.name
        out.append(
            _entry(
                models.KIND_AGENT,
                company,
                agent_user_id=user.id,
                agent_name=facts_name,
            )
        )
    # Private records are NOT offered: an unclaimed agent
    # record confers no posting rights (owner, 2026-11-06), so
    # no spot is ever listed for one.
    return out


def company_tab(db: Session, user, company_id: uuid.UUID) -> dict:
    """The dealer page's Flyers tab: this company's sources —
    the company's own spot plus its agents' spots — as the
    viewer may see them, and the postable state for the
    posting controls."""
    company = dealers_service.visible_company(db, user.id, company_id)
    if company is None:
        raise FlyerNotFound("That dealer isn't on your list.")
    sources = db.scalars(
        select(models.FlyerSource).where(
            models.FlyerSource.company_id == company_id
        )
    ).all()
    views = []
    for source in sources:
        if source_visible_to(db, user.id, source) or can_post_source(
            db, user, source
        ):
            views.append(source_view(db, user, source, with_history=True))
    postable = [
        entry
        for entry in postable_sources(db, user)
        if entry["company_id"] == company_id
    ]
    return {
        "company_id": company_id,
        "sources": views,
        "postable": postable,
    }


# ------------------------------------------------------------ notifications


def alerts_enabled(db: Session, user_id: uuid.UUID) -> bool:
    """The flyer alert's own switch: default ON, a stored row
    only where the user flipped it."""
    row = db.get(models.FlyerAlertPref, user_id)
    return True if row is None else bool(row.enabled)


def set_alerts_enabled(db: Session, user_id: uuid.UUID, enabled: bool) -> bool:
    row = db.get(models.FlyerAlertPref, user_id)
    if row is None:
        row = models.FlyerAlertPref(user_id=user_id, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
        row.updated_at = _now()
    db.commit()
    return enabled


def _notify_new_flyer(
    db: Session, source: models.FlyerSource, flyer: models.Flyer, poster_id
) -> int:
    """Tell the source's connected audience (minus the poster,
    minus alert opt-outs) in the flyer's own commit."""
    company = db.get(dealer_models.DealerCompany, source.company_id)
    company_name = company.name if company is not None else "A dealer"
    agent_name = _agent_name(db, source)
    who = f"{agent_name} at {company_name}" if agent_name else company_name
    sent = 0
    for user_id in audience_user_ids(db, source, exclude=poster_id):
        if not alerts_enabled(db, user_id):
            continue
        inbox.create_notification(
            db,
            user_id,
            kind=inbox.KIND_FLYER_POSTED,
            title="New dealer flyer",
            body=f"{who} posted a new flyer.",
            data={
                "source_key": source_key(source),
                "source_id": str(source.id),
                "flyer_id": str(flyer.id),
                "company_id": str(source.company_id),
            },
            commit=False,
        )
        sent += 1
    return sent


# ---------------------------------------------------------------- posting


def _validate_window(starts_on: date, ends_on: date) -> None:
    if ends_on < starts_on:
        raise FlyerError("The flyer's end date is before its start date.")
    if ends_on < _today():
        raise FlyerError(
            "That flyer is already over — pick an end date in the future."
        )


def _store_flyer(
    db: Session,
    user,
    source: models.FlyerSource,
    data: bytes,
    *,
    origin: str,
    origin_url: str,
    label: str,
    starts_on: date,
    ends_on: date,
    notify: bool = True,
) -> models.Flyer:
    """The one door every intake route posts through: PDF
    discipline (magic + cap), thumbnail + page count rendered
    once, bytes to storage, row, notifications."""
    if len(data) > PDF_MAX_BYTES:
        raise FlyerError(
            f"That PDF is too large ({len(data)} bytes; "
            f"max {PDF_MAX_BYTES // (1024 * 1024)} MB)."
        )
    if data[:5] != b"%PDF-":
        raise FlyerError("That file isn't a PDF — flyers are PDFs.")
    try:
        thumb, page_count = render.pdf_thumbnail_jpeg(data)
    except render.RenderError as exc:
        raise FlyerError(str(exc)) from exc
    flyer = models.Flyer(
        source_id=source.id,
        label=(label or "").strip()[:300],
        pdf_key="",
        thumb_key=None,
        page_count=page_count,
        content_hash=hashlib.sha256(data).hexdigest(),
        origin=origin,
        origin_url=origin_url or "",
        starts_on=starts_on,
        ends_on=ends_on,
        posted_by_id=user.id if user is not None else None,
    )
    db.add(flyer)
    db.flush()
    pdf_key = f"flyers/{source.id}/{flyer.id}.pdf"
    thumb_key = f"flyers/{source.id}/{flyer.id}-thumb.jpg"
    try:
        storage.put_bytes(pdf_key, data, "application/pdf")
        storage.put_bytes(thumb_key, thumb, "image/jpeg")
    except StorageError as exc:
        db.rollback()
        raise FlyerError(str(exc)) from exc
    flyer.pdf_key = pdf_key
    flyer.thumb_key = thumb_key
    if notify and user is not None:
        _notify_new_flyer(db, source, flyer, user.id)
    db.commit()
    db.refresh(flyer)
    return flyer


def post_from_link(
    db: Session,
    user,
    source: models.FlyerSource,
    *,
    url: str,
    label: str,
    starts_on: date,
    ends_on: date,
) -> models.Flyer:
    """Intake route 1: paste a website link — the site fetches
    and downloads the flyer through the manuals import's
    SSRF-guarded fetch (https only, every hop re-validated,
    size-capped; PDFs only, judged by the magic bytes)."""
    if not can_post_source(db, user, source):
        raise FlyerError("You can't post flyers to this spot.")
    _validate_window(starts_on, ends_on)
    from app.modules.catalog import manuals

    raw = (url or "").strip()
    if not raw:
        raise FlyerError("Paste the flyer's web address first.")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        data, _content_type = manuals._download(raw)
    except manuals.ManualError as exc:
        raise FlyerError(str(exc)) from exc
    return _store_flyer(
        db,
        user,
        source,
        data,
        origin=models.ORIGIN_LINK,
        origin_url=raw,
        label=label,
        starts_on=starts_on,
        ends_on=ends_on,
    )


# -- staging uploads (the presigned discipline: bytes never
#    pass through the API; the post call verifies the object
#    before a byte is trusted) --------------------------------


def _staging_key(user_id: uuid.UUID, filename: str, ext: str) -> str:
    safe = storage.safe_filename(filename) or f"file{ext}"
    if "." not in safe:
        safe = safe + ext
    return f"flyer-staging/{user_id}/{uuid.uuid4().hex}-{safe}"


def issue_pdf_upload_url(
    user, *, filename: str, content_type: str, size_bytes: int | None
) -> dict:
    content_type = (content_type or "").lower().strip()
    if content_type != "application/pdf":
        raise FlyerError("Flyers are PDFs — that file type can't be posted.")
    if size_bytes is not None:
        if size_bytes <= 0:
            raise FlyerError("size_bytes must be positive")
        if size_bytes > PDF_MAX_BYTES:
            raise FlyerError(
                f"That PDF is too large (max {PDF_MAX_BYTES // (1024 * 1024)} MB)."
            )
    key = _staging_key(user.id, filename, ".pdf")
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise FlyerError(str(exc)) from exc
    return {"upload_url": url, "key": key, "expires_in": 900}


def issue_photo_upload_url(
    user, *, filename: str, content_type: str, size_bytes: int | None
) -> dict:
    content_type = (content_type or "").lower().strip()
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise FlyerError("Page photos are JPG, PNG, or WebP images.")
    if size_bytes is not None:
        if size_bytes <= 0:
            raise FlyerError("size_bytes must be positive")
        if size_bytes > PHOTO_MAX_BYTES:
            raise FlyerError(
                f"That photo is too large (max {PHOTO_MAX_BYTES // (1024 * 1024)} MB)."
            )
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[
        content_type
    ]
    key = _staging_key(user.id, filename, ext)
    try:
        url = storage.presigned_put_url(key, content_type)
    except StorageError as exc:
        raise FlyerError(str(exc)) from exc
    return {"upload_url": url, "key": key, "expires_in": 900}


def _fetch_staged(user, key: str, *, max_bytes: int) -> bytes:
    """Read back an object the caller staged, verifying the
    namespace is theirs and the size is inside the cap before
    the bytes are trusted (the attach-time discipline)."""
    if not key.startswith(f"flyer-staging/{user.id}/"):
        raise FlyerError("That upload isn't yours.")
    try:
        meta = storage.head(key)
    except StorageError as exc:
        raise FlyerError(str(exc)) from exc
    if meta.size_bytes > max_bytes:
        raise FlyerError("That upload is larger than it declared.")
    try:
        return storage.fetch(key)
    except StorageError as exc:
        raise FlyerError(str(exc)) from exc


def _drop_staged(key: str) -> None:
    try:
        storage.delete(key)
    except StorageError:
        pass


def post_from_upload(
    db: Session,
    user,
    source: models.FlyerSource,
    *,
    key: str,
    label: str,
    starts_on: date,
    ends_on: date,
) -> models.Flyer:
    """Intake route 2: upload a PDF (staged via presigned PUT,
    verified here by HEAD + the PDF magic bytes)."""
    if not can_post_source(db, user, source):
        raise FlyerError("You can't post flyers to this spot.")
    _validate_window(starts_on, ends_on)
    data = _fetch_staged(user, key, max_bytes=PDF_MAX_BYTES)
    flyer = _store_flyer(
        db,
        user,
        source,
        data,
        origin=models.ORIGIN_UPLOAD,
        origin_url="",
        label=label,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    _drop_staged(key)
    return flyer


# -- the scanner ---------------------------------------------------


def detect_pages(user, keys: list[str]) -> list[dict]:
    """Run paper-edge detection over staged page photos.
    Answers each photo's size + the guessed corners
    (normalized, TL/TR/BR/BL) the nudge editor starts from."""
    if not keys:
        raise FlyerError("Add at least one page photo.")
    if len(keys) > MAX_SCAN_PAGES:
        raise FlyerError(f"A flyer takes at most {MAX_SCAN_PAGES} pages.")
    out = []
    for key in keys:
        data = _fetch_staged(user, key, max_bytes=PHOTO_MAX_BYTES)
        try:
            corners, detected, width, height = scan.detect_corners(data)
        except scan.ScanError as exc:
            raise FlyerError(str(exc)) from exc
        out.append(
            {
                "key": key,
                "width": width,
                "height": height,
                "corners": corners,
                "detected": detected,
            }
        )
    return out


def post_from_photos(
    db: Session,
    user,
    source: models.FlyerSource,
    *,
    pages: list[dict],
    label: str,
    starts_on: date,
    ends_on: date,
) -> models.Flyer:
    """Intake route 3: phone photos → the scanner squares and
    cleans each page by its (possibly nudged) corners, and
    the pages assemble into ONE PDF — the flyer."""
    if not can_post_source(db, user, source):
        raise FlyerError("You can't post flyers to this spot.")
    _validate_window(starts_on, ends_on)
    if not pages:
        raise FlyerError("Add at least one page photo.")
    if len(pages) > MAX_SCAN_PAGES:
        raise FlyerError(f"A flyer takes at most {MAX_SCAN_PAGES} pages.")
    page_jpegs: list[bytes] = []
    staged_keys: list[str] = []
    for page in pages:
        key = page.get("key") or ""
        corners = page.get("corners") or []
        data = _fetch_staged(user, key, max_bytes=PHOTO_MAX_BYTES)
        try:
            page_jpegs.append(scan.warp_page(data, corners))
        except scan.ScanError as exc:
            raise FlyerError(str(exc)) from exc
        staged_keys.append(key)
    try:
        pdf = render.assemble_pdf(page_jpegs)
    except render.RenderError as exc:
        raise FlyerError(str(exc)) from exc
    flyer = _store_flyer(
        db,
        user,
        source,
        pdf,
        origin=models.ORIGIN_PHOTOS,
        origin_url="",
        label=label,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    for key in staged_keys:
        _drop_staged(key)
    return flyer


def delete_flyer(db: Session, user, flyer: models.Flyer) -> None:
    """A poster takes one of the spot's flyers down (mistakes
    happen); the files go with the row."""
    source = get_source(db, flyer.source_id)
    if not can_post_source(db, user, source):
        raise FlyerError("Only the flyer's owner can take it down.")
    for key in (flyer.pdf_key, flyer.thumb_key):
        if key:
            _drop_staged_key(key)
    db.delete(flyer)
    db.commit()


def _drop_staged_key(key: str) -> None:
    try:
        storage.delete(key)
    except StorageError:
        pass


# ------------------------------------------------------- the standing job


def _run_official_pulls(db: Session, today: date) -> tuple[int, int, int, int, int]:
    """The SYSTEM pass of the daily pull (owner, 2026-11-06
    22:20): tool companies that publish their flyers online
    have those flyers available for their dealers
    automatically. For every directory company carrying the
    platform-kept official flyer link
    (DealerCompany.official_flyer_url), the link is fetched
    through the same guarded download and whatever it holds
    posts under the company's flyer spot — created on the
    spot, owned by nobody, if the company has none yet.

    The poster's own standing address always wins: a spot
    carrying one is skipped here (its own pass does that
    pulling), and if the address is later cleared the system
    link takes over again. A spot switched off is skipped —
    off means off, for the system too. Content-hash dedupe
    lives on the source (auto_hash): a changed edition posts
    fresh (and notifies the spot's audience), an unchanged
    one never re-posts. The platform is the poster — a system
    actor, not a user — so the posting gate does not apply,
    and the flyer's posted_by is honestly nobody.
    Returns (posted, unchanged, failed, overridden, skipped)."""
    from app.modules.catalog import manuals

    posted = unchanged = failed = overridden = skipped = 0
    companies = db.scalars(
        select(dealer_models.DealerCompany).where(
            dealer_models.DealerCompany.is_directory.is_(True),
            dealer_models.DealerCompany.official_flyer_url != "",
        )
    ).all()
    for company in companies:
        source = db.scalar(
            select(models.FlyerSource).where(
                models.FlyerSource.kind == models.KIND_COMPANY,
                models.FlyerSource.company_id == company.id,
            )
        )
        if source is not None and not source.visible:
            skipped += 1
            continue
        if source is not None and source.standing_url:
            overridden += 1
            continue
        try:
            data, _ct = manuals._download(company.official_flyer_url)
            if data[:5] != b"%PDF-":
                raise FlyerError("The official address didn't answer a PDF.")
            digest = hashlib.sha256(data).hexdigest()
            if source is None:
                source = models.FlyerSource(
                    kind=models.KIND_COMPANY,
                    company_id=company.id,
                    created_by_id=None,
                )
                db.add(source)
                db.commit()
                db.refresh(source)
            if digest == source.auto_hash:
                source.auto_checked_at = _now()
                db.commit()
                unchanged += 1
                continue
            flyer = _store_flyer(
                db,
                None,
                source,
                data,
                origin=models.ORIGIN_STANDING,
                origin_url=company.official_flyer_url,
                label="",
                starts_on=today,
                ends_on=today + timedelta(days=6),
                notify=False,
            )
            _notify_new_flyer(db, source, flyer, None)
            source.auto_hash = digest
            source.auto_checked_at = _now()
            db.commit()
            posted += 1
        except Exception:  # noqa: BLE001 — one bad link must not kill the job
            db.rollback()
            try:
                if source is not None and source.id is not None:
                    source.auto_checked_at = _now()
                    db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            failed += 1
    return posted, unchanged, failed, overridden, skipped


def run_standing_pulls(db: Session, today: date | None = None) -> str:
    """The daily pull, two passes. POSTER pass: every source
    with a standing web address gets its flyer spot fetched
    through the guarded download; whatever it holds becomes
    the current flyer — UNLESS the bytes are the ones already
    posted (content-hash dedupe: an unchanged flyer never
    re-posts and never re-notifies). SYSTEM pass
    (_run_official_pulls): the platform's official flyer
    links post under directory companies' spots.
    Private-agent spots are skipped by the poster pass —
    posting was removed from them entirely, so their standing
    addresses no longer post either. A failed pull is
    recorded and left for tomorrow; it never takes the job
    down."""
    from app.modules.catalog import manuals

    today = today or _today()
    sources = db.scalars(
        select(models.FlyerSource).where(
            models.FlyerSource.standing_url != "",
            ~(
                (models.FlyerSource.kind == models.KIND_AGENT)
                & (models.FlyerSource.private_agent_id.is_not(None))
            ),
        )
    ).all()
    posted = unchanged = failed = 0
    for source in sources:
        try:
            data, _ct = manuals._download(source.standing_url)
            if data[:5] != b"%PDF-":
                raise FlyerError("The standing address didn't answer a PDF.")
            digest = hashlib.sha256(data).hexdigest()
            if digest == source.standing_hash:
                source.standing_checked_at = _now()
                db.commit()
                unchanged += 1
                continue

            class _Poster:
                id = source.created_by_id

            flyer = _store_flyer(
                db,
                _Poster() if source.created_by_id else None,
                source,
                data,
                origin=models.ORIGIN_STANDING,
                origin_url=source.standing_url,
                label="",
                starts_on=today,
                ends_on=today + timedelta(days=6),
                notify=source.created_by_id is not None,
            )
            source.standing_hash = digest
            source.standing_checked_at = _now()
            db.commit()
            posted += 1
            _ = flyer
        except Exception:  # noqa: BLE001 — one bad spot must not kill the job
            db.rollback()
            try:
                source.standing_checked_at = _now()
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            failed += 1
    a_posted, a_unchanged, a_failed, a_overridden, a_skipped = (
        _run_official_pulls(db, today)
    )
    return (
        f"flyer standing pulls: {posted} posted, "
        f"{unchanged} unchanged, {failed} failed; "
        f"official links: {a_posted} posted, {a_unchanged} unchanged, "
        f"{a_failed} failed, {a_overridden} overridden, "
        f"{a_skipped} skipped"
    )
