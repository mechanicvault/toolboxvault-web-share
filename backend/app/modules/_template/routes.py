"""COPY-PASTE TEMPLATE — routes.py.

The HTTP layer ONLY: parse input, call service functions, shape output.
No business logic here, no SQL here. If a route is getting clever, the
cleverness belongs in service.py.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules._template import schemas, service

router = APIRouter()


@router.get("/ping", response_model=schemas.PingResponse)
def ping() -> schemas.PingResponse:
    """Smoke-test route proving the module is wired up."""
    return service.ping()


@router.get("/example", response_model=list[schemas.ExampleItem])
def list_examples(db: Session = Depends(get_db)) -> list[schemas.ExampleItem]:
    """Example read route: route -> service -> schemas. No SQL here."""
    return service.list_examples(db)
