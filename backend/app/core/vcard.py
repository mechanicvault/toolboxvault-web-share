"""vCard (.vcf) build + parse — the contact-card format library
(contact cards lane, 2026-11-07).

Pure format code: no module data lives here. The borrowing
module builds borrower cards and parses imports through this
file; the dealers module builds agent cards through it. One
implementation of the format, two callers.

BUILD: vCard 3.0, CRLF line endings, values escaped, long lines
folded at 75 octets (the shape phone contacts apps — iOS,
Android/Google Contacts, Outlook — all accept).

PARSE: deliberately forgiving, because real-world cards are
messy: 2.1 / 3.0 / 4.0 cards, folded lines, quoted-printable
values with declared charsets, grouped properties
(item1.EMAIL), tel:/mailto: URI values, extra fields the site
has no home for (ignored — never surfaced anywhere they don't
belong). A card with no name anywhere (no FN, no usable N, no
ORG) is reported as an error entry, never guessed at.

Caps (generous but real): MAX_FILE_BYTES per import file,
MAX_CARDS per file. Callers enforce them; the numbers live
here so the preview and the confirm agree.
"""

import quopri
import re

MAX_FILE_BYTES = 2_000_000  # ~2 MB — thousands of ordinary cards
MAX_CARDS = 500

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# A run of phone-ish characters holding at least 7 digits:
# starts with a digit or +, ends with a digit, allows the usual
# separators in between.
_PHONE_RUN_RE = re.compile(r"\+?\d[\d\s().\-–—]{4,}\d")


# ----------------------------------------------------------------------
# Building
# ----------------------------------------------------------------------


def _escape(value: str) -> str:
    """vCard 3.0 text escaping: backslash first, then the
    structural characters and newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold(line: str) -> str:
    """Fold one logical line to <=75-octet physical lines
    (CRLF + single space continuation), per RFC 2425."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    budget = 75
    rest = line
    while rest:
        chunk = rest.encode("utf-8")[:budget]
        # Never split a multi-byte character.
        while True:
            try:
                text = chunk.decode("utf-8")
                break
            except UnicodeDecodeError:
                chunk = chunk[:-1]
        parts.append(text)
        rest = rest[len(text):]
        budget = 74  # continuation lines spend one octet on the space
    return "\r\n ".join(parts)


def build_vcard(
    *,
    name: str,
    phones: list[str] | None = None,
    emails: list[str] | None = None,
    org: str = "",
    note: str = "",
) -> str:
    """One vCard 3.0 card as text (CRLF endings, trailing CRLF).

    N is derived from the display name best-effort (last word =
    family name) so strict importers that key off N still file
    the contact properly."""
    name = (name or "").strip()
    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    words = name.split()
    if len(words) >= 2:
        lines.append(f"N:{_escape(words[-1])};{_escape(' '.join(words[:-1]))};;;")
    elif words:
        lines.append(f"N:;{_escape(words[0])};;;")
    lines.append(f"FN:{_escape(name)}")
    for phone in phones or []:
        phone = phone.strip()
        if phone:
            lines.append(f"TEL;TYPE=CELL:{_escape(phone)}")
    for email in emails or []:
        email = email.strip()
        if email:
            lines.append(f"EMAIL;TYPE=INTERNET:{_escape(email)}")
    if org.strip():
        lines.append(f"ORG:{_escape(org.strip())}")
    if note.strip():
        lines.append(f"NOTE:{_escape(note.strip())}")
    lines.append("END:VCARD")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def build_vcard_file(cards: list[str]) -> str:
    """A .vcf file body: the cards concatenated."""
    return "".join(cards)


