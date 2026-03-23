import json
import os
import re
import subprocess
from collections import deque
from pathlib import Path
import sys
import textwrap
import types
from urllib.parse import urljoin
from urllib.request import urlopen

import pytest

import scrapling.benchmarking as benchmarking
from scrapling.benchmarking import (
    BASELINE_SCHEMA_VERSION,
    baseline_payload,
    evaluate_suite,
    evaluate_workload,
    list_suite_names,
    list_workload_names,
    load_baseline,
    load_suite_spec,
    load_workload_spec,
    save_baseline,
)


def test_benchmark_assets_are_discoverable():
    assert "dev" in list_suite_names()
    assert "release" in list_suite_names()
    assert "holdout" in list_suite_names()
    assert "browser" in list_suite_names()
    assert "browser_holdout" in list_suite_names()
    assert "static_extract" in list_workload_names()
    assert "large_dom_extract" in list_workload_names()
    assert "text_similarity" in list_workload_names()
    assert "holdout_static_extract" in list_workload_names()
    assert "crawl_extract" in list_workload_names()
    assert "session_flow_extract" in list_workload_names()
    assert "protected_replay_extract" in list_workload_names()
    assert "browser_dynamic_extract" in list_workload_names()
    assert "browser_session_extract" in list_workload_names()


def test_packaged_assets_work_when_repo_benchmarks_are_unavailable(monkeypatch, tmp_path):
    empty_root = tmp_path / "empty-root"
    empty_root.mkdir()

    monkeypatch.setattr(benchmarking, "REPO_ROOT", empty_root)
    monkeypatch.setattr(benchmarking, "BENCHMARKS_ROOT", empty_root / "benchmarks")
    monkeypatch.setattr(benchmarking, "SCHEMA_ROOT", empty_root / "benchmarks" / "schema")
    monkeypatch.setattr(benchmarking, "SUITES_ROOT", empty_root / "benchmarks" / "suites")
    monkeypatch.setattr(benchmarking, "WORKLOADS_ROOT", empty_root / "benchmarks" / "workloads")
    benchmarking._schema_payload.cache_clear()
    if hasattr(benchmarking, "_packaged_benchmarks_root"):
        benchmarking._packaged_benchmarks_root.cache_clear()

    suite_names = list_suite_names()
    workload_names = list_workload_names()
    suite = load_suite_spec("dev")
    workload = load_workload_spec("static_extract")
    report = evaluate_suite("dev", repetitions=1, warmups=0)

    assert "dev" in suite_names
    assert "static_extract" in workload_names
    assert suite.name == "dev"
    assert workload.id == "static_extract"
    assert Path(workload.fixture).exists()
    assert Path(workload.expected).exists()
    assert report["passed"] is True


