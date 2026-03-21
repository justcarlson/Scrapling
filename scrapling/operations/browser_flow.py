from dataclasses import asdict, dataclass, field

from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession
from scrapling.core.shell import Convertor
from scrapling.parser import Selector
from scrapling.engines.toolbelt.convertor import ResponseFactory
from scrapling.core._types import Optional, Literal, Any, Dict, Sequence, SetCookieParam, extraction_types
from scrapling.operations.network import NetworkCapture, NetworkEntry

FlowStrategy = Literal["fetch", "stealthy_fetch"]
FlowActionType = Literal["click", "wait", "wait_for_selector", "fill", "press", "scroll", "evaluate"]


@dataclass(slots=True)
class FlowActionRecord:
    index: int
    type: str
    status: str
    details: Dict[str, Any]

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class FlowExtractResult:
    page_url: str
    final_url: str
    strategy: str
    extraction_type: str
    css_selector: Optional[str]
    content: list[str]
    actions: list[FlowActionRecord]
    network: list[NetworkEntry] = field(default_factory=list)

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "final_url": self.final_url,
            "strategy": self.strategy,
            "extraction_type": self.extraction_type,
            "css_selector": self.css_selector,
            "content": self.content,
            "actions": [action.to_dict() for action in self.actions],
            "network": [entry.to_dict() for entry in self.network],
        }

    def to_text(self) -> str:
        lines = [
            f"Page URL: {self.page_url}",
            f"Final URL: {self.final_url}",
            f"Strategy: {self.strategy}",
            f"Extraction type: {self.extraction_type}",
            f"Actions executed: {len(self.actions)}",
        ]
        if self.network:
            lines.append(f"Network entries observed: {len(self.network)}")
        for action in self.actions:
            lines.append(f"- [{action.index}] {action.type}: {action.status}")
        if self.network:
            lines.append("")
            lines.append("Observed network:")
            for entry in self.network:
                status = entry.status if entry.status is not None else "-"
                lines.append(f"- [{entry.index}] {entry.method} {entry.url} -> {status} ({entry.resource_type})")
        if self.content:
            lines.extend(["", *self.content])
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            "# Browser Flow",
            "",
            f"- Page URL: `{self.page_url}`",
            f"- Final URL: `{self.final_url}`",
            f"- Strategy: `{self.strategy}`",
            f"- Extraction type: `{self.extraction_type}`",
            f"- Actions executed: `{len(self.actions)}`",
            f"- Network entries observed: `{len(self.network)}`",
            "",
            "## Actions",
            "",
        ]
        for action in self.actions:
            lines.append(f"- `{action.index}` `{action.type}` `{action.status}`")
        if self.network:
            lines.extend(["", "## Network", "", "| # | Method | Status | Type | URL |", "|---|---|---:|---|---|"])
            for entry in self.network:
                status = entry.status if entry.status is not None else "-"
                lines.append(
                    f"| {entry.index} | {entry.method} | {status} | {entry.resource_type} | `{entry.url}` |"
                )
        lines.extend(["", "## Content", ""])
        lines.extend(self.content or [""])
        return "\n".join(lines).rstrip()


def _get_session_class(strategy: FlowStrategy):
    if strategy == "fetch":
        return AsyncDynamicSession
    if strategy == "stealthy_fetch":
        return AsyncStealthySession
    raise ValueError("Unsupported strategy. Use one of: fetch, stealthy_fetch")


async def _run_action(page, action: Dict[str, Any]) -> Dict[str, Any]:
    action_type = action.get("type")
    if action_type == "click":
        selector = action["selector"]
        await page.locator(selector).first.click()
        return {"selector": selector}

    if action_type == "wait":
        timeout_ms = int(action.get("timeout_ms", 0))
        await page.wait_for_timeout(timeout_ms)
        return {"timeout_ms": timeout_ms}

    if action_type == "wait_for_selector":
        selector = action["selector"]
        state = action.get("state", "attached")
        await page.locator(selector).first.wait_for(state=state)
        return {"selector": selector, "state": state}

    if action_type == "fill":
        selector = action["selector"]
        value = action.get("value", "")
        await page.locator(selector).first.fill(value)
        return {"selector": selector}

    if action_type == "press":
        selector = action["selector"]
        key = action["key"]
        await page.locator(selector).first.press(key)
        return {"selector": selector, "key": key}

    if action_type == "scroll":
        x = int(action.get("x", 0))
        y = int(action.get("y", 0))
        if action.get("to_bottom"):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return {"to_bottom": True}
        await page.mouse.wheel(x, y)
        return {"x": x, "y": y}

    if action_type == "evaluate":
        script = action["script"]
        arg = action.get("arg")
        await page.evaluate(script, arg)
        return {"script": script}

    raise ValueError(f"Unsupported action type: {action_type}")


async def run_flow_and_extract(
    page_url: str,
    actions: list[Dict[str, Any]],
    strategy: FlowStrategy = "fetch",
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
    wait_selector_state: str = "attached",
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
) -> FlowExtractResult:
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

    records: list[FlowActionRecord] = []
    capture = NetworkCapture(
        include_headers=include_headers,
        include_bodies=include_bodies,
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
            None,
        ) as page_info:
            page = page_info.page
            if observe_network:
                capture.bind(page)
            first_response = await page.goto(page_url, referer=referer)
            await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]
            if not first_response:
                raise RuntimeError(f"Failed to get response for {page_url}")

            if strategy == "stealthy_fetch" and solve_cloudflare:
                await session._cloudflare_solver(page)  # type: ignore[attr-defined]
                await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]

            for index, action in enumerate(actions):
                details = await _run_action(page, action)
                records.append(
                    FlowActionRecord(
                        index=index,
                        type=action["type"],
                        status="completed",
                        details=details,
                    )
                )
                await session._wait_for_page_stability(page, session._config.load_dom, False)  # type: ignore[attr-defined]

            if wait_selector:
                waiter = page.locator(wait_selector)
                await waiter.first.wait_for(state=wait_selector_state)
                await session._wait_for_page_stability(page, session._config.load_dom, network_idle)  # type: ignore[attr-defined]

            await page.wait_for_timeout(wait)
            html = await ResponseFactory._get_async_page_content(page)
            selector = Selector(html)
            content = [
                result
                for result in Convertor._extract_content(
                    selector,
                    extraction_type=extraction_type,
                    css_selector=css_selector,
                    main_content_only=main_content_only,
                )
                if result
            ]

            return FlowExtractResult(
                page_url=page_url,
                final_url=page.url,
                strategy=strategy,
                extraction_type=extraction_type,
                css_selector=css_selector,
                content=content,
                actions=records,
                network=capture.entries if observe_network else [],
            )
