import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock, AsyncMock
import pytest_httpbin

from scrapling.parser import Selector
from scrapling.cli import (
    shell, mcp, get, post, put, delete, fetch, stealthy_fetch, list_page_images, fetch_page_image, extract_app_state, observe_network, run_flow_and_extract, debug_page, export_storage_state, discover_endpoints
)


@pytest_httpbin.use_class_based_httpbin
def configure_selector_mock():
    """Helper function to create a properly configured Selector mock"""
    mock_response = MagicMock(spec=Selector)
    mock_response.body = "<html><body>Test content</body></html>"
    mock_response.html_content = "<html><body>Test content</body></html>"
    mock_response.encoding = "utf-8"
    mock_response.get_all_text.return_value = "Test content"
    mock_response.css.return_value = [mock_response]
    return mock_response


class TestCLI:
    """Test CLI functionality"""

    @pytest.fixture
    def html_url(self, httpbin):
        return f"{httpbin.url}/html"

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_shell_command(self, runner):
        """Test shell command"""
        with patch('scrapling.core.shell.CustomShell') as mock_shell:
            mock_instance = MagicMock()
            mock_shell.return_value = mock_instance

            result = runner.invoke(shell)
            assert result.exit_code == 0
            mock_instance.start.assert_called_once()

    def test_mcp_command(self, runner):
        """Test MCP command"""
        with patch('scrapling.core.ai.ScraplingMCPServer') as mock_server:
            mock_instance = MagicMock()
            mock_server.return_value = mock_instance

            result = runner.invoke(mcp)
            assert result.exit_code == 0
            mock_instance.serve.assert_called_once()

    def test_extract_get_command(self, runner, tmp_path, html_url):
        """Test extract `get` command"""
        output_file = tmp_path / "output.md"

        with patch('scrapling.fetchers.Fetcher.get') as mock_get:
            mock_response = configure_selector_mock()
            mock_response.status = 200
            mock_get.return_value = mock_response

            result = runner.invoke(
                get,
                [html_url, str(output_file)]
            )
            assert result.exit_code == 0

        # Test with various options
        with patch('scrapling.fetchers.Fetcher.get') as mock_get:
            mock_get.return_value = mock_response

            result = runner.invoke(
                get,
                [
                    html_url,
                    str(output_file),
                    '-H', 'User-Agent: Test',
                    '--cookies', 'session=abc123',
                    '--timeout', '60',
                    '--proxy', 'http://proxy:8080',
                    '-s', '.content',
                    '-p', 'page=1'
                ]
            )
            assert result.exit_code == 0

    def test_extract_post_command(self, runner, tmp_path, html_url):
        """Test extract `post` command"""
        output_file = tmp_path / "output.html"

        with patch('scrapling.fetchers.Fetcher.post') as mock_post:
            mock_response = configure_selector_mock()
            mock_post.return_value = mock_response

            result = runner.invoke(
                post,
                [
                    html_url,
                    str(output_file),
                    '-d', 'key=value',
                    '-j', '{"data": "test"}'
                ]
            )
            assert result.exit_code == 0

    def test_extract_put_command(self, runner, tmp_path, html_url):
        """Test extract `put` command"""
        output_file = tmp_path / "output.html"

        with patch('scrapling.fetchers.Fetcher.put') as mock_put:
            mock_response = configure_selector_mock()
            mock_put.return_value = mock_response

            result = runner.invoke(
                put,
                [
                    html_url,
                    str(output_file),
                    '-d', 'key=value',
                    '-j', '{"data": "test"}'
                ]
            )
            assert result.exit_code == 0

    def test_extract_delete_command(self, runner, tmp_path, html_url):
        """Test extract `delete` command"""
        output_file = tmp_path / "output.html"

        with patch('scrapling.fetchers.Fetcher.delete') as mock_delete:
            mock_response = configure_selector_mock()
            mock_delete.return_value = mock_response

            result = runner.invoke(
                delete,
                [
                    html_url,
                    str(output_file)
                ]
            )
            assert result.exit_code == 0

    def test_extract_fetch_command(self, runner, tmp_path, html_url):
        """Test extract fetch command"""
        output_file = tmp_path / "output.txt"

        with patch('scrapling.fetchers.DynamicFetcher.fetch') as mock_fetch:
            mock_response = configure_selector_mock()
            mock_fetch.return_value = mock_response

            result = runner.invoke(
                fetch,
                [
                    html_url,
                    str(output_file),
                    '--headless',
                    '--timeout', '60000'
                ]
            )
            assert result.exit_code == 0

    def test_extract_stealthy_fetch_command(self, runner, tmp_path, html_url):
        """Test extract fetch command"""
        output_file = tmp_path / "output.md"

        with patch('scrapling.fetchers.StealthyFetcher.fetch') as mock_fetch:
            mock_response = configure_selector_mock()
            mock_fetch.return_value = mock_response

            result = runner.invoke(
                stealthy_fetch,
                [
                    html_url,
                    str(output_file),
                    '--headless',
                    '--css-selector', 'body',
                    '--timeout', '60000'
                ]
            )
            assert result.exit_code == 0

    def test_list_page_images_command(self, runner):
        """Test image listing CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "strategy": "fetch",
            "css_selector": "img",
            "count": 1,
            "images": [{"index": 0, "src": "/a.png", "absolute_url": "https://example.com/a.png"}],
        }

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.images.list_page_images', mock_operation):
            result = runner.invoke(
                list_page_images,
                [
                    'https://example.com/article',
                    '--strategy', 'fetch',
                    '--src-contains', '.png',
                ]
            )
            assert result.exit_code == 0
            assert '"count": 1' in result.output

    def test_fetch_page_image_command(self, runner, tmp_path):
        """Test image fetching CLI command"""
        output_file = tmp_path / "image.png"
        fake_result = MagicMock()
        fake_result.data = b"\x89PNG\r\n\x1a\nfakepng"
        fake_result.image_index = 0
        fake_result.page_url = "https://example.com/article"
        fake_result.image_url = "https://example.com/a.png"
        fake_result.mime_type = "image/png"
        fake_result.bytes_count = len(fake_result.data)
        fake_result.metadata_dict.return_value = {
            "page_url": fake_result.page_url,
            "image_url": fake_result.image_url,
            "strategy": "fetch",
            "mime_type": fake_result.mime_type,
            "bytes": fake_result.bytes_count,
            "image_index": 0,
            "candidate": {"index": 0, "src": "/a.png", "absolute_url": fake_result.image_url},
        }

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.images.fetch_page_image', mock_operation):
            result = runner.invoke(
                fetch_page_image,
                [
                    'https://example.com/article',
                    str(output_file),
                    '--metadata-format', 'json',
                ]
            )
            assert result.exit_code == 0
            assert output_file.exists()
            assert output_file.read_bytes() == fake_result.data
            assert '"mime_type": "image/png"' in result.output

    def test_extract_app_state_command(self, runner):
        """Test app-state extraction CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "strategy": "fetch",
            "count": 1,
            "states": [
                {
                    "kind": "next_data",
                    "key": "__NEXT_DATA__[0]",
                    "selector": "script#__NEXT_DATA__",
                    "data": {"page": "/article"},
                }
            ],
        }
        fake_result.to_text.return_value = "Page URL: https://example.com/article\nStates found: 1"
        fake_result.to_markdown.return_value = "# App State"

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.app_state.extract_app_state', mock_operation):
            result = runner.invoke(
                extract_app_state,
                [
                    'https://example.com/article',
                    '--kind', 'next_data',
                    '--format', 'markdown',
                ]
            )
            assert result.exit_code == 0
            assert "# App State" in result.output

    def test_observe_network_command(self, runner):
        """Test network observation CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "strategy": "fetch",
            "count": 1,
            "entries": [
                {
                    "index": 0,
                    "url": "https://example.com/api/items",
                    "method": "GET",
                    "resource_type": "fetch",
                    "status": 200,
                    "content_type": "application/json",
                    "stage": "responded",
                }
            ],
        }
        fake_result.to_text.return_value = "Requests observed: 1"
        fake_result.to_markdown.return_value = "# Network Observation"

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.network.observe_network', mock_operation):
            result = runner.invoke(
                observe_network,
                [
                    'https://example.com/article',
                    '--format', 'markdown',
                    '--include-bodies',
                ]
            )
            assert result.exit_code == 0
            assert "# Network Observation" in result.output

    def test_run_flow_and_extract_command(self, runner, tmp_path):
        """Test browser flow CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "final_url": "https://example.com/article?done=1",
            "strategy": "fetch",
            "extraction_type": "markdown",
            "css_selector": None,
            "content": ["Final content"],
            "actions": [{"index": 0, "type": "click", "status": "completed", "details": {"selector": "#go"}}],
            "network": [
                {
                    "index": 0,
                    "url": "https://example.com/api/items",
                    "method": "GET",
                    "resource_type": "fetch",
                    "status": 200,
                    "content_type": "application/json",
                    "stage": "responded",
                }
            ],
        }
        fake_result.to_text.return_value = "Final content"
        fake_result.to_markdown.return_value = "# Browser Flow"
        actions_file = tmp_path / "actions.json"
        actions_file.write_text('[{"type":"click","selector":"#go"}]', encoding="utf-8")

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.browser_flow.run_flow_and_extract', mock_operation):
            result = runner.invoke(
                run_flow_and_extract,
                [
                    'https://example.com/article',
                    '--actions-file', str(actions_file),
                    '--observe-network',
                    '--format', 'markdown',
                ]
            )
            assert result.exit_code == 0
            assert "# Browser Flow" in result.output
            assert mock_operation.await_args.kwargs["observe_network"] is True

    def test_debug_page_command(self, runner):
        """Test page debug CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "final_url": "https://example.com/app",
            "strategy": "fetch",
            "status": 200,
            "title": "App",
            "ready_state": "complete",
            "challenge_detected": None,
            "redirect_chain": [{"index": 0, "url": "https://example.com/login", "status": 302}],
            "page_errors": ["Uncaught ReferenceError: app is not defined"],
            "failed_requests": [],
            "network_count": 2,
        }
        fake_result.to_text.return_value = "Ready state: complete"
        fake_result.to_markdown.return_value = "# Page Debug"

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.debug.debug_page', mock_operation):
            result = runner.invoke(
                debug_page,
                [
                    'https://example.com/article',
                    '--format', 'markdown',
                ]
            )
            assert result.exit_code == 0
            assert "# Page Debug" in result.output

    def test_export_storage_state_command(self, runner):
        """Test storage state CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "final_url": "https://example.com/app",
            "strategy": "fetch",
            "cookies": [{"name": "session", "value": "abc123"}],
            "local_storage": {"token": "secret"},
            "session_storage": {"view": "dashboard"},
            "origins": [{"origin": "https://example.com", "local_storage": {"token": "secret"}}],
        }
        fake_result.to_text.return_value = "Cookies: 1"
        fake_result.to_markdown.return_value = "# Storage State"

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.storage_state.export_storage_state', mock_operation):
            result = runner.invoke(
                export_storage_state,
                [
                    'https://example.com/article',
                    '--format', 'markdown',
                ]
            )
            assert result.exit_code == 0
            assert "# Storage State" in result.output

    def test_discover_endpoints_command(self, runner, tmp_path):
        """Test endpoint discovery CLI command"""
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "page_url": "https://example.com/article",
            "final_url": "https://example.com/app",
            "strategy": "fetch",
            "count": 2,
            "endpoints": [
                {
                    "url": "https://example.com/api/bootstrap",
                    "method": "GET",
                    "kind": "api",
                    "resource_type": "fetch",
                    "status": 200,
                    "content_type": "application/json",
                    "graphql_operation_names": None,
                }
            ],
            "graphql_operations": [
                {
                    "name": "SearchProducts",
                    "endpoint_url": "https://example.com/graphql",
                    "method": "POST",
                }
            ],
            "websocket_urls": ["wss://example.com/socket"],
        }
        fake_result.to_text.return_value = "Endpoints discovered: 2"
        fake_result.to_markdown.return_value = "# Endpoint Discovery"
        actions_file = tmp_path / "actions.json"
        actions_file.write_text('[{"type":"click","selector":"#go"}]', encoding="utf-8")

        mock_operation = AsyncMock(return_value=fake_result)
        with patch('scrapling.operations.discover_endpoints.discover_endpoints', mock_operation):
            result = runner.invoke(
                discover_endpoints,
                [
                    'https://example.com/article',
                    '--actions-file', str(actions_file),
                    '--format', 'markdown',
                ]
            )
            assert result.exit_code == 0
            assert "# Endpoint Discovery" in result.output

    def test_invalid_arguments(self, runner, html_url):
        """Test invalid arguments handling"""
        # Missing required arguments
        result = runner.invoke(get)
        assert result.exit_code != 0

        _ = runner.invoke(
            get,
            [html_url, 'output.invalid']
        )
        # Should handle the error gracefully

    def test_impersonate_comma_separated(self, runner, tmp_path, html_url):
        """Test that comma-separated impersonate values are parsed correctly"""
        output_file = tmp_path / "output.md"

        with patch('scrapling.fetchers.Fetcher.get') as mock_get:
            mock_response = configure_selector_mock()
            mock_response.status = 200
            mock_get.return_value = mock_response

            result = runner.invoke(
                get,
                [
                    html_url,
                    str(output_file),
                    '--impersonate', 'chrome,firefox,safari'
                ]
            )
            assert result.exit_code == 0

            # Verify that the impersonate argument was converted to a list
            call_kwargs = mock_get.call_args[1]
            assert isinstance(call_kwargs['impersonate'], list)
            assert call_kwargs['impersonate'] == ['chrome', 'firefox', 'safari']

    def test_impersonate_single_browser(self, runner, tmp_path, html_url):
        """Test that single impersonate value remains as string"""
        output_file = tmp_path / "output.md"

        with patch('scrapling.fetchers.Fetcher.get') as mock_get:
            mock_response = configure_selector_mock()
            mock_response.status = 200
            mock_get.return_value = mock_response

            result = runner.invoke(
                get,
                [
                    html_url,
                    str(output_file),
                    '--impersonate', 'chrome'
                ]
            )
            assert result.exit_code == 0

            # Verify that the impersonate argument remains a string
            call_kwargs = mock_get.call_args[1]
            assert isinstance(call_kwargs['impersonate'], str)
            assert call_kwargs['impersonate'] == 'chrome'
