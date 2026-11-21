"""Account settings completion (Phase A1): profile name editing,
the sessions list + sign-out controls, the data export (user
backup v1), and self-serve permanent account deletion.

Deletion is tested ONLY on throwaway fixture users created inside
this file — never on shared fixtures.
"""

import io
import itertools
import uuid
import zipfile

import pytest

from app.core.storage import StorageError
from app.modules.billing import models as billing_models
from app.modules.billing import wallet
from app.modules.core import models as core_models
from app.modules.core import service as core_service
from app.modules.dealers import models as dealers_models
from app.modules.inventory import models as inventory_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
PASSWORD = "correct-horse-9"


@pytest.fixture(autouse=True)
def _seed_plans(db):
    db.add(
        billing_models.Plan(
            plan_key="free", name="Free", item_limit=20,
            ai_monthly_credits=0, is_paid=False, sort_order=0,
        )
    )
    db.commit()


@pytest.fixture(autouse=True)
def _account_numbers(monkeypatch):
    # service.create_user needs Postgres nextval() for the account
    # number; SQLite has no sequences, so stub the counter (the
    # established pattern — see test_oauth.py).
    counter = itertools.count(900100)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )


def _signup(db, email, name="Settings User"):
    return core_service.create_user(db, email, name, PASSWORD, [MECHANIC])


