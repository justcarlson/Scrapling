import pytest

from scrapling.operations.browser_flow import FlowExtractResult, run_flow_and_extract


class FakeRequest:
    def __init__(self, url, method="GET", resource_type="fetch", post_data=None, headers=None):
        self.url = url
        self.method = method
        self.resource_type = resource_type
        self.post_data = post_data
        self.failure = "failed"
        self._headers = headers or {"accept": "application/json"}

    async def all_headers(self):
        return self._headers


class FakeResponse:
    def __init__(self, request, url, status=200, headers=None, text='{"ok":true}'):
        self.request = request
        self.url = url
        self.status = status
        self._headers = headers or {"content-type": "application/json"}
        self._text = text

    async def all_headers(self):
        return self._headers

    async def text(self):
        return self._text


class FakeLocator:
    def __init__(self):
        self.first = self

    async def click(self):
        return None

    async def wait_for(self, state="attached"):
        return None

    async def fill(self, value):
        self.value = value
        return None

    async def press(self, key):
        self.key = key
        return None


class FakeMouse:
    async def wheel(self, x, y):
        self.last = (x, y)
        return None


class FakePage:
    def __init__(self):
        self.url = "https://example.com/article?done=1"
        self.mouse = FakeMouse()
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, url, referer=None):
        if "request" in self.handlers:
            request = FakeRequest("https://example.com/api/items")
            response = FakeResponse(request, "https://example.com/api/items")
            await self.handlers["request"](request)
            await self.handlers["response"](response)
        return object()

    def locator(self, selector):
        return FakeLocator()

    async def wait_for_timeout(self, timeout):
        return None

    async def evaluate(self, script, arg=None):
        self.last_eval = (script, arg)
        return None

    async def content(self):
        return "<html><body><main><h1>Final content</h1></main></body></html>"


class FakePageInfo:
    def __init__(self):
        self.page = FakePage()


class FakePageGenerator:
    async def __aenter__(self):
        return FakePageInfo()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._config = type("Config", (), {"load_dom": True})()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def _page_generator(self, *args, **kwargs):
        return FakePageGenerator()

    async def _wait_for_page_stability(self, page, load_dom, network_idle):
        return None


class TestBrowserFlowOperations:
    @pytest.mark.asyncio
    async def test_run_flow_and_extract(self, monkeypatch):
        monkeypatch.setattr("scrapling.operations.browser_flow.AsyncDynamicSession", FakeSession)

        result = await run_flow_and_extract(
            page_url="https://example.com/article",
            strategy="fetch",
            extraction_type="text",
            actions=[
                {"type": "click", "selector": "#go"},
                {"type": "wait", "timeout_ms": 10},
                {"type": "evaluate", "script": "() => window.__done = true"},
            ],
        )

        assert isinstance(result, FlowExtractResult)
        assert result.final_url == "https://example.com/article?done=1"
        assert result.content
        assert len(result.actions) == 3
        assert result.actions[0].type == "click"
        assert result.network == []
        assert "# Browser Flow" in result.to_markdown()

    @pytest.mark.asyncio
    async def test_run_flow_and_extract_with_network_observation(self, monkeypatch):
        monkeypatch.setattr("scrapling.operations.browser_flow.AsyncDynamicSession", FakeSession)

        result = await run_flow_and_extract(
            page_url="https://example.com/article",
            strategy="fetch",
            extraction_type="text",
            observe_network=True,
            include_bodies=True,
            actions=[
                {"type": "click", "selector": "#go"},
            ],
        )

        assert isinstance(result, FlowExtractResult)
        assert len(result.network) == 1
        assert result.network[0].url == "https://example.com/api/items"
        assert result.network[0].response_preview == {"ok": True}
        assert "# Browser Flow" in result.to_markdown()
