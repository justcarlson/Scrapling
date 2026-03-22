from __future__ import annotations

import gc
import hashlib
import http.server
import json
import logging
import math
import multiprocessing
import os
import platform
import signal
from difflib import SequenceMatcher
from functools import lru_cache
from queue import Empty
import statistics
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns, process_time_ns
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from scrapling import Selector, __version__
from scrapling.core.utils import set_logger, reset_logger

BENCHMARK_REPORT_VERSION = 2
BASELINE_SCHEMA_VERSION = 3
DEFAULT_REPETITIONS = 5
DEFAULT_WARMUPS = 1
DEFAULT_TIMEOUT_MS = 30_000

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_ROOT = REPO_ROOT / "benchmarks"
SCHEMA_ROOT = BENCHMARKS_ROOT / "schema"
SUITES_ROOT = BENCHMARKS_ROOT / "suites"
WORKLOADS_ROOT = BENCHMARKS_ROOT / "workloads"

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - exercised in subprocess test
    resource = None

try:  # pragma: no cover - exercised when installed
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - fallback exercised in tests only if dependency is absent
    Draft202012Validator = None


@dataclass(frozen=True)
class SuiteDefaults:
    repetitions: int = DEFAULT_REPETITIONS
    warmups: int = DEFAULT_WARMUPS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    seed: int | None = None


@dataclass(frozen=True)
class SuiteWorkload:
    id: str
    weight: float
    required: bool = True
    spec_ref: str | None = None


@dataclass(frozen=True)
class SuiteSpec:
    name: str
    version: int
    workloads: tuple[SuiteWorkload, ...]
    defaults: SuiteDefaults


@dataclass(frozen=True)
class WorkloadSpec:
    id: str
    version: int
    kind: str
    fixture: str
    fixtures: tuple[str, ...]
    expected: str
    ready_condition: Mapping[str, Any]
    extract_spec: Mapping[str, Any]
    correctness: Mapping[str, Any]
    cost_weights: Mapping[str, float]


@dataclass(frozen=True)
class WorkloadMetrics:
    wall_ms: float
    cpu_ms: float
    peak_rss_mb: float
    load_ms: float
    extract_ms: float
    work_units: int


@dataclass(frozen=True)
class CorrectnessSummary:
    passed: bool
    item_count: int
    expected_item_count: int
    required_fields_match: bool
    semantic_match: float
    non_empty: bool
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class StabilitySummary:
    mean_ms: float
    median_ms: float
    p95_ms: float
    cv: float
    success_rate: float
    consistent_output: bool
    penalty: float


@dataclass(frozen=True)
class WorkloadReport:
    id: str
    required: bool
    weight: float
    passed: bool
    failure_kind: str | None
    score: float | None
    effective_cost: float
    baseline_effective_cost: float | None
    metrics: WorkloadMetrics
    correctness: CorrectnessSummary
    stability: StabilitySummary
    artifacts: Mapping[str, str]


def _report_suite_score(report: Mapping[str, Any]) -> float | None:
    value = report.get("srps")
    if value is None:
        return None
    return float(value)


def _workload_report_from_dict(payload: Mapping[str, Any]) -> WorkloadReport:
    return WorkloadReport(
        id=payload["id"],
        required=payload["required"],
        weight=payload["weight"],
        passed=payload["passed"],
        failure_kind=payload.get("failure_kind"),
        score=payload["score"],
        effective_cost=payload["effective_cost"],
        baseline_effective_cost=payload["baseline_effective_cost"],
        metrics=WorkloadMetrics(**payload["metrics"]),
        correctness=CorrectnessSummary(
            passed=payload["correctness"]["passed"],
            item_count=payload["correctness"]["item_count"],
            expected_item_count=payload["correctness"]["expected_item_count"],
            required_fields_match=payload["correctness"]["required_fields_match"],
            semantic_match=payload["correctness"]["semantic_match"],
            non_empty=payload["correctness"]["non_empty"],
            messages=tuple(payload["correctness"]["messages"]),
        ),
        stability=StabilitySummary(
            mean_ms=payload["stability"]["mean_ms"],
            median_ms=payload["stability"]["median_ms"],
            p95_ms=payload["stability"]["p95_ms"],
            cv=payload["stability"]["cv"],
            success_rate=payload["stability"].get("success_rate", 1.0),
            consistent_output=payload["stability"].get("consistent_output", True),
            penalty=payload["stability"]["penalty"],
        ),
        artifacts=payload["artifacts"],
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _schema_payload(name: str) -> dict[str, Any]:
    return _load_json(SCHEMA_ROOT / name)


def _matches_schema_type(expected: str, value: Any) -> bool:
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    python_type = type_map.get(expected)
    if python_type is None:
        return True
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, python_type)


def _validate_schema_fallback(
    payload: Any,
    schema: Mapping[str, Any],
    *,
    label: str,
    path: str = "$",
) -> None:
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_matches_schema_type(candidate, payload) for candidate in expected_type):
            raise ValueError(f"Invalid {label}: {path} must be one of {expected_type}")
    elif isinstance(expected_type, str) and not _matches_schema_type(expected_type, payload):
        raise ValueError(f"Invalid {label}: {path} must be of type {expected_type}")

    if not isinstance(payload, Mapping):
        if isinstance(payload, list) and "items" in schema:
            for index, item in enumerate(payload):
                _validate_schema_fallback(
                    item,
                    schema["items"],
                    label=label,
                    path=f"{path}[{index}]",
                )
        return

    required = schema.get("required", [])
    for key in required:
        if key not in payload:
            raise ValueError(f"Invalid {label}: missing required property '{key}'")

    properties = schema.get("properties", {})
    additional_properties = schema.get("additionalProperties")
    for key, value in payload.items():
        if key in properties:
            _validate_schema_fallback(
                value,
                properties[key],
                label=label,
                path=f"{path}.{key}",
            )
        elif isinstance(additional_properties, Mapping):
            _validate_schema_fallback(
                value,
                additional_properties,
                label=label,
                path=f"{path}.{key}",
            )


