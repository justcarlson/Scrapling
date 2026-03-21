import pytest

from scrapling.operations.discover_endpoints import EndpointDiscoveryResult, discover_endpoints


class FakeRequest:
    def __init__(self, url, method="GET", resource_type="fetch", post_data=None, failure="failed"):
        self.url = url
        self.method = method
        self.resource_type = resource_type
        self.post_data = post_data
        self.failure = failure
        self._headers = {"accept": "application/json"}

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


class FakePage:
    def __init__(self):
        self.url = "https://example.com/app"
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, url, referer=None):
        bootstrap = FakeRequest("https://example.com/api/bootstrap")
        bootstrap_response = FakeResponse(bootstrap, "https://example.com/api/bootstrap")
        graphql = FakeRequest(
            "https://example.com/graphql",
            method="POST",
            resource_type="fetch",
            post_data='{"operationName":"SearchProducts","query":"query SearchProducts { products { id } }"}',
        )
        graphql_response = FakeResponse(graphql, "https://example.com/graphql")
        websocket = FakeRequest("wss://example.com/socket", resource_type="websocket")

        await self.handlers["request"](bootstrap)
        await self.handlers["response"](bootstrap_response)
        await self.handlers["request"](graphql)
        await self.handlers["response"](graphql_response)
        await self.handlers["request"](websocket)
        return object()

    def locator(self, selector):
        return FakeLocator()

    async def wait_for_timeout(self, timeout):
        return None


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


class TestDiscoverEndpointsOperations:
    @pytest.mark.asyncio
    async def test_discover_endpoints(self, monkeypatch):
        monkeypatch.setattr("scrapling.operations.discover_endpoints.AsyncDynamicSession", FakeSession)

        result = await discover_endpoints(
            page_url="https://example.com/article",
            strategy="fetch",
            actions=[{"type": "click", "selector": "#go"}],
        )

        assert isinstance(result, EndpointDiscoveryResult)
        assert result.final_url == "https://example.com/app"
        assert result.count == 3
        assert any(endpoint.kind == "api" for endpoint in result.endpoints)
        assert any(endpoint.kind == "graphql" for endpoint in result.endpoints)
        assert result.graphql_operations[0].name == "SearchProducts"
        assert result.websocket_urls == ["wss://example.com/socket"]
        assert "# Endpoint Discovery" in result.to_markdown()
