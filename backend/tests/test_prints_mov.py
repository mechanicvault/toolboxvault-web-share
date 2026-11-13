"""3D print video .mov bug lane (owner report 2026-11-09):
a member's 31 MB iPhone .mov was refused by the site's EDGE
(nginx client_max_body_size 20m) before the API ever saw it —
and had it fit, the pipeline would have stored the HEVC bytes
raw, a file most browsers cannot play.

These tests pin the halves that live in this repo:
- the codec reader (which track is the video, what codec it
  carries) on synthetic containers;
- the storage processing: a WebM and an H.264 MP4 land as-is;
  a .mov / HEVC MP4 is converted to H.264 MP4 on upload (real
  ffmpeg encodes, when ffmpeg is on hand), the recorded
  duration still the ORIGINAL upload's measured length;
- with no converter available, a .mov is refused in honest
  words instead of being stored unplayable;
- the nginx template's body ceiling covers the app's own
  100 MB upload cap, so the edge can never again silently
  undercut it (the production half of the incident).
"""

import re
import shutil
import struct
import subprocess
import uuid
from pathlib import Path

import pytest

from app.core import storage as storage_module
from app.modules.core import models as core_models
from app.modules.prints import service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None, reason="ffmpeg not installed in this environment"
)


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
            raise storage_module.ObjectNotFound(key)
        return self.objects[key]

    def head(self, key):
        if key not in self.objects:
            raise storage_module.ObjectNotFound(key)
        return storage_module.StoredObject(
            key=key, size_bytes=len(self.objects[key]), content_type=""
        )

    def delete(self, key):
        self.objects.pop(key, None)

    def presigned_put_url(self, key, content_type, expires_in=900):
        return f"https://files.test/put/{key}"

    def presigned_get_url(self, key, expires_in=3600):
        return f"https://files.test/get/{key}"


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


