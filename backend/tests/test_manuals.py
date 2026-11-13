"""Wave 4 — Locate User Manual (owner spec; re-tiered 2026-11-05).

Pins:
  - the corporate directory's own URLs seed the BACKUP LINKS
    tier (their existing website/warranty URLs — no invented
    deep links): the owner ruled 2026-11-05 that links are the
    fallback for when no manual can be pulled, never the
    headline result;
  - a document is offered as a FOUND MANUAL only after the
    guarded probe proves the bytes at its address are a PDF —
    an unverifiable address is not a result;
  - discovery is keyless (public engine pages + page mining +
    manufacturer patterns), and the AI seam's web search, when
    configured, feeds the same probe as one more source;
  - NOTHING auto-imports: candidates only, until the user picks;
  - import downloads server-side and stores a MANUAL
    attachment with provenance (origin/source_url/source_name/
    fetched_at/content hash) — manuals are their own kind/area
    since the owner ruling 2026-11-03 (they filed as documents
    before it);
  - add-by-link (same ruling): a pasted address is fetched
    through the same guard; PDFs only; failures file nothing;
  - dedupe by source URL, then by content hash — the second
    import answers already_present instead of a second copy;
  - SSRF guards: non-https, private and loopback hosts, and
    non-document content are refused;
  - the wizard door (POST /manual-lookup) searches by the
    draft's brand + model; searches carry a per-user budget;
  - the inbox hears BOTH outcomes: saved -> the success note,
    no pullable manual -> "No manual found for <brand> <model>".

Storage + DNS + the AI transport + the keyless discovery
transport are stubbed — no real network anywhere in this file.
"""

import uuid

import pytest

from app.core import storage
from app.modules.catalog import manuals
from app.modules.core import models as core_models
from app.modules.dealers import models as dealer_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PDF_BYTES = b"%PDF-1.4\n%fake-manual-bytes\n" + b"x" * 64


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Manual User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000431", "manuals@example.com")


