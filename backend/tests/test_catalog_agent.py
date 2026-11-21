"""Rebuild Phase 3 — the agent loop, driven by a scripted
driver model (the transport seam is stubbed; no live AI).

The script walks the SBUPM246V shape end to end: open the
page, read the recorded data response (12 of 24 — Matco's
rotating slice), replay it for the other 12, submit the full
24. The referee must verify, the run must return the 24, and
through run_lookup the library must record the entry as
VERIFIED — the first write path that can earn that status.

A second script submits the contaminated list instead: the
referee rejects the cross-sell pieces, the same submit comes
back unchanged, and the loop ends honestly partial.
"""

import json
import uuid

import pytest

from app.modules.billing import ai_service
from app.modules.catalog import agent, grounded, library, lookup
from app.modules.core import models as core_models

_PAGE = """
<html><head><title>SBUPM246V 24-Piece Socket Set</title></head>
<body><main>
  <h1>24-Piece 3/8 Drive ADV Universal Impact Socket Set</h1>
  <section class="product-details"><h2>Set Details</h2>
    <div class="piece-grid">
      <div class="card"><a href="/p/bup10m6v">BUP10M6V socket</a> $31.95</div>
      <div class="card"><a href="/p/bup11m6v">BUP11M6V socket</a> $35.95</div>
      <div class="card"><a href="/p/bxp6v">BXP6V extension</a> $20.95</div>
    </div>
  </section>
  <aside class="rail"><h2>Similar Products</h2>
    <div class="card"><a href="/p/mt4779p">MT4779P impact wrench</a> $499.95</div>
  </aside>
</main></body></html>
"""

_STANDARD = [f"BUP{i}M6V" for i in range(10, 20)]
_DEEP = [f"BDUP{i}M6V" for i in range(10, 20)]
_ALL24 = _STANDARD + _DEEP + ["BXP3V", "BXP6V", "BXP12V", "BUP2BV"]


def _name(model):
    if model.startswith("BDUP"):
        return f"{model[4:-3]}MM DEEP UNIVERSAL IMPACT SOCKET"
    if model.startswith("BXP"):
        return "EXTENSION BAR"
    if model == "BUP2BV":
        return "ADAPTER"
    return f"{model[3:-3]}MM UNIVERSAL IMPACT SOCKET"


def _payload(models):
    return json.dumps(
        {
            "payLoad": {
                "products": [
                    {"sku": m, "price": 30.0} for m in models
                ]
            }
        }
    )


def _proposal(models):
    return {
        "status": "found",
        "product": {
            "brand": "Matco Tools",
            "model": "SBUPM246V",
            "name": "24-Piece 3/8 Drive ADV Universal Impact Socket Set",
            "category": "Socket set",
            "size": "3/8 in drive",
            "msrp": 499.95,
            "photos": [],
            "specs": [],
            "warranty": {"type": "lifetime", "months": None, "terms": ""},
        },
        "is_set": True,
        "stated_piece_count": 24,
        "makeup": [
            {"type": "standard sockets", "size_from": 10, "size_to": 19, "qty": 10},
            {"type": "deep sockets", "size_from": 10, "size_to": 19, "qty": 10},
            {"type": "extensions", "size_from": None, "size_to": None, "qty": 3},
            {"type": "adapter", "size_from": None, "size_to": None, "qty": 1},
        ],
        "pieces": [
            {
                "model": m,
                "name": _name(m),
                "msrp": 31.95,
                "image_url": None,
                "qty": 1,
                "source": "set_contents",
                # The first slice cites the first recording;
                # pieces from the replayed slice cite R2.
                "evidence": [
                    {"id": "R1" if m in _ALL24[:12] else "R2", "quote": m}
                ],
            }
            for m in models
        ],
        "addons": [],
    }


def _script(turns):
    state = {"turn": 0}

    def fake_turn(db, *, instructions, input_items, tools, **kwargs):
        index = state["turn"]
        state["turn"] += 1
        calls = turns[min(index, len(turns) - 1)]
        return {
            "output": [
                {
                    "type": "function_call",
                    "name": name,
                    "arguments": json.dumps(args),
                    "call_id": f"call-{index}-{i}",
                }
                for i, (name, args) in enumerate(calls)
            ]
        }

    return fake_turn


