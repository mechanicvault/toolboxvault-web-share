"""User audit trail + restore (core module; owner note 2026-10-19).

Every user gets a journal of their OWN content: each create /
update / delete of an owned record lands a `change_journal` row
with the full before + after snapshot of the row, captured by a
session listener inside the SAME transaction as the change — so
the trail can never drift from the data, and every mutation path
(service functions today, anything written tomorrow) is covered
without per-call-site wiring. The few paths that mutate through
bulk SQL instead of the ORM (tag links, battery links, definition
scrubs) were converted to ORM writes so they pass through here.

Restore markers are points the account can roll back to (baseline
at signup, daily from the jobs seam, manual, forced pre_bulk
before an import, and pre_restore — written by the engine itself
so a restore can be undone). The restore engine inverts every
restorable entry after the marker, newest first, in ONE
transaction: deletions re-created with their ORIGINAL ids, edits
rolled back to the before snapshot, additions removed. Any
conflict aborts the whole restore — no partial state.

Two-party records are journaled for VISIBILITY only and never
inverted (the `restorable` flag): borrowing rows and peer shares
are shared history between people, and filed claims are the
insurer-facing record. Draft claims restore normally.

Files follow their records: deleting a record TOMBSTONES its
storage objects (retained_files) instead of destroying them, so a
restore brings the photos back. The purge seam hard-deletes
tombstones older than the admin setting `audit.retention_days`
(default 180).

Actor attribution: `get_current_user` (app/core/deps.py) stamps
the acting user into a contextvar for the request's duration;
background jobs and direct service calls leave it None (system).
An entry is automatically visibility-only when somebody OTHER
than the owner changed the record (a peer accepting an invite, a
borrower marking a return, an operator verifying a dealer
representation) — restoring one account must never silently
rewrite another person's side of a shared record.
"""

import copy
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.storage import StorageError, storage
from app.modules.core import models

RETENTION_KEY = "audit.retention_days"
RETENTION_DEFAULT = 180

# -- request-scoped journaling state -----------------------------------------
#
# _actor: who is performing the current unit of work (None = the
# system itself: jobs, seeds, direct service calls in tests).
# _suspended: the listener stands down entirely (account deletion,
# the restore engine's own writes).
# _permanent: file retirement hard-deletes objects instead of
# tombstoning them (account deletion only — deletion stays final).

_actor: ContextVar[uuid.UUID | None] = ContextVar("journal_actor", default=None)
_suspended: ContextVar[bool] = ContextVar("journal_suspended", default=False)
_permanent: ContextVar[bool] = ContextVar("journal_permanent", default=False)


@contextmanager
def acting_as(user_id: uuid.UUID | None):
    token = _actor.set(user_id)
    try:
        yield
    finally:
        _actor.reset(token)


@contextmanager
def suspended(*, permanent: bool = False):
    """Stand the journal down for a block. `permanent=True` also
    flips file retirement to hard deletes (account deletion)."""
    t1 = _suspended.set(True)
    t2 = _permanent.set(permanent)
    try:
        yield
    finally:
        _suspended.reset(t1)
        _permanent.reset(t2)


class RestoreConflict(Exception):
    """A restore hit state it cannot safely invert. The engine has
    already rolled everything back; the message is user-facing."""


# -- the entity registry -------------------------------------------------------

_CLAIM_CHILDREN = ("claim_line", "claim_evidence", "claim_communication")
_ATTACHMENT_ENTITIES = (
    "tool", "battery", "set_piece", "part", "sale_listing", "wishlist_item",
)


@dataclass(frozen=True)
class EntitySpec:
    entity_type: str
    module: str
    model_ref: str  # "package.module:ClassName" — resolved lazily
    owner_attr: str = "owner_id"
    depth: int = 0  # restore ordering: parents re-insert first
    noun: str = ""
    name_keys: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ("search_vector",)
    visibility_only: bool = False


