import pytest

from scrapling.operations.network import NetworkCapture, NetworkObservationResult, observe_network


class FakeRequest:
    def __init__(self, url, method="GET", resource_type="fetch", post_data=None, headers=None, failure="failed"):
        self.url = url
        self.method = method
        self.resource_type = resource_type
        self.post_data = post_data
        self.failure = failure
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

    async def wait_for(self, state="attached"):
        return None


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, url, referer=None):
        request = FakeRequest("https://example.com/api/items")
        response = FakeResponse(request, "https://example.com/api/items")
        await self.handlers["request"](request)
        await self.handlers["response"](response)
        return object()

    async def wait_for_timeout(self, timeout):
        return None

    def locator(self, selector):
        return FakeLocator()


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


class TestNetworkOperations:
    def test_network_capture_bind_supports_playwright_style_handler_wrapping(self):
        capture = NetworkCapture()

        class FakePlaywrightPage:
            def on(self, event, handler):
                owner = handler.__self__
                setattr(owner, f"_pw_impl_instance_{handler.__name__}", object())

        capture.bind(FakePlaywrightPage())

    @pytest.mark.asyncio
    async def test_observe_network(self, monkeypatch):
        monkeypatch.setattr("scrapling.operations.network.AsyncDynamicSession", FakeSession)

        result = await observe_network(
            page_url="https://example.com/article",
            strategy="fetch",
            include_bodies=True,
        )

        assert isinstance(result, NetworkObservationResult)
        assert result.count == 1
        assert result.entries[0].url == "https://example.com/api/items"
        assert result.entries[0].status == 200
        assert result.entries[0].response_preview == {"ok": True}
        assert "# Network Observation" in result.to_markdown()
