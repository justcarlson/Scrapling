from __future__ import annotations

import argparse
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ROOT / "tests" / "live" / "targets.json"
DEFAULT_ACTIONS = ROOT / "tests" / "live" / "actions" / "todomvc-add.json"


class SmokeFailure(RuntimeError):
    pass


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def resolve_cli_prefix(cli_bin: str | None, python_bin: str | None) -> list[str]:
    if cli_bin:
        return [cli_bin]

    default_cli = ROOT / ".venv" / "bin" / "scrapling"
    if default_cli.exists():
        return [str(default_cli)]

    if python_bin:
        return [python_bin, "-m", "scrapling.cli"]

    default_python = ROOT / ".venv" / "bin" / "python"
    if default_python.exists():
        return [str(default_python), "-m", "scrapling.cli"]

    raise SmokeFailure("Could not resolve Scrapling CLI. Pass --cli-bin or --python-bin.")


def run_command(argv: list[str], timeout: int) -> CommandResult:
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return CommandResult(
        argv=argv,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def parse_json_output(result: CommandResult) -> Any:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"Command did not return valid JSON: {' '.join(result.argv)}\n{exc}") from exc


def build_todomvc_actions(todo_text: str, output_dir: Path) -> Path:
    actions = load_json(DEFAULT_ACTIONS)
    for action in actions:
        if action.get("value") == "__LIVE_SMOKE_TODO__":
            action["value"] = todo_text
    path = output_dir / "todomvc-actions.json"
    write_json(path, actions)
    return path


def cookie_present(cookies: list[dict[str, Any]], name: str, value: str) -> bool:
    for cookie in cookies:
        if cookie.get("name") == name and str(cookie.get("value")) == value:
            return True
    return False


def test_static_extract(cli_prefix: list[str], targets: dict[str, Any], output_dir: Path, timeout: int) -> dict[str, Any]:
    target = targets["books"]
    output_file = output_dir / "books.md"
    result = run_command([*cli_prefix, "extract", "get", target["url"], str(output_file)], timeout=timeout)
    require(result.returncode == 0, f"extract get failed:\n{result.stderr}")
    require(output_file.exists(), "extract get did not create an output file")
    content = output_file.read_text()
    require(target["known_text"] in content, f"expected known text not found in {output_file}")
    return {"output_file": str(output_file)}


