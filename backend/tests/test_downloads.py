"""Downloads lead magnet: subscribe / unsubscribe / sheet generation.

The public /downloads surfaces (2026-10-29): joining the updates
list must answer the same for new and existing addresses, the
unsubscribe link must work without any account, and every generated
workbook must carry the real wordmark image on BOTH tabs, the
importer's exact labels on the My Tools header row (below the
dashboard band), live totals boxes, and the cover protection
contract.
"""

import io
import uuid

from openpyxl import load_workbook
from sqlalchemy import select

from app.modules.downloads import sheet
from app.modules.downloads.models import DownloadsSubscriber
from app.modules.inventory import importer


def _rows(db):
    return db.scalars(select(DownloadsSubscriber)).all()


def test_subscribe_creates_row_and_dedupes(client, db):
    r1 = client.post("/api/downloads/subscribe", json={"email": "Tech@Example.com"})
    r2 = client.post("/api/downloads/subscribe", json={"email": "tech@example.com"})
    assert r1.status_code == 200 and r1.json() == {"ok": True}
    assert r2.status_code == 200 and r2.json() == {"ok": True}
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].email == "tech@example.com"
    assert rows[0].source == "downloads"
    assert rows[0].unsubscribe_token
    assert rows[0].unsubscribed_at is None


def test_subscribe_invalid_email_422(client, db):
    resp = client.post("/api/downloads/subscribe", json={"email": "not-an-email"})
    assert resp.status_code == 422
    assert _rows(db) == []


def test_subscribe_news_source_marks_row(client, db):
    # The downloads page's voluntary news signup (owner order
    # 2026-11-08) sends source "downloads-news"; the stored row
    # carries that mark so the list knows where a signup came
    # from. The answer is the same {ok: true} as any subscribe.
    resp = client.post(
        "/api/downloads/subscribe",
        json={"email": "news@example.com", "source": "downloads-news"},
    )
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].email == "news@example.com"
    assert rows[0].source == "downloads-news"
    assert rows[0].unsubscribed_at is None


def test_subscribe_news_duplicate_answers_the_same(client, db):
    payload = {"email": "news@example.com", "source": "downloads-news"}
    r1 = client.post("/api/downloads/subscribe", json=payload)
    r2 = client.post("/api/downloads/subscribe", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].source == "downloads-news"


def test_subscribe_unknown_source_clamps_to_downloads(client, db):
    # The source column is a record, not a free-text field: an
    # unrecognized mark lands as the generic "downloads".
    resp = client.post(
        "/api/downloads/subscribe",
        json={"email": "tech@example.com", "source": "carrier-pigeon"},
    )
    assert resp.status_code == 200
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].source == "downloads"


def test_unsubscribe_flow(client, db):
    client.post("/api/downloads/subscribe", json={"email": "tech@example.com"})
    token = _rows(db)[0].unsubscribe_token

    page = client.get(f"/api/downloads/unsubscribe/{token}")
    assert page.status_code == 200
    assert "unsubscribed" in page.text.lower()
    db.expire_all()
    assert _rows(db)[0].unsubscribed_at is not None

    again = client.get(f"/api/downloads/unsubscribe/{token}")
    assert again.status_code == 200

    bogus = client.get("/api/downloads/unsubscribe/definitely-not-a-token")
    assert bogus.status_code == 404


def test_resubscribe_after_unsubscribe(client, db):
    client.post("/api/downloads/subscribe", json={"email": "tech@example.com"})
    token = _rows(db)[0].unsubscribe_token
    client.get(f"/api/downloads/unsubscribe/{token}")
    db.expire_all()
    assert _rows(db)[0].unsubscribed_at is not None

    resp = client.post("/api/downloads/subscribe", json={"email": "tech@example.com"})
    assert resp.status_code == 200
    db.expire_all()
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].unsubscribed_at is None


