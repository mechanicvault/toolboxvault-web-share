"""Agent codes (owner model, 2026-11-03): every user-entered
private agent record carries ONE code, a property of the record
itself. The owner hands the code to their real-world agent; the
agent enters it after signing up and asks to take over the
record; the owner accepts; the account merges onto the record
and inherits everything hung off it (claims, truck account,
route facts — all of which reference the record, never the
code).

Format: eight characters from an unambiguous alphabet (no
0/O/1/I/L — a code read over the phone or off a photo must
survive transcription), displayed grouped as XXXX-XXXX. Entry
normalizes case, spaces and dashes away, so the grouped and
ungrouped forms are the same code. The space is ~31^8 — the
code is a capability, and the takeover flow still requires the
owner's explicit acceptance, so possession alone grants
nothing; entry is rate-limited on top (dealers routes).
"""

import secrets

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_agent_code() -> str:
    """One fresh code (not yet uniqueness-checked)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_agent_code(raw: str | None) -> str:
    """What a typed/pasted code means: uppercased, with spaces
    and dashes stripped. Anything outside the alphabet simply
    won't match a record — callers answer generically."""
    if not raw:
        return ""
    return "".join(
        ch for ch in str(raw).upper() if ch not in " -\t"
    )


def display_agent_code(code: str | None) -> str:
    """The grouped human form, XXXX-XXXX."""
    if not code:
        return ""
    return f"{code[:4]}-{code[4:]}" if len(code) == CODE_LENGTH else code