_SPECS: tuple[EntitySpec, ...] = (
    # inventory
    EntitySpec("tool", "inventory", "app.modules.inventory.models:Tool",
               depth=2, noun="tool", name_keys=("name",)),
    EntitySpec("battery", "inventory", "app.modules.inventory.models:Battery",
               depth=2, noun="battery", name_keys=("name",)),
    EntitySpec("set_piece", "inventory", "app.modules.inventory.models:SetPiece",
               depth=3, noun="set piece", name_keys=("name",)),
    EntitySpec("field_definition", "inventory",
               "app.modules.inventory.models:FieldDefinition",
               depth=0, noun="custom field", name_keys=("label", "name")),
    EntitySpec("tag", "inventory", "app.modules.inventory.models:Tag",
               depth=0, noun="tag", name_keys=("name",)),
    EntitySpec("item_tag", "inventory", "app.modules.inventory.models:ItemTag",
               depth=4, noun="item tag"),
    # Inventory location tree (Package B, 2026-10-19): nodes are
    # parents of the items filed under them — depth 1 re-inserts a
    # node before the tools/batteries (depth 2) that reference it.
    EntitySpec("inventory_location", "inventory",
               "app.modules.inventory.models:InventoryLocation",
               depth=1, noun="location", name_keys=("name",)),
    # Importer smart matching (2026-10-19): the owner's learned
    # resolve answers — restoring them restores what the importer
    # pre-answers.
    EntitySpec("import_value_mapping", "inventory",
               "app.modules.inventory.models:ImportValueMapping",
               depth=0, noun="import value mapping",
               name_keys=("raw_value",)),
    # Gap wave 1 (2026-10-20): the category manager's registry rows
    # (the category STRINGS live on the items themselves and ride
    # the tool/battery entries; the registry row is the anchor a
    # rename/merge hangs off) and lost/stolen report records
    # (children of their item — depth 3, with the set pieces: the
    # item at depth 2 re-inserts first).
    EntitySpec("inventory_category", "inventory",
               "app.modules.inventory.models:InventoryCategory",
               depth=0, noun="category", name_keys=("name",)),
    EntitySpec("loss_report", "inventory",
               "app.modules.inventory.models:ItemLossReport",
               depth=3, noun="lost/stolen report"),
    # Borrower address book (gap wave 1): the owner's own contact
    # records — restorable. Checkouts stay visibility-only; their
    # borrower_contact_id link is a plain snapshot column, so a
    # restored contact never has to re-point a ledger row.
    EntitySpec("borrower_contact", "borrowing",
               "app.modules.borrowing.models:BorrowerContact",
               depth=0, noun="borrower", name_keys=("name",)),
    # used parts
    EntitySpec("part", "parts", "app.modules.parts.models:Part",
               depth=1, noun="used part", name_keys=("title",)),
    EntitySpec("part_location", "parts", "app.modules.parts.models:PartLocation",
               depth=0, noun="part location", name_keys=("name",)),
    # Community pool choices (2026-10-19): the owner's visibility
    # defaults — restoring them restores what the shelf showed.
    EntitySpec("part_pool_setting", "parts",
               "app.modules.parts.models:PartPoolSettings",
               depth=0, noun="pool settings"),
    # Tools For Sale (2026-10-19): a listing is the owner's own
    # record — restorable like a part (its photos ride the
    # attachment tombstone path via _ATTACHMENT_ENTITIES).
    # Interactions + ratings are deliberately NOT here: they are
    # two-party history (the borrowing/checkout posture, one step
    # further — not even visibility-journaled, since a rating's
    # blind state must never be reconstructible from a journal).
    EntitySpec("sale_listing", "marketplace",
               "app.modules.marketplace.models:SaleListing",
               depth=1, noun="sale listing", name_keys=("title",)),
    # Community Forum (2026-10-20): threads + posts are journaled
    # for VISIBILITY ONLY, never inverted — the peer-share /
    # checkout posture, for a sharper reason: a post lives inside
    # a shared conversation, and a restore must never resurrect
    # content a moderator removed or the firewall held, nor
    # rewrite the context other members replied to. The owner's
    # history shows the entries; the restore engine skips them.
    EntitySpec("forum_thread", "forum",
               "app.modules.forum.models:ForumThread",
               owner_attr="author_id", depth=1, noun="forum thread",
               name_keys=("title",), visibility_only=True),
    EntitySpec("forum_post", "forum",
               "app.modules.forum.models:ForumPost",
               owner_attr="author_id", depth=2, noun="forum post",
               visibility_only=True),
    # maintenance. (repair_record is RETIRED — repairs ∪ claims
    # merge, 2026-11-04: the records became claims in migration
    # 0074, which also flipped their journal rows to
    # visibility-only; the trail stays readable, never inverted.)
    EntitySpec("maintenance_schedule", "maintenance",
               "app.modules.maintenance.models:MaintenanceSchedule",
               depth=1, noun="maintenance schedule",
               name_keys=("label", "item_name")),
    EntitySpec("maintenance_log_entry", "maintenance",
               "app.modules.maintenance.models:MaintenanceLogEntry",
               depth=2, noun="maintenance log entry"),
    # dealers (private data only — directory rows have no owner)
    EntitySpec("dealer_company", "dealers",
               "app.modules.dealers.models:DealerCompany",
               depth=0, noun="dealer company", name_keys=("name",)),
    EntitySpec("private_agent", "dealers",
               "app.modules.dealers.models:PrivateAgent",
               depth=1, noun="dealer agent", name_keys=("name",)),
    EntitySpec("preferred_agent", "dealers",
               "app.modules.dealers.models:PreferredAgent",
               owner_attr="user_id", depth=2, noun="preferred agent"),
    EntitySpec("agent_profile", "dealers",
               "app.modules.dealers.models:AgentProfile",
               owner_attr="user_id", depth=0, noun="dealer profile",
               name_keys=("display_name",)),
    EntitySpec("company_representation", "dealers",
               "app.modules.dealers.models:CompanyRepresentation",
               owner_attr="agent_user_id", depth=1,
               noun="company representation"),
    # Warranty service requests (dealer build, 2026-10-20):
    # TWO-PARTY records like forum posts — the audit trail shows
    # them, but they are never restorable: restoring one side's
    # copy would resurrect a shared business record the other
    # party watched change.
    EntitySpec("warranty_request", "dealers",
               "app.modules.dealers.models:WarrantyServiceRequest",
               owner_attr="requester_id", depth=2,
               noun="warranty service request", visibility_only=True,
               name_keys=("item_name",)),
    # sharing configs (core)
    EntitySpec("share_config", "core", "app.modules.core.models:ShareConfig",
               depth=0, noun="sharing settings"),
    EntitySpec("shared_item", "core", "app.modules.core.models:SharedItem",
               depth=3, noun="shared item"),
    EntitySpec("peer_share", "core", "app.modules.core.models:PeerShare",
               depth=0, noun="tool-list share", visibility_only=True),
    EntitySpec("peer_exclusion", "core",
               "app.modules.core.models:PeerShareExclusion",
               depth=3, noun="peer sharing exclusion"),
    EntitySpec("peer_set_choice", "core",
               "app.modules.core.models:PeerSetChoice",
               depth=1, noun="peer set choice"),
    # Sharing rules + insurance profile (Package C, 2026-10-19).
    # A rule's target is a plain id snapshot (no FK), so restores
    # never need the target to exist first — depth 0. Exclusions
    # carry real item FKs, so they restore at the picks' depth.
    EntitySpec("share_rule", "core", "app.modules.core.models:ShareRule",
               depth=0, noun="sharing rule"),
    EntitySpec("share_exclusion", "core",
               "app.modules.core.models:ShareExclusion",
               depth=3, noun="sharing exclusion"),
    EntitySpec("peer_exclusion_rule", "core",
               "app.modules.core.models:PeerShareExclusionRule",
               depth=0, noun="peer withholding rule"),
    EntitySpec("insurance_profile", "core",
               "app.modules.core.models:InsuranceProfile",
               owner_attr="user_id", depth=0, noun="insurance profile",
               name_keys=("insurer_company",)),
    # claims (drafts restorable; children follow their claim)
    EntitySpec("claim", "claims", "app.modules.claims.models:Claim",
               depth=5, noun="claim", name_keys=("claim_number",)),
    EntitySpec("claim_line", "claims", "app.modules.claims.models:ClaimLine",
               depth=6, noun="claim item", name_keys=("target_name",)),
    EntitySpec("claim_evidence", "claims",
               "app.modules.claims.models:ClaimEvidence",
               depth=6, noun="claim evidence", name_keys=("filename",)),
    EntitySpec("claim_communication", "claims",
               "app.modules.claims.models:ClaimCommunication",
               depth=6, noun="claim message", name_keys=("summary",)),
    # borrowing — the shared ledger: visibility only, never inverted
    EntitySpec("checkout", "borrowing", "app.modules.borrowing.models:Checkout",
               depth=1, noun="checkout", name_keys=("item_name",),
               visibility_only=True),
    # Wave 2 (2026-10-20). Wishlist items are the owner's own
    # records — restorable like a part (photos ride the
    # attachment tombstone path via _ATTACHMENT_ENTITIES).
    EntitySpec("wishlist_item", "wishlist",
               "app.modules.wishlist.models:WishlistItem",
               depth=1, noun="wishlist item", name_keys=("title",)),
    # Sale records: the sold ledger is the owner's own history —
    # journaled VISIBILITY-ONLY like the checkout ledger: a
    # restore must never un-sell or re-sell an item behind the
    # ledger's back (Undo sale is the correction path, and IT is
    # journaled as its own entry).
    EntitySpec("sale_record", "inventory",
               "app.modules.inventory.models:SaleRecord",
               depth=2, noun="sale record", name_keys=("item_name",),
               visibility_only=True),
    # Truck accounts + entries: TWO-PARTY money history — the
    # warranty-request posture. The audit trail shows them; the
    # restore engine never inverts them (one side's restore
    # would rewrite the other side's ledger). Entries attribute
    # to the DEALER via the denormalized dealer_user_id (owner
    # attr), so a customer's history shows their side through
    # the account's entries.
    EntitySpec("truck_account", "truck_accounts",
               "app.modules.truck_accounts.models:TruckAccount",
               owner_attr="dealer_user_id", depth=1,
               noun="truck account", name_keys=("customer_name",),
               visibility_only=True),
    EntitySpec("truck_entry", "truck_accounts",
               "app.modules.truck_accounts.models:TruckEntry",
               owner_attr="dealer_user_id", depth=2,
               noun="truck entry", visibility_only=True),
    # Wave 3 (2026-10-20).
    # Shop memberships: TWO-PARTY records (owner + member) —
    # visibility-only like their truck siblings; one side's
    # restore must never resurrect the other side's crew state.
    EntitySpec("shop_membership", "core",
               "app.modules.core.models:ShopMembership",
               owner_attr="shop_user_id", depth=1,
               noun="crew membership", name_keys=("invite_email",),
               visibility_only=True),
    # The insurer affiliation is the user's OWN profile record —
    # restorable like the My Insurance profile it sits beside.
    EntitySpec("insurer_affiliation", "core",
               "app.modules.core.models:InsurerAffiliation",
               owner_attr="user_id", depth=0, noun="insurer affiliation",
               name_keys=("role_at_company",)),
    # Feedback posts + comments: community content — the forum
    # posture (visibility only; moderation history is never
    # inverted by a restore).
    EntitySpec("feedback_post", "feedback",
               "app.modules.feedback.models:FeedbackPost",
               owner_attr="author_id", depth=1, noun="feedback post",
               name_keys=("title",), visibility_only=True),
    EntitySpec("feedback_comment", "feedback",
               "app.modules.feedback.models:FeedbackComment",
               owner_attr="author_id", depth=2, noun="feedback comment",
               visibility_only=True),
)

