"""Tool Expansion matching engine (owner spec 2026-10-25).

Ryan's rule, one sentence: the system notes model numbers and
checks them across all users' data — if a model number in my
inventory shows up in another person's data as part of a set,
that set's piece model numbers are possible addons for my tool.

Two flavors, both that rule:

- SET-TO-SET: my set's model number equals another user's set's
  model number → their ADDON pieces for that set (SetPiece rows
  marked addon, plus tools attached into the set) that I don't
  already own become suggestions tied to my set.
- MEMBERSHIP: a model number I own (a standalone tool/battery,
  or a piece of one of my sets) appears as a piece inside another
  user's set → that set's other pieces that I don't own become
  suggestions tied to my item/set.

THE POOL is the community catalog's pool: users whose Sharing
contribution is ON (users.catalog_contribute, default ON). The
viewer never feeds their own suggestions.

SCALE SHAPE (2026-10-26, audit B1): the pool derivation is
computed ONCE per process into a snapshot (source sets loaded
column-light, two inverted indexes, the community spelling
votes) and reused by every read — the original derived-at-read
shape reloaded the entire pool as full ORM rows on EVERY call
to /suggestions, /summary and /counts and re-derived all
matches in Python (measured 2.1 s for a 4-item viewer against
a 51k-item pool, growing with every new contributor). Per-viewer
generation now walks only the candidate source sets an inverted
index names. The snapshot is invalidated by a session listener
the moment a flush writes a Tool, Battery or SetPiece or flips
a user's catalog_contribute — opting out removes a user's
weight on the very write that opts out. The same flush bumps
the te_pool_epoch counter INSIDE the same transaction, so every
other API worker sees the bump on its next read (one primary-
key lookup) and rebuilds at once; a TTL backstops only a missed
bump. User controls (dismissals, reports, the kill
threshold) are NEVER cached: they are read live from their
small ledgers on every call, so they bite immediately.

PRIVACY IS A HARD LAW: a suggestion carries ONLY the suggested
piece's name + model number (spelled the way the community most
often records them) and the link to the VIEWER'S OWN item. Source
owners' identities, serials, prices, photos and notes never enter
the payload — they are never even loaded into the result shape.

USER CONTROLS:
- Dismiss ("remove for me"): hides one suggestion on one of the
  viewer's items, for that viewer only.
- Report ("not relevant / inaccurate"): judges a MATCH (the
  normalized anchor-model ↔ suggested-model pairing). The
  reporter's own view hides the pairing at once; when
  KILL_THRESHOLD distinct users have reported the same pairing,
  it stops generating for everyone.

FRESHNESS: a set added a second ago already feeds (and
receives) suggestions everywhere: the write retires its own
process's snapshot at flush time and bumps the shared pool
epoch in the same transaction, so sibling workers rebuild on
their next read. Suggestions themselves are still never stored.
"""

import re
import threading
import time
import uuid
from collections import Counter, defaultdict

from sqlalchemy import event, func, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.tool_expansion import models

# The community-kill threshold (owner spec 2026-10-25): how many
# DISTINCT users must call the same match inaccurate before it
# stops generating for everyone. An operator setting (system
# settings store), not a constant buried in the matching code —
# the default below applies only until the operator sets it.
KILL_THRESHOLD_KEY = "tool_expansion.kill_threshold"
KILL_THRESHOLD_DEFAULT = 3

_WHITESPACE = re.compile(r"\s+")

# Piece presence states that still mean "the user has this piece":
# present, or owned-but-misplaced. Sold / removed pieces are gone
# from the owner's hands, so their model numbers neither suppress
# a suggestion nor anchor a match.
_HELD_PIECE_STATUSES = frozenset({"present", "missing"})


class ExpansionNotFound(LookupError):
    """The named anchor item isn't the caller's (or doesn't exist)."""


