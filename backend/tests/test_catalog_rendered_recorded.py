"""The recorded render seam (lookup rebuild Phase 1 fix).

render_page_recorded registers a response handler with
Playwright. Playwright annotates the handler object when it
is registered, which builtin methods (list.append) refuse —
so the original registration raised AttributeError before
the page even loaded, every recorded render failed, and the
agent silently read raw downloads instead (found live
2026-11-20: zero data responses on every real page). These
tests drive _render with a fake browser whose `on` mimics
that annotation, so the seam itself is under test.
"""

import json

from app.modules.catalog import rendered


class _FakeResponse:
    url = "https://example.com/arc/getProductsData"
    status = 200
    headers = {"content-type": "application/json"}

    def text(self):
        return json.dumps(
            {"payLoad": {"products": [{"sku": "A1"}, {"sku": "A2"}]}}
        )


class _FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        # Playwright's registration annotates the handler.
        setattr(handler, "_pw_impl_instance_", object())
        self.handlers[event] = handler

    def goto(self, url, **kwargs):
        handler = self.handlers.get("response")
        if handler is not None:
            handler(_FakeResponse())

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, *args, **kwargs):
        pass

    def evaluate(self, script):
        if "querySelectorAll('img')" in script or 'querySelectorAll("img")' in script:
            return []
        return 0

    def content(self):
        return "<html><head><title>Probe</title></head><body></body></html>"

    def close(self):
        pass


class _FakeContext:
    def __init__(self, page):
        self._page = page

    def route(self, pattern, handler):
        pass

    def new_page(self):
        return self._page

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    def new_context(self, **kwargs):
        return _FakeContext(self._page)


def test_recorded_render_captures_data_responses(monkeypatch):
    page = _FakePage()
    monkeypatch.setattr(rendered, "_get_browser", lambda: _FakeBrowser(page))
    monkeypatch.setattr(rendered, "_pages_served", 0)
    html, media, recordings = rendered.render_page_recorded(
        "https://example.com/catalog/product/x"
    )
    assert "<html" in html
    assert len(recordings) == 1
    (recording,) = recordings
    assert recording["url"].endswith("getProductsData")
    assert recording["arrays"][0]["path"] == "$.payLoad.products"
    assert recording["arrays"][0]["count"] == 2


def test_plain_render_still_returns_dom(monkeypatch):
    page = _FakePage()
    monkeypatch.setattr(rendered, "_get_browser", lambda: _FakeBrowser(page))
    monkeypatch.setattr(rendered, "_pages_served", 0)
    html, media = rendered.render_page("https://example.com/catalog/product/x")
    assert "<html" in html
    assert media == []
