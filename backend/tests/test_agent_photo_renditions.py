"""Agent profile photos in small slots (prints-thumbnails
audit follow-through, 2026-11-10): an agent's photo renders
at 56px on company-page cards and 28px in the Home widget's
near-you strip, but the serializers handed out a presigned
URL to the FULL original (uploads run to 10 MB) — the same
disease the 3D print shelf had. The card serializers now
hand out the inventory pipeline's 128px rendition URL (the
ungated signed capability endpoint; the original is
preserved and still served to the owner's own profile
editor, where the photo itself is managed).

Proven against the real serializers + the real thumb
endpoint, storage faked at the storage object.
"""

import io
import uuid

import pytest
from PIL import Image

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.dealers import areas, models as dealer_models, portal

DEALER = "tool_dealer"
MECHANIC = "mechanic_technician"


class _FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, data, content_type):
        self.objects[key] = data
        return storage_module.StoredObject(
            key=key, size_bytes=len(data), content_type=content_type
        )

    def fetch(self, key):
        if key not in self.objects:
            raise storage_module.StorageError(f"missing: {key}")
        return self.objects[key]

    def head(self, key):
        if key not in self.objects:
            raise storage_module.StorageError(f"missing: {key}")
        return storage_module.StoredObject(
            key=key, size_bytes=len(self.objects[key]), content_type=""
        )

    def delete(self, key):
        self.objects.pop(key, None)

    def presigned_put_url(self, key, content_type, expires_in=900):
        return f"https://files.test/put/{key}"

    def presigned_get_url(self, key, expires_in=3600):
        return f"https://files.test/read/{key}"


@pytest.fixture()
def fake_storage(monkeypatch):
    fake = _FakeStorage()
    for name in (
        "put_bytes",
        "fetch",
        "head",
        "delete",
        "presigned_put_url",
        "presigned_get_url",
    ):
        monkeypatch.setattr(storage_module.storage, name, getattr(fake, name))
    return fake


def _make_user(db, account_number, email, account_types, name):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _jpeg(width=1200, height=900) -> bytes:
    image = Image.effect_noise((width, height), 100).convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


@pytest.fixture()
def agent_with_photo(db, fake_storage):
    agent = _make_user(
        db, "TV-D-000601", "andy@example.com", (DEALER,), "Andy Agent"
    )
    photo = _jpeg()
    key = f"{agent.id}/dealer-profile/me.jpg"
    fake_storage.objects[key] = photo
    profile = dealer_models.AgentProfile(
        user_id=agent.id,
        display_name="Andy the Tool Guy",
        service_area="Central Minnesota",
        photo_key=key,
        publicly_listed=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return agent, profile, key, photo


def test_public_agent_card_serves_rendition_not_original(
    client, agent_with_photo, fake_storage
):
    agent, profile, key, photo = agent_with_photo
    card = portal.public_agent_card(agent, profile, verified=False)
    url = card["photo_url"]
    assert url.startswith("/api/inventory/thumb/128?")
    # The rendition endpoint serves a 128px JPEG, not the
    # multi-hundred-KB original — and the original survives.
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    with Image.open(io.BytesIO(resp.content)) as image:
        assert max(image.size) == 128
    assert len(resp.content) < len(photo) // 10
    assert fake_storage.objects[key] == photo


def test_find_agent_card_serves_rendition(db, agent_with_photo):
    agent, profile, key, _photo = agent_with_photo
    viewer = _make_user(
        db, "TV-M-000601", "mike@example.com", (MECHANIC,), "Mike Mechanic"
    )
    card = areas.find_agent_card(db, agent, profile, public=True)
    assert card["photo_url"].startswith("/api/inventory/thumb/128?")
    signed_out_card = areas.find_agent_card(db, agent, profile, public=False)
    assert signed_out_card["photo_url"].startswith("/api/inventory/thumb/128?")


def test_owner_profile_view_keeps_the_original(agent_with_photo):
    agent, profile, key, _photo = agent_with_photo
    view = portal.serialize_profile(agent, profile)
    assert view["photo_url"] == f"https://files.test/read/{key}"
    assert view["has_photo"] is True


def test_no_photo_no_url(db):
    agent = _make_user(
        db, "TV-D-000602", "nophoto@example.com", (DEALER,), "No Photo"
    )
    profile = dealer_models.AgentProfile(
        user_id=agent.id, display_name="No Photo", photo_key=None
    )
    db.add(profile)
    db.commit()
    card = portal.public_agent_card(agent, profile, verified=False)
    assert "photo_url" not in card
    assert portal._photo_thumb_url(None) is None
