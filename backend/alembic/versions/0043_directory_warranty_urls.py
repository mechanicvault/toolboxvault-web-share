"""Directory warranty-URL data-quality pass (completeness audit A12).

Five platform directory rows carried a warranty_url that did not
take a mechanic to the brand's warranty help — a Terms-of-Sale legal
page (Snap-on), a generic help index (Amazon), an unrelated
test-forms page (SUNEX), a generic support index (Wright) — or none
at all (Harbor Freight). These URLs also feed Locate Manual's
manufacturer candidate (warranty_url first, website fallback).

Each replacement below was verified 2026-10-22 against the brand's
OWN official site (per-fact citations in
goals/toolbox-vault-website/files/corporate-directory-data.json,
whose rows were updated in the same pass):

- Snap-on -> https://snapon.com/warranty-information — the first-
  party claim portal, linked verbatim from snapon.com's own footer
  ("WARRANTY INFORMATION"); the old Terms-of-Sale page links to it.
- Amazon -> the A-to-z Guarantee claims page (help nodeId 201809390)
  — Amazon's returns/warranty claims mechanism; the old node was a
  generic help index. Amazon publishes no manufacturer-style warranty
  hub (its own Warranty Policy states terms vary by manufacturer).
- SUNEX -> https://sunextools.com/pages/warranty-information — the
  warranty page in the site's own "Warranty & Returns" nav group.
- Wright -> https://wrighttool.com/pages/warranty — the dedicated
  warranty page in the site's own top nav.
- Harbor Freight -> their official Hand Tool Limited Lifetime
  Warranty PDF — HF publishes warranty terms only as per-category
  PDFs; hand tools are the category this directory exists for.

Deliberately NOT changed (verified, recorded in the A12 evidence):
Matco and Cornwell publish no standalone public warranty page
(Matco's is behind the SSO login wall; Cornwell's gated FAQ is
partner-filed), Lisle publishes none on its own domain, and Titan
remains absent (no official footprint verifiable) — those rows keep
their website fallback exactly as the original research left them.

Idempotent: plain UPDATEs scoped to platform rows (owner_id NULL)
matched by name. Downgrade restores the pre-pass values verbatim.

Revision ID: 0043_directory_warranty_urls
Revises: 0042_wave4
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_directory_warranty_urls"
down_revision: str | None = "0042_wave4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# name -> (value before this pass, value after)
_URLS: dict[str, tuple[str | None, str]] = {
    "Snap-on Incorporated": (
        "https://www.snapon.com/Terms-and-Conditions-of-Sale",
        "https://snapon.com/warranty-information",
    ),
    "Amazon.com": (
        "https://www.amazon.com/gp/help/customer/display.html?nodeId=201819200",
        "https://www.amazon.com/gp/help/customer/display.html?nodeId=201809390",
    ),
    "SUNEX Tools Inc.": (
        "https://sunextools.com/pages/test-forms",
        "https://sunextools.com/pages/warranty-information",
    ),
    "Wright Tool Company": (
        "https://wrighttool.com/support",
        "https://wrighttool.com/pages/warranty",
    ),
    "Harbor Freight Tools": (
        None,
        "https://www.harborfreight.com/media/catalog/product/w/a/warranty-hand-tools.pdf",
    ),
}


def _apply(values: dict[str, str | None]) -> None:
    bind = op.get_bind()
    for name, url in values.items():
        bind.execute(
            sa.text(
                "UPDATE dealer_companies SET warranty_url = :url"
                " WHERE owner_id IS NULL AND name = :name"
            ),
            {"url": url, "name": name},
        )


def upgrade() -> None:
    _apply({name: new for name, (_old, new) in _URLS.items()})


def downgrade() -> None:
    _apply({name: old for name, (old, _new) in _URLS.items()})
