"""Custom-field owner scoping (audit C4): definitions are per-user.

Behavioral tests run on SQLite with the real engine functions. The delete
path's scrub was originally a Postgres JSONB UPDATE verified at the SQL
level; the audit-trail build (2026-10-19) rewrote it as an ORM walk so
each value removal lands in the owner's change journal — the guarantee
under test is unchanged (the scrub is owner-scoped, exactly what C4
violated) and is now verified behaviorally against real rows.
"""

import uuid

import pytest

from app.modules.inventory import custom_fields, models, schemas


def _payload(name="vin", label="VIN", field_type="text", required=False, options=None):
    return schemas.FieldDefinitionCreate(
        name=name,
        label=label,
        field_type=field_type,
        required=required,
        options=options or [],
    )


def test_list_definitions_is_owner_scoped(db, user_a, user_b):
    custom_fields.create_definition(db, user_a.id, _payload())
    assert [d.name for d in custom_fields.list_definitions(db, user_a.id, "tool")] == ["vin"]
    assert custom_fields.list_definitions(db, user_b.id, "tool") == []


def test_get_definition_hides_other_users_definitions(db, user_a, user_b):
    definition = custom_fields.create_definition(db, user_a.id, _payload())
    assert custom_fields.get_definition(db, user_a.id, definition.id) is not None
    assert custom_fields.get_definition(db, user_b.id, definition.id) is None


def test_update_by_non_owner_is_a_no_op(db, user_a, user_b):
    definition = custom_fields.create_definition(db, user_a.id, _payload())
    result = custom_fields.update_definition(
        db, user_b.id, definition.id, schemas.FieldDefinitionUpdate(label="Hacked")
    )
    assert result is None
    assert custom_fields.get_definition(db, user_a.id, definition.id).label == "VIN"


def test_required_fields_do_not_leak_across_users(db, user_a, user_b):
    custom_fields.create_definition(db, user_a.id, _payload(required=True))
    # User B has no definitions: A's required field must not block B.
    assert custom_fields.validate_custom_data(db, user_b.id, {}) == {}
    # ...but it blocks A.
    with pytest.raises(custom_fields.FieldValidationError):
        custom_fields.validate_custom_data(db, user_a.id, {})


def test_user_cannot_reference_another_users_definition(db, user_a, user_b):
    definition = custom_fields.create_definition(db, user_a.id, _payload())
    with pytest.raises(custom_fields.FieldValidationError):
        custom_fields.validate_custom_data(db, user_b.id, {str(definition.id): "1HGBH48JXMN109186"})
    # By name either: the slug namespace is per-user.
    with pytest.raises(custom_fields.FieldValidationError):
        custom_fields.validate_custom_data(db, user_b.id, {"vin": "1HGBH48JXMN109186"})


def test_value_type_validation(db, user_a):
    custom_fields.create_definition(
        db, user_a.id, _payload(name="mileage", label="Mileage", field_type="number")
    )
    custom_fields.create_definition(
        db,
        user_a.id,
        _payload(
            name="cond",
            label="Condition",
            field_type="dropdown",
            options=["New", "Used"],
        ),
    )
    ok = custom_fields.validate_custom_data(
        db, user_a.id, {"mileage": 12000, "cond": "Used"}
    )
    assert set(ok.values()) == {12000, "Used"}
    with pytest.raises(custom_fields.FieldValidationError):
        custom_fields.validate_custom_data(db, user_a.id, {"mileage": "lots"})
    with pytest.raises(custom_fields.FieldValidationError):
        custom_fields.validate_custom_data(db, user_a.id, {"cond": "Mint"})


def test_delete_by_non_owner_returns_false_and_keeps_definition(db, user_a, user_b):
    definition = custom_fields.create_definition(db, user_a.id, _payload())
    assert custom_fields.delete_definition(db, user_b.id, definition.id) is False
    assert custom_fields.get_definition(db, user_a.id, definition.id) is not None


def test_delete_scrub_update_is_owner_scoped(db, user_a, user_b):
    """The C4 regression, verified behaviorally: deleting A's
    definition strips A's values from A's records — and touches
    NOTHING of B's, even a B record that (pathologically) carries
    A's definition key. The scrub walks tools AND batteries (a
    'both' definition's values can live in either) AND parts."""
    definition = custom_fields.create_definition(db, user_a.id, _payload())
    key = str(definition.id)
    mine_tool = models.Tool(
        owner_id=user_a.id, name="Mine", custom_data={key: "1HG"}
    )
    mine_batt = models.Battery(
        owner_id=user_a.id, name="MineBatt", custom_data={key: "1HG"}
    )
    theirs_tool = models.Tool(
        owner_id=user_b.id, name="Theirs", custom_data={key: "JT4"}
    )
    db.add_all([mine_tool, mine_batt, theirs_tool])
    db.commit()

    assert custom_fields.delete_definition(db, user_a.id, definition.id) is True

    db.refresh(mine_tool)
    db.refresh(mine_batt)
    db.refresh(theirs_tool)
    assert mine_tool.custom_data == {}
    assert mine_batt.custom_data == {}
    # The other user's record is byte-identical — the whole point.
    assert theirs_tool.custom_data == {key: "JT4"}
    assert custom_fields.get_definition(db, user_a.id, definition.id) is None
