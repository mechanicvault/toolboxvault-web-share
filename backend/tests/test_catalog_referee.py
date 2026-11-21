"""Rebuild Phase 2 — the referee, tested on the incident.

The fixtures are the SBUPM246V case itself (2026-11-20):
the contaminated list the old pipeline certified (12 real
pieces + 6 Similar-Products impact wrenches), the hand-
verified true 24, and a 23-of-24 near miss. The referee must
reject the first, verify the second, and name the gap in the
third — in plain code, with no AI anywhere near the verdict.
"""

from app.modules.catalog import referee

_PRICES = {
    "BUP10M6V": 31.95, "BUP11M6V": 35.95, "BUP12M6V": 31.95,
    "BUP13M6V": 31.95, "BUP14M6V": 32.95, "BUP15M6V": 31.95,
    "BUP16M6V": 32.95, "BUP17M6V": 31.95, "BUP18M6V": 31.95,
    "BUP19M6V": 35.95,
    "BDUP10M6V": 34.95, "BDUP11M6V": 34.95, "BDUP12M6V": 34.95,
    "BDUP13M6V": 34.95, "BDUP14M6V": 34.95, "BDUP15M6V": 34.95,
    "BDUP16M6V": 37.95, "BDUP17M6V": 37.95, "BDUP18M6V": 37.95,
    "BDUP19M6V": 37.95,
    "BXP3V": 13.95, "BXP6V": 20.95, "BXP12V": 34.95, "BUP2BV": 34.95,
}

_NAMES = {}
for _model in _PRICES:
    if _model.startswith("BDUP"):
        _NAMES[_model] = f"{_model[4:-3]}MM DEEP UNIVERSAL IMPACT SOCKET"
    elif _model.startswith("BXP"):
        _NAMES[_model] = "EXTENSION BAR"
    elif _model == "BUP2BV":
        _NAMES[_model] = "ADAPTER"
    else:
        _NAMES[_model] = f"{_model[3:-3]}MM UNIVERSAL IMPACT SOCKET"

_MAKEUP = [
    {"type": "standard sockets", "size_from": 10, "size_to": 19, "qty": 10},
    {"type": "deep sockets", "size_from": 10, "size_to": 19, "qty": 10},
    {"type": "extensions", "size_from": None, "size_to": None, "qty": 3},
    {"type": "adapter", "size_from": None, "size_to": None, "qty": 1},
]


def _piece(model, msrp=None):
    return {
        "model": model,
        "name": _NAMES.get(model, model),
        "msrp": _PRICES.get(model, 499.95) if msrp is None else msrp,
        "image_url": None,
        "qty": 1,
        "source": "set_contents",
        "evidence": [{"id": "ev1", "quote": model}],
    }


def _pages(models, drive="3/8"):
    return {
        referee.norm_model(m): {
            "found": True,
            "msrp": _PRICES.get(m),
            "image_url": None,
            "brand": "Matco Tools",
            "drive": drive,
        }
        for m in models
    }


def _proposal(pieces):
    return {
        "product": {
            "brand": "Matco Tools",
            "model": "SBUPM246V",
            "name": "24-Piece 3/8 Drive ADV Universal Impact Socket Set",
            "size": "3/8 in drive",
            "msrp": 499.95,
        },
        "is_set": True,
        "stated_piece_count": 24,
        "makeup": _MAKEUP,
        "pieces": pieces,
    }


def test_evidence_stated_count_forces_set_treatment():
    # The 2026-11-20 live failure: the agent proposed a
    # 10-piece set as a bare product (no is_set, no stated
    # count, no pieces) and the referee verified the fields.
    # When the run's own pages stated the count, the proposal
    # is judged as that set whatever it claims.
    proposal = {
        "product": {
            "brand": "Mac Tools",
            "model": "SMDM106TR",
            "name": "Socket Set",
            "msrp": 100.0,
        },
        "is_set": False,
        "pieces": [],
    }
    verdict = referee.judge(proposal, evidence_stated_count=10)
    assert verdict["status"] == "partial"
    assert any("0 of 10 pieces confirmed" in gap for gap in verdict["gaps"])
    # And with no evidence count, a bare product still verifies
    # on its fields alone — the rule only binds what the
    # evidence itself stated.
    verdict = referee.judge(proposal)
    assert verdict["status"] == "verified"


