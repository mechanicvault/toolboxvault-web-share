"""COPY-PASTE TEMPLATE — service.py.

The module's business logic AND its public interface to other modules.

Two jobs, one file, one rule:
  - Internal helpers and DB writes for THIS module's tables live here.
  - Functions other modules are allowed to call are the module's SERVICE
    INTERFACE: keep their names/signatures stable, and bump the manifest
    `version` whenever you change them. Declared consumers are listed in
    their manifests' `dependencies`, so the blast radius is visible.

Other modules import from HERE (e.g. `from app.modules.inventory.service
import get_item_summary`). They never import this module's models or routes.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules._template import models, schemas


def ping() -> schemas.PingResponse:
    return schemas.PingResponse(ok=True, module="template")


def list_examples(db: Session) -> list[schemas.ExampleItem]:
    rows = db.scalars(select(models.ExampleItem).order_by(models.ExampleItem.id))
    return [schemas.ExampleItem.model_validate(row) for row in rows]
