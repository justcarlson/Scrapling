import pytest

from scrapling.operations.app_state import AppStateResult, _parse_script_json, extract_app_state


class DummyElement:
    def __init__(self, attrib, text=""):
        self.attrib = attrib
        self.text = text


class DummyResponse:
    def __init__(self, url, elements_by_selector):
        self.url = url
        self._elements_by_selector = elements_by_selector

    def css(self, selector):
        return self._elements_by_selector.get(selector, [])


class TestAppStateOperations:
    def test_parse_script_json_accepts_str_subclasses(self):
        class TextSubclass(str):
            pass

        payload = TextSubclass('{"buildId":"build-123","page":"/article"}')

        assert _parse_script_json(payload) == {"buildId": "build-123", "page": "/article"}

    @pytest.mark.asyncio
    async def test_extract_app_state(self, monkeypatch):
        page_response = DummyResponse(
            url="https://example.com/article",
            elements_by_selector={
                "script#__NEXT_DATA__": [
                    DummyElement({"id": "__NEXT_DATA__"}, '{"buildId":"build-123","page":"/article"}')
                ],
                'script[type="application/ld+json"]': [
                    DummyElement({"type": "application/ld+json"}, '{"@type":"Article","headline":"Hello"}')
                ],
            },
        )

        async def fake_fetch(url, **kwargs):
            assert url == "https://example.com/article"
            return page_response

        monkeypatch.setattr("scrapling.operations.app_state.DynamicFetcher.async_fetch", fake_fetch)

        result = await extract_app_state(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, AppStateResult)
        assert result.count == 2
        assert {state.kind for state in result.states} == {"next_data", "json_ld"}
        assert "Page URL" in result.to_text()
        assert "# App State" in result.to_markdown()
