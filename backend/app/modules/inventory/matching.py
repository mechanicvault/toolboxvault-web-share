"""Importer smart value matching (2026-10-19, Ryan's spec).

Ryan's rule: an import must MATCH values interactively. His
dealer column may say "matco" while the site holds "Matco
Incorporated" — the importer ASKS ("Is your dealer 'matco' the
same as 'Matco Incorporated'?"), applies the answer across every
row carrying the value, and REMEMBERS it for the next import. No
one re-points a thousand rows by hand.

Three tiers, per distinct incoming value of a matchable field
(dealer, brand, category, tags, location):

  1. SILENT — a learned answer, or normalized equality with an
     existing value (casefold, punctuation folding, company-suffix
     folding: Inc / Incorporated / Corp / LLC / Co ...). Silent
     never means invisible: every applied mapping is LISTED in the
     resolve plan and again in the import summary, with counts.
  2. ASK — fuzzy candidates (edit distance + token overlap).
     Similarity NEVER auto-merges: Mac Tools and Matco Tools are
     different companies, and a score can't tell them apart — the
     user can. Candidates are offered, never chosen for them.
  3. ASK — no candidates at all: create the value as new, or
     leave it unset. (For dealers, "create" mints a PRIVATE
     company — allowed here precisely because the user chose it;
     the importer still never creates anything silently.)

Dry run and confirm share resolve_effective(), so a check can
never disagree with the import that follows it — the importer's
founding invariant, extended to resolutions. Any value still
unanswered REFUSES the run (422) rather than guessing.
"""

import re
import uuid
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import models, service

# The importer field keys this engine reconciles. `dealer_name` is
# the mapping key the importer uses for the dealer column.
MATCHABLE_FIELDS = ("dealer_name", "brand", "category", "tags", "location")

# Company suffixes folded away during normalization, repeatedly —
# "Matco Tools, Incorporated" and "matco tools" are the same name.
_COMPANY_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "llc", "ltd",
    "limited", "co", "company", "llp", "lp",
}

# A fuzzy candidate must clear this bar to be OFFERED. The bar only
# decides what gets offered — an offer is a question, never a merge.
_CANDIDATE_FLOOR = 0.4
_CANDIDATE_CAP = 5


