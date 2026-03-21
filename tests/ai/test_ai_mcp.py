import pytest
import pytest_httpbin

from scrapling.core.ai import (
    AppStateResultModel,
    EndpointDiscoveryResultModel,
    FlowExtractResultModel,
    ImageCandidatesModel,
    NetworkObservationResultModel,
    PageDebugResultModel,
    ResponseModel,
    ScraplingMCPServer,
    StorageStateResultModel,
)


class DummyElement:
    def __init__(self, attrib):
        self.attrib = attrib


class DummyResponse:
    def __init__(self, url, status=200, body=b"", headers=None, elements=None):
        self.url = url
        self.status = status
        self.body = body
        self.headers = headers or {}
        self._elements = elements or []

    def css(self, selector):
        assert selector == "img"
        return self._elements


@pytest_httpbin.use_class_based_httpbin
class TestMCPServer:
    """Test MCP server functionality"""

    @pytest.fixture(scope="class")
    def test_url(self, httpbin):
        return f"{httpbin.url}/html"

    @pytest.fixture
    def server(self):
        return ScraplingMCPServer()

    def test_get_tool(self, server, test_url):
        """Test the get tool method"""
        result = server.get(url=test_url, extraction_type="markdown")
        assert isinstance(result, ResponseModel)
        assert result.status == 200
        assert result.url == test_url

    @pytest.mark.asyncio
    async def test_bulk_get_tool(self, server, test_url):
        """Test the bulk_get tool method"""
        results = await server.bulk_get(urls=(test_url, test_url), extraction_type="html")

        assert len(results) == 2
        assert all(isinstance(r, ResponseModel) for r in results)

    @pytest.mark.asyncio
    async def test_fetch_tool(self, server, test_url):
        """Test the fetch tool method"""
        result = await server.fetch(url=test_url, headless=True)
        assert isinstance(result, ResponseModel)
        assert result.status == 200

    @pytest.mark.asyncio
    async def test_bulk_fetch_tool(self, server, test_url):
        """Test the bulk_fetch tool method"""
        result = await server.bulk_fetch(urls=(test_url, test_url), headless=True)
        assert all(isinstance(r, ResponseModel) for r in result)

    @pytest.mark.asyncio
    async def test_stealthy_fetch_tool(self, server, test_url):
        """Test the stealthy_fetch tool method"""
        result = await server.stealthy_fetch(url=test_url, headless=True)
        assert isinstance(result, ResponseModel)
        assert result.status == 200

    @pytest.mark.asyncio
    async def test_bulk_stealthy_fetch_tool(self, server, test_url):
        """Test the bulk_stealthy_fetch tool method"""
        result = await server.bulk_stealthy_fetch(urls=(test_url, test_url), headless=True)
        assert all(isinstance(r, ResponseModel) for r in result)

    @pytest.mark.asyncio
    async def test_list_page_images_tool(self, server, monkeypatch):
        """Test image candidate listing."""
        page_response = DummyResponse(
            url="https://example.com/article",
            elements=[
                DummyElement({"src": "/assets/header.png"}),
                DummyElement({"src": "/hc/article_attachments/12345", "alt": "Article image"}),
            ],
        )

        async def fake_fetch(url, **kwargs):
            assert url == "https://example.com/article"
            return page_response

        monkeypatch.setattr("scrapling.core.ai.DynamicFetcher.async_fetch", fake_fetch)

        result = await server.list_page_images(
            page_url="https://example.com/article",
            strategy="fetch",
            src_contains="/hc/article_attachments/",
        )

        assert isinstance(result, ImageCandidatesModel)
        assert result.count == 1
        assert result.images[0].absolute_url == "https://example.com/hc/article_attachments/12345"
        assert result.images[0].alt == "Article image"

    @pytest.mark.asyncio
    async def test_fetch_page_image_tool(self, server, monkeypatch):
        """Test MCP image content return."""
        page_response = DummyResponse(
            url="https://example.com/article",
            elements=[DummyElement({"src": "/hc/article_attachments/12345", "alt": "Article image"})],
        )
        image_response = DummyResponse(
            url="https://example.com/hc/article_attachments/12345",
            body=b"\x89PNG\r\n\x1a\nfakepng",
            headers={"content-type": "image/png"},
        )

        async def fake_fetch(url, **kwargs):
            if url == "https://example.com/article":
                return page_response
            if url == "https://example.com/hc/article_attachments/12345":
                return image_response
            raise AssertionError(f"Unexpected URL: {url}")

        monkeypatch.setattr("scrapling.core.ai.DynamicFetcher.async_fetch", fake_fetch)

        result = await server.fetch_page_image(
            page_url="https://example.com/article",
            strategy="fetch",
            src_contains="/hc/article_attachments/",
        )

        assert result.isError is False
        assert len(result.content) == 2
        assert result.content[0].type == "text"
        assert result.content[1].type == "image"
        assert result.content[1].mimeType == "image/png"
        assert result.structuredContent["image_url"] == "https://example.com/hc/article_attachments/12345"
        assert result.structuredContent["bytes"] == len(image_response.body)

    @pytest.mark.asyncio
    async def test_extract_app_state_tool(self, server, monkeypatch):
        """Test app-state extraction."""
        next_data = DummyElement({"id": "__NEXT_DATA__"})
        next_data.text = '{"buildId":"build-123","page":"/article"}'
        json_ld = DummyElement({"type": "application/ld+json"})
        json_ld.text = '{"@type":"Article","headline":"Hello"}'
        page_response = DummyResponse(
            url="https://example.com/article",
            elements=[],
        )

        def css(selector):
            if selector == "script#__NEXT_DATA__":
                return [next_data]
            if selector == 'script[type="application/ld+json"]':
                return [json_ld]
            return []

        page_response.css = css

        async def fake_fetch(url, **kwargs):
            assert url == "https://example.com/article"
            return page_response

        monkeypatch.setattr("scrapling.operations.app_state.DynamicFetcher.async_fetch", fake_fetch)

        result = await server.extract_app_state(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, AppStateResultModel)
        assert result.count == 2
        assert {state.kind for state in result.states} == {"next_data", "json_ld"}

    @pytest.mark.asyncio
    async def test_observe_network_tool(self, server, monkeypatch):
        async def fake_observe(**kwargs):
            from scrapling.operations.network import NetworkObservationResult, NetworkEntry

            return NetworkObservationResult(
                page_url=kwargs["page_url"],
                strategy=kwargs["strategy"],
                count=1,
                entries=[
                    NetworkEntry(
                        index=0,
                        url="https://example.com/api/items",
                        method="GET",
                        resource_type="fetch",
                        status=200,
                        content_type="application/json",
                        stage="responded",
                    )
                ],
            )

        monkeypatch.setattr("scrapling.core.ai.observe_network_operation", fake_observe)

        result = await server.observe_network(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, NetworkObservationResultModel)
        assert result.count == 1
        assert result.entries[0].url == "https://example.com/api/items"

    @pytest.mark.asyncio
    async def test_run_flow_and_extract_tool(self, server, monkeypatch):
        async def fake_flow(**kwargs):
            from scrapling.operations.browser_flow import FlowActionRecord, FlowExtractResult
            from scrapling.operations.network import NetworkEntry

            return FlowExtractResult(
                page_url=kwargs["page_url"],
                final_url="https://example.com/article?done=1",
                strategy=kwargs["strategy"],
                extraction_type=kwargs["extraction_type"],
                css_selector=kwargs["css_selector"],
                content=["Final content"],
                actions=[
                    FlowActionRecord(index=0, type="click", status="completed", details={"selector": "#go"})
                ],
                network=[
                    NetworkEntry(
                        index=0,
                        url="https://example.com/api/items",
                        method="GET",
                        resource_type="fetch",
                        status=200,
                        content_type="application/json",
                        stage="responded",
                    )
                ],
            )

        monkeypatch.setattr("scrapling.core.ai.run_flow_and_extract_operation", fake_flow)

        result = await server.run_flow_and_extract(
            page_url="https://example.com/article",
            actions=[{"type": "click", "selector": "#go"}],
            strategy="fetch",
            observe_network=True,
        )

        assert isinstance(result, FlowExtractResultModel)
        assert result.final_url == "https://example.com/article?done=1"
        assert result.content == ["Final content"]
        assert result.network[0].url == "https://example.com/api/items"

    @pytest.mark.asyncio
    async def test_debug_page_tool(self, server, monkeypatch):
        async def fake_debug(**kwargs):
            from scrapling.operations.debug import PageDebugResult, RedirectEntry
            from scrapling.operations.network import NetworkEntry

            return PageDebugResult(
                page_url=kwargs["page_url"],
                final_url="https://example.com/app",
                strategy=kwargs["strategy"],
                status=200,
                title="App",
                ready_state="complete",
                challenge_detected=None,
                redirect_chain=[
                    RedirectEntry(index=0, url="https://example.com/login", status=302),
                ],
                page_errors=["Uncaught ReferenceError: app is not defined"],
                failed_requests=[
                    NetworkEntry(
                        index=0,
                        url="https://example.com/api/fail",
                        method="GET",
                        resource_type="fetch",
                        stage="failed",
                        failure_text="net::ERR_CONNECTION_RESET",
                    )
                ],
                network_count=2,
            )

        monkeypatch.setattr("scrapling.core.ai.debug_page_operation", fake_debug)

        result = await server.debug_page(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, PageDebugResultModel)
        assert result.final_url == "https://example.com/app"
        assert result.redirect_chain[0].status == 302
        assert result.failed_requests[0].stage == "failed"

    @pytest.mark.asyncio
    async def test_export_storage_state_tool(self, server, monkeypatch):
        async def fake_storage(**kwargs):
            from scrapling.operations.storage_state import StorageOriginEntry, StorageStateResult

            return StorageStateResult(
                page_url=kwargs["page_url"],
                final_url="https://example.com/app",
                strategy=kwargs["strategy"],
                cookies=[{"name": "session", "value": "abc123"}],
                local_storage={"token": "secret"},
                session_storage={"view": "dashboard"},
                origins=[StorageOriginEntry(origin="https://example.com", local_storage={"token": "secret"})],
            )

        monkeypatch.setattr("scrapling.core.ai.export_storage_state_operation", fake_storage)

        result = await server.export_storage_state(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, StorageStateResultModel)
        assert result.cookies[0]["name"] == "session"
        assert result.origins[0].origin == "https://example.com"

    @pytest.mark.asyncio
    async def test_discover_endpoints_tool(self, server, monkeypatch):
        async def fake_discover(**kwargs):
            from scrapling.operations.discover_endpoints import (
                DiscoveredEndpoint,
                EndpointDiscoveryResult,
                GraphQLOperation,
            )

            return EndpointDiscoveryResult(
                page_url=kwargs["page_url"],
                final_url="https://example.com/app",
                strategy=kwargs["strategy"],
                count=2,
                endpoints=[
                    DiscoveredEndpoint(
                        url="https://example.com/api/bootstrap",
                        method="GET",
                        kind="api",
                        resource_type="fetch",
                        status=200,
                        content_type="application/json",
                    ),
                    DiscoveredEndpoint(
                        url="https://example.com/graphql",
                        method="POST",
                        kind="graphql",
                        resource_type="fetch",
                        status=200,
                        content_type="application/json",
                        graphql_operation_names=["SearchProducts"],
                    ),
                ],
                graphql_operations=[
                    GraphQLOperation(
                        name="SearchProducts",
                        endpoint_url="https://example.com/graphql",
                        method="POST",
                    )
                ],
                websocket_urls=["wss://example.com/socket"],
            )

        monkeypatch.setattr("scrapling.core.ai.discover_endpoints_operation", fake_discover)

        result = await server.discover_endpoints(
            page_url="https://example.com/article",
            actions=[{"type": "click", "selector": "#go"}],
            strategy="fetch",
        )

        assert isinstance(result, EndpointDiscoveryResultModel)
        assert result.endpoints[1].kind == "graphql"
        assert result.graphql_operations[0].name == "SearchProducts"
        assert result.websocket_urls == ["wss://example.com/socket"]
