"""Tool Expansion module tables (owner spec 2026-10-25).

The module itself is DERIVED — suggestions are computed from
inventory data (the community catalog's precedent), so nothing
about a suggestion is ever stored; since the 2026-10-26 scale
fix the derivation runs over a per-process pool snapshot that
writes invalidate (see service.py's header for the contract).
The only rows this module owns are the two user-control ledgers
Ryan specified:

- tool_expansion_dismissals — "move to archived matches" (the
  2026-11-10 main-tab model's name for the same row; the write
  began life as "remove this for me"): one user's choice to take
  one suggestion out of their Matches tab. Keyed to the VIEWER's
  own item (kind + id) and the suggested model number (normalized),
  because the same suggested model can expand two different items
  and the user may only want it gone from one of them. Other users
  are unaffected. Since lane 5 the ledger is READABLE by its owner
  (GET /tool-expansion/archived) and a row deletes back out via
  un-archive — the stored fact never changed, only its framing.

- tool_expansion_reports — "not relevant / inaccurate": one user's
  verdict on a MATCH — the (anchor model, suggested model) pairing,
  both normalized. When enough DISTINCT users have reported the
  same pairing (the kill threshold setting), the match stops
  generating for everyone. A reporter's own view hides the pairing
  immediately, below the threshold too.

Both ledgers are the user's own paperwork: they die with the
account (core's delete_account sweeps them, the same rule as the
marketplace reports a user filed).

te_pool_epoch is the pool snapshot's cross-process version
counter (scale fix follow-up, 2026-10-26): a single row whose
epoch is bumped INSIDE the same transaction as any pool-relevant
write (tool/battery/piece writes, contribution toggles), so every
API worker — not just the one that took the write — sees its
cached pool derivation is stale on the very next read.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PoolEpoch(Base):
    __tablename__ = "te_pool_epoch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class ExpansionDismissal(Base):
    __tablename__ = "tool_expansion_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "anchor_kind",
            "anchor_id",
            "suggested_model",
            name="uq_expansion_dismissal",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The viewer's own item the suggestion was tied to: tool|battery.
    anchor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    anchor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # The suggested piece's model number, normalized (service.norm_model).
    suggested_model: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExpansionReport(Base):
    __tablename__ = "tool_expansion_reports"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "anchor_model",
            "suggested_model",
            name="uq_expansion_report",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The match being judged: the shared model number that linked
    # the viewer's item to the source set, and the suggested piece's
    # model number — both normalized (service.norm_model).
    anchor_model: Mapped[str] = mapped_column(String(200), nullable=False)
    suggested_model: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
