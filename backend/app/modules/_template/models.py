"""COPY-PASTE TEMPLATE — models.py.

This module's tables. ONLY this module's service.py may write to these
tables. Other modules read this module's data through service.py functions,
never by importing these models.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ExampleItem(Base):
    """Replace with your module's real tables."""

    __tablename__ = "template_example_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