def download_filename(name: str, fallback: str = "contact") -> str:
    """A safe .vcf download filename from a contact's name:
    'Neighbor Nate' -> 'neighbor-nate.vcf'."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return f"{slug or fallback}.vcf"


def split_contact_text(text: str) -> tuple[list[str], list[str], str]:
    """Best-effort split of a free-text contact string (the
    address book's contact field: "a phone, an email, 'the guy
    at the marina' — whatever the owner typed") into
    (phones, emails, leftover).

    Emails come out by regex (the same pattern the nudge surface
    uses). Phone runs (>=7 digits among phone separators) come
    out next. Whatever text remains is the leftover — callers
    preserve it (note) rather than dropping it."""
    text = (text or "").strip()
    if not text:
        return [], [], ""
    emails = _EMAIL_RE.findall(text)
    rest = _EMAIL_RE.sub(" ", text)
    phones: list[str] = []
    for match in _PHONE_RUN_RE.finditer(rest):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        if len(digits) >= 7:
            phones.append(candidate)
    rest = _PHONE_RUN_RE.sub(" ", rest)
    leftover = re.sub(r"[\s,;·|/]+", " ", rest).strip(" ,;·-|/")
    return phones, emails, leftover


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


def _decode_bytes(data: bytes) -> str:
    """File bytes -> text. UTF-8 (with or without BOM) first —
    the modern producers; Windows-1252 as the fallback for the
    older desktop producers that never declared a charset."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _logical_lines(text: str) -> list[str]:
    """Physical lines -> logical property lines: standard
    unfolding (a line starting with space/tab continues the
    previous one, minus its first character) plus the
    quoted-printable soft-break join (a QP value's lines end
    with '=' and continue on the next physical line raw)."""
    physical = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    logical: list[str] = []
    for raw in physical:
        if raw[:1] in (" ", "\t") and logical:
            logical[-1] += raw[1:]
            continue
        if logical:
            prev = logical[-1]
            header = prev.split(":", 1)[0].upper()
            if "QUOTED-PRINTABLE" in header and prev.endswith("="):
                logical[-1] = prev[:-1] + raw
                continue
        logical.append(raw)
    return logical


def _decode_qp(value: str, charset: str) -> str:
    """A quoted-printable value -> text. QP payloads are pure
    ASCII by definition, so the detour through bytes is safe;
    the declared charset names the result's encoding (UTF-8
    default, Windows-1252 the usual fallback)."""
    try:
        raw = quopri.decodestring(value.encode("latin-1", errors="replace"))
    except Exception:
        return value
    for encoding in (charset or "utf-8", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _unescape(value: str) -> str:
    """Reverse vCard text escaping (\\n, \\, \\;, \\\\)."""
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in ("n", "N"):
                out.append("\n")
            elif nxt in (",", ";", "\\"):
                out.append(nxt)
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _split_unescaped(value: str, sep: str) -> list[str]:
    """Split on a separator that isn't backslash-escaped."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            current.append(value[i:i + 2])
            i += 2
        elif char == sep:
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    parts.append("".join(current))
    return parts


class ParsedCard(dict):
    """One parsed card: {name, phones, emails, org, note} —
    or, when the card can't yield a contact, {error}."""


def _parse_card(lines: list[str]) -> ParsedCard:
    props: dict[str, list[str]] = {}
    for line in lines:
        if ":" not in line:
            continue
        header, value = line.split(":", 1)
        segments = header.split(";")
        raw_name = segments[0].strip().upper()
        # Grouped properties: item1.EMAIL -> EMAIL.
        prop = raw_name.rsplit(".", 1)[-1]
        params: dict[str, str] = {}
        bare_types: list[str] = []
        for segment in segments[1:]:
            if "=" in segment:
                key, val = segment.split("=", 1)
                params[key.strip().upper()] = val.strip()
            elif segment.strip():
                bare_types.append(segment.strip().upper())
        if params.get("ENCODING", "").upper() in (
            "QUOTED-PRINTABLE",
            "QUOTED_PRINTABLE",
        ):
            value = _decode_qp(value, params.get("CHARSET", "utf-8"))
        props.setdefault(prop, []).append(value.strip())

    def first(prop: str) -> str:
        values = props.get(prop) or []
        return _unescape(values[0]) if values else ""

    def all_values(prop: str) -> list[str]:
        return [_unescape(v) for v in props.get(prop) or []]

    name = first("FN")
    if not name and props.get("N"):
        parts = [_unescape(p) for p in _split_unescaped(props["N"][0], ";")]
        parts += [""] * (5 - len(parts))
        family, given, additional, prefix, suffix = parts[:5]
        name = " ".join(
            p for p in (prefix, given, additional, family, suffix) if p.strip()
        ).strip()
    org = first("ORG")
    if not name:
        name = org
    if not name:
        return ParsedCard(error="no_name")

    phones: list[str] = []
    for raw in all_values("TEL"):
        value = raw.strip()
        if value.lower().startswith("tel:"):
            value = value[4:]
        if value and value not in phones:
            phones.append(value)
    emails: list[str] = []
    for raw in all_values("EMAIL"):
        value = raw.strip()
        if value.lower().startswith("mailto:"):
            value = value[7:]
        if value and value not in emails:
            emails.append(value)
    note = first("NOTE")
    return ParsedCard(
        name=name,
        phones=phones,
        emails=emails,
        org=org if org != name else "",
        note=note,
    )


def parse_vcf(data: bytes) -> tuple[list[ParsedCard], int]:
    """A whole .vcf file -> (cards, total_found).

    cards holds one entry per card found (successful parses and
    {error} entries alike, in file order). total_found counts
    every BEGIN:VCARD seen, so callers can say honestly when a
    file carried more cards than the cap let through."""
    text = _decode_bytes(data)
    cards: list[ParsedCard] = []
    total = 0
    current: list[str] | None = None
    for line in _logical_lines(text):
        marker = line.strip().upper()
        if marker == "BEGIN:VCARD":
            if current is not None:
                # A new BEGIN closes a card whose END went missing.
                total += 1
                if len(cards) < MAX_CARDS:
                    cards.append(_parse_card(current))
            current = []
        elif marker == "END:VCARD":
            if current is not None:
                total += 1
                if len(cards) < MAX_CARDS:
                    cards.append(_parse_card(current))
                current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        total += 1
        if len(cards) < MAX_CARDS:
            cards.append(_parse_card(current))
    return cards, total