@pytest.fixture()
def tool(client, owner):
    resp = client.post(
        "/api/inventory",
        json={
            "name": "Torque wrench",
            "brand": "Snap-on",
            "model": "QD3R250",
            "category": "Torque",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def directory_brand(db):
    corp = dealer_models.DealerCompany(
        id=uuid.uuid4(),
        owner_id=None,
        is_directory=True,
        name="Snap-on Incorporated",
        website="https://www.snapon.com",
        warranty_url="https://www.snapon.com/warranty-info",
    )
    db.add(corp)
    db.commit()
    return corp


@pytest.fixture(autouse=True)
def _offline_discovery(monkeypatch):
    """Keyless discovery must never touch the real network from
    tests: engine and mining fetches read as empty pages and
    every probe fails closed (nothing is pullable). Tests that
    exercise discovery stub these seams themselves."""
    monkeypatch.setattr(manuals, "_fetch_text", lambda *a, **k: "")
    monkeypatch.setattr(manuals, "_probe_document", lambda url: None)


@pytest.fixture()
def fake_storage(monkeypatch):
    """Object storage captured in memory — the manuals service
    calls the storage SINGLETON's methods, so the stub patches
    the instance, not the module."""
    stored: dict[str, bytes] = {}

    def put_bytes(key, data, content_type):
        stored[key] = bytes(data)
        return storage.StoredObject(
            key=key, size_bytes=len(data), content_type=content_type
        )

    monkeypatch.setattr(storage.storage, "put_bytes", put_bytes)
    return stored


def _public_ip(monkeypatch, *ips):
    monkeypatch.setattr(manuals, "_host_ips", lambda host: list(ips))


def _inbox(db, user_id):
    from app.modules.core import inbox

    return inbox.list_for_user(db, user_id)


def test_directory_entry_seeds_the_backup_links(
    client, owner, tool, directory_brand
):
    """Owner re-tier (2026-11-05): the directory's own entry is
    a go-look-yourself LINK — it leads the backup tier and is
    never offered as a found manual."""
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidates"] == []
    links = body["links"]
    assert links[0]["source_name"] == "Snap-on Incorporated"
    # Seeded from the row's own warranty URL — nothing invented.
    assert links[0]["source_url"] == "https://www.snapon.com/warranty-info"
    assert links[0]["file_type"] == "web"
    assert links[0]["importable"] is False


def test_links_use_refreshed_warranty_url_for_harbor_freight(
    client, db, owner
):
    """A12 regression pin, re-tiered: Harbor Freight's directory row
    carried NO warranty URL before the 0043 refresh (Locate Manual
    fell back to the bare homepage). With the verified warranty URL
    seeded, the manufacturer's backup link points at it."""
    db.add(
        dealer_models.DealerCompany(
            id=uuid.uuid4(),
            owner_id=None,
            is_directory=True,
            name="Harbor Freight Tools",
            website="https://www.harborfreight.com",
            warranty_url=(
                "https://www.harborfreight.com/media/catalog/product/"
                "w/a/warranty-hand-tools.pdf"
            ),
        )
    )
    db.commit()
    resp_tool = client.post(
        "/api/inventory",
        json={"name": "Floor jack", "brand": "Harbor Freight", "model": "HJ-3T"},
        headers=auth_headers(owner),
    )
    assert resp_tool.status_code == 201, resp_tool.text
    resp = client.post(
        f"/api/inventory/tools/{resp_tool.json()['id']}/locate-manual",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidates"] == []
    links = body["links"]
    assert links[0]["source_name"] == "Harbor Freight Tools"
    assert links[0]["source_url"].endswith("warranty-hand-tools.pdf")


def test_no_candidates_sends_the_not_found_notice(client, db, owner):
    resp_tool = client.post(
        "/api/inventory",
        json={"name": "Odd tool", "brand": "NoName", "model": "X-1"},
        headers=auth_headers(owner),
    )
    tool_id = resp_tool.json()["id"]
    resp = client.post(
        f"/api/inventory/tools/{tool_id}/locate-manual",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []
    notes = [e for e in _inbox(db, owner.id) if e["kind"] == "manual_not_found"]
    assert notes, "the not-found outcome must reach the inbox"
    assert "No manual found for NoName X-1" in notes[0]["body"]


def test_ai_layer_feeds_probe_and_links(
    client, db, owner, tool, directory_brand, monkeypatch
):
    """The AI seam's web search (one-vendor decision, 2026-10-25)
    is one discovery source among several: with the AI configured,
    its PDF citations face the same probe as every other source
    and its page citations join the backup links behind the
    manufacturer's own entry."""
    from app.modules.billing import ai_service, entitlements

    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "MANUAL_TEST_AI_KEY")
    monkeypatch.setenv("MANUAL_TEST_AI_KEY", "ai-key-not-real")
    db.commit()

    def fake_transport(url, headers, body, timeout=None):
        assert url.endswith("/responses")
        assert "QD3R250" in body["input"]
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Found the manual.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "QD3R250 Owner's Manual (PDF)",
                                    "url": "https://manuals.example.com/qd3r250.pdf?utm_source=openai",
                                },
                                {
                                    "type": "url_citation",
                                    "title": "Some blog post",
                                    "url": "https://blog.example.com/qd3r250-review",
                                },
                            ],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(ai_service, "_transport", fake_transport)
    monkeypatch.setattr(
        manuals,
        "_probe_document",
        lambda url: (
            {"size_bytes": 4242} if "manuals.example.com" in url else None
        ),
    )
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual",
        headers=auth_headers(owner),
    )
    body = resp.json()
    candidates = body["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["file_type"] == "pdf"
    assert candidates[0]["importable"] is True
    assert candidates[0]["source_name"] == "manuals.example.com"
    assert candidates[0]["size_bytes"] == 4242
    links = body["links"]
    assert links[0]["source_name"] == "Snap-on Incorporated"
    assert any(link["source_name"] == "blog.example.com" for link in links)


def test_import_stores_manual_with_provenance(
    client, db, owner, tool, directory_brand, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")

    def fake_download(url):
        return PDF_BYTES, "application/pdf"

    monkeypatch.setattr(manuals, "_download", fake_download)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": "https://manuals.example.com/qd3r250.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["already_present"] is False
    attachment = body["attachment"]
    assert attachment["kind"] == "manual"
    assert attachment["origin"] == "manual"
    assert attachment["source_url"] == "https://manuals.example.com/qd3r250.pdf"
    assert attachment["fetched_at"]
    assert fake_storage != {}
    # The item's attachment list shows it with the provenance —
    # under manuals, NOT documents.
    detail = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert [a for a in detail["attachments"] if a["kind"] == "document"] == []
    docs = [a for a in detail["attachments"] if a["kind"] == "manual"]
    assert len(docs) == 1
    assert docs[0]["source_url"] == attachment["source_url"]
    # And the inbox got the success note.
    notes = [e for e in _inbox(db, owner.id) if e["kind"] == "manual_saved"]
    assert notes
    assert "Torque wrench" in notes[0]["body"]


def test_import_dedupes_by_url_then_by_hash(
    client, db, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        manuals, "_download", lambda url: (PDF_BYTES, "application/pdf")
    )
    first = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": "https://manuals.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert first.json()["already_present"] is False
    same_url = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": "https://manuals.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert same_url.json()["already_present"] is True
    # Same bytes under a DIFFERENT url: hash dedupe catches it.
    same_bytes = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": "https://mirror.example.com/b.pdf"},
        headers=auth_headers(owner),
    )
    assert same_bytes.json()["already_present"] is True
    row = db.get(inventory_models.Tool, uuid.UUID(tool["id"]))
    manuals_only = [a for a in row.attachments if a.get("origin") == "manual"]
    assert len(manuals_only) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://manuals.example.com/a.pdf",  # not https
        "https://localhost/a.pdf",  # loopback name
        "https://127.0.0.1/a.pdf",  # loopback literal
    ],
)
def test_import_refuses_unsafe_urls(client, owner, tool, monkeypatch, url):
    _public_ip(monkeypatch, "127.0.0.1")
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": url},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text


