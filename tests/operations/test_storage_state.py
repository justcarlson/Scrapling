import pytest

from scrapling.operations.storage_state import StorageStateResult, export_storage_state


class FakeContext:
    async def cookies(self):
        return [{"name": "session", "value": "abc123", "domain": "example.com"}]

    async def storage_state(self):
        return {
            "cookies": [{"name": "session", "value": "abc123", "domain": "example.com"}],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [
                        {"name": "token", "value": "secret"},
                    ],
                }
            ],
        }


class FakeLocator:
    def __init__(self):
        self.first = self

    async def wait_for(self, state="attached"):
        return None


class FakePage:
    def __init__(self):
        self.url = "https://example.com/app"
        self.context = FakeContext()

    async def goto(self, url, referer=None):
        return object()

    def locator(self, selector):
        return FakeLocator()

    async def wait_for_timeout(self, timeout):
        return None

    async def evaluate(self, script, storage_name):
        if storage_name == "localStorage":
            return {"token": "secret"}
        if storage_name == "sessionStorage":
            return {"view": "dashboard"}
        return {}


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


class TestStorageStateOperations:
    @pytest.mark.asyncio
    async def test_export_storage_state(self, monkeypatch):
        monkeypatch.setattr("scrapling.operations.storage_state.AsyncDynamicSession", FakeSession)

        result = await export_storage_state(
            page_url="https://example.com/article",
            strategy="fetch",
        )

        assert isinstance(result, StorageStateResult)
        assert result.final_url == "https://example.com/app"
        assert result.cookies[0]["name"] == "session"
        assert result.local_storage == {"token": "secret"}
        assert result.session_storage == {"view": "dashboard"}
        assert result.origins[0].origin == "https://example.com"
        assert "# Storage State" in result.to_markdown()
