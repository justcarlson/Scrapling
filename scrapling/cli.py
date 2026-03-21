from pathlib import Path
from subprocess import check_output
from sys import executable as python_executable
from asyncio import run as asyncio_run
from json import dumps as json_dumps

from scrapling.core.utils import log
from scrapling.engines.toolbelt.custom import Response
from scrapling.core.utils._shell import _CookieParser, _ParseHeaders
from scrapling.core._types import List, Optional, Dict, Tuple, Any, Callable

from orjson import loads as json_loads, JSONDecodeError

try:
    from click import command, option, Choice, group, argument
except (ImportError, ModuleNotFoundError) as e:
    raise ModuleNotFoundError(
        "You need to install scrapling with any of the extras to enable Shell commands. See: https://scrapling.readthedocs.io/en/latest/#installation"
    ) from e

__OUTPUT_FILE_HELP__ = "The output file path can be an HTML file, a Markdown file of the HTML content, or the text content itself. Use file extensions (`.html`/`.md`/`.txt`) respectively."
__PACKAGE_DIR__ = Path(__file__).parent


def __Execute(cmd: List[str], help_line: str) -> None:  # pragma: no cover
    print(f"Installing {help_line}...")
    _ = check_output(cmd, shell=False)  # nosec B603
    # I meant to not use try except here


