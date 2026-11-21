"""Rows 219 + 221 — the internal tool library.

Pins:
  - a grounded result is recorded with its pieces, photos,
    specs and warranty, and reads back in the grounded shape;
  - a complete VERIFIED library entry answers run_lookup
    WITHOUT the web walk running at all (the walk stub raises
    if called);
  - a library miss walks and writes back as a CANDIDATE: it
    fills later lookups but never certifies itself, so the
    walk runs again until a verified record exists (rebuild
    Phase 0 — the pre-rebuild write-back answered the next
    lookup by itself, which is how the contaminated
    SBUPM246V list certified itself);
  - a piece list is replaced only by a verified list, and a
    record's trust status never demotes;
  - a partial library entry fills what it has and the walk
    still runs for the rest;
  - the AI supplement never fires on top of a library hit
    (row 213's fence, extended: the library is a real source);
  - entries are found by UPC alone, and a piece's part number
    reverse-finds the sets that contain it (row 217's data);
  - the seed path (import_product) stores through the same
    upsert, and a re-import with newer facts refreshes.
"""

import uuid

import pytest

from app.modules.catalog import grounded, library, lookup
from app.modules.core import models as core_models


@pytest.fixture()
def seeker(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000511",
        email="libseeker@example.com",
        name="Library Seeker",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _grounded_set():
    return {
        "fields": {
            "name": "13 PIECE TORX BIT SOCKET SET",
            "brand": "Matco Tools",
            "model": "SABCTX13VA",
            "category": "Socket set",
            "size": "1/4 in drive",
            "msrp": 169.95,
            "description": "Torx bit sockets.",
            "upc": "012345678905",
        },
        "pieces": [
            {
                "name": "T8 TORX BIT SOCKET",
                "model": "A8TXVA",
                "msrp": 14.95,
                "image_url": "https://img.example/t8.jpg",
            },
            {
                "name": "T10 TORX BIT SOCKET",
                "model": "A10TXVA",
                "msrp": 13.95,
                "image_url": "https://img.example/t10.jpg",
            },
        ],
        "piece_count": 13,
        "photos": ["https://img.example/set.jpg"],
        "specs": {"Finish": "Chrome"},
        "warranty_type": "lifetime",
        "warranty_months": None,
        "warranty_terms": "LIFETIME WARRANTY",
        "source_name": "Matco Tools",
        "source_url": "https://www.matcotools.com/catalog/product/sabctx13va",
        "image_url": "https://img.example/set.jpg",
        "ai_used": False,
    }


def test_record_and_read_round_trip(db):
    assert library.record_grounded(
        db,
        _grounded_set(),
        typed_brand="Matco",
        typed_model="SABCTX13VA",
    )
    result = library.library_result(
        db, brand="Matco Tools", model="sabctx13va"
    )
    assert result is not None
    assert result["fields"]["name"] == "13 PIECE TORX BIT SOCKET SET"
    assert result["fields"]["msrp"] == 169.95
    assert result["piece_count"] == 13
    assert [p["model"] for p in result["pieces"]] == ["A8TXVA", "A10TXVA"]
    assert result["pieces"][0]["msrp"] == 14.95
    assert result["specs"] == {"Finish": "Chrome"}
    assert result["warranty_type"] == "lifetime"
    assert result["source_name"] == "Matco Tools"
    assert result["ai_used"] is False
    # A plain web pull is a candidate, never more (Phase 0).
    assert result["status"] == "candidate"


def test_reverse_lookup_finds_the_set(db):
    library.record_grounded(db, _grounded_set())
    hits = library.sets_containing(db, "a8txva")
    assert len(hits) == 1
    assert hits[0]["fields"]["model"] == "SABCTX13VA"
    assert library.sets_containing(db, "NOSUCHPIECE") == []


def test_found_by_upc_alone(db):
    library.record_grounded(db, _grounded_set())
    result = library.library_result(db, upc="0123 4567 8905")
    assert result is not None
    assert result["fields"]["model"] == "SABCTX13VA"


def test_seed_import_and_refresh(db):
    record = {
        "brand": "Mac Tools",
        "model": "SMUPM96TR",
        "name": "1/4 Drive Universal Impact Socket Set",
        "msrp": 459.99,
        "category": "Socket set",
    }
    assert library.import_product(db, record, source_name="Mac catalog")
    first = library.library_result(db, brand="Mac Tools", model="SMUPM96TR")
    assert first["fields"]["msrp"] == 459.99
    record["msrp"] = 439.99
    assert library.import_product(db, record, source_name="Mac catalog")
    refreshed = library.library_result(
        db, brand="Mac Tools", model="SMUPM96TR"
    )
    assert refreshed["fields"]["msrp"] == 439.99


def _no_web(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("the web walk must not run")

    monkeypatch.setattr(grounded, "grounded_product", _boom)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)


def test_complete_library_entry_answers_without_the_web(db, seeker, monkeypatch):
    # A VERIFIED entry answers alone (rebuild Phase 0: only
    # trusted records may speak as truth — see the candidate
    # tests below for the unproven case).
    library.record_grounded(db, _grounded_set(), source_kind="verified")
    _no_web(monkeypatch)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=True
    )
    assert result["fields"]["name"]["source"] == "library"
    assert result["fields"]["msrp"]["value"] == 169.95
    assert [p["model"] for p in result["pieces"]] == ["A8TXVA", "A10TXVA"]
    assert result["piece_count"] == 13
    assert result["source_name"] == "Matco Tools"