def _sheet(client, payload):
    resp = client.post("/api/downloads/sheet", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return load_workbook(io.BytesIO(resp.content))


def _band(tools):
    """{box title: formula} from the My Tools dashboard band."""
    titles = [c.value for c in tools[sheet.BOX_LABEL_ROW] if c.value]
    formulas = [c.value for c in tools[sheet.BOX_VALUE_ROW] if c.value]
    return dict(zip(titles, formulas))


def test_sheet_generic(client):
    wb = _sheet(client, {"preset": "generic", "personal_header": True})
    assert wb.sheetnames == ["Start Here", "My Tools"]
    tools = wb["My Tools"]
    labels = [c.value for c in tools[sheet.LABEL_ROW]]
    assert labels == [sheet._LABELS[k] for k in sheet.PRESETS["generic"]]
    assert len(labels) == 13
    # The band: real wordmark image on this tab too, band + header
    # frozen, filter on the header row, labels repeat when printing.
    assert len(tools._images) >= 1
    assert tools.freeze_panes == f"A{sheet.FIRST_DATA_ROW}"
    assert tools.auto_filter.ref.startswith(f"A{sheet.LABEL_ROW}:")
    assert tools.print_title_rows == f"${sheet.LABEL_ROW}:${sheet.LABEL_ROW}"
    assert tools.protection.sheet is False
    # All four totals boxes, live formulas over the data range.
    band = _band(tools)
    assert set(band) == {
        "TOTAL TOOLS",
        "TOTAL QUANTITY",
        "TOTAL PURCHASE VALUE",
        "TOTAL REPLACEMENT VALUE",
    }
    first, last = sheet.FIRST_DATA_ROW, sheet.LAST_DATA_ROW
    assert band["TOTAL TOOLS"] == f"=COUNTA(A{first}:A{last})"
    assert "SUMPRODUCT" in band["TOTAL QUANTITY"]
    assert "SUMPRODUCT" in band["TOTAL PURCHASE VALUE"]
    assert "SUMPRODUCT" in band["TOTAL REPLACEMENT VALUE"]

    cover = wb["Start Here"]
    assert cover.protection.sheet is True
    assert len(cover._images) >= 1
    values = [c.value for row in cover.iter_rows() for c in row if c.value]
    assert not any(v == "TOOLBOX VAULT" for v in values)
    assert any("toolboxvault.com/downloads" in str(v) for v in values)
    assert any("PREPARED FOR" in str(v) for v in values)
    # Name/Brand header row of My Tools untouched by the cover layout.
    assert labels[0] == "Name"


def test_sheet_no_personal_header_omits_section(client):
    wb = _sheet(client, {"preset": "generic"})
    cover = wb["Start Here"]
    values = [c.value for row in cover.iter_rows() for c in row if c.value]
    assert not any("PREPARED FOR" in str(v) for v in values)


def test_sheet_custom_forces_name_and_catalog_order(client):
    wb = _sheet(client, {"preset": "custom", "fields": ["quantity", "brand"]})
    labels = [c.value for c in wb["My Tools"][sheet.LABEL_ROW]]
    assert labels == ["Name", "Brand", "Quantity"]


def test_sheet_presets_sizes(client):
    for preset, count in (("starter", 7), ("insurance", 12), ("everything", 28)):
        wb = _sheet(client, {"preset": preset})
        labels = [c.value for c in wb["My Tools"][sheet.LABEL_ROW]]
        assert len(labels) == count, preset
        assert labels[0] == "Name"


def test_sheet_band_boxes_adapt_to_fields(client):
    # Starter has Quantity but no money columns: two boxes only.
    wb = _sheet(client, {"preset": "starter"})
    band = _band(wb["My Tools"])
    assert set(band) == {"TOTAL TOOLS", "TOTAL QUANTITY"}
    # Price without Quantity: the money column alone is the total.
    wb = _sheet(client, {"preset": "custom", "fields": ["purchase_price"]})
    band = _band(wb["My Tools"])
    assert set(band) == {"TOTAL TOOLS", "TOTAL PURCHASE VALUE"}
    price_col = "B"  # Name, Purchase price (each)
    assert band["TOTAL PURCHASE VALUE"] == (
        f"=SUM({price_col}{sheet.FIRST_DATA_ROW}:{price_col}{sheet.LAST_DATA_ROW})"
    )
    # Name alone: only the tools box survives.
    wb = _sheet(client, {"preset": "custom", "fields": ["brand"]})
    assert set(_band(wb["My Tools"])) == {"TOTAL TOOLS"}


def test_sheet_cover_totals_point_at_band(client):
    wb = _sheet(client, {"preset": "generic"})
    cover = wb["Start Here"]
    refs = {
        c.value
        for row in cover.iter_rows()
        for c in row
        if isinstance(c.value, str) and c.value.startswith("='My Tools'!")
    }
    tools = wb["My Tools"]
    box_value_cells = {
        c.coordinate
        for c in tools[sheet.BOX_VALUE_ROW]
        if isinstance(c.value, str) and c.value.startswith("=")
    }
    pointed = {ref.split("!")[1] for ref in refs}
    # Quantity, purchase and replacement totals all mirror a box.
    assert len(refs) == 3
    assert pointed <= box_value_cells


def test_sheet_bad_preset_400(client):
    resp = client.post("/api/downloads/sheet", json={"preset": "nope"})
    assert resp.status_code == 400


def test_catalog_matches_importer():
    importer_pairs = [(k, label) for k, label, _t, _r in importer._COMMON_FIELDS]
    importer_pairs += [(k, label) for k, label, _t, _r in importer._TOOL_FIELDS]
    assert sheet.FIELD_CATALOG == importer_pairs


def test_sheet_generic_columns_all_auto_suggest(client, db):
    """A banded Generic file comes back through the importer with
    every column auto-suggested: header detection finds the label
    row below the band, and all 13 verbatim catalog labels map —
    including "Purchase price (each)" and "Notes / description",
    whose normalized forms needed their own synonym entries."""
    resp = client.post("/api/downloads/sheet", json={"preset": "generic"})
    assert resp.status_code == 200, resp.text
    _fmt, headers, _data_rows = importer.parse_spreadsheet(
        "Toolbox-Vault-Tool-Inventory.xlsx", resp.content
    )
    keys = sheet.PRESETS["generic"]
    assert headers == [sheet._LABELS[k] for k in keys]
    fields = importer.field_catalog(db, uuid.uuid4(), "tool")
    suggestions = importer.suggest_mapping(headers, fields)
    assert suggestions == {index: key for index, key in enumerate(keys)}
