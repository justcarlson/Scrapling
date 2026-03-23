#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scrapling.benchmarking import (
    _report_is_strict_success,
    evaluate_suite,
    list_suite_names,
    list_workload_names,
    save_baseline,
)


DEFAULT_OUTPUT_PATH = Path(".benchmarks/latest.json")
DEFAULT_ARTIFACTS_DIR = Path(".benchmarks/artifacts")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Scrapling's benchmark evaluator."
    )
    parser.add_argument(
        "--suite",
        default="dev",
        help="Benchmark suite name or path. Default: dev.",
    )
    parser.add_argument(
        "--workload",
        "--scenario",
        action="append",
        dest="workloads",
        help="Benchmark workload to run. Repeat to select multiple workloads.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        help="Number of measured repetitions per workload.",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        help="Warm-up repetitions per workload.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional seed recorded in the benchmark report.",
    )
    parser.add_argument(
        "--baseline",
        help="Baseline JSON path. Default: benchmarks/baselines/<suite>.json",
    )
    parser.add_argument(
        "--holdout-suite",
        help="Optional holdout suite name or path.",
    )
    parser.add_argument(
        "--holdout-baseline",
        help="Holdout baseline JSON path. Default: benchmarks/baselines/<holdout-suite>.json",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Report output path. Default: .benchmarks/latest.json",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(DEFAULT_ARTIFACTS_DIR),
        help="Artifacts directory. Default: .benchmarks/artifacts",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Write the current report to the baseline path after the run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the benchmark report as JSON.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Return a non-zero exit code when required correctness gates fail "
            "or the run is not baseline-comparable."
        ),
    )
    parser.add_argument(
        "--list-suites",
        action="store_true",
        help="List available suites and exit.",
    )
    parser.add_argument(
        "--list-workloads",
        "--list-scenarios",
        action="store_true",
        help="List available workloads and exit.",
    )
    return parser


def _print_human_report(report: dict[str, object]) -> None:
    environment = report["environment"]
    print("Scrapling Benchmark Evaluator")
    print(
        f"Suite: {report['suite']} | "
        f"Passed: {report['passed']} | "
        f"SRPS: {report['srps'] if report['srps'] is not None else 'N/A'}"
    )
    print(
        f"Environment: Scrapling {environment['scrapling_version']} | "
        f"Python {environment['python_version']} | {environment['platform']}"
    )
    print("")
    print(
        f"{'Workload':<20} {'passed':>8} {'eff cost':>10} {'wall ms':>10} {'load ms':>10} {'extract ms':>12} {'score':>10}"
    )
    print("-" * 90)
    for workload in report["workloads"]:
        score = "-" if workload["score"] is None else f"{workload['score']:.2f}"
        print(
            f"{workload['id']:<20} "
            f"{str(workload['passed']):>8} "
            f"{workload['effective_cost']:>10.4f} "
            f"{workload['metrics']['wall_ms']:>10.4f} "
            f"{workload['metrics']['load_ms']:>10.4f} "
            f"{workload['metrics']['extract_ms']:>12.4f} "
            f"{score:>10}"
        )

def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_suites:
        for suite_name in list_suite_names():
            print(suite_name)
        return 0

    if args.list_workloads:
        for workload_name in list_workload_names():
            print(workload_name)
        return 0

    baseline_path = args.baseline or f"benchmarks/baselines/{Path(args.suite).stem}.json"
    holdout_baseline_path = None
    if args.holdout_suite:
        holdout_baseline_path = args.holdout_baseline or (
            f"benchmarks/baselines/{Path(args.holdout_suite).stem}.json"
        )

    report = evaluate_suite(
        suite_name_or_path=args.suite,
        baseline_path=baseline_path,
        output_path=args.output,
        artifacts_dir=args.artifacts_dir,
        repetitions=args.repetitions,
        warmups=args.warmups,
        seed=args.seed,
        workload_filter=args.workloads,
        holdout_suite_name_or_path=args.holdout_suite,
        holdout_baseline_path=holdout_baseline_path,
    )

    strict_success = _report_is_strict_success(report)

    baseline_saved = False
    if args.save_baseline and (not args.strict or strict_success):
        save_baseline(baseline_path, report)
        baseline_saved = True

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human_report(report)
        print(f"\nReport written to {args.output}")
        if baseline_saved:
            print(f"Baseline saved to {baseline_path}")

    if args.strict and not strict_success:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
