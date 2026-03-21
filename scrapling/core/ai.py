import base64
from asyncio import gather

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import BaseModel, Field

from scrapling.core.shell import Convertor
from scrapling.engines.toolbelt.custom import Response as _ScraplingResponse
from scrapling.engines.static import ImpersonateType
from scrapling.fetchers import (
    Fetcher,
    FetcherSession,
    DynamicFetcher,
    AsyncDynamicSession,
    StealthyFetcher,
    AsyncStealthySession,
)
from scrapling.core._types import (
    Optional,
    Tuple,
    Mapping,
    Dict,
    List,
    Any,
    Generator,
    Sequence,
    SetCookieParam,
    extraction_types,
    SelectorWaitStates,
)
from scrapling.operations.images import (
    ImageCandidatesResult as SharedImageCandidatesResult,
    fetch_page_image as fetch_page_image_operation,
    list_page_images as list_page_images_operation,
)
from scrapling.operations.app_state import AppStateResult as SharedAppStateResult, extract_app_state as extract_app_state_operation
from scrapling.operations.network import NetworkObservationResult as SharedNetworkObservationResult, observe_network as observe_network_operation
from scrapling.operations.browser_flow import FlowExtractResult as SharedFlowExtractResult, run_flow_and_extract as run_flow_and_extract_operation
from scrapling.operations.debug import PageDebugResult as SharedPageDebugResult, debug_page as debug_page_operation
from scrapling.operations.storage_state import StorageStateResult as SharedStorageStateResult, export_storage_state as export_storage_state_operation
from scrapling.operations.discover_endpoints import EndpointDiscoveryResult as SharedEndpointDiscoveryResult, discover_endpoints as discover_endpoints_operation


class ResponseModel(BaseModel):
    """Request's response information structure."""

    status: int = Field(description="The status code returned by the website.")
    content: list[str] = Field(description="The content as Markdown/HTML or the text content of the page.")
    url: str = Field(description="The URL given by the user that resulted in this response.")


class ImageCandidateModel(BaseModel):
    """Page image metadata."""

    index: int = Field(description="The zero-based index of the matched image in the filtered result set.")
    src: str = Field(description="The raw src-like attribute extracted from the DOM.")
    absolute_url: str = Field(description="The resolved absolute URL for the image asset.")
    alt: Optional[str] = Field(default=None, description="The image alt text when present.")
    title: Optional[str] = Field(default=None, description="The image title attribute when present.")
    width: Optional[str] = Field(default=None, description="The image width attribute when present.")
    height: Optional[str] = Field(default=None, description="The image height attribute when present.")


class ImageCandidatesModel(BaseModel):
    """List of image candidates found on a page."""

    page_url: str = Field(description="The page URL that was inspected.")
    strategy: str = Field(description="The fetching strategy used to inspect the page.")
    css_selector: str = Field(description="The CSS selector used to match images.")
    count: int = Field(description="The number of image candidates returned.")
    images: list[ImageCandidateModel] = Field(description="The image candidates found on the page.")


class AppStateEntryModel(BaseModel):
    """Extracted app state blob."""

    kind: str = Field(description="Detected app-state kind, such as next_data or json_ld.")
    key: str = Field(description="Stable key for the extracted state blob.")
    selector: str = Field(description="CSS selector used to locate the state blob.")
    data: Any = Field(description="The parsed JSON payload.")


class AppStateResultModel(BaseModel):
    """Extracted application state payloads from a page."""

    page_url: str = Field(description="The page URL that was inspected.")
    strategy: str = Field(description="The fetching strategy used to inspect the page.")
    count: int = Field(description="The number of parsed state payloads returned.")
    states: list[AppStateEntryModel] = Field(description="The parsed state payloads.")


class NetworkEntryModel(BaseModel):
    """Observed network request/response record."""

    index: int = Field(description="Zero-based observation index.")
    url: str = Field(description="Observed request URL.")
    method: str = Field(description="HTTP method used by the request.")
    resource_type: str = Field(description="Playwright resource type for the request.")
    status: Optional[int] = Field(default=None, description="HTTP response status when available.")
    content_type: Optional[str] = Field(default=None, description="Response content type when available.")
    stage: str = Field(description="Observation stage: requested, responded, or failed.")
    failure_text: Optional[str] = Field(default=None, description="Failure reason when the request failed.")
    request_post_data: Optional[str] = Field(default=None, description="Request body when captured.")
    response_preview: Optional[Any] = Field(default=None, description="Parsed or trimmed response preview when captured.")
    request_headers: Optional[Dict[str, str]] = Field(default=None, description="Request headers when captured.")
    response_headers: Optional[Dict[str, str]] = Field(default=None, description="Response headers when captured.")


class NetworkObservationResultModel(BaseModel):
    """Observed network activity during a browser-backed fetch."""

    page_url: str = Field(description="The page URL that was observed.")
    strategy: str = Field(description="The browser-backed strategy used for observation.")
    count: int = Field(description="The number of observed network entries returned.")
    entries: list[NetworkEntryModel] = Field(description="The observed network entries.")


class FlowActionRecordModel(BaseModel):
    """Executed browser-flow action record."""

    index: int = Field(description="Zero-based action index.")
    type: str = Field(description="Action type that was executed.")
    status: str = Field(description="Execution status for the action.")
    details: Dict[str, Any] = Field(description="Action-specific execution details.")


class FlowExtractResultModel(BaseModel):
    """Result of running a declarative browser flow and extracting page content."""

    page_url: str = Field(description="The initial page URL.")
    final_url: str = Field(description="The final browser URL after the flow completed.")
    strategy: str = Field(description="The browser-backed strategy used for the flow.")
    extraction_type: str = Field(description="The extraction type used for the final content.")
    css_selector: Optional[str] = Field(default=None, description="Optional CSS selector used for final extraction.")
    content: list[str] = Field(description="The extracted final content.")
    actions: list[FlowActionRecordModel] = Field(description="The executed browser-flow actions.")
    network: list[NetworkEntryModel] = Field(default_factory=list, description="Observed network entries captured during the flow.")


