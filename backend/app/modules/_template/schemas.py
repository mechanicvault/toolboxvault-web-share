"""COPY-PASTE TEMPLATE — schemas.py.

Request/response shapes (Pydantic v2). Routes validate input and serialize
output with these; service functions may also accept/return them.
"""

from pydantic import BaseModel, ConfigDict


class PingResponse(BaseModel):
    ok: bool
    module: str


class ExampleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
