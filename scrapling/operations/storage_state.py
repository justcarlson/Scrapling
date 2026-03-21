from dataclasses import asdict, dataclass
from json import dumps as json_dumps

from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession
from scrapling.core._types import Optional, Literal, Any, Dict, Sequence, SetCookieParam

StorageStrategy = Literal["fetch", "stealthy_fetch"]


@dataclass(slots=True)
class StorageOriginEntry:
    origin: str
    local_storage: Dict[str, str]

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class StorageStateResult:
    page_url: str
    final_url: str
    strategy: str
    cookies: list[Dict[str, Any]]
    local_storage: Dict[str, str]
    session_storage: Dict[str, str]
    origins: list[StorageOriginEntry]

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "final_url": self.final_url,
            "strategy": self.strategy,
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "session_storage": self.session_storage,
            "origins": [origin.to_dict() for origin in self.origins],
        }

    def to_text(self) -> str:
        lines = [
            f"Page URL: {self.page_url}",
            f"Final URL: {self.final_url}",
            f"Strategy: {self.strategy}",
            f"Cookies: {len(self.cookies)}",
            f"Local storage keys: {len(self.local_storage)}",
            f"Session storage keys: {len(self.session_storage)}",
            f"Origins: {len(self.origins)}",
        ]
        for origin in self.origins:
            lines.append(f"- {origin.origin}: {len(origin.local_storage)} local storage entries")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            "# Storage State",
            "",
            f"- Page URL: `{self.page_url}`",
            f"- Final URL: `{self.final_url}`",
            f"- Strategy: `{self.strategy}`",
            f"- Cookies: `{len(self.cookies)}`",
            f"- Local storage keys: `{len(self.local_storage)}`",
            f"- Session storage keys: `{len(self.session_storage)}`",
            f"- Origins: `{len(self.origins)}`",
            "",
            "## Current Page Storage",
            "",
            "### Local Storage",
            "",
            "```json",
            json_dumps(self.local_storage, indent=2, sort_keys=True, ensure_ascii=False),
            "```",
            "",
            "### Session Storage",
            "",
            "```json",
            json_dumps(self.session_storage, indent=2, sort_keys=True, ensure_ascii=False),
            "```",
            "",
        ]
        if self.origins:
            lines.extend(["## Origins", ""])
            for origin in self.origins:
                lines.extend(
                    [
                        f"### {origin.origin}",
                        "",
                        "```json",
                        json_dumps(origin.local_storage, indent=2, sort_keys=True, ensure_ascii=False),
                        "```",
                        "",
                    ]
                )
        return "\n".join(lines).rstrip()


def _get_session_class(strategy: StorageStrategy):
    if strategy == "fetch":
        return AsyncDynamicSession
    if strategy == "stealthy_fetch":
        return AsyncStealthySession
    raise ValueError("Unsupported strategy. Use one of: fetch, stealthy_fetch")


async def _read_web_storage(page, storage_name: str) -> Dict[str, str]:
    return await page.evaluate(
        """(name) => {
            const storage = window[name];
            const result = {};
            for (let index = 0; index < storage.length; index += 1) {
                const key = storage.key(index);
                if (key !== null) {
                    result[key] = storage.getItem(key) ?? "";
                }
            }
            return result;
        }""",
        storage_name,
    )


async def export_storage_state(
    page_url: str,
    strategy: StorageStrategy = "fetch",
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
) -> StorageStateResult:
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

        async with session._page_generator(  # type: ignore[attr-defined]
            timeout,
            extra_headers,
            disable_resources,
            proxy,
            blocked_domains,
        ) as page_info:
            page = page_info.page
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

            local_storage = await _read_web_storage(page, "localStorage")
            session_storage = await _read_web_storage(page, "sessionStorage")
            context_storage_state = await page.context.storage_state()
            origins = [
                StorageOriginEntry(
                    origin=entry.get("origin", ""),
                    local_storage={item.get("name", ""): item.get("value", "") for item in entry.get("localStorage", [])},
                )
                for entry in context_storage_state.get("origins", [])
            ]

            return StorageStateResult(
                page_url=page_url,
                final_url=page.url,
                strategy=strategy,
                cookies=await page.context.cookies(),
                local_storage=local_storage,
                session_storage=session_storage,
                origins=origins,
            )
