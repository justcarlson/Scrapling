from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import httpx
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ROOT / "tests" / "live" / "targets.json"
DEFAULT_ACTIONS = ROOT / "tests" / "live" / "actions" / "todomvc-add.json"


class SmokeFailure(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def build_todomvc_actions(todo_text: str) -> list[dict[str, Any]]:
    actions = load_json(DEFAULT_ACTIONS)
    for action in actions:
        if action.get("value") == "__LIVE_SMOKE_TODO__":
            action["value"] = todo_text
    return actions


def cookie_present(cookies: list[dict[str, Any]], name: str, value: str) -> bool:
    for cookie in cookies:
        if cookie.get("name") == name and str(cookie.get("value")) == value:
            return True
    return False


def resolve_python_bin(python_bin: str | None) -> str:
    if python_bin:
        return python_bin
    default_python = ROOT / ".venv" / "bin" / "python"
    if default_python.exists():
        return str(default_python)
    return sys.executable


def resolve_cli_bin(cli_bin: str | None, python_bin: str) -> list[str]:
    if cli_bin:
        return [cli_bin]
    default_cli = ROOT / ".venv" / "bin" / "scrapling"
    if default_cli.exists():
        return [str(default_cli)]
    return [python_bin, "-m", "scrapling.cli"]


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def open_stdio_session(cli_prefix: list[str]) -> AsyncIterator[ClientSession]:
    server = StdioServerParameters(
        command=cli_prefix[0],
        args=[*cli_prefix[1:], "mcp"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def open_http_session(cli_prefix: list[str], port: int) -> AsyncIterator[ClientSession]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    process = subprocess.Popen(
        [
            *cli_prefix,
            "mcp",
            "--http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}/mcp"
        async with httpx.AsyncClient(timeout=5.0) as client:
            ready = False
            for _ in range(40):
                if process.poll() is not None:
                    stderr = process.stderr.read() if process.stderr else ""
                    raise SmokeFailure(f"MCP HTTP server exited early:\n{stderr}")
                try:
                    response = await client.post(
                        base_url,
                        headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
                        json={
                            "jsonrpc": "2.0",
                            "id": "ready-check",
                            "method": "ping",
                            "params": {}
                        },
                    )
                    if response.status_code in {200, 202, 400, 404}:
                        ready = True
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
            require(ready, "MCP HTTP server did not become reachable in time")

        async with streamable_http_client(base_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


async def test_list_tools(session: ClientSession) -> dict[str, Any]:
    result = await session.list_tools()
    names = {tool.name for tool in result.tools}
    required = {
        "get",
        "extract_app_state",
        "list_page_images",
        "fetch_page_image",
        "run_flow_and_extract",
        "observe_network",
        "debug_page",
        "export_storage_state",
        "discover_endpoints",
    }
    missing = sorted(required - names)
    require(not missing, f"MCP server is missing expected tools: {', '.join(missing)}")
    return {"tool_count": len(names)}


async def test_get(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["books"]
    result = await session.call_tool("get", {"url": target["url"]})
    require(not result.isError, "MCP get returned an error")
    payload = result.structuredContent or {}
    require(target["known_text"] in "\n".join(payload.get("content", [])), "expected known text not found in MCP get output")
    return {"status": payload.get("status")}


async def test_list_page_images(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["books"]
    result = await session.call_tool("list_page_images", {"page_url": target["url"]})
    require(not result.isError, "MCP list_page_images returned an error")
    payload = result.structuredContent or {}
    require(payload.get("count", 0) > 0, "expected non-empty MCP image candidate list")
    return {"count": payload["count"]}


async def test_fetch_page_image(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["books"]
    result = await session.call_tool("fetch_page_image", {"page_url": target["url"]})
    require(not result.isError, "MCP fetch_page_image returned an error")
    payload = result.structuredContent or {}
    image_blocks = [block for block in result.content if getattr(block, "type", None) == "image"]
    require(image_blocks, "MCP fetch_page_image did not return an image content block")
    require(bool(payload.get("mime_type")), "MCP image metadata missing mime_type")
    require(bool(payload.get("image_url")), "MCP image metadata missing image_url")
    return {"mime_type": payload["mime_type"]}


async def test_run_flow_and_extract(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["todomvc"]
    todo_text = f"scrapling-mcp-{int(time.time())}"
    result = await session.call_tool(
        "run_flow_and_extract",
        {
            "page_url": target["url"],
            "actions": build_todomvc_actions(todo_text),
            "extraction_type": "text",
        },
    )
    require(not result.isError, "MCP run_flow_and_extract returned an error")
    payload = result.structuredContent or {}
    require(any(todo_text in chunk for chunk in payload.get("content", [])), "inserted todo item not found in MCP flow output")
    return {"final_url": payload.get("final_url")}


async def test_run_flow_and_extract_with_network(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["todomvc"]
    todo_text = f"scrapling-mcp-network-{int(time.time())}"
    result = await session.call_tool(
        "run_flow_and_extract",
        {
            "page_url": target["url"],
            "actions": build_todomvc_actions(todo_text),
            "extraction_type": "text",
            "observe_network": True,
        },
    )
    require(not result.isError, "MCP flow+network returned an error")
    payload = result.structuredContent or {}
    require("actions" in payload, "MCP flow result is missing actions")
    require("network" in payload, "MCP flow result is missing network")
    return {"network_count": len(payload.get("network", []))}


async def test_extract_app_state_next(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["next_preview"]
    result = await session.call_tool(
        "extract_app_state",
        {
            "page_url": target["url"],
            "strategy": "get",
            "kinds": ["next_data"],
        },
    )
    require(not result.isError, "MCP extract_app_state next_data returned an error")
    payload = result.structuredContent or {}
    require(payload.get("count", 0) > 0, "expected at least one Next.js app-state payload from MCP")
    state = payload["states"][0]
    require(state["kind"] == target["expected_kind"], "unexpected app-state kind for Next.js MCP target")
    require(state["key"] == target["expected_key"], "unexpected app-state key for Next.js MCP target")
    return {"count": payload["count"]}


async def test_extract_app_state_nuxt(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["nuxt_new"]
    result = await session.call_tool(
        "extract_app_state",
        {
            "page_url": target["url"],
            "strategy": "get",
            "kinds": ["nuxt_data"],
        },
    )
    require(not result.isError, "MCP extract_app_state nuxt_data returned an error")
    payload = result.structuredContent or {}
    require(payload.get("count", 0) > 0, "expected at least one Nuxt app-state payload from MCP")
    kinds = {state["kind"] for state in payload["states"]}
    keys = [state["key"] for state in payload["states"]]
    require(target["expected_kind"] in kinds, "unexpected app-state kinds for Nuxt MCP target")
    require(any(key.startswith(target["expected_key_prefix"]) for key in keys), "expected Nuxt app-state key was not found in MCP output")
    return {"count": payload["count"]}


async def test_debug_page(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["webscraper_ajax"]
    result = await session.call_tool("debug_page", {"page_url": target["url"]})
    require(not result.isError, "MCP debug_page returned an error")
    payload = result.structuredContent or {}
    require(target["expected_title"] in (payload.get("title") or ""), "MCP debug_page title did not match expected target")
    return {"final_url": payload.get("final_url")}


async def test_observe_network(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["webscraper_ajax"]
    result = await session.call_tool("observe_network", {"page_url": target["url"], "include_bodies": True})
    require(not result.isError, "MCP observe_network returned an error")
    payload = result.structuredContent or {}
    require(payload.get("count", -1) >= 0, "MCP observe_network returned an invalid count")
    return {"count": payload["count"]}


async def test_export_storage_state(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["httpbin_cookies"]
    result = await session.call_tool("export_storage_state", {"page_url": target["url"]})
    require(not result.isError, "MCP export_storage_state returned an error")
    payload = result.structuredContent or {}
    require(
        cookie_present(payload.get("cookies", []), target["cookie_name"], target["cookie_value"]),
        "expected cookie was not present in MCP storage export",
    )
    return {"final_url": payload.get("final_url")}


async def test_discover_endpoints(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["webscraper_ajax"]
    result = await session.call_tool("discover_endpoints", {"page_url": target["url"]})
    require(not result.isError, "MCP discover_endpoints returned an error")
    payload = result.structuredContent or {}
    require("endpoints" in payload, "MCP discover_endpoints output is missing endpoints")
    return {"count": payload.get("count", 0)}


async def test_debug_page_challenge(session: ClientSession, targets: dict[str, Any]) -> dict[str, Any]:
    target = targets["nopecha_cloudflare"]
    result = await session.call_tool("debug_page", {"page_url": target["url"]})
    require(not result.isError, "MCP challenge debug_page returned an error")
    payload = result.structuredContent or {}
    title = payload.get("title") or ""
    challenge = payload.get("challenge_detected")
    require(
        target["expected_title_contains"] in title or challenge is not None,
        "MCP challenge debug did not report the expected title or a challenge type",
    )
    return {"title": title, "challenge_detected": challenge}


TESTS: dict[str, Callable[..., Any]] = {
    "list_tools": test_list_tools,
    "get": test_get,
    "extract_app_state_next": test_extract_app_state_next,
    "extract_app_state_nuxt": test_extract_app_state_nuxt,
    "list_page_images": test_list_page_images,
    "fetch_page_image": test_fetch_page_image,
    "run_flow_and_extract": test_run_flow_and_extract,
    "run_flow_and_extract_with_network": test_run_flow_and_extract_with_network,
    "debug_page": test_debug_page,
    "observe_network": test_observe_network,
    "export_storage_state": test_export_storage_state,
    "discover_endpoints": test_discover_endpoints,
    "debug_page_challenge": test_debug_page_challenge,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live end-to-end Scrapling MCP smoke tests.")
    parser.add_argument("--targets-file", default=str(DEFAULT_TARGETS), help="Path to the live target registry JSON file.")
    parser.add_argument("--python-bin", default=None, help="Python executable to use for the MCP server process.")
    parser.add_argument("--cli-bin", default=None, help="Path to the Scrapling CLI executable.")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="MCP transport to exercise.")
    parser.add_argument("--port", type=int, default=None, help="HTTP port to use when --transport=http.")
    parser.add_argument("--tests", nargs="*", choices=sorted(TESTS.keys()), help="Subset of MCP smoke tests to run.")
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()
    targets = load_json(Path(args.targets_file))
    python_bin = resolve_python_bin(args.python_bin)
    cli_prefix = resolve_cli_bin(args.cli_bin, python_bin)
    selected_tests = args.tests or list(TESTS.keys())

    if args.transport == "stdio":
        session_cm = open_stdio_session(cli_prefix)
    else:
        session_cm = open_http_session(cli_prefix, args.port or find_free_port())

    failures: list[tuple[str, str]] = []
    async with session_cm as session:
        for name in selected_tests:
            print(f"[mcp-smoke] running {name}", flush=True)
            try:
                if name == "list_tools":
                    details = await TESTS[name](session=session)
                else:
                    details = await TESTS[name](session=session, targets=targets)
            except SmokeFailure as exc:
                failures.append((name, str(exc)))
                print(f"[mcp-smoke] FAIL {name}: {exc}", file=sys.stderr, flush=True)
                continue
            print(f"[mcp-smoke] PASS {name}: {json.dumps(details, sort_keys=True)}", flush=True)

    if failures:
        print("[mcp-smoke] failures:", file=sys.stderr)
        for name, message in failures:
            print(f" - {name}: {message}", file=sys.stderr)
        return 1

    print(f"[mcp-smoke] all {len(selected_tests)} selected tests passed")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
