"""3D print files service (owner order 2026-11-08).

The shelf rules, all enforced here on the server:

- READING IS PUBLIC. Anyone — signed in or not — browses,
  searches, opens a file page, and downloads PRINT files.
  Downloads count in the same request that serves the bytes
  (the Part 1 downloads discipline: one atomic UPDATE, then
  the serve).
- THE REGISTERED EXTRAS. STEP files, ratings, comments, flags
  and uploads are members-only. The routes gate on a session;
  the ownership rules live here (only the publisher updates or
  removes their own file; nobody rates their own file).
- VERSIONS ONLY RISE. An update adds a version row; old
  versions stay listed and downloadable forever. Removal is
  the only way off the shelf, and it is a tombstone, never a
  delete (the boards' moderation pattern).
- FLAGS FEED THE SHARED QUEUE. A flag writes a PrintReport
  and tells the whole moderation team in the same commit
  (the forum's pattern, inbox.notify_moderation_team), and
  the queue itself is the messaging ModerationPage's — this
  module adds its section, it does not build a second queue.
- TOPIC RULE. Mechanic / tool / toolbox prints only — the
  category set (categories.py) has no off-topic bucket, and
  the flag queue is how the community polices the rest.
- SHOWCASE MEDIA + LISTING EDITS (owner orders 2026-11-08
  21:31–23:44). A listing carries up to five photos and ONE
  video (30 seconds max — the length measured HERE from the
  container's own bytes at upload, never the client's word).
  Media belongs to the listing, not to a version; the first
  photo in media order is the cover, mirrored onto the
  file's preview_key so every surface that ever read the
  cover keeps reading it. The publisher edits their listing
  (title / description / category / media) through doors
  that never touch the version flow.
- PHONE VIDEOS ARE CONVERTED ON UPLOAD (bug lane 2026-11-09).
  An iPhone .mov is normally HEVC, which most desktop browsers
  cannot decode at all — stored raw, it would "save" and then
  never play. Any upload that is not already a web-playable
  H.264 MP4 / WebM is converted to H.264 + AAC MP4 (faststart)
  before it lands in storage; the 30-second rule is still
  measured on the ORIGINAL upload, before conversion.

Uploads arrive as multipart bodies and are stored server-side
(storage.put_bytes): print files allow .stl / .3mf / .obj,
STEP files .step / .stp, each verified against its bytes (a
renamed file does not pass), with size caps below. The
presigned-URL flow the photo surfaces use stays theirs; these
formats sit outside its content-type allowlist by design.
"""

import os
import shutil
import struct
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.storage import StorageError, content_matches_declared, storage
from app.core import i18n
from app.modules.core import content_alerts, inbox
from app.modules.core import service as core_service
from app.modules.prints import categories, models, renditions

# -- upload rules ---------------------------------------------------

PRINT_EXTENSIONS = {".stl": "model/stl", ".3mf": "model/3mf", ".obj": "text/plain"}
STEP_EXTENSIONS = {".step", ".stp"}
STEP_CONTENT_TYPE = "application/step"
PRINT_MAX_BYTES = 100 * 1024 * 1024
STEP_MAX_BYTES = 100 * 1024 * 1024
PHOTO_MAX_BYTES = 10 * 1024 * 1024

TITLE_MAX = 160
DESCRIPTION_MAX = 4000
NOTE_MAX = 500
COMMENT_MAX = 2000
REASON_MAX = 500

FORMER_MEMBER = "Former member"

SORTS = ("newest", "downloads", "rating")


class PrintsError(Exception):
    """A prints action is refused, in plain words."""


