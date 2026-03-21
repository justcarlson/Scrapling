from dataclasses import asdict, dataclass

from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession
from scrapling.engines._browsers._base import StealthySessionMixin
from scrapling.engines.toolbelt.convertor import ResponseFactory
from scrapling.core._types import Optional, Literal, Any, Dict, Sequence, SetCookieParam
from scrapling.operations.network import NetworkCapture, NetworkEntry

DebugStrategy = Literal["fetch", "stealthy_fetch"]


@dataclass(slots=True)
class RedirectEntry:
    index: int
    url: str
    status: Optional[int] = None

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class PageDebugResult:
    page_url: str
    final_url: str
    strategy: str
    status: Optional[int]
    title: Optional[str]
    ready_state: Optional[str]
    challenge_detected: Optional[str]
    redirect_chain: list[RedirectEntry]
    page_errors: list[str]
    failed_requests: list[NetworkEntry]
    network_count: int

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "final_url": self.final_url,
            "strategy": self.strategy,
            "status": self.status,
            "title": self.title,
            "ready_state": self.ready_state,
            "challenge_detected": self.challenge_detected,
            "redirect_chain": [entry.to_dict() for entry in self.redirect_chain],
            "page_errors": self.page_errors,
            "failed_requests": [entry.to_dict() for entry in self.failed_requests],
            "network_count": self.network_count,
        }

    def to_text(self) -> str:
        lines = [
            f"Page URL: {self.page_url}",
            f"Final URL: {self.final_url}",
            f"Strategy: {self.strategy}",
            f"Status: {self.status if self.status is not None else '-'}",
            f"Title: {self.title or '-'}",
            f"Ready state: {self.ready_state or '-'}",
            f"Challenge detected: {self.challenge_detected or '-'}",
            f"Redirects: {len(self.redirect_chain)}",
            f"Page errors: {len(self.page_errors)}",
            f"Failed requests: {len(self.failed_requests)}",
            f"Observed requests: {self.network_count}",
        ]
        if self.redirect_chain:
            lines.append("")
            lines.append("Redirect chain:")
            for entry in self.redirect_chain:
                status = entry.status if entry.status is not None else "-"
                lines.append(f"- [{entry.index}] {entry.url} -> {status}")
        if self.page_errors:
            lines.append("")
            lines.append("Page errors:")
            for error in self.page_errors:
                lines.append(f"- {error}")
        if self.failed_requests:
            lines.append("")
            lines.append("Failed requests:")
            for entry in self.failed_requests:
                lines.append(f"- [{entry.index}] {entry.method} {entry.url} ({entry.resource_type})")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            "# Page Debug",
            "",
            f"- Page URL: `{self.page_url}`",
            f"- Final URL: `{self.final_url}`",
            f"- Strategy: `{self.strategy}`",
            f"- Status: `{self.status if self.status is not None else '-'}`",
            f"- Title: `{self.title or '-'}`",
            f"- Ready state: `{self.ready_state or '-'}`",
            f"- Challenge detected: `{self.challenge_detected or '-'}`",
            f"- Redirects: `{len(self.redirect_chain)}`",
            f"- Page errors: `{len(self.page_errors)}`",
            f"- Failed requests: `{len(self.failed_requests)}`",
            f"- Observed requests: `{self.network_count}`",
            "",
        ]
        if self.redirect_chain:
            lines.extend(["## Redirect Chain", "", "| # | Status | URL |", "|---|---:|---|"])
            for entry in self.redirect_chain:
                status = entry.status if entry.status is not None else "-"
                lines.append(f"| {entry.index} | {status} | `{entry.url}` |")
            lines.append("")
        if self.page_errors:
            lines.extend(["## Page Errors", ""])
            lines.extend(f"- {error}" for error in self.page_errors)
            lines.append("")
        if self.failed_requests:
            lines.extend(["## Failed Requests", "", "| # | Method | Type | URL |", "|---|---|---|---|"])
            for entry in self.failed_requests:
                lines.append(f"| {entry.index} | {entry.method} | {entry.resource_type} | `{entry.url}` |")
            lines.append("")
        return "\n".join(lines).rstrip()


def _get_session_class(strategy: DebugStrategy):
    if strategy == "fetch":
        return AsyncDynamicSession
    if strategy == "stealthy_fetch":
        return AsyncStealthySession
    raise ValueError("Unsupported strategy. Use one of: fetch, stealthy_fetch")


async def _collect_redirect_chain(first_response) -> list[RedirectEntry]:
    chain: list[RedirectEntry] = []
    current_request = first_response.request.redirected_from
    while current_request:
        current_response = await current_request.response()
        chain.insert(
            0,
            RedirectEntry(
                index=len(chain),
                url=current_request.url,
                status=current_response.status if current_response else 301,
            ),
        )
        current_request = current_request.redirected_from
    return [RedirectEntry(index=index, url=entry.url, status=entry.status) for index, entry in enumerate(chain)]


async def debug_page(
    page_url: str,
    strategy: DebugStrategy = "fetch",
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
) -> PageDebugResult:
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

    capture = NetworkCapture(max_entries=max_entries)
    page_errors: list[str] = []

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
            page.on("pageerror", lambda error: page_errors.append(str(error)))

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

            html = await ResponseFactory._get_async_page_content(page)
            challenge_detected = StealthySessionMixin._detect_cloudflare(html)
            ready_state = await page.evaluate("() => document.readyState")
            title = await page.title()
            redirect_chain = await _collect_redirect_chain(first_response)
            failed_requests = [entry for entry in capture.entries if entry.stage == "failed"]

            return PageDebugResult(
                page_url=page_url,
                final_url=page.url,
                strategy=strategy,
                status=first_response.status,
                title=title,
                ready_state=ready_state,
                challenge_detected=challenge_detected,
                redirect_chain=redirect_chain,
                page_errors=page_errors,
                failed_requests=failed_requests,
                network_count=len(capture.entries),
            )