class UnresolvedValuesError(ValueError):
    """Ask-tier values have no answer yet. Routes turn this into a
    422 — the run refuses rather than guessing."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        labels = [
            f"{_field_noun(e['field'])} '{e['raw']}'" for e in entries[:6]
        ]
        more = (
            f" and {len(entries) - 6} more"
            if len(entries) > 6
            else ""
        )
        super().__init__(
            "Some values still need your answer in the Resolve "
            "matches step: " + ", ".join(labels) + more + "."
        )


class ResolutionValidationError(ValueError):
    """A submitted answer points somewhere it can't (a company the
    user can't see, a location node that isn't theirs...). 422."""


def _field_noun(field: str) -> str:
    return {
        "dealer_name": "dealer",
        "brand": "brand",
        "category": "category",
        "tags": "tag",
        "location": "location",
    }.get(field, field)


# ---------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------


def normalize_match_value(raw: str) -> str:
    """The matching key for a value: casefolded, punctuation folded
    to spaces, a leading "the" dropped, and trailing company
    suffixes folded away (repeatedly — "Tools Inc LLC" loses both).
    Two values with the same key are the same value, spelled
    differently."""
    text = (raw or "").casefold().strip()
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    tokens = text.split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    while tokens and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _fuzzy_score(a: str, b: str) -> float:
    """How plausible a candidate is: the better of edit-distance
    ratio and token overlap, with a substring bonus (a bare 'matco'
    against 'matco tools'). Only ever ranks OFFERS."""
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    union = tokens_a | tokens_b
    jaccard = len(tokens_a & tokens_b) / len(union) if union else 0.0
    score = max(ratio, jaccard)
    if len(a) >= 3 and (a in b or b in a):
        score = max(score, 0.75)
    return score


# ---------------------------------------------------------------------
# The existing-value universes (all owner-scoped)
# ---------------------------------------------------------------------


def _universe(db: Session, owner_id: uuid.UUID, field: str) -> list[dict]:
    """The values a field can resolve TO. A target:
    {target_id, target_value, label, match_keys}. Dealer targets
    point at companies, location targets at tree nodes; brand /
    category / tag targets carry the canonical string itself."""
    targets: list[dict] = []
    if field == "dealer_name":
        from app.modules.dealers import service as dealers_service

        for company in dealers_service.list_companies(db, owner_id):
            targets.append(
                {
                    "target_id": str(company.id),
                    "target_value": None,
                    "label": company.name,
                    "match_keys": {normalize_match_value(company.name)},
                }
            )
    elif field in ("brand", "category"):
        for value in service.field_suggestions(db, owner_id, field):
            targets.append(
                {
                    "target_id": None,
                    "target_value": value,
                    "label": value,
                    "match_keys": {normalize_match_value(value)},
                }
            )
    elif field == "tags":
        for value in service.field_suggestions(db, owner_id, "tag"):
            targets.append(
                {
                    "target_id": None,
                    "target_value": value,
                    "label": value,
                    "match_keys": {normalize_match_value(value)},
                }
            )
    elif field == "location":
        nodes = service.owned_locations(db, owner_id)
        for node in nodes:
            path = service.location_path(nodes, node)
            targets.append(
                {
                    "target_id": str(node.id),
                    "target_value": None,
                    "label": path,
                    "match_keys": {
                        normalize_match_value(node.name),
                        normalize_match_value(path),
                    },
                }
            )
    return targets


def _public_target(target: dict) -> dict:
    return {
        "target_id": target["target_id"],
        "target_value": target["target_value"],
        "label": target["label"],
    }


def _candidates(raw_norm: str, targets: list[dict]) -> list[dict]:
    """Ranked fuzzy offers for one unanswered value — every target
    that clears the floor, best first. BOTH lookalikes appear when
    both are plausible; that's the point of asking."""
    scored: list[tuple[float, dict]] = []
    for target in targets:
        score = max(
            (_fuzzy_score(raw_norm, key) for key in target["match_keys"]),
            default=0.0,
        )
        if score >= _CANDIDATE_FLOOR:
            scored.append((score, target))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["label"].lower()))
    return [
        {**_public_target(target), "score": round(score, 3)}
        for score, target in scored[:_CANDIDATE_CAP]
    ]


# ---------------------------------------------------------------------
# Distinct incoming values
# ---------------------------------------------------------------------


def distinct_values(
    rows: list[list[str]], mapping: dict[int, str], field: str
) -> dict[str, int]:
    """{raw value: row count} for one matchable field, in
    first-seen order. Tags split per cell (one cell can carry
    several distinct tags)."""
    column = next((i for i, key in mapping.items() if key == field), None)
    if column is None:
        return {}
    counts: dict[str, int] = {}
    if field == "tags":
        from app.modules.inventory.importer import _split_multi

        for row in rows:
            cell = row[column] if column < len(row) else ""
            for tag in _split_multi(cell):
                counts[tag] = counts.get(tag, 0) + 1
        return counts
    for row in rows:
        raw = (row[column] if column < len(row) else "").strip()
        if raw:
            counts[raw] = counts.get(raw, 0) + 1
    return counts


# ---------------------------------------------------------------------
# Learned answers
# ---------------------------------------------------------------------


def _learned_index(
    db: Session, owner_id: uuid.UUID
) -> dict[tuple[str, str], models.ImportValueMapping]:
    rows = db.scalars(
        select(models.ImportValueMapping).where(
            models.ImportValueMapping.owner_id == owner_id
        )
    )
    return {(row.field, row.normalized): row for row in rows}


def _learned_resolution(
    learned: models.ImportValueMapping, targets: list[dict]
) -> dict | None:
    """The resolution a learned row pre-answers, or None when the
    row has gone stale (its target was deleted) — stale means the
    question gets asked again, never guessed at."""
    if learned.action in ("create", "unset"):
        return {
            "action": learned.action,
            "target_id": None,
            "target_value": learned.target_value,
            "parent_id": None,
            "source": "learned",
        }
    # action == "map": the target must still exist.
    if learned.target_id is not None:
        target_ids = {t["target_id"] for t in targets}
        if str(learned.target_id) not in target_ids:
            return None
    return {
        "action": "map",
        "target_id": (
            str(learned.target_id) if learned.target_id is not None else None
        ),
        "target_value": learned.target_value,
        "parent_id": None,
        "source": "learned",
    }