class PrintsNotFound(PrintsError):
    """The named file / comment / report isn't available."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(db: Session, actor, action: str, target, detail: dict) -> None:
    from app.modules.core import audit

    audit.record(db, actor, action=action, target=str(target), detail=detail)


# -- upload validation ------------------------------------------------


def _extension(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _looks_like_stl(data: bytes) -> bool:
    """Binary STL is self-describing: an 80-byte header, a
    little-endian triangle count, then exactly 50 bytes per
    triangle. ASCII STL opens with `solid` and reads as text.
    Either shape passes; a renamed impostor passes neither."""
    if len(data) >= 84:
        (count,) = struct.unpack("<I", data[80:84])
        if 84 + 50 * count == len(data):
            return True
    return data[:5].lower() == b"solid" and content_matches_declared(
        "text/plain", data[:512]
    )


def validate_print_upload(filename: str, data: bytes) -> str:
    """Returns the content type to store under, or raises
    PrintsError. Extension AND bytes must agree."""
    ext = _extension(filename)
    if ext not in PRINT_EXTENSIONS:
        raise PrintsError(
            "Print files must be .stl, .3mf, or .obj — "
            f"'{filename or 'that file'}' isn't one of those."
        )
    if not data:
        raise PrintsError("That print file is empty.")
    if len(data) > PRINT_MAX_BYTES:
        raise PrintsError("Print files are capped at 100 MB.")
    if ext == ".stl" and not _looks_like_stl(data):
        raise PrintsError(
            "That .stl file's contents don't read as an STL model."
        )
    if ext == ".3mf" and data[:4] not in (b"PK\x03\x04", b"PK\x07\x08"):
        raise PrintsError(
            "That .3mf file's contents don't read as a 3MF package."
        )
    if ext == ".obj" and not content_matches_declared("text/plain", data[:512]):
        raise PrintsError(
            "That .obj file's contents don't read as a text model."
        )
    return PRINT_EXTENSIONS[ext]


def validate_step_upload(filename: str, data: bytes) -> str:
    ext = _extension(filename)
    if ext not in STEP_EXTENSIONS:
        raise PrintsError(
            "STEP files must be .step or .stp — "
            f"'{filename or 'that file'}' isn't one of those."
        )
    if not data:
        raise PrintsError("That STEP file is empty.")
    if len(data) > STEP_MAX_BYTES:
        raise PrintsError("STEP files are capped at 100 MB.")
    # A STEP file opens with its ISO 10303-21 header — the
    # standard's own magic, in the first lines of the file.
    if b"ISO-10303-21" not in data[:512]:
        raise PrintsError(
            "That file's contents don't read as a STEP file."
        )
    return STEP_CONTENT_TYPE


def validate_photo_upload(filename: str, data: bytes) -> str:
    """Preview photos are images, verified by their magic
    bytes (the storage module's sniff table) — the declared
    name and type are never trusted."""
    if not data:
        raise PrintsError("That photo is empty.")
    if len(data) > PHOTO_MAX_BYTES:
        raise PrintsError("Preview photos are capped at 10 MB.")
    for content_type in ("image/jpeg", "image/png", "image/webp"):
        if content_matches_declared(content_type, data[:512]):
            return content_type
    raise PrintsError("Preview photos must be JPG, PNG, or WebP images.")


# -- showcase media rules (owner orders 2026-11-08) -----------

MEDIA_KINDS = ("photo", "video")
# Up to five photos on a listing; the first in media order is
# its cover everywhere a single picture shows.
PHOTO_MAX_COUNT = 5
VIDEO_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}
# In step with the module's other caps (print / STEP: 100 MB).
VIDEO_MAX_BYTES = 100 * 1024 * 1024
# Ryan's cap: ONE video, no longer than 30 seconds. The
# duration is MEASURED on the server from the file's own
# container (below) — the client's word is never taken. Half
# a second of tolerance covers container/frame rounding on a
# clip a phone honestly calls 30 seconds; the refusal message
# names the 30-second limit either way.
VIDEO_MAX_SECONDS = 30.0
VIDEO_TOLERANCE_SECONDS = 0.5


def _boxes(data: bytes, start: int, end: int):
    """The ISO-BMFF boxes inside data[start:end]: yields
    (type, content start, content end) per box, tolerating
    64-bit large sizes and run-to-the-end boxes."""
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8 : pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end + header:
            return
        yield data[pos + 4 : pos + 8], pos + header, min(pos + size, end)
        pos += size


def _mp4_duration(data: bytes) -> float | None:
    """The duration an ISO-BMFF file (MP4 / MOV) declares in
    its movie header: mvhd's duration / timescale, in seconds.
    Pure container reading — no decoder, no external tool, so
    the check runs identically everywhere the API runs."""
    for box_type, start, end in _boxes(data, 0, len(data)):
        if box_type != b"moov":
            continue
        for child_type, child_start, child_end in _boxes(data, start, end):
            if child_type != b"mvhd":
                continue
            content = data[child_start:child_end]
            if len(content) < 4:
                return None
            if content[0] == 1:  # version 1: 64-bit times + duration
                if len(content) < 32:
                    return None
                timescale = struct.unpack(">I", content[20:24])[0]
                duration = struct.unpack(">Q", content[24:32])[0]
            else:  # version 0: 32-bit throughout
                if len(content) < 20:
                    return None
                timescale = struct.unpack(">I", content[12:16])[0]
                duration = struct.unpack(">I", content[16:20])[0]
            if not timescale:
                return None
            return duration / timescale
    return None


def _ebml_element(data: bytes, pos: int):
    """One EBML element header at pos: (element id, header
    length, size) with size -1 for the unknown-size marker,
    or None when the bytes run out / don't parse."""
    if pos >= len(data) or data[pos] == 0:
        return None
    first = data[pos]
    mask = 0x80
    id_len = 1
    while id_len <= 4 and not (first & mask):
        mask >>= 1
        id_len += 1
    if pos + id_len >= len(data):
        return None
    element_id = int.from_bytes(data[pos : pos + id_len], "big")
    # The data size is a vint with its marker bit stripped.
    size_pos = pos + id_len
    size_first = data[size_pos]
    if size_first == 0:
        return None
    mask = 0x80
    size_len = 1
    while size_len <= 8 and not (size_first & mask):
        mask >>= 1
        size_len += 1
    if size_pos + size_len > len(data):
        return None
    raw = int.from_bytes(data[size_pos : size_pos + size_len], "big")
    value = raw & ((1 << (7 * size_len)) - 1)
    if value == (1 << (7 * size_len)) - 1:
        value = -1  # unknown size
    return element_id, id_len + size_len, value


def _webm_duration(data: bytes) -> float | None:
    """A WebM's declared duration: the Segment Info's Duration
    (a float, in TimecodeScale units — nanoseconds at the
    default scale). Read from the container, like the MP4
    path; a stream that declares no duration can't be
    verified, and the caller refuses it."""
    if data[:4] != b"\x1a\x45\xdf\xa3":
        return None
    header = _ebml_element(data, 0)
    if header is None:
        return None
    _, header_len, header_size = header
    pos = header_len + (header_size if header_size >= 0 else 0)
    end = len(data)
    info_span = None
    while pos < end:
        element = _ebml_element(data, pos)
        if element is None:
            return None
        element_id, el_header, el_size = element
        content = pos + el_header
        el_end = end if el_size < 0 else min(content + el_size, end)
        if element_id == 0x18538067:  # Segment — descend into it
            pos = content
            end = el_end
            continue
        if element_id == 0x1549A966:  # Info
            info_span = (content, el_end)
            break
        if element_id == 0x1F43B675:  # Cluster — Info precedes it
            return None
        pos = el_end
    if info_span is None:
        return None
    start, info_end = info_span
    timescale = 1_000_000  # the EBML default (nanoseconds)
    duration = None
    pos = start
    while pos < info_end:
        element = _ebml_element(data, pos)
        if element is None:
            break
        element_id, el_header, el_size = element
        content = pos + el_header
        el_end = info_end if el_size < 0 else min(content + el_size, info_end)
        if element_id == 0x2AD7B1 and el_end > content:  # TimecodeScale
            timescale = (
                int.from_bytes(data[content:el_end], "big") or timescale
            )
        elif element_id == 0x4489:  # Duration (float32 or float64)
            raw = data[content:el_end]
            if len(raw) == 4:
                duration = struct.unpack(">f", raw)[0]
            elif len(raw) == 8:
                duration = struct.unpack(">d", raw)[0]
        pos = el_end
    if duration is None:
        return None
    return duration * timescale / 1_000_000_000


def probe_video_duration(data: bytes) -> float | None:
    """The container's own declared length, in seconds —
    the number the 30-second rule is enforced against."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return _webm_duration(data)
    if data[4:8] == b"ftyp":
        return _mp4_duration(data)
    return None


def validate_video_upload(filename: str, data: bytes) -> tuple[str, float]:
    """Returns (content type, measured duration seconds), or
    raises PrintsError. Extension AND bytes must agree, and
    the LENGTH IS VERIFIED from the container: over the limit
    — or unverifiable — is refused, in words that name the
    30-second cap."""
    ext = _extension(filename)
    if ext not in VIDEO_EXTENSIONS:
        raise PrintsError(
            "Videos must be .mp4, .webm, or .mov — "
            f"'{filename or 'that file'}' isn't one of those."
        )
    if not data:
        raise PrintsError("That video is empty.")
    if len(data) > VIDEO_MAX_BYTES:
        raise PrintsError("Videos are capped at 100 MB.")
    if ext == ".webm":
        # The EBML header + the webm DocType in the header block.
        if data[:4] != b"\x1a\x45\xdf\xa3" or b"webm" not in data[:256]:
            raise PrintsError(
                "That .webm file's contents don't read as a WebM video."
            )
    elif data[4:8] != b"ftyp":
        raise PrintsError(
            "That video's contents don't read as an MP4/MOV video."
        )
    duration = probe_video_duration(data)
    if duration is None:
        raise PrintsError(
            "That video's length couldn't be verified — only videos "
            "whose length can be checked can go up (30 seconds max)."
        )
    if duration > VIDEO_MAX_SECONDS + VIDEO_TOLERANCE_SECONDS:
        raise PrintsError(
            "Videos are capped at 30 seconds — "
            f"that one runs {int(round(duration))} seconds."
        )
    return VIDEO_EXTENSIONS[ext], duration


def _bmff_video_codec(data: bytes) -> str | None:
    """The video codec an ISO-BMFF file (MP4 / MOV) carries,
    read from its video track's sample description — avc1 is
    H.264; hvc1 / hev1 are HEVC. This is the fact that decides
    whether browsers can play the file as it stands. Pure
    container reading, like the duration prober: find the
    track whose handler is 'vide' (an audio track listed first
    must not answer for it) and read its first sample entry."""
    def _track_entry(track_start: int, track_end: int):
        handler = None
        entry = None
        for t, s, e in _boxes(data, track_start, track_end):
            if t != b"mdia":
                continue
            for mt, ms, me in _boxes(data, s, e):
                if mt == b"hdlr" and me - ms >= 12:
                    handler = data[ms + 8 : ms + 12]
                elif mt == b"minf":
                    for nt, ns, ne in _boxes(data, ms, me):
                        if nt != b"stbl":
                            continue
                        for bt, bs, be in _boxes(data, ns, ne):
                            if bt == b"stsd" and be - bs >= 16:
                                entry = data[bs + 12 : bs + 16]
            return handler, entry
        return None, None

    fallback = None
    for box_type, start, end in _boxes(data, 0, len(data)):
        if box_type != b"moov":
            continue
        for child_type, child_start, child_end in _boxes(data, start, end):
            if child_type != b"trak":
                continue
            handler, entry = _track_entry(child_start, child_end)
            if entry is None:
                continue
            if handler == b"vide":
                return (
                    entry.decode("ascii", "replace").strip().lower()
                    or None
                )
            if fallback is None:
                fallback = entry
        break
    if fallback is not None:
        return fallback.decode("ascii", "replace").strip().lower() or None
    return None


# Converting a phone video (an HEVC .mov above all) into the
# H.264 + AAC MP4 every browser plays. ffmpeg ships in the api
# image for exactly this (see the backend Dockerfile). The
# conversion runs at upload, AFTER the duration rule measured
# the original bytes: the stored file is a web rendition; the
# rule never moves.
VIDEO_TRANSCODE_TIMEOUT_SECONDS = 480


def _convert_video_to_mp4(filename: str, data: bytes, *, remux: bool) -> bytes:
    """Convert an accepted video upload into a web-playable
    H.264 + AAC MP4, moov first so the viewer streams it.

    `remux` is for uploads whose video is already H.264 (a .mov
    from a phone set to 'Most Compatible'): the picture stream
    copies across untouched and only the audio is re-encoded.
    Anything else is re-encoded, capped at 1920 wide — a 4K
    phone clip becomes a 1080p web clip (the site's standing
    posture for uploads: store the rendition the web needs).
    A failed remux falls back to the re-encode before giving
    up, and the output is verified (duration readable, codec
    avc1) before a single byte is trusted."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PrintsError(
            "That video can't be processed right now — it wasn't "
            "saved. Please try again later."
        )
    ext = _extension(filename) or ".bin"
    attempts: list[list[str]] = []
    if remux:
        attempts.append(["-c:v", "copy", "-c:a", "aac", "-b:a", "160k"])
    attempts.append(
        [
            "-vf", "scale='min(1920,iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
        ]
    )
    with tempfile.TemporaryDirectory(prefix="print-video-") as tmp:
        src = os.path.join(tmp, f"in{ext}")
        dst = os.path.join(tmp, "out.mp4")
        with open(src, "wb") as fh:
            fh.write(data)
        for codec_args in attempts:
            try:
                proc = subprocess.run(
                    [
                        ffmpeg, "-hide_banner", "-loglevel", "error",
                        "-y", "-i", src,
                        "-map", "0:v:0", "-map", "0:a:0?",
                        *codec_args,
                        "-movflags", "+faststart",
                        dst,
                    ],
                    capture_output=True,
                    timeout=VIDEO_TRANSCODE_TIMEOUT_SECONDS,
                )
            except (subprocess.TimeoutExpired, OSError):
                break
            if proc.returncode == 0 and os.path.exists(dst):
                with open(dst, "rb") as fh:
                    out = fh.read()
                if (
                    out
                    and probe_video_duration(out) is not None
                    and _bmff_video_codec(out) == "avc1"
                ):
                    return out
            # A failed attempt leaves no partial output behind
            # for the next attempt to trip over.
            if os.path.exists(dst):
                os.unlink(dst)
    raise PrintsError(
        "That video couldn't be converted for web playback — it "
        "wasn't saved. An MP4 recorded or exported from your "
        "phone usually works."
    )


