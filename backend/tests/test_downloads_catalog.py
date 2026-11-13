"""Downloads documents catalog (owner order 2026-11-08): the
public shelf behind the /downloads page's Documents tab.

Proves:
- the catalog lists the nine shelf files in shelf order, each
  with its format, its saved-as filename, and a live count;
- a download serves the file's real bytes with the right media
  type and Content-Disposition, and the count moves by exactly
  one per download — signed-out (these calls carry no auth);
- an unknown key is a plain 404 and moves nothing;
- the packaged inventory sheet is the production capture of
  the sheet the old page served (byte-identical);
- the two spreadsheets carry their working formulas.
"""

from pathlib import Path

from sqlalchemy import select

from app.modules.downloads import catalog as catalog_def
from app.modules.downloads import service
from app.modules.downloads.models import DownloadFile

_FILES_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "downloads" / "files"

EXPECTED_KEYS = [entry.key for entry in catalog_def.CATALOG]


def test_catalog_lists_the_whole_shelf_in_order(client):
    res = client.get("/api/downloads/catalog")
    assert res.status_code == 200
    files = res.json()["files"]
    assert [f["key"] for f in files] == EXPECTED_KEYS
    assert len(files) == 9
    for f in files:
        entry = catalog_def.BY_KEY[f["key"]]
        assert f["format"] == entry.file_format
        assert f["filename"] == entry.filename
        assert f["download_count"] == 0


def test_download_serves_bytes_and_counts(client, db):
    res = client.get("/api/downloads/files/torque-chart")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert (
        res.headers["content-disposition"]
        == 'attachment; filename="Torque-Conversion-Chart.pdf"'
    )
    assert res.content == (_FILES_DIR / "torque-conversion-chart.pdf").read_bytes()

    res = client.get("/api/downloads/files/torque-chart")
    assert res.status_code == 200
    row = db.scalars(
        select(DownloadFile).where(DownloadFile.key == "torque-chart")
    ).first()
    assert row.download_count == 2
    counts = {f["key"]: f["download_count"] for f in client.get("/api/downloads/catalog").json()["files"]}
    assert counts["torque-chart"] == 2
    assert counts["tool-inventory"] == 0


def test_download_xlsx_media_type_and_bytes(client):
    res = client.get("/api/downloads/files/paycheck-calculator")
    assert res.status_code == 200
    assert res.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert res.content == (
        _FILES_DIR / "paycheck-overtime-calculator.xlsx"
    ).read_bytes()


def test_unknown_key_is_404_and_moves_nothing(client, db):
    res = client.get("/api/downloads/files/not-a-file")
    assert res.status_code == 404
    assert db.scalars(select(DownloadFile)).first() is not None
    total = sum(
        row.download_count for row in db.scalars(select(DownloadFile)).all()
    )
    assert total == 0


def test_inventory_sheet_is_the_production_capture(client):
    """The catalog's inventory sheet is byte-identical to the
    file the old page served — its sha256 is the capture taken
    from production before this lane touched anything (the
    builder is not byte-deterministic across calls: embedded
    timestamps; the capture is the ground truth)."""
    import hashlib

    res = client.get("/api/downloads/files/tool-inventory")
    assert res.status_code == 200
    digest = hashlib.sha256(res.content).hexdigest()
    assert digest == (
        "dff2396c566a5f9de4e86320371a3826da8e"
        "5422c128a7507b08ac1aa416a8ef"
    )


def test_spreadsheets_carry_working_formulas():
    from openpyxl import load_workbook

    wb = load_workbook(_FILES_DIR / "paycheck-overtime-calculator.xlsx")
    ws = wb.active
    assert ws["B13"].value == "=B5*B6"
    assert ws["B14"].value == "=B5*B7*B8"
    assert ws["B16"].value == "=SUM(B13:B15)"
    assert ws["B18"].value == "=B16*52"

    wb = load_workbook(_FILES_DIR / "flat-rate-hours-tracker.xlsx")
    ws = wb.active
    assert ws["F5"].value == '=IF(OR(D5="",E5="",E5=0),"",D5/E5)'
    assert ws["G5"].value == '=IF(D5="","",D5*$B$2)'
    assert ws["D35"].value == "=SUM(D5:D34)"
    assert ws["F35"].value == '=IF(E35=0,"",D35/E35)'


def test_ensure_catalog_is_idempotent_and_keeps_counts(db):
    service.ensure_catalog(db)
    service.ensure_catalog(db)
    rows = db.scalars(select(DownloadFile)).all()
    assert len(rows) == 9
    row = next(r for r in rows if r.key == "torque-chart")
    row.download_count = 7
    db.commit()
    service.ensure_catalog(db)
    db.expire_all()
    row = db.scalars(
        select(DownloadFile).where(DownloadFile.key == "torque-chart")
    ).first()
    assert row.download_count == 7
