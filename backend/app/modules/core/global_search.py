"""Global search (owner spec, 2026-10-25): the header search bar
searches the user's OWN records, everywhere — "shouldnt say search
tools, it should just say search. This search bar should search
everywhere and everything."

One endpoint, GET /api/core/search?q=…, answering grouped results:
one group per kind of record (Inventory, Parts, Wishlist, Dealers,
People, …), each result carrying enough of the record to recognize
it plus the deep link to that record (the same destinations the
notification click-through work resolved in inbox_links).

Rules, all enforced here on the server:

  - OWN DATA ONLY. Every family query is scoped to the caller
    (owner_id / participant / either side of a truck account).
  - MODULE SWITCHES APPLY. A family contributes results only when
    its feature module is effective for the caller WITH the
    per-user layer (module_control.visible_module_ids) — the same
    set the nav shows. A module the user switched off contributes
    nothing, exactly as everywhere else.
  - FORUMS ARE EXCLUDED, ENTIRELY (owner, 2026-10-25): "the only
    thing this search bar should not search is the forums. That
    search should be its own beast." The forum keeps its own
    in-forum search (/api/forum/search); no forum table is read
    here. The community catalog pool and the feedback boards are
    likewise left out — shared/community surfaces, not the user's
    own records (the catalog is a lookup, not a record the user
    owns; feedback is a public board like the forum). ONE ordered
    exception (owner order, 2026-11-08): the 3D print files
    shelf IS in this search, in its own group — the Downloads
    Part 2 spec names the main search as one of its surfaces,
    and the shelf is public by design (see _prints).
  - SHARED TOOLS have no group of their own: the underlying
    records are tools/batteries — the user's own appear under
    Inventory, and a peer's items are that peer's records, not
    the caller's.

Matching is deliberately loose (owner's acceptance example: the
word "ratchet" must find a borrower named "Ratched", a note on a
dealer, a wishlist item, and inventory ratchets): the query splits
into words, and a record matches when EVERY word appears as a
case-insensitive substring somewhere in the record's text — names,
descriptions, notes, and the other text the record carries — with
one tolerance on top: a record word that is a near-prefix twin of
the query word (all but the last letter shared, five letters or
more) also counts, which is what carries "ratchet" → "Ratched"
(see _term_hits). Notes attached to anything are searchable text;
the result is the record carrying the note.

Each group reports its TRUE total and shows at most GROUP_CAP
results (Ryan's readings: a normal search returns everything; the
cap only bites on pathological queries).

STATUSES (busy work #2, owner order 2026-11-10): a result whose
record HAS a status carries it in the payload — resolved HERE,
on the server, from the record itself (never re-derived in the
browser): the claim's ladder word (a warranty claim under its
closed layer reads Closed), the loan's state with overdue
computed by the borrowing service's own is_overdue, the item's
one primary status composed exactly as the item page's header
pill composes it, and so on per family (the per-family mapping
is recorded in the lane INDEX). The payload carries the status's
dictionary key + the module's pill tone; the client renders the
shared Badge with the module's own word in the reader's locale.
A family whose records have no meaningful status (parts,
dealers, people, messages, the prints shelf — every print result
is live by construction) carries none; statuses are never
invented. The sub-reads an item's status composes from (loans,
claims, listings) honor the same module visibility the families
themselves are gated on, exactly as the item page's best-effort
reads do.
"""

import re
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.borrowing import models as borrowing_models
from app.modules.claims import models as claims_models
from app.modules.core import models as core_models
from app.modules.core import module_control
from app.modules.dealers import models as dealers_models
from app.modules.inventory import models as inventory_models
from app.modules.maintenance import models as maintenance_models
from app.modules.marketplace import models as marketplace_models
from app.modules.messaging import models as messaging_models
from app.modules.parts import models as parts_models
from app.modules.support import models as support_models
from app.modules.truck_accounts import models as truck_models
from app.modules.wishlist import models as wishlist_models

router = APIRouter()

GROUP_CAP = 25

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


# -- matching -----------------------------------------------------


def _terms(q: str) -> list[str]:
    return [t.lower() for t in q.split() if t]


def _custom_values(custom_data: dict | None) -> list[str]:
    """The searchable text inside a custom_data JSONB blob: every
    string value (and string inside a list value)."""
    out: list[str] = []
    for value in (custom_data or {}).values():
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            out.extend(v for v in value if isinstance(v, str))
    return out


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _term_hits(term: str, haystack: str, words: list[str]) -> bool:
    """One query word against a record's text. A plain substring
    hit is the main rule; on top of that, a word of the record
    counts when it is a near-prefix twin of the query word —
    sharing all but (at most) the last letter, for words of five
    letters or more. That tolerance is what makes "ratchet" find
    the borrower named "Ratched" (and "sockets" find "socket")
    without opening the door to edit-distance fuzz: the cost of a
    rare extra result in your own data is low, the cost of NOT
    finding the record you typed is the failure this search
    exists to fix."""
    if term in haystack:
        return True
    if len(term) < 5:
        return False
    for word in words:
        if len(word) < 5:
            continue
        if _common_prefix_len(term, word) >= min(len(term), len(word)) - 1:
            return True
    return False