def _validate_schema(payload: Mapping[str, Any], schema_name: str, *, label: str) -> None:
    schema = _schema_payload(schema_name)
    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
        if errors:
            message = errors[0].message
            raise ValueError(f"Invalid {label}: {message}")
        return
    _validate_schema_fallback(payload, schema, label=label)


def _resolve_json_path(path_or_name: str | Path, default_root: Path) -> Path:
    candidate = Path(path_or_name)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    if candidate.suffix:
        resolved = (REPO_ROOT / candidate).resolve()
        if resolved.exists():
            return resolved
    default_candidate = default_root / f"{candidate.stem}.json"
    if default_candidate.exists():
        return default_candidate.resolve()
    raise ValueError(f"Unable to resolve benchmark path: {path_or_name}")


def _resolve_relative(path_value: str, base_path: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    repo_candidate = (REPO_ROOT / path).resolve()
    if repo_candidate.exists():
        return repo_candidate
    return (base_path.parent / path).resolve()


def _resolve_suite_workload_ref(path_value: str, suite_path: Path) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    if path.exists():
        return str(path.resolve())

    repo_candidate = (REPO_ROOT / path).resolve()
    if repo_candidate.exists():
        return str(repo_candidate)

    if path.suffix or len(path.parts) > 1:
        return str((suite_path.parent / path).resolve())
    return path_value


def list_suite_names() -> list[str]:
    if not SUITES_ROOT.exists():
        return []
    return sorted(path.stem for path in SUITES_ROOT.glob("*.json"))


def list_workload_names() -> list[str]:
    if not WORKLOADS_ROOT.exists():
        return []
    return sorted(path.stem for path in WORKLOADS_ROOT.glob("*.json"))


def load_workload_spec(path_or_name: str | Path) -> WorkloadSpec:
    spec_path = _resolve_json_path(path_or_name, WORKLOADS_ROOT)
    payload = _load_json(spec_path)
    _validate_schema(payload, "workload.schema.json", label="benchmark workload spec")
    return WorkloadSpec(
        id=payload["id"],
        version=int(payload["version"]),
        kind=payload["kind"],
        fixture=str(_resolve_relative(payload["fixture"], spec_path)),
        fixtures=tuple(
            str(_resolve_relative(path_value, spec_path))
            for path_value in payload.get("fixtures", [])
        ),
        expected=str(_resolve_relative(payload["expected"], spec_path)),
        ready_condition=payload.get("ready_condition", {"type": "immediate"}),
        extract_spec=payload["extract_spec"],
        correctness=payload["correctness"],
        cost_weights=payload["cost_weights"],
    )


def load_suite_spec(
    suite_name_or_path: str | Path = "dev",
    workload_filter: Sequence[str] | None = None,
) -> SuiteSpec:
    suite_path = _resolve_json_path(suite_name_or_path, SUITES_ROOT)
    payload = _load_json(suite_path)
    _validate_schema(payload, "suite.schema.json", label="benchmark suite spec")
    workloads: list[SuiteWorkload] = []
    for entry in payload["workloads"]:
        spec_ref = _resolve_suite_workload_ref(entry["id"], suite_path)
        workload_spec = load_workload_spec(spec_ref)
        workloads.append(
            SuiteWorkload(
                id=workload_spec.id,
                weight=float(entry["weight"]),
                required=bool(entry.get("required", True)),
                spec_ref=spec_ref,
            )
        )
    defaults = payload.get("defaults", {})
    spec = SuiteSpec(
        name=payload["name"],
        version=int(payload["version"]),
        workloads=tuple(workloads),
        defaults=SuiteDefaults(
            repetitions=int(defaults.get("repetitions", DEFAULT_REPETITIONS)),
            warmups=int(defaults.get("warmups", DEFAULT_WARMUPS)),
            timeout_ms=int(defaults.get("timeout_ms", DEFAULT_TIMEOUT_MS)),
            seed=defaults.get("seed"),
        ),
    )
    if workload_filter is None:
        return spec

    filtered = [entry for entry in spec.workloads if entry.id in set(workload_filter)]
    missing = sorted(set(workload_filter) - {entry.id for entry in spec.workloads})
    if missing:
        raise ValueError(
            "Unknown benchmark workload(s): "
            + ", ".join(missing)
            + ". Available workloads: "
            + ", ".join(entry.id for entry in spec.workloads)
        )
    return SuiteSpec(
        name=spec.name,
        version=spec.version,
        workloads=tuple(filtered),
        defaults=spec.defaults,
    )


def environment_metadata() -> dict[str, str]:
    return {
        "scrapling_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    return value


def _sha256_payload(payload: Any) -> str:
    serialized = json.dumps(_normalize(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def workload_spec_fingerprint(workload: WorkloadSpec) -> str:
    payload = {
        "id": workload.id,
        "version": workload.version,
        "kind": workload.kind,
        "fixture_hash": _sha256_file(workload.fixture),
        "fixture_hashes": [_sha256_file(path) for path in workload.fixtures],
        "expected_hash": _sha256_file(workload.expected),
        "ready_condition": workload.ready_condition,
        "extract_spec": workload.extract_spec,
        "correctness": workload.correctness,
        "cost_weights": workload.cost_weights,
    }
    return _sha256_payload(payload)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if len(values) == 1:
        return values[0]

    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _current_peak_rss_mb() -> float:
    if resource is None:
        return 0.0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / 1024, 4)


def _fixture_server_root(fixture_paths: Sequence[str]) -> Path:
    resolved = [Path(path).resolve() for path in fixture_paths]
    if all(path.is_relative_to(REPO_ROOT) for path in resolved):
        return REPO_ROOT
    if len(resolved) == 1:
        return resolved[0].parent
    return Path(os.path.commonpath([str(path) for path in resolved]))


def _benchmark_context(*, prefer_fork: bool = False):
    if prefer_fork and "fork" in multiprocessing.get_all_start_methods():
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context("spawn")


def _selector_get(node: Selector, selector: str) -> str | None:
    value = node.css(selector).get()
    if value is None:
        return None
    return str(value).strip()


class _SilentStaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return


class LocalFixtureServer:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "LocalFixtureServer":
        handler = lambda *args, **kwargs: _SilentStaticHandler(
            *args,
            directory=str(self.root),
            **kwargs,
        )
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("LocalFixtureServer not started")
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def url_for(self, path: str | Path) -> str:
        relative = Path(path).resolve().relative_to(self.root)
        return f"{self.base_url}/{quote(relative.as_posix())}"


def _quiet_logger() -> logging.Logger:
    logger = logging.getLogger("scrapling.benchmark.quiet")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)
    return logger


def _extract_record_css(selector: Selector, extract_spec: Mapping[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for node in selector.css(extract_spec["item_selector"]):
        item: dict[str, Any] = {}
        for field_name, field_selector in extract_spec["fields"].items():
            item[field_name] = _selector_get(node, field_selector)
        items.append(item)
    return {"items": items}


def _extract_text_similarity(selector: Selector, extract_spec: Mapping[str, Any]) -> dict[str, Any]:
    target_node = selector.find_by_text(
        extract_spec["target_text"],
        first_match=True,
        clean_match=False,
    )
    anchor = target_node.parent if target_node.parent is not None else target_node
    ignore_attributes = tuple(extract_spec.get("ignore_attributes", []))
    similar = anchor.find_similar(
        similarity_threshold=float(extract_spec.get("similarity_threshold", 1.0)),
        ignore_attributes=ignore_attributes,
        match_text=bool(extract_spec.get("match_text", False)),
    )

    items: list[dict[str, Any]] = []
    if extract_spec.get("include_anchor", True):
        items.append({"title": _selector_get(anchor, extract_spec["text_selector"])})
    for node in similar:
        items.append({"title": _selector_get(node, extract_spec["text_selector"])})
    return {"items": items}


def _extract_browser_session_values(selector: Selector, extract_spec: Mapping[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for field_name, field_selector in extract_spec["fields"].items():
        item[field_name] = _selector_get(selector, field_selector)
    return {"items": [item]}


def _run_browser_extraction(
    workload: WorkloadSpec,
    fixture_paths: Sequence[str],
) -> tuple[dict[str, Any], float, float, Sequence[str]]:
    from scrapling import DynamicFetcher

    with LocalFixtureServer(_fixture_server_root(fixture_paths)) as server:
        start_url = server.url_for(fixture_paths[0])
        load_start = perf_counter_ns()
        token = set_logger(_quiet_logger())
        try:
            response = DynamicFetcher.fetch(
                start_url,
                headless=True,
                google_search=False,
                wait_selector=workload.ready_condition.get("selector"),
                wait_selector_state=workload.ready_condition.get("state", "attached"),
                timeout=int(workload.ready_condition.get("timeout_ms", DEFAULT_TIMEOUT_MS)),
                network_idle=bool(workload.ready_condition.get("network_idle", False)),
                wait=int(workload.ready_condition.get("wait_ms", 0)),
            )
        finally:
            reset_logger(token)
        load_ms = (perf_counter_ns() - load_start) / 1_000_000

        extract_start = perf_counter_ns()
        strategy = workload.extract_spec["strategy"]
        if strategy == "record_css":
            output = _extract_record_css(response, workload.extract_spec)
        elif strategy == "browser_session_values":
            output = _extract_browser_session_values(response, workload.extract_spec)
        else:
            raise ValueError(f"Unsupported browser benchmark extraction strategy: {strategy}")
        extract_ms = (perf_counter_ns() - extract_start) / 1_000_000
        rendered_text = str(response.get_all_text(separator=" ", strip=True))
        return output, load_ms, extract_ms, (rendered_text,)


def _run_extraction(
    workload: WorkloadSpec,
    fixture_texts: Sequence[str],
    fixture_paths: Sequence[str],
) -> tuple[dict[str, Any], float, float, Sequence[str]]:
    load_start = perf_counter_ns()
    strategy = workload.extract_spec["strategy"]
    if workload.kind == "browser":
        return _run_browser_extraction(workload, fixture_paths)
    if strategy == "record_css":
        selector = Selector(fixture_texts[0], adaptive=False)
        load_ms = (perf_counter_ns() - load_start) / 1_000_000
        extract_start = perf_counter_ns()
        output = _extract_record_css(selector, workload.extract_spec)
        page_texts = (str(selector.get_all_text(separator=" ", strip=True)),)
    elif strategy == "multi_fixture_record_css":
        selectors = [Selector(text, adaptive=False) for text in fixture_texts]
        load_ms = (perf_counter_ns() - load_start) / 1_000_000
        extract_start = perf_counter_ns()
        items: list[dict[str, Any]] = []
        for selector in selectors:
            items.extend(_extract_record_css(selector, workload.extract_spec)["items"])
        output = {"items": items}
        page_texts = tuple(str(selector.get_all_text(separator=" ", strip=True)) for selector in selectors)
    elif strategy == "text_similarity":
        selector = Selector(fixture_texts[0], adaptive=False)
        load_ms = (perf_counter_ns() - load_start) / 1_000_000
        extract_start = perf_counter_ns()
        output = _extract_text_similarity(selector, workload.extract_spec)
        page_texts = (str(selector.get_all_text(separator=" ", strip=True)),)
    elif strategy == "session_values":
        selectors = [Selector(text, adaptive=False) for text in fixture_texts]
        load_ms = (perf_counter_ns() - load_start) / 1_000_000
        extract_start = perf_counter_ns()
        item: dict[str, Any] = {}
        for step in workload.extract_spec["steps"]:
            selector = selectors[int(step["fixture_index"])]
            for field_name, field_selector in step["fields"].items():
                item[field_name] = _selector_get(selector, field_selector)
        output = {"items": [item]}
        page_texts = tuple(str(selector.get_all_text(separator=" ", strip=True)) for selector in selectors)
    else:
        raise ValueError(f"Unsupported benchmark extraction strategy: {strategy}")
    extract_ms = (perf_counter_ns() - extract_start) / 1_000_000
    return output, load_ms, extract_ms, page_texts


def _diff_items(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=False)):
        if _normalize(expected_item) != _normalize(actual_item):
            mismatches.append(
                {
                    "index": index,
                    "expected": _normalize(expected_item),
                    "actual": _normalize(actual_item),
                }
            )
    return {
        "expected_item_count": len(expected),
        "actual_item_count": len(actual),
        "mismatches": mismatches,
    }


def _semantic_field_score(expected_value: Any, actual_value: Any) -> float:
    left = _normalize(expected_value)
    right = _normalize(actual_value)
    if left == right:
        return 1.0
    if isinstance(left, str) and isinstance(right, str):
        return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
    return 0.0


def _semantic_match_score(expected_items: Sequence[Mapping[str, Any]], actual_items: Sequence[Mapping[str, Any]]) -> float:
    if not expected_items and not actual_items:
        return 1.0
    if not expected_items or not actual_items:
        return 0.0

    compared = 0
    total_score = 0.0
    for expected_item, actual_item in zip(expected_items, actual_items, strict=False):
        fields = sorted(set(expected_item) | set(actual_item))
        if not fields:
            continue
        compared += 1
        total_score += statistics.mean(
            _semantic_field_score(expected_item.get(field), actual_item.get(field))
            for field in fields
        )

    if compared == 0:
        return 0.0
    count_penalty = min(len(expected_items), len(actual_items)) / max(len(expected_items), len(actual_items))
    return round((total_score / compared) * count_penalty, 4)


def _failed_workload_report(
    workload_id: str,
    *,
    weight: float,
    required: bool,
    failure_kind: str,
    messages: Sequence[str],
    artifacts_dir: str | Path | None = None,
    baseline_entry: Mapping[str, Any] | None = None,
    expected_item_count: int = 0,
) -> WorkloadReport:
    baseline_effective_cost = None
    score = None
    if baseline_entry and float(baseline_entry.get("effective_cost", 0.0)) > 0:
        baseline_effective_cost = float(baseline_entry["effective_cost"])
        score = 0.0

    artifact_targets = _artifact_paths(Path(artifacts_dir) if artifacts_dir else None, workload_id)
    if artifact_targets:
        empty_output = {"items": []}
        artifact_targets["raw_output"].write_text(
            json.dumps(empty_output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_targets["normalized_output"].write_text(
            json.dumps(empty_output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_targets["diff"].write_text(
            json.dumps({"error": list(messages)}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_targets["metrics_trace"].write_text(
            json.dumps({"error": list(messages), "repetitions": []}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return WorkloadReport(
        id=workload_id,
        required=required,
        weight=weight,
        passed=False,
        failure_kind=failure_kind,
        score=score,
        effective_cost=0.0,
        baseline_effective_cost=baseline_effective_cost,
        metrics=WorkloadMetrics(
            wall_ms=0.0,
            cpu_ms=0.0,
            peak_rss_mb=0.0,
            load_ms=0.0,
            extract_ms=0.0,
            work_units=0,
        ),
        correctness=CorrectnessSummary(
            passed=False,
            item_count=0,
            expected_item_count=expected_item_count,
            required_fields_match=False,
            semantic_match=0.0,
            non_empty=False,
            messages=tuple(messages),
        ),
        stability=StabilitySummary(
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            cv=0.0,
            success_rate=0.0,
            consistent_output=False,
            penalty=0.0,
        ),
        artifacts={name: str(path) for name, path in artifact_targets.items()},
    )


def _evaluate_correctness(
    workload: WorkloadSpec,
    actual_output: Mapping[str, Any],
    expected_output: Mapping[str, Any],
    page_texts: Sequence[str],
) -> tuple[CorrectnessSummary, dict[str, Any]]:
    actual_items = list(actual_output.get("items", []))
    expected_items = list(expected_output.get("items", []))
    required_fields = tuple(workload.correctness.get("required_fields", []))

    required_fields_match = all(
        all(item.get(field) not in (None, "") for field in required_fields)
        for item in actual_items
    )
    non_empty = bool(actual_items) or not expected_items
    item_count_match = len(actual_items) == len(expected_items)
    exact_match = _normalize(actual_items) == _normalize(expected_items)
    semantic_match = _semantic_match_score(expected_items, actual_items)
    page_text = "\n".join(page_texts)
    forbidden_page_texts = tuple(workload.correctness.get("forbidden_page_texts", []))
    required_page_texts = tuple(workload.correctness.get("required_page_texts", []))
    forbidden_page_texts_match = all(text not in page_text for text in forbidden_page_texts)
    required_page_texts_match = all(text in page_text for text in required_page_texts)

    messages: list[str] = []
    if not non_empty:
        messages.append("output is empty")
    if not required_fields_match:
        messages.append("required fields missing")
    if not item_count_match:
        messages.append("item count mismatch")
    if semantic_match < float(workload.correctness.get("semantic_match_threshold", 1.0)):
        messages.append("semantic match below threshold")
    if workload.correctness.get("comparison", "exact") == "exact" and not exact_match:
        messages.append("normalized output mismatch")
    if not forbidden_page_texts_match:
        messages.append("forbidden page text detected")
    if not required_page_texts_match:
        messages.append("required page text missing")

    passed = non_empty and required_fields_match and item_count_match
    if workload.correctness.get("comparison", "exact") == "exact":
        passed = passed and exact_match
    passed = passed and semantic_match >= float(workload.correctness.get("semantic_match_threshold", 1.0))
    passed = passed and forbidden_page_texts_match and required_page_texts_match

    summary = CorrectnessSummary(
        passed=passed,
        item_count=len(actual_items),
        expected_item_count=len(expected_items),
        required_fields_match=required_fields_match,
        semantic_match=round(semantic_match, 4),
        non_empty=non_empty,
        messages=tuple(messages),
    )
    return summary, _diff_items(expected_items, actual_items)


def _stability_penalty(
    sample_ms: list[float],
    *,
    success_rate: float = 1.0,
    consistent_output: bool = True,
) -> StabilitySummary:
    mean_ms = statistics.mean(sample_ms)
    median_ms = statistics.median(sample_ms)
    p95_ms = _percentile(sample_ms, 0.95)
    cv = statistics.pstdev(sample_ms) / mean_ms if len(sample_ms) > 1 and mean_ms > 0 else 0.0
    timing_penalty = 1.0 / (1.0 + min(cv, 1.0))
    consistency_penalty = 1.0 if consistent_output else 0.5
    penalty = timing_penalty * success_rate * consistency_penalty
    return StabilitySummary(
        mean_ms=round(mean_ms, 4),
        median_ms=round(median_ms, 4),
        p95_ms=round(p95_ms, 4),
        cv=round(cv, 4),
        success_rate=round(success_rate, 4),
        consistent_output=consistent_output,
        penalty=round(penalty, 4),
    )


def _effective_cost(metrics: WorkloadMetrics, cost_weights: Mapping[str, float]) -> float:
    return round(
        metrics.wall_ms * float(cost_weights.get("wall_ms", 0.0))
        + metrics.cpu_ms * float(cost_weights.get("cpu_ms", 0.0))
        + metrics.peak_rss_mb * float(cost_weights.get("peak_rss_mb", 0.0))
        + metrics.load_ms * float(cost_weights.get("load_ms", 0.0))
        + metrics.extract_ms * float(cost_weights.get("extract_ms", 0.0)),
        4,
    )


def _artifact_paths(base_dir: Path | None, workload_id: str) -> dict[str, Path]:
    if base_dir is None:
        return {}
    workload_dir = base_dir / workload_id
    workload_dir.mkdir(parents=True, exist_ok=True)
    return {
        "raw_output": workload_dir / "output.json",
        "normalized_output": workload_dir / "normalized_output.json",
        "diff": workload_dir / "diff.json",
        "metrics_trace": workload_dir / "metrics_trace.json",
    }


def _evaluate_workload_in_process(
    workload: WorkloadSpec,
    *,
    weight: float,
    required: bool,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    baseline_entry: Mapping[str, Any] | None = None,
    artifacts_dir: str | Path | None = None,
) -> WorkloadReport:
    if repetitions <= 0:
        raise ValueError("repetitions must be greater than zero")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")

    fixture_paths = workload.fixtures or (workload.fixture,)
    fixture_texts = [
        Path(path_value).read_text(encoding="utf-8")
        for path_value in fixture_paths
    ]
    expected_output = _load_json(Path(workload.expected))

    _run_warmups_out_of_process(workload, warmups=warmups)

    wall_samples: list[float] = []
    cpu_samples: list[float] = []
    load_samples: list[float] = []
    extract_samples: list[float] = []
    rss_samples: list[float] = []
    actual_output: dict[str, Any] = {}
    page_texts: Sequence[str] = ()
    diff_payload: dict[str, Any] = {}
    normalized_outputs: list[Any] = []
    correctness_runs: list[CorrectnessSummary] = []
    metric_traces: list[dict[str, Any]] = []

    for _ in range(repetitions):
        gc.collect()
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            wall_start = perf_counter_ns()
            cpu_start = process_time_ns()
            actual_output, load_ms, extract_ms, page_texts = _run_extraction(
                workload,
                fixture_texts,
                fixture_paths,
            )
            cpu_ns = process_time_ns() - cpu_start
            wall_ns = perf_counter_ns() - wall_start
        finally:
            if gc_was_enabled:
                gc.enable()

        wall_samples.append(wall_ns / 1_000_000)
        cpu_samples.append(cpu_ns / 1_000_000)
        load_samples.append(load_ms)
        extract_samples.append(extract_ms)
        rss_mb = _current_peak_rss_mb()
        rss_samples.append(rss_mb)
        correctness, diff_payload = _evaluate_correctness(
            workload,
            actual_output,
            expected_output,
            page_texts,
        )
        correctness_runs.append(correctness)
        normalized_output = _normalize(actual_output)
        normalized_outputs.append(normalized_output)
        metric_traces.append(
            {
                "wall_ms": round(wall_ns / 1_000_000, 4),
                "cpu_ms": round(cpu_ns / 1_000_000, 4),
                "load_ms": round(load_ms, 4),
                "extract_ms": round(extract_ms, 4),
                "peak_rss_mb": round(rss_mb, 4),
                "correctness_passed": correctness.passed,
                "semantic_match": correctness.semantic_match,
                "messages": list(correctness.messages),
                "normalized_output_hash": _sha256_payload(normalized_output),
            }
        )

    all_runs_passed = all(run.passed for run in correctness_runs)
    consistent_output = all(
        output == normalized_outputs[0] for output in normalized_outputs[1:]
    )
    aggregate_messages: list[str] = []
    seen_messages: set[str] = set()
    for run in correctness_runs:
        for message in run.messages:
            if message not in seen_messages:
                aggregate_messages.append(message)
                seen_messages.add(message)
    failed_repetitions = sum(not run.passed for run in correctness_runs)
    if failed_repetitions:
        aggregate_messages.append(
            f"correctness failed in {failed_repetitions}/{repetitions} repetitions"
        )
    if not consistent_output:
        aggregate_messages.append("output changed across repetitions")

    correctness = CorrectnessSummary(
        passed=all_runs_passed and consistent_output,
        item_count=correctness_runs[-1].item_count,
        expected_item_count=correctness_runs[-1].expected_item_count,
        required_fields_match=all(run.required_fields_match for run in correctness_runs),
        semantic_match=round(min(run.semantic_match for run in correctness_runs), 4),
        non_empty=all(run.non_empty for run in correctness_runs),
        messages=tuple(aggregate_messages),
    )
    stability = _stability_penalty(
        wall_samples,
        success_rate=(repetitions - failed_repetitions) / repetitions,
        consistent_output=consistent_output,
    )
    metrics = WorkloadMetrics(
        wall_ms=round(statistics.mean(wall_samples), 4),
        cpu_ms=round(statistics.mean(cpu_samples), 4),
        peak_rss_mb=round(max(rss_samples), 4),
        load_ms=round(statistics.mean(load_samples), 4),
        extract_ms=round(statistics.mean(extract_samples), 4),
        work_units=len(actual_output.get("items", [])),
    )
    effective_cost = _effective_cost(metrics, workload.cost_weights)

    baseline_effective_cost: float | None = None
    score: float | None = None
    if baseline_entry:
        baseline_effective_cost = float(baseline_entry["effective_cost"])
        if baseline_effective_cost > 0 and correctness.passed and effective_cost > 0:
            score = round(
                100 * (baseline_effective_cost / effective_cost) * stability.penalty,
                2,
            )

    artifact_targets = _artifact_paths(Path(artifacts_dir) if artifacts_dir else None, workload.id)
    if artifact_targets:
        artifact_targets["raw_output"].write_text(
            json.dumps(actual_output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_targets["normalized_output"].write_text(
            json.dumps(_normalize(actual_output), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_targets["diff"].write_text(
            json.dumps(diff_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_targets["metrics_trace"].write_text(
            json.dumps({"repetitions": metric_traces}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return WorkloadReport(
        id=workload.id,
        required=required,
        weight=weight,
        passed=correctness.passed,
        failure_kind=None if correctness.passed else "correctness",
        score=score,
        effective_cost=effective_cost,
        baseline_effective_cost=baseline_effective_cost,
        metrics=metrics,
        correctness=correctness,
        stability=stability,
        artifacts={name: str(path) for name, path in artifact_targets.items()},
    )


def _workload_worker(
    queue: multiprocessing.queues.Queue,
    workload_payload: dict[str, Any],
    *,
    weight: float,
    required: bool,
    repetitions: int,
    warmups: int,
    baseline_entry: Mapping[str, Any] | None,
    artifacts_dir: str | Path | None,
) -> None:
    try:
        report = _evaluate_workload_in_process(
            WorkloadSpec(**workload_payload),
            weight=weight,
            required=required,
            repetitions=repetitions,
            warmups=warmups,
            baseline_entry=baseline_entry,
            artifacts_dir=artifacts_dir,
        )
        queue.put({"ok": True, "report": asdict(report)})
    except Exception as exc:  # pragma: no cover - exercised through parent path
        queue.put({"ok": False, "error": repr(exc)})


def _warmup_worker(
    queue: multiprocessing.queues.Queue,
    workload_payload: dict[str, Any],
    *,
    warmups: int,
) -> None:
    try:
        workload = WorkloadSpec(**workload_payload)
        fixture_paths = workload.fixtures or (workload.fixture,)
        fixture_texts = [
            Path(path_value).read_text(encoding="utf-8")
            for path_value in fixture_paths
        ]
        for _ in range(warmups):
            _run_extraction(workload, fixture_texts, fixture_paths)
        queue.put({"ok": True})
    except Exception as exc:  # pragma: no cover - exercised through parent path
        queue.put({"ok": False, "error": repr(exc)})


def _run_warmups_out_of_process(workload: WorkloadSpec, *, warmups: int) -> None:
    if warmups <= 0:
        return

    ctx = _benchmark_context(prefer_fork=True)
    queue = ctx.Queue()
    process = ctx.Process(
        target=_warmup_worker,
        args=(queue, asdict(workload)),
        kwargs={"warmups": warmups},
    )
    process.start()
    process.join()
    if process.exitcode != 0:
        raise RuntimeError(f"benchmark warmup worker failed with exit code {process.exitcode}")
    try:
        payload = queue.get(timeout=0.1)
    except Empty as exc:
        raise RuntimeError("benchmark warmup worker exited without producing a result") from exc
    if not payload["ok"]:
        raise RuntimeError(payload["error"])


def _run_in_process_with_timeout(
    timeout_ms: int | None,
    func,
    *args: Any,
    **kwargs: Any,
) -> WorkloadReport:
    if timeout_ms is None:
        return func(*args, **kwargs)
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("timeout_ms in in-process benchmark mode requires the main thread")
    if not hasattr(signal, "setitimer") or not hasattr(signal, "SIGALRM"):
        raise RuntimeError("timeout_ms in in-process benchmark mode is not supported on this platform")

    def _handle_alarm(signum, frame) -> None:  # pragma: no cover - signal handler
        raise TimeoutError(f"workload timed out after {timeout_ms} ms")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_ms / 1000)
    try:
        return func(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _compatible_baseline_entry(
    workload: WorkloadSpec,
    baseline_entry: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if baseline_entry is None:
        return None
    if int(baseline_entry.get("workload_version", workload.version)) != workload.version:
        return None
    fingerprint = baseline_entry.get("spec_fingerprint")
    if fingerprint is None:
        return None
    if fingerprint != workload_spec_fingerprint(workload):
        return None
    return baseline_entry


def evaluate_workload(
    workload: WorkloadSpec,
    *,
    weight: float,
    required: bool,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    baseline_entry: Mapping[str, Any] | None = None,
    artifacts_dir: str | Path | None = None,
    timeout_ms: int | None = DEFAULT_TIMEOUT_MS,
    isolate_process: bool = True,
) -> WorkloadReport:
    baseline_entry = _compatible_baseline_entry(workload, baseline_entry)
    if not isolate_process:
        try:
            return _run_in_process_with_timeout(
                timeout_ms,
                _evaluate_workload_in_process,
                workload,
                weight=weight,
                required=required,
                repetitions=repetitions,
                warmups=warmups,
                baseline_entry=baseline_entry,
                artifacts_dir=artifacts_dir,
            )
        except TimeoutError as exc:
            return _failed_workload_report(
                workload.id,
                weight=weight,
                required=required,
                failure_kind="timeout",
                messages=(str(exc),),
                artifacts_dir=artifacts_dir,
                baseline_entry=baseline_entry,
            )
        except Exception as exc:
            return _failed_workload_report(
                workload.id,
                weight=weight,
                required=required,
                failure_kind="worker_error",
                messages=(repr(exc),),
                artifacts_dir=artifacts_dir,
                baseline_entry=baseline_entry,
            )

    ctx = _benchmark_context()
    queue = ctx.Queue()
    process = ctx.Process(
        target=_workload_worker,
        args=(queue, asdict(workload)),
        kwargs={
            "weight": weight,
            "required": required,
            "repetitions": repetitions,
            "warmups": warmups,
            "baseline_entry": baseline_entry,
            "artifacts_dir": artifacts_dir,
        },
    )
    process.start()
    process.join(timeout=None if timeout_ms is None else timeout_ms / 1000)
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        return _failed_workload_report(
            workload.id,
            weight=weight,
            required=required,
            failure_kind="timeout",
            messages=(f"workload timed out after {timeout_ms} ms",),
            artifacts_dir=artifacts_dir,
            baseline_entry=baseline_entry,
        )
    if process.exitcode != 0:
        return _failed_workload_report(
            workload.id,
            weight=weight,
            required=required,
            failure_kind="worker_exit",
            messages=(f"benchmark worker failed with exit code {process.exitcode}",),
            artifacts_dir=artifacts_dir,
            baseline_entry=baseline_entry,
        )
    try:
        payload = queue.get(timeout=0.1)
    except Empty:
        return _failed_workload_report(
            workload.id,
            weight=weight,
            required=required,
            failure_kind="worker_protocol_error",
            messages=("benchmark worker exited without producing a result",),
            artifacts_dir=artifacts_dir,
            baseline_entry=baseline_entry,
        )
    if not payload["ok"]:
        return _failed_workload_report(
            workload.id,
            weight=weight,
            required=required,
            failure_kind="worker_error",
            messages=(payload["error"],),
            artifacts_dir=artifacts_dir,
            baseline_entry=baseline_entry,
        )
    return _workload_report_from_dict(payload["report"])


def _suite_score(
    reports: Iterable[WorkloadReport],
    *,
    correctness_passed: bool,
    generalization_penalty: float = 1.0,
) -> float | None:
    if not correctness_passed:
        return 0.0

    weighted_logs: list[float] = []
    total_weight = 0.0
    weighted_stability_logs: list[float] = []
    for report in reports:
        if not report.passed:
            continue
        if report.baseline_effective_cost is None or report.baseline_effective_cost <= 0:
            continue
        if report.effective_cost <= 0:
            continue
        ratio = report.baseline_effective_cost / report.effective_cost
        weighted_logs.append(math.log(ratio) * report.weight)
        weighted_stability_logs.append(math.log(max(report.stability.penalty, 1e-9)) * report.weight)
        total_weight += report.weight

    if total_weight <= 0:
        return None
    stability_penalty = math.exp(sum(weighted_stability_logs) / total_weight)
    return round(
        100
        * generalization_penalty
        * stability_penalty
        * math.exp(sum(weighted_logs) / total_weight),
        2,
    )


def _suite_stability_penalty(reports: Iterable[WorkloadReport]) -> float | None:
    weighted_logs: list[float] = []
    total_weight = 0.0
    for report in reports:
        if not report.passed or report.baseline_effective_cost is None or report.baseline_effective_cost <= 0:
            continue
        weighted_logs.append(math.log(max(report.stability.penalty, 1e-9)) * report.weight)
        total_weight += report.weight
    if total_weight <= 0:
        return None
    return round(math.exp(sum(weighted_logs) / total_weight), 4)


def load_baseline(path: str | Path) -> dict[str, Any] | None:
    baseline_path = Path(path)
    if not baseline_path.exists():
        return None
    payload = _load_json(baseline_path)
    if int(payload.get("schema_version", -1)) != BASELINE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported baseline schema version: {payload.get('schema_version')}"
        )
    _validate_schema(payload, "baseline.schema.json", label="benchmark baseline")
    return payload


def baseline_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    workloads = {
        workload["id"]: {
            "effective_cost": workload["effective_cost"],
            "weight": workload["weight"],
            "metrics": workload["metrics"],
            "passed": workload["passed"],
            "workload_version": workload["workload_version"],
            "spec_fingerprint": workload["spec_fingerprint"],
        }
        for workload in report["workloads"]
    }
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": report["suite"],
        "suite_version": report["suite_version"],
        "environment": report["environment"],
        "workloads": workloads,
    }


def save_baseline(path: str | Path, report: Mapping[str, Any]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = baseline_payload(report)
    _validate_schema(payload, "baseline.schema.json", label="benchmark baseline")
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _evaluate_suite_core(
    suite_name_or_path: str | Path = "dev",
    *,
    baseline_path: str | Path | None = None,
    output_path: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
    repetitions: int | None = None,
    warmups: int | None = None,
    seed: int | None = None,
    workload_filter: Sequence[str] | None = None,
) -> dict[str, Any]:
    suite = load_suite_spec(suite_name_or_path, workload_filter=workload_filter)
    baseline = load_baseline(baseline_path) if baseline_path else None
    if baseline is not None:
        if baseline.get("suite") != suite.name:
            raise ValueError(
                f"Baseline suite '{baseline.get('suite')}' does not match requested suite '{suite.name}'"
            )
        if int(baseline.get("suite_version", suite.version)) != suite.version:
            raise ValueError(
                "Baseline suite version "
                f"{baseline.get('suite_version')} does not match requested suite version {suite.version}"
            )
    baseline_workloads = baseline["workloads"] if baseline else {}

    reports: list[WorkloadReport] = []
    workload_metadata: list[tuple[WorkloadReport, WorkloadSpec]] = []
    for entry in suite.workloads:
        spec = load_workload_spec(entry.spec_ref or entry.id)
        report = evaluate_workload(
            spec,
            weight=entry.weight,
            required=entry.required,
            repetitions=repetitions or suite.defaults.repetitions,
            warmups=warmups if warmups is not None else suite.defaults.warmups,
            baseline_entry=baseline_workloads.get(spec.id),
            artifacts_dir=artifacts_dir,
            timeout_ms=suite.defaults.timeout_ms,
        )
        reports.append(report)
        workload_metadata.append((report, spec))

    correctness_passed = all(
        report.passed for report in reports if report.required
    )
    generalization_penalty = 1.0
    srps = _suite_score(
        reports,
        correctness_passed=correctness_passed,
        generalization_penalty=generalization_penalty,
    )

    payload = {
        "version": BENCHMARK_REPORT_VERSION,
        "suite": suite.name,
        "suite_version": suite.version,
        "passed": correctness_passed,
        "srps": srps,
        "baseline": {
            "path": str(baseline_path) if baseline_path else None,
            "version": BASELINE_SCHEMA_VERSION if baseline else None,
        },
        "environment": environment_metadata(),
        "summary": {
            "correctness_passed": correctness_passed,
            "generalization_penalty": generalization_penalty,
            "stability_penalty": _suite_stability_penalty(reports),
            "seed": seed if seed is not None else suite.defaults.seed,
        },
        "workloads": [
            {
                **asdict(report),
                "workload_version": spec.version,
                "spec_fingerprint": workload_spec_fingerprint(spec),
            }
            for report, spec in workload_metadata
        ],
    }
    payload = json.loads(json.dumps(payload))
    _validate_schema(payload, "report.schema.json", label="benchmark report")
    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return payload


def evaluate_suite(
    suite_name_or_path: str | Path = "dev",
    *,
    baseline_path: str | Path | None = None,
    output_path: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
    repetitions: int | None = None,
    warmups: int | None = None,
    seed: int | None = None,
    workload_filter: Sequence[str] | None = None,
    holdout_suite_name_or_path: str | Path | None = None,
    holdout_baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    main_report = _evaluate_suite_core(
        suite_name_or_path=suite_name_or_path,
        baseline_path=baseline_path,
        output_path=None,
        artifacts_dir=artifacts_dir,
        repetitions=repetitions,
        warmups=warmups,
        seed=seed,
        workload_filter=workload_filter,
    )

    holdout_report: dict[str, Any] | None = None
    generalization_penalty = 1.0
    overall_passed = bool(main_report["passed"])

    if holdout_suite_name_or_path is not None:
        holdout_artifacts_dir = (
            str(Path(artifacts_dir) / "holdout") if artifacts_dir is not None else None
        )
        holdout_report = _evaluate_suite_core(
            suite_name_or_path=holdout_suite_name_or_path,
            baseline_path=holdout_baseline_path,
            output_path=None,
            artifacts_dir=holdout_artifacts_dir,
            repetitions=repetitions,
            warmups=warmups,
            seed=seed,
            workload_filter=None,
        )
        overall_passed = overall_passed and bool(holdout_report["passed"])
        main_score = _report_suite_score(main_report)
        holdout_score = _report_suite_score(holdout_report)
        if not holdout_report["passed"]:
            generalization_penalty = 0.0
        elif main_score is not None and main_score > 0 and holdout_score is not None:
            generalization_penalty = round(min(1.0, holdout_score / main_score), 4)

    final_srps = main_report["srps"]
    if not overall_passed:
        final_srps = 0.0
    elif final_srps is not None:
        final_srps = round(float(final_srps) * generalization_penalty, 2)

    main_report["passed"] = overall_passed
    main_report["srps"] = final_srps
    main_report["summary"]["correctness_passed"] = overall_passed
    main_report["summary"]["generalization_penalty"] = generalization_penalty
    if holdout_report is not None:
        main_report["summary"]["holdout"] = {
            "suite": holdout_report["suite"],
            "passed": holdout_report["passed"],
            "srps": holdout_report["srps"],
        }

    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(main_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return main_report


def run_benchmark(
    *,
    suite_name_or_path: str | Path = "dev",
    baseline_path: str | Path | None = None,
    output_path: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
    repetitions: int | None = None,
    warmups: int | None = None,
    seed: int | None = None,
    workload_filter: Sequence[str] | None = None,
    holdout_suite_name_or_path: str | Path | None = None,
    holdout_baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    return evaluate_suite(
        suite_name_or_path=suite_name_or_path,
        baseline_path=baseline_path,
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        repetitions=repetitions,
        warmups=warmups,
        seed=seed,
        workload_filter=workload_filter,
        holdout_suite_name_or_path=holdout_suite_name_or_path,
        holdout_baseline_path=holdout_baseline_path,
    )