def test_list_page_images(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["books"]
    result = run_command([*cli_prefix, "inspect", "list-page-images", target["url"]], timeout=timeout)
    require(result.returncode == 0, f"list-page-images failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require(payload["count"] > 0, "expected non-empty image candidate list")
    return {"count": payload["count"]}


def test_fetch_page_image(cli_prefix: list[str], targets: dict[str, Any], output_dir: Path, timeout: int) -> dict[str, Any]:
    target = targets["books"]
    output_file = output_dir / "cover.bin"
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "fetch-page-image",
            target["url"],
            str(output_file),
            "--metadata-format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"fetch-page-image failed:\n{result.stderr}")
    metadata = parse_json_output(result)
    require(output_file.exists(), "fetch-page-image did not create an output file")
    require(output_file.stat().st_size > 0, "fetched image file is empty")
    require(bool(metadata.get("mime_type")), "image metadata missing mime_type")
    require(bool(metadata.get("image_url")), "image metadata missing image_url")
    return {
        "output_file": str(output_file),
        "mime_type": metadata["mime_type"],
    }


def test_run_flow(cli_prefix: list[str], targets: dict[str, Any], output_dir: Path, timeout: int) -> dict[str, Any]:
    target = targets["todomvc"]
    todo_text = f"scrapling-live-{int(time.time())}"
    actions_file = build_todomvc_actions(todo_text, output_dir)
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "run-flow-and-extract",
            target["url"],
            "--actions-file",
            str(actions_file),
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"run-flow-and-extract failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require("#/" in payload["final_url"], "expected TodoMVC final URL to remain in app route")
    require(any(todo_text in chunk for chunk in payload["content"]), "inserted todo item not found in extracted content")
    require(all(action["status"] == "completed" for action in payload["actions"]), "one or more flow actions did not complete")
    return {"todo_text": todo_text, "actions_file": str(actions_file)}


def test_run_flow_with_network(cli_prefix: list[str], targets: dict[str, Any], output_dir: Path, timeout: int) -> dict[str, Any]:
    target = targets["todomvc"]
    todo_text = f"scrapling-live-network-{int(time.time())}"
    actions_file = build_todomvc_actions(todo_text, output_dir)
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "run-flow-and-extract",
            target["url"],
            "--actions-file",
            str(actions_file),
            "--observe-network",
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"run-flow-and-extract --observe-network failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require("actions" in payload, "flow result is missing actions")
    require("network" in payload, "flow result is missing network")
    return {"network_count": len(payload["network"])}


def test_extract_app_state_next(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["next_preview"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "extract-app-state",
            target["url"],
            "--kind",
            "next_data",
            "--strategy",
            "get",
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"extract-app-state next_data failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require(payload["count"] > 0, "expected at least one Next.js app-state payload")
    state = payload["states"][0]
    require(state["kind"] == target["expected_kind"], "unexpected app-state kind for Next.js target")
    require(state["key"] == target["expected_key"], "unexpected app-state key for Next.js target")
    return {"count": payload["count"]}


def test_extract_app_state_nuxt(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["nuxt_new"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "extract-app-state",
            target["url"],
            "--kind",
            "nuxt_data",
            "--strategy",
            "get",
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"extract-app-state nuxt_data failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require(payload["count"] > 0, "expected at least one Nuxt app-state payload")
    kinds = {state["kind"] for state in payload["states"]}
    keys = [state["key"] for state in payload["states"]]
    require(target["expected_kind"] in kinds, "unexpected app-state kinds for Nuxt target")
    require(any(key.startswith(target["expected_key_prefix"]) for key in keys), "expected Nuxt app-state key was not found")
    return {"count": payload["count"]}


def test_debug_page_ajax(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["webscraper_ajax"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "debug-page",
            target["url"],
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"debug-page failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require(target["expected_title"] in (payload.get("title") or ""), "debug-page title did not match expected target")
    require(payload.get("final_url"), "debug-page did not return a final_url")
    return {"final_url": payload["final_url"], "page_errors": len(payload.get("page_errors", []))}


def test_observe_network(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["webscraper_ajax"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "observe-network",
            target["url"],
            "--include-bodies",
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"observe-network failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require(payload["count"] >= 0, "observe-network returned an invalid count")
    if payload["entries"]:
        first = payload["entries"][0]
        for key in ("url", "method", "stage"):
            require(key in first, f"observe-network entry missing {key}")
    return {"count": payload["count"]}


def test_discover_endpoints(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["webscraper_ajax"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "discover-endpoints",
            target["url"],
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"discover-endpoints failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require("endpoints" in payload, "discover-endpoints output is missing endpoints")
    return {"count": payload["count"]}


def test_export_storage_state(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["httpbin_cookies"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "export-storage-state",
            target["url"],
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"export-storage-state failed:\n{result.stderr}")
    payload = parse_json_output(result)
    require(
        cookie_present(payload.get("cookies", []), target["cookie_name"], target["cookie_value"]),
        "expected cookie was not present in exported storage state",
    )
    require(payload.get("final_url"), "storage-state result is missing final_url")
    return {"final_url": payload["final_url"]}


def test_debug_page_challenge(cli_prefix: list[str], targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["nopecha_cloudflare"]
    result = run_command(
        [
            *cli_prefix,
            "inspect",
            "debug-page",
            target["url"],
            "--format",
            "json",
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"debug-page on challenge target failed:\n{result.stderr}")
    payload = parse_json_output(result)
    title = payload.get("title") or ""
    challenge = payload.get("challenge_detected")
    require(
        target["expected_title_contains"] in title or challenge is not None,
        "challenge target did not report either the expected title or a detected challenge",
    )
    return {"title": title, "challenge_detected": challenge}


def test_graphql_control(targets: dict[str, Any], timeout: int) -> dict[str, Any]:
    target = targets["countries_graphql"]
    result = run_command(
        [
            "curl",
            "-sS",
            target["url"],
            "-H",
            "content-type: application/json",
            "--data",
            '{"query":"{ countries { code name } }"}',
        ],
        timeout=timeout,
    )
    require(result.returncode == 0, f"curl GraphQL control failed:\n{result.stderr}")
    payload = parse_json_output(result)
    countries = payload.get("data", {}).get("countries", [])
    require(bool(countries), "GraphQL control returned no countries")
    return {"count": len(countries)}


TESTS: dict[str, Callable[..., dict[str, Any]]] = {
    "static_extract_baseline": test_static_extract,
    "list_page_images": test_list_page_images,
    "fetch_page_image": test_fetch_page_image,
    "run_flow_and_extract": test_run_flow,
    "run_flow_and_extract_with_network": test_run_flow_with_network,
    "extract_app_state_next": test_extract_app_state_next,
    "extract_app_state_nuxt": test_extract_app_state_nuxt,
    "debug_page_ajax": test_debug_page_ajax,
    "observe_network": test_observe_network,
    "discover_endpoints": test_discover_endpoints,
    "export_storage_state": test_export_storage_state,
    "debug_page_challenge": test_debug_page_challenge,
    "graphql_control": test_graphql_control,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live end-to-end Scrapling CLI smoke tests.")
    parser.add_argument("--targets-file", default=str(DEFAULT_TARGETS), help="Path to the live target registry JSON file.")
    parser.add_argument("--cli-bin", default=None, help="Path to the Scrapling CLI executable.")
    parser.add_argument("--python-bin", default=None, help="Python executable to use when resolving the CLI fallback.")
    parser.add_argument("--timeout", type=int, default=180, help="Per-command timeout in seconds.")
    parser.add_argument("--output-dir", default=None, help="Directory for temporary live-smoke outputs.")
    parser.add_argument("--keep-output", action="store_true", help="Keep the output directory instead of deleting it.")
    parser.add_argument("--tests", nargs="*", choices=sorted(TESTS.keys()), help="Subset of smoke tests to run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = load_json(Path(args.targets_file))
    cli_prefix = resolve_cli_prefix(args.cli_bin, args.python_bin)
    selected_tests = args.tests or list(TESTS.keys())

    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="scrapling-live-smoke-"))
        cleanup = not args.keep_output

    failures: list[tuple[str, str]] = []
    for name in selected_tests:
        print(f"[live-smoke] running {name}", flush=True)
        try:
            parameters = inspect.signature(TESTS[name]).parameters
            kwargs: dict[str, Any] = {"targets": targets, "timeout": args.timeout}
            if "cli_prefix" in parameters:
                kwargs["cli_prefix"] = cli_prefix
            if "output_dir" in parameters:
                kwargs["output_dir"] = output_dir
            details = TESTS[name](**kwargs)
        except SmokeFailure as exc:
            failures.append((name, str(exc)))
            print(f"[live-smoke] FAIL {name}: {exc}", file=sys.stderr, flush=True)
            continue
        print(f"[live-smoke] PASS {name}: {json.dumps(details, sort_keys=True)}", flush=True)

    if cleanup and output_dir.exists():
        shutil.rmtree(output_dir)
    else:
        print(f"[live-smoke] outputs kept at {output_dir}")

    if failures:
        print("[live-smoke] failures:", file=sys.stderr)
        for name, message in failures:
            print(f" - {name}: {message}", file=sys.stderr)
        return 1

    print(f"[live-smoke] all {len(selected_tests)} selected tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
