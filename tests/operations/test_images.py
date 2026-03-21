import pytest

from scrapling.operations.images import ImageCandidatesResult, ImageFetchResult, fetch_page_image, list_page_images


class DummyElement:
    def __init__(self, attrib):
        self.attrib = attrib


class DummyResponse:
    def __init__(self, url, body=b"", headers=None, elements=None):
        self.url = url
        self.body = body
        self.headers = headers or {}
        self._elements = elements or []

    def css(self, selector):
        assert selector == "img"
        return self._elements


class TestImageOperations:
    @pytest.mark.asyncio
    async def test_list_page_images(self, monkeypatch):
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

        monkeypatch.setattr("scrapling.operations.images.DynamicFetcher.async_fetch", fake_fetch)

        result = await list_page_images(
            page_url="https://example.com/article",
            strategy="fetch",
            src_contains="/hc/article_attachments/",
        )

        assert isinstance(result, ImageCandidatesResult)
        assert result.count == 1
        assert result.images[0].absolute_url == "https://example.com/hc/article_attachments/12345"
        assert result.images[0].alt == "Article image"

    @pytest.mark.asyncio
    async def test_fetch_page_image(self, monkeypatch):
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

        monkeypatch.setattr("scrapling.operations.images.DynamicFetcher.async_fetch", fake_fetch)

        result = await fetch_page_image(
            page_url="https://example.com/article",
            strategy="fetch",
            src_contains="/hc/article_attachments/",
        )

        assert isinstance(result, ImageFetchResult)
        assert result.image_url == "https://example.com/hc/article_attachments/12345"
        assert result.mime_type == "image/png"
        assert result.bytes_count == len(image_response.body)
        assert result.data == image_response.body
