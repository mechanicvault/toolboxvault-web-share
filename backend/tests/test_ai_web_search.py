"""AI seam web search (owner's one-vendor decision, 2026-10-25).

The provider's own web search is the site's only search. These
tests pin the boundary contract:

  - only citation URLs (+ the cited page's title) cross the
    seam — the provider's answer TEXT is discarded here and
    never reaches a consumer as evidence;
  - citation URLs are cleaned (utm_* tracking parameters
    stripped), deduped, https only;
  - a dark seam raises AiNotConfigured; a failed provider call
    raises AiProviderError; a search that cites nothing usable
    returns [] (consumers degrade honestly);
  - both providers' shapes parse: OpenAI Responses
    url_citation annotations, Anthropic web_search_tool_result
    blocks.
"""

import pytest

from app.modules.billing import ai_service, entitlements


def _configure(db, monkeypatch, provider="openai"):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, provider)
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "SEARCH_TEST_KEY")
    monkeypatch.setenv("SEARCH_TEST_KEY", "key-not-real")
    db.commit()


def _openai_body(annotations, text="The answer is SPRB4A with a price."):
    return {
        "output": [
            {"type": "web_search_call", "action": {"type": "search"}},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": annotations,
                    }
                ],
            },
        ]
    }


def test_openai_citations_are_cleaned_and_text_is_dropped(db, monkeypatch):
    _configure(db, monkeypatch)
    body = _openai_body(
        [
            {
                "type": "url_citation",
                "url": "https://www.matcotools.com/catalog/product/sprb4a?utm_source=openai&utm_medium=web",
                "title": "SPRB4A | Matco",
            },
            {
                "type": "url_citation",
                "url": "https://www.matcotools.com/catalog/product/sprb4a",
                "title": "Duplicate",
            },
            {"type": "url_citation", "url": "http://insecure.example.com/x", "title": "http"},
            {"type": "url_citation", "url": "", "title": "empty"},
            {"type": "other_annotation", "url": "https://ignored.example.com", "title": "?"},
        ]
    )
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    results = ai_service.web_search(db, "Matco SPRB4A")
    assert results == [
        {
            "url": "https://www.matcotools.com/catalog/product/sprb4a",
            "title": "SPRB4A | Matco",
        }
    ]
    # The answer text never appears in what the seam returns.
    assert "answer" not in str(results)


def test_openai_search_respects_max_results(db, monkeypatch):
    _configure(db, monkeypatch)
    annotations = [
        {
            "type": "url_citation",
            "url": f"https://shop{i}.example.com/p",
            "title": f"P{i}",
        }
        for i in range(10)
    ]
    monkeypatch.setattr(
        ai_service, "_transport", lambda *a, **k: _openai_body(annotations)
    )
    results = ai_service.web_search(db, "Anything", max_results=3)
    assert [r["url"] for r in results] == [
        "https://shop0.example.com/p",
        "https://shop1.example.com/p",
        "https://shop2.example.com/p",
    ]


def test_openai_error_body_is_a_provider_error(db, monkeypatch):
    _configure(db, monkeypatch)
    monkeypatch.setattr(
        ai_service,
        "_transport",
        lambda *a, **k: {"error": {"message": "tool not available"}},
    )
    with pytest.raises(ai_service.AiProviderError):
        ai_service.web_search(db, "Matco SPRB4A")


def test_dark_seam_raises_not_configured(db, monkeypatch):
    monkeypatch.setattr(
        ai_service,
        "_transport",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("transport must not be dialed while dark")
        ),
    )
    with pytest.raises(ai_service.AiNotConfigured):
        ai_service.web_search(db, "Matco SPRB4A")


def test_search_that_cites_nothing_returns_empty(db, monkeypatch):
    _configure(db, monkeypatch)
    monkeypatch.setattr(
        ai_service, "_transport", lambda *a, **k: _openai_body([], text="No idea.")
    )
    assert ai_service.web_search(db, "Obscure XQ-99") == []


def test_anthropic_search_blocks_parse(db, monkeypatch):
    _configure(db, monkeypatch, provider="anthropic")
    body = {
        "content": [
            {"type": "server_tool_use", "name": "web_search"},
            {
                "type": "web_search_tool_result",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://www.dewalt.com/product/dcf891b?utm_source=anthropic",
                        "title": "DCF891B",
                    },
                    {
                        "type": "web_search_result",
                        "url": "https://shop.example.com/dcf891b",
                        "title": "Shop",
                    },
                ],
            },
            {"type": "text", "text": "It is an impact wrench."},
        ]
    }
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    results = ai_service.web_search(db, "DeWalt DCF891")
    assert results == [
        {"url": "https://www.dewalt.com/product/dcf891b", "title": "DCF891B"},
        {"url": "https://shop.example.com/dcf891b", "title": "Shop"},
    ]


def test_anthropic_search_error_is_a_provider_error(db, monkeypatch):
    _configure(db, monkeypatch, provider="anthropic")
    body = {
        "content": [
            {
                "type": "web_search_tool_result",
                "content": {"type": "web_search_tool_result_error", "error_code": "x"},
            }
        ]
    }
    monkeypatch.setattr(ai_service, "_transport", lambda *a, **k: body)
    with pytest.raises(ai_service.AiProviderError):
        ai_service.web_search(db, "DeWalt DCF891")
