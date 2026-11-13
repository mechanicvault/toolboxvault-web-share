"""Notification click-through links (owner spec, 2026-10-25):
clicking a notification marks it read AND takes the user to its
source — the specific record the notification is about.

The destination for every inbox kind is resolved HERE, on the
server, and shipped on the wire as `link` (see
inbox.notification_view). Server-side is deliberate: this is the
one place that can cheaply batch-check that the source record
still exists (a deleted source downgrades to the module's main
page — never an error, never a dead end), tell the two sides of
a two-party kind apart (crew_left lands the shop owner on the
crew roster and the member on My Shop), and respect the user's
module switches (a kind whose module the user turned off is
hidden by the inbox's own rules; the one always-visible module
kind — dealer warranty requests — falls back to Home when the
dealers module is off rather than landing on the module-off
page).

KIND_LINKS is the complete map. A test pins it against every
kind constant the system can create (inbox's KIND_* plus the
dealer warranty kinds), so a new kind cannot ship without a
destination.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.core import inbox, models

# -- families ---------------------------------------------------
# A family is one deep-link shape: where the record lives, how
# its existence is checked, and the main-page fallback used
# when the record (or the id in the payload) is gone.
F_TICKET_MEMBER = "ticket_member"  # /help?ticket=<id>
F_TICKET_ADMIN = "ticket_admin"  # /admin/support?ticket=<id>
F_CLAIM = "claim"  # /claims/<id> (warranty claims)
F_DISASTER_CLAIM = "disaster_claim"  # /disaster-claims/<id> (insurance claims)
F_ITEM = "item"  # /inventory/<id> or /inventory/batteries/<id>
F_MESSAGE_THREAD = "message_thread"  # /messages/<id>
F_FORUM_THREAD = "forum_thread"  # /forum/thread/<id>
F_FEEDBACK_POST = "feedback_post"  # /feedback/post/<id>
F_TRUCK_ACCOUNT = "truck_account"  # /truck-accounts/<id>
F_CHECKOUT = "checkout"  # /borrowing?checkout=<id>
F_RATING = "rating"  # the removed review's deal thread, else /marketplace
F_MEMBERSHIP = "membership"  # crew_left: audience decides the settings page
F_DEALERS = "dealers"  # /dealers, or Home when the module is off
F_DEALER_COMPANY = "dealer_company"  # /dealers/<company>#agents when visible
F_FLYER = "flyer"  # /flyers#<source_key> — the source's own tab
F_PRINT_FILE = "print_file"  # /3dprints/<file_id> — the listing page
F_STATIC = "static"  # a fixed page; the fallback IS the destination
F_ANNOUNCEMENT = "announcement"  # the composer's own link, else Home


def is_internal_path(value) -> bool:
    """True when `value` is a safe in-app route: a string that
    starts with exactly one "/" and carries no scheme, host,
    backslash or whitespace. The announcement composer accepts
    a link on the operator's word; this is the check that keeps
    that word from becoming an open-redirect off the site."""
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ch.isspace() for ch in value)
    )

# kind -> (family, fallback path). For F_STATIC the fallback is
# the destination itself.
KIND_LINKS: dict[str, tuple[str, str]] = {
    # Shared tools is a tabbed page (Main Tab Layout program,
    # 2026-11-09): the recipient answers an invite on the
    # Shared-with-me tab; the inviter reads an accept/decline on
    # their I-am-sharing tab. The page reads these hashes the
    # way /flyers and /repairs read theirs.
    inbox.KIND_PEER_INVITE_RECEIVED: (F_STATIC, "/shared-tools#shared-with-me"),
    inbox.KIND_PEER_INVITE_ACCEPTED: (F_STATIC, "/shared-tools#sharing"),
    inbox.KIND_PEER_INVITE_DECLINED: (F_STATIC, "/shared-tools#sharing"),
    inbox.KIND_BORROW_REQUESTED: (F_CHECKOUT, "/borrowing"),
    inbox.KIND_BORROW_APPROVED: (F_CHECKOUT, "/borrowing"),
    inbox.KIND_BORROW_DECLINED: (F_CHECKOUT, "/borrowing"),
    inbox.KIND_BORROW_REQUEST_CANCELLED: (F_CHECKOUT, "/borrowing"),
    inbox.KIND_BORROW_RETURNED: (F_CHECKOUT, "/borrowing"),
    inbox.KIND_MAINTENANCE_OVERDUE: (F_ITEM, "/inventory"),
    # Claim deadlines (proof of loss, depreciation) are the
    # DISASTER section's machinery (claims separation,
    # 2026-11-05): those notifications land on the disaster
    # claim itself, in its own section.
    inbox.KIND_CLAIM_DEADLINE: (F_DISASTER_CLAIM, "/disaster-claims"),
    inbox.KIND_CLAIM_READINESS: (F_STATIC, "/inventory/health"),
    # Warranty claims (2026-10-25): both seats land on the claim
    # itself — the page renders the owner's or the dealer's view
    # by who is asking.
    inbox.KIND_WARRANTY_CLAIM_NEW: (F_CLAIM, "/repairs#repair-claims"),
    inbox.KIND_WARRANTY_CLAIM_UPDATE: (F_CLAIM, "/repairs#repair-claims"),
    inbox.KIND_CLAIM_BACKORDER: (F_CLAIM, "/repairs#repair-claims"),
    inbox.KIND_MESSAGE_RECEIVED: (F_MESSAGE_THREAD, "/messages"),
    inbox.KIND_MESSAGE_REQUEST_ACCEPTED: (F_MESSAGE_THREAD, "/messages"),
    # Tier conversion (2026-11-10): a god account clicks through
    # to the approval queue; the requester who was approved lands
    # on Home (the full site, the account-type gate first); a
    # denied requester lands on the Settings profile section,
    # where the code door lives.
    inbox.KIND_CONVERSION_REQUESTED: (F_STATIC, "/admin/conversion-requests"),
    inbox.KIND_CONVERSION_APPROVED: (F_STATIC, "/"),
    inbox.KIND_CONVERSION_DENIED: (F_STATIC, "/settings/profile"),
    inbox.KIND_FORUM_REPLY: (F_FORUM_THREAD, "/forum"),
    inbox.KIND_RATING_REMOVED: (F_RATING, "/marketplace"),
    inbox.KIND_TRUCK_INVITE: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_ACCEPTED: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_DECLINED: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_CHARGE: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_PAYMENT: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_CLOSED: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_DUE: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_OVERDUE: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    # The transfer kind's constant lives in truck_accounts.service
    # (KIND_TRUCK_TRANSFERRED); the string is repeated here like
    # the dealer warranty kinds below. The payload carries the
    # account_id, so the bell entry lands on the account itself.
    "truck_account_transferred": (F_TRUCK_ACCOUNT, "/truck-accounts"),
    # Stage 2 payment requests ride the same account link — the
    # payload carries the account_id like every truck kind.
    inbox.KIND_TRUCK_PAYMENT_REQUESTED: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_PAYMENT_REQUEST_APPROVED: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_TRUCK_PAYMENT_REQUEST_DECLINED: (F_TRUCK_ACCOUNT, "/truck-accounts"),
    inbox.KIND_CREW_INVITE: (F_STATIC, "/settings/my-shop"),
    inbox.KIND_CREW_ACCEPTED: (F_STATIC, "/settings/crew"),
    inbox.KIND_CREW_DECLINED: (F_STATIC, "/settings/crew"),
    inbox.KIND_CREW_LEFT: (F_MEMBERSHIP, "/settings/my-shop"),
    inbox.KIND_CREW_GRACE_ENDING: (F_STATIC, "/settings/my-shop"),
    inbox.KIND_CREW_GRACE_EXPIRED: (F_STATIC, "/settings/my-shop"),
    inbox.KIND_FEEDBACK_STATUS: (F_FEEDBACK_POST, "/feedback"),
    inbox.KIND_FEEDBACK_COMMENT: (F_FEEDBACK_POST, "/feedback"),
    inbox.KIND_FEEDBACK_NEW_POST: (F_FEEDBACK_POST, "/feedback"),
    # Onboarding new-feature note: the setup hub IS the
    # destination (it opens on the new feature's step).
    inbox.KIND_ONBOARDING_NEW_FEATURE: (F_STATIC, "/setup"),
    # Feature announcements (release machinery, 2026-11-08):
    # the destination is the composer's own optional link,
    # validated as an internal path; no link (or a bad one)
    # lands on Home — the announcement text itself is the news.
    inbox.KIND_FEATURE_ANNOUNCEMENT: (F_ANNOUNCEMENT, "/"),
    inbox.KIND_MANUAL_SAVED: (F_ITEM, "/inventory"),
    inbox.KIND_MANUAL_NOT_FOUND: (F_ITEM, "/inventory"),
    inbox.KIND_DEALER_ROUTE_DAY: (F_STATIC, "/settings/dealer-profile"),
    inbox.KIND_AGENT_TAKEOVER_REQUESTED: (F_DEALER_COMPANY, "/dealers"),
    inbox.KIND_AGENT_TAKEOVER_ACCEPTED: (F_DEALER_COMPANY, "/dealers"),
    inbox.KIND_AGENT_TAKEOVER_DECLINED: (F_DEALER_COMPANY, "/dealers"),
    # The 30-day invite reminder lands on the same Agents tab:
    # the record's agent code and copyable invite message — the
    # hand-over the reminder points at — live there.
    inbox.KIND_AGENT_INVITE_REMINDER: (F_DEALER_COMPANY, "/dealers"),
    inbox.KIND_FLYER_POSTED: (F_FLYER, "/flyers"),
    # Content alerts (sweep E4, 2026-11-12): a new/updated
    # print file lands on the listing's own page (gone or
    # removed → the shelf); a new downloads document lands on
    # the Downloads page's Documents tab.
    inbox.KIND_PRINT_FILE_NEW: (F_PRINT_FILE, "/3dprints"),
    inbox.KIND_PRINT_FILE_UPDATED: (F_PRINT_FILE, "/3dprints"),
    inbox.KIND_DOWNLOAD_FILE_NEW: (F_STATIC, "/downloads#documents"),
    inbox.KIND_CLOUD_BACKUP_FAILED: (F_STATIC, "/settings/cloud-backup"),
    inbox.KIND_CLOUD_BACKUP_RECOVERED: (F_STATIC, "/settings/cloud-backup"),
    inbox.KIND_SUPPORT_REPLY: (F_TICKET_MEMBER, "/help"),
    inbox.KIND_SUPPORT_STATUS: (F_TICKET_MEMBER, "/help"),
    inbox.KIND_SUPPORT_TICKET_NEW: (F_TICKET_ADMIN, "/admin/support"),
    inbox.KIND_SUPPORT_TICKET_REPLY: (F_TICKET_ADMIN, "/admin/support"),
    # Community moderation (admin lane, 2026-11-07): a flag
    # lands the responder on the moderation queue (the flag's
    # working surface); a blocked member lands on the ticket
    # desk — the notice's own road back; an unblocked member
    # lands on the forum, the community's front door.
    inbox.KIND_COMMUNITY_FLAG: (F_STATIC, "/moderation"),
    inbox.KIND_COMMUNITY_BLOCKED: (F_STATIC, "/help#tickets"),
    inbox.KIND_COMMUNITY_UNBLOCKED: (F_STATIC, "/forum"),
    # The dealer warranty kinds live in dealers/warranty.py (its
    # own KIND_REQUEST_* constants); strings repeated here so
    # this module never imports a feature module at load time.
    "warranty_request_received": (F_DEALERS, "/dealers"),
    "warranty_request_claimed": (F_DEALERS, "/dealers"),
    "warranty_request_status": (F_DEALERS, "/dealers"),
}


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _existing_ids(db: Session, model, ids: set[uuid.UUID], *extra) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(
        db.scalars(select(model.id).where(model.id.in_(sorted(ids)), *extra)).all()
    )


def resolve_links(
    db: Session, user: models.User, rows: list[models.Notification]
) -> dict[uuid.UUID, str | None]:
    """The click-through link for each row, keyed by row id.
    Kinds with no KIND_LINKS entry resolve to None (the client
    then keeps the old mark-read-only click) — the completeness
    test keeps that set empty for every kind the system creates.
    All existence checks batch: one query per family per list,
    never one per row. Cross-module models import locally —
    those modules import the inbox, so a top-level import here
    would cycle."""
    wanted: dict[str, set[uuid.UUID]] = {
        "ticket": set(),
        "claim": set(),
        "tool": set(),
        "battery": set(),
        "message_thread": set(),
        "forum_thread": set(),
        "feedback_post": set(),
        "truck_account": set(),
        "checkout": set(),
        "membership": set(),
        "dealer_company": set(),
        "flyer_source": set(),
        "print_file": set(),
    }
    memberships: dict[uuid.UUID, models.ShopMembership] = {}
    dealer_companies: dict[uuid.UUID, object] = {}
    needs_dealers_visibility = False

    for row in rows:
        spec = KIND_LINKS.get(row.kind)
        if spec is None:
            continue
        family = spec[0]
        data = row.data or {}
        if family in (F_TICKET_MEMBER, F_TICKET_ADMIN):
            _collect(wanted["ticket"], data.get("ticket_id"))
        elif family in (F_CLAIM, F_DISASTER_CLAIM):
            _collect(wanted["claim"], data.get("claim_id"))
        elif family == F_ITEM:
            key = "battery" if data.get("item_kind") == "battery" else "tool"
            _collect(wanted[key], data.get("item_id"))
        elif family in (F_MESSAGE_THREAD, F_RATING):
            _collect(wanted["message_thread"], data.get("thread_id"))
        elif family == F_FORUM_THREAD:
            _collect(wanted["forum_thread"], data.get("thread_id"))
        elif family == F_FEEDBACK_POST:
            _collect(wanted["feedback_post"], data.get("post_id"))
        elif family == F_TRUCK_ACCOUNT:
            _collect(wanted["truck_account"], data.get("account_id"))
        elif family == F_CHECKOUT:
            _collect(wanted["checkout"], data.get("checkout_id"))
        elif family == F_MEMBERSHIP:
            _collect(wanted["membership"], data.get("membership_id"))
        elif family == F_DEALERS:
            needs_dealers_visibility = True
        elif family == F_DEALER_COMPANY:
            needs_dealers_visibility = True
            _collect(wanted["dealer_company"], data.get("company_id"))
        elif family == F_FLYER:
            _collect(wanted["flyer_source"], data.get("source_id"))
        elif family == F_PRINT_FILE:
            _collect(wanted["print_file"], data.get("file_id"))

    existing: dict[str, set[uuid.UUID]] = {}
    if wanted["ticket"]:
        from app.modules.support import models as support_models

        existing["ticket"] = _existing_ids(db, support_models.SupportTicket, wanted["ticket"])
    if wanted["claim"]:
        from app.modules.claims import models as claim_models

        existing["claim"] = _existing_ids(db, claim_models.Claim, wanted["claim"])
        # Each claim's KIND rides along (claims separation,
        # 2026-11-05): a claim link must land in the claim's OWN
        # section — warranty under /claims, disaster under
        # /disaster-claims — never the other section's page.
        existing["claim_kinds"] = {
            row_id: kind
            for row_id, kind in db.execute(
                select(claim_models.Claim.id, claim_models.Claim.kind).where(
                    claim_models.Claim.id.in_(sorted(wanted["claim"]))
                )
            )
        }
    if wanted["tool"]:
        from app.modules.inventory import models as inventory_models

        existing["tool"] = _existing_ids(db, inventory_models.Tool, wanted["tool"])
    if wanted["battery"]:
        from app.modules.inventory import models as inventory_models

        existing["battery"] = _existing_ids(db, inventory_models.Battery, wanted["battery"])
    if wanted["message_thread"]:
        from app.modules.messaging import models as messaging_models

        # Existence FOR THIS USER: a thread they don't take part
        # in is not a destination (its page would refuse them).
        existing["message_thread"] = _existing_ids(
            db,
            messaging_models.MessageThread,
            wanted["message_thread"],
            (messaging_models.MessageThread.participant_low_id == user.id)
            | (messaging_models.MessageThread.participant_high_id == user.id),
        )
    if wanted["forum_thread"]:
        from app.modules.forum import models as forum_models

        existing["forum_thread"] = _existing_ids(db, forum_models.ForumThread, wanted["forum_thread"])
    if wanted["feedback_post"]:
        from app.modules.feedback import models as feedback_models

        existing["feedback_post"] = _existing_ids(db, feedback_models.FeedbackPost, wanted["feedback_post"])
    if wanted["truck_account"]:
        from app.modules.truck_accounts import models as truck_models

        existing["truck_account"] = _existing_ids(db, truck_models.TruckAccount, wanted["truck_account"])
    if wanted["checkout"]:
        from app.modules.borrowing import models as borrowing_models

        existing["checkout"] = _existing_ids(db, borrowing_models.Checkout, wanted["checkout"])
    if wanted["membership"]:
        memberships = {
            m.id: m
            for m in db.scalars(
                select(models.ShopMembership).where(
                    models.ShopMembership.id.in_(sorted(wanted["membership"]))
                )
            ).all()
        }

    if wanted["dealer_company"]:
        from app.modules.dealers import models as dealer_models

        dealer_companies = {
            c.id: c
            for c in db.scalars(
                select(dealer_models.DealerCompany).where(
                    dealer_models.DealerCompany.id.in_(
                        sorted(wanted["dealer_company"])
                    )
                )
            ).all()
        }
    if wanted["flyer_source"]:
        from app.modules.flyers import models as flyer_models

        existing["flyer_source"] = _existing_ids(
            db, flyer_models.FlyerSource, wanted["flyer_source"]
        )
    if wanted["print_file"]:
        from app.modules.prints import models as print_models

        # Only a LIVE listing is a destination; a removed one
        # downgrades to the shelf (the F_FLYER posture).
        existing["print_file"] = _existing_ids(
            db,
            print_models.PrintFile,
            wanted["print_file"],
            print_models.PrintFile.status == "live",
        )

    dealers_visible: bool | None = None
    if needs_dealers_visibility:
        from app.modules.core import module_control, tiers

        dealers_visible = "dealers" in module_control.visible_module_ids(
            db,
            user.id,
            user.account_types or (),
            tier=tiers.resolved_tier(user),
            beta_tester=bool(getattr(user, "beta_tester", False)),
        )

    links: dict[uuid.UUID, str | None] = {}
    for row in rows:
        links[row.id] = _link_for_row(
            row,
            user=user,
            existing=existing,
            memberships=memberships,
            dealer_companies=dealer_companies,
            dealers_visible=dealers_visible,
        )
    return links


def _collect(target: set[uuid.UUID], value) -> None:
    parsed = _uuid(value)
    if parsed is not None:
        target.add(parsed)


def _link_for_row(
    row: models.Notification,
    *,
    user: models.User,
    existing: dict[str, set[uuid.UUID]],
    memberships: dict[uuid.UUID, models.ShopMembership],
    dealer_companies: dict[uuid.UUID, object],
    dealers_visible: bool | None,
) -> str | None:
    spec = KIND_LINKS.get(row.kind)
    if spec is None:
        return None
    family, fallback = spec
    data = row.data or {}

    if family == F_STATIC:
        return fallback
    if family == F_ANNOUNCEMENT:
        link = data.get("link")
        return link if is_internal_path(link) else fallback
    if family == F_TICKET_MEMBER:
        tid = _uuid(data.get("ticket_id"))
        return f"/help?ticket={tid}" if tid in existing.get("ticket", set()) else fallback
    if family == F_TICKET_ADMIN:
        tid = _uuid(data.get("ticket_id"))
        return (
            f"/admin/support?ticket={tid}"
            if tid in existing.get("ticket", set())
            else fallback
        )
    if family == F_CLAIM:
        cid = _uuid(data.get("claim_id"))
        kinds = existing.get("claim_kinds", {})
        if cid in existing.get("claim", set()) and kinds.get(cid) != "insurance_disaster":
            return f"/claims/{cid}"
        return fallback
    if family == F_DISASTER_CLAIM:
        cid = _uuid(data.get("claim_id"))
        kinds = existing.get("claim_kinds", {})
        if cid in existing.get("claim", set()) and kinds.get(cid) == "insurance_disaster":
            return f"/disaster-claims/{cid}"
        return fallback
    if family == F_ITEM:
        iid = _uuid(data.get("item_id"))
        if data.get("item_kind") == "battery":
            return (
                f"/inventory/batteries/{iid}"
                if iid in existing.get("battery", set())
                else fallback
            )
        return f"/inventory/{iid}" if iid in existing.get("tool", set()) else fallback
    if family == F_MESSAGE_THREAD:
        tid = _uuid(data.get("thread_id"))
        return (
            f"/messages/{tid}"
            if tid in existing.get("message_thread", set())
            else fallback
        )
    if family == F_FORUM_THREAD:
        tid = _uuid(data.get("thread_id"))
        return (
            f"/forum/thread/{tid}"
            if tid in existing.get("forum_thread", set())
            else fallback
        )
    if family == F_FEEDBACK_POST:
        pid = _uuid(data.get("post_id"))
        return (
            f"/feedback/post/{pid}"
            if pid in existing.get("feedback_post", set())
            else fallback
        )
    if family == F_TRUCK_ACCOUNT:
        aid = _uuid(data.get("account_id"))
        return (
            f"/truck-accounts/{aid}"
            if aid in existing.get("truck_account", set())
            else fallback
        )
    if family == F_CHECKOUT:
        cid = _uuid(data.get("checkout_id"))
        return (
            f"/borrowing?checkout={cid}"
            if cid in existing.get("checkout", set())
            else fallback
        )
    if family == F_RATING:
        tid = _uuid(data.get("thread_id"))
        if tid is not None and tid in existing.get("message_thread", set()):
            return f"/messages/{tid}"
        return fallback
    if family == F_MEMBERSHIP:
        membership = memberships.get(_uuid(data.get("membership_id")))
        if membership is not None:
            return (
                "/settings/crew"
                if membership.shop_user_id == user.id
                else "/settings/my-shop"
            )
        # The membership row is gone; land on the side of the
        # fence the account itself suggests.
        return (
            "/settings/crew"
            if "shop_company" in (user.account_types or ())
            else "/settings/my-shop"
        )
    if family == F_FLYER:
        # The flyer page at the source's own tab; a source that's
        # gone downgrades to the flyer page itself.
        sid = _uuid(data.get("source_id"))
        key = data.get("source_key")
        if sid in existing.get("flyer_source", set()) and key:
            return f"/flyers#{key}"
        return fallback
    if family == F_PRINT_FILE:
        fid = _uuid(data.get("file_id"))
        return (
            f"/3dprints/{fid}"
            if fid in existing.get("print_file", set())
            else fallback
        )
    if family == F_DEALER_COMPANY:
        # The company page's Agents tab — but only when the page
        # is a destination FOR THIS USER: the dealers module must
        # be visible to them and the company must be the directory
        # or their own (an agent hearing back about a customer's
        # PRIVATE company lands on the directory instead — that
        # page would refuse them).
        if not dealers_visible:
            return "/"
        cid = _uuid(data.get("company_id"))
        company = dealer_companies.get(cid) if cid else None
        if company is not None and (
            company.owner_id is None or company.owner_id == user.id
        ):
            return f"/dealers/{cid}#agents"
        return fallback
    if family == F_DEALERS:
        return "/dealers" if dealers_visible else "/"
    return fallback