def _process_video_for_storage(
    filename: str, data: bytes
) -> tuple[str, str, bytes, bool]:
    """What actually lands in storage for an accepted video:
    (stored filename, content type, bytes, converted?). A WebM
    and an H.264 MP4 are already what browsers play and store
    as-is. Everything else — every .mov, an HEVC MP4 — is
    converted to H.264 MP4 first, so the listing's video PLAYS
    for the visitor watching it, not just on the phone that
    shot it (bug lane 2026-11-09).

    The one pass-through on a doubt: an .mp4 whose sample
    description the codec reader can't find stores as-is. MP4
    is the web's own container; an unreadable stsd there is
    likelier this reader's limit than an unplayable file, and
    a member's valid MP4 doesn't get refused over it. A .mov
    gets no such benefit — the QuickTime container is itself
    the thing being converted away, and ffmpeg reads whatever
    this reader missed."""
    ext = _extension(filename)
    if ext == ".webm":
        return filename, VIDEO_EXTENSIONS[ext], data, False
    codec = _bmff_video_codec(data)
    if ext == ".mp4" and codec in ("avc1", None):
        return filename, VIDEO_EXTENSIONS[ext], data, False
    stored = _convert_video_to_mp4(filename, data, remux=(codec == "avc1"))
    safe = storage.safe_filename(filename)
    stem = safe.rsplit(".", 1)[0] if "." in safe else safe
    return f"{stem}.mp4", "video/mp4", stored, True


def _put(key: str, data: bytes, content_type: str) -> None:
    try:
        storage.put_bytes(key, data, content_type)
    except StorageError as exc:
        raise PrintsError(f"The file couldn't be stored: {exc}") from exc


def _generate_photo_variants(key: str) -> None:
    """Eagerly make a freshly stored photo's card + display
    renditions (renditions.py — the inventory pipeline's
    derived-key cache), so the shelf's first reads are plain
    storage fetches. Best-effort by design: the original is
    the source of truth, rendition trouble never fails an
    upload, and a missing rendition is retried lazily on
    read and by the backfill script."""
    try:
        renditions.ensure_variants(key)
    except Exception:
        pass


def _delete_quietly(key: str | None) -> None:
    if not key:
        return
    try:
        storage.delete(key)
    except StorageError:
        pass


def _key(publisher_id, file_id, kind: str, filename: str, version: int | None = None) -> str:
    safe = storage.safe_filename(filename)
    if kind == "preview":
        return f"prints/{publisher_id}/{file_id}/preview-{safe}"
    return f"prints/{publisher_id}/{file_id}/v{version}/{kind}-{safe}"


# -- reads ------------------------------------------------------------


def get_file(db: Session, file_id: uuid.UUID) -> models.PrintFile | None:
    return db.get(models.PrintFile, file_id)


def get_live_file(db: Session, file_id: uuid.UUID) -> models.PrintFile:
    row = get_file(db, file_id)
    if row is None or row.status != "live":
        raise PrintsNotFound("That print file isn't available.")
    return row


def publisher_block(db: Session, row: models.PrintFile) -> dict:
    """The public publisher identity (the forum's author-block
    posture): a gone or deactivated account renders as Former
    member, never an error, never a stale name."""
    user = None if row.publisher_gone else core_service.get_user_by_id(db, row.publisher_id)
    if user is None or not user.is_active:
        return {
            "user_id": row.publisher_id,
            "display_name": FORMER_MEMBER,
            "account_number": "",
        }
    return {
        "user_id": user.id,
        "display_name": user.name,
        "account_number": user.account_number,
    }


def _rating_view(row: models.PrintFile) -> dict:
    average = (row.rating_sum / row.rating_count) if row.rating_count else None
    return {"average": average, "count": row.rating_count}


# -- per-file update opt-in (sweep E4, busy-work #6) -----------
#
# "Tell me when THIS file gets a new version" — the door on the
# listing page. Presence of a PrintFileFollow row IS the opt-in
# (default OFF: no row). The publisher never follows their own
# file through this door, and the update fan-out below excludes
# the publisher regardless, so nobody is ever notified of their
# own publish.

_UPDATED_COPY = {
    "en": (
        "Print file updated",
        "“{title}” has a new version (v{version}).",
    ),
    "es": (
        "Archivo de impresión actualizado",
        "«{title}» tiene una versión nueva (v{version}).",
    ),
}


def is_following(db: Session, file_id: uuid.UUID, viewer) -> bool:
    if viewer is None:
        return False
    return (
        db.scalars(
            select(models.PrintFileFollow).where(
                models.PrintFileFollow.file_id == file_id,
                models.PrintFileFollow.user_id == viewer.id,
            )
        ).first()
        is not None
    )