_SPEC_BY_TYPE: dict[str, EntitySpec] = {s.entity_type: s for s in _SPECS}
_MODEL_TO_SPEC: dict[type, EntitySpec] = {}
_MODELS: dict[str, type] = {}


def _model_for(spec: EntitySpec) -> type:
    cached = _MODELS.get(spec.entity_type)
    if cached is not None:
        return cached
    module_path, _, class_name = spec.model_ref.partition(":")
    import importlib

    model = getattr(importlib.import_module(module_path), class_name)
    _MODELS[spec.entity_type] = model
    _MODEL_TO_SPEC[model] = spec
    return model


def _spec_for_instance(obj: object) -> EntitySpec | None:
    spec = _MODEL_TO_SPEC.get(type(obj))
    if spec is not None:
        return spec
    # First sight of this class: resolve every spec's model once
    # (imports are cached by the interpreter, so this is cheap).
    for candidate in _SPECS:
        _model_for(candidate)
    return _MODEL_TO_SPEC.get(type(obj))


# -- snapshot (de)serialization -------------------------------------------------


def _dump_value(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    if isinstance(value, bytes):
        return None  # registered entities carry no byte columns
    return value


def _snapshot(obj: object, spec: EntitySpec, *, before: bool) -> dict:
    """The full row as plain JSON-able data. For `before` images of
    a dirty object, changed columns read their pre-change value
    from the attribute history; everything else reads current."""
    state = inspect(obj)
    out: dict[str, object] = {}
    for column in obj.__table__.columns:
        if column.key in spec.exclude:
            continue
        if before:
            history = state.attrs[column.key].history
            if history.deleted:
                out[column.key] = _dump_value(history.deleted[0])
                continue
        out[column.key] = _dump_value(getattr(obj, column.key))
    return out


def _touch(obj: object, spec: EntitySpec) -> None:
    """Force-load every snapshotted column. A dirty/deleted object
    may carry expired attributes (an earlier commit in the same
    flow); the history recipe needs them loaded to tell old from
    new. A SELECT inside before_flush is safe — it cannot trigger
    another flush."""
    for column in obj.__table__.columns:
        if column.key in spec.exclude:
            continue
        try:
            getattr(obj, column.key)
        except Exception:
            pass  # a column that will not load reads as its default


def _load_value(column, value: object) -> object:
    """Inverse of _dump_value, per target column type."""
    if value is None:
        return None
    col_type = column.type
    if isinstance(col_type, (postgresql.UUID, sa.Uuid)):
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if isinstance(col_type, sa.DateTime):
        return (
            datetime.fromisoformat(value) if isinstance(value, str) else value
        )
    if isinstance(col_type, sa.Date):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(col_type, sa.Numeric):
        return Decimal(str(value))
    if isinstance(col_type, (sa.JSON, postgresql.JSONB)):
        return copy.deepcopy(value)
    return value


def _row_values(spec: EntitySpec, snapshot: dict) -> dict:
    model = _model_for(spec)
    values: dict[str, object] = {}
    for column in model.__table__.columns:
        if column.key in spec.exclude or column.key not in snapshot:
            continue
        values[column.key] = _load_value(column, snapshot[column.key])
    return values


# -- labels ---------------------------------------------------------------------

_VERBS = {"create": "Added", "update": "Changed", "delete": "Deleted"}


def _label_for(spec: EntitySpec, action: str, snap: dict | None) -> str:
    snap = snap or {}
    if spec.entity_type == "checkout":
        item = str(snap.get("item_name") or "an item")
        if action == "create":
            return f"Checked out '{item}'"
        if action == "delete":
            return f"Removed the checkout of '{item}'"
        return f"Updated the checkout of '{item}'"
    if spec.entity_type == "item_tag":
        return (
            "Removed a tag from an item"
            if action == "delete"
            else "Changed an item's tags"
        )
    verb = _VERBS.get(action, "Changed")
    name = ""
    for key in spec.name_keys:
        raw = snap.get(key)
        if raw:
            name = str(raw).strip()
            break
    if len(name) > 80:
        name = name[:77] + "…"
    text = f"{verb} {spec.noun}"
    if name:
        text += f" '{name}'"
    if spec.entity_type in (
        "share_config",
        "shared_item",
        "share_rule",
        "share_exclusion",
    ):
        group = snap.get("recipient_group")
        if group:
            text += f" ({group})"
    return text


# -- restorability ---------------------------------------------------------------


def _claim_status(session: Session, claim_id: object) -> str | None:
    """A claim's status as the listener sees it, read from the
    identity map / store WITHOUT flushing (before_flush is
    mid-transaction; Session.get never autoflushes)."""
    if not claim_id:
        return None
    try:
        cid = claim_id if isinstance(claim_id, uuid.UUID) else uuid.UUID(str(claim_id))
    except (ValueError, AttributeError):
        return None
    claim_spec = _SPEC_BY_TYPE["claim"]
    claim_model = _model_for(claim_spec)
    row = session.get(claim_model, cid)
    return row.status if row is not None else None


def _restorable(
    session: Session,
    spec: EntitySpec,
    action: str,
    before: dict | None,
    after: dict | None,
    actor_id: uuid.UUID | None,
    owner_id: uuid.UUID,
) -> bool:
    if spec.visibility_only:
        return False
    # Somebody else's hand on your record (a peer accepting, a
    # borrower returning, an operator verifying) is shared history:
    # visible in the trail, never rewound by your restore.
    if actor_id is not None and actor_id != owner_id:
        return False
    if spec.entity_type == "claim":
        b = (before or {}).get("status")
        a = (after or {}).get("status")
        if action == "create":
            return a == "draft"
        if action == "delete":
            return b == "draft"
        return b == "draft" and a == "draft"
    if spec.entity_type in _CLAIM_CHILDREN:
        snap = after if after is not None else before
        status = _claim_status(session, (snap or {}).get("claim_id"))
        return status == "draft"
    return True


# -- the listener -----------------------------------------------------------------


def _session_actor(session: Session) -> uuid.UUID | None:
    """Who is driving this session's work. The acting_as override
    (the restore engine, explicit service flows) wins; otherwise
    the stamp get_current_user leaves on the request session —
    session state, not a contextvar, because FastAPI runs the
    dependency and the endpoint in different context copies and a
    contextvar set in one never reaches the other's flushes."""
    override = _actor.get()
    if override is not None:
        return override
    return session.info.get("journal_actor")


def _capture(
    session: Session,
    obj: object,
    action: str,
    *,
    before: dict | None,
    after: dict | None,
) -> models.ChangeJournal | None:
    spec = _spec_for_instance(obj)
    if spec is None:
        return None
    owner_raw = getattr(obj, spec.owner_attr, None)
    if owner_raw is None:
        return None  # ownerless rows (directory companies) are platform data
    owner_id = (
        owner_raw if isinstance(owner_raw, uuid.UUID) else uuid.UUID(str(owner_raw))
    )
    if action == "update" and before == after:
        return None  # a flush that changed nothing earns no entry
    snap = after if after is not None else before
    actor_id = _session_actor(session)
    return models.ChangeJournal(
        user_id=owner_id,
        module=spec.module,
        entity_type=spec.entity_type,
        entity_id=obj.id,
        action=action,
        before=before,
        after=after,
        actor_id=actor_id,
        restorable=_restorable(
            session, spec, action, before, after, actor_id, owner_id
        ),
        label=_label_for(spec, action, snap),
    )


def _before_flush(session: Session, flush_context, instances) -> None:  # noqa: ANN001
    if _suspended.get():
        return
    entries: list[models.ChangeJournal] = []
    for obj in list(session.new):
        spec = _spec_for_instance(obj)
        if spec is None:
            continue
        if getattr(obj, "id", None) is None:
            # Column defaults fire at INSERT — after before_flush —
            # so a brand-new row has no id yet. Every registered
            # model's default is uuid4; assigning the same value
            # here is invisible to the row and gives the entry its
            # entity_id.
            obj.id = uuid.uuid4()
        entry = _capture(session, obj, "create", before=None,
                         after=_snapshot(obj, spec, before=False))
        if entry is not None:
            entries.append(entry)
    for obj in list(session.dirty):
        spec = _spec_for_instance(obj)
        if spec is None:
            continue
        if not session.is_modified(obj, include_collections=True):
            continue
        _touch(obj, spec)
        entry = _capture(
            session, obj, "update",
            before=_snapshot(obj, spec, before=True),
            after=_snapshot(obj, spec, before=False),
        )
        if entry is not None:
            entries.append(entry)
    for obj in list(session.deleted):
        spec = _spec_for_instance(obj)
        if spec is None:
            continue
        _touch(obj, spec)
        entry = _capture(session, obj, "delete",
                         before=_snapshot(obj, spec, before=False), after=None)
        if entry is not None:
            entries.append(entry)
    if entries:
        live = _live_owner_ids(session, entries)
        for entry in entries:
            # An entry whose owner no longer exists is dropped, not
            # flushed: change_journal.user_id is a hard FK and the
            # flush would take the caller's whole transaction down
            # with it (step-4 campaign D6 — a moderator removing a
            # deleted author's forum post 500'd). The dead owner's
            # trail is gone with their account by design; the
            # moderation action itself is still recorded in the
            # admin audit log by the acting service.
            if entry.user_id in live:
                session.add(entry)


def _live_owner_ids(
    session: Session, entries: list[models.ChangeJournal]
) -> set[uuid.UUID]:
    """Which of the entries' owners still have a users row. Forum
    threads/posts name their author in a PLAIN column by design
    (they survive deletion as "Former member" history), so their
    journal owner can legitimately be a deleted user. A user
    created in THIS flush (signup) counts as live — its row lands
    in the same transaction."""
    wanted = {entry.user_id for entry in entries}
    live = set(
        session.scalars(
            select(models.User.id).where(models.User.id.in_(wanted))
        )
    )
    live |= {
        obj.id
        for obj in session.new
        if isinstance(obj, models.User) and obj.id is not None
    }
    return live


def _install_listener() -> None:
    from sqlalchemy import event

    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)


