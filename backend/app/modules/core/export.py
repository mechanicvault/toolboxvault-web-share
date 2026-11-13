"""Data export (user backup v1): "Download my data" in Settings.

One ZIP with everything that is the caller's: profile, tools
and batteries (incl. custom-field values), field definitions,
sharing configs, peer grants — plus the actual attachment files wherever storage
can hand them over. A file storage can't produce goes into
files_manifest.json with a fresh presigned link instead, so the
archive is never silently incomplete: every attachment is either
IN the zip or IN the manifest with a working link.

Owner-scoped by construction: every read goes through the owning
module's owner-checked service functions with the caller's id.
"""

import io
import json
import zipfile

from sqlalchemy.orm import Session

from app.core.storage import (
    EXPORT_FALLBACK_TTL_SECONDS,
    StorageError,
    storage,
)
from app.modules.borrowing import service as borrowing_service
from app.modules.claims import service as claims_service
from app.modules.dealers import portal as dealers_portal
from app.modules.core import insurance, models, peer_sharing, sharing
from app.modules.inventory import custom_fields
from app.modules.inventory import service as inventory_service
from app.modules.maintenance import service as maintenance_service
from app.modules.core import crew as crew_service
from app.modules.feedback import service as feedback_service
from app.modules.forum import service as forum_service
from app.modules.marketplace import service as marketplace_service
from app.modules.inventory import sales as inventory_sales
from app.modules.parts import service as parts_service
from app.modules.truck_accounts import service as truck_service
from app.modules.wishlist import service as wishlist_service


def _json_default(value):
    return str(value)


def _dump(payload) -> bytes:
    return json.dumps(payload, indent=2, default=_json_default).encode("utf-8")