def test_repo_checkout_assets_win_over_packaged_assets(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_benchmarks = repo_root / "benchmarks"
    packaged_root = tmp_path / "packaged"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.0'\n", encoding="utf-8")

    for root in (repo_benchmarks, packaged_root):
        (root / "suites").mkdir(parents=True)
        (root / "workloads").mkdir(parents=True)

    (repo_benchmarks / "fixtures").mkdir()
    (repo_benchmarks / "expected").mkdir()
    (packaged_root / "fixtures").mkdir()
    (packaged_root / "expected").mkdir()

    (repo_benchmarks / "fixtures" / "repo.html").write_text("<html></html>", encoding="utf-8")
    (repo_benchmarks / "expected" / "repo.json").write_text('{"items": []}', encoding="utf-8")
    (packaged_root / "fixtures" / "packaged.html").write_text("<html></html>", encoding="utf-8")
    (packaged_root / "expected" / "packaged.json").write_text('{"items": []}', encoding="utf-8")

    (repo_benchmarks / "suites" / "dev.json").write_text(
        json.dumps(
            {
                "name": "dev",
                "version": 1,
                "workloads": [{"id": "shared_workload", "weight": 1.0, "required": True}],
            }
        ),
        encoding="utf-8",
    )
    (packaged_root / "suites" / "dev.json").write_text(
        json.dumps(
            {
                "name": "dev",
                "version": 1,
                "workloads": [{"id": "shared_workload", "weight": 1.0, "required": True}],
            }
        ),
        encoding="utf-8",
    )

    (repo_benchmarks / "workloads" / "shared_workload.json").write_text(
        json.dumps(
            {
                "id": "repo_workload",
                "version": 1,
                "kind": "static",
                "fixture": "fixtures/repo.html",
                "expected": "expected/repo.json",
                "extract_spec": {"strategy": "record_css", "item_selector": ".item", "fields": {}},
                "correctness": {"comparison": "exact", "required_fields": [], "semantic_match_threshold": 1.0},
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )
    (packaged_root / "workloads" / "shared_workload.json").write_text(
        json.dumps(
            {
                "id": "packaged_workload",
                "version": 1,
                "kind": "static",
                "fixture": "fixtures/packaged.html",
                "expected": "expected/packaged.json",
                "extract_spec": {"strategy": "record_css", "item_selector": ".item", "fields": {}},
                "correctness": {"comparison": "exact", "required_fields": [], "semantic_match_threshold": 1.0},
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(benchmarking, "REPO_ROOT", repo_root)
    monkeypatch.setattr(benchmarking, "BENCHMARKS_ROOT", repo_benchmarks)
    monkeypatch.setattr(benchmarking, "SCHEMA_ROOT", repo_benchmarks / "schema")
    monkeypatch.setattr(benchmarking, "SUITES_ROOT", repo_benchmarks / "suites")
    monkeypatch.setattr(benchmarking, "WORKLOADS_ROOT", repo_benchmarks / "workloads")
    monkeypatch.setattr(benchmarking, "_packaged_benchmarks_root", lambda: packaged_root)
    monkeypatch.setattr(benchmarking, "_validate_schema", lambda *args, **kwargs: None)

    suite = load_suite_spec("dev")

    assert suite.workloads[0].id == "repo_workload"


def _build_and_install_wheel(tmp_path):
    dist_dir = tmp_path / "dist"
    install_dir = tmp_path / "install"
    work_dir = tmp_path / "work"
    dist_dir.mkdir()
    install_dir.mkdir()
    work_dir.mkdir()

    repo_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "-w", str(dist_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    wheel_path = next(dist_dir.glob("scrapling-*.whl"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_dir),
            str(wheel_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return install_dir, work_dir


def test_installed_wheel_can_run_dev_suite_with_packaged_assets(tmp_path):
    install_dir, work_dir = _build_and_install_wheel(tmp_path)
    installed_benchmarks = install_dir / "benchmarks"

    script = textwrap.dedent(
        """
        import json
        import scrapling.benchmarking as b

        report = b.evaluate_suite("dev", repetitions=1, warmups=0)
        print(json.dumps({
            "module_file": b.__file__,
            "suite_names": b.list_suite_names(),
            "passed": report["passed"],
        }))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=work_dir,
        env={**os.environ, "PYTHONPATH": str(install_dir)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert not installed_benchmarks.exists()
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["module_file"].startswith(str(install_dir))
    assert "dev" in payload["suite_names"]
    assert payload["passed"] is True


@pytest.mark.parametrize(
    ("workload_name", "expected_text"),
    [
        ("browser_session_extract", "Session dashboard"),
        ("holdout_browser_session_extract", "Holdout session dashboard"),
    ],
)
def test_installed_wheel_packaged_browser_redirects_resolve(tmp_path, workload_name, expected_text):
    install_dir, work_dir = _build_and_install_wheel(tmp_path)
    installed_benchmarks = install_dir / "benchmarks"

    script = textwrap.dedent(
        f"""
        import json
        from pathlib import Path
        from urllib.parse import urljoin
        from urllib.request import urlopen

        import scrapling.benchmarking as b

        workload = b.load_workload_spec({workload_name!r})
        source = Path(workload.fixture).read_text(encoding="utf-8")
        redirect_target = source.split("window.location.href = '", 1)[1].split("'", 1)[0]

        with b.LocalFixtureServer(b._fixture_server_root((workload.fixture,))) as server:
            destination = urljoin(server.url_for(workload.fixture), redirect_target)
            with urlopen(destination) as response:
                body = response.read().decode("utf-8")

        print(json.dumps({{"module_file": b.__file__, "body": body}}))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=work_dir,
        env={**os.environ, "PYTHONPATH": str(install_dir)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert not installed_benchmarks.exists()
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["module_file"].startswith(str(install_dir))
    assert expected_text in payload["body"]


@pytest.mark.parametrize(
    ("workload_name", "expected_text"),
    [
        ("browser_session_extract", "Session dashboard"),
        ("holdout_browser_session_extract", "Holdout session dashboard"),
    ],
)
def test_packaged_browser_session_redirects_stay_within_fixture_server(
    monkeypatch,
    tmp_path,
    workload_name,
    expected_text,
):
    empty_root = tmp_path / "empty-root"
    empty_root.mkdir()
    packaged_root = Path(__file__).resolve().parents[2] / "scrapling" / "_benchmark_assets"

    monkeypatch.setattr(benchmarking, "REPO_ROOT", empty_root)
    monkeypatch.setattr(benchmarking, "BENCHMARKS_ROOT", empty_root / "benchmarks")
    monkeypatch.setattr(benchmarking, "SCHEMA_ROOT", empty_root / "benchmarks" / "schema")
    monkeypatch.setattr(benchmarking, "SUITES_ROOT", empty_root / "benchmarks" / "suites")
    monkeypatch.setattr(benchmarking, "WORKLOADS_ROOT", empty_root / "benchmarks" / "workloads")
    monkeypatch.setattr(benchmarking, "_packaged_benchmarks_root", lambda: packaged_root)
    benchmarking._schema_payload.cache_clear()

    workload = load_workload_spec(workload_name)
    match = re.search(
        r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]",
        Path(workload.fixture).read_text(encoding="utf-8"),
    )

    assert match is not None
    redirect_target = match.group(1)

    with benchmarking.LocalFixtureServer(benchmarking._fixture_server_root((workload.fixture,))) as server:
        destination = urljoin(server.url_for(workload.fixture), redirect_target)
        with urlopen(destination) as response:
            body = response.read().decode("utf-8")

    assert expected_text in body


def test_load_suite_and_workload_specs():
    suite = load_suite_spec("dev")
    workload = load_workload_spec("static_extract")
    release_suite = load_suite_spec("release")
    browser_suite = load_suite_spec("browser")
    browser_holdout_suite = load_suite_spec("browser_holdout")

    assert suite.name == "dev"
    assert len(suite.workloads) == 3
    assert release_suite.name == "release"
    assert len(release_suite.workloads) == 8
    assert browser_suite.name == "browser"
    assert len(browser_suite.workloads) == 2
    assert browser_holdout_suite.name == "browser_holdout"
    assert len(browser_holdout_suite.workloads) == 2
    assert workload.id == "static_extract"
    assert Path(workload.fixture).exists()
    assert Path(workload.expected).exists()


def test_load_suite_spec_rejects_invalid_schema(tmp_path):
    suite_path = tmp_path / "invalid_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "invalid",
                "version": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid benchmark suite spec"):
        load_suite_spec(suite_path)


def test_load_workload_spec_rejects_invalid_schema(tmp_path):
    workload_path = tmp_path / "invalid_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "invalid",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "extract_spec": {},
                "correctness": {},
                "cost_weights": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid benchmark workload spec"):
        load_workload_spec(workload_path)


def test_load_suite_spec_rejects_negative_weight(tmp_path):
    suite_path = tmp_path / "invalid_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "invalid",
                "version": 1,
                "workloads": [
                    {"id": "static_extract", "weight": -0.1, "required": True},
                    {"id": "text_similarity", "weight": 1.1, "required": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid benchmark suite spec"):
        load_suite_spec(suite_path)


def test_load_suite_spec_rejects_weights_that_do_not_sum_to_one(tmp_path):
    suite_path = tmp_path / "invalid_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "invalid",
                "version": 1,
                "workloads": [
                    {"id": "static_extract", "weight": 0.2, "required": True},
                    {"id": "text_similarity", "weight": 0.2, "required": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sum to 1.0"):
        load_suite_spec(suite_path)


def test_load_workload_spec_rejects_unknown_cost_weight_key(tmp_path):
    workload_path = tmp_path / "invalid_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "invalid",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "expected": "benchmarks/expected/static_extract.expected.json",
                "extract_spec": {
                    "strategy": "record_css",
                    "item_selector": ".product-card",
                    "fields": {"title": ".title::text"},
                },
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                    "bogus": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid benchmark workload spec"):
        load_workload_spec(workload_path)


def test_load_workload_spec_requires_all_cost_weight_keys(tmp_path):
    workload_path = tmp_path / "invalid_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "invalid",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "expected": "benchmarks/expected/static_extract.expected.json",
                "extract_spec": {
                    "strategy": "record_css",
                    "item_selector": ".product-card",
                    "fields": {"title": ".title::text"},
                },
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid benchmark workload spec"):
        load_workload_spec(workload_path)


def test_evaluate_suite_resolves_workloads_relative_to_custom_suite_path(tmp_path):
    workload_path = tmp_path / "relative_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "relative_static",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "expected": "benchmarks/expected/static_extract.expected.json",
                "ready_condition": {"type": "immediate"},
                "extract_spec": {
                    "strategy": "record_css",
                    "item_selector": ".product-card",
                    "fields": {
                        "title": ".title::text",
                        "price": ".price::text",
                        "url": "a::attr(href)",
                    },
                },
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title", "price", "url"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )
    suite_path = tmp_path / "custom_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "custom",
                "version": 1,
                "workloads": [{"id": "relative_workload.json", "weight": 1.0, "required": True}],
                "defaults": {"repetitions": 1, "warmups": 0},
            }
        ),
        encoding="utf-8",
    )

    suite = load_suite_spec(suite_path)
    report = evaluate_suite(suite_path, repetitions=1, warmups=0)

    assert suite.workloads[0].id == "relative_static"
    assert report["passed"] is True
    assert report["workloads"][0]["id"] == "relative_static"


def test_release_suite_runs_new_workload_kinds():
    report = evaluate_suite("release", repetitions=1, warmups=0)

    workload_ids = [workload["id"] for workload in report["workloads"]]
    assert report["passed"] is True
    assert "crawl_extract" in workload_ids
    assert "session_flow_extract" in workload_ids
    assert "protected_replay_extract" in workload_ids
    assert "browser_dynamic_extract" in workload_ids
    assert "browser_session_extract" in workload_ids


def test_release_suite_treats_browser_workloads_as_optional(monkeypatch):
    release_suite = load_suite_spec("release")
    real_evaluate_workload = benchmarking.evaluate_workload

    def fake_evaluate_workload(workload, **kwargs):
        if workload.id.startswith("browser_"):
            return benchmarking._failed_workload_report(
                workload.id,
                weight=kwargs["weight"],
                required=kwargs["required"],
                failure_kind="worker_error",
                messages=("missing browser extras",),
                baseline_entry=kwargs.get("baseline_entry"),
                artifacts_dir=kwargs.get("artifacts_dir"),
            )
        return real_evaluate_workload(
            workload,
            **kwargs,
        )

    browser_entries = {entry.id: entry.required for entry in release_suite.workloads if entry.id.startswith("browser_")}
    monkeypatch.setattr(benchmarking, "evaluate_workload", fake_evaluate_workload)

    report = evaluate_suite("release", repetitions=1, warmups=0)

    assert browser_entries == {
        "browser_dynamic_extract": False,
        "browser_session_extract": False,
    }
    assert report["passed"] is True
    failed_browser_reports = [workload for workload in report["workloads"] if workload["id"].startswith("browser_")]
    assert all(workload["passed"] is False for workload in failed_browser_reports)


def test_acceptance_primitives_align_report_and_payload_forms():
    report = benchmarking.WorkloadReport(
        id="browser_dynamic_extract",
        required=False,
        weight=0.2,
        passed=False,
        failure_kind="environment_unavailable",
        score=None,
        effective_cost=0.0,
        baseline_effective_cost=None,
        metrics=benchmarking.WorkloadMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0),
        correctness=benchmarking.CorrectnessSummary(
            passed=False,
            item_count=0,
            expected_item_count=1,
            required_fields_match=False,
            semantic_match=0.0,
            non_empty=False,
            messages=("browser benchmark dependencies are unavailable",),
        ),
        stability=benchmarking.StabilitySummary(
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            cv=0.0,
            success_rate=0.0,
            consistent_output=False,
            penalty=0.0,
        ),
        artifacts={},
    )
    payload = {
        "required": False,
        "failure_kind": "environment_unavailable",
        "baseline_effective_cost": None,
        "passed": False,
        "effective_cost": 0.0,
    }

    assert benchmarking._is_environment_unavailable_optional(report) is True
    assert benchmarking._is_neutral_workload_payload(payload) is True
    assert benchmarking._is_baseline_comparable_workload(report) is True
    assert benchmarking._is_baseline_comparable_workload_payload(payload) is True


def test_report_is_strict_success_matches_shared_acceptance_contract():
    report = {
        "passed": True,
        "srps": 100.0,
        "summary": {
            "baseline_comparable": True,
            "holdout": {
                "suite": "holdout",
                "passed": True,
                "srps": 95.0,
                "baseline_comparable": True,
            },
        },
        "workloads": [
            {
                "id": "static_extract",
                "required": True,
                "failure_kind": None,
                "baseline_effective_cost": 10.0,
                "passed": True,
                "effective_cost": 9.0,
            },
            {
                "id": "browser_dynamic_extract",
                "required": False,
                "failure_kind": "environment_unavailable",
                "baseline_effective_cost": None,
                "passed": False,
                "effective_cost": 0.0,
            },
        ],
    }

    assert benchmarking._report_is_strict_success(report) is True
    report["summary"]["holdout"]["baseline_comparable"] = False
    assert benchmarking._report_is_strict_success(report) is False


def test_suite_score_penalizes_failed_optional_workloads():
    passing_required = benchmarking.WorkloadReport(
        id="required_ok",
        required=True,
        weight=0.7,
        passed=True,
        failure_kind=None,
        score=100.0,
        effective_cost=10.0,
        baseline_effective_cost=10.0,
        metrics=benchmarking.WorkloadMetrics(1.0, 1.0, 1.0, 1.0, 1.0, 1),
        correctness=benchmarking.CorrectnessSummary(
            passed=True,
            item_count=1,
            expected_item_count=1,
            required_fields_match=True,
            semantic_match=1.0,
            non_empty=True,
        ),
        stability=benchmarking.StabilitySummary(
            mean_ms=1.0,
            median_ms=1.0,
            p95_ms=1.0,
            cv=0.0,
            success_rate=1.0,
            consistent_output=True,
            penalty=1.0,
        ),
        artifacts={},
    )
    passing_optional = benchmarking.WorkloadReport(
        id="optional_ok",
        required=False,
        weight=0.3,
        passed=True,
        failure_kind=None,
        score=100.0,
        effective_cost=10.0,
        baseline_effective_cost=10.0,
        metrics=benchmarking.WorkloadMetrics(1.0, 1.0, 1.0, 1.0, 1.0, 1),
        correctness=benchmarking.CorrectnessSummary(
            passed=True,
            item_count=1,
            expected_item_count=1,
            required_fields_match=True,
            semantic_match=1.0,
            non_empty=True,
        ),
        stability=benchmarking.StabilitySummary(
            mean_ms=1.0,
            median_ms=1.0,
            p95_ms=1.0,
            cv=0.0,
            success_rate=1.0,
            consistent_output=True,
            penalty=1.0,
        ),
        artifacts={},
    )
    failed_optional = benchmarking._failed_workload_report(
        "optional_failed",
        weight=0.3,
        required=False,
        failure_kind="worker_error",
        messages=("failed",),
        baseline_entry={"effective_cost": 10.0},
    )

    all_passing_score = benchmarking._suite_score(
        [passing_required, passing_optional],
        correctness_passed=True,
    )
    failed_optional_score = benchmarking._suite_score(
        [passing_required, failed_optional],
        correctness_passed=True,
    )

    assert all_passing_score == 100.0
    assert failed_optional_score is not None
    assert failed_optional_score < all_passing_score


def test_suite_score_treats_environment_unavailable_optional_workloads_neutrally():
    passing_required = benchmarking.WorkloadReport(
        id="required_ok",
        required=True,
        weight=0.7,
        passed=True,
        failure_kind=None,
        score=100.0,
        effective_cost=10.0,
        baseline_effective_cost=10.0,
        metrics=benchmarking.WorkloadMetrics(1.0, 1.0, 1.0, 1.0, 1.0, 1),
        correctness=benchmarking.CorrectnessSummary(
            passed=True,
            item_count=1,
            expected_item_count=1,
            required_fields_match=True,
            semantic_match=1.0,
            non_empty=True,
        ),
        stability=benchmarking.StabilitySummary(
            mean_ms=1.0,
            median_ms=1.0,
            p95_ms=1.0,
            cv=0.0,
            success_rate=1.0,
            consistent_output=True,
            penalty=1.0,
        ),
        artifacts={},
    )
    passing_optional = benchmarking.WorkloadReport(
        id="optional_ok",
        required=False,
        weight=0.3,
        passed=True,
        failure_kind=None,
        score=100.0,
        effective_cost=10.0,
        baseline_effective_cost=10.0,
        metrics=benchmarking.WorkloadMetrics(1.0, 1.0, 1.0, 1.0, 1.0, 1),
        correctness=benchmarking.CorrectnessSummary(
            passed=True,
            item_count=1,
            expected_item_count=1,
            required_fields_match=True,
            semantic_match=1.0,
            non_empty=True,
        ),
        stability=benchmarking.StabilitySummary(
            mean_ms=1.0,
            median_ms=1.0,
            p95_ms=1.0,
            cv=0.0,
            success_rate=1.0,
            consistent_output=True,
            penalty=1.0,
        ),
        artifacts={},
    )
    skipped_optional = benchmarking._failed_workload_report(
        "optional_skipped",
        weight=0.3,
        required=False,
        failure_kind="environment_unavailable",
        messages=("missing browser extras",),
        baseline_entry={"effective_cost": 10.0},
    )

    all_passing_score = benchmarking._suite_score(
        [passing_required, passing_optional],
        correctness_passed=True,
    )
    skipped_optional_score = benchmarking._suite_score(
        [passing_required, skipped_optional],
        correctness_passed=True,
    )

    assert all_passing_score == 100.0
    assert skipped_optional_score == all_passing_score


def test_acceptance_policy_treats_optional_environment_unavailable_as_neutral():
    policy = benchmarking._acceptance_policy_for_payload(
        {
            "required": False,
            "failure_kind": "environment_unavailable",
            "passed": False,
            "effective_cost": 0.0,
            "baseline_effective_cost": None,
        }
    )

    assert policy.neutral_skip is True
    assert policy.baseline_comparable is True
    assert policy.baseline_writable is False
    assert policy.baseline_acceptable is True


def test_acceptance_policy_treats_failed_required_workload_as_not_acceptable():
    report = benchmarking._failed_workload_report(
        "required_failed",
        weight=1.0,
        required=True,
        failure_kind="worker_error",
        messages=("failed",),
        baseline_entry={"effective_cost": 10.0},
    )

    policy = benchmarking._acceptance_policy_for_report(report)

    assert policy.neutral_skip is False
    assert policy.baseline_comparable is True
    assert policy.baseline_writable is False
    assert policy.baseline_acceptable is False


def test_required_environment_unavailable_workload_still_fails_suite(monkeypatch):
    real_evaluate_workload = benchmarking.evaluate_workload

    def fake_evaluate_workload(workload, **kwargs):
        if workload.id == "static_extract":
            return benchmarking._failed_workload_report(
                workload.id,
                weight=kwargs["weight"],
                required=kwargs["required"],
                failure_kind="environment_unavailable",
                messages=("required runtime is unavailable",),
                baseline_entry=kwargs.get("baseline_entry"),
                artifacts_dir=kwargs.get("artifacts_dir"),
            )
        return real_evaluate_workload(workload, **kwargs)

    monkeypatch.setattr(benchmarking, "evaluate_workload", fake_evaluate_workload)

    report = evaluate_suite("dev", repetitions=1, warmups=0)

    assert report["passed"] is False
    assert report["srps"] == 0.0
    assert report["workloads"][0]["failure_kind"] == "environment_unavailable"


def test_browser_suite_runs_browser_workloads():
    report = evaluate_suite("browser", repetitions=1, warmups=0)

    workload_ids = [workload["id"] for workload in report["workloads"]]
    assert report["passed"] is True
    assert "browser_dynamic_extract" in workload_ids
    assert "browser_session_extract" in workload_ids


def test_browser_holdout_suite_runs_browser_workloads():
    report = evaluate_suite("browser_holdout", repetitions=1, warmups=0)

    workload_ids = [workload["id"] for workload in report["workloads"]]
    assert report["passed"] is True
    assert "holdout_browser_dynamic_extract" in workload_ids
    assert "holdout_browser_session_extract" in workload_ids


def test_custom_browser_suite_supports_fixtures_outside_repo_root(tmp_path):
    fixture_path = tmp_path / "external_browser_fixture.html"
    fixture_path.write_text(
        """
        <html>
          <body>
            <article class="product-card">
              <h2 class="title">External Widget</h2>
              <span class="price">$9.99</span>
              <a href="/external-widget">View</a>
            </article>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    expected_path = tmp_path / "external_browser.expected.json"
    expected_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "title": "External Widget",
                        "price": "$9.99",
                        "url": "/external-widget",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    workload_path = tmp_path / "external_browser_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "external_browser_extract",
                "version": 1,
                "kind": "browser",
                "fixture": str(fixture_path),
                "expected": str(expected_path),
                "ready_condition": {"selector": ".product-card", "state": "attached", "timeout_ms": 5000},
                "extract_spec": {
                    "strategy": "record_css",
                    "item_selector": ".product-card",
                    "fields": {
                        "title": ".title::text",
                        "price": ".price::text",
                        "url": "a::attr(href)",
                    },
                },
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title", "price", "url"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )
    suite_path = tmp_path / "external_browser_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "external_browser",
                "version": 1,
                "workloads": [{"id": "external_browser_workload.json", "weight": 1.0, "required": True}],
                "defaults": {"repetitions": 1, "warmups": 0, "timeout_ms": 5000},
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_suite(suite_path, repetitions=1, warmups=0)

    assert report["passed"] is True
    assert report["workloads"][0]["id"] == "external_browser_extract"


def test_evaluate_suite_produces_report_and_artifacts(tmp_path):
    output_path = tmp_path / "report.json"
    artifacts_dir = tmp_path / "artifacts"

    report = evaluate_suite(
        "dev",
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        repetitions=1,
        warmups=0,
    )

    assert report["version"] == 2
    assert report["suite"] == "dev"
    assert report["passed"] is True
    assert report["srps"] is None
    assert output_path.exists()
    assert len(report["workloads"]) == 3
    for workload in report["workloads"]:
        assert workload["passed"] is True
        assert Path(workload["artifacts"]["raw_output"]).exists()
        assert Path(workload["artifacts"]["normalized_output"]).exists()
        assert Path(workload["artifacts"]["diff"]).exists()
        assert Path(workload["artifacts"]["metrics_trace"]).exists()


def test_baseline_round_trip_adds_scores(tmp_path):
    baseline_path = tmp_path / "dev-baseline.json"

    initial = evaluate_suite("dev", repetitions=1, warmups=0)
    save_baseline(baseline_path, initial)
    loaded = load_baseline(baseline_path)
    rerun = evaluate_suite(
        "dev",
        baseline_path=baseline_path,
        repetitions=1,
        warmups=0,
    )

    assert loaded["schema_version"] == BASELINE_SCHEMA_VERSION
    assert rerun["srps"] is not None
    assert all(workload["score"] is not None for workload in rerun["workloads"])


def test_filtered_baseline_scores_same_filtered_workload_set(tmp_path):
    baseline_path = tmp_path / "dev-filtered-baseline.json"
    filtered = evaluate_suite(
        "dev",
        repetitions=1,
        warmups=0,
        workload_filter=["static_extract"],
    )

    save_baseline(baseline_path, filtered)
    rerun = evaluate_suite(
        "dev",
        baseline_path=baseline_path,
        repetitions=1,
        warmups=0,
        workload_filter=["static_extract"],
    )

    assert rerun["summary"]["baseline_comparable"] is True
    assert rerun["srps"] is not None
    assert [workload["id"] for workload in rerun["workloads"]] == ["static_extract"]


def test_filtered_baseline_does_not_score_full_suite(tmp_path):
    baseline_path = tmp_path / "dev-filtered-baseline.json"
    filtered = evaluate_suite(
        "dev",
        repetitions=1,
        warmups=0,
        workload_filter=["static_extract"],
    )

    save_baseline(baseline_path, filtered)
    rerun = evaluate_suite(
        "dev",
        baseline_path=baseline_path,
        repetitions=1,
        warmups=0,
    )

    assert rerun["summary"]["baseline_comparable"] is False
    assert rerun["srps"] is None
    assert {workload["id"] for workload in rerun["workloads"] if workload["baseline_effective_cost"] is None} == {
        "large_dom_extract",
        "text_similarity",
    }


def test_holdout_suite_contributes_generalization_summary(tmp_path):
    dev_baseline = tmp_path / "dev-baseline.json"
    holdout_baseline = tmp_path / "holdout-baseline.json"

    dev_report = evaluate_suite("dev", repetitions=1, warmups=0)
    holdout_report = evaluate_suite("holdout", repetitions=1, warmups=0)
    save_baseline(dev_baseline, dev_report)
    save_baseline(holdout_baseline, holdout_report)

    combined = evaluate_suite(
        "dev",
        baseline_path=dev_baseline,
        holdout_suite_name_or_path="holdout",
        holdout_baseline_path=holdout_baseline,
        repetitions=1,
        warmups=0,
    )

    assert combined["passed"] is True
    assert combined["srps"] is not None
    assert combined["summary"]["generalization_penalty"] > 0
    assert combined["summary"]["holdout"]["suite"] == "holdout"


def test_evaluate_suite_revalidates_final_report_after_holdout_adjustments(monkeypatch):
    validations = []

    def fake_validate(payload, schema_name, *, label):
        validations.append((schema_name, label, json.loads(json.dumps(payload))))

    reports = iter(
        [
            {
                "version": benchmarking.BENCHMARK_REPORT_VERSION,
                "suite": "dev",
                "suite_version": 1,
                "passed": True,
                "srps": 100.0,
                "baseline": {"path": "benchmarks/baselines/dev.json", "version": benchmarking.BASELINE_SCHEMA_VERSION},
                "environment": benchmarking.environment_metadata(),
                "summary": {
                    "correctness_passed": True,
                    "generalization_penalty": 1.0,
                    "baseline_comparable": True,
                    "stability_penalty": 1.0,
                    "seed": None,
                },
                "workloads": [],
            },
            {
                "version": benchmarking.BENCHMARK_REPORT_VERSION,
                "suite": "holdout",
                "suite_version": 1,
                "passed": True,
                "srps": 50.0,
                "baseline": {
                    "path": "benchmarks/baselines/holdout.json",
                    "version": benchmarking.BASELINE_SCHEMA_VERSION,
                },
                "environment": benchmarking.environment_metadata(),
                "summary": {
                    "correctness_passed": True,
                    "generalization_penalty": 1.0,
                    "baseline_comparable": True,
                    "stability_penalty": 1.0,
                    "seed": None,
                },
                "workloads": [],
            },
        ]
    )

    monkeypatch.setattr(benchmarking, "_evaluate_suite_core", lambda *args, **kwargs: next(reports))
    monkeypatch.setattr(benchmarking, "_validate_schema", fake_validate)

    report = evaluate_suite("dev", holdout_suite_name_or_path="holdout")

    assert report["summary"]["holdout"]["suite"] == "holdout"
    final_report_validations = [
        payload
        for schema_name, label, payload in validations
        if schema_name == "report.schema.json" and label == "benchmark report"
    ]
    assert final_report_validations
    assert final_report_validations[-1]["summary"]["holdout"]["suite"] == "holdout"
    assert final_report_validations[-1]["summary"]["generalization_penalty"] == 0.5
    assert final_report_validations[-1]["srps"] == 50.0


def test_baseline_payload_shape():
    report = evaluate_suite("dev", repetitions=1, warmups=0)
    payload = baseline_payload(report)

    assert payload["schema_version"] == BASELINE_SCHEMA_VERSION
    assert payload["suite"] == "dev"
    assert set(payload["workloads"]) == {
        "static_extract",
        "large_dom_extract",
        "text_similarity",
    }
    assert payload["suite_version"] == 1
    assert payload["workloads"]["static_extract"]["workload_version"] == 1
    assert payload["workloads"]["static_extract"]["spec_fingerprint"]


def test_save_baseline_rejects_failed_workloads(tmp_path):
    baseline_path = tmp_path / "invalid-baseline.json"
    report = evaluate_suite("dev", repetitions=1, warmups=0)
    report["workloads"][0]["passed"] = False
    report["workloads"][0]["failure_kind"] = "correctness"
    report["workloads"][0]["effective_cost"] = 0.0
    report["workloads"][0]["score"] = 0.0
    report["passed"] = False
    report["srps"] = 0.0

    with pytest.raises(ValueError, match="failed workloads"):
        save_baseline(baseline_path, report)


def test_save_baseline_omits_optional_environment_unavailable_workloads(tmp_path):
    baseline_path = tmp_path / "release-baseline.json"
    report = evaluate_suite("release", repetitions=1, warmups=0)
    report["workloads"].append(
        {
            "id": "browser_optional_missing",
            "required": False,
            "weight": 0.1,
            "passed": False,
            "failure_kind": "environment_unavailable",
            "score": None,
            "effective_cost": 0.0,
            "baseline_effective_cost": None,
            "metrics": {
                "wall_ms": 0.0,
                "cpu_ms": 0.0,
                "peak_rss_mb": 0.0,
                "load_ms": 0.0,
                "extract_ms": 0.0,
                "work_units": 0,
            },
            "correctness": {
                "passed": False,
                "item_count": 0,
                "expected_item_count": 1,
                "required_fields_match": False,
                "semantic_match": 0.0,
                "non_empty": False,
                "messages": ["browser benchmark dependencies are unavailable"],
            },
            "stability": {
                "mean_ms": 0.0,
                "median_ms": 0.0,
                "p95_ms": 0.0,
                "cv": 0.0,
                "success_rate": 0.0,
                "consistent_output": False,
                "penalty": 0.0,
            },
            "artifacts": {},
            "workload_version": 1,
            "spec_fingerprint": "fingerprint",
        }
    )

    save_baseline(baseline_path, report)
    payload = load_baseline(baseline_path)

    assert payload is not None
    assert "browser_optional_missing" not in payload["workloads"]


def test_load_baseline_rejects_unknown_schema(tmp_path):
    baseline_path = tmp_path / "bad-baseline.json"
    baseline_path.write_text(
        json.dumps({"schema_version": 999, "workloads": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported baseline schema version"):
        load_baseline(baseline_path)


def test_load_baseline_rejects_invalid_shape(tmp_path):
    baseline_path = tmp_path / "bad-baseline.json"
    baseline_path.write_text(
        json.dumps({"schema_version": BASELINE_SCHEMA_VERSION, "suite": "dev"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid benchmark baseline"):
        load_baseline(baseline_path)


def test_report_schema_rejects_invalid_nested_shapes():
    with pytest.raises(ValueError, match="Invalid benchmark report"):
        benchmarking._validate_schema(
            {
                "version": 2,
                "suite": "dev",
                "suite_version": 1,
                "passed": True,
                "srps": None,
                "baseline": {"path": None, "version": None},
                "environment": {
                    "scrapling_version": "0.4.2",
                    "python_version": "3.14.3",
                    "platform": "test-platform",
                    "processor": "unknown",
                    "timestamp_utc": "2026-03-22T00:00:00+00:00",
                },
                "summary": {
                    "correctness_passed": True,
                    "generalization_penalty": 1.0,
                    "baseline_comparable": False,
                    "stability_penalty": None,
                    "seed": None,
                },
                "workloads": [
                    {
                        "id": "static_extract",
                        "required": True,
                        "weight": 1.0,
                        "passed": True,
                        "score": None,
                        "effective_cost": 10.0,
                        "baseline_effective_cost": None,
                        "metrics": [],
                        "correctness": {},
                        "stability": {},
                        "artifacts": {},
                        "workload_version": 1,
                        "spec_fingerprint": "fingerprint",
                        "failure_kind": None,
                    }
                ],
            },
            "report.schema.json",
            label="benchmark report",
        )


def test_fallback_schema_validator_rejects_unknown_keys_when_additional_properties_false(
    monkeypatch,
):
    monkeypatch.setattr(benchmarking, "Draft202012Validator", None)
    monkeypatch.setattr(
        benchmarking,
        "_schema_payload",
        lambda _: {
            "type": "object",
            "properties": {
                "child": {
                    "type": "object",
                    "properties": {
                        "known": {"type": "string"},
                    },
                    "required": ["known"],
                    "additionalProperties": False,
                }
            },
            "required": ["child"],
            "additionalProperties": False,
        },
    )

    with pytest.raises(ValueError, match="unexpected property 'extra'"):
        benchmarking._validate_schema(
            {
                "child": {"known": "value", "extra": "nope"},
            },
            "irrelevant.schema.json",
            label="benchmark schema payload",
        )


def test_evaluate_suite_rejects_mismatched_baseline_suite(tmp_path):
    baseline_path = tmp_path / "holdout-baseline.json"
    save_baseline(baseline_path, evaluate_suite("holdout", repetitions=1, warmups=0))

    with pytest.raises(ValueError, match="does not match requested suite"):
        evaluate_suite("dev", baseline_path=baseline_path, repetitions=1, warmups=0)


def test_evaluate_suite_rejects_zero_repetitions():
    with pytest.raises(ValueError, match="repetitions must be greater than zero"):
        evaluate_suite("dev", repetitions=0, warmups=0)


def test_evaluate_suite_rejects_negative_warmups():
    with pytest.raises(ValueError, match="warmups cannot be negative"):
        evaluate_suite("dev", repetitions=1, warmups=-1)


def test_evaluate_suite_marks_partial_holdout_baseline_as_not_comparable(tmp_path):
    baseline_path = tmp_path / "holdout-baseline.json"
    save_baseline(baseline_path, evaluate_suite("holdout", repetitions=1, warmups=0))
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["workloads"].pop(next(iter(payload["workloads"])))
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_suite(
        "dev",
        repetitions=1,
        warmups=0,
        holdout_suite_name_or_path="holdout",
        holdout_baseline_path=baseline_path,
    )

    assert report["summary"]["holdout"]["baseline_comparable"] is False


def test_required_correctness_failure_zeroes_srps(tmp_path):
    expected_path = tmp_path / "wrong.expected.json"
    expected_path.write_text(json.dumps({"items": [{"title": "wrong"}]}), encoding="utf-8")

    workload_path = tmp_path / "broken_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "broken_static",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "expected": str(expected_path),
                "ready_condition": {"type": "immediate"},
                "extract_spec": {
                    "strategy": "record_css",
                    "item_selector": ".product-card",
                    "fields": {
                        "title": ".title::text",
                        "price": ".price::text",
                        "url": "a::attr(href)",
                    },
                },
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title", "price", "url"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )

    suite_path = tmp_path / "broken_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "broken",
                "version": 1,
                "workloads": [{"id": str(workload_path), "weight": 1.0, "required": True}],
                "defaults": {"repetitions": 1, "warmups": 0},
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_suite(suite_path, repetitions=1, warmups=0)

    assert report["passed"] is False
    assert report["srps"] == 0.0
    assert report["workloads"][0]["passed"] is False
    assert report["workloads"][0]["failure_kind"] == "correctness"


def test_workload_exception_is_reported_in_json_report(tmp_path):
    expected_path = tmp_path / "output.expected.json"
    expected_path.write_text(json.dumps({"items": [{"title": "value"}]}), encoding="utf-8")

    workload_path = tmp_path / "exploding_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "exploding_workload",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "expected": str(expected_path),
                "ready_condition": {"type": "immediate"},
                "extract_spec": {"strategy": "unsupported"},
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )
    suite_path = tmp_path / "exploding_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "exploding",
                "version": 1,
                "workloads": [{"id": str(workload_path), "weight": 1.0, "required": True}],
                "defaults": {"repetitions": 1, "warmups": 0, "timeout_ms": 1000},
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_suite(suite_path, repetitions=1, warmups=0)

    assert report["passed"] is False
    assert report["srps"] == 0.0
    assert report["workloads"][0]["failure_kind"] == "worker_error"
    assert "Unsupported benchmark extraction strategy" in " ".join(report["workloads"][0]["correctness"]["messages"])


def test_evaluate_workload_reports_environment_unavailable(monkeypatch):
    monkeypatch.setattr(
        benchmarking,
        "_evaluate_workload_in_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            benchmarking._EnvironmentUnavailableError("missing browser extras")
        ),
    )

    report = evaluate_workload(
        load_workload_spec("browser_dynamic_extract"),
        weight=1.0,
        required=False,
        repetitions=1,
        warmups=0,
        timeout_ms=None,
        isolate_process=False,
    )

    assert report.passed is False
    assert report.failure_kind == "environment_unavailable"
    assert "missing browser extras" in " ".join(report.correctness.messages)


def test_evaluate_workload_preserves_environment_unavailable_from_warmup(monkeypatch):
    monkeypatch.setattr(
        benchmarking,
        "_run_process_job",
        lambda **kwargs: {
            "ok": False,
            "error": "missing browser extras",
            "failure_kind": "environment_unavailable",
        },
    )

    report = evaluate_workload(
        load_workload_spec("browser_dynamic_extract"),
        weight=1.0,
        required=False,
        repetitions=1,
        warmups=1,
        timeout_ms=None,
        isolate_process=False,
    )

    assert report.passed is False
    assert report.failure_kind == "environment_unavailable"
    assert "missing browser extras" in " ".join(report.correctness.messages)


def test_evaluate_workload_times_out_and_returns_failure(monkeypatch):
    class FakeQueue:
        def get(self):
            raise AssertionError("queue.get should not be called on timeout")

    class FakeProcess:
        exitcode = None

        def __init__(self):
            self.terminated = False
            self.started = False

        def start(self):
            self.started = True

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return not self.terminated

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    class FakeContext:
        def __init__(self):
            self.process = FakeProcess()

        def Queue(self):
            return FakeQueue()

        def Process(self, *args, **kwargs):
            return self.process

    monkeypatch.setattr(benchmarking.multiprocessing, "get_context", lambda _: FakeContext())

    report = evaluate_workload(
        load_workload_spec("static_extract"),
        weight=1.0,
        required=True,
        repetitions=1,
        warmups=0,
        timeout_ms=1,
    )

    assert report.passed is False
    assert report.failure_kind == "timeout"
    assert "timed out" in " ".join(report.correctness.messages)


def test_evaluate_workload_times_out_when_warmup_worker_hangs(monkeypatch):
    class FakeQueue:
        def get(self, timeout=None):
            raise AssertionError("queue.get should not be called on timeout")

    class FakeProcess:
        exitcode = None

        def __init__(self):
            self.terminated = False

        def start(self):
            return None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return not self.terminated

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    class FakeContext:
        def Queue(self):
            return FakeQueue()

        def Process(self, *args, **kwargs):
            return FakeProcess()

    monkeypatch.setattr(benchmarking, "_benchmark_context", lambda prefer_fork=False: FakeContext())

    report = evaluate_workload(
        load_workload_spec("static_extract"),
        weight=1.0,
        required=True,
        repetitions=1,
        warmups=1,
        timeout_ms=1,
        isolate_process=False,
    )

    assert report.passed is False
    assert report.failure_kind == "timeout"
    assert "timed out" in " ".join(report.correctness.messages)


def test_flaky_repetitions_fail_correctness(monkeypatch):
    workload = load_workload_spec("static_extract")
    expected_output = json.loads(Path(workload.expected).read_text(encoding="utf-8"))
    outputs = deque(
        [
            {"items": [{"title": "wrong", "price": "$0.00", "url": "/wrong"}]},
            expected_output,
        ]
    )

    def fake_run_extraction(*args, **kwargs):
        return outputs.popleft(), 1.0, 1.0, ("catalog page",)

    monkeypatch.setattr(benchmarking, "_run_extraction", fake_run_extraction)

    report = evaluate_workload(
        workload,
        weight=1.0,
        required=True,
        repetitions=2,
        warmups=0,
        isolate_process=False,
    )

    assert report.passed is False
    assert report.failure_kind == "correctness"
    assert "repetitions" in " ".join(report.correctness.messages)


def test_warmups_do_not_pollute_peak_rss_in_measured_repetitions(monkeypatch):
    workload = load_workload_spec("static_extract")
    expected_output = json.loads(Path(workload.expected).read_text(encoding="utf-8"))
    state = {"calls": 0}

    def fake_run_extraction(*args, **kwargs):
        state["calls"] += 1
        return expected_output, 1.0, 1.0, ("catalog page",)

    def fake_peak_rss():
        return 500.0 if state["calls"] > 1 else 50.0

    monkeypatch.setattr(benchmarking, "_run_extraction", fake_run_extraction)
    monkeypatch.setattr(benchmarking, "_current_peak_rss_mb", fake_peak_rss)

    report = evaluate_workload(
        workload,
        weight=1.0,
        required=True,
        repetitions=1,
        warmups=1,
        timeout_ms=None,
        isolate_process=False,
    )

    assert report.passed is True
    assert report.metrics.peak_rss_mb == 50.0


def test_benchmarking_import_survives_missing_resource_module(tmp_path):
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        textwrap.dedent(
            """
            import builtins

            _real_import = builtins.__import__

            def _blocked_import(name, *args, **kwargs):
                if name == "resource":
                    raise ModuleNotFoundError("No module named 'resource'")
                return _real_import(name, *args, **kwargs)

            builtins.__import__ = _blocked_import
            """
        ),
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    pythonpath = [str(tmp_path), str(repo_root)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scrapling.benchmarking as b; print('dev' in b.list_suite_names()); print(b._current_peak_rss_mb())",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_lines = result.stdout.strip().splitlines()
    assert stdout_lines[0] == "True"
    assert float(stdout_lines[1]) == 0.0


def test_current_peak_rss_mb_uses_kilobytes_on_linux(monkeypatch):
    class FakeUsage:
        ru_maxrss = 2048

    fake_resource = types.SimpleNamespace()
    monkeypatch.setattr(benchmarking, "resource", fake_resource)
    monkeypatch.setattr(benchmarking.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        benchmarking.resource,
        "RUSAGE_SELF",
        object(),
        raising=False,
    )
    monkeypatch.setattr(
        benchmarking.resource,
        "getrusage",
        lambda who: FakeUsage(),
        raising=False,
    )

    assert benchmarking._current_peak_rss_mb() == 2.0


def test_current_peak_rss_mb_uses_bytes_on_macos(monkeypatch):
    class FakeUsage:
        ru_maxrss = 2 * 1024 * 1024

    fake_resource = types.SimpleNamespace()
    monkeypatch.setattr(benchmarking, "resource", fake_resource)
    monkeypatch.setattr(benchmarking.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        benchmarking.resource,
        "RUSAGE_SELF",
        object(),
        raising=False,
    )
    monkeypatch.setattr(
        benchmarking.resource,
        "getrusage",
        lambda who: FakeUsage(),
        raising=False,
    )

    assert benchmarking._current_peak_rss_mb() == 2.0


def test_evaluate_suite_api_works_from_plain_top_level_script(tmp_path):
    if benchmarking.platform.system() != "Linux":
        pytest.skip("plain top-level script support is only guaranteed on Linux")

    script_path = tmp_path / "plain_benchmark_script.py"
    script_path.write_text(
        "from scrapling.benchmarking import evaluate_suite\n"
        "print(evaluate_suite('dev', repetitions=1, warmups=0)['passed'])\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    pythonpath = [str(repo_root)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_benchmark_context_respects_default_on_macos(monkeypatch):
    calls = []

    monkeypatch.setattr(benchmarking.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(benchmarking.multiprocessing, "get_all_start_methods", lambda: ["fork", "spawn"])
    monkeypatch.setattr(benchmarking.multiprocessing, "get_start_method", lambda allow_none=True: "spawn")
    monkeypatch.setattr(
        benchmarking.multiprocessing,
        "get_context",
        lambda method=None: calls.append(method) or method,
    )

    ctx = benchmarking._benchmark_context()
    warmup_ctx = benchmarking._benchmark_context(prefer_fork=True)

    assert ctx == "spawn"
    assert warmup_ctx == "spawn"
    assert calls == ["spawn", "spawn"]


def test_in_process_mode_converts_exceptions_to_failed_report(tmp_path):
    expected_path = tmp_path / "output.expected.json"
    expected_path.write_text(json.dumps({"items": [{"title": "value"}]}), encoding="utf-8")
    workload_path = tmp_path / "exploding_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "exploding_in_process",
                "version": 1,
                "kind": "static",
                "fixture": "benchmarks/fixtures/static/catalog.html",
                "expected": str(expected_path),
                "ready_condition": {"type": "immediate"},
                "extract_spec": {"strategy": "unsupported"},
                "correctness": {
                    "comparison": "exact",
                    "required_fields": ["title"],
                    "semantic_match_threshold": 1.0,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_workload(
        load_workload_spec(workload_path),
        weight=1.0,
        required=True,
        repetitions=1,
        warmups=0,
        timeout_ms=None,
        isolate_process=False,
    )

    assert report.passed is False
    assert report.failure_kind == "worker_error"
    assert "Unsupported benchmark extraction strategy" in " ".join(report.correctness.messages)


def test_semantic_comparison_can_pass_without_exact_match(tmp_path):
    fixture_path = tmp_path / "semantic_fixture.html"
    fixture_path.write_text(
        """
        <html>
          <body>
            <article class="product-card">
              <h2 class="title">Alpha product!</h2>
            </article>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    expected_path = tmp_path / "semantic.expected.json"
    expected_path.write_text(
        json.dumps({"items": [{"title": "Alpha Product"}]}),
        encoding="utf-8",
    )
    workload_path = tmp_path / "semantic_workload.json"
    workload_path.write_text(
        json.dumps(
            {
                "id": "semantic_static",
                "version": 1,
                "kind": "static",
                "fixture": str(fixture_path),
                "expected": str(expected_path),
                "ready_condition": {"type": "immediate"},
                "extract_spec": {
                    "strategy": "record_css",
                    "item_selector": ".product-card",
                    "fields": {"title": ".title::text"},
                },
                "correctness": {
                    "comparison": "semantic",
                    "required_fields": ["title"],
                    "semantic_match_threshold": 0.9,
                },
                "cost_weights": {
                    "wall_ms": 0.35,
                    "cpu_ms": 0.25,
                    "peak_rss_mb": 0.15,
                    "load_ms": 0.1,
                    "extract_ms": 0.15,
                },
            }
        ),
        encoding="utf-8",
    )
    suite_path = tmp_path / "semantic_suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "name": "semantic",
                "version": 1,
                "workloads": [{"id": str(workload_path), "weight": 1.0, "required": True}],
                "defaults": {"repetitions": 1, "warmups": 0},
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_suite(suite_path, repetitions=1, warmups=0)

    assert report["passed"] is True
    assert report["workloads"][0]["correctness"]["semantic_match"] >= 0.9
    assert report["workloads"][0]["correctness"]["semantic_match"] < 1.0


def test_semantic_match_score_is_order_insensitive_for_equivalent_records():
    expected = [
        {"title": "Alpha Product", "price": "$10.00", "url": "/products/a"},
        {"title": "Beta Product", "price": "$12.00", "url": "/products/b"},
    ]
    actual = [
        {"title": "Beta Product", "price": "$12.00", "url": "/products/b"},
        {"title": "Alpha Product", "price": "$10.00", "url": "/products/a"},
    ]

    assert benchmarking._semantic_match_score(expected, actual) == 1.0


def test_baseline_fingerprint_mismatch_disables_scoring(tmp_path):
    baseline_path = tmp_path / "dev-baseline.json"
    save_baseline(baseline_path, evaluate_suite("dev", repetitions=1, warmups=0))
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["workloads"]["static_extract"]["spec_fingerprint"] = "mismatch"
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    rerun = evaluate_suite(
        "dev",
        baseline_path=baseline_path,
        repetitions=1,
        warmups=0,
    )

    static_report = next(workload for workload in rerun["workloads"] if workload["id"] == "static_extract")
    assert static_report["score"] is None