def _login(client, email, ua="TestBrowser/1.0"):
    resp = client.post(
        "/api/core/login",
        json={"email": email, "password": PASSWORD},
        headers={"User-Agent": ua},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- profile ---------------------------------------------------------------------


def test_name_is_editable(db, client):
    user = _signup(db, "rename@example.com")
    resp = client.patch(
        "/api/core/me", json={"name": "Renamed Person"}, headers=auth_headers(user)
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Person"
    assert core_service.get_user_by_id(db, user.id).name == "Renamed Person"
    # Email is untouched and not editable through this endpoint.
    assert resp.json()["email"] == "rename@example.com"


def test_blank_name_refused(db, client):
    user = _signup(db, "blank@example.com")
    assert (
        client.patch(
            "/api/core/me", json={"name": "   "}, headers=auth_headers(user)
        ).status_code
        == 422
    )


# -- sessions ----------------------------------------------------------------------


def test_sessions_list_marks_current_and_captures_agent(db, client):
    user = _signup(db, "sessions@example.com")
    tokens = _login(client, "sessions@example.com", ua="PhoneBrowser/2.0")
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Current-Session": tokens["refresh_token"],
    }
    sessions = client.get("/api/core/sessions", headers=headers)
    assert sessions.status_code == 200
    body = sessions.json()
    assert len(body) == 1
    assert body[0]["is_current"] is True
    assert "PhoneBrowser" in body[0]["user_agent"]


def test_revoke_one_session(db, client):
    _signup(db, "multi@example.com")
    first = _login(client, "multi@example.com", ua="First/1.0")
    second = _login(client, "multi@example.com", ua="Second/1.0")
    headers = {
        "Authorization": f"Bearer {first['access_token']}",
        "X-Current-Session": first["refresh_token"],
    }
    body = client.get("/api/core/sessions", headers=headers).json()
    assert len(body) == 2
    other = next(s for s in body if not s["is_current"])

    # Sign out the other session: it leaves the list, mine stays.
    assert (
        client.delete(f"/api/core/sessions/{other['id']}", headers=headers).status_code
        == 204
    )
    remaining = client.get("/api/core/sessions", headers=headers).json()
    assert len(remaining) == 1
    assert remaining[0]["is_current"] is True
    # The signed-out session's refresh token is dead. (Probed LAST:
    # the pre-existing reuse defense treats a revoked token's
    # replay as theft and ends the whole token family.)
    assert (
        client.post(
            "/api/core/refresh", json={"refresh_token": second["refresh_token"]}
        ).status_code
        == 401
    )


def test_revoke_other_sessions(db, client):
    _signup(db, "elsewhere@example.com")
    mine = _login(client, "elsewhere@example.com", ua="Mine/1.0")
    other = _login(client, "elsewhere@example.com", ua="Other/1.0")
    headers = {
        "Authorization": f"Bearer {mine['access_token']}",
        "X-Current-Session": mine["refresh_token"],
    }
    assert len(client.get("/api/core/sessions", headers=headers).json()) == 2
    resp = client.post(
        "/api/core/sessions/revoke-others",
        json={"refresh_token": mine["refresh_token"]},
        headers=headers,
    )
    assert resp.json() == {"ended": 1}
    remaining = client.get("/api/core/sessions", headers=headers).json()
    assert len(remaining) == 1 and remaining[0]["is_current"] is True
    # My own session still refreshes fine (probed before the dead
    # one — see the family-revocation note above).
    assert (
        client.post(
            "/api/core/refresh", json={"refresh_token": mine["refresh_token"]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/core/refresh", json={"refresh_token": other["refresh_token"]}
        ).status_code
        == 401
    )


def test_sessions_are_owner_scoped(db, client):
    mine = _signup(db, "mine@example.com")
    _signup(db, "theirs@example.com")
    _login(client, "theirs@example.com")
    sessions = client.get("/api/core/sessions", headers=auth_headers(mine))
    assert sessions.json() == []


# -- data export ---------------------------------------------------------------------


class _StubStorage:
    """Export storage double: one key fetchable, everything else
    falls back to a manifest link."""

    def fetch(self, key):
        if key.endswith("ok.jpg"):
            return b"fake-jpeg-bytes"
        raise StorageError("stub: not fetchable")

    def presigned_get_url(self, key, expires_in=None):
        # Mirrors the real storage signature (F4-07: callers may pass
        # an explicit lifetime, e.g. the export fallback TTL).
        return f"https://files.example.test/{key}?sig=stub"


def _tool_with_attachment(db, owner_id, name, key):
    tool = inventory_models.Tool(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name=name,
        attachments=[
            {
                "key": key,
                "filename": key.rsplit("/", 1)[-1],
                "kind": "photo",
                "content_type": "image/jpeg",
                "size_bytes": 15,
            }
        ],
    )
    db.add(tool)
    db.commit()
    return tool


def test_export_zip_contents(db, client, monkeypatch):
    from app.modules.core import export as export_module

    monkeypatch.setattr(export_module, "storage", _StubStorage())
    user = _signup(db, "exporter@example.com")
    _tool_with_attachment(db, user.id, "Fetched Wrench", "photos/ok.jpg")
    _tool_with_attachment(db, user.id, "Linked Wrench", "photos/gone.jpg")

    resp = client.get("/api/core/export", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(archive.namelist())
    assert {"account.json", "tools.json", "field_definitions.json",
            "sharing.json", "files_manifest.json"} <= names

    import json

    account = json.loads(archive.read("account.json"))
    assert account["email"] == "exporter@example.com"
    tools = json.loads(archive.read("tools.json"))
    assert {t["name"] for t in tools} == {"Fetched Wrench", "Linked Wrench"}

    manifest = json.loads(archive.read("files_manifest.json"))
    by_name = {m["filename"]: m for m in manifest}
    assert by_name["ok.jpg"]["included"] is True
    fetched_path = by_name["ok.jpg"]["zip_path"]
    assert archive.read(fetched_path) == b"fake-jpeg-bytes"
    assert by_name["gone.jpg"]["included"] is False
    assert by_name["gone.jpg"]["url"].startswith("https://files.example.test/")


def test_export_needs_auth(client):
    assert client.get("/api/core/export").status_code == 401


# -- account deletion ------------------------------------------------------------------


def test_delete_requires_exact_confirmation(db, client):
    user = _signup(db, "careful@example.com")
    resp = client.request(
        "DELETE", "/api/core/me",
        json={"confirmation": "delete"}, headers=auth_headers(user),
    )
    assert resp.status_code == 400
    assert core_service.get_user_by_id(db, user.id) is not None


def test_delete_account_removes_everything(db, client):
    # THROWAWAY fixture user, created only for this test.
    user = _signup(db, "gone@example.com")
    survivor = _signup(db, "survivor@example.com")
    survivor.referred_by_id = user.id
    db.commit()

    tool = inventory_models.Tool(
        id=uuid.uuid4(), owner_id=user.id, name="Doomed Tool"
    )
    db.add(tool)
    db.add(
        core_models.UserPageLayout(user_id=user.id, page_key="home", blocks=[])
    )
    db.commit()
    wallet.credit(db, user.id, amount=7, bucket="banked", reason="grant")
    _login(client, "gone@example.com")

    resp = client.request(
        "DELETE", "/api/core/me",
        json={"confirmation": "DELETE"}, headers=auth_headers(user),
    )
    assert resp.status_code == 204

    # The account and its sessions are gone: the old token is dead.
    assert core_service.get_user_by_id(db, user.id) is None
    assert client.get("/api/core/me", headers=auth_headers(user)).status_code == 401
    from sqlalchemy import select

    assert db.scalars(
        select(inventory_models.Tool).where(
            inventory_models.Tool.owner_id == user.id
        )
    ).first() is None
    assert db.scalars(
        select(billing_models.AiWallet).where(
            billing_models.AiWallet.user_id == user.id
        )
    ).first() is None
    assert db.scalars(
        select(core_models.RefreshToken).where(
            core_models.RefreshToken.user_id == user.id
        )
    ).first() is None
    # The survivor keeps their account; their referral link is nulled.
    db.refresh(survivor)
    assert survivor.referred_by_id is None


def test_delete_account_with_dealer_list_customization(db, client):
    # Regression (2026-11-05): a user who customized their dealer
    # list — hidden brands AND own entries — could not delete
    # their account at all: the deletion cascade never cleared
    # user_dealer_list_hidden / user_dealer_list_entries and both
    # FKs carry no cascade, so the user delete died on
    # user_dealer_list_hidden_user_id_fkey (a production 500).
    # THROWAWAY fixture users, created only for this test.
    user = _signup(db, "customized@example.com")
    bystander = _signup(db, "bystander@example.com")
    company = dealers_models.DealerCompany(
        id=uuid.uuid4(), owner_id=None, name="Directory Brand",
        is_directory=True,
    )
    db.add(company)
    db.commit()
    _login(client, "customized@example.com")
    headers = auth_headers(user)

    resp = client.post(
        "/api/dealers/directory-hidden",
        json={"company_id": str(company.id)}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/dealers/list-entries",
        json={"name": "My Own Entry"}, headers=headers,
    )
    assert resp.status_code == 201, resp.text
    # The bystander hid the same brand: their overlay is theirs.
    db.add(
        dealers_models.DealerListHidden(
            user_id=bystander.id, company_id=company.id
        )
    )
    db.commit()

    resp = client.request(
        "DELETE", "/api/core/me",
        json={"confirmation": "DELETE"}, headers=headers,
    )
    assert resp.status_code == 204, resp.text

    from sqlalchemy import select

    assert core_service.get_user_by_id(db, user.id) is None
    assert client.get("/api/core/me", headers=headers).status_code == 401
    # No orphans: the deleted user's overlay rows are gone...
    assert db.scalars(
        select(dealers_models.DealerListHidden).where(
            dealers_models.DealerListHidden.user_id == user.id
        )
    ).first() is None
    assert db.scalars(
        select(dealers_models.DealerListEntry).where(
            dealers_models.DealerListEntry.user_id == user.id
        )
    ).first() is None
    # ...while the directory company (platform data) and the
    # bystander's own overlay row both survive untouched.
    assert db.get(dealers_models.DealerCompany, company.id) is not None
    assert db.scalars(
        select(dealers_models.DealerListHidden).where(
            dealers_models.DealerListHidden.user_id == bystander.id
        )
    ).first() is not None


def test_delete_account_nulls_representation_verifier(db, client):
    # Regression (2026-11-05, same audit): dealer_company_
    # representations.verified_by_id also carries no FK action
    # and was never nulled, so an operator who had verified an
    # agent's representation could not delete their account
    # either. The representation is the AGENT's record: it keeps
    # its verified standing; only the verifier link nulls.
    agent = _signup(db, "agent@example.com")
    operator = _signup(db, "verifier@example.com")
    company = dealers_models.DealerCompany(
        id=uuid.uuid4(), owner_id=None, name="Rep Brand",
        is_directory=True,
    )
    db.add(company)
    db.flush()
    rep = dealers_models.CompanyRepresentation(
        agent_user_id=agent.id, company_id=company.id,
        verified=True, verified_by_id=operator.id,
    )
    db.add(rep)
    db.commit()
    _login(client, "verifier@example.com")

    resp = client.request(
        "DELETE", "/api/core/me",
        json={"confirmation": "DELETE"}, headers=auth_headers(operator),
    )
    assert resp.status_code == 204, resp.text

    assert core_service.get_user_by_id(db, operator.id) is None
    assert core_service.get_user_by_id(db, agent.id) is not None
    db.refresh(rep)
    assert rep.verified is True
    assert rep.verified_by_id is None


# -- billing summary ---------------------------------------------------------------------


def test_billing_me_summary(db, client):
    user = _signup(db, "summary@example.com")
    for i in range(3):
        db.add(
            inventory_models.Tool(
                id=uuid.uuid4(), owner_id=user.id, name=f"T{i}"
            )
        )
    db.commit()
    resp = client.get("/api/billing/me", headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_key"] == "free"
    assert body["item_limit"] == 20
    assert body["items_total"] == 3
    assert body["items_active"] == 3
    assert body["enforcement_enabled"] is False
    assert body["subscription"] is None
    assert body["referral_paying_count"] == 0