_install_listener()


# -- markers -----------------------------------------------------------------------


def current_seq(db: Session, user_id: uuid.UUID) -> int:
    """The user's journal high-water mark (0 = nothing journaled)."""
    value = db.scalar(
        select(func.max(models.ChangeJournal.seq)).where(
            models.ChangeJournal.user_id == user_id
        )
    )
    return int(value or 0)


def create_marker(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    label: str = "",
    commit: bool = True,
) -> models.RestoreMarker:
    marker = models.RestoreMarker(
        user_id=user_id,
        kind=kind,
        label=(label or "").strip()[:200],
        journal_seq=current_seq(db, user_id),
    )
    db.add(marker)
    if commit:
        db.commit()
        db.refresh(marker)
    else:
        db.flush()
    return marker


def create_baseline(db: Session, user_id: uuid.UUID) -> models.RestoreMarker:
    """The account-creation marker. Idempotent: an account with a
    baseline already (re-entrant creation paths) keeps the first."""
    existing = db.scalars(
        select(models.RestoreMarker).where(
            models.RestoreMarker.user_id == user_id,
            models.RestoreMarker.kind == "baseline",
        )
    ).first()
    if existing is not None:
        return existing
    return create_marker(
        db, user_id, kind="baseline", label="Account created"
    )