def build_export_zip(db: Session, user: models.User) -> bytes:
    """Assemble the caller's full export archive."""
    # A backup carries EVERYTHING: attached addon tools too (they
    # are full records), and serialize_tool's set block carries each
    # set's complete structure — pieces with prices/status, attached
    # tools, totals. No "include addons?" prompt here: it's a backup.
    tools = inventory_service.list_tools(db, user.id, include_attached=True)

    manifest: list[dict] = []
    files: dict[str, bytes] = {}
    tools_payload = []
    for tool in tools:
        view = inventory_service.serialize_tool(db, tool)
        # A backup carries EVERYTHING — including the dormant
        # condition value (Package B removed it from every surface,
        # but the stored data is the owner's and exports preserve
        # it verbatim).
        view["condition"] = tool.condition or ""
        attachments = []
        for item in view["attachments"]:
            entry = {
                "tool_id": str(tool.id),
                "key": item["key"],
                "filename": item["filename"],
                "kind": item["kind"],
                "content_type": item["content_type"],
                "size_bytes": item["size_bytes"],
                "included": False,
                "zip_path": None,
                "url": None,
            }
            zip_path = f"files/{tool.id}/{item['key'].rsplit('/', 1)[-1]}"
            try:
                files[zip_path] = storage.fetch(item["key"])
                entry["included"] = True
                entry["zip_path"] = zip_path
            except StorageError:
                # Not fatal: the manifest carries a fresh link.
                entry["url"] = storage.presigned_get_url(item["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
            manifest.append(entry)
            attachments.append(
                {k: v for k, v in item.items() if k != "url"}
                | {"zip_path": entry["zip_path"]}
            )
        view["attachments"] = attachments
        # Set pieces carry their own files — fetch those into the
        # archive too (the set block in the payload names them).
        if view.get("set"):
            for piece in (
                view["set"]["core_pieces"] + view["set"]["addon_pieces"]
            ):
                for item in piece["attachments"]:
                    entry = {
                        "tool_id": str(tool.id),
                        "piece_id": str(piece["id"]),
                        "key": item["key"],
                        "filename": item["filename"],
                        "kind": item["kind"],
                        "content_type": item["content_type"],
                        "size_bytes": item["size_bytes"],
                        "included": False,
                        "zip_path": None,
                        "url": None,
                    }
                    zip_path = (
                        f"files/{tool.id}/pieces/{piece['id']}/"
                        f"{item['key'].rsplit('/', 1)[-1]}"
                    )
                    try:
                        files[zip_path] = storage.fetch(item["key"])
                        entry["included"] = True
                        entry["zip_path"] = zip_path
                    except StorageError:
                        entry["url"] = storage.presigned_get_url(item["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
                    manifest.append(entry)
        tools_payload.append(view)

    # Batteries are the caller's assets too — same treatment as
    # tools: full serialized payload + files into the zip (or the
    # manifest with a fresh link when storage can't hand one over).
    batteries_payload = []
    for battery in inventory_service.list_batteries(db, user.id):
        view = inventory_service.serialize_battery(db, battery)
        view["condition"] = battery.condition or ""  # see tools above
        attachments = []
        for item in view["attachments"]:
            entry = {
                "battery_id": str(battery.id),
                "key": item["key"],
                "filename": item["filename"],
                "kind": item["kind"],
                "content_type": item["content_type"],
                "size_bytes": item["size_bytes"],
                "included": False,
                "zip_path": None,
                "url": None,
            }
            zip_path = f"files/batteries/{battery.id}/{item['key'].rsplit('/', 1)[-1]}"
            try:
                files[zip_path] = storage.fetch(item["key"])
                entry["included"] = True
                entry["zip_path"] = zip_path
            except StorageError:
                entry["url"] = storage.presigned_get_url(item["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
            manifest.append(entry)
            attachments.append(
                {k: v for k, v in item.items() if k != "url"}
                | {"zip_path": entry["zip_path"]}
            )
        view["attachments"] = attachments
        batteries_payload.append(view)

    # Used Parts: the location tree + every spare, with photo
    # files into the archive under the same manifest discipline.
    parts_export = parts_service.export_rows(db, user.id)
    for part in parts_export["parts"]:
        attachments = []
        for item in part["attachments"]:
            entry = {
                "part_id": part["id"],
                "key": item["key"],
                "filename": item["filename"],
                "kind": item["kind"],
                "content_type": item["content_type"],
                "size_bytes": item["size_bytes"],
                "included": False,
                "zip_path": None,
                "url": None,
            }
            zip_path = f"files/parts/{part['id']}/{item['key'].rsplit('/', 1)[-1]}"
            try:
                files[zip_path] = storage.fetch(item["key"])
                entry["included"] = True
                entry["zip_path"] = zip_path
            except StorageError:
                entry["url"] = storage.presigned_get_url(item["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
            manifest.append(entry)
            attachments.append({**item, "zip_path": entry["zip_path"]})
        part["attachments"] = attachments

    definitions = [
        {
            "id": str(d.id),
            "item_type": d.item_type,
            "name": d.name,
            "label": d.label,
            "field_type": d.field_type,
            "required": d.required,
            "searchable": d.searchable,
            "options": d.options,
            "sort_order": d.sort_order,
        }
        for d in custom_fields.list_definitions(db, user.id, "all")
    ]

    # Claims: the full claim picture, SPLIT by kind (claims
    # separation, 2026-11-05) — claims.json carries the warranty
    # claims, disaster_claims.json the insurance ones, each with
    # snapshotted lines, evidence and comms log — plus the
    # claim-specific UPLOAD files into the archive (referenced
    # evidence files are the items' own files, already carried
    # above with the tools/batteries).
    from app.modules.claims import models as claim_models

    claims_payload = claims_service.export_rows(
        db, user.id, kind=claim_models.KIND_WARRANTY
    )
    disaster_claims_payload = claims_service.export_rows(
        db, user.id, kind=claim_models.KIND_INSURANCE
    )
    for claim in [
        *claims_payload["claims"],
        *disaster_claims_payload["claims"],
    ]:
        for evidence in claim["evidence"]:
            stored = evidence.get("attachment")
            if evidence["source"] != "upload" or not stored:
                continue
            entry = {
                "claim_id": str(claim["id"]),
                "claim_number": claim["claim_number"],
                "key": stored["key"],
                "filename": stored["filename"],
                "kind": stored["kind"],
                "content_type": stored["content_type"],
                "size_bytes": stored["size_bytes"],
                "included": False,
                "zip_path": None,
                "url": None,
            }
            zip_path = (
                f"files/claims/{claim['id']}/"
                f"{stored['key'].rsplit('/', 1)[-1]}"
            )
            try:
                files[zip_path] = storage.fetch(stored["key"])
                entry["included"] = True
                entry["zip_path"] = zip_path
            except StorageError:
                entry["url"] = storage.presigned_get_url(stored["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
            manifest.append(entry)
            evidence["zip_path"] = entry["zip_path"]

    # Dealer portal: the profile photo is the user's file too —
    # carry its bytes like claim uploads (manifest falls back to a
    # presigned link when storage can't produce it).
    dealer_profile = dealers_portal.get_profile(db, user.id)
    if dealer_profile is not None and dealer_profile.photo_key:
        key = dealer_profile.photo_key
        entry = {
            "key": key,
            "filename": key.rsplit("/", 1)[-1],
            "kind": "photo",
            "included": False,
            "zip_path": None,
            "url": None,
        }
        zip_path = f"files/dealer-profile/{key.rsplit('/', 1)[-1]}"
        try:
            files[zip_path] = storage.fetch(key)
            entry["included"] = True
            entry["zip_path"] = zip_path
        except StorageError:
            entry["url"] = storage.presigned_get_url(key, expires_in=EXPORT_FALLBACK_TTL_SECONDS)
        manifest.append(entry)

    # Tools For Sale (2026-10-19): my listings with their photo
    # files into the archive under the same manifest discipline,
    # plus my deal interactions and ratings (given + received).
    marketplace_export = marketplace_service.export_rows(db, user.id)
    for listing in marketplace_export["listings"]:
        attachments = []
        for item in listing["attachments"]:
            entry = {
                "listing_id": listing["id"],
                "key": item["key"],
                "filename": item["filename"],
                "kind": item["kind"],
                "content_type": item["content_type"],
                "size_bytes": item["size_bytes"],
                "included": False,
                "zip_path": None,
                "url": None,
            }
            zip_path = (
                f"files/marketplace/{listing['id']}/"
                f"{item['key'].rsplit('/', 1)[-1]}"
            )
            try:
                files[zip_path] = storage.fetch(item["key"])
                entry["included"] = True
                entry["zip_path"] = zip_path
            except StorageError:
                entry["url"] = storage.presigned_get_url(item["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
            manifest.append(entry)
            attachments.append({**item, "zip_path": entry["zip_path"]})
        listing["attachments"] = attachments

    # Wishlist (wave 2): my want-list rows ride wishlist.json;
    # their photo bytes join the archive under the same manifest
    # discipline as listings.
    wishlist_export = wishlist_service.export_rows(db, user.id)
    for wish in wishlist_export:
        for item in wish["attachments"]:
            if not isinstance(item, dict) or "key" not in item:
                continue
            entry = {
                "wishlist_item_id": wish["id"],
                "key": item["key"],
                "filename": item.get("filename", ""),
                "kind": item.get("kind", "photo"),
                "content_type": item.get("content_type", ""),
                "size_bytes": item.get("size_bytes", 0),
                "included": False,
                "zip_path": None,
                "url": None,
            }
            zip_path = (
                f"files/wishlist/{wish['id']}/"
                f"{item['key'].rsplit('/', 1)[-1]}"
            )
            try:
                files[zip_path] = storage.fetch(item["key"])
                entry["included"] = True
                entry["zip_path"] = zip_path
            except StorageError:
                entry["url"] = storage.presigned_get_url(item["key"], expires_in=EXPORT_FALLBACK_TTL_SECONDS)
            manifest.append(entry)

    tier = sharing.get_overview(db, user.id)
    peer = peer_sharing.get_overview(db, user)

    # Importer smart matching (2026-10-19): the learned resolve
    # answers are the owner's data — they ride the backup too.
    from app.modules.inventory import matching as import_matching

    import_mappings_payload = [
        {
            "field": row["field"],
            "raw_value": row["raw_value"],
            "action": row["action"],
            "target_label": row["target_label"],
            "target_value": row["target_value"],
            "updated_at": row["updated_at"],
        }
        for row in import_matching.list_learned(db, user.id)
    ]

    payloads = {
        "account.json": {
            "account_number": user.account_number,
            "email": user.email,
            "name": user.name,
            # Country + currency (wave 3): the account's own
            # locale facts ride the backup.
            "country": user.country or "",
            "currency": user.currency or "USD",
            # Report contact details (reports alignment, 2026-10-19):
            # the owner's own export carries the full profile.
            "phone": user.phone or "",
            "postal_address": user.postal_address or "",
            "account_types": list(user.account_types or []),
            "email_verified": user.email_verified,
            "created_at": user.created_at,
        },
        "tools.json": tools_payload,
        "batteries.json": batteries_payload,
        "field_definitions.json": definitions,
        "sharing.json": {"tier": tier, "peer": peer},
        "borrowing.json": borrowing_service.export_rows(db, user.id),
        # Gap wave 1 (2026-10-20): the borrower address book, the
        # lost/stolen report records, and the category/tag
        # vocabulary (warranty details ride the tool/battery
        # payloads above via their serializers).
        "borrowers.json": borrowing_service.export_borrower_contacts(
            db, user.id
        ),
        "loss_reports.json": [
            inventory_service.serialize_loss_report(row)
            for row in inventory_service.list_all_loss_reports(db, user.id)
        ],
        "categories.json": {
            "categories": inventory_service.list_categories(db, user.id),
            "tags": inventory_service.list_tags(db, user.id),
        },
        "maintenance.json": maintenance_service.export_rows(db, user.id),
        "claims.json": claims_payload,
        "disaster_claims.json": disaster_claims_payload,
        "dealers.json": dealers_portal.export_rows(db, user.id),
        "parts.json": parts_export,
        "marketplace.json": marketplace_export,
        # Community Forum (2026-10-20): my threads + every post I
        # wrote, any status — my own backup carries my words even
        # where the public surfaces no longer show them.
        "forum.json": forum_service.export_rows(db, user.id),
        "import_mappings.json": import_mappings_payload,
        # My Insurance (Package C): the owner's insurer + agent.
        "insurance.json": insurance.export_payload(db, user.id),
        # Wave 2 (2026-10-20): the wishlist, the sold ledger
        # (reversals included — the honest history), and truck
        # accounts role-shaped (my side of each tab + its ledger).
        "wishlist.json": wishlist_export,
        "sales.json": inventory_sales.export_rows(db, user.id),
        "truck_accounts.json": truck_service.export_rows(db, user.id),
        # Wave 3 (2026-10-20): my crew facts (roster + memberships)
        # and my feedback (posts, comments, upvotes).
        "crew.json": crew_service.export_rows(db, user.id),
        "feedback.json": feedback_service.export_rows(db, user.id),
        "files_manifest.json": manifest,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, _dump(payload))
        for path, blob in files.items():
            archive.writestr(path, blob)
    return buffer.getvalue()
