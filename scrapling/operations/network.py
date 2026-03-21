from dataclasses import asdict, dataclass, field

from orjson import loads as json_loads, JSONDecodeError

from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession
from scrapling.core._types import Optional, Literal, Any, Dict, Sequence, SetCookieParam

ObserveStrategy = Literal["fetch", "stealthy_fetch"]


@dataclass(slots=True)
class NetworkEntry:
    index: int
    url: str
    method: str
    resource_type: str
    status: Optional[int] = None
    content_type: Optional[str] = None
    stage: str = "requested"
    failure_text: Optional[str] = None
    request_post_data: Optional[str] = None
    response_preview: Optional[Any] = None
    request_headers: Optional[Dict[str, str]] = None
    response_headers: Optional[Dict[str, str]] = None

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class NetworkObservationResult:
    page_url: str
    strategy: str
    count: int
    entries: list[NetworkEntry]

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "strategy": self.strategy,
            "count": self.count,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_text(self) -> str:
        lines = [
            f"Page URL: {self.page_url}",
            f"Strategy: {self.strategy}",
            f"Requests observed: {self.count}",
        ]
        for entry in self.entries:
            status = entry.status if entry.status is not None else "-"
            lines.append(f"- [{entry.index}] {entry.method} {entry.url} -> {status} ({entry.resource_type})")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            "# Network Observation",
            "",
            f"- Page URL: `{self.page_url}`",
            f"- Strategy: `{self.strategy}`",
            f"- Requests observed: `{self.count}`",
            "",
            "| # | Method | Status | Type | URL |",
            "|---|---|---:|---|---|",
        ]
        for entry in self.entries:
            status = entry.status if entry.status is not None else "-"
            lines.append(
                f"| {entry.index} | {entry.method} | {status} | {entry.resource_type} | `{entry.url}` |"
            )
        return "\n".join(lines)


@dataclass
class NetworkCapture:
    include_headers: bool = False
    include_bodies: bool = False
    max_entries: int = 100
    max_body_chars: int = 2000
    url_contains: Optional[str] = None
    entries_by_request: dict[int, NetworkEntry] = field(default_factory=dict)
    ordered_entries: list[NetworkEntry] = field(default_factory=list)

    @property
    def entries(self) -> list[NetworkEntry]:
        return self.ordered_entries

    def should_capture(self, url: str) -> bool:
        return not self.url_contains or self.url_contains in url

    async def on_request(self, request):
        if len(self.ordered_entries) >= self.max_entries or not self.should_capture(request.url):
            return

        entry = NetworkEntry(
            index=len(self.ordered_entries),
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
            request_post_data=request.post_data if self.include_bodies else None,
            request_headers=await request.all_headers() if self.include_headers else None,
        )
        self.entries_by_request[id(request)] = entry
        self.ordered_entries.append(entry)

    async def on_response(self, response):
        if not self.should_capture(response.url):
            return

        request = response.request
        entry = self.entries_by_request.get(id(request))
        if entry is None:
            if len(self.ordered_entries) >= self.max_entries:
                return
            entry = NetworkEntry(
                index=len(self.ordered_entries),
                url=request.url,
                method=request.method,
                resource_type=request.resource_type,
            )
            self.entries_by_request[id(request)] = entry
            self.ordered_entries.append(entry)

        entry.stage = "responded"
        entry.status = response.status
        headers = await response.all_headers()
        entry.content_type = headers.get("content-type")
        if self.include_headers:
            entry.response_headers = headers
        if self.include_bodies and entry.content_type and _is_previewable_content_type(entry.content_type):
            try:
                text = await response.text()
                entry.response_preview = _preview_response_body(text, entry.content_type, self.max_body_chars)
            except Exception:
                entry.response_preview = None

    async def on_request_failed(self, request):
        if not self.should_capture(request.url):
            return
        entry = self.entries_by_request.get(id(request))
        if entry is None:
            if len(self.ordered_entries) >= self.max_entries:
                return
            entry = NetworkEntry(
                index=len(self.ordered_entries),
                url=request.url,
                method=request.method,
                resource_type=request.resource_type,
            )
            self.entries_by_request[id(request)] = entry
            self.ordered_entries.append(entry)
        entry.stage = "failed"
        entry.failure_text = request.failure

    def bind(self, page) -> None:
        page.on("request", self.on_request)
        page.on("response", self.on_response)
        page.on("requestfailed", self.on_request_failed)