def _hit(terms: list[str], fields: list[str]) -> bool:
    """Every query word appears somewhere in the record's text."""
    haystack = "\n".join(f for f in fields if f).lower()
    words = [w for w in _WORD_SPLIT.split(haystack) if w]
    return all(_term_hits(term, haystack, words) for term in terms)


def _excerpt(terms: list[str], texts: list[str]) -> str:
    """A window of the first long text that actually contains a
    query word — how a note/description match shows itself, so the
    user can see WHY the record matched. Empty when the match
    lives in short fields (name, brand, …) that the title/detail
    already show."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower()
        positions = [lowered.find(term) for term in terms if term in lowered]
        if not positions:
            continue
        start = max(0, min(positions) - 60)
        end = min(len(text), min(positions) + 100)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        return snippet
    return ""


def _status(key: str, tone: str) -> dict:
    """One result's status, resolved server-side: the module's
    dictionary key for its own status word + the pill tone the
    module itself gives that state. The client renders the shared
    Badge from these two facts and nothing else."""
    return {"key": key, "tone": tone}


def _result(
    record_id,
    kind: str,
    title: str,
    detail: str,
    excerpt: str,
    link: str,
    photo: dict | None = None,
    status: dict | None = None,
) -> dict:
    return {
        "id": str(record_id),
        "kind": kind,
        "title": title,
        "detail": detail,
        "excerpt": excerpt,
        "link": link,
        # Item thumbnail data (inventory group only): the primary
        # photo's rendition URLs, or None — the client paints the
        # shared no-photo placeholder for None.
        "photo": photo,
        # The record's status (busy work #2), or None for the
        # families whose records carry no meaningful status.
        "status": status,
    }


def _group(key: str, results: list[dict]) -> dict | None:
    if not results:
        return None
    return {"key": key, "total": len(results), "results": results[:GROUP_CAP]}


# -- families -----------------------------------------------------


# The claims module's pill tones (frontend claims/format
# STATUS_TONES), mirrored: the search payload ships the tone the
# claim's own surfaces give the state.
_CLAIM_TONES = {
    "draft": "neutral",
    "filed": "accent",
    "in_review": "warning",
    "approved": "success",
    "denied": "danger",
    "paid": "success",
    "closed": "neutral",
    "not_reported": "warning",
    "reported": "accent",
    "waiting_on_agent": "neutral",
    "waiting_on_parts": "warning",
    "in_repair": "warning",
    "agent_has_tool": "accent",
    "completed": "success",
    "backordered": "danger",
}


def _claim_status(claim) -> dict:
    """A claim's search status, in the claims module's own words:
    the ladder status — except a warranty claim under its closed
    layer (closed_at stamped), which reads Closed, exactly as
    the module shelves it in Repair history with the ladder
    untouched underneath. Insurance claims close AS a status, so
    their ladder word already says it."""
    if claim.kind == claims_models.KIND_WARRANTY and claim.closed_at is not None:
        return _status("claims.status.closed", _CLAIM_TONES["closed"])
    return _status(
        f"claims.status.{claim.status}",
        _CLAIM_TONES.get(claim.status, "neutral"),
    )


def _item_statuses(
    db: Session,
    user: CurrentUser,
    visible: set[str],
    matched: list[tuple[str, object]],
) -> dict[tuple[str, uuid.UUID], dict]:
    """The inventory rows' ONE primary status each, composed
    server-side with the SAME precedence the item page's header
    pill uses (ItemStatusPill): Lost > Stolen > Broken (Sent out
    when its open warranty claim is already in repair) > Sent out
    > Sold > Replaced > Checked out (red when overdue) > For sale
    > Available. The sub-reads are batched and gated on the same
    module visibility the search families answer to — a module
    that isn't effective for the caller contributes nothing,
    exactly as the item page's best-effort reads behave."""
    from app.modules.borrowing import service as borrowing_service

    if not matched:
        return {}
    ids = [item.id for _, item in matched]
    checkouts: dict[tuple[str, uuid.UUID], object] = {}
    if "borrowing" in visible:
        for row in db.scalars(
            select(borrowing_models.Checkout).where(
                borrowing_models.Checkout.owner_id == user.id,
                borrowing_models.Checkout.item_id.in_(ids),
                borrowing_models.Checkout.state.in_(
                    (
                        borrowing_models.STATE_REQUESTED,
                        borrowing_models.STATE_CHECKED_OUT,
                    )
                ),
            )
        ):
            checkouts[(row.item_kind, row.item_id)] = row
    sent_out: set[tuple[str, uuid.UUID]] = set()
    if "claims" in visible:
        for line in db.scalars(
            select(claims_models.ClaimLine)
            .join(
                claims_models.Claim,
                claims_models.ClaimLine.claim_id == claims_models.Claim.id,
            )
            .where(
                claims_models.Claim.owner_id == user.id,
                claims_models.Claim.kind == claims_models.KIND_WARRANTY,
                claims_models.Claim.status == claims_models.STATUS_IN_REPAIR,
                claims_models.Claim.closed_at.is_(None),
                claims_models.ClaimLine.target_id.in_(ids),
            )
        ):
            # A set's lines target the set itself; the set IS the
            # tool row the search shows, so its kind seats as tool.
            kind = "battery" if line.target_kind == "battery" else "tool"
            sent_out.add((kind, line.target_id))
    for_sale: set[tuple[str, uuid.UUID]] = set()
    if "marketplace" in visible:
        for listing in db.scalars(
            select(marketplace_models.SaleListing).where(
                marketplace_models.SaleListing.owner_id == user.id,
                marketplace_models.SaleListing.status == "active",
                marketplace_models.SaleListing.source_id.in_(ids),
            )
        ):
            if listing.source_kind in ("tool", "battery"):
                for_sale.add((listing.source_kind, listing.source_id))
    out: dict[tuple[str, uuid.UUID], dict] = {}
    for item_kind, item in matched:
        key = (item_kind, item.id)
        standing = item.standing or "in_service"
        if standing == "lost":
            status = _status("inventory.status.lost", "neutral")
        elif standing == "stolen":
            status = _status("inventory.status.stolen", "danger")
        elif standing == "broken" and key in sent_out:
            status = _status("inventory.status.sentOut", "warning")
        elif standing == "broken":
            status = _status("inventory.status.broken", "danger")
        elif standing == "in_repair":
            status = _status("inventory.status.sentOut", "warning")
        elif standing == "sold":
            status = _status("inventory.status.sold", "success")
        elif standing == "replaced":
            status = _status("inventory.status.replaced", "neutral")
        else:
            checkout = checkouts.get(key)
            if checkout is not None and checkout.state == borrowing_models.STATE_CHECKED_OUT:
                status = _status(
                    "inventory.status.checkedOut",
                    "danger" if borrowing_service.is_overdue(checkout) else "accent",
                )
            elif key in for_sale:
                status = _status("inventory.status.forSale", "success")
            else:
                status = _status("inventory.status.available", "success")
        out[key] = status
    return out