@pytest.fixture()
def seams(monkeypatch):
    monkeypatch.setattr(ai_service, "ai_configured", lambda db: True)
    monkeypatch.setattr(
        agent,
        "_load_page",
        lambda url: (
            _PAGE,
            [],
            [
                {
                    "url": "https://www.matcotools.com/arc/getProductsData",
                    "status": 200,
                    "arrays": [
                        {
                            "path": "$.payLoad.products",
                            "count": 12,
                            "keys": ["price", "sku"],
                        }
                    ],
                    "data": json.loads(_payload(_ALL24[:12])),
                }
            ],
            "rendered",
        ),
    )
    monkeypatch.setattr(
        agent,
        "_fetch_url",
        lambda url: ("application/json", _payload(_ALL24[12:])),
    )


def test_agent_run_verifies_the_full_set(db, seams, monkeypatch):
    turns = [
        [("open_page", {"url": "https://www.matcotools.com/catalog/product/sbupm246v"})],
        [("read_data_response", {"response_id": "R1", "path": "$.payLoad.products"})],
        [("replay_data_response", {"response_id": "R1"})],
        [("submit", {"proposal": _proposal(_ALL24)})],
    ]
    monkeypatch.setattr(ai_service, "run_agent_turn", _script(turns))
    result = agent.run_agent_lookup(db, brand="Matco Tools", model="SBUPM246V")
    assert result is not None
    assert result["agent_status"] == "verified"
    assert len(result["pieces"]) == 24
    assert {p["model"] for p in result["pieces"]} == set(_ALL24)


def test_agent_run_ends_partial_on_a_contaminated_submit(db, seams, monkeypatch):
    junk = ["MT4779M", "MT4779B", "MT4779G", "MT4779P", "MT4779SG", "MT4765G"]
    contaminated = _proposal(_ALL24[:12] + junk)
    for piece in contaminated["pieces"]:
        if piece["model"].startswith("MT"):
            piece["name"] = "IMPACT WRENCH"
            piece["source"] = "set_contents"
    turns = [
        [("open_page", {"url": "https://www.matcotools.com/catalog/product/sbupm246v"})],
        [("submit", {"proposal": contaminated})],
        [("submit", {"proposal": contaminated})],
        [("submit", {"proposal": contaminated})],
    ]
    monkeypatch.setattr(ai_service, "run_agent_turn", _script(turns))
    result = agent.run_agent_lookup(db, brand="Matco Tools", model="SBUPM246V")
    assert result is not None
    assert result["agent_status"] == "partial"
    confirmed = {p["model"] for p in result["pieces"]}
    assert not any(m.startswith("MT") for m in confirmed)


def test_agent_reads_the_mac_feed_as_evidence(db, monkeypatch):
    from app.modules.catalog import feeds

    monkeypatch.setattr(ai_service, "ai_configured", lambda db_: True)
    monkeypatch.setattr(
        feeds,
        "mac_product",
        lambda model, quick=False: {
            "fields": {
                "brand": "Mac Tools",
                "model": "SMUPM96TR",
                "name": "9-Piece Universal Socket Set",
                "msrp": 459.99,
            },
            "pieces": [
                {"name": f"Socket {i}", "model": f"MUP{i}MMR", "msrp": 20.0, "image_url": None}
                for i in range(10, 19)
            ],
            "piece_count": None,
            "photos": [],
            "specs": {},
            "warranty_type": None,
            "warranty_months": None,
            "warranty_terms": None,
            "source_name": "Mac Tools",
            "source_url": "https://www.mactools.com/products/smupm96tr",
            "image_url": None,
            "ai_used": False,
        },
    )
    proposal = {
        "status": "found",
        "product": {
            "brand": "Mac Tools",
            "model": "SMUPM96TR",
            "name": "9-Piece Universal Socket Set",
            "msrp": 459.99,
            "photos": [],
            "specs": [],
            "warranty": {"type": None, "months": None, "terms": ""},
        },
        "is_set": True,
        "stated_piece_count": 9,
        "makeup": [],
        "pieces": [
            {
                "model": f"MUP{i}MMR",
                "name": f"Socket {i}",
                "msrp": 20.0,
                "image_url": None,
                "qty": 1,
                "source": "set_contents",
                "evidence": [{"id": "R1", "quote": f"MUP{i}MMR"}],
            }
            for i in range(10, 19)
        ],
        "addons": [],
    }
    turns = [
        [("read_feed", {})],
        [("submit", {"proposal": proposal})],
    ]
    monkeypatch.setattr(ai_service, "run_agent_turn", _script(turns))
    result = agent.run_agent_lookup(db, brand="Mac Tools", model="SMUPM96TR")
    assert result is not None
    assert result["agent_status"] == "verified"
    assert len(result["pieces"]) == 9


