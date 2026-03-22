import json

import pytest

from scripts import perf_benchmark


def _fake_report(passed=True, srps=123.45):
    return {
        "version": 2,
        "suite": "dev",
        "passed": passed,
        "srps": srps,
        "baseline": {"path": "benchmarks/baselines/dev.json", "version": 2},
        "environment": {
            "scrapling_version": "0.4.2",
            "python_version": "3.14.3",
            "platform": "test-platform",
        },
        "summary": {
            "correctness_passed": passed,
            "generalization_penalty": 1.0,
            "holdout": None,
            "seed": None,
        },
        "workloads": [
            {
                "id": "static_extract",
                "required": True,
                "weight": 1.0,
                "passed": passed,
                "failure_kind": None if passed else "correctness",
                "score": srps,
                "effective_cost": 10.0,
                "baseline_effective_cost": 12.0,
                "metrics": {
                    "wall_ms": 5.0,
                    "cpu_ms": 4.0,
                    "peak_rss_mb": 20.0,
                    "load_ms": 1.0,
                    "extract_ms": 2.0,
                    "work_units": 6,
                },
                "correctness": {
                    "passed": passed,
                    "item_count": 6,
                    "expected_item_count": 6,
                    "required_fields_match": passed,
                    "semantic_match": 1.0 if passed else 0.0,
                    "non_empty": True,
                    "messages": [],
                },
                "stability": {
                    "mean_ms": 5.0,
                    "median_ms": 5.0,
                    "p95_ms": 5.0,
                    "cv": 0.0,
                    "penalty": 1.0,
                },
                "artifacts": {},
            }
        ],
    }


def test_main_lists_suites(capsys):
    exit_code = perf_benchmark.main(["--list-suites"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "dev" in output


def test_main_lists_workloads(capsys):
    exit_code = perf_benchmark.main(["--list-workloads"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "static_extract" in output


def test_main_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(perf_benchmark, "evaluate_suite", lambda **_: _fake_report())

    exit_code = perf_benchmark.main(["--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["suite"] == "dev"


def test_main_saves_baseline(monkeypatch, tmp_path, capsys):
    baseline_path = tmp_path / "baseline.json"
    saved = {}

    def fake_save_baseline(path, report):
        saved["path"] = path
        saved["report"] = report
        return path

    monkeypatch.setattr(perf_benchmark, "evaluate_suite", lambda **_: _fake_report())
    monkeypatch.setattr(perf_benchmark, "save_baseline", fake_save_baseline)

    exit_code = perf_benchmark.main(
        ["--baseline", str(baseline_path), "--save-baseline"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert saved["path"] == str(baseline_path)
    assert saved["report"]["suite"] == "dev"
    assert f"Baseline saved to {baseline_path}" in output


def test_main_strict_mode_fails_on_regression(monkeypatch):
    monkeypatch.setattr(
        perf_benchmark,
        "evaluate_suite",
        lambda **_: _fake_report(passed=False, srps=0.0),
    )

    exit_code = perf_benchmark.main(["--strict"])

    assert exit_code == 1


def test_main_passes_workload_filter(monkeypatch):
    captured = {}

    def fake_evaluate_suite(**kwargs):
        captured.update(kwargs)
        return _fake_report()

    monkeypatch.setattr(perf_benchmark, "evaluate_suite", fake_evaluate_suite)

    exit_code = perf_benchmark.main(
        ["--workload", "static_extract", "--workload", "text_similarity"]
    )

    assert exit_code == 0
    assert captured["workload_filter"] == ["static_extract", "text_similarity"]


def test_main_passes_holdout_arguments(monkeypatch):
    captured = {}

    def fake_evaluate_suite(**kwargs):
        captured.update(kwargs)
        return _fake_report()

    monkeypatch.setattr(perf_benchmark, "evaluate_suite", fake_evaluate_suite)

    exit_code = perf_benchmark.main(
        ["--holdout-suite", "holdout", "--holdout-baseline", "benchmarks/baselines/holdout.json"]
    )

    assert exit_code == 0
    assert captured["holdout_suite_name_or_path"] == "holdout"
    assert captured["holdout_baseline_path"] == "benchmarks/baselines/holdout.json"


def test_main_surfaces_unknown_workload_error(monkeypatch):
    def fake_evaluate_suite(**_):
        raise ValueError("Unknown benchmark workload(s): nope")

    monkeypatch.setattr(perf_benchmark, "evaluate_suite", fake_evaluate_suite)

    with pytest.raises(ValueError, match="Unknown benchmark workload"):
        perf_benchmark.main(["--workload", "nope"])
