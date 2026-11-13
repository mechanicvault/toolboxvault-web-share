"""Reports routes: meta (builder catalog), run, saved configs,
file exports, and email delivery.

The whole tree is gated on the reports module being effective for
the caller (module doctrine): off or unassigned → 403
module_unavailable, like every other feature module.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, require_module
from app.modules.core import module_control
from app.modules.reports import columns as colmod
from app.modules.reports import exports, schemas, service

router = APIRouter(dependencies=[Depends(require_module("reports"))])


def _dealer_visible(db: Session, user: CurrentUser) -> bool:
    """Dealer tags ride the dealers module (inventory's rule): when
    that module is off for this user, report dealer columns render
    blank while the stored tag stays untouched."""
    return module_control.effective_for_user(db, "dealers", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester)


# Activity kinds feed off other modules' books (activity.py):
# each builder's data owner decides the extra gate on top of the
# reports module itself. Inventory-fed kinds (sales, lost/stolen,
# year-end, tax) need no extra gate — inventory already gates
# reports. The map is by activity kind (ACTIVITY_BUILDERS keys);
# the dedicated GET/export routes name their module directly.
ACTIVITY_MODULE_BY_KIND: dict[str, str] = {
    "repair_costs": "claims",
    "dealer_account": "truck_accounts",
    "checked_out": "borrowing",
    "warranty_claims": "dealers",
}


def _require_activity_module(db: Session, user: CurrentUser, module_id: str) -> None:
    """403 module_unavailable when the activity report's owning
    module isn't effective for the caller (user layer included)."""
    if not module_control.effective_for_user(
        db, module_id, user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "module_unavailable",
                "module": module_id,
                "message": "This module isn't enabled for your account.",
            },
        )