def test_miss_walks_writes_back_as_candidate_until_verified(
    db, seeker, monkeypatch
):
    # Rebuild Phase 0 contract: a walk writes back as a
    # CANDIDATE — it fills later lookups but never certifies
    # itself, so the walk runs again. Only a verified record
    # answers alone. (Pre-rebuild, the write-back answered the
    # next lookup by itself: the self-certification that let
    # the contaminated SBUPM246V list into the library.)
    calls = {"count": 0}

    def fake_grounded(db_, **kwargs):
        calls["count"] += 1
        return _grounded_set()

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    first = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=False
    )
    assert calls["count"] == 1
    assert first["fields"]["name"]["source"] == "web"
    stored = library.library_result(db, brand="Matco", model="SABCTX13VA")
    assert stored is not None
    assert stored["status"] == "candidate"

    second = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=True
    )
    assert calls["count"] == 2
    assert len(second["pieces"]) == 2

    library.record_grounded(
        db,
        _grounded_set(),
        typed_brand="Matco",
        typed_model="SABCTX13VA",
        source_kind="verified",
    )

    def _boom(*args, **kwargs):
        raise AssertionError("verified lookup must come from the library")

    monkeypatch.setattr(grounded, "grounded_product", _boom)
    third = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=True
    )
    assert third["fields"]["name"]["source"] == "library"
    assert len(third["pieces"]) == 2


def test_partial_entry_fills_and_the_walk_still_runs(db, seeker, monkeypatch):
    library.import_product(
        db,
        {
            "brand": "Matco Tools",
            "model": "SABCTX13VA",
            "name": "13 PIECE TORX BIT SOCKET SET",
        },
        source_name="Seed catalog",
    )

    def fake_grounded(db_, **kwargs):
        result = _grounded_set()
        result["fields"] = {"category": "Socket set", "msrp": 169.95}
        result["pieces"] = []
        result["piece_count"] = None
        return result

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=False
    )
    assert result["fields"]["name"]["source"] == "library"
    assert result["fields"]["category"]["source"] == "web"


def test_names_only_set_entry_still_walks_and_upgrades(db, seeker, monkeypatch):
    weak = _grounded_set()
    weak["pieces"] = [
        {"name": "T8 TORX BIT SOCKET", "model": None, "msrp": None,
         "image_url": None},
        {"name": "T10 TORX BIT SOCKET", "model": None, "msrp": None,
         "image_url": None},
        {"name": "T15 TORX BIT SOCKET", "model": None, "msrp": None,
         "image_url": None},
    ]
    library.record_grounded(db, weak)

    calls = {"count": 0}

    def fake_grounded(db_, **kwargs):
        calls["count"] += 1
        return _grounded_set()

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=False
    )
    # The names-only entry did NOT count as complete: the walk
    # ran, and its priced pieces are what the user got.
    assert calls["count"] == 1
    assert [p["model"] for p in result["pieces"]] == ["A8TXVA", "A10TXVA"]
    upgraded = library.library_result(db, brand="Matco", model="SABCTX13VA")
    assert [p["model"] for p in upgraded["pieces"]] == ["A8TXVA", "A10TXVA"]