def get_marker(
    db: Session, user_id: uuid.UUID, marker_id: uuid.UUID
) -> models.RestoreMarker | None:
    marker = db.get(models.RestoreMarker, marker_id)
    if marker is None or marker.user_id != user_id:
        return None
    return marker


def list_markers(db: Session, user_id: uuid.UUID) -> list[models.RestoreMarker]:
    return list(
        db.scalars(
            select(models.RestoreMarker)
            .where(models.RestoreMarker.user_id == user_id)
            .order_by(
                models.RestoreMarker.created_at.desc(),
                models.RestoreMarker.journal_seq.desc(),
            )
        )
    )


def list_entries(
    db: Session, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> tuple[list[models.ChangeJournal], int]:
    total = db.scalar(
        select(func.count(models.ChangeJournal.id)).where(
            models.ChangeJournal.user_id == user_id
        )
    )
    rows = list(
        db.scalars(
            select(models.ChangeJournal)
            .where(models.ChangeJournal.user_id == user_id)
            .order_by(models.ChangeJournal.seq.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total or 0)


def _window(
    db: Session, user_id: uuid.UUID, marker: models.RestoreMarker
) -> tuple[list[models.ChangeJournal], list[models.ChangeJournal]]:
    """(restorable work, visibility-only entries) after the marker.
    Restore events themselves are neither — they are the trail's
    punctuation, not changes to undo or to count as skipped."""
    rows = list(
        db.scalars(
            select(models.ChangeJournal)
            .where(
                models.ChangeJournal.user_id == user_id,
                models.ChangeJournal.seq > marker.journal_seq,
                models.ChangeJournal.action != "restore",
            )
            .order_by(models.ChangeJournal.seq.desc())
        )
    )
    work = [row for row in rows if row.restorable]
    skipped = [row for row in rows if not row.restorable]
    return work, skipped


def restore_preview(
    db: Session, user_id: uuid.UUID, marker: models.RestoreMarker
) -> dict:
    """The confirm modal's numbers, computed without touching
    anything: how many changes a restore would undo, and how many
    shared records it would leave alone."""
    work, skipped = _window(db, user_id, marker)
    return {
        "marker_id": marker.id,
        "changes_to_undo": len(work),
        "shared_not_changed": len(skipped),
    }


def run_daily_markers(db: Session, *, today: date | None = None) -> int:
    """Jobs seam: one daily marker per user per day, only for users
    whose journal moved since their last marker. Returns how many
    markers were created."""
    today = today or datetime.now(timezone.utc).date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    activity = db.execute(
        select(
            models.ChangeJournal.user_id, func.max(models.ChangeJournal.seq)
        ).group_by(models.ChangeJournal.user_id)
    ).all()
    created = 0
    for user_id, max_seq in activity:
        last_seq = db.scalar(
            select(func.max(models.RestoreMarker.journal_seq)).where(
                models.RestoreMarker.user_id == user_id
            )
        )
        if max_seq is None or int(max_seq) <= int(last_seq or 0):
            continue
        made_today = db.scalar(
            select(func.count(models.RestoreMarker.id)).where(
                models.RestoreMarker.user_id == user_id,
                models.RestoreMarker.created_at >= day_start,
                # The baseline is the account's birth certificate,
                # not a daily marker — it never caps the day. Any
                # REAL marker today (daily, manual, pre_*) does:
                # one fresh restore point per user per day is the
                # whole promise.
                models.RestoreMarker.kind != "baseline",
            )
        )
        if made_today:
            continue
        db.add(
            models.RestoreMarker(
                user_id=user_id,
                kind="daily",
                label="Daily restore point",
                journal_seq=int(max_seq),
            )
        )
        created += 1
    db.commit()
    return created


# -- file retention ------------------------------------------------------------------


def retention_days(db: Session) -> int:
    """The admin setting, read through billing's settings store
    (the lazy import keeps core free of a billing edge)."""
    try:
        from app.modules.billing import entitlements

        raw = entitlements.get_setting(db, RETENTION_KEY, RETENTION_DEFAULT)
        return max(1, int(raw))
    except (TypeError, ValueError):
        return RETENTION_DEFAULT


def retire_keys(
    db: Session,
    owner_id: uuid.UUID,
    keys,
    *,
    entity_type: str = "",
    entity_id: uuid.UUID | None = None,
) -> None:
    """Tombstone storage objects whose records stopped referencing
    them. Adds rows to the CALLER's transaction (no commit) so the
    tombstone lands atomically with the change that orphaned the
    file. Under the permanent flag (account deletion) the objects
    are destroyed instead — deletion stays final."""
    clean = [k for k in dict.fromkeys(keys or []) if k]
    if not clean:
        return
    if _permanent.get():
        for key in clean:
            try:
                storage.delete(key)
            except StorageError:
                continue
        return
    existing = set(
        db.scalars(
            select(models.RetainedFile.storage_key).where(
                models.RetainedFile.storage_key.in_(clean)
            )
        )
    )
    for key in clean:
        if key in existing:
            continue
        db.add(
            models.RetainedFile(
                user_id=owner_id,
                storage_key=key,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )


def retire_record_files(
    db: Session, owner_id: uuid.UUID, record, *, entity_type: str
) -> None:
    """retire_keys for a record carrying the standard attachments
    list (tools, batteries, set pieces, parts)."""
    keys = [
        item.get("key")
        for item in (getattr(record, "attachments", None) or [])
        if isinstance(item, dict)
    ]
    retire_keys(
        db, owner_id, keys, entity_type=entity_type, entity_id=record.id
    )


def purge_expired_files(db: Session, *, days: int | None = None) -> int:
    """Jobs seam: hard-delete tombstoned objects older than the
    retention window, rows and bytes together. Returns the purge
    count. A file whose bytes are already gone still loses its row
    (storage.delete is best-effort by contract)."""
    window = retention_days(db) if days is None else max(1, int(days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window)
    rows = list(
        db.scalars(
            select(models.RetainedFile).where(
                models.RetainedFile.deleted_at < cutoff
            )
        )
    )
    for row in rows:
        try:
            storage.delete(row.storage_key)
        except StorageError:
            pass
        db.delete(row)
    db.commit()
    return len(rows)


def _attachment_keys_in(snapshot: dict | None) -> set[str]:
    keys: set[str] = set()
    if not snapshot:
        return keys
    for item in snapshot.get("attachments") or []:
        if isinstance(item, dict) and item.get("key"):
            keys.add(str(item["key"]))
    photo = snapshot.get("photo_key")
    if photo:
        keys.add(str(photo))
    attachment = snapshot.get("attachment")
    if isinstance(attachment, dict) and attachment.get("key"):
        keys.add(str(attachment["key"]))
    return keys


def _live_file_keys(db: Session, user_id: uuid.UUID) -> set[str]:
    """Every storage key the user's live records still reference:
    attachment lists, the dealer profile photo, claim-upload
    evidence. Restore reconciliation measures tombstones against
    exactly this set."""
    keys: set[str] = set()
    for entity_type in _ATTACHMENT_ENTITIES:
        spec = _SPEC_BY_TYPE[entity_type]
        model = _model_for(spec)
        for row in db.scalars(
            select(model).where(getattr(model, spec.owner_attr) == user_id)
        ):
            for item in row.attachments or []:
                if isinstance(item, dict) and item.get("key"):
                    keys.add(str(item["key"]))
    profile_spec = _SPEC_BY_TYPE["agent_profile"]
    profile_model = _model_for(profile_spec)
    for row in db.scalars(
        select(profile_model).where(profile_model.user_id == user_id)
    ):
        if row.photo_key:
            keys.add(str(row.photo_key))
    evidence_spec = _SPEC_BY_TYPE["claim_evidence"]
    evidence_model = _model_for(evidence_spec)
    for row in db.scalars(
        select(evidence_model).where(evidence_model.owner_id == user_id)
    ):
        if row.source == "upload" and isinstance(row.attachment, dict):
            key = row.attachment.get("key")
            if key:
                keys.add(str(key))
    return keys


def _reconcile_files(
    db: Session,
    user_id: uuid.UUID,
    window_entries: list[models.ChangeJournal],
) -> None:
    """After a restore: keys the restored records reference again
    lose their tombstones (the files are live); keys the restore
    dropped — and that no live record references — gain one (the
    bytes stay for the retention window). Runs inside the restore
    transaction."""
    live = _live_file_keys(db, user_id)
    candidates: set[str] = set()
    for entry in window_entries:
        candidates |= _attachment_keys_in(entry.before)
        candidates |= _attachment_keys_in(entry.after)
    tombstoned = {
        row.storage_key: row
        for row in db.scalars(
            select(models.RetainedFile).where(
                models.RetainedFile.user_id == user_id
            )
        )
    }
    candidates |= set(tombstoned)
    for key in candidates:
        row = tombstoned.get(key)
        if key in live:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(
                models.RetainedFile(
                    user_id=user_id, storage_key=key, entity_type="restore"
                )
            )


# -- the restore engine ---------------------------------------------------------


def _current_snapshot(db: Session, spec: EntitySpec, entity_id: uuid.UUID):
    model = _model_for(spec)
    row = db.get(model, entity_id)
    if row is None:
        return None, None
    return row, _snapshot(row, spec, before=False)


def _claim_gate(
    db: Session, spec: EntitySpec, entry: models.ChangeJournal
) -> bool:
    """True when a claim-family op must be SKIPPED (counted as not
    changed): the claim has a life beyond the journal window —
    once filed, its lines/evidence/messages are the insurer-facing
    record and a restore never reaches into it."""
    if spec.entity_type == "claim":
        return False  # claim rows themselves are gated per-op below
    if spec.entity_type not in _CLAIM_CHILDREN:
        return False
    snap = entry.after if entry.after is not None else entry.before
    status = _claim_status(db, (snap or {}).get("claim_id"))
    return status is not None and status != "draft"


# -- the restore engine ---------------------------------------------------------


def _current_snapshot(db: Session, spec: EntitySpec, entity_id: uuid.UUID):
    model = _model_for(spec)
    row = db.get(model, entity_id)
    if row is None:
        return None, None
    return row, _snapshot(row, spec, before=False)


def _claim_gate(
    db: Session, spec: EntitySpec, entry: models.ChangeJournal
) -> bool:
    """True when a claim-family op must be SKIPPED (counted as not
    changed): the claim has a life beyond the journal window —
    once filed, its lines/evidence/messages are the insurer-facing
    record and a restore never reaches into it."""
    if spec.entity_type == "claim":
        return False  # claim rows themselves are gated per-op below
    if spec.entity_type not in _CLAIM_CHILDREN:
        return False
    snap = entry.after if entry.after is not None else entry.before
    status = _claim_status(db, (snap or {}).get("claim_id"))
    return status is not None and status != "draft"


def restore_to_marker(
    db: Session,
    user_id: uuid.UUID,
    marker: models.RestoreMarker,
    *,
    actor_id: uuid.UUID | None,
) -> dict:
    """Roll the account back to `marker`. ONE transaction: a
    pre_restore marker is written first (its own commit, so the
    restore can itself be undone even if this one aborts), then
    every restorable entry after the marker is inverted STRICTLY
    NEWEST FIRST — deletes re-created with their original ids,
    updates rolled back to the before snapshot, creates removed.
    Newest-first is what makes the foreign keys land: the codebase
    deletes children before parents (and creates parents before
    children), so reversing the journal in exact reverse order
    re-inserts parents before their children and removes children
    before their parents. Any conflict aborts everything with a
    friendly report.

    The engine's own writes are journaled as ordinary entries
    (actor = whoever ran the restore): that is precisely what
    makes a restore undoable — restoring to the pre_restore
    marker inverts the restore itself."""
    work, skipped = _window(db, user_id, marker)
    pre_marker = create_marker(
        db,
        user_id,
        kind="pre_restore",
        label=f"Before restoring to {marker.label or 'a restore point'}",
    )
    restored = 0
    engine_skipped = 0
    try:
        with acting_as(actor_id):
            for entry in work:  # _window orders newest first
                spec = _SPEC_BY_TYPE[entry.entity_type]
                if _claim_gate(db, spec, entry):
                    engine_skipped += 1
                    continue
                row, current = _current_snapshot(db, spec, entry.entity_id)
                if entry.action == "delete":
                    if row is not None:
                        existing = {
                            k: current.get(k) for k in (entry.before or {})
                        }
                        if existing == (entry.before or {}):
                            restored += 1  # already back, as it was
                            continue
                        raise RestoreConflict(
                            f"'{entry.label}' can't be undone: a record "
                            "with the same id is back already, with "
                            "different details. Nothing was changed."
                        )
                    model = _model_for(spec)
                    db.add(model(**_row_values(spec, entry.before or {})))
                    db.flush()
                    restored += 1
                elif entry.action == "update":
                    if row is None:
                        raise RestoreConflict(
                            f"'{entry.label}' can't be undone: the record "
                            "it changed is gone, and not through your "
                            "history. Nothing was changed."
                        )
                    if spec.entity_type == "claim" and row.status != "draft":
                        engine_skipped += 1  # filed since: hands off
                        continue
                    for key, value in _row_values(
                        spec, entry.before or {}
                    ).items():
                        if key == "id":
                            continue
                        setattr(row, key, value)
                    db.flush()
                    restored += 1
                else:  # create → remove the row it added
                    if row is None:
                        restored += 1  # already gone; end state matches
                        continue
                    if spec.entity_type == "claim" and row.status != "draft":
                        engine_skipped += 1  # filed since: hands off
                        continue
                    db.delete(row)
                    db.flush()
                    restored += 1

            _reconcile_files(db, user_id, work)
            db.add(
                models.ChangeJournal(
                    user_id=user_id,
                    module="core",
                    entity_type="restore",
                    entity_id=marker.id,
                    action="restore",
                    before=None,
                    after={
                        "restored": restored,
                        "not_changed": len(skipped) + engine_skipped,
                        "marker_kind": marker.kind,
                    },
                    actor_id=actor_id,
                    marker_id=marker.id,
                    restorable=False,
                    label=(
                        f"Restored to "
                        f"'{marker.label or 'restore point'}'"
                    ),
                )
            )
            db.commit()
    except RestoreConflict:
        db.rollback()
        raise
    except sa.exc.IntegrityError as exc:
        db.rollback()
        raise RestoreConflict(
            "The restore hit records that no longer fit together "
            "(something changed outside your history). Nothing was "
            "changed."
        ) from exc
    return {
        "restored": restored,
        "not_changed": len(skipped) + engine_skipped,
        "pre_restore_marker_id": pre_marker.id,
        "marker_id": marker.id,
    }
