"""Password policy (audit I1): minimum length enforced by the signup
schema — every password-setting path inherits it from here.
"""

import pytest
from pydantic import ValidationError

from app.modules.core import schemas


def _signup(password: str) -> schemas.SignupRequest:
    return schemas.SignupRequest(
        email="new@example.com",
        name="New User",
        password=password,
        account_types=["mechanic_technician"],
        country="US",
        currency="USD",
        locale="en",
    )


def test_password_below_minimum_is_rejected():
    with pytest.raises(ValidationError):
        _signup("x" * (schemas.PASSWORD_MIN_LENGTH - 1))


def test_password_at_minimum_is_accepted():
    assert _signup("x" * schemas.PASSWORD_MIN_LENGTH).password


def test_minimum_is_six_characters():
    # Owner policy decision 2026-10-17: 6 characters (was the blueprint's
    # 10). Changing it is a product decision, not a refactor.
    assert schemas.PASSWORD_MIN_LENGTH == 6


def test_five_rejected_and_six_accepted():
    # The policy boundary stated outright: 5 chars never, 6 chars fine.
    with pytest.raises(ValidationError):
        _signup("x" * 5)
    assert _signup("x" * 6).password == "x" * 6