def test_import_refuses_private_resolution(client, owner, tool, monkeypatch):
    _public_ip(monkeypatch, "10.0.0.5")
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": "https://sneaky.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_import_refuses_non_document_content(
    client, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        manuals, "_download", lambda url: (b"<html>nope</html>", "text/html")
    )
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import",
        json={"source_url": "https://manuals.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422


def test_locate_on_foreign_item_is_404(client, db, owner, tool):
    stranger = _make_user(db, "TV-M-000432", "stranger2@example.com")
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual",
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 404


# -- add a manual by link (owner ruling 2026-11-03) ----------------


def _attachments(client, owner, tool_id):
    detail = client.get(
        f"/api/inventory/{tool_id}", headers=auth_headers(owner)
    ).json()
    return detail["attachments"]


def test_import_link_stores_pdf_as_manual(
    client, db, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        manuals, "_download", lambda url: (PDF_BYTES, "application/pdf")
    )
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "https://manuals.example.com/qd3r250.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["already_present"] is False
    attachment = body["attachment"]
    assert attachment["kind"] == "manual"
    assert attachment["origin"] == "manual"
    assert attachment["filename"] == "qd3r250.pdf"
    assert attachment["content_type"] == "application/pdf"
    assert list(fake_storage.values()) == [PDF_BYTES]
    assert len(_attachments(client, owner, tool["id"])) == 1


def test_import_link_accepts_a_schemeless_address(
    client, db, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")
    seen = {}

    def fake_download(url):
        seen["url"] = url
        return PDF_BYTES, "application/pdf"

    monkeypatch.setattr(manuals, "_download", fake_download)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "manuals.example.com/qd3r250.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert seen["url"] == "https://manuals.example.com/qd3r250.pdf"


def test_import_link_refuses_an_html_page_and_files_nothing(
    client, db, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        manuals, "_download", lambda url: (b"<html>nope</html>", "text/html")
    )
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "https://manuals.example.com/qd3r250"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    assert _attachments(client, owner, tool["id"]) == []
    assert fake_storage == {}


def test_import_link_refuses_a_dead_address_and_files_nothing(
    client, db, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")

    def dead(url):
        raise manuals.ManualError("The source answered HTTP 404.")

    monkeypatch.setattr(manuals, "_download", dead)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "https://manuals.example.com/gone.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    assert "404" in resp.json()["detail"]
    assert _attachments(client, owner, tool["id"]) == []
    assert fake_storage == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://manuals.example.com/a.pdf",  # not https
        "https://localhost/a.pdf",  # loopback name
        "https://127.0.0.1/a.pdf",  # loopback literal
    ],
)
def test_import_link_refuses_unsafe_urls(client, owner, tool, monkeypatch, url):
    # The REAL download path runs here (only DNS is stubbed): the
    # guard must refuse before any bytes move.
    _public_ip(monkeypatch, "127.0.0.1")
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": url},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    assert _attachments(client, owner, tool["id"]) == []


def test_import_link_refuses_private_resolution(
    client, owner, tool, monkeypatch
):
    _public_ip(monkeypatch, "10.0.0.5")
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "https://sneaky.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    assert _attachments(client, owner, tool["id"]) == []


def test_import_link_dedupes_repeat_adds(
    client, db, owner, tool, monkeypatch, fake_storage
):
    _public_ip(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        manuals, "_download", lambda url: (PDF_BYTES, "application/pdf")
    )
    first = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "https://manuals.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert first.json()["already_present"] is False
    again = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual/import-link",
        json={"url": "https://manuals.example.com/a.pdf"},
        headers=auth_headers(owner),
    )
    assert again.json()["already_present"] is True
    assert len(_attachments(client, owner, tool["id"])) == 1


