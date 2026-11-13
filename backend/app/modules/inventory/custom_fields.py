"""Custom-fields engine (inventory module).

Field definitions are the schema; records' custom_data holds the values
keyed by definition id. Definitions are per-user: every function here
takes the owning user's id and scopes to it, so one user can never see,
mutate, or delete another user's definitions (or, via delete-scrubbing,
their values). Validation happens on every record create/update so bad
data can never enter through the API.

APPLIES-TO (the definition's `item_type`): 'tool' definitions apply to
tools only, 'battery' to batteries only, 'both' to either — one
definition can serve both record kinds (values live per-record, in
that record's own custom_data). 'tool' is the default everywhere, so
definitions written before batteries existed behave exactly as they
always did.

'part' joined the axis with the Used Parts module (2026-10-19): a
'part' definition applies to used parts only, and NOTHING else
applies to parts — 'both' keeps its original tools+batteries meaning
(rather than silently sweeping parts in, which would let a required
'both' field start blocking part creation for existing owners).
Parts values live in parts.custom_data and validate through this
same engine with item_type='part'.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import models, schemas

FIELD_TYPES = ("text", "number", "date", "dropdown", "boolean")
ITEM_TYPES = ("tool", "battery", "both", "part")


class FieldValidationError(ValueError):
    """Raised when custom_data breaks a definition's rules. Routes -> 422."""


def _applies_to(item_type: str) -> tuple[str, ...]:
    """The stored item_type values that apply to records of a kind:
    the kind itself plus 'both' — except parts, which take ONLY
    'part' definitions ('both' means tools+batteries, see the module
    docstring)."""
    if item_type == "part":
        return ("part",)
    return (item_type, "both")


# -- definitions CRUD ----------------------------------------------------
def list_definitions(
    db: Session, owner_id: uuid.UUID, item_type: str = "tool"
) -> list[models.FieldDefinition]:
    """Definitions applying to `item_type` records ('tool' |
    'battery'), each kind's own plus the 'both' ones. The special
    value 'all' returns every definition the owner has (the
    Settings manager view)."""
    stmt = select(models.FieldDefinition).where(
        models.FieldDefinition.owner_id == owner_id
    )
    if item_type != "all":
        stmt = stmt.where(
            models.FieldDefinition.item_type.in_(_applies_to(item_type))
        )
    return list(
        db.scalars(
            stmt.order_by(
                models.FieldDefinition.sort_order, models.FieldDefinition.label
            )
        )
    )


def get_definition(
    db: Session, owner_id: uuid.UUID, definition_id: uuid.UUID
) -> models.FieldDefinition | None:
    return db.scalars(
        select(models.FieldDefinition).where(
            models.FieldDefinition.id == definition_id,
            models.FieldDefinition.owner_id == owner_id,
        )
    ).first()


def create_definition(
    db: Session, owner_id: uuid.UUID, payload: schemas.FieldDefinitionCreate
) -> models.FieldDefinition:
    _check_definition_payload(payload)
    definition = models.FieldDefinition(owner_id=owner_id, **payload.model_dump())
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


def update_definition(
    db: Session,
    owner_id: uuid.UUID,
    definition_id: uuid.UUID,
    payload: schemas.FieldDefinitionUpdate,
) -> models.FieldDefinition | None:
    definition = get_definition(db, owner_id, definition_id)
    if definition is None:
        return None
    _check_definition_payload(payload, partial=True)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(definition, key, value)
    db.commit()
    db.refresh(definition)
    return definition