def norm_model(value) -> str:
    """Model-number comparison form: trim, collapse internal
    whitespace, casefold — the importer's merge-dedupe pattern
    (inventory/importer.py), deliberately NOT the company-name
    matcher: punctuation inside a part number is identity and is
    never folded away, and no suffix is ever dropped."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", str(value).strip()).casefold()


def kill_threshold(db: Session) -> int:
    raw = entitlements.get_setting(db, KILL_THRESHOLD_KEY, KILL_THRESHOLD_DEFAULT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return KILL_THRESHOLD_DEFAULT
    return value if value >= 1 else KILL_THRESHOLD_DEFAULT


# -- the pool -------------------------------------------------------------


class _SourcePiece:
    """One piece of a contributor's set, as matching sees it.

    `match_norms` is every normalized model number that identifies
    the piece (a SetPiece row has exactly one part number; a tool
    attached into the set also answers to its alternate model
    numbers). `norm` is the PRIMARY — the number a suggestion for
    this piece is keyed and displayed by.
    """

    __slots__ = ("norm", "display", "name", "is_addon", "match_norms")

    def __init__(self, norm, display, name, is_addon, match_norms):
        self.norm = norm
        self.display = display
        self.name = name
        self.is_addon = is_addon
        self.match_norms = match_norms


class _SourceSet:
    __slots__ = ("owner_id", "model_norms", "pieces")

    def __init__(self, owner_id, model_norms, pieces):
        # owner_id is INTERNAL bookkeeping only (per-viewer pool
        # exclusion + spelling-vote subtraction). It never enters
        # a payload — the privacy law at the top of this file.
        self.owner_id = owner_id
        self.model_norms = model_norms  # the set's own model numbers
        self.pieces = pieces  # list[_SourcePiece]


def _model_norms_of(model, model_numbers) -> set[str]:
    """Every normalized model number a tool record answers to:
    the primary model plus its multi-value model numbers list."""
    norms = set()
    primary = norm_model(model)
    if primary:
        norms.add(primary)
    for entry in model_numbers or []:
        folded = norm_model(entry)
        if folded:
            norms.add(folded)
    return norms


# -- the pool snapshot ------------------------------------------------------
#
# One derivation per process, reused by every read until a write
# invalidates it or the TTL ages it out (see the module docstring
# for the shape and the invalidation contract). The snapshot holds
# ONLY what matching needs, loaded column-light — never full ORM
# rows with their JSONB attachments/custom data (the original
# load hauled ~640k piece rows' worth of full rows per call at
# staging scale).

# Backstop only: the pool epoch (below) is what normally retires
# a snapshot across processes; the TTL bounds the damage if a
# write path ever bumps neither (e.g. out-of-band SQL).
POOL_TTL_SECONDS = 60.0


class _PoolSnapshot:
    __slots__ = (
        "built_at",
        "epoch",
        "source_sets",
        "by_piece_model",
        "by_set_model",
        "name_votes",
        "display_votes",
        "own_name_votes",
        "own_display_votes",
    )

    def __init__(self, built_at, epoch, source_sets):
        self.built_at = built_at
        self.epoch = epoch
        self.source_sets = source_sets
        # Inverted indexes: model number -> indexes into
        # source_sets, in source (Tool.id) order. by_piece_model
        # answers "which source sets contain a piece answering to
        # this number" (the membership candidates); by_set_model
        # answers "which source sets ARE this number" (the
        # set-to-set candidates).
        self.by_piece_model: dict[str, list[int]] = defaultdict(list)
        self.by_set_model: dict[str, list[int]] = defaultdict(list)
        # Community spelling votes, global and per owner — the
        # per-owner copies let a read subtract the viewer's own
        # contributions, reproducing exactly the votes the old
        # per-viewer pool (which excluded the viewer) produced.
        self.name_votes: dict[str, Counter] = defaultdict(Counter)
        self.display_votes: dict[str, Counter] = defaultdict(Counter)
        self.own_name_votes: dict = defaultdict(lambda: defaultdict(Counter))
        self.own_display_votes: dict = defaultdict(lambda: defaultdict(Counter))
        for idx, source in enumerate(source_sets):
            for norm in source.model_norms:
                self.by_set_model[norm].append(idx)
            seen_piece_norms: set[str] = set()
            for piece in source.pieces:
                self.name_votes[piece.norm][piece.name] += 1
                self.display_votes[piece.norm][piece.display] += 1
                self.own_name_votes[source.owner_id][piece.norm][piece.name] += 1
                self.own_display_votes[source.owner_id][piece.norm][
                    piece.display
                ] += 1
                for norm in piece.match_norms:
                    if norm not in seen_piece_norms:
                        seen_piece_norms.add(norm)
                        self.by_piece_model[norm].append(idx)


def _read_epoch(db: Session) -> int:
    """The shared pool version (te_pool_epoch row 1). One primary-
    key read; a missing table/row reads as 0 — the TTL and the
    local invalidation still bound freshness there (defensive:
    every real database carries the row via migration 0063 /
    create_all)."""
    try:
        value = db.scalar(select(models.PoolEpoch.epoch).where(models.PoolEpoch.id == 1))
    except Exception:
        db.rollback()
        return 0
    return int(value) if value is not None else 0


def _bump_epoch(session) -> None:  # noqa: ANN001
    """Advance the shared pool version INSIDE the caller's
    transaction (called from the after_flush listener): sibling
    workers see the bump exactly when the write commits — never
    before, never stale after."""
    result = session.execute(
        update(models.PoolEpoch)
        .where(models.PoolEpoch.id == 1)
        .values(epoch=models.PoolEpoch.epoch + 1)
    )
    if result.rowcount == 0:
        # The seed row should always exist (migration 0063 /
        # create_all + first build); create it inline rather than
        # flushing from inside after_flush.
        session.execute(
            insert(models.PoolEpoch).values(id=1, epoch=1)
        )


def _build_snapshot(db: Session, epoch: int) -> _PoolSnapshot:
    contributor_ids = set(
        db.scalars(
            select(core_models.User.id).where(
                core_models.User.catalog_contribute.is_(True)
            )
        )
    )
    source_sets: list[_SourceSet] = []
    if contributor_ids:
        tool = inventory_models.Tool
        piece_model = inventory_models.SetPiece
        set_rows = db.execute(
            select(tool.id, tool.owner_id, tool.model, tool.model_numbers)
            .where(
                tool.owner_id.in_(contributor_ids),
                tool.is_set.is_(True),
            )
            .order_by(tool.id)
        ).all()
        set_ids = [row.id for row in set_rows]

        pieces_by_set: dict[uuid.UUID, list[_SourcePiece]] = defaultdict(list)
        if set_ids:
            for set_id, part_number, name, kind in db.execute(
                select(
                    piece_model.set_id,
                    piece_model.part_number,
                    piece_model.name,
                    piece_model.kind,
                ).where(piece_model.set_id.in_(set_ids))
            ):
                folded = norm_model(part_number)
                if not folded:
                    continue  # a piece with no number can neither match nor be named by number
                pieces_by_set[set_id].append(
                    _SourcePiece(
                        norm=folded,
                        display=(part_number or "").strip(),
                        name=name,
                        is_addon=kind == "addon",
                        match_norms={folded},
                    )
                )
            # Tools folded into a set are its addon pieces too
            # (the sets model: attached tools live inside the
            # set's addon section).
            for set_id, model, model_numbers, name in db.execute(
                select(
                    tool.attached_to_set_id,
                    tool.model,
                    tool.model_numbers,
                    tool.name,
                ).where(tool.attached_to_set_id.in_(set_ids))
            ):
                norms = _model_norms_of(model, model_numbers)
                primary = norm_model(model)
                if not norms or not primary:
                    continue
                pieces_by_set[set_id].append(
                    _SourcePiece(
                        norm=primary,
                        display=(model or "").strip(),
                        name=name,
                        is_addon=True,
                        match_norms=norms,
                    )
                )

        source_sets = [
            _SourceSet(
                owner_id=row.owner_id,
                model_norms=_model_norms_of(row.model, row.model_numbers),
                pieces=pieces_by_set.get(row.id, []),
            )
            for row in set_rows
        ]
    return _PoolSnapshot(time.monotonic(), epoch, source_sets)


_pool_lock = threading.RLock()
_pool_snapshot: _PoolSnapshot | None = None


def invalidate_pool_cache() -> None:
    """Drop the pool snapshot; the next read rebuilds it. Called
    by the session listener below on every write that can change
    the pool, and available to any future write path that bypasses
    the ORM (bulk DML) — those must call it themselves."""
    global _pool_snapshot
    with _pool_lock:
        _pool_snapshot = None


def _pool(db: Session) -> _PoolSnapshot:
    """The current snapshot, rebuilt when the shared epoch moved
    (any worker's pool write), when this process invalidated its
    own copy, or when the TTL backstop ages it out. The epoch
    read happens on every call — that single indexed lookup is
    the whole cross-process freshness cost."""
    global _pool_snapshot
    epoch = _read_epoch(db)
    snap = _pool_snapshot
    if (
        snap is not None
        and snap.epoch == epoch
        and time.monotonic() - snap.built_at < POOL_TTL_SECONDS
    ):
        return snap
    with _pool_lock:
        snap = _pool_snapshot
        if (
            snap is None
            or snap.epoch != epoch
            or time.monotonic() - snap.built_at >= POOL_TTL_SECONDS
        ):
            snap = _build_snapshot(db, epoch)
            _pool_snapshot = snap
        return snap


_POOL_WATCHED = (
    inventory_models.Tool,
    inventory_models.Battery,
    inventory_models.SetPiece,
)


def _pool_invalidation_listener(session, flush_context) -> None:  # noqa: ANN001
    """after_flush: any write to a pool-feeding table (tools,
    batteries, set pieces) or a catalog_contribute flip retires
    this process's snapshot at the moment of the write AND bumps
    the shared pool epoch inside the same transaction, so every
    other worker retires its copy on its next read — that is what
    makes opt-out (and every edit) immediate fleet-wide. Runs on
    every flush of every session; the isinstance scan over the
    flush's own objects is the whole cost when nothing
    pool-shaped changed."""
    watched = False
    for obj in session.new:
        if isinstance(obj, _POOL_WATCHED):
            watched = True
            break
    if not watched:
        for obj in session.deleted:
            if isinstance(obj, _POOL_WATCHED):
                watched = True
                break
    if not watched:
        for obj in session.dirty:
            if isinstance(obj, _POOL_WATCHED):
                watched = True
                break
            if isinstance(obj, core_models.User):
                history = inspect(obj).attrs.catalog_contribute.history
                if history.has_changes():
                    watched = True
                    break
    if watched:
        _bump_epoch(session)
        invalidate_pool_cache()


def _install_pool_listener() -> None:
    # The change journal's install pattern (core/journal.py):
    # module import installs once, guarded against double-install.
    if not event.contains(Session, "after_flush", _pool_invalidation_listener):
        event.listen(Session, "after_flush", _pool_invalidation_listener)


_install_pool_listener()


# -- the viewer's side ------------------------------------------------------


class _Anchor:
    """One of the viewer's own items a suggestion can tie to."""

    __slots__ = ("kind", "id", "name", "is_set", "models", "set_models")

    def __init__(self, kind, id, name, is_set, models, set_models):
        self.kind = kind  # "tool" | "battery"
        self.id = id
        self.name = name
        self.is_set = is_set
        # Every model number this item answers to for MEMBERSHIP
        # matching: its own numbers, plus (for a set) its held
        # pieces' part numbers.
        self.models = models
        # A set's OWN model numbers only — the set-to-set key.
        self.set_models = set_models


def _load_viewer(db: Session, viewer_id) -> tuple[list[_Anchor], set[str]]:
    """The viewer's anchors and their full owned-model set.

    OWNED = every model number anywhere in the viewer's inventory:
    tools (standalone, sets, and tools attached into their sets),
    batteries, and held set pieces. A suggestion for an owned
    model is never generated — you can't expand into what you
    already have.

    Column-light (scale fix, 2026-10-26): only the columns
    matching reads — a heavy viewer's own rows were never the
    bottleneck, but hauling their full JSONB-laden records to
    fold six strings was waste on every call.
    """
    tool = inventory_models.Tool
    battery_model = inventory_models.Battery
    piece_model = inventory_models.SetPiece
    tool_rows = db.execute(
        select(
            tool.id,
            tool.name,
            tool.is_set,
            tool.model,
            tool.model_numbers,
            tool.attached_to_set_id,
        )
        .where(tool.owner_id == viewer_id)
        .order_by(tool.id)
    ).all()
    battery_rows = db.execute(
        select(battery_model.id, battery_model.name, battery_model.model)
        .where(battery_model.owner_id == viewer_id)
        .order_by(battery_model.id)
    ).all()
    piece_rows = db.execute(
        select(piece_model.set_id, piece_model.part_number, piece_model.status)
        .where(piece_model.owner_id == viewer_id)
    ).all()

    owned: set[str] = set()
    for row in tool_rows:
        owned |= _model_norms_of(row.model, row.model_numbers)
    for row in battery_rows:
        folded = norm_model(row.model)
        if folded:
            owned.add(folded)
    held_piece_norms_by_set: dict[uuid.UUID, set[str]] = defaultdict(set)
    for set_id, part_number, status in piece_rows:
        folded = norm_model(part_number)
        if not folded:
            continue
        if status in _HELD_PIECE_STATUSES:
            owned.add(folded)
            held_piece_norms_by_set[set_id].add(folded)

    anchors: list[_Anchor] = []
    for row in tool_rows:
        if row.attached_to_set_id is not None:
            continue  # inside one of the viewer's sets — not its own anchor
        own = _model_norms_of(row.model, row.model_numbers)
        models = set(own)
        if row.is_set:
            models |= held_piece_norms_by_set.get(row.id, set())
        anchors.append(
            _Anchor(
                kind="tool",
                id=row.id,
                name=row.name,
                is_set=bool(row.is_set),
                models=models,
                set_models=own if row.is_set else set(),
            )
        )
    for row in battery_rows:
        folded = norm_model(row.model)
        anchors.append(
            _Anchor(
                kind="battery",
                id=row.id,
                name=row.name,
                is_set=False,
                models={folded} if folded else set(),
                set_models=set(),
            )
        )
    return anchors, owned


# -- generation -------------------------------------------------------------


def _generate(db: Session, viewer_id, pool: _PoolSnapshot) -> list[dict]:
    """Raw live suggestions for the viewer, before user controls:
    [{anchor, anchor_model, suggested_model}] — one row per
    (anchor item, suggested model). Name/display resolution and
    the dismissal/report filters apply on top in _live_groups.

    The walk visits only the source sets the snapshot's inverted
    indexes name as candidates for this anchor — a source set can
    change an anchor's answer only by BEING one of the anchor's
    set models (set-to-set) or by CONTAINING a piece answering to
    one of the anchor's models (membership) — and visits them in
    the pool's load order, so first-writer-wins resolves exactly
    as the old whole-pool loop did. The viewer's own sets are
    skipped outright: the pool the old code built excluded the
    viewer, so their data never fed their own suggestions (not
    even a sold-off addon piece of their own set)."""
    anchors, owned = _load_viewer(db, viewer_id)
    if not anchors or not pool.source_sets:
        return []

    # Every set model the viewer owns. A source set whose model
    # matches ANY of them is a set the viewer already has: its
    # standard contents are not expansions of anything the viewer
    # owns (set-to-set below still surfaces its ADDONS, tied to
    # the viewer's own copy of that set).
    viewer_set_norms: set[str] = set()
    for anchor in anchors:
        if anchor.is_set:
            viewer_set_norms |= anchor.set_models

    raw: list[dict] = []
    for anchor in anchors:
        found: dict[str, str] = {}  # suggested norm -> anchor model norm
        candidates: set[int] = set()
        if anchor.is_set:
            for norm in anchor.set_models:
                candidates.update(pool.by_set_model.get(norm, ()))
        for norm in anchor.models:
            candidates.update(pool.by_piece_model.get(norm, ()))
        for idx in sorted(candidates):
            source = pool.source_sets[idx]
            if source.owner_id == viewer_id:
                continue  # the viewer never feeds their own suggestions
            # SET-TO-SET: same set on both sides → their addons.
            if anchor.is_set and anchor.set_models & source.model_norms:
                anchor_model = sorted(anchor.set_models & source.model_norms)[0]
                for piece in source.pieces:
                    if not piece.is_addon:
                        continue
                    if piece.norm in owned or piece.norm in found:
                        continue
                    found[piece.norm] = anchor_model
            # MEMBERSHIP: one of my model numbers lives in their
            # set as a piece → their set's other pieces. A source
            # set the viewer already owns (by model) is skipped
            # wholesale: its pieces came WITH the viewer's copy,
            # so neither the membership bridge through one
            # recorded piece nor a loose matching tool may
            # re-offer them as expansions.
            if source.model_norms & viewer_set_norms:
                continue
            matched: set[str] = set()
            for piece in source.pieces:
                matched |= piece.match_norms & anchor.models
            if matched:
                anchor_model = sorted(matched)[0]
                for piece in source.pieces:
                    if piece.norm in owned or piece.norm in found:
                        continue
                    found[piece.norm] = anchor_model
        for suggested_model, anchor_model in found.items():
            raw.append(
                {
                    "anchor": anchor,
                    "anchor_model": anchor_model,
                    "suggested_model": suggested_model,
                }
            )
    return raw


def _pick(counter: Counter) -> str:
    if not counter:
        return ""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _pick_for_viewer(votes: dict, own_votes: dict, viewer_id, norm: str) -> str:
    """How the community spells one suggested model, for THIS
    viewer: the snapshot's pool-wide votes minus the viewer's own
    contributions — exactly the votes the old per-viewer pool
    (built excluding the viewer) would have counted. Most
    frequent wins; ties break to the lexicographically first
    spelling so the answer is stable between calls (the
    catalog's display-spelling rule, made deterministic)."""
    counter = votes.get(norm)
    if not counter:
        return ""
    own = own_votes.get(viewer_id, {}).get(norm)
    if own:
        counter = counter - own  # Counter subtraction drops dead votes
    return _pick(counter)


def _report_state(
    db: Session, viewer_id
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """(killed, my_reported): the report ledger's two filters over
    (anchor_model, suggested_model) pairings — the pairings the
    community kill threshold has stopped for everyone, and the
    pairings THIS viewer reported (hidden for them at once).
    Read LIVE on every call from the ledger — never from the
    snapshot — so a report (including the third report that kills
    a match) bites on the very next read. The ledger's unique
    (user, pair) constraint makes COUNT(*) the distinct-user
    count the threshold speaks in; the pair index (migration
    0062) serves the GROUP BY."""
    threshold = kill_threshold(db)
    report_counts: dict[tuple[str, str], int] = {
        (anchor_model, suggested_model): count
        for anchor_model, suggested_model, count in db.execute(
            select(
                models.ExpansionReport.anchor_model,
                models.ExpansionReport.suggested_model,
                func.count(),
            ).group_by(
                models.ExpansionReport.anchor_model,
                models.ExpansionReport.suggested_model,
            )
        )
    }
    my_reported: set[tuple[str, str]] = set(
        db.execute(
            select(
                models.ExpansionReport.anchor_model,
                models.ExpansionReport.suggested_model,
            ).where(models.ExpansionReport.user_id == viewer_id)
        )
    )
    killed = {
        pair for pair, count in report_counts.items() if count >= threshold
    }
    return killed, my_reported


def _live_groups(db: Session, viewer_id) -> list[dict]:
    """The full live answer, user controls applied:
    [{item: {...}, suggestions: [{name, model_number,
    anchor_model, suggested_model}]}] — groups and suggestions
    in a stable order (item name, then suggested model)."""
    pool = _pool(db)
    raw = _generate(db, viewer_id, pool)
    if not raw:
        return []

    killed, my_reported = _report_state(db, viewer_id)

    dismissed = {
        (row.anchor_kind, row.anchor_id, row.suggested_model)
        for row in db.scalars(
            select(models.ExpansionDismissal).where(
                models.ExpansionDismissal.user_id == viewer_id
            )
        )
    }

    groups: dict[tuple[str, uuid.UUID], dict] = {}
    for row in raw:
        anchor = row["anchor"]
        pair = (row["anchor_model"], row["suggested_model"])
        if pair in killed or pair in my_reported:
            continue
        if (anchor.kind, anchor.id, row["suggested_model"]) in dismissed:
            continue
        key = (anchor.kind, anchor.id)
        group = groups.get(key)
        if group is None:
            group = {
                "item": {
                    "kind": anchor.kind,
                    "id": anchor.id,
                    "name": anchor.name,
                    "is_set": anchor.is_set,
                },
                "suggestions": [],
            }
            groups[key] = group
        group["suggestions"].append(
            {
                "name": _pick_for_viewer(
                    pool.name_votes,
                    pool.own_name_votes,
                    viewer_id,
                    row["suggested_model"],
                ),
                "model_number": _pick_for_viewer(
                    pool.display_votes,
                    pool.own_display_votes,
                    viewer_id,
                    row["suggested_model"],
                ),
                "anchor_model": row["anchor_model"],
                "suggested_model": row["suggested_model"],
            }
        )

    ordered = sorted(
        groups.values(),
        key=lambda g: (g["item"]["name"].casefold(), g["item"]["kind"]),
    )
    for group in ordered:
        group["suggestions"].sort(key=lambda s: s["suggested_model"])
    return ordered


# -- public reads -------------------------------------------------------------


def suggestions(db: Session, viewer_id, *, kind=None, item_id=None) -> dict:
    groups = _live_groups(db, viewer_id)
    if kind is not None and item_id is not None:
        groups = [
            g
            for g in groups
            if g["item"]["kind"] == kind and g["item"]["id"] == item_id
        ]
    return {
        "total": sum(len(g["suggestions"]) for g in groups),
        "groups": groups,
    }


def summary(db: Session, viewer_id) -> dict:
    groups = _live_groups(db, viewer_id)
    top = []
    # The top list feeds exactly one consumer — the Home
    # widget — whose rows choice runs 2–5 (widget options
    # Wave 4 batch B), so the cap is 5: the widget slices
    # to the member's setting, and its default (2) is
    # unchanged. `count` below always carries the full
    # suggestion total.
    for group in groups:
        for suggestion in group["suggestions"]:
            top.append(
                {
                    "name": suggestion["name"],
                    "model_number": suggestion["model_number"],
                    "item_name": group["item"]["name"],
                }
            )
            if len(top) == 5:
                break
        if len(top) == 5:
            break
    return {
        "count": sum(len(g["suggestions"]) for g in groups),
        "top": top,
    }


def counts(db: Session, viewer_id) -> dict:
    groups = _live_groups(db, viewer_id)
    return {
        "counts": {
            f"{g['item']['kind']}:{g['item']['id']}": len(g["suggestions"])
            for g in groups
            if g["suggestions"]
        }
    }


def archived(db: Session, viewer_id) -> dict:
    """The Archived matches read (main tab layout program,
    lane 5, 2026-11-10): the viewer's own dismissal ledger, made
    readable — Ryan's model turns "remove for me" into "move to
    archived matches", and the archive tab is where the user
    finds those matches again. Same ledger, same rows; this read
    is the only new thing.

    Display resolution is honest about what still exists:
    - the suggested piece's name + display model number resolve
      from the live pool's community spelling votes (the same
      `_pick_for_viewer` the live list uses) — a match whose
      source data no longer generates leaves no votes behind, so
      the name comes back "" and the model number falls back to
      the ledger's stored normalized key, never an invented
      spelling;
    - the anchor is the viewer's OWN item, loaded by id — an
      item deleted since the dismissal resolves to None and the
      row stands as a tombstone on the facts the ledger holds;
    - `restorable` says whether un-archiving puts the match back
      on the Matches tab today: the derivation still produces it
      for that anchor AND the pairing is neither community-killed
      nor reported by this viewer."""
    rows = db.scalars(
        select(models.ExpansionDismissal)
        .where(models.ExpansionDismissal.user_id == viewer_id)
        .order_by(models.ExpansionDismissal.created_at.desc())
    ).all()
    if not rows:
        return {"total": 0, "entries": []}

    pool = _pool(db)

    tool_ids = {r.anchor_id for r in rows if r.anchor_kind == "tool"}
    battery_ids = {r.anchor_id for r in rows if r.anchor_kind == "battery"}
    items: dict[tuple[str, uuid.UUID], dict] = {}
    if tool_ids:
        tool = inventory_models.Tool
        for row in db.execute(
            select(tool.id, tool.name, tool.is_set).where(
                tool.owner_id == viewer_id, tool.id.in_(tool_ids)
            )
        ):
            items[("tool", row.id)] = {
                "kind": "tool",
                "id": row.id,
                "name": row.name,
                "is_set": bool(row.is_set),
            }
    if battery_ids:
        battery_model = inventory_models.Battery
        for row in db.execute(
            select(battery_model.id, battery_model.name).where(
                battery_model.owner_id == viewer_id,
                battery_model.id.in_(battery_ids),
            )
        ):
            items[("battery", row.id)] = {
                "kind": "battery",
                "id": row.id,
                "name": row.name,
                "is_set": False,
            }

    killed, my_reported = _report_state(db, viewer_id)
    live_pairs: dict[tuple[str, uuid.UUID, str], str] = {
        (row["anchor"].kind, row["anchor"].id, row["suggested_model"]): row[
            "anchor_model"
        ]
        for row in _generate(db, viewer_id, pool)
    }

    entries = []
    for row in rows:
        name = _pick_for_viewer(
            pool.name_votes, pool.own_name_votes, viewer_id, row.suggested_model
        )
        display = _pick_for_viewer(
            pool.display_votes,
            pool.own_display_votes,
            viewer_id,
            row.suggested_model,
        )
        anchor_model = live_pairs.get(
            (row.anchor_kind, row.anchor_id, row.suggested_model)
        )
        pair = (
            (anchor_model, row.suggested_model)
            if anchor_model is not None
            else None
        )
        restorable = (
            pair is not None and pair not in killed and pair not in my_reported
        )
        entries.append(
            {
                "anchor_kind": row.anchor_kind,
                "anchor_id": row.anchor_id,
                "item": items.get((row.anchor_kind, row.anchor_id)),
                "name": name,
                "model_number": display or row.suggested_model,
                "suggested_model": row.suggested_model,
                "archived_at": row.created_at,
                "restorable": restorable,
            }
        )
    return {"total": len(entries), "entries": entries}


# -- user controls ------------------------------------------------------------


def dismiss(db: Session, viewer_id, *, anchor_kind, anchor_id, suggested_model) -> None:
    """Remove one suggestion for this viewer, on this item,
    forever. Idempotent — dismissing twice is the same state."""
    folded = norm_model(suggested_model)
    if not folded:
        raise ExpansionNotFound("Nothing to remove.")
    table = (
        inventory_models.Tool
        if anchor_kind == "tool"
        else inventory_models.Battery
    )
    item = db.get(table, anchor_id)
    if item is None or item.owner_id != viewer_id:
        raise ExpansionNotFound("That item isn't yours.")
    existing = db.scalar(
        select(models.ExpansionDismissal).where(
            models.ExpansionDismissal.user_id == viewer_id,
            models.ExpansionDismissal.anchor_kind == anchor_kind,
            models.ExpansionDismissal.anchor_id == anchor_id,
            models.ExpansionDismissal.suggested_model == folded,
        )
    )
    if existing is not None:
        return
    db.add(
        models.ExpansionDismissal(
            user_id=viewer_id,
            anchor_kind=anchor_kind,
            anchor_id=anchor_id,
            suggested_model=folded,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # a racing double-submit landed first — same state


def unarchive(db: Session, viewer_id, *, anchor_kind, anchor_id, suggested_model) -> None:
    """Bring one archived match back: delete this viewer's ledger
    row (the exact inverse of `dismiss`). The row is the user's
    own paperwork, keyed by the full dismissal key — it deletes
    even when the anchor item is gone (the tombstone case), and
    a key with no row is a 404, not a silent no-op: the client
    named something that is not in this user's archive."""
    folded = norm_model(suggested_model)
    row = db.scalar(
        select(models.ExpansionDismissal).where(
            models.ExpansionDismissal.user_id == viewer_id,
            models.ExpansionDismissal.anchor_kind == anchor_kind,
            models.ExpansionDismissal.anchor_id == anchor_id,
            models.ExpansionDismissal.suggested_model == folded,
        )
    )
    if row is None:
        raise ExpansionNotFound("That match isn't in your archive.")
    db.delete(row)
    db.commit()


def report(db: Session, viewer_id, *, anchor_model, suggested_model) -> None:
    """Judge one MATCH inaccurate. One row per user per pairing
    (a second report from the same user changes nothing — the
    threshold counts DISTINCT users)."""
    anchor_folded = norm_model(anchor_model)
    suggested_folded = norm_model(suggested_model)
    if not anchor_folded or not suggested_folded:
        raise ExpansionNotFound("That match can't be reported.")
    existing = db.scalar(
        select(models.ExpansionReport).where(
            models.ExpansionReport.user_id == viewer_id,
            models.ExpansionReport.anchor_model == anchor_folded,
            models.ExpansionReport.suggested_model == suggested_folded,
        )
    )
    if existing is not None:
        return
    db.add(
        models.ExpansionReport(
            user_id=viewer_id,
            anchor_model=anchor_folded,
            suggested_model=suggested_folded,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