def set_following(db: Session, user, file_id: uuid.UUID, following: bool) -> bool:
    """Flip the per-file opt-in in place. The listing must be
    live; the publisher's own file is refused in plain words
    (they don't need a door to their own updates)."""
    row = get_live_file(db, file_id)
    if row.publisher_id == user.id:
        raise PrintsError("This is your own file — you don't need update alerts for it.")
    existing = db.scalars(
        select(models.PrintFileFollow).where(
            models.PrintFileFollow.file_id == file_id,
            models.PrintFileFollow.user_id == user.id,
        )
    ).first()
    if following and existing is None:
        db.add(models.PrintFileFollow(user_id=user.id, file_id=file_id))
    elif not following and existing is not None:
        db.delete(existing)
    db.commit()
    return following


def _notify_file_updated(
    db: Session, row: models.PrintFile, version_number: int
) -> int:
    """Tell this file's followers (minus the publisher) about
    a new version, each in their own language, in the update's
    own commit (commit=False)."""
    follower_ids = db.scalars(
        select(models.PrintFileFollow.user_id).where(
            models.PrintFileFollow.file_id == row.id
        )
    ).all()
    sent = 0
    for user_id in follower_ids:
        if user_id == row.publisher_id:
            continue
        user = core_service.get_user_by_id(db, user_id)
        if user is None or not user.is_active:
            continue
        title, body = _UPDATED_COPY[i18n.resolve_locale(user)]
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_PRINT_FILE_UPDATED,
            title=title,
            body=body.format(title=row.title, version=version_number),
            data={"file_id": str(row.id)},
            commit=False,
        )
        sent += 1
    return sent


def _my_rating(db: Session, file_id: uuid.UUID, viewer) -> int | None:
    if viewer is None:
        return None
    row = db.scalars(
        select(models.PrintRating).where(
            models.PrintRating.file_id == file_id,
            models.PrintRating.user_id == viewer.id,
        )
    ).first()
    return row.stars if row is not None else None


def file_view(db: Session, row: models.PrintFile, viewer=None) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description,
        "category": row.category_key,
        "publisher": publisher_block(db, row),
        "status": row.status,
        "current_version": row.current_version,
        "download_count": row.download_count,
        "step_download_count": row.step_download_count,
        "rating": _rating_view(row),
        "my_rating": _my_rating(db, row.id, viewer),
        "following": is_following(db, row.id, viewer),
        "has_preview": row.preview_key is not None,
        "mine": viewer is not None and viewer.id == row.publisher_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def version_view(row: models.PrintFileVersion) -> dict:
    return {
        "version_number": row.version_number,
        "note": row.note,
        "print_filename": row.print_filename,
        "print_size": row.print_size,
        "has_step": row.step_key is not None,
        "step_filename": row.step_filename,
        "downloads": row.downloads,
        "step_downloads": row.step_downloads,
        "created_at": row.created_at,
    }


def list_versions(db: Session, file_id: uuid.UUID) -> list[models.PrintFileVersion]:
    return list(
        db.scalars(
            select(models.PrintFileVersion)
            .where(models.PrintFileVersion.file_id == file_id)
            .order_by(models.PrintFileVersion.version_number.desc())
        ).all()
    )


def _terms(q: str) -> list[str]:
    return [t.lower() for t in (q or "").split() if t]


def _matches(terms: list[str], fields: list[str]) -> bool:
    haystack = " ".join(f for f in fields if f).lower()
    return all(term in haystack for term in terms)


def shelf_stats(db: Session) -> dict:
    """Shelf-wide totals for the browse page's header facts
    (main tab layout conversion, 2026-11-10): how many files
    are live on the shelf and how many print-file downloads
    they have served in total — the same download_count the
    browse rows show, summed over the same live set, NEVER
    narrowed by the reader's search/filter (a fact about the
    shelf, not about the current view)."""
    rows = list(
        db.scalars(
            select(models.PrintFile.download_count).where(
                models.PrintFile.status == "live"
            )
        ).all()
    )
    return {"listings": len(rows), "downloads": sum(rows)}


def browse(
    db: Session,
    *,
    q: str = "",
    category: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
    viewer=None,
) -> tuple[list[dict], int]:
    """The shelf: live files only, with the section's own
    search (title / description / category / publisher name),
    its category filter, and its sorts."""
    stmt = select(models.PrintFile).where(models.PrintFile.status == "live")
    if category:
        stmt = stmt.where(models.PrintFile.category_key == category)
    rows = list(db.scalars(stmt).all())
    terms = _terms(q)
    views = []
    for row in rows:
        view = file_view(db, row, viewer)
        if terms and not _matches(
            terms,
            [row.title, row.description, row.category_key, view["publisher"]["display_name"]],
        ):
            continue
        views.append(view)
    if sort == "downloads":
        views.sort(key=lambda v: (-v["download_count"], -_ts(v["created_at"])))
    elif sort == "rating":
        views.sort(
            key=lambda v: (
                -(v["rating"]["average"] or 0),
                -v["rating"]["count"],
                -_ts(v["created_at"]),
            )
        )
    else:  # newest
        views.sort(key=lambda v: -_ts(v["created_at"]))
    total = len(views)
    return views[offset : offset + limit], total


def _ts(value) -> float:
    return value.timestamp() if value is not None else 0.0


def my_files(db: Session, user) -> list[dict]:
    rows = list(
        db.scalars(
            select(models.PrintFile)
            .where(models.PrintFile.publisher_id == user.id)
            .order_by(models.PrintFile.created_at.desc())
        ).all()
    )
    return [file_view(db, row, user) for row in rows]


def detail(db: Session, row: models.PrintFile, viewer=None) -> dict:
    view = file_view(db, row, viewer)
    view["media"] = media_views(db, row.id)
    view["versions"] = [version_view(v) for v in list_versions(db, row.id)]
    view["maker_links"] = [
        {"id": link.id, "label": link.label, "url": link.url}
        for link in list_links(db, row.publisher_id)
    ]
    view["comment_count"] = _comment_count(db, row.id)
    return view


def _comment_count(db: Session, file_id: uuid.UUID) -> int:
    from sqlalchemy import func as _func

    return int(
        db.scalar(
            select(_func.count())
            .select_from(models.PrintComment)
            .where(
                models.PrintComment.file_id == file_id,
                models.PrintComment.status == "live",
            )
        )
        or 0
    )


# -- showcase media (photos + the one video) ----------------------------


def list_media(db: Session, file_id: uuid.UUID) -> list[models.PrintMedia]:
    """The listing's media in ITS order: one sequence across
    photos and the video — the tab's tiles and the preview
    viewer's walk read exactly this."""
    return list(
        db.scalars(
            select(models.PrintMedia)
            .where(models.PrintMedia.file_id == file_id)
            .order_by(
                models.PrintMedia.sort_order,
                models.PrintMedia.created_at,
                models.PrintMedia.id,
            )
        ).all()
    )


def media_view(row: models.PrintMedia) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "content_type": row.content_type,
        "filename": row.filename,
        "size_bytes": row.size_bytes,
        "duration_seconds": row.duration_seconds,
        "sort_order": row.sort_order,
    }


def media_views(db: Session, file_id: uuid.UUID) -> list[dict]:
    return [media_view(m) for m in list_media(db, file_id)]


def get_media(
    db: Session, file_id: uuid.UUID, media_id: uuid.UUID
) -> models.PrintMedia | None:
    row = db.get(models.PrintMedia, media_id)
    if row is None or row.file_id != file_id:
        return None
    return row


def _media_key(publisher_id, file_id, media_id, filename: str) -> str:
    return (
        f"prints/{publisher_id}/{file_id}/media/"
        f"{media_id}-{storage.safe_filename(filename)}"
    )