def __ParseJSONData(json_string: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse JSON string into a Python object"""
    if not json_string:
        return None

    try:
        return json_loads(json_string)
    except JSONDecodeError as err:  # pragma: no cover
        raise ValueError(f"Invalid JSON data '{json_string}': {err}")


def __Request_and_Save(
    fetcher_func: Callable[..., Response],
    url: str,
    output_file: str,
    css_selector: Optional[str] = None,
    **kwargs,
) -> None:
    """Make a request using the specified fetcher function and save the result"""
    from scrapling.core.shell import Convertor

    # Handle relative paths - convert to an absolute path based on the current working directory
    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_file

    response = fetcher_func(url, **kwargs)
    Convertor.write_content_to_file(response, str(output_path), css_selector)
    log.info(f"Content successfully saved to '{output_path}'")


def __ResolveOutputPath(output_file: str) -> Path:
    """Resolve output paths relative to the current working directory."""
    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_file
    return output_path


def __WriteBinaryFile(output_file: str, data: bytes) -> Path:
    """Write raw bytes to disk and return the resolved output path."""
    output_path = __ResolveOutputPath(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return output_path


def __ParseExtractArguments(
    headers: List[str], cookies: str, params: str, json: Optional[str] = None
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str], Optional[Dict[str, str]]]:
    """Parse arguments for extract command"""
    parsed_headers, parsed_cookies = _ParseHeaders(headers)
    if cookies:
        for key, value in _CookieParser(cookies):
            try:
                parsed_cookies[key] = value
            except Exception as err:
                raise ValueError(f"Could not parse cookies '{cookies}': {err}")

    parsed_json = __ParseJSONData(json)
    parsed_params = {}
    for param in params:
        if "=" in param:
            key, value = param.split("=", 1)
            parsed_params[key] = value

    return parsed_headers, parsed_cookies, parsed_params, parsed_json


def __BuildRequest(headers: List[str], cookies: str, params: str, json: Optional[str] = None, **kwargs) -> Dict:
    """Build a request object using the specified arguments"""
    # Parse parameters
    parsed_headers, parsed_cookies, parsed_params, parsed_json = __ParseExtractArguments(headers, cookies, params, json)
    # Build request arguments
    request_kwargs: Dict[str, Any] = {
        "headers": parsed_headers if parsed_headers else None,
        "cookies": parsed_cookies if parsed_cookies else None,
    }
    if parsed_json:
        request_kwargs["json"] = parsed_json
    if parsed_params:
        request_kwargs["params"] = parsed_params
    if "proxy" in kwargs:
        request_kwargs["proxy"] = kwargs.pop("proxy")

    # Parse impersonate parameter if it contains commas (for random selection)
    if "impersonate" in kwargs and "," in (kwargs.get("impersonate") or ""):
        kwargs["impersonate"] = [browser.strip() for browser in kwargs["impersonate"].split(",")]

    return {**request_kwargs, **kwargs}


def __ReadJSONInput(json_string: Optional[str], json_file: Optional[str]) -> Any:
    """Read JSON from either a direct string or a file path."""
    if json_string and json_file:
        raise ValueError("Use either a JSON string or a JSON file, not both.")
    if json_file:
        return json_loads(Path(json_file).read_text(encoding="utf-8"))
    if json_string:
        return json_loads(json_string)
    return None


@command(help="Install all Scrapling's Fetchers dependencies")
@option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    default=False,
    type=bool,
    help="Force Scrapling to reinstall all Fetchers dependencies",
)
def install(force):  # pragma: no cover
    if force or not __PACKAGE_DIR__.joinpath(".scrapling_dependencies_installed").exists():
        __Execute(
            [python_executable, "-m", "playwright", "install", "chromium"],
            "Playwright browsers",
        )
        __Execute(
            [
                python_executable,
                "-m",
                "playwright",
                "install-deps",
                "chromium",
            ],
            "Playwright dependencies",
        )
        from tld.utils import update_tld_names

        update_tld_names(fail_silently=True)
        # if no errors raised by the above commands, then we add the below file
        __PACKAGE_DIR__.joinpath(".scrapling_dependencies_installed").touch()
    else:
        print("The dependencies are already installed")


@command(help="Run Scrapling's MCP server (Check the docs for more info).")
@option(
    "--http",
    is_flag=True,
    default=False,
    help="Whether to run the MCP server in streamable-http transport or leave it as stdio (Default: False)",
)
@option(
    "--host",
    type=str,
    default="0.0.0.0",
    help="The host to use if streamable-http transport is enabled (Default: '0.0.0.0')",
)
@option(
    "--port", type=int, default=8000, help="The port to use if streamable-http transport is enabled (Default: 8000)"
)
def mcp(http, host, port):
    from scrapling.core.ai import ScraplingMCPServer

    server = ScraplingMCPServer()
    server.serve(http, host, port)


@command(help="Interactive scraping console")
@option(
    "-c",
    "--code",
    "code",
    is_flag=False,
    default="",
    type=str,
    help="Evaluate the code in the shell, print the result and exit",
)
@option(
    "-L",
    "--loglevel",
    "level",
    is_flag=False,
    default="debug",
    type=Choice(["debug", "info", "warning", "error", "critical", "fatal"], case_sensitive=False),
    help="Log level (default: DEBUG)",
)
def shell(code, level):
    from scrapling.core.shell import CustomShell

    console = CustomShell(code=code, log_level=level)
    console.start()


@group(
    help="Fetch web pages using various fetchers and extract full/selected HTML content as HTML, Markdown, or extract text content."
)
def extract():
    """Extract content from web pages and save to files"""
    pass


@group(name="inspect", help="Inspect fetched pages and assets with structured outputs and artifacts.")
def inspect_group():
    """Inspect pages and page-derived assets"""
    pass


@extract.command(help=f"Perform a GET request and save the content to a file.\n\n{__OUTPUT_FILE_HELP__}")
@argument("url", required=True)
@argument("output_file", required=True)
@option(
    "--headers",
    "-H",
    multiple=True,
    help='HTTP headers in format "Key: Value" (can be used multiple times)',
)
@option("--cookies", help='Cookies string in format "name1=value1; name2=value2"')
@option("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
@option("--proxy", help='Proxy URL in format "http://username:password@host:port"')
@option(
    "--css-selector",
    "-s",
    help="CSS selector to extract specific content from the page. It returns all matches.",
)
@option(
    "--params",
    "-p",
    multiple=True,
    help='Query parameters in format "key=value" (can be used multiple times)',
)
@option(
    "--follow-redirects/--no-follow-redirects",
    default=True,
    help="Whether to follow redirects (default: True)",
)
@option(
    "--verify/--no-verify",
    default=True,
    help="Whether to verify SSL certificates (default: True)",
)
@option(
    "--impersonate",
    help="Browser to impersonate. Can be a single browser (e.g., chrome) or comma-separated list for random selection (e.g., chrome,firefox,safari).",
)
@option(
    "--stealthy-headers/--no-stealthy-headers",
    default=True,
    help="Use stealthy browser headers (default: True)",
)
def get(
    url,
    output_file,
    headers,
    cookies,
    timeout,
    proxy,
    css_selector,
    params,
    follow_redirects,
    verify,
    impersonate,
    stealthy_headers,
):
    """
    Perform a GET request and save the content to a file.

    :param url: Target URL for the request.
    :param output_file: Output file path (.md for Markdown, .html for HTML).
    :param headers: HTTP headers to include in the request.
    :param cookies: Cookies to use in the request.
    :param timeout: Number of seconds to wait before timing out.
    :param proxy: Proxy URL to use. (Format: "http://username:password@localhost:8030")
    :param css_selector: CSS selector to extract specific content.
    :param params: Query string parameters for the request.
    :param follow_redirects: Whether to follow redirects.
    :param verify: Whether to verify HTTPS certificates.
    :param impersonate: Browser version to impersonate.
    :param stealthy_headers: If enabled, creates and adds real browser headers.
    """

    kwargs = __BuildRequest(
        headers,
        cookies,
        params,
        None,
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify=verify,
        stealthy_headers=stealthy_headers,
        impersonate=impersonate,
        proxy=proxy,
    )
    from scrapling.fetchers import Fetcher

    __Request_and_Save(Fetcher.get, url, output_file, css_selector, **kwargs)


@extract.command(help=f"Perform a POST request and save the content to a file.\n\n{__OUTPUT_FILE_HELP__}")
@argument("url", required=True)
@argument("output_file", required=True)
@option(
    "--data",
    "-d",
    help='Form data to include in the request body (as string, ex: "param1=value1&param2=value2")',
)
@option("--json", "-j", help="JSON data to include in the request body (as string)")
@option(
    "--headers",
    "-H",
    multiple=True,
    help='HTTP headers in format "Key: Value" (can be used multiple times)',
)
@option("--cookies", help='Cookies string in format "name1=value1; name2=value2"')
@option("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
@option("--proxy", help='Proxy URL in format "http://username:password@host:port"')
@option(
    "--css-selector",
    "-s",
    help="CSS selector to extract specific content from the page. It returns all matches.",
)
@option(
    "--params",
    "-p",
    multiple=True,
    help='Query parameters in format "key=value" (can be used multiple times)',
)
@option(
    "--follow-redirects/--no-follow-redirects",
    default=True,
    help="Whether to follow redirects (default: True)",
)
@option(
    "--verify/--no-verify",
    default=True,
    help="Whether to verify SSL certificates (default: True)",
)
@option(
    "--impersonate",
    help="Browser to impersonate. Can be a single browser (e.g., chrome) or comma-separated list for random selection (e.g., chrome,firefox,safari).",
)
@option(
    "--stealthy-headers/--no-stealthy-headers",
    default=True,
    help="Use stealthy browser headers (default: True)",
)
def post(
    url,
    output_file,
    data,
    json,
    headers,
    cookies,
    timeout,
    proxy,
    css_selector,
    params,
    follow_redirects,
    verify,
    impersonate,
    stealthy_headers,
):
    """
    Perform a POST request and save the content to a file.

    :param url: Target URL for the request.
    :param output_file: Output file path (.md for Markdown, .html for HTML).
    :param data: Form data to include in the request body. (as string, ex: "param1=value1&param2=value2")
    :param json: A JSON serializable object to include in the body of the request.
    :param headers: Headers to include in the request.
    :param cookies: Cookies to use in the request.
    :param timeout: Number of seconds to wait before timing out.
    :param proxy: Proxy URL to use.
    :param css_selector: CSS selector to extract specific content.
    :param params: Query string parameters for the request.
    :param follow_redirects: Whether to follow redirects.
    :param verify: Whether to verify HTTPS certificates.
    :param impersonate: Browser version to impersonate.
    :param stealthy_headers: If enabled, creates and adds real browser headers.
    """

    kwargs = __BuildRequest(
        headers,
        cookies,
        params,
        json,
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify=verify,
        stealthy_headers=stealthy_headers,
        impersonate=impersonate,
        proxy=proxy,
        data=data,
    )
    from scrapling.fetchers import Fetcher

    __Request_and_Save(Fetcher.post, url, output_file, css_selector, **kwargs)


@extract.command(help=f"Perform a PUT request and save the content to a file.\n\n{__OUTPUT_FILE_HELP__}")
@argument("url", required=True)
@argument("output_file", required=True)
@option("--data", "-d", help="Form data to include in the request body")
@option("--json", "-j", help="JSON data to include in the request body (as string)")
@option(
    "--headers",
    "-H",
    multiple=True,
    help='HTTP headers in format "Key: Value" (can be used multiple times)',
)
@option("--cookies", help='Cookies string in format "name1=value1; name2=value2"')
@option("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
@option("--proxy", help='Proxy URL in format "http://username:password@host:port"')
@option(
    "--css-selector",
    "-s",
    help="CSS selector to extract specific content from the page. It returns all matches.",
)
@option(
    "--params",
    "-p",
    multiple=True,
    help='Query parameters in format "key=value" (can be used multiple times)',
)
@option(
    "--follow-redirects/--no-follow-redirects",
    default=True,
    help="Whether to follow redirects (default: True)",
)
@option(
    "--verify/--no-verify",
    default=True,
    help="Whether to verify SSL certificates (default: True)",
)
@option(
    "--impersonate",
    help="Browser to impersonate. Can be a single browser (e.g., chrome) or comma-separated list for random selection (e.g., chrome,firefox,safari).",
)
@option(
    "--stealthy-headers/--no-stealthy-headers",
    default=True,
    help="Use stealthy browser headers (default: True)",
)
def put(
    url,
    output_file,
    data,
    json,
    headers,
    cookies,
    timeout,
    proxy,
    css_selector,
    params,
    follow_redirects,
    verify,
    impersonate,
    stealthy_headers,
):
    """
    Perform a PUT request and save the content to a file.

    :param url: Target URL for the request.
    :param output_file: Output file path (.md for Markdown, .html for HTML).
    :param data: Form data to include in the request body.
    :param json: A JSON serializable object to include in the body of the request.
    :param headers: Headers to include in the request.
    :param cookies: Cookies to use in the request.
    :param timeout: Number of seconds to wait before timing out.
    :param proxy: Proxy URL to use.
    :param css_selector: CSS selector to extract specific content.
    :param params: Query string parameters for the request.
    :param follow_redirects: Whether to follow redirects.
    :param verify: Whether to verify HTTPS certificates.
    :param impersonate: Browser version to impersonate.
    :param stealthy_headers: If enabled, creates and adds real browser headers.
    """

    kwargs = __BuildRequest(
        headers,
        cookies,
        params,
        json,
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify=verify,
        stealthy_headers=stealthy_headers,
        impersonate=impersonate,
        proxy=proxy,
        data=data,
    )
    from scrapling.fetchers import Fetcher

    __Request_and_Save(Fetcher.put, url, output_file, css_selector, **kwargs)


@extract.command(help=f"Perform a DELETE request and save the content to a file.\n\n{__OUTPUT_FILE_HELP__}")
@argument("url", required=True)
@argument("output_file", required=True)
@option(
    "--headers",
    "-H",
    multiple=True,
    help='HTTP headers in format "Key: Value" (can be used multiple times)',
)
@option("--cookies", help='Cookies string in format "name1=value1; name2=value2"')
@option("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
@option("--proxy", help='Proxy URL in format "http://username:password@host:port"')
@option(
    "--css-selector",
    "-s",
    help="CSS selector to extract specific content from the page. It returns all matches.",
)
@option(
    "--params",
    "-p",
    multiple=True,
    help='Query parameters in format "key=value" (can be used multiple times)',
)
@option(
    "--follow-redirects/--no-follow-redirects",
    default=True,
    help="Whether to follow redirects (default: True)",
)
@option(
    "--verify/--no-verify",
    default=True,
    help="Whether to verify SSL certificates (default: True)",
)
@option(
    "--impersonate",
    help="Browser to impersonate. Can be a single browser (e.g., chrome) or comma-separated list for random selection (e.g., chrome,firefox,safari).",
)
@option(
    "--stealthy-headers/--no-stealthy-headers",
    default=True,
    help="Use stealthy browser headers (default: True)",
)
def delete(
    url,
    output_file,
    headers,
    cookies,
    timeout,
    proxy,
    css_selector,
    params,
    follow_redirects,
    verify,
    impersonate,
    stealthy_headers,
):
    """
    Perform a DELETE request and save the content to a file.

    :param url: Target URL for the request.
    :param output_file: Output file path (.md for Markdown, .html for HTML).
    :param headers: Headers to include in the request.
    :param cookies: Cookies to use in the request.
    :param timeout: Number of seconds to wait before timing out.
    :param proxy: Proxy URL to use.
    :param css_selector: CSS selector to extract specific content.
    :param params: Query string parameters for the request.
    :param follow_redirects: Whether to follow redirects.
    :param verify: Whether to verify HTTPS certificates.
    :param impersonate: Browser version to impersonate.
    :param stealthy_headers: If enabled, creates and adds real browser headers.
    """

    kwargs = __BuildRequest(
        headers,
        cookies,
        params,
        None,
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify=verify,
        stealthy_headers=stealthy_headers,
        impersonate=impersonate,
        proxy=proxy,
    )
    from scrapling.fetchers import Fetcher

    __Request_and_Save(Fetcher.delete, url, output_file, css_selector, **kwargs)


@extract.command(help=f"Use DynamicFetcher to fetch content with browser automation.\n\n{__OUTPUT_FILE_HELP__}")
@argument("url", required=True)
@argument("output_file", required=True)
@option(
    "--headless/--no-headless",
    default=True,
    help="Run browser in headless mode (default: True)",
)
@option(
    "--disable-resources/--enable-resources",
    default=False,
    help="Drop unnecessary resources for speed boost (default: False)",
)
@option(
    "--network-idle/--no-network-idle",
    default=False,
    help="Wait for network idle (default: False)",
)
@option(
    "--timeout",
    type=int,
    default=30000,
    help="Timeout in milliseconds (default: 30000)",
)
@option(
    "--wait",
    type=int,
    default=0,
    help="Additional wait time in milliseconds after page load (default: 0)",
)
@option(
    "--css-selector",
    "-s",
    help="CSS selector to extract specific content from the page. It returns all matches.",
)
@option("--wait-selector", help="CSS selector to wait for before proceeding")
@option("--locale", default=None, help="Specify user locale. Defaults to the system default locale.")
@option(
    "--real-chrome/--no-real-chrome",
    default=False,
    help="If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it. (default: False)",
)
@option("--proxy", help='Proxy URL in format "http://username:password@host:port"')
@option(
    "--extra-headers",
    "-H",
    multiple=True,
    help='Extra headers in format "Key: Value" (can be used multiple times)',
)
def fetch(
    url,
    output_file,
    headless,
    disable_resources,
    network_idle,
    timeout,
    wait,
    css_selector,
    wait_selector,
    locale,
    real_chrome,
    proxy,
    extra_headers,
):
    """
    Opens up a browser and fetch content using DynamicFetcher.

    :param url: Target url.
    :param output_file: Output file path (.md for Markdown, .html for HTML).
    :param headless: Run the browser in headless/hidden or headful/visible mode.
    :param disable_resources: Drop requests of unnecessary resources for a speed boost.
    :param network_idle: Wait for the page until there are no network connections for at least 500 ms.
    :param timeout: The timeout in milliseconds that is used in all operations and waits through the page.
    :param wait: The time (milliseconds) the fetcher will wait after everything finishes before returning.
    :param css_selector: CSS selector to extract specific content.
    :param wait_selector: Wait for a specific CSS selector to be in a specific state.
    :param locale: Set the locale for the browser.
    :param real_chrome: If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it.
    :param proxy: The proxy to be used with requests.
    :param extra_headers: Extra headers to add to the request.
    """

    # Parse parameters
    parsed_headers, _ = _ParseHeaders(extra_headers, False)

    # Build request arguments
    kwargs = {
        "headless": headless,
        "disable_resources": disable_resources,
        "network_idle": network_idle,
        "timeout": timeout,
        "locale": locale,
        "real_chrome": real_chrome,
    }

    if wait > 0:
        kwargs["wait"] = wait
    if wait_selector:
        kwargs["wait_selector"] = wait_selector
    if proxy:
        kwargs["proxy"] = proxy
    if parsed_headers:
        kwargs["extra_headers"] = parsed_headers

    from scrapling.fetchers import DynamicFetcher

    __Request_and_Save(DynamicFetcher.fetch, url, output_file, css_selector, **kwargs)


@extract.command(help=f"Use StealthyFetcher to fetch content with advanced stealth features.\n\n{__OUTPUT_FILE_HELP__}")
@argument("url", required=True)
@argument("output_file", required=True)
@option(
    "--headless/--no-headless",
    default=True,
    help="Run browser in headless mode (default: True)",
)
@option(
    "--disable-resources/--enable-resources",
    default=False,
    help="Drop unnecessary resources for speed boost (default: False)",
)
@option(
    "--block-webrtc/--allow-webrtc",
    default=False,
    help="Block WebRTC entirely (default: False)",
)
@option(
    "--solve-cloudflare/--no-solve-cloudflare",
    default=False,
    help="Solve Cloudflare challenges (default: False)",
)
@option("--allow-webgl/--block-webgl", default=True, help="Allow WebGL (default: True)")
@option(
    "--network-idle/--no-network-idle",
    default=False,
    help="Wait for network idle (default: False)",
)
@option(
    "--real-chrome/--no-real-chrome",
    default=False,
    help="If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it. (default: False)",
)
@option(
    "--hide-canvas/--show-canvas",
    default=False,
    help="Add noise to canvas operations (default: False)",
)
@option(
    "--timeout",
    type=int,
    default=30000,
    help="Timeout in milliseconds (default: 30000)",
)
@option(
    "--wait",
    type=int,
    default=0,
    help="Additional wait time in milliseconds after page load (default: 0)",
)
@option(
    "--css-selector",
    "-s",
    help="CSS selector to extract specific content from the page. It returns all matches.",
)
@option("--wait-selector", help="CSS selector to wait for before proceeding")
@option("--proxy", help='Proxy URL in format "http://username:password@host:port"')
@option(
    "--extra-headers",
    "-H",
    multiple=True,
    help='Extra headers in format "Key: Value" (can be used multiple times)',
)
def stealthy_fetch(
    url,
    output_file,
    headless,
    disable_resources,
    block_webrtc,
    solve_cloudflare,
    allow_webgl,
    network_idle,
    real_chrome,
    hide_canvas,
    timeout,
    wait,
    css_selector,
    wait_selector,
    proxy,
    extra_headers,
):
    """
    Opens up a browser with advanced stealth features and fetch content using StealthyFetcher.

    :param url: Target url.
    :param output_file: Output file path (.md for Markdown, .html for HTML).
    :param headless: Run the browser in headless/hidden, or headful/visible mode.
    :param disable_resources: Drop requests of unnecessary resources for a speed boost.
    :param block_webrtc: Blocks WebRTC entirely.
    :param solve_cloudflare: Solves all types of the Cloudflare's Turnstile/Interstitial challenges.
    :param allow_webgl: Allow WebGL (recommended to keep enabled).
    :param network_idle: Wait for the page until there are no network connections for at least 500 ms.
    :param real_chrome: If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it.
    :param hide_canvas: Add random noise to canvas operations to prevent fingerprinting.
    :param timeout: The timeout in milliseconds that is used in all operations and waits through the page.
    :param wait: The time (milliseconds) the fetcher will wait after everything finishes before returning.
    :param css_selector: CSS selector to extract specific content.
    :param wait_selector: Wait for a specific CSS selector to be in a specific state.
    :param proxy: The proxy to be used with requests.
    :param extra_headers: Extra headers to add to the request.
    """

    # Parse parameters
    parsed_headers, _ = _ParseHeaders(extra_headers, False)

    # Build request arguments
    kwargs = {
        "headless": headless,
        "disable_resources": disable_resources,
        "block_webrtc": block_webrtc,
        "solve_cloudflare": solve_cloudflare,
        "allow_webgl": allow_webgl,
        "network_idle": network_idle,
        "real_chrome": real_chrome,
        "hide_canvas": hide_canvas,
        "timeout": timeout,
    }

    if wait > 0:
        kwargs["wait"] = wait
    if wait_selector:
        kwargs["wait_selector"] = wait_selector
    if proxy:
        kwargs["proxy"] = proxy
    if parsed_headers:
        kwargs["extra_headers"] = parsed_headers

    from scrapling.fetchers import StealthyFetcher

    __Request_and_Save(StealthyFetcher.fetch, url, output_file, css_selector, **kwargs)


@inspect_group.command(name="list-page-images", help="List page image candidates as structured JSON.")
@argument("page_url", required=True)
@option(
    "--strategy",
    type=Choice(["get", "fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Fetching strategy to use.",
)
@option("--css-selector", default="img", show_default=True, help="CSS selector used to match image nodes.")
@option("--src-contains", default=None, help="Filter candidates by partial match against the raw or absolute URL.")
@option("--max-results", type=int, default=20, show_default=True, help="Maximum number of candidates to return.")
def list_page_images(page_url, strategy, css_selector, src_contains, max_results):
    """List page image candidates as structured JSON."""
    from scrapling.operations.images import list_page_images as list_page_images_operation

    result = asyncio_run(
        list_page_images_operation(
            page_url=page_url,
            strategy=strategy,
            css_selector=css_selector,
            src_contains=src_contains,
            max_results=max_results,
        )
    )
    print(json_dumps(result.to_dict(), indent=2))


@inspect_group.command(name="fetch-page-image", help="Fetch one page-matched image and save it to disk.")
@argument("page_url", required=True)
@argument("output_file", required=True)
@option(
    "--strategy",
    type=Choice(["get", "fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Fetching strategy to use.",
)
@option("--css-selector", default="img", show_default=True, help="CSS selector used to match image nodes.")
@option("--image-index", type=int, default=0, show_default=True, help="Zero-based candidate index to fetch.")
@option("--src-contains", default=None, help="Filter candidates by partial match against the raw or absolute URL.")
@option("--max-results", type=int, default=20, show_default=True, help="Maximum number of candidates to consider.")
@option(
    "--metadata-format",
    type=Choice(["text", "json", "none"], case_sensitive=False),
    default="text",
    show_default=True,
    help="How to print metadata for the fetched image.",
)
def fetch_page_image(page_url, output_file, strategy, css_selector, image_index, src_contains, max_results, metadata_format):
    """Fetch one page-matched image, save it to disk, and optionally print metadata."""
    from scrapling.operations.images import fetch_page_image as fetch_page_image_operation

    result = asyncio_run(
        fetch_page_image_operation(
            page_url=page_url,
            strategy=strategy,
            css_selector=css_selector,
            image_index=image_index,
            src_contains=src_contains,
            max_results=max_results,
        )
    )
    output_path = __WriteBinaryFile(output_file, result.data)
    metadata = {**result.metadata_dict(), "output_file": str(output_path)}

    if metadata_format == "json":
        print(json_dumps(metadata, indent=2))
    elif metadata_format == "text":
        print(
            "\n".join(
                (
                    f"Saved image {result.image_index} from {result.page_url}",
                    f"Resolved URL: {result.image_url}",
                    f"MIME type: {result.mime_type}",
                    f"Size: {result.bytes_count} bytes",
                    f"Output file: {output_path}",
                )
            )
        )


@inspect_group.command(name="extract-app-state", help="Extract common app-state payloads from a page.")
@argument("page_url", required=True)
@option(
    "--strategy",
    type=Choice(["get", "fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Fetching strategy to use.",
)
@option(
    "--kind",
    "kinds",
    multiple=True,
    type=Choice(["next_data", "nuxt_data", "json_ld", "application_json"], case_sensitive=False),
    help="State kinds to extract. Repeat to narrow the output.",
)
@option(
    "--format",
    "output_format",
    type=Choice(["json", "text", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
    help="How to print the extracted app state.",
)
def extract_app_state(page_url, strategy, kinds, output_format):
    """Extract common app-state payloads and print them in the selected format."""
    from scrapling.operations.app_state import extract_app_state as extract_app_state_operation

    result = asyncio_run(
        extract_app_state_operation(
            page_url=page_url,
            strategy=strategy,
            kinds=list(kinds) if kinds else None,
        )
    )

    if output_format == "json":
        print(json_dumps(result.to_dict(), indent=2))
    elif output_format == "markdown":
        print(result.to_markdown())
    else:
        print(result.to_text())


@inspect_group.command(name="observe-network", help="Observe browser-side network activity for a page.")
@argument("page_url", required=True)
@option(
    "--strategy",
    type=Choice(["fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Browser-backed strategy to use.",
)
@option(
    "--format",
    "output_format",
    type=Choice(["json", "text", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
    help="How to print the observed network activity.",
)
@option("--include-headers/--no-include-headers", default=False, help="Include request and response headers.")
@option("--include-bodies/--no-include-bodies", default=False, help="Include textual response previews when possible.")
@option("--max-entries", type=int, default=100, show_default=True, help="Maximum number of requests to include.")
@option("--max-body-chars", type=int, default=2000, show_default=True, help="Maximum response preview size.")
@option("--url-contains", default=None, help="Optional substring filter for observed request URLs.")
def observe_network(page_url, strategy, output_format, include_headers, include_bodies, max_entries, max_body_chars, url_contains):
    """Observe browser-side network activity and print it in the selected format."""
    from scrapling.operations.network import observe_network as observe_network_operation

    result = asyncio_run(
        observe_network_operation(
            page_url=page_url,
            strategy=strategy,
            include_headers=include_headers,
            include_bodies=include_bodies,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )
    )

    if output_format == "json":
        print(json_dumps(result.to_dict(), indent=2))
    elif output_format == "markdown":
        print(result.to_markdown())
    else:
        print(result.to_text())


@inspect_group.command(name="run-flow-and-extract", help="Run a declarative browser flow and extract the final content.")
@argument("page_url", required=True)
@option(
    "--actions-json",
    default=None,
    help="JSON array describing the browser actions to execute.",
)
@option(
    "--actions-file",
    default=None,
    help="Path to a JSON file describing the browser actions to execute.",
)
@option(
    "--strategy",
    type=Choice(["fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Browser-backed strategy to use.",
)
@option(
    "--extraction-type",
    type=Choice(["markdown", "html", "text"], case_sensitive=False),
    default="markdown",
    show_default=True,
    help="Final extraction type.",
)
@option("--css-selector", default=None, help="Optional CSS selector for the final extraction.")
@option("--observe-network/--no-observe-network", default=False, help="Capture request/response activity during the flow.")
@option("--include-headers/--no-include-headers", default=False, help="Include request and response headers when observing network activity.")
@option("--include-bodies/--no-include-bodies", default=False, help="Include textual response previews when observing network activity.")
@option("--max-entries", type=int, default=100, show_default=True, help="Maximum number of observed requests to include.")
@option("--max-body-chars", type=int, default=2000, show_default=True, help="Maximum response preview size when observing network activity.")
@option("--url-contains", default=None, help="Optional substring filter for observed request URLs.")
@option(
    "--format",
    "output_format",
    type=Choice(["json", "text", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
    help="How to print the flow result.",
)
def run_flow_and_extract(
    page_url,
    actions_json,
    actions_file,
    strategy,
    extraction_type,
    css_selector,
    observe_network,
    include_headers,
    include_bodies,
    max_entries,
    max_body_chars,
    url_contains,
    output_format,
):
    """Run a declarative browser flow and print the extracted final content."""
    from scrapling.operations.browser_flow import run_flow_and_extract as run_flow_and_extract_operation

    actions = __ReadJSONInput(actions_json, actions_file) or []
    if not isinstance(actions, list):
        raise ValueError("Actions must be a JSON array.")

    result = asyncio_run(
        run_flow_and_extract_operation(
            page_url=page_url,
            actions=actions,
            strategy=strategy,
            extraction_type=extraction_type,
            css_selector=css_selector,
            observe_network=observe_network,
            include_headers=include_headers,
            include_bodies=include_bodies,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )
    )

    if output_format == "json":
        print(json_dumps(result.to_dict(), indent=2))
    elif output_format == "markdown":
        print(result.to_markdown())
    else:
        print(result.to_text())


@inspect_group.command(name="debug-page", help="Load a page in the browser and return a compact diagnostic summary.")
@argument("page_url", required=True)
@option(
    "--strategy",
    type=Choice(["fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Browser-backed strategy to use.",
)
@option("--max-entries", type=int, default=100, show_default=True, help="Maximum number of observed requests to track.")
@option(
    "--format",
    "output_format",
    type=Choice(["json", "text", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
    help="How to print the page diagnostics.",
)
def debug_page(page_url, strategy, max_entries, output_format):
    """Load a page in the browser and print a diagnostic summary."""
    from scrapling.operations.debug import debug_page as debug_page_operation

    result = asyncio_run(
        debug_page_operation(
            page_url=page_url,
            strategy=strategy,
            max_entries=max_entries,
        )
    )

    if output_format == "json":
        print(json_dumps(result.to_dict(), indent=2))
    elif output_format == "markdown":
        print(result.to_markdown())
    else:
        print(result.to_text())


@inspect_group.command(name="export-storage-state", help="Load a page in the browser and print cookies plus web-storage state.")
@argument("page_url", required=True)
@option(
    "--strategy",
    type=Choice(["fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Browser-backed strategy to use.",
)
@option(
    "--format",
    "output_format",
    type=Choice(["json", "text", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
    help="How to print the storage snapshot.",
)
def export_storage_state(page_url, strategy, output_format):
    """Load a page in the browser and print cookies plus web-storage state."""
    from scrapling.operations.storage_state import export_storage_state as export_storage_state_operation

    result = asyncio_run(
        export_storage_state_operation(
            page_url=page_url,
            strategy=strategy,
        )
    )

    if output_format == "json":
        print(json_dumps(result.to_dict(), indent=2))
    elif output_format == "markdown":
        print(result.to_markdown())
    else:
        print(result.to_text())


@inspect_group.command(name="discover-endpoints", help="Discover likely API, GraphQL, and WebSocket endpoints from browser traffic.")
@argument("page_url", required=True)
@option(
    "--actions-json",
    default=None,
    help="Optional JSON array describing browser actions to execute before summarizing endpoints.",
)
@option(
    "--actions-file",
    default=None,
    help="Optional path to a JSON file describing browser actions to execute before summarizing endpoints.",
)
@option(
    "--strategy",
    type=Choice(["fetch", "stealthy_fetch"], case_sensitive=False),
    default="fetch",
    show_default=True,
    help="Browser-backed strategy to use.",
)
@option("--max-entries", type=int, default=100, show_default=True, help="Maximum number of observed requests to inspect.")
@option("--max-body-chars", type=int, default=4000, show_default=True, help="Maximum request body size retained for discovery.")
@option("--url-contains", default=None, help="Optional substring filter for observed request URLs.")
@option(
    "--format",
    "output_format",
    type=Choice(["json", "text", "markdown"], case_sensitive=False),
    default="json",
    show_default=True,
    help="How to print the discovered endpoints.",
)
def discover_endpoints(page_url, actions_json, actions_file, strategy, max_entries, max_body_chars, url_contains, output_format):
    """Discover likely API, GraphQL, and WebSocket endpoints from browser traffic."""
    from scrapling.operations.discover_endpoints import discover_endpoints as discover_endpoints_operation

    actions = __ReadJSONInput(actions_json, actions_file)
    if actions is not None and not isinstance(actions, list):
        raise ValueError("Actions must be a JSON array.")

    result = asyncio_run(
        discover_endpoints_operation(
            page_url=page_url,
            actions=actions,
            strategy=strategy,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )
    )

    if output_format == "json":
        print(json_dumps(result.to_dict(), indent=2))
    elif output_format == "markdown":
        print(result.to_markdown())
    else:
        print(result.to_text())


@group()
def main():
    pass


# Adding commands
main.add_command(install)
main.add_command(shell)
main.add_command(extract)
main.add_command(inspect_group)
main.add_command(mcp)


if __name__ == "__main__":
    main()
