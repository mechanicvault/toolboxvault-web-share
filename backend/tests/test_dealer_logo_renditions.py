"""Dealer logos in small slots (image-delivery sweep
follow-on, 2026-11-10): a logo renders at ~100px in
directory tiles and smaller in Home widget strips, but
logo_url_for presigned the FULL harvested original — the
audit's stress case was a 5,820,798-byte transparent PNG.
Logos now serve a 320px rendition from
inventory.logo_thumbs: an alpha-preserving PNG when the
mark has real transparency (the JPEG photo pipeline would
flatten it onto black), the photo pipeline's JPEG when it
is opaque, and NO variant for SVG marks (already optimal,
and Pillow can't rasterize them). Originals are never
modified; anything undecodable keeps serving its original.

Proven against the real serializers + the real rendition
helper + the real backfill script, storage faked at the
storage object.
"""

import io
import uuid

import pytest
from PIL import Image

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.dealers import service as dealer_service
from app.modules.inventory import logo_thumbs
from app.scripts import backfill_logo_renditions

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

    def list_keys(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))

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
        "list_keys",
        "presigned_put_url",
        "presigned_get_url",
    ):
        monkeypatch.setattr(storage_module.storage, name, getattr(fake, name))
    return fake


def _make_user(db, account_number, email, name):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _transparent_png(width=1600, height=1200) -> bytes:
    """A harvested-logo worst case: detailed RGB under an
    alpha channel whose top band is fully transparent (a
    real logo lockup's empty border)."""
    base = Image.effect_noise((width, height), 65).convert("L")
    img = Image.merge(
        "RGBA",
        (
            base,
            base.point(lambda v: 255 - v),
            base.point(lambda v: (v // 2) + 60),
            Image.new("L", (width, height), 255),
        ),
    )
    alpha = img.getchannel("A")
    for x in range(width):
        for y in range(0, height // 10):
            alpha.putpixel((x, y), 0)
    img.putalpha(alpha)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _opaque_png(width=800, height=600) -> bytes:
    img = Image.new("RGBA", (width, height), (24, 60, 120, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _jpeg(width=1200, height=900) -> bytes:
    image = Image.effect_noise((width, height), 100).convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


def _company(db, name, logo_key):
    company = dealer_models.DealerCompany(
        name=name, is_directory=True, logo_key=logo_key
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def test_transparent_png_logo_serves_alpha_rendition(db, fake_storage):
    key = "platform/logos/stress.png"
    original = _transparent_png()
    fake_storage.objects[key] = original
    company = _company(db, "Stress Tools", key)

    view = dealer_service.serialize_company(company)

    vkey = f"{key}.thumb320.png"
    assert view["logo_url"] == f"https://files.test/read/{vkey}"
    # The rendition is a ≤320px PNG whose transparent pixels
    # SURVIVED — the whole reason logos can't ride the JPEG
    # photo pipeline (it flattens alpha onto black).
    data = fake_storage.objects[vkey]
    with Image.open(io.BytesIO(data)) as image:
        assert max(image.size) == 320
        assert image.mode == "RGBA"
        assert image.getpixel((10, 5))[3] == 0  # transparent band
        assert image.getpixel((160, 120))[3] == 255  # opaque body
    assert len(data) < len(original) // 5
    # The original is untouched, and a second read serves
    # the cached variant without regenerating it.
    assert fake_storage.objects[key] == original
    again = dealer_service.logo_url_for(key)
    assert again == view["logo_url"]
    assert fake_storage.objects[vkey] == data


def test_svg_logo_passes_through_untouched(db, fake_storage):
    key = "platform/logos/vector.svg"
    fake_storage.objects[key] = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        b'<rect width="10" height="10"/></svg>'
    )
    company = _company(db, "Vector Tools", key)

    view = dealer_service.serialize_company(company)

    # SVG is already the optimal bytes for a logo slot:
    # the URL is the original's, and no variant object was
    # written (Pillow can't rasterize SVG anyway).
    assert view["logo_url"] == f"https://files.test/read/{key}"
    assert set(fake_storage.objects) == {key}
    assert logo_thumbs.rendition(key, 320) is None


def test_opaque_jpeg_logo_uses_jpeg_rendition(db, fake_storage):
    key = "platform/logos/photo-brand.jpg"
    fake_storage.objects[key] = _jpeg()
    company = _company(db, "Photo Brand", key)

    view = dealer_service.serialize_company(company)

    vkey = f"{key}.thumb320.jpg"
    assert view["logo_url"] == f"https://files.test/read/{vkey}"
    with Image.open(io.BytesIO(fake_storage.objects[vkey])) as image:
        assert image.format == "JPEG"
        assert max(image.size) == 320


def test_opaque_png_logo_takes_jpeg_path(db, fake_storage):
    # Flavor is chosen by the DECODED pixels, not the file
    # extension: a PNG whose alpha is uniformly opaque is
    # an opaque source and gets the smaller JPEG rendition.
    key = "platform/logos/flat.png"
    fake_storage.objects[key] = _opaque_png()
    company = _company(db, "Flat Brand", key)

    view = dealer_service.serialize_company(company)

    assert view["logo_url"] == f"https://files.test/read/{key}.thumb320.jpg"
    assert f"{key}.thumb320.png" not in fake_storage.objects


def test_personal_edit_logo_serves_its_own_rendition(db, fake_storage):
    platform_key = "platform/logos/shared.png"
    fake_storage.objects[platform_key] = _transparent_png(800, 600)
    company = _company(db, "Shared Brand", platform_key)
    override_key = "some-user/logos/mine.png"
    fake_storage.objects[override_key] = _transparent_png(800, 600)
    viewer = _make_user(db, "TV-M-000701", "vic@example.com", "Vic Viewer")
    other = _make_user(db, "TV-M-000702", "ola@example.com", "Ola Other")
    db.add(
        dealer_models.DealerCompanyPersonalEdit(
            user_id=viewer.id, company_id=company.id, logo_key=override_key
        )
    )
    db.commit()

    mine = dealer_service.serialize_company_for_viewer(db, company, viewer.id)
    assert mine["logo_key"] == override_key
    assert mine["logo_url"] == (
        f"https://files.test/read/{override_key}.thumb320.png"
    )

    # Everyone else still gets the DIRECTORY logo's own
    # rendition — the effective-key rule cuts both ways.
    theirs = dealer_service.serialize_company_for_viewer(db, company, other.id)
    assert theirs["logo_url"] == (
        f"https://files.test/read/{platform_key}.thumb320.png"
    )
    raw = dealer_service.serialize_company(company)
    assert raw["logo_url"] == theirs["logo_url"]


def test_personal_logo_map_batch_semantics(db, fake_storage):
    # The near-you read mints one logo URL per row from this
    # map: overrides resolve per viewer, a CLEARED logo maps
    # to None (a real override, not a fallback), companies
    # without an override are absent (caller uses the
    # directory key), and string ids are accepted.
    company = _company(db, "Mapped Brand", "platform/logos/m.png")
    cleared = _company(db, "Cleared Brand", "platform/logos/c.png")
    plain = _company(db, "Plain Brand", "platform/logos/p.png")
    viewer = _make_user(db, "TV-M-000703", "map@example.com", "Map Viewer")
    db.add_all(
        [
            dealer_models.DealerCompanyPersonalEdit(
                user_id=viewer.id,
                company_id=company.id,
                logo_key="mine/logo.png",
            ),
            dealer_models.DealerCompanyPersonalEdit(
                user_id=viewer.id, company_id=cleared.id, logo_key=""
            ),
        ]
    )
    db.commit()

    result = dealer_service.personal_logo_map(
        db, viewer.id, [str(company.id), cleared.id, plain.id]
    )
    assert result == {company.id: "mine/logo.png", cleared.id: None}
    assert dealer_service.personal_logo_map(db, None, [company.id]) == {}


def test_missing_object_falls_back_to_original(db, fake_storage):
    # Nothing in storage behind the key (a harvest gap):
    # today's behavior exactly — the presigned original,
    # which the client swaps for the text tile on error.
    company = _company(db, "Ghost Brand", "platform/logos/ghost.png")
    view = dealer_service.serialize_company(company)
    assert view["logo_url"] == (
        "https://files.test/read/platform/logos/ghost.png"
    )
    assert dealer_service.logo_url_for(None) is None
    assert dealer_service.logo_url_for("") is None


def test_backfill_generates_skips_and_is_idempotent(fake_storage):
    alpha_key = "platform/logos/alpha.png"
    jpg_key = "platform/logos/photo.jpg"
    svg_key = "platform/logos/vector.svg"
    bad_key = "platform/logos/broken.png"
    done_key = "platform/logos/done.png"
    fake_storage.objects[alpha_key] = _transparent_png(800, 600)
    fake_storage.objects[jpg_key] = _jpeg()
    fake_storage.objects[svg_key] = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    fake_storage.objects[bad_key] = b"this is not an image at all"
    fake_storage.objects[done_key] = _opaque_png()
    # done.png already has its rendition cached.
    assert logo_thumbs.generate(done_key, 320) is not None
    objects_before = dict(fake_storage.objects)

    dry = backfill_logo_renditions.run(dry_run=True)
    assert dry == {
        "keys": 5,
        "generated": 0,
        "already_present": 1,
        # alpha + jpg + broken: a dry run reports what it
        # would ATTEMPT — broken.png's undecodability is
        # only discovered by the real run below.
        "would_generate": 3,
        "skipped_svg": 1,
        "failed": 0,
    }
    assert fake_storage.objects == objects_before  # dry run writes nothing

    real = backfill_logo_renditions.run()
    assert real["generated"] == 2
    assert real["already_present"] == 1
    assert real["skipped_svg"] == 1
    assert real["failed"] == 1  # broken.png — reported, left on its original
    assert f"{alpha_key}.thumb320.png" in fake_storage.objects
    assert f"{jpg_key}.thumb320.jpg" in fake_storage.objects
    assert fake_storage.objects[bad_key] == b"this is not an image at all"

    again = backfill_logo_renditions.run()
    assert again["generated"] == 0
    assert again["already_present"] == 3
    assert again["failed"] == 1