@pytest.fixture()
def seeker(db):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number="TV-M-000512",
        email="agentseeker@example.com",
        name="Agent Seeker",
        password_hash="not-a-real-hash",
        account_types=["mechanic_technician"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_run_lookup_records_a_verified_agent_result(
    db, seeker, seams, monkeypatch
):
    turns = [
        [("open_page", {"url": "https://www.matcotools.com/catalog/product/sbupm246v"})],
        [("replay_data_response", {"response_id": "R1"})],
        [("submit", {"proposal": _proposal(_ALL24)})],
    ]
    monkeypatch.setattr(ai_service, "run_agent_turn", _script(turns))
    monkeypatch.setattr(agent, "agent_enabled", lambda db_: True)
    monkeypatch.setattr(lookup.grounded, "search_configured", lambda db_: True)

    def _boom(*args, **kwargs):
        raise AssertionError("the old walk must not run behind the agent")

    monkeypatch.setattr(grounded, "grounded_product", _boom)
    result = lookup.run_lookup(
        db, seeker.id, brand="Matco Tools", model="SBUPM246V", quick=False
    )
    assert len(result["pieces"]) == 24
    stored = library.library_result(db, brand="Matco Tools", model="SBUPM246V")
    assert stored["status"] == "verified"
    assert len(stored["pieces"]) == 24


def test_malformed_proposal_shapes_never_crash(db, seams, monkeypatch):
    # Live failure, 2026-11-20: a run proposed photos=true and
    # the result builder died with TypeError. Model output is
    # untrusted typing — wrong shapes are dropped, the run
    # still returns an honest result.
    proposal = _proposal(_ALL24[:12])
    proposal["product"]["photos"] = True
    proposal["product"]["msrp"] = "499.95"
    proposal["pieces"][0]["msrp"] = True
    turns = [
        [("open_page", {"url": "https://www.matcotools.com/catalog/product/sbupm246v"})],
        [("read_data_response", {"response_id": "R1", "path": "$.payLoad.products"})],
        [("submit", {"proposal": proposal})],
    ]
    monkeypatch.setattr(ai_service, "run_agent_turn", _script(turns))
    result = agent.run_agent_lookup(db, brand="Matco Tools", model="SBUPM246V")
    assert result is not None
    assert result["photos"] == []
    assert result["fields"]["msrp"] == 499.95


def test_feed_piece_count_floors_the_referee(db, seams, monkeypatch):
    # Live failure, 2026-11-20: a 9-piece Mac set read from
    # the feed verified as a bare product (no page was ever
    # opened, so no page stated a count). The feed's own
    # piece list is evidence of the count.
    from app.modules.catalog import feeds

    monkeypatch.setattr(
        feeds,
        "mac_product",
        lambda model: {
            "source_url": "https://www.mactools.com/products/smupm96tr",
            "fields": {"brand": "Mac Tools", "model": "SMUPM96TR", "msrp": 459.99},
            "pieces": [
                {"model": f"P{i}", "msrp": 10.0, "name": f"piece {i}"}
                for i in range(9)
            ],
            "photos": [],
            "specs": {},
        },
    )
    proposal = {
        "product": {"brand": "Mac Tools", "model": "SMUPM96TR", "name": "Set", "msrp": 459.99},
        "is_set": False,
        "pieces": [],
    }
    turns = [
        [("read_feed", {})],
        [("submit", {"proposal": proposal})],
        [("submit", {"proposal": proposal})],
        [("submit", {"proposal": proposal})],
    ]
    monkeypatch.setattr(ai_service, "run_agent_turn", _script(turns))
    result = agent.run_agent_lookup(db, brand="Mac Tools", model="SMUPM96TR")
    assert result is not None
    assert result["agent_status"] == "partial"
    assert any("0 of 9" in gap for gap in result["agent_gaps"])