# -- keyless discovery + the wizard door (owner re-tier, 2026-11-05) ----------


def _yahoo_page(*entries):
    """A minimal Yahoo results page: (url, title) pairs wrapped
    in Yahoo's RU= redirect hrefs — the exact shape the parser
    reads in production."""
    from urllib.parse import quote

    anchors = []
    for url, title in entries:
        wrapped = (
            "https://r.search.yahoo.com/_ylt=Test/RV=2/RE=1/RO=10/RU="
            + quote(url, safe="")
            + "/RK=2/RS=abc-"
        )
        anchors.append(
            f'<div class="compTitle"><a href="{wrapped}">{title}</a></div>'
        )
    return "<html><body>" + "".join(anchors) + "</body></html>"


def _engines(monkeypatch, yahoo_html):
    def fake_fetch(url, timeout=None):
        if "search.yahoo.com" in url:
            return yahoo_html
        return ""

    monkeypatch.setattr(manuals, "_fetch_text", fake_fetch)


def _dewalt_tool(client, owner):
    resp_tool = client.post(
        "/api/inventory",
        json={"name": "Impact wrench", "brand": "DeWalt", "model": "DCF891B"},
        headers=auth_headers(owner),
    )
    assert resp_tool.status_code == 201, resp_tool.text
    return resp_tool.json()


def test_keyless_candidate_offered_once_proven(client, db, owner, monkeypatch):
    """The keyless engines surface the document address; the
    guarded probe proves it; only then is it offered as a
    found manual — with its size."""
    pdf_url = "https://assets.dewalt.com/manuals/NA537404_DCF891.pdf"
    _public_ip(monkeypatch, "93.184.216.34")
    _engines(
        monkeypatch,
        _yahoo_page((pdf_url, "DeWalt DCF891 Instruction Manual")),
    )
    monkeypatch.setattr(
        manuals,
        "_probe_document",
        lambda url: {"size_bytes": 98765} if url == pdf_url else None,
    )
    tool = _dewalt_tool(client, owner)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["candidates"]) == 1
    found = body["candidates"][0]
    assert found["source_url"] == pdf_url
    assert found["importable"] is True
    assert found["size_bytes"] == 98765
    # A proven manual never also appears dressed as a link.
    assert all(link["source_url"] != pdf_url for link in body["links"])


def test_unproven_candidate_is_never_offered(client, db, owner, monkeypatch):
    """Same discovery, but the probe says no (dead address, or
    the bytes are not a PDF): the candidate vanishes, the
    answer is the honest no-manual state, and the inbox
    hears it."""
    pdf_url = "https://assets.dewalt.com/manuals/NA000000_GONE.pdf"
    _public_ip(monkeypatch, "93.184.216.34")
    _engines(monkeypatch, _yahoo_page((pdf_url, "DeWalt manual")))
    # _probe_document stays the autouse fail-closed stub.
    tool = _dewalt_tool(client, owner)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"] == []
    notes = [e for e in _inbox(db, owner.id) if e["kind"] == "manual_not_found"]
    assert notes, "no pullable manual must reach the inbox as not-found"