def delete_definition(
    db: Session, owner_id: uuid.UUID, definition_id: uuid.UUID
) -> bool:
    """Delete one of the owner's definitions AND strip its key from that
    owner's records' custom_data — tools AND batteries, since a 'both'
    definition's values can live in either (never anyone else's), so
    the invariant 'every custom_data key maps to a definition' holds
    per user."""
    definition = get_definition(db, owner_id, definition_id)
    if definition is None:
        return False
    records: list = [models.Tool, models.Battery]
    # Used Parts (2026-10-19): a 'part' definition's values live on
    # part records, which inventory must not hard-depend on — the
    # parts models are imported lazily (the same discipline as the
    # dealer-tag validation), and a missing parts module simply
    # means there is nothing to scrub.
    try:
        from app.modules.parts import models as parts_models

        records.append(parts_models.Part)
    except ImportError:
        pass
    # The scrub is an ORM loop, not a bulk JSONB UPDATE (audit
    # trail, 2026-10-19): each record's value removal lands in the
    # owner's change journal, so restoring a deleted definition
    # brings its values back with it. Owner-scoped and rare — the
    # row walk is cheap at any realistic vault size.
    key = str(definition_id)
    for record in records:
        for row in db.scalars(
            select(record).where(record.owner_id == owner_id)
        ):
            data = row.custom_data or {}
            if key in data:
                row.custom_data = {
                    k: v for k, v in data.items() if k != key
                }
    db.delete(definition)
    db.commit()
    return True


def _check_definition_payload(
    payload: schemas.FieldDefinitionCreate | schemas.FieldDefinitionUpdate,
    partial: bool = False,
) -> None:
    data = payload.model_dump(exclude_unset=True) if partial else payload.model_dump()
    if "item_type" in data and data["item_type"] not in ITEM_TYPES:
        raise FieldValidationError(
            f"item_type must be one of {ITEM_TYPES}, got '{data['item_type']}'"
        )
    if "field_type" in data and data["field_type"] not in FIELD_TYPES:
        raise FieldValidationError(
            f"field_type must be one of {FIELD_TYPES}, got '{data['field_type']}'"
        )
    field_type = data.get("field_type", "text")
    options = data.get("options", [])
    if field_type == "dropdown" and not options:
        raise FieldValidationError("dropdown fields need at least one option")
    if field_type != "dropdown" and options:
        raise FieldValidationError("only dropdown fields use options")


# -- value validation ----------------------------------------------------
def validate_custom_data(
    db: Session, owner_id: uuid.UUID, custom_data: dict, item_type: str = "tool"
) -> dict:
    """Validate and normalize custom_data against the owner's definitions
    for records of `item_type` (their own definitions plus 'both').

    Accepts definition ids OR name slugs as keys; returns values keyed by
    definition id with types checked. Raises FieldValidationError on any
    problem (unknown key, wrong type, missing required field). Required
    fields are enforced per-owner: only the owner's own definitions apply.
    """
    if not isinstance(custom_data, dict):
        raise FieldValidationError("custom_data must be an object")
    definitions = list_definitions(db, owner_id, item_type)
    by_id = {str(d.id): d for d in definitions}
    by_name = {d.name: d for d in definitions}

    normalized: dict[str, object] = {}
    for raw_key, value in custom_data.items():
        definition = by_id.get(str(raw_key)) or by_name.get(str(raw_key))
        if definition is None:
            raise FieldValidationError(f"Unknown custom field: '{raw_key}'")
        normalized[str(definition.id)] = _coerce_value(definition, value)

    missing = [
        d.label
        for d in definitions
        if d.required and str(d.id) not in normalized
    ]
    if missing:
        raise FieldValidationError(
            f"Missing required custom fields: {', '.join(missing)}"
        )
    return normalized


def _coerce_value(
    definition: models.FieldDefinition, value: object
) -> object:
    label = definition.label
    if definition.field_type == "text":
        if not isinstance(value, str):
            raise FieldValidationError(f"'{label}' must be text")
        return value
    if definition.field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FieldValidationError(f"'{label}' must be a number")
        return value
    if definition.field_type == "boolean":
        if not isinstance(value, bool):
            raise FieldValidationError(f"'{label}' must be true or false")
        return value
    if definition.field_type == "date":
        if not isinstance(value, str):
            raise FieldValidationError(f"'{label}' must be a YYYY-MM-DD date")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise FieldValidationError(f"'{label}' must be a YYYY-MM-DD date") from None
        return value
    if definition.field_type == "dropdown":
        if value not in definition.options:
            raise FieldValidationError(
                f"'{label}' must be one of: {', '.join(map(str, definition.options))}"
            )
        return value
    raise FieldValidationError(f"Unknown field type on '{label}'")