def _as_422(exc: service.ReportError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")


@router.get("/meta")
def meta(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything the builder needs in one read: the column
    catalog (base + the owner's custom fields), the grouping and
    sets-mode vocabularies, and the filter vocabularies."""
    from app.modules.inventory import service as inventory_service

    return {
        "columns": service.column_catalog(db, user.id),
        "default_columns": colmod.DEFAULT_COLUMNS,
        "groupings": [
            {"key": "none", "label": "No grouping"},
            {"key": "category", "label": "Category"},
            {"key": "dealer", "label": "Dealer"},
            {"key": "location", "label": "Location"},
            {"key": "tag", "label": "Tag"},
            {"key": "kind", "label": "Kind"},
            {"key": "purchase_year", "label": "Purchase year"},
        ],
        "sets_modes": [
            {
                "key": "summary",
                "label": "Summary — sets as single rows",
                "hint": "Pieces and attached tools are not rows; the set row carries the whole bundle's value.",
            },
            {
                "key": "with_core",
                "label": "With core pieces",
                "hint": "Core pieces appear as rows under their set; a piece's own price shows on its row when one is recorded.",
            },
            {
                "key": "full",
                "label": "Full — every piece and addon",
                "hint": "Core pieces, addon pieces and attached tools all appear as rows with their own prices.",
            },
        ],
        "categories": sorted(
            {t.category for t in inventory_service.list_tools(db, user.id, include_attached=True) if t.category}
            | {b.category for b in inventory_service.list_batteries(db, user.id) if b.category}
        ),
        "locations": inventory_service.list_locations(db, user.id),
        "tags": [t["name"] for t in inventory_service.list_tags(db, user.id)],
    }


@router.post("/run")
def run(
    payload: schemas.RunRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.run_report(
            db,
            user.id,
            payload,
            dealer_visible=_dealer_visible(db, user),
            prepared_for=service.prepared_for_of(_owner_row(db, user)),
        )
    except service.ReportError as exc:
        raise _as_422(exc)


@router.post("/narrative")
def narrative(
    payload: schemas.RunRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI narrative summary (wave 4): a plain-language paragraph
    written from THIS report run's aggregate numbers — counts,
    totals, group subtotals; never row-level personal data beyond
    the owner's own aggregates. Dark-seam contract: while no AI
    provider is configured the endpoint answers 503
    {code: ai_not_configured} and the page hides the panel
    entirely (it never renders an error for an unlit feature)."""
    from app.modules.billing import ai_service, wallet
    from app.modules.core.money import format_money

    if not ai_service.ai_configured(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ai_not_configured",
                "message": "AI features aren't switched on for this site yet.",
            },
        )
    try:
        report = service.build_report(
            db,
            user.id,
            payload,
            dealer_visible=_dealer_visible(db, user),
            prepared_for=service.prepared_for_of(_owner_row(db, user)),
        )
    except service.ReportError as exc:
        raise _as_422(exc)
    owner = _owner_row(db, user)
    currency = owner.currency or "USD"
    summary = report["summary"]
    totals = report["totals"]
    group_lines = []
    for group in report["groups"][:12]:
        subtotal = group.get("subtotal") or {}
        group_lines.append(
            f"- {group.get('label') or 'All items'}: "
            f"{len(group['rows'])} rows, "
            f"value {format_money(subtotal.get('price_total'), currency)}"
        )
    facts = [
        f"Items in report: {summary['items']} ({summary['units']} units counting quantities)",
        f"Total purchase value: {format_money(totals.get('price_total'), currency)}",
        f"Total replacement value: {format_money(totals.get('replacement'), currency)}",
        f"Grouping: {report['grouping']}; sets shown as: {report['sets_mode']}",
    ]
    if group_lines:
        facts.append("Groups:\n" + "\n".join(group_lines))
    prompt = (
        "Write ONE short paragraph (3-5 sentences) summarizing this "
        "tool inventory report for its owner, in plain language. "
        "Use only these figures; do not invent numbers, brands, or "
        "items that aren't listed.\n\n" + "\n".join(facts)
    )
    try:
        ai_service.begin_usage_capture()
        text = ai_service.complete(
            db,
            prompt,
            system="You summarize inventory reports for mechanics. Plain, concrete language.",
        )
        charged = ai_service.charge_for(
            db,
            user.id,
            "report_summary",
            subject=f"Inventory report ({report['grouping']})",
        )
    except ai_service.AiNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ai_not_configured", "message": str(exc)},
        ) from exc
    except ai_service.AiProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ai_provider_error", "message": str(exc)},
        ) from exc
    except wallet.InsufficientCredits as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "insufficient_credits",
                "message": "Your AI credit balance doesn't cover this action.",
            },
        ) from exc
    return {"narrative": text.strip(), "ai_charged": charged}


# -- saved configurations ---------------------------------------------------------