def test_wizard_search_by_brand_and_model(client, db, owner, monkeypatch):
    """The wizard door: brand + model from the draft, no item
    exists — same machinery, same tiers. An empty search is a
    422, and the door needs a signed-in user."""
    pdf_url = "https://assets.dewalt.com/manuals/NA537404_DCF891.pdf"
    _public_ip(monkeypatch, "93.184.216.34")
    _engines(
        monkeypatch,
        _yahoo_page((pdf_url, "DeWalt DCF891 Instruction Manual")),
    )
    monkeypatch.setattr(
        manuals,
        "_probe_document",
        lambda url: {"size_bytes": 98765} if url == pdf_url else None,
    )
    resp = client.post(
        "/api/inventory/manual-lookup",
        json={"brand": "DeWalt", "model": "DCF891B"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    candidates = resp.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["source_url"] == pdf_url

    empty = client.post(
        "/api/inventory/manual-lookup",
        json={"brand": "", "model": ""},
        headers=auth_headers(owner),
    )
    assert empty.status_code == 422

    anon = client.post(
        "/api/inventory/manual-lookup",
        json={"brand": "DeWalt", "model": "DCF891B"},
    )
    assert anon.status_code == 401


def test_manual_search_budget_refuses_past_the_cap(
    client, db, owner, tool, directory_brand
):
    """The per-user search budget (30/hour): past it, the door
    answers 429 instead of fanning out to the engines again."""
    from app.core.rate_limit import manual_lookup_rate_limiter

    key = f"manual-lookup:{owner.id}"
    for _ in range(30):
        manual_lookup_rate_limiter.record_hit(key)
    resp = client.post(
        f"/api/inventory/tools/{tool['id']}/locate-manual",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 429


def test_unrelated_verified_pdf_is_not_offered(client, db, owner, monkeypatch):
    """Production proof (2026-11-05) caught this live: a
    nonsense search surfaced a mutual-fund form PDF whose
    address merely shared the model's number ("999_manual").
    It IS a real, pullable PDF — and it is not a manual for
    the item, so the relevance gate keeps it out even though
    the probe passes."""
    pdf_url = "https://www.aisus.com/forms/2/999_manual.pdf"
    _public_ip(monkeypatch, "93.184.216.34")
    _engines(monkeypatch, _yahoo_page((pdf_url, "YOUR MUTUAL MANUAL")))
    monkeypatch.setattr(
        manuals, "_probe_document", lambda url: {"size_bytes": 7199}
    )
    resp = client.post(
        "/api/inventory/manual-lookup",
        json={"brand": "Zzzcorp", "model": "QQQ-999"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"] == []


def test_display_title_prefers_the_filename_for_breadcrumb_anchors():
    """Yahoo's document anchors are breadcrumbs, not titles."""
    url = (
        "https://assets.dewalt.com/GLOBALBOM/QU/DCF891B/1/"
        "Instruction_Manual/EN/NA006214_man_cordless_impactors_NA.pdf"
    )
    title = manuals._display_title(
        "assets.dewalt.com https://assets.dewalt.com › GLOBALBOM › QU",
        url,
        "assets.dewalt.com",
    )
    assert title == "NA006214_man_cordless_impactors_NA.pdf"
    # A real title survives untouched.
    assert (
        manuals._display_title(
            "QD3R250 Owner's Manual (PDF)",
            "https://manuals.example.com/qd3r250.pdf",
            "manuals.example.com",
        )
        == "QD3R250 Owner's Manual (PDF)"
    )


def test_mined_documents_must_name_the_model_family(
    client, db, owner, monkeypatch
):
    """Production proof (2026-11-05): a DeWalt search surfaced a
    SIBLING product's page, and mining offered that tool's
    manual (DCS354) for a DCF891B. Mined documents now earn
    their place only by naming the model — or its family stem,
    since the DCF891B's own manual is filed as DCF891_DCF892."""
    product_url = "https://www.dewalt.com/product/dcs354b"
    family_pdf = (
        "https://assets.dewalt.com/GLOBALBOM/QU/DCF892B/1/"
        "Instruction_Manual/EN/NA537404_DCF891_DCF892_NA.pdf"
    )
    sibling_pdf = "https://assets.dewalt.com/manuals/DCS354_DCS356.pdf"
    _public_ip(monkeypatch, "93.184.216.34")

    def fake_fetch(url, timeout=None):
        if "search.yahoo.com" in url:
            return _yahoo_page((product_url, "DeWALT product page"))
        if "dewalt.com/product" in url:
            return (
                f'<a href="{sibling_pdf}">sibling</a>'
                f'<a href="{family_pdf}">family</a>'
            )
        return ""

    monkeypatch.setattr(manuals, "_fetch_text", fake_fetch)
    monkeypatch.setattr(
        manuals,
        "_probe_document",
        lambda url: {"size_bytes": 1000},
    )
    resp = client.post(
        "/api/inventory/manual-lookup",
        json={"brand": "DeWalt", "model": "DCF891B"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    urls = [c["source_url"] for c in resp.json()["candidates"]]
    assert family_pdf in urls
    assert sibling_pdf not in urls


def test_same_brand_wrong_model_is_not_offered(client, db, owner, monkeypatch):
    """Production proof (2026-11-05): a repository PDF for a
    DIFFERENT DeWalt model ("DCS354, DCS356") was offered for a
    DCF891B because brand + the word 'manual' was enough. With
    a model given, an off-manufacturer document must name the
    model (or its family stem) itself."""
    pdf_url = "https://manuals.plus/dewalt/dcs354-dcs356-manual.pdf"
    _public_ip(monkeypatch, "93.184.216.34")
    _engines(monkeypatch, _yahoo_page((pdf_url, "DCS354, DCS356")))
    monkeypatch.setattr(
        manuals, "_probe_document", lambda url: {"size_bytes": 5000}
    )
    resp = client.post(
        "/api/inventory/manual-lookup",
        json={"brand": "DeWalt", "model": "DCF891B"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"] == []