def _sync_cover(db: Session, row: models.PrintFile) -> None:
    """Keep the denormalized cover (preview_key /
    preview_content_type — what browse rows, search and the
    record header have always read) pointed at the FIRST
    PHOTO in media order, or nowhere when the set has none."""
    photos = [m for m in list_media(db, row.id) if m.kind == "photo"]
    if photos:
        row.preview_key = photos[0].storage_key
        row.preview_content_type = photos[0].content_type
    else:
        row.preview_key = None
        row.preview_content_type = ""


def _renumber(db: Session, row: models.PrintFile, ordered_ids: list) -> None:
    """Rewrite the media sequence as exactly these ids, in
    this order, numbered 0..n-1."""
    by_id = {m.id: m for m in list_media(db, row.id)}
    for position, media_id in enumerate(ordered_ids):
        by_id[media_id].sort_order = position


def _own_live_file(db: Session, user, file_id: uuid.UUID) -> models.PrintFile:
    """The publisher's door for edits (add_version's posture):
    another member's file — or a missing one — is simply not
    available; your own removed file can't be edited."""
    row = get_file(db, file_id)
    if row is None or row.publisher_id != user.id:
        raise PrintsNotFound("That print file isn't available.")
    if row.status != "live":
        raise PrintsError("That file has been removed — it can't be edited.")
    return row


def add_photo(
    db: Session, user, file_id: uuid.UUID, photo_upload: tuple[str, bytes]
) -> list[dict]:
    """Add one photo to the listing's set (five at most). The
    first photo in the order is the listing's cover."""
    row = _own_live_file(db, user, file_id)
    photos = [m for m in list_media(db, row.id) if m.kind == "photo"]
    if len(photos) >= PHOTO_MAX_COUNT:
        raise PrintsError(
            "A listing carries up to 5 photos — "
            "remove one before adding another."
        )
    photo_type = validate_photo_upload(photo_upload[0], photo_upload[1])
    media_id = uuid.uuid4()
    key = _media_key(user.id, row.id, media_id, photo_upload[0])
    _put(key, photo_upload[1], photo_type)
    _generate_photo_variants(key)
    existing = list_media(db, row.id)
    db.add(
        models.PrintMedia(
            id=media_id,
            file_id=row.id,
            kind="photo",
            storage_key=key,
            content_type=photo_type,
            filename=storage.safe_filename(photo_upload[0]),
            size_bytes=len(photo_upload[1]),
            duration_seconds=None,
            sort_order=len(existing),
        )
    )
    db.flush()
    _sync_cover(db, row)
    row.updated_at = _now()
    db.commit()
    _audit(db, user, "prints.media_add", row.id, {"kind": "photo"})
    return media_views(db, row.id)


def add_video(
    db: Session, user, file_id: uuid.UUID, video_upload: tuple[str, bytes]
) -> list[dict]:
    """Set the listing's ONE video. Its length was verified
    from the container by the validator — over 30 seconds
    (or unverifiable) never reaches storage — and what lands
    in storage is the web-playable rendition (a phone .mov is
    converted to H.264 MP4; see _process_video_for_storage).
    The recorded duration is the ORIGINAL upload's measured
    length: the rule is enforced on what the member sent."""
    row = _own_live_file(db, user, file_id)
    existing = list_media(db, row.id)
    if any(m.kind == "video" for m in existing):
        raise PrintsError(
            "This listing already has a video — "
            "remove it before adding a new one."
        )
    _video_type, duration = validate_video_upload(
        video_upload[0], video_upload[1]
    )
    stored_name, stored_type, stored_bytes, converted = (
        _process_video_for_storage(video_upload[0], video_upload[1])
    )
    media_id = uuid.uuid4()
    key = _media_key(user.id, row.id, media_id, stored_name)
    _put(key, stored_bytes, stored_type)
    db.add(
        models.PrintMedia(
            id=media_id,
            file_id=row.id,
            kind="video",
            storage_key=key,
            content_type=stored_type,
            filename=storage.safe_filename(stored_name),
            size_bytes=len(stored_bytes),
            duration_seconds=duration,
            sort_order=len(existing),
        )
    )
    row.updated_at = _now()
    db.commit()
    audit_detail: dict = {"kind": "video", "duration_seconds": duration}
    if converted:
        audit_detail["converted_from"] = video_upload[0]
    _audit(db, user, "prints.media_add", row.id, audit_detail)
    return media_views(db, row.id)


def remove_media(
    db: Session, user, file_id: uuid.UUID, media_id: uuid.UUID
) -> list[dict]:
    """Take one item out of the set; the order closes up
    behind it and the cover follows the first photo."""
    row = _own_live_file(db, user, file_id)
    media = get_media(db, row.id, media_id)
    if media is None:
        raise PrintsNotFound("That media isn't on this listing.")
    kind = media.kind
    _delete_quietly(media.storage_key)
    if kind == "photo":
        renditions.delete_variants(media.storage_key)
    db.delete(media)
    db.flush()
    _renumber(db, row, [m.id for m in list_media(db, row.id)])
    _sync_cover(db, row)
    row.updated_at = _now()
    db.commit()
    _audit(db, user, "prints.media_remove", row.id, {"kind": kind})
    return media_views(db, row.id)


def reorder_media(
    db: Session, user, file_id: uuid.UUID, media_ids: list[uuid.UUID]
) -> list[dict]:
    """Restate the whole sequence (the edit page sends what
    it shows). The list must be exactly this listing's media
    — no strangers, no duplicates, nothing dropped."""
    row = _own_live_file(db, user, file_id)
    current = [m.id for m in list_media(db, row.id)]
    if len(media_ids) != len(current) or set(media_ids) != set(current):
        raise PrintsError("That order doesn't match this listing's media.")
    _renumber(db, row, list(media_ids))
    _sync_cover(db, row)
    row.updated_at = _now()
    db.commit()
    _audit(db, user, "prints.media_reorder", row.id, {"count": len(media_ids)})
    return media_views(db, row.id)


def update_listing(
    db: Session,
    user,
    file_id: uuid.UUID,
    *,
    title: str,
    description: str,
    category_key: str,
) -> dict:
    """Edit the LISTING — title, description, category. The
    version pointer and every version row are deliberately
    untouched: versions are the print/STEP update flow's
    alone, and a text edit never moves them."""
    row = _own_live_file(db, user, file_id)
    if not categories.is_category(category_key or ""):
        raise PrintsError("Pick one of the shelf's categories.")
    row.title = _clean_title(title)
    row.description = _clean_description(description)
    row.category_key = category_key
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    _audit(db, user, "prints.edit", row.id, {"title": row.title})
    return detail(db, row, user)


# -- publishing -------------------------------------------------------


def _clean_title(value: str) -> str:
    title = (value or "").strip()
    if not title:
        raise PrintsError("Give the file a title.")
    return title[:TITLE_MAX]


def _clean_description(value: str) -> str:
    return (value or "").strip()[:DESCRIPTION_MAX]


def _clean_note(value: str) -> str:
    return (value or "").strip()[:NOTE_MAX]


