import pytest
import pytest_httpbin

from scrapling.core.ai import ImageCandidatesModel, ResponseModel, ScraplingMCPServer


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