def _preview_response_body(text: str, content_type: str, max_body_chars: int) -> Optional[Any]:
    if not text:
        return None
    trimmed = text[:max_body_chars]
    if "json" in content_type:
        try:
            return json_loads(trimmed)
        except JSONDecodeError:
            return trimmed
    return trimmed


def _is_previewable_content_type(content_type: str) -> bool:
    return any(
        token in content_type
        for token in ("json", "text/", "javascript", "xml", "graphql")
    )


def _get_session_class(strategy: ObserveStrategy):
    if strategy == "fetch":
        return AsyncDynamicSession
    if strategy == "stealthy_fetch":
        return AsyncStealthySession
    raise ValueError("Unsupported strategy. Use one of: fetch, stealthy_fetch")


async def observe_network(
    page_url: str,
    strategy: ObserveStrategy = "fetch",
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
    wait_selector_state: str = "attached",
    block_webrtc: bool = False,
    allow_webgl: bool = True,
    solve_cloudflare: bool = False,
    hide_canvas: bool = False,
    additional_args: Optional[Dict] = None,
    blocked_domains: Optional[set[str]] = None,
    include_headers: bool = False,
    include_bodies: bool = False,
    max_entries: int = 100,
    max_body_chars: int = 2000,
    url_contains: Optional[str] = None,
) -> NetworkObservationResult:
    session_cls = _get_session_class(strategy)
    session_kwargs: Dict[str, Any] = {
        "headless": headless,
        "google_search": google_search,
        "real_chrome": real_chrome,
        "wait": wait,
        "proxy": proxy,
        "timezone_id": timezone_id,
        "locale": locale,
        "extra_headers": extra_headers,
        "useragent": useragent,
        "cdp_url": cdp_url,
        "timeout": timeout,
        "disable_resources": disable_resources,
        "wait_selector": wait_selector,
        "cookies": cookies,
        "network_idle": network_idle,
        "wait_selector_state": wait_selector_state,
        "blocked_domains": blocked_domains,
    }
    if strategy == "stealthy_fetch":
        session_kwargs.update(
            {
                "block_webrtc": block_webrtc,
                "allow_webgl": allow_webgl,
                "solve_cloudflare": solve_cloudflare,
                "hide_canvas": hide_canvas,
                "additional_args": additional_args,
            }
        )
    elif additional_args:
        session_kwargs["additional_args"] = additional_args

    async with session_cls(**session_kwargs) as session:
        request_headers_keys = {h.lower() for h in extra_headers.keys()} if extra_headers else set()
        referer = "https://www.google.com/" if (google_search and "referer" not in request_headers_keys) else None
        capture = NetworkCapture(
            include_headers=include_headers,
            include_bodies=include_bodies,
            max_entries=max_entries,
            max_body_chars=max_body_chars,
            url_contains=url_contains,
        )

        async with session._page_generator(  # type: ignore[attr-defined]
            timeout,
            extra_headers,
            disable_resources,
            proxy,
            blocked_domains,
        ) as page_info:
            page = page_info.page
            capture.bind(page)

            first_response = await page.goto(page_url, referer=referer)
            await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]
            if not first_response:
                raise RuntimeError(f"Failed to get response for {page_url}")

            if strategy == "stealthy_fetch" and solve_cloudflare:
                await session._cloudflare_solver(page)  # type: ignore[attr-defined]
                await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]

            if wait_selector:
                waiter = page.locator(wait_selector)
                await waiter.first.wait_for(state=wait_selector_state)
                await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]

            await page.wait_for_timeout(wait)

    return NetworkObservationResult(
        page_url=page_url,
        strategy=strategy,
        count=len(capture.entries),
        entries=capture.entries,
    )