def _make_user(db, account_number, email, *, name="Print User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def publisher(db):
    return _make_user(db, "TV-M-002201", "movpub@example.com", name="Moe Maker")


def _stl():
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 50


def _box(kind: bytes, content: bytes) -> bytes:
    return struct.pack(">I", 8 + len(content)) + kind + content


def _mvhd(seconds: float) -> bytes:
    timescale = 600
    content = (
        b"\x00\x00\x00\x00"
        + b"\x00" * 8
        + struct.pack(">I", timescale)
        + struct.pack(">I", int(round(seconds * timescale)))
        + b"\x00" * 80
    )
    return _box(b"mvhd", content)


def _trak(handler: bytes, entry: bytes) -> bytes:
    hdlr = _box(b"hdlr", b"\x00" * 8 + handler + b"\x00" * 12)
    stsd = _box(
        b"stsd",
        b"\x00" * 4 + struct.pack(">I", 1) + struct.pack(">I", 16) + entry + b"\x00" * 8,
    )
    mdia = _box(b"mdia", hdlr + _box(b"minf", _box(b"stbl", stsd)))
    return _box(b"trak", mdia)


def _container(seconds: float, tracks: list[tuple[bytes, bytes]]) -> bytes:
    moov = _box(b"moov", _mvhd(seconds) + b"".join(_trak(h, e) for h, e in tracks))
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    return ftyp + moov


def _webm(seconds: float) -> bytes:
    def vint(n):
        return bytes([0x80 | n])

    doctype = b"\x42\x82" + vint(4) + b"webm"
    header = b"\x1a\x45\xdf\xa3" + vint(len(doctype)) + doctype
    scale = b"\x2a\xd7\xb1" + vint(3) + (1_000_000).to_bytes(3, "big")
    duration = b"\x44\x89" + vint(8) + struct.pack(">d", seconds * 1000.0)
    info = b"\x15\x49\xa9\x66" + vint(len(scale + duration)) + scale + duration
    segment = b"\x18\x53\x80\x67" + b"\xff" + info
    return header + segment


def _publish(client, user, *, title="MOV mount"):
    resp = client.post(
        "/api/prints/files",
        data={"title": title, "description": "Holds things.", "category": "shop-fixtures"},
        files={"print_file": ("mount.stl", _stl(), "application/octet-stream")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_video(client, user, file_id, name, data):
    return client.post(
        f"/api/prints/files/{file_id}/media/video",
        files={"video": (name, data, "application/octet-stream")},
        headers=auth_headers(user),
    )


def _video_entry(client, file_id):
    resp = client.get(f"/api/prints/files/{file_id}")
    assert resp.status_code == 200, resp.text
    videos = [m for m in resp.json()["media"] if m["kind"] == "video"]
    assert len(videos) == 1
    return videos[0]


def _stored_video_bytes(fake_storage, file_id):
    keys = [
        k
        for k in fake_storage.objects
        if "/media/" in k and str(file_id) in k
    ]
    assert len(keys) == 1, keys
    return keys[0], fake_storage.objects[keys[0]]


# -- the codec reader -------------------------------------------------------


def test_bmff_video_codec_reads_the_video_track():
    hevc = _container(6, [(b"vide", b"hvc1")])
    assert service._bmff_video_codec(hevc) == "hvc1"
    h264 = _container(6, [(b"vide", b"avc1")])
    assert service._bmff_video_codec(h264) == "avc1"
    # An AUDIO track listed first must not answer for the video:
    mixed = _container(6, [(b"soun", b"mp4a"), (b"vide", b"hev1")])
    assert service._bmff_video_codec(mixed) == "hev1"
    # No tracks at all, and plain garbage: unreadable, not a guess.
    assert service._bmff_video_codec(_container(6, [])) is None
    assert service._bmff_video_codec(b"not a video at all") is None


def test_process_passthroughs_store_bytes_unchanged():
    webm = _webm(3)
    name, ctype, data, converted = service._process_video_for_storage(
        "clip.webm", webm
    )
    assert (name, ctype, converted) == ("clip.webm", "video/webm", False)
    assert data is webm

    avc_mp4 = _container(4, [(b"vide", b"avc1")])
    name, ctype, data, converted = service._process_video_for_storage(
        "clip.mp4", avc_mp4
    )
    assert (name, ctype, converted) == ("clip.mp4", "video/mp4", False)
    assert data is avc_mp4

    # An .mp4 whose sample description can't be read stores
    # as-is (documented pass-through: the reader's limit is
    # not a member-facing refusal).
    headless = _container(4, [])
    name, ctype, data, converted = service._process_video_for_storage(
        "clip.mp4", headless
    )
    assert converted is False and data is headless


def test_mov_refused_in_words_when_no_converter(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    hevc_mov = _container(6, [(b"vide", b"hvc1")])
    with pytest.raises(service.PrintsError, match="wasn't saved"):
        service._process_video_for_storage("IMG_0001.MOV", hevc_mov)


def test_duration_rule_still_measures_the_original_upload():
    # A 35-second HEVC .mov is refused by the VALIDATOR naming
    # the cap — conversion never gets a say.
    long_mov = _container(35, [(b"vide", b"hvc1")])
    with pytest.raises(service.PrintsError, match="30 seconds"):
        service.validate_video_upload("IMG_9999.MOV", long_mov)


# -- conversion, end to end through the real route ---------------------------


def _make_clip(tmp_path, name, *, codec_args, seconds=2):
    out = tmp_path / name
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size=320x240:rate=15",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            *codec_args, "-shortest", str(out),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return out.read_bytes()


@needs_ffmpeg
def test_hevc_mov_lands_as_h264_mp4(client, publisher, fake_storage, tmp_path):
    listing = _publish(client, publisher)
    mov = _make_clip(
        tmp_path,
        "in.mov",
        codec_args=["-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-c:a", "aac"],
    )
    resp = _add_video(client, publisher, listing["id"], "IMG_4021.MOV", mov)
    assert resp.status_code == 200, resp.text
    entry = _video_entry(client, listing["id"])
    assert entry["content_type"] == "video/mp4"
    assert entry["filename"].endswith(".mp4")
    # The recorded length is the ORIGINAL upload's measurement.
    assert entry["duration_seconds"] == pytest.approx(2.0, abs=0.6)
    key, stored = _stored_video_bytes(fake_storage, listing["id"])
    assert key.endswith(".mp4")
    assert service._bmff_video_codec(stored) == "avc1"
    assert service.probe_video_duration(stored) is not None


@needs_ffmpeg
def test_h264_mov_is_remuxed_not_reencoded(client, publisher, fake_storage, tmp_path):
    listing = _publish(client, publisher)
    mov = _make_clip(
        tmp_path,
        "in.mov",
        codec_args=["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"],
    )
    resp = _add_video(client, publisher, listing["id"], "clip.mov", mov)
    assert resp.status_code == 200, resp.text
    entry = _video_entry(client, listing["id"])
    assert entry["content_type"] == "video/mp4"
    _key, stored = _stored_video_bytes(fake_storage, listing["id"])
    assert service._bmff_video_codec(stored) == "avc1"
    # A remux keeps the picture stream BIT-IDENTICAL (only the
    # container and the audio encoding change); a re-encode
    # would rewrite every frame's bytes. Compare the raw H.264
    # elementary streams.
    def _h264_stream(data: bytes, tag: str) -> bytes:
        src = tmp_path / f"{tag}-in.mp4"
        dst = tmp_path / f"{tag}-out.h264"
        src.write_bytes(data)
        subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(src), "-map", "0:v:0", "-c:v", "copy",
                "-bsf:v", "h264_mp4toannexb", str(dst),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return dst.read_bytes()

    assert _h264_stream(stored, "stored") == _h264_stream(mov, "upload")


@needs_ffmpeg
def test_h264_mp4_stores_byte_identical(client, publisher, fake_storage, tmp_path):
    listing = _publish(client, publisher)
    mp4 = _make_clip(
        tmp_path,
        "in.mp4",
        codec_args=["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"],
    )
    resp = _add_video(client, publisher, listing["id"], "clip.mp4", mp4)
    assert resp.status_code == 200, resp.text
    _key, stored = _stored_video_bytes(fake_storage, listing["id"])
    assert stored == mp4


@needs_ffmpeg
def test_hevc_mp4_is_converted_too(client, publisher, fake_storage, tmp_path):
    listing = _publish(client, publisher)
    mp4 = _make_clip(
        tmp_path,
        "in.mp4",
        codec_args=["-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-c:a", "aac"],
    )
    resp = _add_video(client, publisher, listing["id"], "clip.mp4", mp4)
    assert resp.status_code == 200, resp.text
    entry = _video_entry(client, listing["id"])
    assert entry["content_type"] == "video/mp4"
    _key, stored = _stored_video_bytes(fake_storage, listing["id"])
    assert stored != mp4
    assert service._bmff_video_codec(stored) == "avc1"


# -- the edge ceiling (the incident's production half) -----------------------


def test_nginx_body_ceiling_covers_the_app_upload_cap():
    template = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "nginx.conf.template"
    ).read_text()
    values = re.findall(r"client_max_body_size\s+(\d+)m", template)
    assert len(values) >= 2, "both server blocks set an explicit ceiling"
    # The app accepts uploads up to VIDEO_MAX_BYTES (100 MB);
    # every edge ceiling must clear it plus multipart overhead,
    # so the app's own refusal is the one a member reads.
    cap_mb = service.VIDEO_MAX_BYTES // (1024 * 1024)
    assert all(int(v) > cap_mb for v in values), values