def create_file(
    db: Session,
    user,
    *,
    title: str,
    description: str,
    category_key: str,
    note: str,
    print_upload: tuple[str, bytes],
    step_upload: tuple[str, bytes] | None,
    photo_upload: tuple[str, bytes] | None,
) -> dict:
    """Publish a NEW file at v1. Uploads are validated (type +
    bytes + size) before anything is stored or written."""
    if not categories.is_category(category_key or ""):
        raise PrintsError("Pick one of the shelf's categories.")
    clean_title = _clean_title(title)
    clean_description = _clean_description(description)
    clean_note = _clean_note(note)
    print_name, print_data = print_upload
    print_type = validate_print_upload(print_name, print_data)
    step_name = step_data = step_type = None
    if step_upload is not None:
        step_name, step_data = step_upload
        step_type = validate_step_upload(step_name, step_data)
    photo_type = None
    if photo_upload is not None:
        photo_type = validate_photo_upload(photo_upload[0], photo_upload[1])

    file_id = uuid.uuid4()
    print_key = _key(user.id, file_id, "print", print_name, version=1)
    _put(print_key, print_data, print_type)
    step_key = None
    if step_upload is not None:
        step_key = _key(user.id, file_id, "step", step_name, version=1)
        _put(step_key, step_data, step_type)
    preview_key = None
    if photo_upload is not None:
        preview_key = _key(user.id, file_id, "preview", photo_upload[0])
        _put(preview_key, photo_upload[1], photo_type)
        _generate_photo_variants(preview_key)

    row = models.PrintFile(
        id=file_id,
        publisher_id=user.id,
        title=clean_title,
        description=clean_description,
        category_key=category_key,
        status="live",
        current_version=1,
        preview_key=preview_key,
        preview_content_type=photo_type or "",
    )
    db.add(row)
    if photo_upload is not None and preview_key is not None:
        # The publish photo is photo #1 of the listing's
        # showcase set, on the same stored object the cover
        # cache points at (one copy of the bytes).
        db.add(
            models.PrintMedia(
                file_id=file_id,
                kind="photo",
                storage_key=preview_key,
                content_type=photo_type or "",
                filename=storage.safe_filename(photo_upload[0]),
                size_bytes=len(photo_upload[1]),
                duration_seconds=None,
                sort_order=0,
            )
        )
    db.add(
        models.PrintFileVersion(
            file_id=file_id,
            version_number=1,
            print_key=print_key,
            print_filename=storage.safe_filename(print_name),
            print_size=len(print_data),
            step_key=step_key,
            step_filename=storage.safe_filename(step_name) if step_name else "",
            step_size=len(step_data) if step_data else 0,
            note=clean_note,
        )
    )
    # New-content opt-in (sweep E4): the prints-box audience is
    # told in THIS commit (commit=False inside the fan-out);
    # the publisher is excluded by the fan-out itself.
    content_alerts.notify_new_print_file(
        db, file_id=row.id, title=row.title, publisher_id=user.id
    )
    db.commit()
    db.refresh(row)
    _audit(db, user, "prints.publish", row.id, {"title": row.title})
    return detail(db, row, user)


def add_version(
    db: Session,
    user,
    file_id: uuid.UUID,
    *,
    note: str,
    print_upload: tuple[str, bytes],
    step_upload: tuple[str, bytes] | None,
    photo_upload: tuple[str, bytes] | None,
) -> dict:
    """Publish an UPDATE: the next version number, with the old
    versions untouched. The publisher's own live files only."""
    row = get_file(db, file_id)
    if row is None or row.publisher_id != user.id:
        raise PrintsNotFound("That print file isn't available.")
    if row.status != "live":
        raise PrintsError("That file has been removed — it can't be updated.")
    print_name, print_data = print_upload
    print_type = validate_print_upload(print_name, print_data)
    step_name = step_data = step_type = None
    if step_upload is not None:
        step_name, step_data = step_upload
        step_type = validate_step_upload(step_name, step_data)
    photo_type = None
    if photo_upload is not None:
        photo_type = validate_photo_upload(photo_upload[0], photo_upload[1])

    number = row.current_version + 1
    print_key = _key(user.id, row.id, "print", print_name, version=number)
    _put(print_key, print_data, print_type)
    step_key = None
    if step_upload is not None:
        step_key = _key(user.id, row.id, "step", step_name, version=number)
        _put(step_key, step_data, step_type)
    if photo_upload is not None:
        # An update's photo is the listing's NEW COVER (the
        # wizard seat's longstanding meaning): it takes the
        # front of the media order. The rest of the set keeps
        # its order; at the 5-photo cap the displaced photo is
        # the one that held the front — never the whole set.
        media_id = uuid.uuid4()
        new_key = _media_key(user.id, row.id, media_id, photo_upload[0])
        _put(new_key, photo_upload[1], photo_type)
        _generate_photo_variants(new_key)
        db.add(
            models.PrintMedia(
                id=media_id,
                file_id=row.id,
                kind="photo",
                storage_key=new_key,
                content_type=photo_type or "",
                filename=storage.safe_filename(photo_upload[0]),
                size_bytes=len(photo_upload[1]),
                duration_seconds=None,
                sort_order=-1,
            )
        )
        db.flush()
        photos = [
            m
            for m in list_media(db, row.id)
            if m.kind == "photo" and m.id != media_id
        ]
        if len(photos) >= PHOTO_MAX_COUNT:
            displaced = photos[0]
            _delete_quietly(displaced.storage_key)
            renditions.delete_variants(displaced.storage_key)
            db.delete(displaced)
            db.flush()
        rest = [m.id for m in list_media(db, row.id) if m.id != media_id]
        _renumber(db, row, [media_id] + rest)
        _sync_cover(db, row)

    db.add(
        models.PrintFileVersion(
            file_id=row.id,
            version_number=number,
            print_key=print_key,
            print_filename=storage.safe_filename(print_name),
            print_size=len(print_data),
            step_key=step_key,
            step_filename=storage.safe_filename(step_name) if step_name else "",
            step_size=len(step_data) if step_data else 0,
            note=_clean_note(note),
        )
    )
    row.current_version = number
    row.updated_at = _now()
    # Per-file update opt-in (sweep E4): this file's followers
    # are told in THIS commit; the publisher is excluded.
    _notify_file_updated(db, row, number)
    db.commit()
    db.refresh(row)
    _audit(db, user, "prints.update", row.id, {"version": number})
    return detail(db, row, user)


def remove_file(
    db: Session,
    actor,
    file_id: uuid.UUID,
    *,
    reason: str = "",
    by_moderator: bool = False,
) -> dict:
    """Take a file off the shelf (tombstone). The publisher
    removes their own; the moderator path (god / moderator
    admin seats, gated in the routes) removes anyone's. Open
    flags on the file close as actioned — the forum's rule."""
    row = get_file(db, file_id)
    if row is None:
        raise PrintsNotFound("That print file isn't available.")
    if not by_moderator and row.publisher_id != actor.id:
        raise PrintsNotFound("That print file isn't available.")
    if row.status == "removed":
        raise PrintsError("That file has already been removed.")
    row.status = "removed"
    row.removed_by_id = actor.id
    row.removed_at = _now()
    row.removed_reason = (reason or "").strip()[:REASON_MAX] or (
        "Removed by moderation." if by_moderator else "Removed by the publisher."
    )
    _action_reports(db, file_id=row.id, resolution="File removed.")
    db.commit()
    db.refresh(row)
    _audit(
        db,
        actor,
        "prints.file_remove",
        row.id,
        {"by_moderator": by_moderator, "reason": row.removed_reason},
    )
    return file_view(db, row, actor)


# -- downloads --------------------------------------------------------


def _version_row(
    db: Session, file_id: uuid.UUID, version_number: int | None
) -> models.PrintFileVersion | None:
    stmt = select(models.PrintFileVersion).where(
        models.PrintFileVersion.file_id == file_id
    )
    if version_number is not None:
        stmt = stmt.where(models.PrintFileVersion.version_number == version_number)
    else:
        stmt = stmt.order_by(models.PrintFileVersion.version_number.desc())
    return db.scalars(stmt).first()


