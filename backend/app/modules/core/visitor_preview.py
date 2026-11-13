"""The visitor stand-in for "View as visitor" previews
(Sweep D5, 2026-11-12).

The preview's honesty rule: a page previewed "as a visitor"
renders from the SAME serializers a real non-owner's request
runs, shaped by a viewer who is a signed-in member with NO
relationship to the record — never the owner's payload with
the owner furniture hidden. This module is that viewer: a
stand-in carrying the nil id (an id no account can hold), so
every viewer-keyed lookup the serializers already perform —
ownership flags, my-rating, personal layers, preferred
agents, roster rows, posting rights — resolves exactly as it
does for a member who has never touched the record, and every
viewer-keyed WRITE seat stays shut because the id owns
nothing.

Only the attributes the serializers read are provided. The
stand-in is never persisted, never authenticated as, and
never reaches a write path: preview routes are GET-only and
gate on the CALLER's real ownership/management first.
"""

import types
import uuid

#: The id no account can hold (the nil UUID is never minted
#: for a user row) — every "mine" test against it is False
#: and every per-viewer lookup keyed on it comes back empty.
VISITOR_ID = uuid.UUID(int=0)


def visitor_viewer() -> types.SimpleNamespace:
    """A viewer-shaped stand-in for a signed-in member with
    no relationship to the record being previewed: no account
    types (no dealer seat, no posting rights), no tier, no
    operator powers, an empty name."""
    return types.SimpleNamespace(
        id=VISITOR_ID,
        account_types=[],
        name="",
        tier=None,
        role="user",
        is_operator=False,
        beta_tester=False,
        currency="USD",
    )
