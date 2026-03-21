from dataclasses import asdict, dataclass
from json import dumps as json_dumps

from orjson import loads as json_loads, JSONDecodeError

from scrapling.fetchers import Fetcher, DynamicFetcher, StealthyFetcher
from scrapling.engines.toolbelt.custom import Response as ScraplingResponse
from scrapling.core._types import Optional, Literal, Any

FetchStrategy = Literal["get", "fetch", "stealthy_fetch"]
AppStateKind = Literal["next_data", "nuxt_data", "json_ld", "application_json"]


@dataclass(slots=True)
class AppStateEntry:
    kind: str
    key: str
    selector: str
    data: Any

    def to_dict(self):
        return asdict(self)


@dataclass(slots=True)
class AppStateResult:
    page_url: str
    strategy: str
    count: int
    states: list[AppStateEntry]

    def to_dict(self):
        return {
            "page_url": self.page_url,
            "strategy": self.strategy,
            "count": self.count,
            "states": [state.to_dict() for state in self.states],
        }

    def to_text(self) -> str:
        lines = [
            f"Page URL: {self.page_url}",
            f"Strategy: {self.strategy}",
            f"States found: {self.count}",
        ]
        for state in self.states:
            summary = _summarize_json_value(state.data)
            lines.append(f"- {state.kind} ({state.key}) via {state.selector}: {summary}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        lines = [
            f"# App State",
            "",
            f"- Page URL: `{self.page_url}`",
            f"- Strategy: `{self.strategy}`",
            f"- States found: `{self.count}`",
            "",
        ]
        for state in self.states:
            lines.extend(
                [
                    f"## {state.kind}",
                    "",
                    f"- Key: `{state.key}`",
                    f"- Selector: `{state.selector}`",
                    "",
                    "```json",
                    json_dumps(state.data, indent=2, sort_keys=True, ensure_ascii=False),
                    "```",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()


def _summarize_json_value(value: Any) -> str:
    if isinstance(value, dict):
        keys = list(value.keys())[:5]
        return f"object with {len(value)} keys ({', '.join(map(str, keys))})"
    if isinstance(value, list):
        return f"array with {len(value)} items"
    return type(value).__name__


async def _fetch_with_strategy(url: str, strategy: FetchStrategy) -> ScraplingResponse:
    if strategy == "get":
        return Fetcher.get(url)
    if strategy == "fetch":
        return await DynamicFetcher.async_fetch(url)
    if strategy == "stealthy_fetch":
        return await StealthyFetcher.async_fetch(url)
    raise ValueError("Unsupported strategy. Use one of: get, fetch, stealthy_fetch")


def _parse_script_json(text: str) -> Optional[Any]:
    if not text:
        return None
    try:
        return json_loads(str(text))
    except JSONDecodeError:
        return None


def _collect_state(
    page: ScraplingResponse,
    selector: str,
    kind: str,
    key_prefix: str,
    limit: Optional[int] = None,
) -> list[AppStateEntry]:
    results: list[AppStateEntry] = []
    for index, node in enumerate(page.css(selector)):
        if limit is not None and len(results) >= limit:
            break
        data = _parse_script_json(node.text.strip() if node.text else "")
        if data is None:
            continue
        results.append(
            AppStateEntry(
                kind=kind,
                key=f"{key_prefix}[{index}]",
                selector=selector,
                data=data,
            )
        )
    return results


async def extract_app_state(
    page_url: str,
    strategy: FetchStrategy = "fetch",
    kinds: Optional[list[AppStateKind]] = None,
) -> AppStateResult:
    selected_kinds = kinds or ["next_data", "nuxt_data", "json_ld", "application_json"]
    page = await _fetch_with_strategy(page_url, strategy)
    states: list[AppStateEntry] = []

    if "next_data" in selected_kinds:
        states.extend(_collect_state(page, "script#__NEXT_DATA__", "next_data", "__NEXT_DATA__", limit=1))
    if "nuxt_data" in selected_kinds:
        states.extend(_collect_state(page, "script#__NUXT_DATA__", "nuxt_data", "__NUXT_DATA__", limit=1))
        states.extend(_collect_state(page, "script[data-nuxt-data]", "nuxt_data", "data-nuxt-data"))
    if "json_ld" in selected_kinds:
        states.extend(_collect_state(page, 'script[type="application/ld+json"]', "json_ld", "json_ld"))
    if "application_json" in selected_kinds:
        states.extend(_collect_state(page, 'script[type="application/json"]', "application_json", "application_json"))

    return AppStateResult(page_url=page_url, strategy=strategy, count=len(states), states=states)