def record_print_download(
    db: Session, file_id: uuid.UUID, version_number: int | None
) -> tuple[models.PrintFile, models.PrintFileVersion] | None:
    """Count first (one atomic UPDATE per counter), then serve
    — the Part 1 discipline. Returns None when the file or the
    version isn't downloadable (unknown, or off the shelf)."""
    row = get_file(db, file_id)
    if row is None or row.status != "live":
        return None
    version = _version_row(db, file_id, version_number)
    if version is None:
        return None
    bumped = db.execute(
        update(models.PrintFileVersion)
        .where(models.PrintFileVersion.id == version.id)
        .values(downloads=models.PrintFileVersion.downloads + 1)
    )
    if bumped.rowcount == 0:
        db.rollback()
        return None
    db.execute(
        update(models.PrintFile)
        .where(models.PrintFile.id == file_id)
        .values(download_count=models.PrintFile.download_count + 1)
    )
    db.commit()
    db.refresh(version)
    return row, version


def record_step_download(
    db: Session, file_id: uuid.UUID, version_number: int | None
) -> tuple[models.PrintFile, models.PrintFileVersion] | None:
    """The STEP twin of the print download — same counting
    discipline, its own counters. None when that version
    carries no STEP file."""
    row = get_file(db, file_id)
    if row is None or row.status != "live":
        return None
    version = _version_row(db, file_id, version_number)
    if version is None or version.step_key is None:
        return None
    db.execute(
        update(models.PrintFileVersion)
        .where(models.PrintFileVersion.id == version.id)
        .values(step_downloads=models.PrintFileVersion.step_downloads + 1)
    )
    db.execute(
        update(models.PrintFile)
        .where(models.PrintFile.id == file_id)
        .values(step_download_count=models.PrintFile.step_download_count + 1)
    )
    db.commit()
    db.refresh(version)
    return row, version


def fetch_bytes(key: str) -> bytes:
    try:
        return storage.fetch(key)
    except StorageError as exc:
        raise PrintsError(f"The file couldn't be read: {exc}") from exc


# -- photo renditions at the read doors --------------------------------
#
# Cards and the detail gallery used to serve each photo's full
# original bytes (the live cover was 3.2 MB into a small card).
# These two helpers are the read side of renditions.py: the
# right-sized variant when one exists or can be generated, the
# original when it can't — a listing NEVER answers a broken
# image. Renditions are JPEG, so a served variant reports
# image/jpeg whatever the original's format was.

PREVIEW_SIZES = ("card", "display")


def preview_bytes(row: models.PrintFile, size: str = "card") -> tuple[bytes, str]:
    """The cover's bytes for the /preview door: the card
    rendition (320) by default — that's what the browse cards
    and the record header plate load — or the display
    rendition (1600) for the cover's big-preview modal."""
    width = (
        renditions.DISPLAY_WIDTH if size == "display" else renditions.CARD_WIDTH
    )
    data = renditions.rendition(row.preview_key, width)
    if data is not None:
        return data, "image/jpeg"
    return fetch_bytes(row.preview_key), row.preview_content_type or "image/png"


def media_photo_bytes(media: models.PrintMedia) -> tuple[bytes, str]:
    """One showcase PHOTO's bytes for the /media door: the
    display rendition (1600 on the long edge) — the gallery
    tiles and the viewer read here, and a bounded variant
    serves both honestly. The original when no rendition can
    be made. Videos never come through here (their bytes are
    the converted web rendition already, range-served)."""
    data = renditions.display(media.storage_key)
    if data is not None:
        return data, "image/jpeg"
    return fetch_bytes(media.storage_key), media.content_type or "image/png"


# -- ratings ------------------------------------------------------------


def rate_file(db: Session, user, file_id: uuid.UUID, stars: int) -> dict:
    row = get_live_file(db, file_id)
    if row.publisher_id == user.id:
        raise PrintsError("You can't rate your own file.")
    if not isinstance(stars, int) or stars < 1 or stars > 5:
        raise PrintsError("Ratings run from one to five stars.")
    existing = db.scalars(
        select(models.PrintRating).where(
            models.PrintRating.file_id == file_id,
            models.PrintRating.user_id == user.id,
        )
    ).first()
    if existing is None:
        db.add(
            models.PrintRating(file_id=file_id, user_id=user.id, stars=stars)
        )
        row.rating_sum += stars
        row.rating_count += 1
    else:
        row.rating_sum += stars - existing.stars
        existing.stars = stars
        existing.updated_at = _now()
    db.commit()
    db.refresh(row)
    view = _rating_view(row)
    view["my_rating"] = stars
    return view


# -- comments -----------------------------------------------------------


def comment_view(db: Session, row: models.PrintComment, viewer=None) -> dict:
    author = None if row.author_gone else core_service.get_user_by_id(db, row.author_id)
    gone = author is None or not author.is_active
    return {
        "id": row.id,
        "file_id": row.file_id,
        "author": {
            "user_id": row.author_id,
            "display_name": FORMER_MEMBER if gone else author.name,
            "account_number": "" if gone else author.account_number,
        },
        "body": "" if row.status != "live" else row.body,
        "status": row.status,
        "mine": viewer is not None and viewer.id == row.author_id,
        "edited_at": row.edited_at,
        "created_at": row.created_at,
    }


def list_comments(db: Session, file_id: uuid.UUID, viewer=None) -> list[dict]:
    """Conversation order (oldest first — the forum's reading
    shape). Removed comments stay as tombstones with their
    bodies hidden, so the thread of the conversation survives."""
    get_live_file(db, file_id)
    rows = list(
        db.scalars(
            select(models.PrintComment)
            .where(models.PrintComment.file_id == file_id)
            .order_by(models.PrintComment.created_at, models.PrintComment.id)
        ).all()
    )
    return [comment_view(db, row, viewer) for row in rows]