def test_the_true_24_verify():
    pieces = [_piece(m) for m in _PRICES]
    verdict = referee.judge(
        _proposal(pieces), piece_pages=_pages(list(_PRICES))
    )
    assert verdict["status"] == "verified"
    assert len(verdict["confirmed"]) == 24
    assert verdict["gaps"] == []
    total = sum(p["msrp"] for p in verdict["confirmed"])
    assert round(total, 2) == 795.80


def test_the_contaminated_list_is_rejected_with_named_gaps():
    real = [
        "BUP11M6V", "BUP12M6V", "BUP14M6V", "BUP16M6V", "BUP19M6V",
        "BDUP10M6V", "BDUP11M6V", "BDUP12M6V", "BDUP14M6V",
        "BDUP16M6V", "BDUP19M6V", "BXP6V",
    ]
    junk = ["MT4779M", "MT4779B", "MT4779G", "MT4779P", "MT4779SG", "MT4765G"]
    pieces = [_piece(m) for m in real + junk]
    pages = _pages(real)
    for model in junk:
        pages[referee.norm_model(model)] = {
            "found": True,
            "msrp": 499.95,
            "image_url": None,
            "brand": "Matco Tools",
            "drive": "1/2",
        }
    verdict = referee.judge(
        _proposal(pieces),
        cross_sell_models=set(junk),
        contents_models=set(real),
        piece_pages=pages,
    )
    assert verdict["status"] == "partial"
    dropped = {d["model"] for d in verdict["dropped"]}
    assert dropped == set(junk)
    assert len(verdict["confirmed"]) == 12
    gap_text = " ".join(verdict["gaps"])
    assert "12 of 24" in gap_text
    # The makeup gaps name the exact missing sizes.
    assert "13, 15, 17, 18" in gap_text


def test_23_of_24_is_partial_and_names_the_adapter():
    models = [m for m in _PRICES if m != "BUP2BV"]
    verdict = referee.judge(
        _proposal([_piece(m) for m in models]),
        piece_pages=_pages(models),
    )
    assert verdict["status"] == "partial"
    assert len(verdict["confirmed"]) == 23
    assert any("adapter" in gap for gap in verdict["gaps"])


def test_makeup_that_does_not_add_up_is_ignored_not_enforced():
    proposal = _proposal([_piece(m) for m in _PRICES])
    proposal["makeup"] = [
        {"type": "standard sockets", "size_from": 10, "size_to": 19, "qty": 9},
        {"type": "deep sockets", "size_from": 10, "size_to": 19, "qty": 10},
        {"type": "extensions", "size_from": None, "size_to": None, "qty": 3},
        {"type": "adapter", "size_from": None, "size_to": None, "qty": 1},
    ]
    verdict = referee.judge(proposal, piece_pages=_pages(list(_PRICES)))
    assert verdict["makeup_applied"] is False
    assert any("makeup ignored" in w for w in verdict["warnings"])
    # The pure count check still verifies the set.
    assert verdict["status"] == "verified"


def test_a_piece_with_no_evidence_is_never_confirmed():
    pieces = [_piece(m) for m in _PRICES]
    pieces[0]["evidence"] = []
    verdict = referee.judge(
        _proposal(pieces), piece_pages=_pages(list(_PRICES))
    )
    assert verdict["status"] == "partial"
    assert len(verdict["confirmed"]) == 23
    assert verdict["unconfirmed"][0]["model"] == "BUP10M6V"
