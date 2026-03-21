from dataclasses import asdict, dataclass
from json import dumps as json_dumps

from orjson import loads as json_loads, JSONDecodeError

from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession
from scrapling.core._types import Optional, Literal, Any, Dict, Sequence, SetCookieParam
from scrapling.operations.network import NetworkCapture, NetworkEntry
from scrapling.operations.browser_flow import _run_action

DiscoverStrategy = Literal["fetch", "stealthy_fetch"]


@dataclass(slots=True)
class GraphQLOperation:
    name: str
    endpoint_url: str
    method: str

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class DiscoveredEndpoint:
    url: str
    method: str
    kind: str
    resource_type: str
    status: Optional[int] = None
    content_type: Optional[str] = None
    graphql_operation_names: list[str] | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class EndpointDiscoveryResult:
    page_url: str
    final_url: str
    strategy: str
    count: int
    endpoints: list[DiscoveredEndpoint]
    graphql_operations: list[GraphQLOperation]
    websocket_urls: list[str]

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "final_url": self.final_url,
            "strategy": self.strategy,
            "count": self.count,
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
            "graphql_operations": [operation.to_dict() for operation in self.graphql_operations],
            "websocket_urls": self.websocket_urls,
        }

    def to_text(self) -> str:
        lines = [
            f"Page URL: {self.page_url}",
            f"Final URL: {self.final_url}",
            f"Strategy: {self.strategy}",
            f"Endpoints discovered: {self.count}",
            f"GraphQL operations: {len(self.graphql_operations)}",
            f"WebSocket URLs: {len(self.websocket_urls)}",
        ]
        for endpoint in self.endpoints:
            status = endpoint.status if endpoint.status is not None else "-"
            lines.append(f"- [{endpoint.kind}] {endpoint.method} {endpoint.url} -> {status}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            "# Endpoint Discovery",
            "",
            f"- Page URL: `{self.page_url}`",
            f"- Final URL: `{self.final_url}`",
            f"- Strategy: `{self.strategy}`",
            f"- Endpoints discovered: `{self.count}`",
            f"- GraphQL operations: `{len(self.graphql_operations)}`",
            f"- WebSocket URLs: `{len(self.websocket_urls)}`",
            "",
            "| Kind | Method | Status | URL |",
            "|---|---|---:|---|",
        ]
        for endpoint in self.endpoints:
            status = endpoint.status if endpoint.status is not None else "-"
            lines.append(f"| {endpoint.kind} | {endpoint.method} | {status} | `{endpoint.url}` |")
        if self.graphql_operations:
            lines.extend(["", "## GraphQL Operations", ""])
            for operation in self.graphql_operations:
                lines.append(f"- `{operation.name}` via `{operation.method}` `{operation.endpoint_url}`")
        if self.websocket_urls:
            lines.extend(["", "## WebSocket URLs", ""])
            for url in self.websocket_urls:
                lines.append(f"- `{url}`")
        return "\n".join(lines).rstrip()


def _get_session_class(strategy: DiscoverStrategy):
    if strategy == "fetch":
        return AsyncDynamicSession
    if strategy == "stealthy_fetch":
        return AsyncStealthySession
    raise ValueError("Unsupported strategy. Use one of: fetch, stealthy_fetch")


def _try_parse_json(text: Optional[str]) -> Optional[Any]:
    if not text:
        return None
    try:
        return json_loads(text)
    except JSONDecodeError:
        return None


def _extract_graphql_operation_names(entry: NetworkEntry) -> list[str]:
    names: list[str] = []
    payload = _try_parse_json(entry.request_post_data)
    if isinstance(payload, dict):
        operation_name = payload.get("operationName")
        if isinstance(operation_name, str) and operation_name:
            names.append(operation_name)
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                operation_name = item.get("operationName")
                if isinstance(operation_name, str) and operation_name:
                    names.append(operation_name)
    return list(dict.fromkeys(names))


def _classify_entry(entry: NetworkEntry) -> tuple[Optional[str], list[str]]:
    graphql_names = _extract_graphql_operation_names(entry)
    content_type = (entry.content_type or "").lower()
    url = entry.url.lower()

    if entry.resource_type == "websocket" or url.startswith("ws://") or url.startswith("wss://"):
        return "websocket", []
    if graphql_names or "graphql" in url or "graphql" in content_type:
        return "graphql", graphql_names
    if entry.resource_type in {"fetch", "xhr"}:
        return "api", []
    if "/api/" in url or content_type.startswith("application/json") or "json" in content_type:
        return "api", []
    return None, []


def _summarize_endpoints(entries: list[NetworkEntry]) -> tuple[list[DiscoveredEndpoint], list[GraphQLOperation], list[str]]:
    endpoints_by_key: dict[tuple[str, str, str], DiscoveredEndpoint] = {}
    graphql_operations: list[GraphQLOperation] = []
    websocket_urls: list[str] = []

    for entry in entries:
        kind, graphql_names = _classify_entry(entry)
        if kind is None:
            continue

        if kind == "websocket" and entry.url not in websocket_urls:
            websocket_urls.append(entry.url)

        if kind == "graphql":
            for name in graphql_names:
                graphql_operations.append(
                    GraphQLOperation(
                        name=name,
                        endpoint_url=entry.url,
                        method=entry.method,
                    )
                )

        key = (kind, entry.method, entry.url)
        if key not in endpoints_by_key:
            endpoints_by_key[key] = DiscoveredEndpoint(
                url=entry.url,
                method=entry.method,
                kind=kind,
                resource_type=entry.resource_type,
                status=entry.status,
                content_type=entry.content_type,
                graphql_operation_names=graphql_names or None,
            )
        elif graphql_names:
            existing = endpoints_by_key[key]
            existing.graphql_operation_names = list(
                dict.fromkeys((existing.graphql_operation_names or []) + graphql_names)
            )
            if existing.status is None:
                existing.status = entry.status
            if existing.content_type is None:
                existing.content_type = entry.content_type

    deduped_graphql = list(
        {
            (operation.name, operation.endpoint_url, operation.method): operation
            for operation in graphql_operations
        }.values()
    )
    return list(endpoints_by_key.values()), deduped_graphql, websocket_urls


async def discover_endpoints(
    page_url: str,
    actions: Optional[list[Dict[str, Any]]] = None,
    strategy: DiscoverStrategy = "fetch",
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
    max_entries: int = 100,
    max_body_chars: int = 4000,
    url_contains: Optional[str] = None,
) -> EndpointDiscoveryResult:
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

    capture = NetworkCapture(
        include_bodies=True,
        max_entries=max_entries,
        max_body_chars=max_body_chars,
        url_contains=url_contains,
    )

    async with session_cls(**session_kwargs) as session:
        request_headers_keys = {h.lower() for h in extra_headers.keys()} if extra_headers else set()
        referer = "https://www.google.com/" if (google_search and "referer" not in request_headers_keys) else None

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

            for action in actions or []:
                await _run_action(page, action)
                await session._wait_for_page_stability(page, session._config.load_dom, False)  # type: ignore[attr-defined]

            if wait_selector:
                waiter = page.locator(wait_selector)
                await waiter.first.wait_for(state=wait_selector_state)
                await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]

            await page.wait_for_timeout(wait)

            endpoints, graphql_operations, websocket_urls = _summarize_endpoints(capture.entries)

            return EndpointDiscoveryResult(
                page_url=page_url,
                final_url=page.url,
                strategy=strategy,
                count=len(endpoints),
                endpoints=endpoints,
                graphql_operations=graphql_operations,
                websocket_urls=websocket_urls,
            )