def test_weak_reimport_never_downgrades_rich_pieces(db):
    library.record_grounded(db, _grounded_set())
    weak = _grounded_set()
    weak["pieces"] = [
        {"name": f"PIECE {i}", "model": None, "msrp": None,
         "image_url": None}
        for i in range(5)
    ]
    weak["piece_count"] = 5
    library.record_grounded(db, weak)
    result = library.library_result(db, brand="Matco", model="SABCTX13VA")
    assert [p["model"] for p in result["pieces"]] == ["A8TXVA", "A10TXVA"]
    assert result["piece_count"] == 13


def _set_with_pieces(models):
    result = _grounded_set()
    result["pieces"] = [
        {
            "name": f"PIECE {model}",
            "model": model,
            "msrp": 10.0,
            "image_url": None,
        }
        for model in models
    ]
    return result


def test_candidate_set_fills_but_never_completes(db, seeker, monkeypatch):
    # The incident shape: a candidate set whose pieces are
    # ALL priced would have counted as "complete" under the
    # old priced-half rule and answered alone. Now the walk
    # still runs — the candidate only fills.
    library.record_grounded(db, _grounded_set())
    calls = {"count": 0}

    def fake_grounded(db_, **kwargs):
        calls["count"] += 1
        return _grounded_set()

    monkeypatch.setattr(grounded, "grounded_product", fake_grounded)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)
    lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=True
    )
    assert calls["count"] == 1


def test_only_a_verified_list_replaces_a_list(db):
    library.import_product(
        db,
        {
            "brand": "Matco Tools",
            "model": "SABCTX13VA",
            "name": "13 PIECE TORX BIT SOCKET SET",
            "category": "Socket set",
            "pieces": [
                {"name": "S1", "model": "S1", "msrp": 9.0},
                {"name": "S2", "model": "S2", "msrp": 9.0},
            ],
        },
        source_name="Seed catalog",
    )

    def stored_models():
        result = library.library_result(
            db, brand="Matco Tools", model="SABCTX13VA"
        )
        return [p["model"] for p in result["pieces"]]

    assert stored_models() == ["S1", "S2"]
    # A candidate pull cannot replace the seed list.
    library.record_grounded(db, _set_with_pieces(["W1", "W2"]))
    assert stored_models() == ["S1", "S2"]
    # A verified pass replaces it wholesale.
    library.record_grounded(
        db, _set_with_pieces(["V1", "V2"]), source_kind="verified"
    )
    assert stored_models() == ["V1", "V2"]
    # And a later candidate cannot touch the verified list.
    library.record_grounded(db, _set_with_pieces(["W9"]))
    assert stored_models() == ["V1", "V2"]


def test_status_ladder_never_demotes(db):
    library.import_product(
        db,
        {
            "brand": "Mac Tools",
            "model": "SMUPM96TR",
            "name": "1/4 Drive Universal Impact Socket Set",
            "category": "Socket set",
            "msrp": 459.99,
        },
        source_name="Mac catalog",
    )
    seeded = library.library_result(db, brand="Mac Tools", model="SMUPM96TR")
    assert seeded["status"] == "seed"
    # A candidate pull with different facts changes nothing.
    rogue = _grounded_set()
    rogue["fields"] = {
        "name": "WRONG NAME",
        "brand": "Mac Tools",
        "model": "SMUPM96TR",
        "msrp": 1.0,
    }
    rogue["pieces"] = []
    rogue["piece_count"] = None
    library.record_grounded(db, rogue)
    after = library.library_result(db, brand="Mac Tools", model="SMUPM96TR")
    assert after["status"] == "seed"
    assert after["fields"]["msrp"] == 459.99
    assert after["fields"]["name"] == "1/4 Drive Universal Impact Socket Set"


def test_ai_never_supplements_a_library_hit(db, seeker, monkeypatch):
    # A complete-but-priceless library entry: category/size/msrp
    # gaps the AI assist would normally propose into. On a
    # library hit it must stay silent (row 213's fence).
    library.import_product(
        db,
        {
            "brand": "Matco Tools",
            "model": "SABCTX13VA",
            "name": "13 PIECE TORX BIT SOCKET SET",
            "category": "Socket set",
        },
        source_name="Seed catalog",
    )
    _no_web(monkeypatch)

    def _boom_ai(*args, **kwargs):
        raise AssertionError("the AI assist must not run")

    monkeypatch.setattr(lookup, "_ai_lookup_fields", _boom_ai)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco", model="SABCTX13VA", quick=True
    )
    assert "msrp" not in result["fields"]
    assert result["fields"]["name"]["source"] == "library"
