"""Downloads routes — public, no auth (the lead magnet's whole point).

Surfaces:
- POST /subscribe: join the updates list. Same answer whether the
  address is new or already listed — no membership oracle.
- GET /unsubscribe/{token}: the link target every update email will
  carry; a plain confirmation page, no app shell needed.
- POST /sheet: generate the free inventory workbook.
- GET /catalog: the Documents shelf (2026-11-08) — every file,
  its format, and its live download count.
- GET /files/{key}: download one catalog file. The count moves
  first, then the file serves — for everyone, signed-in or not,
  no email anywhere (owner order 2026-11-08).
- GET /wallpapers + GET /wallpapers/{key}/view/{size}: the
  Wallpaper shelf (Part 3) — the artwork list with counts, and
  uncounted inline views (tile thumbnails and previews);
  wallpaper downloads ride /files/{key} like every file.
- POST /visit: the page's own unique-visitor counter (owner
  order 2026-11-08), mirroring the teaser's — the counting rules
  live in core/teaser.py next to the original.

No physical or mailing address appears on any of these surfaces —
the only address Toolbox Vault publishes is the website (owner
decision, 2026-10-28).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_visitor_token
from app.modules.core import teaser
from app.modules.downloads import catalog as catalog_def
from app.modules.downloads import inspection, schemas, service, sheet

router = APIRouter()

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_PAGE_STYLE = (
    "body{margin:0;font-family:system-ui,sans-serif;background:#141416;"
    "color:#f4f4f5;display:flex;min-height:100vh;align-items:center;"
    "justify-content:center}main{max-width:30rem;padding:2rem;"
    "text-align:center}h1{font-size:1.6rem;margin-bottom:.75rem}"
    "p{color:#d4d4d8;line-height:1.55}a{color:#ff6a00}"
)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title} — Toolbox Vault</title><style>{_PAGE_STYLE}</style>"
        f"</head><body><main><h1>{title}</h1>{body}"
        "<p><a href=\"https://toolboxvault.com/downloads\">toolboxvault.com/downloads</a></p>"
        "</main></body></html>"
    )


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/visit", response_model=schemas.VisitCountView)
def record_visit(request: Request, response: Response, db: Session = Depends(get_db)):
    """The Downloads page's unique-visitor counter (owner order,
    2026-11-08): the teaser page's counter, mirrored — the page
    calls this once on load and renders the returned count as
    bare digits. The counting rules (its own counted cookie,
    the same automation and operator-IP exclusions, its own row
    in the counter table) live in core/teaser.py; here we only
    mint the counted cookie when the service says this browser
    was just counted. No auth: the count is public by design,
    and the response carries nothing but the number."""
    count, counted = teaser.record_downloads_visit(db, request)
    if counted:
        response.set_cookie(
            teaser.DOWNLOADS_COUNT_COOKIE,
            create_visitor_token(),
            max_age=teaser.COUNT_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.app_base_url.startswith("https://"),
            path="/",
        )
    return {"count": count}


@router.post("/subscribe", response_model=schemas.SubscribeResponse)
def subscribe(body: schemas.SubscribeRequest, db: Session = Depends(get_db)):
    service.subscribe(db, body.email, source=body.source)
    return schemas.SubscribeResponse(ok=True)


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    result = service.unsubscribe(db, token)
    if result is None:
        return HTMLResponse(
            _page(
                "That link doesn't look right",
                "<p>This unsubscribe link isn't one we recognize. If you "
                "keep getting email you don't want, the unsubscribe link "
                "at the bottom of any of our emails will work.</p>",
            ),
            status_code=404,
        )
    return HTMLResponse(
        _page(
            "You're unsubscribed",
            "<p>You won't get Toolbox Vault update emails anymore. "
            "The free sheet is still yours to keep, either way.</p>",
        )
    )


@router.get("/catalog", response_model=schemas.CatalogResponse)
def catalog(db: Session = Depends(get_db)):
    return schemas.CatalogResponse(
        files=[
            schemas.CatalogFile(
                key=row.key,
                format=row.file_format,
                filename=row.filename,
                download_count=row.download_count,
            )
            for row in service.list_files(db)
        ]
    )


@router.get("/wallpapers", response_model=schemas.WallpaperCatalogResponse)
def wallpapers(db: Session = Depends(get_db)):
    """The Wallpaper shelf (Part 3): every artwork, its
    per-size dimensions and counts, and the summed count the
    tile shows. Public like everything on this page."""
    return schemas.WallpaperCatalogResponse(
        wallpapers=[
            schemas.WallpaperView(
                key=artwork["key"],
                branded=artwork["branded"],
                category=artwork["category"],
                download_count=artwork["download_count"],
                sizes=[
                    schemas.WallpaperSizeView(**size)
                    for size in artwork["sizes"]
                ],
            )
            for artwork in service.list_wallpapers(db)
        ]
    )


@router.get("/wallpapers/{key}/view/{size}")
def wallpaper_view(key: str, size: str):
    """An UNCOUNTED look at a wallpaper — a tile thumbnail or
    the preview at a device size, served inline. Browsing the
    gallery never moves a counter; only the download path
    (/files/{key}-{size}) does (owner rule: the count is
    downloads)."""
    content = service.read_view_bytes(key, size)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail="That wallpaper isn't on the shelf.",
        )
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'inline; filename="{key}-{size}.jpg"'},
    )


@router.get("/top-window", response_model=schemas.TopWindowResponse)
def top_window(db: Session = Depends(get_db)):
    """The shelf's top downloads over the last 7 days, from
    the dated event record (0098) — the dashboard Downloads
    widget's weekly strip. Public like the rest of the shelf:
    it names only what the shelf itself shows, with counts
    from the same downloads the counters already count."""
    return schemas.TopWindowResponse(**service.top_downloads_window(db))


@router.get("/files/{key}")
def download_file(key: str, db: Session = Depends(get_db)):
    row = service.record_download(db, key)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That file isn't on the downloads shelf.",
        )
    content = service.read_file_bytes(row)
    return Response(
        content=content,
        media_type=catalog_def.MEDIA_TYPES.get(
            row.file_format, "application/octet-stream"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{row.filename}"'
        },
    )


def _inspection_pdf(body: schemas.InspectionRequest) -> bytes:
    try:
        selected = inspection.resolve_selection(body.items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return inspection.build_inspection_pdf(
        selected=selected,
        lang=body.lang,
        shop_name=body.shop_name,
        shop_address=body.shop_address,
        shop_phone=body.shop_phone,
    )


@router.get("/inspection/options")
def inspection_options(lang: str = "en"):
    """The inspection wizard's catalog (owner order 2026-11-09):
    every category and item, named in the visitor's language.
    Public like the rest of this page."""
    return inspection.options_payload(lang)


@router.post("/inspection/preview")
def inspection_preview(body: schemas.InspectionRequest):
    """Generate the customized checklist for the wizard's
    preview step. Looking is not downloading (the wallpaper
    rule): no counter moves here."""
    content = _inspection_pdf(body)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="Vehicle-Inspection-Checklist.pdf"'
        },
    )


@router.post("/inspection/download")
def inspection_download(body: schemas.InspectionRequest, db: Session = Depends(get_db)):
    """The wizard's Download: the count moves through the
    shelf's own machinery against the inspection row first
    (exactly like /files/{key}), then the generated bytes
    serve — never the stored static file."""
    content = _inspection_pdf(body)
    row = service.record_download(db, "inspection-checklist")
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="That file isn't on the downloads shelf.",
        )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{row.filename}"'
        },
    )


@router.post("/sheet")
def download_sheet(body: schemas.SheetRequest):
    try:
        field_keys = sheet.resolve_fields(body.preset, body.fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = sheet.build_sheet(field_keys, personal_header=body.personal_header)
    filename = (
        "Toolbox-Vault-Tool-Inventory.xlsx"
        if body.preset == "generic" and not body.fields
        else "Toolbox-Vault-Custom-Tool-Inventory.xlsx"
    )
    return Response(
        content=content,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