def _learned_target_label(
    db: Session, owner_id: uuid.UUID, learned: models.ImportValueMapping
) -> str:
    if learned.action == "unset":
        return ""
    if learned.action == "create":
        return learned.raw_value
    if learned.field == "dealer_name" and learned.target_id is not None:
        from app.modules.dealers import models as dealer_models

        company = db.get(dealer_models.DealerCompany, learned.target_id)
        return company.name if company is not None else "(deleted company)"
    if learned.field == "location" and learned.target_id is not None:
        node = service.get_location_node(db, owner_id, learned.target_id)
        if node is None:
            return "(deleted location)"
        return service.location_path(
            service.owned_locations(db, owner_id), node
        )
    return learned.target_value or ""


def list_learned(db: Session, owner_id: uuid.UUID) -> list[dict]:
    """The Settings surface: every remembered answer, with a
    human-readable outcome, oldest answers first."""
    rows = list(
        db.scalars(
            select(models.ImportValueMapping)
            .where(models.ImportValueMapping.owner_id == owner_id)
            .order_by(
                models.ImportValueMapping.field,
                models.ImportValueMapping.raw_value,
            )
        )
    )
    return [
        {
            "id": row.id,
            "field": row.field,
            "raw_value": row.raw_value,
            "action": row.action,
            "target_id": row.target_id,
            "target_value": row.target_value,
            "target_label": _learned_target_label(db, owner_id, row),
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def delete_learned(
    db: Session, owner_id: uuid.UUID, mapping_id: uuid.UUID
) -> bool:
    """Forget one remembered answer (owner-scoped; a foreign id is
    simply 'not found'). The next import carrying that value asks
    again."""
    row = db.get(models.ImportValueMapping, mapping_id)
    if row is None or row.owner_id != owner_id:
        return False
    db.delete(row)
    db.commit()
    return True


def learn_decisions(
    db: Session,
    owner_id: uuid.UUID,
    decisions: dict,
    effective: dict,
) -> None:
    """Persist the answers the user EXPLICITLY gave this import
    (ask-tier answers and overrides of automatic ones), resolved to
    their final form — a dealer the user chose to create is learned
    as a mapping to the company that was created, so the next
    import lands on it directly. Called only after a successful
    confirm: an abandoned import teaches nothing."""
    for field, per_value in (decisions or {}).items():
        if field not in MATCHABLE_FIELDS:
            continue
        for raw in per_value:
            final = (effective.get(field) or {}).get(raw)
            if final is None:
                continue
            normalized = normalize_match_value(raw)
            row = db.scalar(
                select(models.ImportValueMapping).where(
                    models.ImportValueMapping.owner_id == owner_id,
                    models.ImportValueMapping.field == field,
                    models.ImportValueMapping.normalized == normalized,
                )
            )
            if row is None:
                row = models.ImportValueMapping(
                    owner_id=owner_id,
                    field=field,
                    raw_value=raw,
                    normalized=normalized,
                    action=final["action"],
                )
                db.add(row)
            row.action = final["action"]
            row.target_id = (
                uuid.UUID(final["target_id"])
                if final.get("target_id")
                else None
            )
            row.target_value = final.get("target_value")
    db.commit()


# ---------------------------------------------------------------------
# The resolve plan (what the Resolve step shows)
# ---------------------------------------------------------------------


def build_plan(
    db: Session, owner_id: uuid.UUID, rows: list[list[str]], mapping: dict[int, str]
) -> dict:
    """The resolve plan for one import session: per matchable
    field, every distinct incoming value as auto (exact / learned,
    with its resolution) or ask (with ranked candidates), plus the
    full option list per field for 'pick a different one'."""
    learned = _learned_index(db, owner_id)
    entries: list[dict] = []
    options: dict[str, list[dict]] = {}
    for field in MATCHABLE_FIELDS:
        if field not in mapping.values():
            continue
        targets = _universe(db, owner_id, field)
        options[field] = [_public_target(t) for t in targets]
        by_key: dict[str, dict] = {}
        for target in targets:
            for key in target["match_keys"]:
                by_key.setdefault(key, target)
        for raw, count in distinct_values(rows, mapping, field).items():
            normalized = normalize_match_value(raw)
            entry = {
                "field": field,
                "raw": raw,
                "rows": count,
                "status": "ask",
                "source": None,
                "resolution": None,
                "candidates": [],
            }
            learned_row = learned.get((field, normalized))
            if learned_row is not None:
                resolution = _learned_resolution(learned_row, targets)
                if resolution is not None:
                    entry.update(
                        status="auto", source="learned", resolution=resolution
                    )
                    entries.append(entry)
                    continue
            target = by_key.get(normalized)
            if target is not None:
                entry.update(
                    status="auto",
                    source="exact",
                    resolution={
                        "action": "map",
                        "target_id": target["target_id"],
                        "target_value": target["target_value"],
                        "parent_id": None,
                        "source": "exact",
                    },
                )
                entries.append(entry)
                continue
            entry["candidates"] = _candidates(normalized, targets)
            entries.append(entry)
    unresolved = sum(1 for e in entries if e["status"] == "ask")
    return {"entries": entries, "options": options, "unresolved": unresolved}


# ---------------------------------------------------------------------
# Decisions -> the effective resolutions a run applies
# ---------------------------------------------------------------------


def _validate_decision(
    field: str, raw: str, decision: dict, targets: list[dict]
) -> dict:
    """One user answer, checked against the field's universe.
    Returns the internal resolution (source 'decision')."""
    action = decision.get("action")
    noun = _field_noun(field)
    if action not in ("map", "create", "unset"):
        raise ResolutionValidationError(
            f"That answer for {noun} '{raw}' isn't one of the choices."
        )
    if action == "map":
        if field in ("dealer_name", "location"):
            target_id = decision.get("target_id")
            valid = {t["target_id"] for t in targets}
            if not target_id or str(target_id) not in valid:
                raise ResolutionValidationError(
                    f"'{raw}' can't be matched to that {noun} — it "
                    "isn't one of your choices anymore. Review the "
                    "matches and pick again."
                )
            target = next(
                t for t in targets if t["target_id"] == str(target_id)
            )
            return {
                "action": "map",
                "target_id": target["target_id"],
                "target_value": None,
                "parent_id": None,
                "source": "decision",
            }
        target_value = decision.get("target_value")
        valid_values = {t["target_value"] for t in targets}
        if not target_value or target_value not in valid_values:
            raise ResolutionValidationError(
                f"'{raw}' can't be matched to that {noun} — it "
                "isn't one of your existing values anymore. Review "
                "the matches and pick again."
            )
        return {
            "action": "map",
            "target_id": None,
            "target_value": target_value,
            "parent_id": None,
            "source": "decision",
        }
    if action == "create":
        parent_id = decision.get("parent_id")
        if field == "location" and parent_id:
            valid_parents = {t["target_id"] for t in targets}
            if str(parent_id) not in valid_parents:
                raise ResolutionValidationError(
                    f"'{raw}' can't be created under that location — "
                    "it isn't in your location tree anymore."
                )
        return {
            "action": "create",
            "target_id": None,
            "target_value": None,
            "parent_id": str(parent_id) if parent_id else None,
            "source": "decision",
        }
    return {
        "action": "unset",
        "target_id": None,
        "target_value": None,
        "parent_id": None,
        "source": "decision",
    }


def _applied_summary(
    plan_entries: list[dict], effective: dict, universes: dict[str, list[dict]]
) -> list[dict]:
    """The listing every run reports: each mapping applied, with
    its row count and where the answer came from — silent matches
    included (nothing invisible)."""
    labels: dict[tuple[str, str], str] = {}
    for field, targets in universes.items():
        for target in targets:
            key = target["target_id"] or target["target_value"] or ""
            labels[(field, key)] = target["label"]
    summary: list[dict] = []
    for entry in plan_entries:
        resolution = effective[entry["field"]][entry["raw"]]
        if resolution["action"] == "map":
            key = resolution["target_id"] or resolution["target_value"] or ""
            target_label = labels.get(
                (entry["field"], key), resolution["target_value"] or ""
            )
        elif resolution["action"] == "create":
            target_label = entry["raw"]
        else:
            target_label = ""
        summary.append(
            {
                "field": entry["field"],
                "raw": entry["raw"],
                "rows": entry["rows"],
                "action": resolution["action"],
                "target_label": target_label,
                "source": resolution.get("source") or entry["source"] or "decision",
            }
        )
    return summary


def resolve_effective(
    db: Session,
    owner_id: uuid.UUID,
    rows: list[list[str]],
    mapping: dict[int, str],
    decisions: dict | None,
) -> tuple[dict, list[dict]]:
    """Merge the plan with the user's answers into the resolutions
    a dry run / confirm applies. Raises UnresolvedValuesError when
    any ask-tier value is still unanswered — the run refuses
    rather than guessing. Returns (effective, applied_summary):
    effective is {field: {raw: resolution}}."""
    plan = build_plan(db, owner_id, rows, mapping)
    decisions = decisions or {}
    universes = {
        field: _universe(db, owner_id, field)
        for field in MATCHABLE_FIELDS
        if field in mapping.values()
    }
    effective: dict[str, dict[str, dict]] = {}
    unresolved: list[dict] = []
    for entry in plan["entries"]:
        field, raw = entry["field"], entry["raw"]
        decision = (decisions.get(field) or {}).get(raw)
        if decision is not None:
            resolution = _validate_decision(
                field, raw, decision, universes[field]
            )
        elif entry["status"] == "auto":
            resolution = entry["resolution"]
        else:
            unresolved.append(entry)
            continue
        effective.setdefault(field, {})[raw] = resolution
    if unresolved:
        raise UnresolvedValuesError(unresolved)
    summary = _applied_summary(plan["entries"], effective, universes)
    return effective, summary


# ---------------------------------------------------------------------
# Confirm-time creation (the user's explicit "create" answers)
# ---------------------------------------------------------------------


def materialize_creates(
    db: Session, owner_id: uuid.UUID, effective: dict
) -> None:
    """Turn explicit 'create' answers into real rows BEFORE the
    transform runs, rewriting those resolutions to plain maps at
    the created rows — so the transform, and everything after it,
    only ever deals in targets that exist.

    Dealers become PRIVATE companies (the user's own, never
    directory rows). Locations become tree nodes: a value with
    slashes ("Shop / Drawer 2") creates the chain; a plain value
    lands under the parent the user picked (or at the top)."""
    for raw, resolution in (effective.get("dealer_name") or {}).items():
        if resolution["action"] != "create":
            continue
        from app.modules.dealers import service as dealers_service

        company = dealers_service.create_company(
            db, owner_id=owner_id, data={"name": raw.strip()}
        )
        resolution["action"] = "map"
        resolution["target_id"] = str(company.id)
        resolution["created"] = True
    for raw, resolution in (effective.get("location") or {}).items():
        if resolution["action"] != "create":
            continue
        parent_id = (
            uuid.UUID(resolution["parent_id"])
            if resolution.get("parent_id")
            else None
        )
        nodes = service.owned_locations(db, owner_id)
        current_parent = parent_id
        node = None
        segments = [s.strip() for s in raw.split("/") if s.strip()]
        for segment in segments:
            node = next(
                (
                    n
                    for n in nodes
                    if n.parent_id == current_parent
                    and n.name.casefold() == segment.casefold()
                ),
                None,
            )
            if node is None:
                node = service.create_location_node(
                    db, owner_id, name=segment, parent_id=current_parent
                )
                nodes = service.owned_locations(db, owner_id)
            current_parent = node.id
        if node is not None:
            resolution["action"] = "map"
            resolution["target_id"] = str(node.id)
            resolution["created"] = True