def _inventory(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    # Lazy, like the dealers module's records builder: the
    # inventory service imports core's journal at module level.
    from app.modules.inventory import service as inv_service

    results: list[dict] = []
    tools = list(
        db.scalars(
            select(inventory_models.Tool).where(
                inventory_models.Tool.owner_id == user.id,
                # Retired (replaced) items are out of search —
                # history reads them, search doesn't (2026-10-25).
                inventory_models.Tool.standing.is_distinct_from("replaced"),
            )
        )
    )
    # Dealer names ride the tool tag (dealers module) — a match on
    # the dealer's name finds the tool, and the detail can show it.
    dealer_ids = {t.dealer_company_id for t in tools if t.dealer_company_id}
    dealer_names: dict[uuid.UUID, str] = {}
    if dealer_ids:
        dealer_names = {
            row.id: row.name
            for row in db.scalars(
                select(dealers_models.DealerCompany).where(
                    dealers_models.DealerCompany.id.in_(dealer_ids)
                )
            )
        }
        # Personal dealer edits (2026-11-05): the searcher finds
        # and reads his tools by HIS names for their dealers.
        from app.modules.dealers import service as dealers_service

        dealer_names.update(
            dealers_service.personal_name_map(db, user.id, dealer_ids)
        )
    # Set contents are part of a set's text (the inventory search's
    # own rule): a piece's part number / serial, or an attached
    # tool's name, finds the SET.
    set_ids = [t.id for t in tools if t.is_set]
    contents: dict[uuid.UUID, list[str]] = {}
    if set_ids:
        for piece in db.scalars(
            select(inventory_models.SetPiece).where(
                inventory_models.SetPiece.set_id.in_(set_ids)
            )
        ):
            contents.setdefault(piece.set_id, []).extend(
                [piece.name or "", piece.part_number or "", piece.serial_number or ""]
            )
        for attached in tools:
            if attached.attached_to_set_id in set_ids:
                contents.setdefault(attached.attached_to_set_id, []).extend(
                    [attached.name or "", attached.brand or "", attached.model or ""]
                )
    matched_tools = []
    for tool in tools:
        fields = [
            tool.name,
            tool.brand,
            tool.model,
            tool.serial_number,
            tool.condition,
            tool.category,
            tool.location,
            tool.size,
            tool.notes,
            tool.repair_problem,
            tool.warranty_provider,
            dealer_names.get(tool.dealer_company_id, ""),
            *(tool.model_numbers or []),
            *(tool.serial_numbers or []),
            *_custom_values(tool.custom_data),
            *contents.get(tool.id, []),
        ]
        if _hit(terms, fields):
            matched_tools.append(tool)
    statuses = _item_statuses(
        db, user, visible, [("tool", t) for t in matched_tools]
    )
    for tool in matched_tools:
        detail = " · ".join(p for p in (tool.brand, tool.model) if p)
        results.append(
            _result(
                tool.id,
                "tool",
                tool.name,
                detail,
                _excerpt(terms, [tool.notes, tool.repair_problem]),
                f"/inventory/{tool.id}",
                photo=inv_service.primary_photo_thumb(tool),
                status=statuses.get(("tool", tool.id)),
            )
        )
    batteries = list(
        db.scalars(
            select(inventory_models.Battery).where(
                inventory_models.Battery.owner_id == user.id,
                inventory_models.Battery.standing.is_distinct_from("replaced"),
            )
        )
    )
    matched_batteries = []
    for battery in batteries:
        fields = [
            battery.name,
            battery.brand,
            battery.model,
            battery.serial_number,
            battery.condition,
            battery.category,
            battery.location,
            battery.notes,
            battery.platform,
            battery.chemistry,
            battery.repair_problem,
            battery.warranty_provider,
            *_custom_values(battery.custom_data),
        ]
        if _hit(terms, fields):
            matched_batteries.append(battery)
    battery_statuses = _item_statuses(
        db, user, visible, [("battery", b) for b in matched_batteries]
    )
    for battery in matched_batteries:
        detail = " · ".join(p for p in (battery.brand, battery.model) if p)
        results.append(
            _result(
                battery.id,
                "battery",
                battery.name,
                detail,
                _excerpt(terms, [battery.notes, battery.repair_problem]),
                f"/inventory/batteries/{battery.id}",
                photo=inv_service.primary_photo_thumb(battery),
                status=battery_statuses.get(("battery", battery.id)),
            )
        )
    return results


def _parts(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    results: list[dict] = []
    for part in db.scalars(
        select(parts_models.Part).where(parts_models.Part.owner_id == user.id)
    ):
        fields = [
            part.title,
            part.notes,
            part.condition,
            part.make,
            part.model,
            part.engine,
            part.category,
            *_custom_values(part.custom_data),
        ]
        if _hit(terms, fields):
            detail = " · ".join(
                p
                for p in (
                    " ".join(
                        x
                        for x in (
                            str(part.year) if part.year else "",
                            part.make,
                            part.model,
                        )
                        if x
                    ),
                    part.category,
                )
                if p
            )
            results.append(
                _result(
                    part.id,
                    "part",
                    part.title,
                    detail,
                    _excerpt(terms, [part.notes]),
                    f"/parts/{part.id}",
                )
            )
    return results


def _wishlist(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    results: list[dict] = []
    for item in db.scalars(
        select(wishlist_models.WishlistItem).where(
            wishlist_models.WishlistItem.owner_id == user.id
        )
    ):
        if _hit(terms, [item.title, item.notes]):
            # The item's own status (wishlist models STATUSES):
            # wanted | purchased — Purchased wears the success
            # tone the Wishlist page's badge gives it.
            status = (
                _status("wishlist.status.purchased", "success")
                if item.status == "purchased"
                else _status("wishlist.status.wanted", "neutral")
            )
            results.append(
                _result(
                    item.id,
                    "wishlist_item",
                    item.title,
                    "",
                    _excerpt(terms, [item.notes]),
                    "/wishlist",
                    status=status,
                )
            )
    return results


def _dealers(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    results: list[dict] = []
    for company in db.scalars(
        select(dealers_models.DealerCompany).where(
            dealers_models.DealerCompany.owner_id == user.id
        )
    ):
        fields = [
            company.name,
            company.email,
            company.website,
            company.address,
            company.notes,
            company.warranty_phone or "",
            company.ship_to_name or "",
        ]
        if _hit(terms, fields):
            results.append(
                _result(
                    company.id,
                    "dealer",
                    company.name,
                    "",
                    _excerpt(terms, [company.notes]),
                    f"/dealers/{company.id}",
                )
            )
    for agent in db.scalars(
        select(dealers_models.PrivateAgent).where(
            dealers_models.PrivateAgent.owner_id == user.id
        )
    ):
        if _hit(terms, [agent.name, agent.phone, agent.email, agent.notes]):
            link = f"/dealers/{agent.company_id}" if agent.company_id else "/dealers"
            results.append(
                _result(
                    agent.id,
                    "agent",
                    agent.name,
                    "",
                    _excerpt(terms, [agent.notes]),
                    link,
                )
            )
    return results


def _people(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    results: list[dict] = []
    for contact in db.scalars(
        select(borrowing_models.BorrowerContact).where(
            borrowing_models.BorrowerContact.owner_id == user.id
        )
    ):
        if _hit(terms, [contact.name, contact.contact, contact.notes]):
            results.append(
                _result(
                    contact.id,
                    "person",
                    contact.name,
                    contact.contact,
                    _excerpt(terms, [contact.notes]),
                    "/borrowing",
                )
            )
    return results


# The borrowing module's state tones (frontend borrowing/format
# STATE_TONES), mirrored; overdue is the danger state the item
# pill and the Borrowing page both give a past-due loan.
_CHECKOUT_TONES = {
    "requested": "warning",
    "checked_out": "accent",
    "returned": "success",
    "declined": "danger",
    "cancelled": "neutral",
}


def _checkout_status(checkout) -> dict:
    """A loan's search status, in the borrowing module's own
    words (its STATE_LABELS): the state itself — except a loan
    still out past its due moment, which reads Overdue, computed
    by the borrowing service's own is_overdue (the Borrowing
    page's source of truth, not a second implementation)."""
    from app.modules.borrowing import service as borrowing_service

    if checkout.state == borrowing_models.STATE_CHECKED_OUT and (
        borrowing_service.is_overdue(checkout)
    ):
        return _status("borrowing.state.overdue", "danger")
    return _status(
        f"borrowing.state.{checkout.state}",
        _CHECKOUT_TONES.get(checkout.state, "neutral"),
    )


def _borrowing(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    """Loans on BOTH sides of the ledger (sweep B4, F5): the
    loans I made (owner side — the original family) and the loans
    I am the borrower on (another owner's rows naming me). A
    borrower-side loan is my record too — I am holding the item —
    so a search for the item, or for the owner who lent it, must
    find it instead of stopping at people and items. The detail
    column names the counterparty from the caller's seat: the
    borrower on my loans, the owner on loans to me."""
    rows = list(
        db.scalars(
            select(borrowing_models.Checkout).where(
                or_(
                    borrowing_models.Checkout.owner_id == user.id,
                    borrowing_models.Checkout.borrower_user_id == user.id,
                )
            )
        )
    )
    owner_names: dict[uuid.UUID, str] = {}
    other_owner_ids = {r.owner_id for r in rows if r.owner_id != user.id}
    if other_owner_ids:
        owner_names = {
            row.id: row.name
            for row in db.scalars(
                select(core_models.User).where(
                    core_models.User.id.in_(other_owner_ids)
                )
            )
        }
    results: list[dict] = []
    for checkout in rows:
        mine = checkout.owner_id == user.id
        counterparty = (
            checkout.borrower_name
            if mine
            else owner_names.get(checkout.owner_id, "")
        )
        fields = [
            checkout.item_name,
            checkout.borrower_name,
            checkout.borrower_contact,
            checkout.notes,
            counterparty,
        ]
        if _hit(terms, fields):
            results.append(
                _result(
                    checkout.id,
                    "checkout",
                    checkout.item_name,
                    counterparty,
                    _excerpt(terms, [checkout.notes]),
                    f"/borrowing?checkout={checkout.id}",
                    status=_checkout_status(checkout),
                )
            )
    return results


def _claims_by_kind(
    db: Session, user: CurrentUser, terms: list[str], kind: str
) -> list[dict]:
    """One claim KIND's search results (claims separation,
    2026-11-05): the claims group searches warranty claims only,
    the disaster_claims group insurance claims only — each result
    links into its own section, and neither group can surface
    the other kind."""
    disaster = kind == claims_models.KIND_INSURANCE
    claims = list(
        db.scalars(
            select(claims_models.Claim).where(
                claims_models.Claim.owner_id == user.id,
                claims_models.Claim.kind == kind,
            )
        )
    )
    if not claims:
        return []
    claim_ids = [c.id for c in claims]
    lines: dict[uuid.UUID, list[str]] = {}
    for line in db.scalars(
        select(claims_models.ClaimLine).where(
            claims_models.ClaimLine.claim_id.in_(claim_ids)
        )
    ):
        lines.setdefault(line.claim_id, []).extend(
            [line.target_name or "", line.set_name or ""]
        )
    comms: dict[uuid.UUID, list[str]] = {}
    for comm in db.scalars(
        select(claims_models.ClaimCommunication).where(
            claims_models.ClaimCommunication.claim_id.in_(claim_ids)
        )
    ):
        comms.setdefault(comm.claim_id, []).extend(
            [comm.contact or "", comm.summary or ""]
        )
    results: list[dict] = []
    for claim in claims:
        fields = [
            claim.claim_number,
            claim.insurer_name,
            claim.policy_number,
            claim.manufacturer_case_number,
            claim.agent_name,
            claim.incident_type,
            claim.description,
            claim.repair_sent_to,
            claim.police_report_number,
            claim.police_department,
            *lines.get(claim.id, []),
            *comms.get(claim.id, []),
        ]
        if _hit(terms, fields):
            title = f"Claim {claim.claim_number}" if claim.claim_number else "Claim"
            results.append(
                _result(
                    claim.id,
                    "disaster_claim" if disaster else "claim",
                    title,
                    claim.insurer_name if disaster else claim.dealer_name,
                    _excerpt(terms, [claim.description, *comms.get(claim.id, [])]),
                    f"/disaster-claims/{claim.id}"
                    if disaster
                    else f"/claims/{claim.id}",
                    status=_claim_status(claim),
                )
            )
    return results


def _claims(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    return _claims_by_kind(db, user, terms, claims_models.KIND_WARRANTY)


def _disaster_claims(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    return _claims_by_kind(db, user, terms, claims_models.KIND_INSURANCE)


def _item_link(db: Session, item_kind: str, item_id: uuid.UUID) -> str:
    """Maintenance records live on their item (the inbox's F_ITEM
    precedent): link to the item while it exists, else the Tool
    Maintenance tab of the merged Repairs & Maintenance page
    (merge, 2026-11-05) — never a dead end."""
    if item_kind == "battery":
        exists = db.scalar(
            select(inventory_models.Battery.id).where(
                inventory_models.Battery.id == item_id
            )
        )
        return (
            f"/inventory/batteries/{item_id}"
            if exists
            else "/repairs#tool-maintenance"
        )
    exists = db.scalar(
        select(inventory_models.Tool.id).where(inventory_models.Tool.id == item_id)
    )
    return f"/inventory/{item_id}" if exists else "/repairs#tool-maintenance"


# A schedule's due standing tones (frontend maintenance/format
# DUE_STATUS_TONES), mirrored.
_DUE_TONES = {
    "overdue": "danger",
    "due_soon": "warning",
    "ok": "success",
    "unknown": "neutral",
}


def _maintenance(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    """Schedules and their logs. Repair records used to be
    searched here too — since the repairs ∪ claims merge
    (2026-11-04) a repair IS a warranty claim, so the repair's
    words (problem, sent-to) are found by the claims group."""
    results: list[dict] = []
    schedules = list(
        db.scalars(
            select(maintenance_models.MaintenanceSchedule).where(
                maintenance_models.MaintenanceSchedule.owner_id == user.id
            )
        )
    )
    schedule_ids = [s.id for s in schedules]
    log_texts: dict[uuid.UUID, list[str]] = {}
    if schedule_ids:
        for entry in db.scalars(
            select(maintenance_models.MaintenanceLogEntry).where(
                maintenance_models.MaintenanceLogEntry.schedule_id.in_(schedule_ids)
            )
        ):
            log_texts.setdefault(entry.schedule_id, []).extend(
                [entry.technician or "", entry.notes or ""]
            )
    # A schedule's status is its due standing, computed by the
    # maintenance service's own due_status (the boards' source).
    from app.modules.maintenance import service as maintenance_service

    for schedule in schedules:
        fields = [
            schedule.item_name,
            schedule.label,
            *log_texts.get(schedule.id, []),
        ]
        if _hit(terms, fields):
            due = maintenance_service.due_status(schedule)
            results.append(
                _result(
                    schedule.id,
                    "schedule",
                    schedule.item_name,
                    schedule.label,
                    _excerpt(terms, log_texts.get(schedule.id, [])),
                    _item_link(db, schedule.item_kind, schedule.item_id),
                    status=_status(
                        f"maintenance.dueStatus.{due}",
                        _DUE_TONES.get(due, "neutral"),
                    ),
                )
            )
    return results


# A truck account's status tones (the Truck Accounts pages'
# statusBadge), mirrored: active success, invited ("Invite
# pending") warning, closed neutral.
_TRUCK_TONES = {"active": "success", "invited": "warning", "closed": "neutral"}


def _truck_accounts(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    accounts = list(
        db.scalars(
            select(truck_models.TruckAccount).where(
                or_(
                    truck_models.TruckAccount.dealer_user_id == user.id,
                    truck_models.TruckAccount.customer_user_id == user.id,
                )
            )
        )
    )
    if not accounts:
        return []
    account_ids = [a.id for a in accounts]
    notes: dict[uuid.UUID, list[str]] = {}
    for entry in db.scalars(
        select(truck_models.TruckEntry).where(
            truck_models.TruckEntry.account_id.in_(account_ids)
        )
    ):
        notes.setdefault(entry.account_id, []).append(entry.note or "")
    dealer_names: dict[uuid.UUID, str] = {}
    dealer_ids = {a.dealer_user_id for a in accounts if a.dealer_user_id != user.id}
    if dealer_ids:
        dealer_names = {
            row.id: row.name
            for row in db.scalars(
                select(core_models.User).where(core_models.User.id.in_(dealer_ids))
            )
        }
    results: list[dict] = []
    for account in accounts:
        fields = [
            account.customer_name,
            account.customer_email,
            dealer_names.get(account.dealer_user_id, ""),
            *notes.get(account.id, []),
        ]
        if _hit(terms, fields):
            if account.dealer_user_id == user.id:
                title = account.customer_name or ""
            else:
                title = dealer_names.get(account.dealer_user_id) or account.customer_name or ""
            results.append(
                _result(
                    account.id,
                    "truck_account",
                    title,
                    "",
                    _excerpt(terms, notes.get(account.id, [])),
                    f"/truck-accounts/{account.id}",
                    status=_status(
                        f"truck.status.{account.status}",
                        _TRUCK_TONES.get(account.status, "neutral"),
                    ),
                )
            )
    return results


# A listing's status words + tones (My Listings' own badge:
# On the board / Sold / Removed).
_LISTING_STATUSES = {
    "active": ("marketplace.row.onBoard", "success"),
    "sold": ("marketplace.row.sold", "accent"),
    "removed": ("marketplace.row.removed", "neutral"),
}


def _listings(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    results: list[dict] = []
    for listing in db.scalars(
        select(marketplace_models.SaleListing).where(
            marketplace_models.SaleListing.owner_id == user.id
        )
    ):
        fields = [
            listing.title,
            listing.description,
            listing.brand,
            listing.model,
            listing.condition,
        ]
        if _hit(terms, fields):
            # The status used to ride the detail column as a raw
            # value; it is a real status now (busy work #2) and
            # the detail steps aside for it.
            key, tone = _LISTING_STATUSES.get(
                listing.status, ("marketplace.row.onBoard", "success")
            )
            results.append(
                _result(
                    listing.id,
                    "listing",
                    listing.title,
                    "",
                    _excerpt(terms, [listing.description]),
                    f"/marketplace/{listing.id}",
                    status=_status(key, tone),
                )
            )
    return results


def _messages(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    threads = list(
        db.scalars(
            select(messaging_models.MessageThread).where(
                or_(
                    messaging_models.MessageThread.participant_low_id == user.id,
                    messaging_models.MessageThread.participant_high_id == user.id,
                )
            )
        )
    )
    if not threads:
        return []
    other_ids = {
        t.participant_high_id if t.participant_low_id == user.id else t.participant_low_id
        for t in threads
    }
    names: dict[uuid.UUID, str] = {
        row.id: row.name
        for row in db.scalars(
            select(core_models.User).where(core_models.User.id.in_(other_ids))
        )
    }
    thread_ids = [t.id for t in threads]
    # A message's text is searchable only when the caller may see
    # it: their own sends, plus delivered ones (messaging's
    # visible_to_recipient rule — held/shadow/discarded sends are
    # not the other party's to know about, and a wiped message's
    # body never surfaces).
    bodies: dict[uuid.UUID, list[str]] = {}
    for message in db.scalars(
        select(messaging_models.Message).where(
            messaging_models.Message.thread_id.in_(thread_ids),
            or_(
                messaging_models.Message.sender_id == user.id,
                messaging_models.Message.status == "sent",
            ),
        )
    ):
        if message.body:
            bodies.setdefault(message.thread_id, []).append(message.body)
    results: list[dict] = []
    for thread in threads:
        other_id = (
            thread.participant_high_id
            if thread.participant_low_id == user.id
            else thread.participant_low_id
        )
        other_name = names.get(other_id, "")
        fields = [other_name, thread.anchor_title, *bodies.get(thread.id, [])]
        if _hit(terms, fields):
            results.append(
                _result(
                    thread.id,
                    "message_thread",
                    other_name or thread.anchor_title,
                    thread.anchor_title if other_name else "",
                    _excerpt(terms, bodies.get(thread.id, [])),
                    f"/messages/{thread.id}",
                )
            )
    return results


# A ticket's status words are the Help page's own keys
# (help.statusOpen / statusUnderReview / statusClosed); the
# tones follow the system's standing semantics — live work in
# the accent, with the desk in warning, done in neutral.
_TICKET_STATUSES = {
    "open": ("help.statusOpen", "accent"),
    "under_review": ("help.statusUnderReview", "warning"),
    "closed": ("help.statusClosed", "neutral"),
}


def _support(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    tickets = list(
        db.scalars(
            select(support_models.SupportTicket).where(
                support_models.SupportTicket.user_id == user.id
            )
        )
    )
    if not tickets:
        return []
    ticket_ids = [t.id for t in tickets]
    bodies: dict[uuid.UUID, list[str]] = {}
    for message in db.scalars(
        select(support_models.SupportMessage).where(
            support_models.SupportMessage.ticket_id.in_(ticket_ids)
        )
    ):
        bodies.setdefault(message.ticket_id, []).append(message.body or "")
    results: list[dict] = []
    for ticket in tickets:
        fields = [ticket.subject, *bodies.get(ticket.id, [])]
        if _hit(terms, fields):
            # The status used to ride the detail column as a raw
            # value; it is a real status now (busy work #2) and
            # the detail steps aside for it.
            key, tone = _TICKET_STATUSES.get(
                ticket.status, ("help.statusOpen", "accent")
            )
            results.append(
                _result(
                    ticket.id,
                    "support_ticket",
                    ticket.subject,
                    "",
                    _excerpt(terms, bodies.get(ticket.id, [])),
                    f"/help?ticket={ticket.id}",
                    status=_status(key, tone),
                )
            )
    return results


def _prints(
    db: Session, user: CurrentUser, terms: list[str], visible: set[str]
) -> list[dict]:
    """3D print files — the ONE public-shelf family (owner
    order, 2026-11-08: the Downloads Part 2 spec puts its files
    in the main search explicitly). Unlike every other family
    these are NOT the caller's own records: the shelf is public
    by design, so every live file is a candidate and the match
    runs over title, description, category and publisher name.
    The module gate still applies — the family contributes only
    when the prints module is effective for the caller (the
    _FAMILIES contract), exactly like the own-data families.
    No status rides these results (busy work #2): the query only
    ever returns live files, so a status would say the same word
    on every row and narrow nothing."""
    from app.modules.core import service as core_service
    from app.modules.prints import models as print_models

    rows = list(
        db.scalars(
            select(print_models.PrintFile).where(
                print_models.PrintFile.status == "live"
            )
        )
    )
    results: list[dict] = []
    for row in rows:
        publisher = (
            None
            if row.publisher_gone
            else core_service.get_user_by_id(db, row.publisher_id)
        )
        publisher_name = (
            publisher.name
            if publisher is not None and publisher.is_active
            else "Former member"
        )
        fields = [row.title, row.description, row.category_key, publisher_name]
        if _hit(terms, fields):
            results.append(
                _result(
                    row.id,
                    "print_file",
                    row.title,
                    publisher_name,
                    _excerpt(terms, [row.description]),
                    f"/3dprints/{row.id}",
                )
            )
    return results


# group key -> (feature module, builder). FORUMS ARE NOT HERE —
# excluded entirely by the owner's word (see module docstring).
_FAMILIES = [
    ("inventory", "inventory", _inventory),
    ("parts", "parts", _parts),
    ("wishlist", "wishlist", _wishlist),
    ("dealers", "dealers", _dealers),
    ("people", "borrowing", _people),
    ("borrowing", "borrowing", _borrowing),
    ("claims", "claims", _claims),
    ("disaster_claims", "disaster_claims", _disaster_claims),
    ("maintenance", "maintenance", _maintenance),
    ("truck_accounts", "truck_accounts", _truck_accounts),
    ("listings", "marketplace", _listings),
    ("messages", "messaging", _messages),
    ("support", "support", _support),
    ("prints", "prints", _prints),
]


@router.get("/search")
def global_search(
    q: str = "",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grouped search over the caller's own records. Only families
    whose module is effective for the caller (operator layer AND
    the user's own switches) contribute — a switched-off module's
    records are as invisible here as everywhere else."""
    terms = _terms(q)
    if not terms:
        return {"query": q, "groups": []}
    visible = module_control.visible_module_ids(
        db, user.id, user.account_types, tier=user.tier, beta_tester=user.beta_tester
    )
    groups: list[dict] = []
    for key, module_id, builder in _FAMILIES:
        if module_id not in visible:
            continue
        group = _group(key, builder(db, user, terms, visible))
        if group is not None:
            groups.append(group)
    return {"query": q, "groups": groups}
