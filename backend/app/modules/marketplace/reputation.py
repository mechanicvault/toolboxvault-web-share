"""The reputation engine (community suite, owner decisions
2026-10-19 16:48/16:49): ratings tied to COMPLETED interactions,
published DOUBLE-BLIND.

SERVICE INTERFACE (stable — the forum build consumes the same
functions; bump the marketplace manifest version on change):
  - create_interaction(db, *, user_a, user_b, source, ...) —
    idempotent by dedupe key: a deal is rateable exactly once.
  - create_interaction_for_thread(db, thread) — the both-sides-
    closed completion path (anchored threads only).
  - complete_thread(db, user, thread) — one side's close; the
    second side's close creates the interaction.
  - submit_rating(db, user, interaction_id, stars, text) —
    one per side per interaction; the second submission publishes
    BOTH ratings together.
  - refresh_publication(db, interaction) / publish_due(db) —
    the 14-day rule: a lone rating publishes anyway once the
    interaction is 14 days old (silence is not a veto). Applied
    LAZILY on every read path below AND by the jobs sweep
    (app/scripts/run_marketplace_jobs.py) so publication never
    depends on someone happening to look.
  - summary_for(db, user_id) -> {average, count, completed_deals}
    — THE aggregate: messaging's public profile, the listing
    payloads, and the board's rating sort all read it here, so
    the numbers can never disagree between surfaces.
  - completed_count(db, user_id) — registered into the spam
    firewall's interaction-counter seam at import: completed
    deals now lift trust tiers for real.
  - report_rating(db, reporter, rating_id, reason) /
    list_rating_reports(db, status) /
    dismiss_rating_report(db, actor, report_id, resolution) /
    remove_rating_for_report(db, actor, report_id, resolution)
    — MODERATOR REMOVAL of abusive ratings (gap wave 1,
    2026-10-20): members report a published rating; the report
    lands in the moderation queue's Ratings section; a moderator
    dismisses it (the rating stands) or removes the rating —
    the row is kept (append-only history), its text replaced by
    REMOVED_TEXT, removed_at stamped, and every aggregate
    excludes it from that moment. The interaction record and the
    other side's rating are untouched; the rating's author gets
    an inbox notification; both actions are audit-logged.

Aggregates count PUBLISHED, UNREMOVED ratings only — a rating
still in its blind hold is invisible to everyone, including
aggregate math (it would leak through the average otherwise),
and a removed rating stops counting the moment it is removed.
"""

# The placeholder a removed rating's text is replaced with —
# everywhere the rating still renders (profile review list, the
# interaction view), this is what stands in its place.
REMOVED_TEXT = "This review was removed by a moderator."

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.core import service as core_service
from app.modules.marketplace import models

# Ryan's hybrid rule: both-or-14-days (2026-10-19).
PUBLISH_AFTER_DAYS = 14

FORMER_MEMBER = "Former member"


class ReputationError(ValueError):
    """Friendly refusal. Routes -> 422."""


