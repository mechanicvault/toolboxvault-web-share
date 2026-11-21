"""Phone number display formatting (core).

PHONE STANDARD: every phone
number a user READS renders in the 10-digit form "111-222-3333".

`format_phone` in this module is THE backend formatter — the
twin of the frontend's one helper (frontend/src/lib/format.ts,
`formatPhone`, same rule, mirrored semantics). Server-rendered
documents (PDFs, report exports, generated text a human reads)
route every phone value through it; never print a raw phone
field into a document again.

The rule is deliberately narrow so it can never mangle a number
it doesn't recognize:
  - the value must consist ONLY of digits and phone punctuation
    (spaces, dashes, parens, dots, one leading "+"); any letter
    or other character → returned EXACTLY as stored;
  - exactly 10 digits → "111-222-3333";
  - exactly 11 digits starting with "1" → the leading 1 drops,
    same rendering;
  - anything else (7-digit locals, extensions that survived the
    character gate, international numbers) → EXACTLY as stored.

Display only: the stored value is never rewritten. Data
payloads (API responses, vCards, account data exports) are NOT
display and keep the stored value — this module is for rendered
documents only.
"""

import re

# ASCII digits only, mirroring the frontend regex's \d.
_PHONE_CHARS = re.compile(r"\+?[0-9\s().-]+")
_NON_DIGITS = re.compile(r"[^0-9]")


def format_phone(value: str | None) -> str:
    """Render a stored phone value for a human reader.

    None/empty → "". A clean 10-digit US number (or an 11-digit
    one with a leading country-code 1) renders "111-222-3333";
    anything else returns byte-identical to what was stored.
    """
    if not value:
        return ""
    if not _PHONE_CHARS.fullmatch(value.strip()):
        return value
    digits = _NON_DIGITS.sub("", value)
    if len(digits) == 10:
        ten = digits
    elif len(digits) == 11 and digits.startswith("1"):
        ten = digits[1:]
    else:
        return value
    return f"{ten[:3]}-{ten[3:6]}-{ten[6:]}"