def add_comment(db: Session, user, file_id: uuid.UUID, body: str) -> dict:
    row = get_live_file(db, file_id)
    text = (body or "").strip()
    if not text:
        raise PrintsError("Write the comment first.")
    comment = models.PrintComment(
        file_id=row.id, author_id=user.id, body=text[:COMMENT_MAX]
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment_view(db, comment, user)


def get_comment(db: Session, comment_id: uuid.UUID) -> models.PrintComment | None:
    return db.get(models.PrintComment, comment_id)


def remove_comment(
    db: Session,
    actor,
    comment_id: uuid.UUID,
    *,
    reason: str = "",
    by_moderator: bool = False,
) -> dict:
    row = get_comment(db, comment_id)
    if row is None:
        raise PrintsNotFound("That comment isn't available.")
    if not by_moderator and row.author_id != actor.id:
        raise PrintsNotFound("That comment isn't available.")
    if row.status != "live":
        raise PrintsError("That comment has already been removed.")
    row.status = "removed_mod" if by_moderator else "removed_author"
    row.removed_reason = (reason or "").strip()[:REASON_MAX] or (
        "Removed by moderation." if by_moderator else "Removed by the author."
    )
    _action_reports(
        db, comment_id=row.id, resolution="Comment removed."
    )
    db.commit()
    db.refresh(row)
    _audit(
        db,
        actor,
        "prints.comment_remove",
        row.id,
        {"by_moderator": by_moderator},
    )
    return comment_view(db, row, actor)


# -- reports (flags) ----------------------------------------------------


def _report(
    db: Session,
    user,
    *,
    target_kind: str,
    file: models.PrintFile,
    comment: models.PrintComment | None,
    reason: str,
) -> models.PrintReport:
    existing = db.scalars(
        select(models.PrintReport).where(
            models.PrintReport.target_kind == target_kind,
            models.PrintReport.file_id == file.id,
            models.PrintReport.reporter_id == user.id,
            models.PrintReport.status == "open",
            models.PrintReport.comment_id == (comment.id if comment else None),
        )
    ).first()
    if existing is not None:
        raise PrintsError(
            "You've already flagged this — it's in the moderation queue."
        )
    row = models.PrintReport(
        target_kind=target_kind,
        file_id=file.id,
        comment_id=comment.id if comment else None,
        reporter_id=user.id,
        reason=(reason or "").strip()[:REASON_MAX],
    )
    db.add(row)
    db.flush()
    # A flag tells the whole moderation team (the forum's rule:
    # moderators, moderator admins AND god) — in the flag's own
    # commit, so the note can never announce a flag that didn't
    # land.
    label = "3D print comment" if target_kind == "comment" else "3D print file"
    inbox.notify_moderation_team(
        db,
        kind=inbox.KIND_COMMUNITY_FLAG,
        title=f"New flag: {label}",
        body=(
            f"{user.name} flagged a {label} on "
            f"“{file.title}”: {row.reason or 'no notes given'}"
        ),
        data={
            "surface": "prints",
            "report_id": str(row.id),
            "file_id": str(file.id),
            "comment_id": str(comment.id) if comment else "",
        },
        exclude_id=user.id,
    )
    db.commit()
    db.refresh(row)
    return row


def report_file(db: Session, user, file_id: uuid.UUID, reason: str) -> dict:
    row = get_file(db, file_id)
    if row is None:
        raise PrintsNotFound("That print file isn't available.")
    if row.status == "removed":
        raise PrintsError("That file has already been removed.")
    report = _report(
        db, user, target_kind="file", file=row, comment=None, reason=reason
    )
    return _report_view(db, report)


def report_comment(db: Session, user, comment_id: uuid.UUID, reason: str) -> dict:
    comment = get_comment(db, comment_id)
    if comment is None:
        raise PrintsNotFound("That comment isn't available.")
    if comment.status != "live":
        raise PrintsError("That comment has already been removed.")
    file = get_file(db, comment.file_id)
    if file is None:
        raise PrintsNotFound("That print file isn't available.")
    report = _report(
        db, user, target_kind="comment", file=file, comment=comment, reason=reason
    )
    return _report_view(db, report)


def _report_view(db: Session, row: models.PrintReport) -> dict:
    file = get_file(db, row.file_id)
    comment = get_comment(db, row.comment_id) if row.comment_id else None
    reporter = core_service.get_user_by_id(db, row.reporter_id)
    return {
        "id": row.id,
        "target_kind": row.target_kind,
        "file_id": row.file_id,
        "file_title": file.title if file is not None else "",
        "file_status": file.status if file is not None else "",
        "comment_id": row.comment_id,
        "comment_status": comment.status if comment is not None else "",
        "comment_excerpt": (
            comment.body[:200] if comment is not None and comment.status == "live" else ""
        ),
        "comment_author_id": comment.author_id if comment is not None else None,
        "reporter_id": row.reporter_id,
        "reporter_name": reporter.name if reporter is not None else "",
        "reason": row.reason,
        "status": row.status,
        "resolution": row.resolution,
        "resolved_by_id": row.resolved_by_id,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
    }


def list_reports(db: Session, status: str = "open") -> list[dict]:
    rows = list(
        db.scalars(
            select(models.PrintReport)
            .where(models.PrintReport.status == status)
            .order_by(models.PrintReport.created_at)
        ).all()
    )
    return [_report_view(db, row) for row in rows]


def dismiss_report(
    db: Session, actor, report_id: uuid.UUID, resolution: str = ""
) -> dict:
    row = db.get(models.PrintReport, report_id)
    if row is None:
        raise PrintsNotFound("That report isn't available.")
    row.status = "dismissed"
    row.resolution = (resolution or "")[:REASON_MAX]
    row.resolved_by_id = actor.id
    row.resolved_at = _now()
    db.commit()
    _audit(db, actor, "prints.report_dismiss", row.file_id, {"report_id": str(row.id)})
    return _report_view(db, row)


def _action_reports(
    db: Session,
    *,
    file_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    resolution: str,
) -> None:
    """Close every open report on a target that was just
    actioned (the forum's _action_reports rule: an open report
    must never dangle after its target is gone)."""
    stmt = select(models.PrintReport).where(
        models.PrintReport.status == "open"
    )
    if comment_id is not None:
        stmt = stmt.where(models.PrintReport.comment_id == comment_id)
    elif file_id is not None:
        stmt = stmt.where(
            models.PrintReport.file_id == file_id,
            models.PrintReport.target_kind == "file",
        )
    for report in db.scalars(stmt).all():
        report.status = "actioned"
        report.resolution = resolution
        report.resolved_at = _now()


# -- maker profile links ------------------------------------------------


def _clean_url(value: str) -> str:
    url = (value or "").strip()
    if not url or len(url) > 500:
        raise PrintsError("That link doesn't look right.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PrintsError(
            "Profile links must be full web addresses (https://…)."
        )
    return url


def list_links(db: Session, user_id: uuid.UUID) -> list[models.PrintMakerLink]:
    return list(
        db.scalars(
            select(models.PrintMakerLink)
            .where(models.PrintMakerLink.user_id == user_id)
            .order_by(models.PrintMakerLink.sort_order, models.PrintMakerLink.created_at)
        ).all()
    )


def link_view(row: models.PrintMakerLink) -> dict:
    return {"id": row.id, "label": row.label, "url": row.url}


def create_link(db: Session, user, *, label: str, url: str) -> dict:
    label = (label or "").strip()
    if not label:
        raise PrintsError("Give the link a label — the site's name works.")
    row = models.PrintMakerLink(
        user_id=user.id,
        label=label[:80],
        url=_clean_url(url),
        sort_order=len(list_links(db, user.id)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return link_view(row)


def update_link(
    db: Session, user, link_id: uuid.UUID, *, label: str, url: str
) -> dict:
    row = db.get(models.PrintMakerLink, link_id)
    if row is None or row.user_id != user.id:
        raise PrintsNotFound("That link isn't available.")
    label = (label or "").strip()
    if not label:
        raise PrintsError("Give the link a label — the site's name works.")
    row.label = label[:80]
    row.url = _clean_url(url)
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return link_view(row)


def delete_link(db: Session, user, link_id: uuid.UUID) -> None:
    row = db.get(models.PrintMakerLink, link_id)
    if row is None or row.user_id != user.id:
        raise PrintsNotFound("That link isn't available.")
    db.delete(row)
    db.commit()


# -- account deletion (the core cascade's prints pass) ------------------


def tombstone_author(db: Session, user_id: uuid.UUID) -> None:
    """The cascade's prints pass (the forum posture): the
    member's files come off the shelf under a Former-member
    tombstone, their comments stay as tombstones, and their
    own ratings / reports / maker links — their paperwork —
    go with the account. Rating aggregates on OTHER members'
    files are repaired in the same pass."""
    rated = list(
        db.scalars(
            select(models.PrintRating).where(models.PrintRating.user_id == user_id)
        ).all()
    )
    for rating in rated:
        file = get_file(db, rating.file_id)
        if file is not None and file.rating_count > 0:
            file.rating_sum -= rating.stars
            file.rating_count -= 1
        db.delete(rating)
    db.query(models.PrintReport).filter(
        models.PrintReport.reporter_id == user_id
    ).delete(synchronize_session=False)
    db.query(models.PrintMakerLink).filter(
        models.PrintMakerLink.user_id == user_id
    ).delete(synchronize_session=False)
    db.query(models.PrintComment).filter(
        models.PrintComment.author_id == user_id
    ).update(
        {models.PrintComment.author_gone: True}, synchronize_session=False
    )
    db.query(models.PrintFile).filter(
        models.PrintFile.publisher_id == user_id
    ).update(
        {
            models.PrintFile.publisher_gone: True,
            models.PrintFile.status: "removed",
            models.PrintFile.removed_reason: "Publisher account closed.",
            models.PrintFile.removed_at: _now(),
        },
        synchronize_session=False,
    )
    db.commit()
