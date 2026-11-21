"""Rebuild Phase 5 — library policy and the review queue.

Pins: a candidate re-sighted by an independent run with the
same complete piece list is corroborated and promoted to
verified; an incomplete or differing re-sight is not; two
verified runs that disagree drop the entry to conflict (it
stops completing lookups) with the challenger filed as
evidence; an admin can approve, reject, and resolve a
conflict either way from the queue.
"""

from app.modules.catalog import library


def _result(models, *, msrp=499.95, price=30.0):
    return {
        "fields": {
            "brand": "Matco Tools",
            "model": "SBUPM246V",
            "name": "24-Piece Socket Set",
            "msrp": msrp,
        },
        "pieces": [
            {"name": m, "model": m, "msrp": price, "image_url": None}
            for m in models
        ],
        "piece_count": len(models),
        "photos": [],
        "specs": {},
        "warranty_type": None,
        "warranty_months": None,
        "warranty_terms": None,
        "source_name": "Matco",
        "source_url": "https://example.com/set",
        "image_url": None,
    }


_MODELS24 = [f"P{i:02d}V" for i in range(24)]


def test_two_run_promotion(db):
    library.record_grounded(db, _result(_MODELS24))
    stored = library.library_result(db, brand="Matco Tools", model="SBUPM246V")
    assert stored["status"] == "candidate"
    assert stored["confirmations"] == 0
    # A second, independent run re-sights the same complete list.
    library.record_grounded(db, _result(_MODELS24))
    stored = library.library_result(db, brand="Matco Tools", model="SBUPM246V")
    assert stored["confirmations"] == 1
    assert stored["status"] == "verified"


def test_no_promotion_for_an_incomplete_resight(db):
    library.record_grounded(db, _result(_MODELS24))
    library.record_grounded(db, _result(_MODELS24[:12]))
    stored = library.library_result(db, brand="Matco Tools", model="SBUPM246V")
    assert stored["status"] == "candidate"
    assert stored["confirmations"] == 0


def test_no_promotion_when_a_piece_is_unpriced(db):
    library.record_grounded(db, _result(_MODELS24))
    unpriced = _result(_MODELS24)
    unpriced["pieces"][3]["msrp"] = None
    library.record_grounded(db, unpriced)
    stored = library.library_result(db, brand="Matco Tools", model="SBUPM246V")
    assert stored["status"] == "candidate"


def test_verified_disagreement_becomes_a_conflict(db):
    library.import_product(
        db,
        {
            "brand": "Matco Tools",
            "model": "SBUPM246V",
            "name": "24-Piece Socket Set",
            "msrp": 499.95,
            "piece_count": 24,
            "pieces": [
                {"name": m, "model": m, "msrp": 30.0} for m in _MODELS24
            ],
        },
        source_name="verified import",
        source_kind="verified",
    )
    challenger = _result(["Q01V", "Q02V"])
    library.record_grounded(
        db, challenger, source_kind="verified"
    )
    stored = library.library_result(db, brand="Matco Tools", model="SBUPM246V")
    assert stored["status"] == "conflict"
    # The stored list survives untouched.
    assert {p["model"] for p in stored["pieces"]} == set(_MODELS24)
    # The entry sits in the review queue as a conflict.
    queue = library.review_queue(db, status="conflict")
    assert len(queue) == 1
    entry_id = queue[0]["id"]
    # The admin keeps the stored list -> verified again.
    resolved = library.resolve_conflict(db, entry_id, keep="stored")
    assert resolved["status"] == "verified"
    assert {p["model"] for p in resolved["pieces"]} == set(_MODELS24)


def test_admin_approve_and_reject(db):
    library.record_grounded(db, _result(_MODELS24[:4]))
    queue = library.review_queue(db)
    assert len(queue) == 1
    entry_id = queue[0]["id"]
    approved = library.set_status(db, entry_id, "verified")
    assert approved["status"] == "verified"
    rejected = library.set_status(db, entry_id, "quarantined")
    assert rejected["status"] == "quarantined"
    assert library.review_queue(db) == []