class ReputationNotFound(ReputationError):
    """Missing OR not yours — ids never leak existence. -> 404."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def pair_of(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if str(a) < str(b) else (b, a)


# -- interactions -------------------------------------------------------------


def get_interaction(
    db: Session, interaction_id: uuid.UUID
) -> models.DealInteraction | None:
    return db.get(models.DealInteraction, interaction_id)


def participant_interaction(
    db: Session, user_id: uuid.UUID, interaction_id: uuid.UUID
) -> models.DealInteraction:
    row = get_interaction(db, interaction_id)
    if row is None or user_id not in (row.party_low_id, row.party_high_id):
        raise ReputationNotFound("That deal isn't available.")
    return row


def create_interaction(
    db: Session,
    *,
    user_a,
    user_b,
    source: str,
    dedupe_key: str,
    listing_id: uuid.UUID | None = None,
    part_id: uuid.UUID | None = None,
    thread_id: uuid.UUID | None = None,
    context_title: str = "",
) -> tuple[models.DealInteraction, bool]:
    """Find-or-create the interaction for one deal. Returns
    (row, created). Commits."""
    existing = db.scalars(
        select(models.DealInteraction).where(
            models.DealInteraction.dedupe_key == dedupe_key
        )
    ).first()
    if existing is not None:
        return existing, False
    low, high = pair_of(user_a.id, user_b.id)
    names = {user_a.id: user_a.name, user_b.id: user_b.name}
    row = models.DealInteraction(
        party_low_id=low,
        party_high_id=high,
        party_low_name=names[low],
        party_high_name=names[high],
        source=source,
        listing_id=listing_id,
        part_id=part_id,
        thread_id=thread_id,
        context_title=(context_title or "")[:300],
        dedupe_key=dedupe_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def interactions_for(db: Session, user_id: uuid.UUID) -> list[models.DealInteraction]:
    return list(
        db.scalars(
            select(models.DealInteraction)
            .where(
                (models.DealInteraction.party_low_id == user_id)
                | (models.DealInteraction.party_high_id == user_id)
            )
            .order_by(models.DealInteraction.completed_at.desc())
        ).all()
    )


def completed_count(db: Session, user_id: uuid.UUID) -> int:
    """Spam-firewall seam: how many completed deals stand behind
    this account (either side — both parties did the deal)."""
    return int(
        db.scalar(
            select(func.count(models.DealInteraction.id)).where(
                (models.DealInteraction.party_low_id == user_id)
                | (models.DealInteraction.party_high_id == user_id)
            )
        )
        or 0
    )


# -- thread completion (both sides close an anchored thread) --------------------


def thread_completion_state(
    db: Session, thread, user_id: uuid.UUID
) -> dict:
    """Where this thread's completion stands FOR THIS VIEWER:
    whether they closed it, whether the other side did, and the
    interaction once it exists. Blind-safe: it says THAT the
    other side closed, never anything about ratings."""
    rows = list(
        db.scalars(
            select(models.ThreadCompletion).where(
                models.ThreadCompletion.thread_id == thread.id
            )
        ).all()
    )
    closed_by = {row.user_id for row in rows}
    interaction = db.scalars(
        select(models.DealInteraction).where(
            models.DealInteraction.dedupe_key == f"thread:{thread.id}"
        )
    ).first()
    other = (
        thread.participant_high_id
        if thread.participant_low_id == user_id
        else thread.participant_low_id
    )
    return {
        "anchored": bool(thread.anchor_type),
        "i_closed": user_id in closed_by,
        "other_closed": other in closed_by,
        "interaction_id": interaction.id if interaction is not None else None,
    }


def complete_thread(db: Session, user, thread) -> dict:
    """Record MY close of an anchored thread as a completed deal.
    When the other side has also closed, the interaction is
    created (dedupe makes a double-close harmless). Commits.
    Returns the completion state for the caller."""
    if not thread.anchor_type or thread.anchor_id is None:
        raise ReputationError(
            "Only a conversation about a listing or a part can be "
            "closed as a completed deal."
        )
    existing = db.scalars(
        select(models.ThreadCompletion).where(
            models.ThreadCompletion.thread_id == thread.id,
            models.ThreadCompletion.user_id == user.id,
        )
    ).first()
    if existing is None:
        db.add(
            models.ThreadCompletion(thread_id=thread.id, user_id=user.id)
        )
        db.commit()
    state = thread_completion_state(db, thread, user.id)
    if state["other_closed"] and state["interaction_id"] is None:
        other_id = (
            thread.participant_high_id
            if thread.participant_low_id == user.id
            else thread.participant_low_id
        )
        other = core_service.get_user_by_id(db, other_id)
        if other is not None:
            source = "listing" if thread.anchor_type == "listing" else "part"
            create_interaction(
                db,
                user_a=user,
                user_b=other,
                source=source,
                dedupe_key=f"thread:{thread.id}",
                listing_id=thread.anchor_id if source == "listing" else None,
                part_id=thread.anchor_id if source == "part" else None,
                thread_id=thread.id,
                context_title=thread.anchor_title,
            )
            state = thread_completion_state(db, thread, user.id)
    return state


# -- ratings -------------------------------------------------------------------


def rating_by(
    db: Session, interaction_id: uuid.UUID, rater_id: uuid.UUID
) -> models.Rating | None:
    return db.scalars(
        select(models.Rating).where(
            models.Rating.interaction_id == interaction_id,
            models.Rating.rater_id == rater_id,
        )
    ).first()


def ratings_of(db: Session, interaction_id: uuid.UUID) -> list[models.Rating]:
    return list(
        db.scalars(
            select(models.Rating).where(
                models.Rating.interaction_id == interaction_id
            )
        ).all()
    )


def refresh_publication(db: Session, interaction: models.DealInteraction) -> bool:
    """Apply the publication rules to one interaction's ratings:
    both submitted → both publish; a lone rating publishes once
    the interaction is PUBLISH_AFTER_DAYS old. Returns True when
    anything changed (and commits)."""
    rows = ratings_of(db, interaction.id)
    unpublished = [row for row in rows if row.published_at is None]
    if not unpublished:
        return False
    now = _now()
    publish = False
    if len(rows) >= 2:
        publish = True
    else:
        completed = _aware(interaction.completed_at)
        if completed is not None and now >= completed + timedelta(
            days=PUBLISH_AFTER_DAYS
        ):
            publish = True
    if not publish:
        return False
    for row in unpublished:
        row.published_at = now
    db.commit()
    return True


def publish_due(db: Session) -> int:
    """The jobs sweep: every interaction with an unpublished
    rating gets its publication rules applied. Returns how many
    ratings were published."""
    interaction_ids = list(
        db.scalars(
            select(models.Rating.interaction_id)
            .where(models.Rating.published_at.is_(None))
            .distinct()
        ).all()
    )
    published = 0
    for interaction_id in interaction_ids:
        before = {
            row.id
            for row in ratings_of(db, interaction_id)
            if row.published_at is not None
        }
        interaction = get_interaction(db, interaction_id)
        if interaction is not None:
            refresh_publication(db, interaction)
        after = {
            row.id
            for row in ratings_of(db, interaction_id)
            if row.published_at is not None
        }
        published += len(after - before)
    return published


def submit_rating(
    db: Session, user, interaction_id: uuid.UUID, stars: int, text: str
) -> models.Rating:
    """One rating, from one side of one real interaction. The
    second side's submission publishes BOTH (refresh_publication
    runs inside). Commits."""
    interaction = participant_interaction(db, user.id, interaction_id)
    if stars < 1 or stars > 5:
        raise ReputationError("Pick a star rating from 1 to 5.")
    if rating_by(db, interaction.id, user.id) is not None:
        raise ReputationError(
            "You've already rated this deal — one rating per side."
        )
    other = (
        interaction.party_high_id
        if interaction.party_low_id == user.id
        else interaction.party_low_id
    )
    row = models.Rating(
        interaction_id=interaction.id,
        rater_id=user.id,
        ratee_id=other,
        stars=stars,
        text=(text or "").strip()[:500],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    refresh_publication(db, interaction)
    db.refresh(row)
    return row


# -- aggregates + public reads ---------------------------------------------------


def summary_for(db: Session, user_id: uuid.UUID) -> dict:
    """THE reputation aggregate (see module docstring): average
    + count over PUBLISHED ratings about the user, plus their
    completed-deals count. Due publications are refreshed first
    (the lazy half of the 14-day rule), scoped to this user's
    interactions so a profile read never sweeps the world."""
    for interaction in interactions_for(db, user_id):
        refresh_publication(db, interaction)
    stats = db.execute(
        select(func.avg(models.Rating.stars), func.count(models.Rating.id)).where(
            models.Rating.ratee_id == user_id,
            models.Rating.published_at.is_not(None),
            models.Rating.removed_at.is_(None),
        )
    ).one()
    average, count = stats
    return {
        "average": round(float(average), 2) if average is not None else None,
        "count": int(count or 0),
        "completed_deals": completed_count(db, user_id),
    }


def _rater_display(db: Session, rater_id: uuid.UUID) -> str:
    user = core_service.get_user_by_id(db, rater_id)
    if user is None:
        return FORMER_MEMBER
    return user.name


def published_ratings_for(db: Session, user_id: uuid.UUID) -> list[dict]:
    """The published reviews ABOUT a user, newest first — the
    profile's review list. Unpublished ratings do not exist here
    (not their stars, not their text, not their count)."""
    for interaction in interactions_for(db, user_id):
        refresh_publication(db, interaction)
    rows = list(
        db.scalars(
            select(models.Rating)
            .where(
                models.Rating.ratee_id == user_id,
                models.Rating.published_at.is_not(None),
            )
            .order_by(models.Rating.published_at.desc())
        ).all()
    )
    views = []
    for row in rows:
        interaction = get_interaction(db, row.interaction_id)
        removed = row.removed_at is not None
        views.append(
            {
                "id": row.id,
                # A removed rating keeps its place in the list as
                # a tombstone: no stars, the placeholder text, and
                # the removed flag — its content is gone.
                "stars": None if removed else row.stars,
                "text": REMOVED_TEXT if removed else row.text,
                "removed": removed,
                "rater_id": row.rater_id,
                "rater_name": _rater_display(db, row.rater_id),
                "context_title": (
                    interaction.context_title if interaction is not None else ""
                ),
                "published_at": row.published_at,
                "created_at": row.created_at,
            }
        )
    return views


def interaction_view(db: Session, user_id: uuid.UUID, row: models.DealInteraction) -> dict:
    """One interaction as ONE side sees it — the blind-honest
    shape: my rating in full (mine is mine); the other side's
    stars/text ONLY once published. Whether they have SUBMITTED
    is shown (`their_rating_submitted`) — the pair's status has
    to be able to say "waiting on them" vs "waiting on you", and
    a submitted-fact carries no content: never "they rated you 2
    stars, wait 13 days"."""
    refresh_publication(db, row)
    other = row.party_high_id if row.party_low_id == user_id else row.party_low_id
    other_name = (
        row.party_high_name if row.party_low_id == user_id else row.party_low_name
    )
    mine = rating_by(db, row.id, user_id)
    theirs = rating_by(db, row.id, other)
    their_view = None
    if theirs is not None and theirs.published_at is not None:
        their_removed = theirs.removed_at is not None
        their_view = {
            # The id rides along so the deals view can offer the
            # Report action on the rating itself (gap wave 1).
            "id": theirs.id,
            "stars": None if their_removed else theirs.stars,
            "text": REMOVED_TEXT if their_removed else theirs.text,
            "removed": their_removed,
            "published_at": theirs.published_at,
        }
    mine_removed = mine is not None and mine.removed_at is not None
    return {
        "id": row.id,
        "source": row.source,
        "context_title": row.context_title,
        "listing_id": row.listing_id,
        "part_id": row.part_id,
        "thread_id": row.thread_id,
        "other_user_id": other,
        "other_name": other_name,
        "completed_at": row.completed_at,
        "my_rating": (
            {
                "stars": None if mine_removed else mine.stars,
                "text": REMOVED_TEXT if mine_removed else mine.text,
                "removed": mine_removed,
                "published": mine.published_at is not None,
                "published_at": mine.published_at,
            }
            if mine is not None
            else None
        ),
        "their_rating": their_view,
        "their_rating_submitted": theirs is not None,
    }


