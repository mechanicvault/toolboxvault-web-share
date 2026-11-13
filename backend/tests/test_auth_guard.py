"""Auth guard behavior: who gets in, who gets a 401, and what shape the
rest of the codebase receives (the CurrentUser principal, audit I10).
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.deps import CurrentUser, get_current_user, get_current_user_id
from app.core.security import create_access_token, decode_access_token
from app.modules.core import models as core_models


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_missing_credentials_are_401():
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(None)
    assert exc.value.status_code == 401


def test_garbage_token_is_401():
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(_bearer("not-a-token"))
    assert exc.value.status_code == 401


def test_wrong_secret_token_is_401():
    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "some-other-secret",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(_bearer(forged))
    assert exc.value.status_code == 401


def test_expired_token_is_401():
    expired = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert decode_access_token(expired) is None
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(_bearer(expired))
    assert exc.value.status_code == 401


def test_valid_token_round_trips_the_user_id():
    user_id = str(uuid.uuid4())
    assert get_current_user_id(_bearer(create_access_token(user_id))) == user_id


def test_get_current_user_returns_principal_not_orm(db, user_a):
    principal = get_current_user(user_id=str(user_a.id), db=db)
    assert isinstance(principal, CurrentUser)
    assert not isinstance(principal, core_models.User)
    assert principal.id == user_a.id
    assert principal.account_number == user_a.account_number
    assert principal.email == user_a.email
    assert principal.email_verified is False


def test_get_current_user_unknown_id_is_401(db):
    with pytest.raises(HTTPException) as exc:
        get_current_user(user_id=str(uuid.uuid4()), db=db)
    assert exc.value.status_code == 401