@router.get("/configs")
def list_configs(
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Saved configs AND the built-in presets (marked builtin —
    copy one to make it yours; presets can't be edited or deleted)."""
    return {
        "saved": [service.serialize_config(c) for c in service.list_configs(db, user.id)],
        "presets": service.list_presets(),
    }


@router.post("/configs", status_code=status.HTTP_201_CREATED)
def create_config(
    payload: schemas.ConfigWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        config = service.create_config(db, user.id, payload)
    except service.ReportError as exc:
        raise _as_422(exc)
    return service.serialize_config(config)


@router.get("/configs/{config_id}")
def get_config(
    config_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = service.get_config(db, user.id, config_id)
    if config is None:
        raise _not_found()
    return service.serialize_config(config)


@router.put("/configs/{config_id}")
def update_config(
    config_id: uuid.UUID,
    payload: schemas.ConfigWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        config = service.update_config(db, user.id, config_id, payload)
    except service.ReportError as exc:
        raise _as_422(exc)
    if config is None:
        raise _not_found()
    return service.serialize_config(config)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(
    config_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not service.delete_config(db, user.id, config_id):
        raise _not_found()


# -- activity reports (wave 3): year-end ledger + repair costs ----------------------
#
# Dedicated report kinds (see activity.py): ledgers over events
# in other modules' books, which the column-spec presets cannot
# express. On-screen JSON + CSV/PDF downloads ride one builder,
# so the file can never disagree with the screen.


@router.get("/year-end")
def year_end(
    year: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    return activity.build_year_end(db, _owner_row(db, user), year)


@router.get("/year-end/export")
def year_end_export(
    year: int,
    fmt: str = "pdf",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    if fmt not in ("csv", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format must be csv or pdf.",
        )
    owner = _owner_row(db, user)
    report = activity.build_year_end(db, owner, year)
    content = activity.render_activity(report, fmt, owner)
    return Response(
        content=content,
        media_type=exports.MIME_TYPES[fmt],
        headers={
            "Content-Disposition": (
                f'attachment; filename="year-end-{year}.{exports.EXTENSIONS[fmt]}"'
            )
        },
    )


@router.get("/repair-costs")
def repair_costs(
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import date as _date

    from app.modules.reports import activity

    _require_activity_module(db, user, "maintenance")
    try:
        start_date = _date.fromisoformat(start) if start else None
        end_date = _date.fromisoformat(end) if end else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be YYYY-MM-DD.",
        )
    return activity.build_repair_costs(
        db, _owner_row(db, user), start=start_date, end=end_date
    )


@router.get("/repair-costs/export")
def repair_costs_export(
    fmt: str = "pdf",
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import date as _date

    from app.modules.reports import activity

    _require_activity_module(db, user, "maintenance")
    if fmt not in ("csv", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format must be csv or pdf.",
        )
    try:
        start_date = _date.fromisoformat(start) if start else None
        end_date = _date.fromisoformat(end) if end else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be YYYY-MM-DD.",
        )
    owner = _owner_row(db, user)
    report = activity.build_repair_costs(
        db, owner, start=start_date, end=end_date
    )
    content = activity.render_activity(report, fmt, owner)
    return Response(
        content=content,
        media_type=exports.MIME_TYPES[fmt],
        headers={
            "Content-Disposition": (
                f'attachment; filename="repair-costs.{exports.EXTENSIONS[fmt]}"'
            )
        },
    )


# -- A13/A14 dedicated kinds (audit, 2026-10-22) -----------------------------------
#
# Sales, dealer accounts, checked-out, lost/stolen, warranty
# claims, and the Tax / Section 179 worksheet — same contract
# as year-end/repair-costs (one builder behind screen + CSV +
# PDF), plus a shared email route for every activity kind.


def _parse_period(start: str | None, end: str | None):
    from datetime import date as _date

    try:
        return (
            _date.fromisoformat(start) if start else None,
            _date.fromisoformat(end) if end else None,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be YYYY-MM-DD.",
        )


def _activity_export(report: dict, fmt: str, owner, filename: str) -> Response:
    from app.modules.reports import activity

    if fmt not in ("csv", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format must be csv or pdf.",
        )
    content = activity.render_activity(report, fmt, owner)
    return Response(
        content=content,
        media_type=exports.MIME_TYPES[fmt],
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}.{exports.EXTENSIONS[fmt]}"'
            )
        },
    )


@router.get("/sales")
def sales_report(
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    start_date, end_date = _parse_period(start, end)
    return activity.build_sales(
        db, _owner_row(db, user), start=start_date, end=end_date
    )


@router.get("/sales/export")
def sales_export(
    fmt: str = "pdf",
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    start_date, end_date = _parse_period(start, end)
    owner = _owner_row(db, user)
    report = activity.build_sales(db, owner, start=start_date, end=end_date)
    return _activity_export(report, fmt, owner, "sales")


@router.get("/dealer-accounts")
def dealer_accounts_report(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    _require_activity_module(db, user, "truck_accounts")
    return activity.build_dealer_accounts(db, _owner_row(db, user))


@router.get("/dealer-accounts/export")
def dealer_accounts_export(
    fmt: str = "pdf",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    _require_activity_module(db, user, "truck_accounts")
    owner = _owner_row(db, user)
    report = activity.build_dealer_accounts(db, owner)
    return _activity_export(report, fmt, owner, "dealer-accounts")


@router.get("/checked-out")
def checked_out_report(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    _require_activity_module(db, user, "borrowing")
    return activity.build_checked_out(db, _owner_row(db, user))


@router.get("/checked-out/export")
def checked_out_export(
    fmt: str = "pdf",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    _require_activity_module(db, user, "borrowing")
    owner = _owner_row(db, user)
    report = activity.build_checked_out(db, owner)
    return _activity_export(report, fmt, owner, "checked-out")


@router.get("/lost-stolen")
def lost_stolen_report(
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    start_date, end_date = _parse_period(start, end)
    return activity.build_lost_stolen(
        db, _owner_row(db, user), start=start_date, end=end_date
    )


@router.get("/lost-stolen/export")
def lost_stolen_export(
    fmt: str = "pdf",
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    start_date, end_date = _parse_period(start, end)
    owner = _owner_row(db, user)
    report = activity.build_lost_stolen(db, owner, start=start_date, end=end_date)
    return _activity_export(report, fmt, owner, "lost-stolen")


@router.get("/warranty-claims")
def warranty_claims_report(
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    start_date, end_date = _parse_period(start, end)
    _require_activity_module(db, user, "dealers")
    return activity.build_warranty_claims(
        db, _owner_row(db, user), start=start_date, end=end_date
    )


@router.get("/warranty-claims/export")
def warranty_claims_export(
    fmt: str = "pdf",
    start: str | None = None,
    end: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    start_date, end_date = _parse_period(start, end)
    _require_activity_module(db, user, "dealers")
    owner = _owner_row(db, user)
    report = activity.build_warranty_claims(db, owner, start=start_date, end=end_date)
    return _activity_export(report, fmt, owner, "warranty-claims")


@router.get("/tax-year")
def tax_year_report(
    year: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    return activity.build_tax_year(db, _owner_row(db, user), year)


@router.get("/tax-year/export")
def tax_year_export(
    year: int,
    fmt: str = "pdf",
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.modules.reports import activity

    owner = _owner_row(db, user)
    report = activity.build_tax_year(db, owner, year)
    return _activity_export(report, fmt, owner, f"tax-year-{year}")


class ActivityEmailRequest(BaseModel):
    kind: str
    format: str = "pdf"
    year: int | None = None
    start: str | None = None
    end: str | None = None
    recipient: str | None = None


@router.post("/activity/email")
def email_activity_report(
    payload: ActivityEmailRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Email ANY activity kind (year-end + repair-costs
    included) through the mail seam — the file attached, built
    by the same builder the screen renders."""
    from app.core import notifications
    from app.modules.reports import activity

    builder = activity.ACTIVITY_BUILDERS.get(payload.kind)
    if builder is not None:
        owner_module = ACTIVITY_MODULE_BY_KIND.get(payload.kind)
        if owner_module is not None:
            _require_activity_module(db, user, owner_module)
    if builder is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown activity report kind: {payload.kind}",
        )
    if payload.format not in ("csv", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format must be csv or pdf.",
        )
    start_date, end_date = _parse_period(payload.start, payload.end)
    owner = _owner_row(db, user)
    report = builder(db, owner, year=payload.year, start=start_date, end=end_date)
    content = activity.render_activity(report, payload.format, owner)
    filename = f"{report['kind']}.{exports.EXTENSIONS[payload.format]}"
    sent = notifications.send_email(
        db,
        to=payload.recipient or owner.email,
        subject=f"Toolbox Vault report — {report['title']}",
        body=(
            f"Your {report['title']} report is attached "
            f"({payload.format.upper()}). It was generated from "
            "your Toolbox Vault records just now."
        ),
        kind="report",
        attachment=(filename, content),
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The email couldn't be sent — email delivery isn't available right now.",
        )
    return {"sent": True, "kind": report["kind"], "title": report["title"]}


# -- exports + email -----------------------------------------------------------------


def _export_response(
    db: Session, user: CurrentUser, spec: schemas.ExportRequest, fmt: str, name: str | None
) -> Response:
    try:
        report = service.build_report(
            db,
            user.id,
            spec,
            dealer_visible=_dealer_visible(db, user),
            prepared_for=service.prepared_for_of(_owner_row(db, user)),
        )
    except service.ReportError as exc:
        raise _as_422(exc)
    title = name or "Inventory report"
    content = exports.render(report, fmt, title, _owner_row(db, user))
    filename = exports.report_filename(name, fmt)
    return Response(
        content=content,
        media_type=exports.MIME_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _owner_row(db: Session, user: CurrentUser):
    from app.modules.core import models as core_models

    return db.get(core_models.User, user.id)


@router.post("/export/csv")
def export_csv(
    payload: schemas.ExportRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _export_response(db, user, payload, "csv", None)


@router.post("/export/xlsx")
def export_xlsx(
    payload: schemas.ExportRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _export_response(db, user, payload, "xlsx", None)


@router.post("/export/pdf")
def export_pdf(
    payload: schemas.ExportRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _export_response(db, user, payload, "pdf", None)


@router.post("/email")
def email(
    payload: schemas.EmailRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owner = _owner_row(db, user)
    try:
        return exports.email_report(
            db,
            owner,
            payload,
            payload.format,
            str(payload.recipient) if payload.recipient else None,
            payload.report_name,
            dealer_visible=_dealer_visible(db, user),
        )
    except service.ReportError as exc:
        raise _as_422(exc)


# -- the redesigned page (2026-11-06): type catalog, saved
# templates, generation, and the History --------------------------------
#
# The wizard, Quick Reports / Accounting lists and History tab
# all ride these routes. A catalog type's own module gate (the
# module that owns its books) applies on top of the reports
# module gate the whole router carries — same discipline as the
# activity routes above.

from app.core import storage as storage_mod  # noqa: E402
from app.modules.reports import catalog, library  # noqa: E402


def _is_admin_seat(user: CurrentUser) -> bool:
    """The Admin Reports audience (admin lane, owner 2026-11-06):
    god + moderator_admin rungs, operator flag included — the
    same seats that hold the admin Home widgets."""
    return bool(user.is_operator) or user.tier in ("god", "moderator_admin")


def _type_spec(report_type: str) -> dict | None:
    return catalog.TYPES.get(report_type) or catalog.ADMIN_TYPES.get(
        report_type
    )


def _type_module_on(db: Session, user: CurrentUser, report_type: str) -> bool:
    module_id = _type_spec(report_type)["module"]
    if module_id is None:
        return True
    return module_control.effective_for_user(
        db, module_id, user.account_types, user_id=user.id,
        tier=user.tier, beta_tester=user.beta_tester,
    )


def _gate_type(db: Session, user: CurrentUser, report_type: str) -> None:
    if _type_spec(report_type) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown report type: {report_type}",
        )
    if report_type in catalog.ADMIN_TYPES and not _is_admin_seat(user):
        # Admin datasets refuse everyone else outright — the
        # types don't exist outside admin seats, on any route.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin reports are reserved to the site admins.",
        )
    if not _type_module_on(db, user, report_type):
        module_id = _type_spec(report_type)["module"]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "module_unavailable",
                "module": module_id,
                "message": "This module isn't enabled for your account.",
            },
        )


class DescribeRequest(BaseModel):
    report_type: str
    settings: dict = {}


class TemplateWrite(BaseModel):
    report_type: str
    name: str = ""
    description: str | None = None
    area: str | None = None
    settings: dict = {}


class GenerateRequest(BaseModel):
    report_type: str
    settings: dict = {}
    format: str = "pdf"
    name: str | None = None


class TemplateRunRequest(BaseModel):
    format: str | None = None
    year: int | None = None


class HistoryEmailRequest(BaseModel):
    """The viewer popup's "Email this file" for a history entry:
    the entry's own stored key + a recipient (owner-scoped and
    rate-limited in the library, mirroring the inventory
    attachment email)."""

    key: str = Field(min_length=1)
    recipient: EmailStr


@router.get("/catalog")
def get_catalog(
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    """The wizard's type catalog: every kind, its home area, its
    honest formats and settings, and whether the caller's modules
    let them run it (a gated kind is listed but unavailable — the
    generate routes refuse it the same way)."""
    owner = _owner_row(db, user)
    payload = {
        "types": [
            catalog.type_view(
                key, available=_type_module_on(db, user, key), owner=owner
            )
            for key in catalog.TYPES
        ]
    }
    if _is_admin_seat(user):
        # The admin catalog rides a SEPARATE field, present only
        # for admin seats — a member's response is byte-identical
        # to before, and admin datasets never enter the user list.
        payload["admin_types"] = [
            catalog.type_view(key, available=True, owner=owner)
            for key in catalog.ADMIN_TYPES
        ]
    return payload


@router.post("/describe")
def describe(
    payload: DescribeRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The save step's prefill: the system-written name +
    description for a type + settings, in the owner's locale."""
    if _type_spec(payload.report_type) is None:
        raise _as_422(service.ReportError(f"Unknown report type: {payload.report_type}"))
    _gate_type(db, user, payload.report_type)
    try:
        settings = library.validate_settings(payload.report_type, payload.settings)
    except service.ReportError as exc:
        raise _as_422(exc)
    owner = _owner_row(db, user)
    return {
        "name": catalog.default_name(payload.report_type, settings, owner),
        "description": catalog.default_description(
            payload.report_type, settings, owner
        ),
    }


@router.get("/templates")
def list_templates(
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    owner = _owner_row(db, user)
    return {
        "templates": [
            library.serialize_template(row, owner)
            for row in library.list_templates(db, owner)
        ]
    }


@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateWrite,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _gate_type(db, user, payload.report_type)
    owner = _owner_row(db, user)
    try:
        row = library.create_template(
            db,
            owner,
            report_type=payload.report_type,
            name=payload.name,
            description=payload.description,
            area=payload.area,
            settings=payload.settings,
        )
    except service.ReportError as exc:
        raise _as_422(exc)
    return library.serialize_template(row)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not library.delete_template(db, user.id, template_id):
        raise _not_found()


def _generate_and_record(
    db: Session,
    user: CurrentUser,
    *,
    report_type: str,
    settings: dict,
    fmt: str,
    name: str,
    template_id: uuid.UUID | None = None,
) -> dict:
    owner = _owner_row(db, user)
    try:
        content = library.generate_bytes(
            db, owner, report_type, settings, fmt,
            dealer_visible=_dealer_visible(db, user),
        )
    except service.ReportError as exc:
        raise _as_422(exc)
    try:
        row = library.record_generation(
            db,
            owner,
            report_type=report_type,
            name=name,
            fmt=fmt,
            content=content,
            settings={**settings, "format": fmt},
            template_id=template_id,
        )
    except storage_mod.StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The report was built but its file couldn't be stored.",
        )
    return library.serialize_history(row)


@router.post("/generate", status_code=status.HTTP_201_CREATED)
def generate(
    payload: GenerateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A wizard one-off: build the file, store it, leave its
    History row, and hand the row back (the file itself comes
    from the history download route)."""
    _gate_type(db, user, payload.report_type)
    owner = _owner_row(db, user)
    try:
        settings = library.validate_settings(payload.report_type, payload.settings)
        fmt = library.validate_format(payload.report_type, payload.format)
    except service.ReportError as exc:
        raise _as_422(exc)
    name = (payload.name or "").strip() or catalog.default_name(
        payload.report_type, settings, owner
    )
    return _generate_and_record(
        db, user,
        report_type=payload.report_type, settings=settings, fmt=fmt, name=name,
    )


@router.post("/preview")
def preview(
    payload: GenerateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The wizard's preview step: the ACTUAL document for these
    settings, built and returned — never stored, never a History
    row. The save/generate step is what keeps a file."""
    _gate_type(db, user, payload.report_type)
    owner = _owner_row(db, user)
    try:
        settings = library.validate_settings(payload.report_type, payload.settings)
        fmt = library.validate_format(payload.report_type, payload.format)
        content = library.generate_bytes(
            db, owner, payload.report_type, settings, fmt,
            dealer_visible=_dealer_visible(db, user),
        )
    except service.ReportError as exc:
        raise _as_422(exc)
    filename = exports.report_filename(
        catalog.default_name(payload.report_type, settings, owner), fmt
    )
    return Response(
        content=content,
        media_type=exports.MIME_TYPES[fmt],
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/templates/{template_id}/run", status_code=status.HTTP_201_CREATED)
def run_template(
    template_id: uuid.UUID,
    payload: TemplateRunRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run a saved template against today's data. A year-kind
    template asks its year at run time: the payload's year wins
    over whatever the template stored."""
    row = library.get_template(db, user.id, template_id)
    if row is None:
        raise _not_found()
    _gate_type(db, user, row.report_type)
    settings = dict(row.settings or {})
    if payload.year is not None:
        settings["year"] = payload.year
    try:
        settings = library.validate_settings(row.report_type, settings)
        fmt = library.validate_format(
            row.report_type,
            payload.format or settings.get("format") or "pdf",
        )
    except service.ReportError as exc:
        raise _as_422(exc)
    name = row.name
    if payload.year is not None and (_type_spec(row.report_type) or {}).get("settings") in (
        "year",
        "year_or_all",
    ):
        name = f"{row.name} — {payload.year}"
    return _generate_and_record(
        db, user,
        report_type=row.report_type, settings=settings, fmt=fmt, name=name,
        template_id=row.id,
    )


@router.get("/history")
def list_history(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    format: str | None = None,
    q: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import date as _date

    try:
        day_from = _date.fromisoformat(from_) if from_ else None
        day_to = _date.fromisoformat(to) if to else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be YYYY-MM-DD.",
        )
    if format is not None and format not in ("pdf", "csv", "xlsx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format must be pdf, csv or xlsx.",
        )
    rows = library.list_history(
        db, user.id, day_from=day_from, day_to=day_to, fmt=format, q=q
    )
    return {"entries": [library.serialize_history(row) for row in rows]}


@router.get("/history/{history_id}/download")
def download_history(
    history_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = library.get_history(db, user.id, history_id)
    if row is None:
        raise _not_found()
    try:
        content = storage_mod.storage.fetch(row.storage_key)
    except storage_mod.StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The stored file couldn't be read.",
        )
    filename = exports.report_filename(row.name, row.format)
    return Response(
        content=content,
        media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/history/{history_id}/view")
def view_history(
    history_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = library.get_history(db, user.id, history_id)
    if row is None:
        raise _not_found()
    return {"attachment": library.history_view(row)}


@router.post("/history/{history_id}/email")
def email_history(
    history_id: uuid.UUID,
    payload: HistoryEmailRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Email a generated report's file from the viewer popup —
    the same action a document on a tool offers (Ryan,
    2026-11-07)."""
    owner = _owner_row(db, user)
    try:
        return library.email_history_file(
            db, owner, history_id, key=payload.key, recipient=payload.recipient
        )
    except LookupError:
        raise _not_found()
    except library.EmailRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    except service.ReportError as exc:
        raise _as_422(exc)


@router.delete("/history/{history_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_history_entry(
    history_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not library.delete_history(db, user.id, history_id):
        raise _not_found()