# -- rating moderation (gap wave 1, 2026-10-20) -----------------------------------
#
# Reports land in the moderation queue's Ratings section. The two
# resolutions mirror the message queue: dismiss (the rating
# stands) or remove (the rating stops counting everywhere and its
# text becomes the placeholder). Both are audit-logged under the
# actor; removal also notifies the rating's author in their inbox.


def _audit(db: Session, actor, action: str, target, detail: dict) -> None:
    from app.modules.core import audit

    audit.record(db, actor, action=action, target=str(target), detail=detail)


def report_rating(
    db: Session, reporter, rating_id: uuid.UUID, reason: str
) -> models.RatingReport:
    """File a report against a PUBLISHED rating. Only published
    ratings render anywhere, so only they can be reported; the
    author can't report their own review; one open report per
    reporter per rating (the message-reports rule). Commits."""
    rating = db.get(models.Rating, rating_id)
    if rating is None or rating.published_at is None:
        raise ReputationNotFound("That review isn't available.")
    if rating.removed_at is not None:
        raise ReputationError("That review has already been removed.")
    if rating.rater_id == reporter.id:
        raise ReputationError("You can't report your own review.")
    existing = db.scalars(
        select(models.RatingReport).where(
            models.RatingReport.rating_id == rating.id,
            models.RatingReport.reporter_id == reporter.id,
            models.RatingReport.status == "open",
        )
    ).first()
    if existing is not None:
        raise ReputationError(
            "You've already reported this review — it's in the "
            "moderation queue."
        )
    row = models.RatingReport(
        rating_id=rating.id,
        reporter_id=reporter.id,
        reason=(reason or "").strip()[:500],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def rating_report_view(db: Session, row: models.RatingReport) -> dict:
    """The queue's wire shape for one rating report (the report
    plus the rating it names — see schemas.RatingReportPublic)."""
    rating = db.get(models.Rating, row.rating_id)
    reporter = core_service.get_user_by_id(db, row.reporter_id)
    interaction = (
        get_interaction(db, rating.interaction_id) if rating is not None else None
    )
    return {
        "id": row.id,
        "rating_id": row.rating_id,
        "reporter_id": row.reporter_id,
        "reporter_name": reporter.name if reporter is not None else "",
        "reason": row.reason,
        "status": row.status,
        "resolution": row.resolution,
        "resolved_by_id": row.resolved_by_id,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
        "rating_stars": rating.stars if rating is not None else None,
        "rating_text": (
            REMOVED_TEXT
            if rating is not None and rating.removed_at is not None
            else (rating.text if rating is not None else "")
        ),
        "rating_removed": (
            rating.removed_at is not None if rating is not None else False
        ),
        "rater_id": rating.rater_id if rating is not None else None,
        "rater_name": (
            _rater_display(db, rating.rater_id) if rating is not None else ""
        ),
        "ratee_id": rating.ratee_id if rating is not None else None,
        "ratee_name": (
            _rater_display(db, rating.ratee_id) if rating is not None else ""
        ),
        "context_title": interaction.context_title if interaction is not None else "",
    }


def list_rating_reports(db: Session, status: str = "open") -> list[dict]:
    rows = list(
        db.scalars(
            select(models.RatingReport)
            .where(models.RatingReport.status == status)
            .order_by(models.RatingReport.created_at)
        ).all()
    )
    return [rating_report_view(db, row) for row in rows]


def _open_rating_report(
    db: Session, report_id: uuid.UUID
) -> models.RatingReport:
    row = db.get(models.RatingReport, report_id)
    if row is None:
        raise ReputationNotFound("That report isn't available.")
    if row.status != "open":
        raise ReputationError("That report has already been resolved.")
    return row


def dismiss_rating_report(
    db: Session, actor, report_id: uuid.UUID, resolution: str = ""
) -> dict:
    """The rating stands. Audit-logged (rating.report_dismiss)."""
    row = _open_rating_report(db, report_id)
    row.status = "dismissed"
    row.resolution = (resolution or "")[:500]
    row.resolved_by_id = actor.id
    row.resolved_at = _now()
    db.commit()
    _audit(
        db, actor, "rating.report_dismiss", row.rating_id,
        {"report_id": str(row.id)},
    )
    return rating_report_view(db, row)


def remove_rating_for_report(
    db: Session, actor, report_id: uuid.UUID, resolution: str = ""
) -> dict:
    """Remove the reported rating: text replaced by the
    placeholder, removed_at stamped, aggregates exclude it from
    now on (summary_for filters removed_at). The interaction and
    the other side's rating are untouched. The report becomes
    "actioned"; the author is notified in their inbox; the act is
    audit-logged (rating.remove)."""
    from app.modules.core import inbox

    row = _open_rating_report(db, report_id)
    rating = db.get(models.Rating, row.rating_id)
    if rating is None:
        raise ReputationNotFound("That review isn't available.")
    if rating.removed_at is None:
        rating.text = REMOVED_TEXT
        rating.removed_at = _now()
        rating.removed_by_id = actor.id
    row.status = "actioned"
    row.resolution = (resolution or "")[:500]
    row.resolved_by_id = actor.id
    row.resolved_at = _now()
    db.commit()
    _audit(
        db, actor, "rating.remove", rating.id,
        {"report_id": str(row.id), "rater_id": str(rating.rater_id)},
    )
    interaction = get_interaction(db, rating.interaction_id)
    inbox.rating_removed(
        db,
        rater_id=rating.rater_id,
        context_title=interaction.context_title if interaction else "",
        thread_id=interaction.thread_id if interaction else None,
    )
    return rating_report_view(db, row)


# -- the spam seam ----------------------------------------------------------------
#
# The firewall's completed-interactions counter (messaging/spam.py)
# reads 0 until a provider registers. Registration happens at
# import: the app factory imports every module's routes (which
# import this engine through the marketplace service), so by the
# time any request is served the seam is live.

from app.modules.messaging import spam as _spam  # noqa: E402

_spam.register_interaction_counter(completed_count)