class RedirectEntryModel(BaseModel):
    """Observed redirect hop before the final page response."""

    index: int = Field(description="Zero-based redirect index.")
    url: str = Field(description="Redirect request URL.")
    status: Optional[int] = Field(default=None, description="HTTP status observed for the redirect response.")


class PageDebugResultModel(BaseModel):
    """Diagnostic summary for a browser-backed page load."""

    page_url: str = Field(description="The initial page URL.")
    final_url: str = Field(description="The final browser URL after navigation completed.")
    strategy: str = Field(description="The browser-backed strategy used for the page load.")
    status: Optional[int] = Field(default=None, description="HTTP status of the final page response when available.")
    title: Optional[str] = Field(default=None, description="Final document title when available.")
    ready_state: Optional[str] = Field(default=None, description="Final document.readyState value when available.")
    challenge_detected: Optional[str] = Field(default=None, description="Detected Cloudflare challenge type when present.")
    redirect_chain: list[RedirectEntryModel] = Field(default_factory=list, description="Redirect hops observed before the final page response.")
    page_errors: list[str] = Field(default_factory=list, description="Unhandled page errors raised during navigation.")
    failed_requests: list[NetworkEntryModel] = Field(default_factory=list, description="Failed network requests observed during navigation.")
    network_count: int = Field(description="Total observed network entries during navigation.")


class StorageOriginEntryModel(BaseModel):
    """Local storage snapshot for one origin in the browser context."""

    origin: str = Field(description="Origin URL for the stored entries.")
    local_storage: Dict[str, str] = Field(description="Local storage entries recorded for the origin.")


class StorageStateResultModel(BaseModel):
    """Structured browser storage snapshot for a page."""

    page_url: str = Field(description="The initial page URL.")
    final_url: str = Field(description="The final browser URL after navigation completed.")
    strategy: str = Field(description="The browser-backed strategy used for the page load.")
    cookies: list[Dict[str, Any]] = Field(description="Cookies currently visible to the browser context.")
    local_storage: Dict[str, str] = Field(description="Current page localStorage snapshot.")
    session_storage: Dict[str, str] = Field(description="Current page sessionStorage snapshot.")
    origins: list[StorageOriginEntryModel] = Field(description="Context storage_state origins, including localStorage entries.")


class GraphQLOperationModel(BaseModel):
    """GraphQL operation discovered during browser-side endpoint observation."""

    name: str = Field(description="GraphQL operation name.")
    endpoint_url: str = Field(description="Endpoint URL used by the operation.")
    method: str = Field(description="HTTP method used by the operation.")


class DiscoveredEndpointModel(BaseModel):
    """Summarized API-like endpoint discovered from observed browser traffic."""

    url: str = Field(description="Discovered endpoint URL.")
    method: str = Field(description="HTTP method used by the endpoint.")
    kind: str = Field(description="Endpoint kind, such as api, graphql, or websocket.")
    resource_type: str = Field(description="Underlying Playwright resource type.")
    status: Optional[int] = Field(default=None, description="Observed HTTP status when available.")
    content_type: Optional[str] = Field(default=None, description="Observed content type when available.")
    graphql_operation_names: Optional[list[str]] = Field(default=None, description="Discovered GraphQL operation names for this endpoint.")


class EndpointDiscoveryResultModel(BaseModel):
    """Structured endpoint inventory discovered from browser-side traffic."""

    page_url: str = Field(description="The initial page URL.")
    final_url: str = Field(description="The final browser URL after discovery completed.")
    strategy: str = Field(description="The browser-backed strategy used for discovery.")
    count: int = Field(description="The number of unique endpoints returned.")
    endpoints: list[DiscoveredEndpointModel] = Field(description="The discovered endpoints.")
    graphql_operations: list[GraphQLOperationModel] = Field(description="Discovered GraphQL operations.")
    websocket_urls: list[str] = Field(description="Discovered WebSocket URLs.")


def _content_translator(content: Generator[str, None, None], page: _ScraplingResponse) -> ResponseModel:
    """Convert a content generator to a list of ResponseModel objects."""
    return ResponseModel(status=page.status, content=[result for result in content], url=page.url)


def _normalize_credentials(credentials: Optional[Dict[str, str]]) -> Optional[Tuple[str, str]]:
    """Convert a credentials dictionary to a tuple accepted by fetchers."""
    if not credentials:
        return None

    username = credentials.get("username")
    password = credentials.get("password")

    if username is None or password is None:
        raise ValueError("Credentials dictionary must contain both 'username' and 'password' keys")

    return username, password
