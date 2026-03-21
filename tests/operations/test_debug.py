import pytest

from scrapling.operations.debug import PageDebugResult, debug_page


class FakeResponseForRedirect:
    def __init__(self, status):
        self.status = status


class FakeRedirectRequest:
    def __init__(self, url, status, redirected_from=None):
        self.url = url
        self._response = FakeResponseForRedirect(status)
        self.redirected_from = redirected_from

    async def response(self):
        return self._response


class FakeRequest:
    def __init__(self, url, method="GET", resource_type="fetch", failure="net::ERR_ABORTED"):
        self.url = url
        self.method = method
        self.resource_type = resource_type
        self.failure = failure
        self.post_data = None
        self._headers = {"accept": "application/json"}

    async def all_headers(self):
        return self._headers


class FakeFirstResponse:
    def __init__(self):
        redirect_a = FakeRedirectRequest("https://example.com/login", 302)
        redirect_b = FakeRedirectRequest("https://example.com/sso", 302, redirected_from=redirect_a)
        self.request = type("Request", (), {"redirected_from": redirect_b})()
        self.status = 200


class FakeLocator:
    def __init__(self):
        self.first = self

    async def wait_for(self, state="attached"):
        return None


class FakePage:
    def __init__(self):
        self.url = "https://example.com/app"
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, url, referer=None):
        request = FakeRequest("https://example.com/api/bootstrap")
        failed = FakeRequest("https://example.com/api/fail", failure="net::ERR_CONNECTION_RESET")
        await self.handlers["request"](request)
        await self.handlers["requestfailed"](failed)
        self.handlers["pageerror"](RuntimeError("Uncaught ReferenceError: app is not defined"))
        return FakeFirstResponse()

    async def wait_for_timeout(self, timeout):
        return None

    def locator(self, selector):
        return FakeLocator()

    async def evaluate(self, script):
        return "complete"

    async def title(self):
        return "App"

    async def content(self):
        return "<html><head><title>App</title></head><body>Loaded</body></html>"


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


class TestDebugOperations:
    @pytest.mark.asyncio
    async def test_debug_page(self, monkeypatch):
        monkeypatch.setattr("scrapling.operations.debug.AsyncDynamicSession", FakeSession)

        result = await debug_page(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, PageDebugResult)
        assert result.final_url == "https://example.com/app"
        assert result.status == 200
        assert result.ready_state == "complete"
        assert len(result.redirect_chain) == 2
        assert result.redirect_chain[0].url == "https://example.com/login"
        assert result.page_errors == ["Uncaught ReferenceError: app is not defined"]
        assert len(result.failed_requests) == 1
        assert result.failed_requests[0].url == "https://example.com/api/fail"
        assert "# Page Debug" in result.to_markdown()