class ScraplingMCPServer:
    @staticmethod
    def get(
        url: str,
        impersonate: ImpersonateType = "chrome",
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        params: Optional[Dict] = None,
        headers: Optional[Mapping[str, Optional[str]]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: Optional[int | float] = 30,
        follow_redirects: bool = True,
        max_redirects: int = 30,
        retries: Optional[int] = 3,
        retry_delay: Optional[int] = 1,
        proxy: Optional[str] = None,
        proxy_auth: Optional[Dict[str, str]] = None,
        auth: Optional[Dict[str, str]] = None,
        verify: Optional[bool] = True,
        http3: Optional[bool] = False,
        stealthy_headers: Optional[bool] = True,
    ) -> ResponseModel:
        """Make GET HTTP request to a URL and return a structured output of the result.
        Note: This is only suitable for low-mid protection levels. For high-protection levels or websites that require JS loading, use the other tools directly.
        Note: If the `css_selector` resolves to more than one element, all the elements will be returned.

        :param url: The URL to request.
        :param impersonate: Browser version to impersonate its fingerprint. It's using the latest chrome version by default.
        :param extraction_type: The type of content to extract from the page. Defaults to "markdown". Options are:
            - Markdown will convert the page content to Markdown format.
            - HTML will return the raw HTML content of the page.
            - Text will return the text content of the page.
        :param css_selector: CSS selector to extract the content from the page. If main_content_only is True, then it will be executed on the main content of the page. Defaults to None.
        :param main_content_only: Whether to extract only the main content of the page. Defaults to True. The main content here is the data inside the `<body>` tag.
        :param params: Query string parameters for the request.
        :param headers: Headers to include in the request.
        :param cookies: Cookies to use in the request.
        :param timeout: Number of seconds to wait before timing out.
        :param follow_redirects: Whether to follow redirects. Defaults to True.
        :param max_redirects: Maximum number of redirects. Default 30, use -1 for unlimited.
        :param retries: Number of retry attempts. Defaults to 3.
        :param retry_delay: Number of seconds to wait between retry attempts. Defaults to 1 second.
        :param proxy: Proxy URL to use. Format: "http://username:password@localhost:8030".
                     Cannot be used together with the `proxies` parameter.
        :param proxy_auth: HTTP basic auth for proxy in dictionary format with `username` and `password` keys.
        :param auth: HTTP basic auth in dictionary format with `username` and `password` keys.
        :param verify: Whether to verify HTTPS certificates.
        :param http3: Whether to use HTTP3. Defaults to False. It might be problematic if used it with `impersonate`.
        :param stealthy_headers: If enabled (default), it creates and adds real browser headers. It also sets a Google referer header.
        """
        normalized_proxy_auth = _normalize_credentials(proxy_auth)
        normalized_auth = _normalize_credentials(auth)

        page = Fetcher.get(
            url,
            auth=normalized_auth,
            proxy=proxy,
            http3=http3,
            verify=verify,
            params=params,
            proxy_auth=normalized_proxy_auth,
            retry_delay=retry_delay,
            stealthy_headers=stealthy_headers,
            impersonate=impersonate,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            retries=retries,
            max_redirects=max_redirects,
            follow_redirects=follow_redirects,
        )
        return _content_translator(
            Convertor._extract_content(
                page,
                css_selector=css_selector,
                extraction_type=extraction_type,
                main_content_only=main_content_only,
            ),
            page,
        )

    @staticmethod
    async def bulk_get(
        urls: List[str],
        impersonate: ImpersonateType = "chrome",
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        params: Optional[Dict] = None,
        headers: Optional[Mapping[str, Optional[str]]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: Optional[int | float] = 30,
        follow_redirects: bool = True,
        max_redirects: int = 30,
        retries: Optional[int] = 3,
        retry_delay: Optional[int] = 1,
        proxy: Optional[str] = None,
        proxy_auth: Optional[Dict[str, str]] = None,
        auth: Optional[Dict[str, str]] = None,
        verify: Optional[bool] = True,
        http3: Optional[bool] = False,
        stealthy_headers: Optional[bool] = True,
    ) -> List[ResponseModel]:
        """Make GET HTTP request to a group of URLs and for each URL, return a structured output of the result.
        Note: This is only suitable for low-mid protection levels. For high-protection levels or websites that require JS loading, use the other tools directly.
        Note: If the `css_selector` resolves to more than one element, all the elements will be returned.

        :param urls: A list of the URLs to request.
        :param impersonate: Browser version to impersonate its fingerprint. It's using the latest chrome version by default.
        :param extraction_type: The type of content to extract from the page. Defaults to "markdown". Options are:
            - Markdown will convert the page content to Markdown format.
            - HTML will return the raw HTML content of the page.
            - Text will return the text content of the page.
        :param css_selector: CSS selector to extract the content from the page. If main_content_only is True, then it will be executed on the main content of the page. Defaults to None.
        :param main_content_only: Whether to extract only the main content of the page. Defaults to True. The main content here is the data inside the `<body>` tag.
        :param params: Query string parameters for the request.
        :param headers: Headers to include in the request.
        :param cookies: Cookies to use in the request.
        :param timeout: Number of seconds to wait before timing out.
        :param follow_redirects: Whether to follow redirects. Defaults to True.
        :param max_redirects: Maximum number of redirects. Default 30, use -1 for unlimited.
        :param retries: Number of retry attempts. Defaults to 3.
        :param retry_delay: Number of seconds to wait between retry attempts. Defaults to 1 second.
        :param proxy: Proxy URL to use. Format: "http://username:password@localhost:8030".
                     Cannot be used together with the `proxies` parameter.
        :param proxy_auth: HTTP basic auth for proxy in dictionary format with `username` and `password` keys.
        :param auth: HTTP basic auth in dictionary format with `username` and `password` keys.
        :param verify: Whether to verify HTTPS certificates.
        :param http3: Whether to use HTTP3. Defaults to False. It might be problematic if used it with `impersonate`.
        :param stealthy_headers: If enabled (default), it creates and adds real browser headers. It also sets a Google referer header.
        """
        normalized_proxy_auth = _normalize_credentials(proxy_auth)
        normalized_auth = _normalize_credentials(auth)

        async with FetcherSession() as session:
            tasks: List[Any] = [
                session.get(
                    url,
                    auth=normalized_auth,
                    proxy=proxy,
                    http3=http3,
                    verify=verify,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    timeout=timeout,
                    retries=retries,
                    proxy_auth=normalized_proxy_auth,
                    retry_delay=retry_delay,
                    impersonate=impersonate,
                    max_redirects=max_redirects,
                    follow_redirects=follow_redirects,
                    stealthy_headers=stealthy_headers,
                )
                for url in urls
            ]
            responses = await gather(*tasks)
            return [
                _content_translator(
                    Convertor._extract_content(
                        page,
                        css_selector=css_selector,
                        extraction_type=extraction_type,
                        main_content_only=main_content_only,
                    ),
                    page,
                )
                for page in responses
            ]

    @staticmethod
    async def fetch(
        url: str,
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        headless: bool = True,  # noqa: F821
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = False,
        wait_selector_state: SelectorWaitStates = "attached",
    ) -> ResponseModel:
        """Use playwright to open a browser to fetch a URL and return a structured output of the result.
        Note: This is only suitable for low-mid protection levels.
        Note: If the `css_selector` resolves to more than one element, all the elements will be returned.

        :param url: The URL to request.
        :param extraction_type: The type of content to extract from the page. Defaults to "markdown". Options are:
            - Markdown will convert the page content to Markdown format.
            - HTML will return the raw HTML content of the page.
            - Text will return the text content of the page.
        :param css_selector: CSS selector to extract the content from the page. If main_content_only is True, then it will be executed on the main content of the page. Defaults to None.
        :param main_content_only: Whether to extract only the main content of the page. Defaults to True. The main content here is the data inside the `<body>` tag.
        :param headless: Run the browser in headless/hidden (default), or headful/visible mode.
        :param disable_resources: Drop requests for unnecessary resources for a speed boost.
            Requests dropped are of type `font`, `image`, `media`, `beacon`, `object`, `imageset`, `texttrack`, `websocket`, `csp_report`, and `stylesheet`.
        :param useragent: Pass a useragent string to be used. Otherwise the fetcher will generate a real Useragent of the same browser and use it.
        :param cookies: Set cookies for the next request. It should be in a dictionary format that Playwright accepts.
        :param network_idle: Wait for the page until there are no network connections for at least 500 ms.
        :param timeout: The timeout in milliseconds that is used in all operations and waits through the page. The default is 30,000
        :param wait: The time (milliseconds) the fetcher will wait after everything finishes before closing the page and returning the ` Response ` object.
        :param wait_selector: Wait for a specific CSS selector to be in a specific state.
        :param timezone_id: Changes the timezone of the browser. Defaults to the system timezone.
        :param locale: Specify user locale, for example, `en-GB`, `de-DE`, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting
            rules. Defaults to the system default locale.
        :param wait_selector_state: The state to wait for the selector given with `wait_selector`. The default state is `attached`.
        :param real_chrome: If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it.
        :param cdp_url: Instead of launching a new browser instance, connect to this CDP URL to control real browsers through CDP.
        :param google_search: Enabled by default, Scrapling will set a Google referer header.
        :param extra_headers: A dictionary of extra headers to add to the request. _The referer set by `google_search` takes priority over the referer set here if used together._
        :param proxy: The proxy to be used with requests, it can be a string or a dictionary with the keys 'server', 'username', and 'password' only.
        """
        page = await DynamicFetcher.async_fetch(
            url,
            wait=wait,
            proxy=proxy,
            locale=locale,
            timeout=timeout,
            cookies=cookies,
            cdp_url=cdp_url,
            headless=headless,
            useragent=useragent,
            timezone_id=timezone_id,
            real_chrome=real_chrome,
            network_idle=network_idle,
            wait_selector=wait_selector,
            extra_headers=extra_headers,
            google_search=google_search,
            disable_resources=disable_resources,
            wait_selector_state=wait_selector_state,
        )
        return _content_translator(
            Convertor._extract_content(
                page,
                css_selector=css_selector,
                extraction_type=extraction_type,
                main_content_only=main_content_only,
            ),
            page,
        )

    @staticmethod
    async def bulk_fetch(
        urls: List[str],
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        headless: bool = True,  # noqa: F821
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = False,
        wait_selector_state: SelectorWaitStates = "attached",
    ) -> List[ResponseModel]:
        """Use playwright to open a browser, then fetch a group of URLs at the same time, and for each page return a structured output of the result.
        Note: This is only suitable for low-mid protection levels.
        Note: If the `css_selector` resolves to more than one element, all the elements will be returned.

        :param urls: A list of the URLs to request.
        :param extraction_type: The type of content to extract from the page. Defaults to "markdown". Options are:
            - Markdown will convert the page content to Markdown format.
            - HTML will return the raw HTML content of the page.
            - Text will return the text content of the page.
        :param css_selector: CSS selector to extract the content from the page. If main_content_only is True, then it will be executed on the main content of the page. Defaults to None.
        :param main_content_only: Whether to extract only the main content of the page. Defaults to True. The main content here is the data inside the `<body>` tag.
        :param headless: Run the browser in headless/hidden (default), or headful/visible mode.
        :param disable_resources: Drop requests for unnecessary resources for a speed boost.
            Requests dropped are of type `font`, `image`, `media`, `beacon`, `object`, `imageset`, `texttrack`, `websocket`, `csp_report`, and `stylesheet`.
        :param useragent: Pass a useragent string to be used. Otherwise the fetcher will generate a real Useragent of the same browser and use it.
        :param cookies: Set cookies for the next request. It should be in a dictionary format that Playwright accepts.
        :param network_idle: Wait for the page until there are no network connections for at least 500 ms.
        :param timeout: The timeout in milliseconds that is used in all operations and waits through the page. The default is 30,000
        :param wait: The time (milliseconds) the fetcher will wait after everything finishes before closing the page and returning the ` Response ` object.
        :param wait_selector: Wait for a specific CSS selector to be in a specific state.
        :param timezone_id: Changes the timezone of the browser. Defaults to the system timezone.
        :param locale: Specify user locale, for example, `en-GB`, `de-DE`, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting
            rules. Defaults to the system default locale.
        :param wait_selector_state: The state to wait for the selector given with `wait_selector`. The default state is `attached`.
        :param real_chrome: If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it.
        :param cdp_url: Instead of launching a new browser instance, connect to this CDP URL to control real browsers through CDP.
        :param google_search: Enabled by default, Scrapling will set a Google referer header.
        :param extra_headers: A dictionary of extra headers to add to the request. _The referer set by `google_search` takes priority over the referer set here if used together._
        :param proxy: The proxy to be used with requests, it can be a string or a dictionary with the keys 'server', 'username', and 'password' only.
        """
        async with AsyncDynamicSession(
            wait=wait,
            proxy=proxy,
            locale=locale,
            timeout=timeout,
            cookies=cookies,
            cdp_url=cdp_url,
            headless=headless,
            max_pages=len(urls),
            useragent=useragent,
            timezone_id=timezone_id,
            real_chrome=real_chrome,
            network_idle=network_idle,
            wait_selector=wait_selector,
            google_search=google_search,
            extra_headers=extra_headers,
            disable_resources=disable_resources,
            wait_selector_state=wait_selector_state,
        ) as session:
            tasks = [session.fetch(url) for url in urls]
            responses = await gather(*tasks)
            return [
                _content_translator(
                    Convertor._extract_content(
                        page,
                        css_selector=css_selector,
                        extraction_type=extraction_type,
                        main_content_only=main_content_only,
                    ),
                    page,
                )
                for page in responses
            ]

    @staticmethod
    async def stealthy_fetch(
        url: str,
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        headless: bool = True,  # noqa: F821
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        hide_canvas: bool = False,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = False,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
    ) -> ResponseModel:
        """Use the stealthy fetcher to fetch a URL and return a structured output of the result.
        Note: This is the only suitable fetcher for high protection levels.
        Note: If the `css_selector` resolves to more than one element, all the elements will be returned.

        :param url: The URL to request.
        :param extraction_type: The type of content to extract from the page. Defaults to "markdown". Options are:
            - Markdown will convert the page content to Markdown format.
            - HTML will return the raw HTML content of the page.
            - Text will return the text content of the page.
        :param css_selector: CSS selector to extract the content from the page. If main_content_only is True, then it will be executed on the main content of the page. Defaults to None.
        :param main_content_only: Whether to extract only the main content of the page. Defaults to True. The main content here is the data inside the `<body>` tag.
        :param headless: Run the browser in headless/hidden (default), or headful/visible mode.
        :param disable_resources: Drop requests for unnecessary resources for a speed boost.
            Requests dropped are of type `font`, `image`, `media`, `beacon`, `object`, `imageset`, `texttrack`, `websocket`, `csp_report`, and `stylesheet`.
        :param useragent: Pass a useragent string to be used. Otherwise the fetcher will generate a real Useragent of the same browser and use it.
        :param cookies: Set cookies for the next request.
        :param solve_cloudflare: Solves all types of the Cloudflare's Turnstile/Interstitial challenges before returning the response to you.
        :param allow_webgl: Enabled by default. Disabling WebGL is not recommended as many WAFs now check if WebGL is enabled.
        :param network_idle: Wait for the page until there are no network connections for at least 500 ms.
        :param wait: The time (milliseconds) the fetcher will wait after everything finishes before closing the page and returning the ` Response ` object.
        :param timeout: The timeout in milliseconds that is used in all operations and waits through the page. The default is 30,000
        :param wait_selector: Wait for a specific CSS selector to be in a specific state.
        :param timezone_id: Changes the timezone of the browser. Defaults to the system timezone.
        :param locale: Specify user locale, for example, `en-GB`, `de-DE`, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting
            rules. Defaults to the system default locale.
        :param wait_selector_state: The state to wait for the selector given with `wait_selector`. The default state is `attached`.
        :param real_chrome: If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it.
        :param hide_canvas: Add random noise to canvas operations to prevent fingerprinting.
        :param block_webrtc: Forces WebRTC to respect proxy settings to prevent local IP address leak.
        :param cdp_url: Instead of launching a new browser instance, connect to this CDP URL to control real browsers through CDP.
        :param google_search: Enabled by default, Scrapling will set a Google referer header.
        :param extra_headers: A dictionary of extra headers to add to the request. _The referer set by `google_search` takes priority over the referer set here if used together._
        :param proxy: The proxy to be used with requests, it can be a string or a dictionary with the keys 'server', 'username', and 'password' only.
        :param additional_args: Additional arguments to be passed to Playwright's context as additional settings, and it takes higher priority than Scrapling's settings.
        """
        page = await StealthyFetcher.async_fetch(
            url,
            wait=wait,
            proxy=proxy,
            locale=locale,
            cdp_url=cdp_url,
            timeout=timeout,
            cookies=cookies,
            headless=headless,
            useragent=useragent,
            timezone_id=timezone_id,
            real_chrome=real_chrome,
            hide_canvas=hide_canvas,
            allow_webgl=allow_webgl,
            network_idle=network_idle,
            block_webrtc=block_webrtc,
            wait_selector=wait_selector,
            google_search=google_search,
            extra_headers=extra_headers,
            additional_args=additional_args,
            solve_cloudflare=solve_cloudflare,
            disable_resources=disable_resources,
            wait_selector_state=wait_selector_state,
        )
        return _content_translator(
            Convertor._extract_content(
                page,
                css_selector=css_selector,
                extraction_type=extraction_type,
                main_content_only=main_content_only,
            ),
            page,
        )

    @staticmethod
    async def bulk_stealthy_fetch(
        urls: List[str],
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        headless: bool = True,  # noqa: F821
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        hide_canvas: bool = False,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = False,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
    ) -> List[ResponseModel]:
        """Use the stealthy fetcher to fetch a group of URLs at the same time, and for each page return a structured output of the result.
        Note: This is the only suitable fetcher for high protection levels.
        Note: If the `css_selector` resolves to more than one element, all the elements will be returned.

        :param urls: A list of the URLs to request.
        :param extraction_type: The type of content to extract from the page. Defaults to "markdown". Options are:
            - Markdown will convert the page content to Markdown format.
            - HTML will return the raw HTML content of the page.
            - Text will return the text content of the page.
        :param css_selector: CSS selector to extract the content from the page. If main_content_only is True, then it will be executed on the main content of the page. Defaults to None.
        :param main_content_only: Whether to extract only the main content of the page. Defaults to True. The main content here is the data inside the `<body>` tag.
        :param headless: Run the browser in headless/hidden (default), or headful/visible mode.
        :param disable_resources: Drop requests for unnecessary resources for a speed boost.
            Requests dropped are of type `font`, `image`, `media`, `beacon`, `object`, `imageset`, `texttrack`, `websocket`, `csp_report`, and `stylesheet`.
        :param useragent: Pass a useragent string to be used. Otherwise the fetcher will generate a real Useragent of the same browser and use it.
        :param cookies: Set cookies for the next request.
        :param solve_cloudflare: Solves all types of the Cloudflare's Turnstile/Interstitial challenges before returning the response to you.
        :param allow_webgl: Enabled by default. Disabling WebGL is not recommended as many WAFs now check if WebGL is enabled.
        :param network_idle: Wait for the page until there are no network connections for at least 500 ms.
        :param wait: The time (milliseconds) the fetcher will wait after everything finishes before closing the page and returning the ` Response ` object.
        :param timeout: The timeout in milliseconds that is used in all operations and waits through the page. The default is 30,000
        :param wait_selector: Wait for a specific CSS selector to be in a specific state.
        :param timezone_id: Changes the timezone of the browser. Defaults to the system timezone.
        :param locale: Specify user locale, for example, `en-GB`, `de-DE`, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting
            rules. Defaults to the system default locale.
        :param wait_selector_state: The state to wait for the selector given with `wait_selector`. The default state is `attached`.
        :param real_chrome: If you have a Chrome browser installed on your device, enable this, and the Fetcher will launch an instance of your browser and use it.
        :param hide_canvas: Add random noise to canvas operations to prevent fingerprinting.
        :param block_webrtc: Forces WebRTC to respect proxy settings to prevent local IP address leak.
        :param cdp_url: Instead of launching a new browser instance, connect to this CDP URL to control real browsers through CDP.
        :param google_search: Enabled by default, Scrapling will set a Google referer header.
        :param extra_headers: A dictionary of extra headers to add to the request. _The referer set by `google_search` takes priority over the referer set here if used together._
        :param proxy: The proxy to be used with requests, it can be a string or a dictionary with the keys 'server', 'username', and 'password' only.
        :param additional_args: Additional arguments to be passed to Playwright's context as additional settings, and it takes higher priority than Scrapling's settings.
        """
        async with AsyncStealthySession(
            wait=wait,
            proxy=proxy,
            locale=locale,
            cdp_url=cdp_url,
            timeout=timeout,
            cookies=cookies,
            headless=headless,
            useragent=useragent,
            timezone_id=timezone_id,
            real_chrome=real_chrome,
            hide_canvas=hide_canvas,
            allow_webgl=allow_webgl,
            network_idle=network_idle,
            block_webrtc=block_webrtc,
            wait_selector=wait_selector,
            google_search=google_search,
            extra_headers=extra_headers,
            additional_args=additional_args,
            solve_cloudflare=solve_cloudflare,
            disable_resources=disable_resources,
            wait_selector_state=wait_selector_state,
        ) as session:
            tasks = [session.fetch(url) for url in urls]
            responses = await gather(*tasks)
            return [
                _content_translator(
                    Convertor._extract_content(
                        page,
                        css_selector=css_selector,
                        extraction_type=extraction_type,
                        main_content_only=main_content_only,
                    ),
                    page,
                )
                for page in responses
            ]

    @staticmethod
    async def list_page_images(
        page_url: str,
        strategy: str = "fetch",
        css_selector: str = "img",
        src_contains: Optional[str] = None,
        max_results: int = 20,
    ) -> ImageCandidatesModel:
        """Load a page with Scrapling and list the image candidates that can be returned by MCP.

        :param page_url: The page URL to inspect for image elements.
        :param strategy: The fetching strategy to use. Options are:
            - get: low-mid protection HTTP request
            - fetch: browser-backed fetching
            - stealthy_fetch: browser-backed fetching for high protection levels
        :param css_selector: CSS selector used to match candidate images. Defaults to "img".
        :param src_contains: Optional string that must be present in either the raw src or resolved image URL.
        :param max_results: Maximum number of image candidates to return. Defaults to 20.
        """
        result: SharedImageCandidatesResult = await list_page_images_operation(
            page_url=page_url,
            strategy=strategy,
            css_selector=css_selector,
            src_contains=src_contains,
            max_results=max_results,
        )
        return ImageCandidatesModel(
            page_url=result.page_url,
            strategy=result.strategy,
            css_selector=result.css_selector,
            count=result.count,
            images=[ImageCandidateModel(**candidate.to_dict()) for candidate in result.images],
        )

    @staticmethod
    async def fetch_page_image(
        page_url: str,
        strategy: str = "fetch",
        css_selector: str = "img",
        image_index: int = 0,
        src_contains: Optional[str] = None,
        max_results: int = 20,
    ) -> CallToolResult:
        """Load a page with Scrapling, download one matched image, and return it as MCP image content.

        :param page_url: The page URL to inspect for image elements.
        :param strategy: The fetching strategy to use. Options are:
            - get: low-mid protection HTTP request
            - fetch: browser-backed fetching
            - stealthy_fetch: browser-backed fetching for high protection levels
        :param css_selector: CSS selector used to match candidate images. Defaults to "img".
        :param image_index: Zero-based index of the image candidate to fetch after filtering. Defaults to 0.
        :param src_contains: Optional string that must be present in either the raw src or resolved image URL.
        :param max_results: Maximum number of image candidates to consider. Defaults to 20.
        """
        try:
            result = await fetch_page_image_operation(
                page_url=page_url,
                strategy=strategy,
                css_selector=css_selector,
                image_index=image_index,
                src_contains=src_contains,
                max_results=max_results,
            )
        except (TypeError, ValueError) as exc:
            return CallToolResult(
                isError=True,
                content=[
                    TextContent(
                        type="text",
                        text=str(exc),
                    )
                ],
            )

        encoded = base64.b64encode(result.data).decode("ascii")
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=(
                        f"Fetched image {image_index} from {page_url}\n"
                        f"Resolved URL: {result.image_url}\n"
                        f"MIME type: {result.mime_type}\n"
                        f"Size: {result.bytes_count} bytes"
                    ),
                ),
                ImageContent(type="image", data=encoded, mimeType=result.mime_type),
            ],
            structuredContent=result.metadata_dict(),
        )

    @staticmethod
    async def extract_app_state(
        page_url: str,
        strategy: str = "fetch",
        kinds: Optional[List[str]] = None,
    ) -> AppStateResultModel:
        """Fetch a page server-side and extract app-state payloads as parsed JSON.

        :param page_url: The page URL to inspect.
        :param strategy: The fetching strategy to use. Options are:
            - get: low-mid protection HTTP request
            - fetch: browser-backed fetching
            - stealthy_fetch: browser-backed fetching for high protection levels
        :param kinds: Optional list of state kinds to extract. Supported values are:
            - next_data
            - nuxt_data
            - json_ld
            - application_json
        """
        result: SharedAppStateResult = await extract_app_state_operation(
            page_url=page_url,
            strategy=strategy,
            kinds=kinds,
        )
        return AppStateResultModel(
            page_url=result.page_url,
            strategy=result.strategy,
            count=result.count,
            states=[AppStateEntryModel(**state.to_dict()) for state in result.states],
        )

    @staticmethod
    async def observe_network(
        page_url: str,
        strategy: str = "fetch",
        headless: bool = True,
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = True,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
        hide_canvas: bool = False,
        include_headers: bool = False,
        include_bodies: bool = False,
        max_entries: int = 100,
        max_body_chars: int = 2000,
        url_contains: Optional[str] = None,
    ) -> NetworkObservationResultModel:
        """Observe browser-side network activity for a page and return structured request/response records.

        :param page_url: The page URL to observe.
        :param strategy: Browser-backed strategy to use. Options are:
            - fetch
            - stealthy_fetch
        :param include_headers: Include captured request and response headers in the result.
        :param include_bodies: Include parsed or trimmed textual response previews when possible.
        :param max_entries: Maximum number of observed requests to return.
        :param max_body_chars: Maximum preview length for textual response bodies.
        :param url_contains: Optional substring filter applied to observed request URLs.
        """
        result: SharedNetworkObservationResult = await observe_network_operation(
            page_url=page_url,
            strategy=strategy,
            headless=headless,
            google_search=google_search,
            real_chrome=real_chrome,
            wait=wait,
            proxy=proxy,
            timezone_id=timezone_id,
            locale=locale,
            extra_headers=extra_headers,
            useragent=useragent,
            cdp_url=cdp_url,
            timeout=timeout,
            disable_resources=disable_resources,
            wait_selector=wait_selector,
            cookies=cookies,
            network_idle=network_idle,
            wait_selector_state=wait_selector_state,
            block_webrtc=block_webrtc,
            allow_webgl=allow_webgl,
            solve_cloudflare=solve_cloudflare,
            additional_args=additional_args,
            hide_canvas=hide_canvas,
            include_headers=include_headers,
            include_bodies=include_bodies,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )
        return NetworkObservationResultModel(
            page_url=result.page_url,
            strategy=result.strategy,
            count=result.count,
            entries=[NetworkEntryModel(**entry.to_dict()) for entry in result.entries],
        )

    @staticmethod
    async def run_flow_and_extract(
        page_url: str,
        actions: List[Dict[str, Any]],
        strategy: str = "fetch",
        extraction_type: extraction_types = "markdown",
        css_selector: Optional[str] = None,
        main_content_only: bool = True,
        headless: bool = True,
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = True,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
        hide_canvas: bool = False,
        observe_network: bool = False,
        include_headers: bool = False,
        include_bodies: bool = False,
        max_entries: int = 100,
        max_body_chars: int = 2000,
        url_contains: Optional[str] = None,
    ) -> FlowExtractResultModel:
        """Run a declarative browser flow and then extract the final page content.

        :param page_url: The initial page URL.
        :param actions: A list of browser actions. Supported action types are:
            - click
            - wait
            - wait_for_selector
            - fill
            - press
            - scroll
            - evaluate
        :param strategy: Browser-backed strategy to use. Options are:
            - fetch
            - stealthy_fetch
        :param observe_network: Capture request/response activity triggered during the flow in the same browser session.
        :param include_headers: Include captured request and response headers when network observation is enabled.
        :param include_bodies: Include parsed or trimmed textual response previews when network observation is enabled.
        :param max_entries: Maximum number of observed requests to return when network observation is enabled.
        :param max_body_chars: Maximum preview length for textual response bodies when network observation is enabled.
        :param url_contains: Optional substring filter applied to observed request URLs when network observation is enabled.
        """
        result: SharedFlowExtractResult = await run_flow_and_extract_operation(
            page_url=page_url,
            actions=actions,
            strategy=strategy,
            extraction_type=extraction_type,
            css_selector=css_selector,
            main_content_only=main_content_only,
            headless=headless,
            google_search=google_search,
            real_chrome=real_chrome,
            wait=wait,
            proxy=proxy,
            timezone_id=timezone_id,
            locale=locale,
            extra_headers=extra_headers,
            useragent=useragent,
            cdp_url=cdp_url,
            timeout=timeout,
            disable_resources=disable_resources,
            wait_selector=wait_selector,
            cookies=cookies,
            network_idle=network_idle,
            wait_selector_state=wait_selector_state,
            block_webrtc=block_webrtc,
            allow_webgl=allow_webgl,
            solve_cloudflare=solve_cloudflare,
            additional_args=additional_args,
            hide_canvas=hide_canvas,
            observe_network=observe_network,
            include_headers=include_headers,
            include_bodies=include_bodies,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )
        return FlowExtractResultModel(
            page_url=result.page_url,
            final_url=result.final_url,
            strategy=result.strategy,
            extraction_type=result.extraction_type,
            css_selector=result.css_selector,
            content=result.content,
            actions=[FlowActionRecordModel(**action.to_dict()) for action in result.actions],
            network=[NetworkEntryModel(**entry.to_dict()) for entry in result.network],
        )

    @staticmethod
    async def debug_page(
        page_url: str,
        strategy: str = "fetch",
        headless: bool = True,
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = True,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
        hide_canvas: bool = False,
        max_entries: int = 100,
    ) -> PageDebugResultModel:
        """Load a page in the browser and return a compact diagnostic summary for debugging failures.

        :param page_url: The page URL to inspect.
        :param strategy: Browser-backed strategy to use. Options are:
            - fetch
            - stealthy_fetch
        :param max_entries: Maximum number of observed network requests to track while collecting diagnostics.
        """
        result: SharedPageDebugResult = await debug_page_operation(
            page_url=page_url,
            strategy=strategy,
            headless=headless,
            google_search=google_search,
            real_chrome=real_chrome,
            wait=wait,
            proxy=proxy,
            timezone_id=timezone_id,
            locale=locale,
            extra_headers=extra_headers,
            useragent=useragent,
            cdp_url=cdp_url,
            timeout=timeout,
            disable_resources=disable_resources,
            wait_selector=wait_selector,
            cookies=cookies,
            network_idle=network_idle,
            wait_selector_state=wait_selector_state,
            block_webrtc=block_webrtc,
            allow_webgl=allow_webgl,
            solve_cloudflare=solve_cloudflare,
            additional_args=additional_args,
            hide_canvas=hide_canvas,
            max_entries=max_entries,
        )
        return PageDebugResultModel(
            page_url=result.page_url,
            final_url=result.final_url,
            strategy=result.strategy,
            status=result.status,
            title=result.title,
            ready_state=result.ready_state,
            challenge_detected=result.challenge_detected,
            redirect_chain=[RedirectEntryModel(**entry.to_dict()) for entry in result.redirect_chain],
            page_errors=result.page_errors,
            failed_requests=[NetworkEntryModel(**entry.to_dict()) for entry in result.failed_requests],
            network_count=result.network_count,
        )

    @staticmethod
    async def export_storage_state(
        page_url: str,
        strategy: str = "fetch",
        headless: bool = True,
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = True,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
        hide_canvas: bool = False,
    ) -> StorageStateResultModel:
        """Load a page in the browser and return cookies plus web-storage state for persistence.

        :param page_url: The page URL to inspect.
        :param strategy: Browser-backed strategy to use. Options are:
            - fetch
            - stealthy_fetch
        """
        result: SharedStorageStateResult = await export_storage_state_operation(
            page_url=page_url,
            strategy=strategy,
            headless=headless,
            google_search=google_search,
            real_chrome=real_chrome,
            wait=wait,
            proxy=proxy,
            timezone_id=timezone_id,
            locale=locale,
            extra_headers=extra_headers,
            useragent=useragent,
            cdp_url=cdp_url,
            timeout=timeout,
            disable_resources=disable_resources,
            wait_selector=wait_selector,
            cookies=cookies,
            network_idle=network_idle,
            wait_selector_state=wait_selector_state,
            block_webrtc=block_webrtc,
            allow_webgl=allow_webgl,
            solve_cloudflare=solve_cloudflare,
            additional_args=additional_args,
            hide_canvas=hide_canvas,
        )
        return StorageStateResultModel(
            page_url=result.page_url,
            final_url=result.final_url,
            strategy=result.strategy,
            cookies=result.cookies,
            local_storage=result.local_storage,
            session_storage=result.session_storage,
            origins=[StorageOriginEntryModel(**origin.to_dict()) for origin in result.origins],
        )

    @staticmethod
    async def discover_endpoints(
        page_url: str,
        actions: Optional[List[Dict[str, Any]]] = None,
        strategy: str = "fetch",
        headless: bool = True,
        google_search: bool = True,
        real_chrome: bool = False,
        wait: int | float = 0,
        proxy: Optional[str | Dict[str, str]] = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        extra_headers: Optional[Dict[str, str]] = None,
        useragent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        timeout: int | float = 30000,
        disable_resources: bool = False,
        wait_selector: Optional[str] = None,
        cookies: Sequence[SetCookieParam] | None = None,
        network_idle: bool = True,
        wait_selector_state: SelectorWaitStates = "attached",
        block_webrtc: bool = False,
        allow_webgl: bool = True,
        solve_cloudflare: bool = False,
        additional_args: Optional[Dict] = None,
        hide_canvas: bool = False,
        max_entries: int = 100,
        max_body_chars: int = 4000,
        url_contains: Optional[str] = None,
    ) -> EndpointDiscoveryResultModel:
        """Discover likely API, GraphQL, and WebSocket endpoints from browser-side traffic.

        :param page_url: The initial page URL.
        :param actions: Optional browser actions to execute before summarizing observed endpoints.
        :param strategy: Browser-backed strategy to use. Options are:
            - fetch
            - stealthy_fetch
        :param max_entries: Maximum number of observed requests to inspect.
        :param max_body_chars: Maximum request body length retained for GraphQL inspection.
        :param url_contains: Optional substring filter applied to observed request URLs.
        """
        result: SharedEndpointDiscoveryResult = await discover_endpoints_operation(
            page_url=page_url,
            actions=actions,
            strategy=strategy,
            headless=headless,
            google_search=google_search,
            real_chrome=real_chrome,
            wait=wait,
            proxy=proxy,
            timezone_id=timezone_id,
            locale=locale,
            extra_headers=extra_headers,
            useragent=useragent,
            cdp_url=cdp_url,
            timeout=timeout,
            disable_resources=disable_resources,
            wait_selector=wait_selector,
            cookies=cookies,
            network_idle=network_idle,
            wait_selector_state=wait_selector_state,
            block_webrtc=block_webrtc,
            allow_webgl=allow_webgl,
            solve_cloudflare=solve_cloudflare,
            additional_args=additional_args,
            hide_canvas=hide_canvas,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )
        return EndpointDiscoveryResultModel(
            page_url=result.page_url,
            final_url=result.final_url,
            strategy=result.strategy,
            count=result.count,
            endpoints=[DiscoveredEndpointModel(**endpoint.to_dict()) for endpoint in result.endpoints],
            graphql_operations=[GraphQLOperationModel(**operation.to_dict()) for operation in result.graphql_operations],
            websocket_urls=result.websocket_urls,
        )

    def serve(self, http: bool, host: str, port: int):
        """Serve the MCP server."""
        server = FastMCP(name="Scrapling", host=host, port=port)
        server.add_tool(self.get, title="get", description=self.get.__doc__, structured_output=True)
        server.add_tool(self.bulk_get, title="bulk_get", description=self.bulk_get.__doc__, structured_output=True)
        server.add_tool(self.fetch, title="fetch", description=self.fetch.__doc__, structured_output=True)
        server.add_tool(
            self.bulk_fetch, title="bulk_fetch", description=self.bulk_fetch.__doc__, structured_output=True
        )
        server.add_tool(
            self.stealthy_fetch, title="stealthy_fetch", description=self.stealthy_fetch.__doc__, structured_output=True
        )
        server.add_tool(
            self.bulk_stealthy_fetch,
            title="bulk_stealthy_fetch",
            description=self.bulk_stealthy_fetch.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.list_page_images,
            title="list_page_images",
            description=self.list_page_images.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.fetch_page_image,
            title="fetch_page_image",
            description=self.fetch_page_image.__doc__,
        )
        server.add_tool(
            self.extract_app_state,
            title="extract_app_state",
            description=self.extract_app_state.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.observe_network,
            title="observe_network",
            description=self.observe_network.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.run_flow_and_extract,
            title="run_flow_and_extract",
            description=self.run_flow_and_extract.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.debug_page,
            title="debug_page",
            description=self.debug_page.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.export_storage_state,
            title="export_storage_state",
            description=self.export_storage_state.__doc__,
            structured_output=True,
        )
        server.add_tool(
            self.discover_endpoints,
            title="discover_endpoints",
            description=self.discover_endpoints.__doc__,
            structured_output=True,
        )
        server.run(transport="stdio" if not http else "streamable-http")
