Scrapling benchmark evaluator implementation plan

Goal
- Build the benchmark evaluator described in `.tasks/BENCHMARK_SPEC.md`.
- Deliver one measurable, correctness-gated score that can be consumed by humans or external optimization loops.

Constraints
- Keep the benchmark separate from optimizer logic.
- Favor deterministic fixtures first, then add slower real-world workloads.
- Avoid replacing the legacy `benchmarks.py` marketing comparison until the new evaluator is stable.

Deliverables
- Benchmark directory layout under `benchmarks/`
- Typed evaluator implementation in Scrapling
- CLI entrypoint with suite support and JSON reports
- Baseline save/load v2
- Correctness-gated workload execution
- Dev-suite workloads
- Tests for schema, metric math, gating, and CLI behavior
- Docs for usage and report interpretation

Phase 0: foundations
- Create benchmark directory structure:
  - `benchmarks/schema/`
  - `benchmarks/suites/`
  - `benchmarks/workloads/`
  - `benchmarks/fixtures/`
  - `benchmarks/expected/`
  - `benchmarks/baselines/`
- Define benchmark report schema
- Define suite schema
- Define workload schema
- Decide report versioning rules

Phase 1: evaluator core
- Refactor `scrapling/benchmarking.py` into evaluator-oriented models and functions
- Add typed models for:
  - suite spec
  - workload spec
  - workload report
  - benchmark report
  - correctness summary
  - stability summary
- Add core API:
  - `evaluate_suite(...)`
  - `evaluate_workload(...)`
- Implement baseline v2:
  - save
  - load
  - schema-version validation

Phase 2: metrics and scoring
- Implement raw metric collection:
  - wall-clock timing
  - CPU timing
  - peak RSS measurement
  - load time
  - extract time
- Implement workload `EffectiveCost`
- Implement `SRPS` aggregation
- Implement `StabilityPenalty`
- Keep `GeneralizationPenalty` plumbed even if initial holdout suite is minimal

Phase 3: correctness gates
- Implement common gate checks:
  - fetch succeeded
  - ready condition met
  - extraction succeeded
  - required fields present
  - item count within tolerance
  - exact normalized match or semantic threshold met
- Define normalized output comparison helpers
- Add artifact generation:
  - raw output
  - normalized output
  - diff

Phase 4: first usable dev suite
- Implement the first three deterministic workloads:
  - `static_extract`
  - `large_dom_extract`
  - `text_similarity`
- Add fixture files and expected outputs
- Add `benchmarks/suites/dev.json`
- Add baseline file generation flow for the dev suite

Phase 5: CLI and report UX
- Extend `scripts/perf_benchmark.py` to support:
  - `--suite`
  - `--baseline`
  - `--output`
  - `--artifacts-dir`
  - `--repetitions`
  - `--seed`
  - `--strict`
  - `--json`
- Print:
  - top-level `SRPS`
  - pass/fail
  - workload breakdown
  - artifact paths where relevant

Phase 6: tests
- Add benchmark-focused tests under:
  - `tests/benchmarks/`
- Cover:
  - metric math
  - baseline round-trip
  - schema-version rejection
  - correctness gate failures zero the score
  - report serialization
  - CLI argument handling
  - deterministic CLI output with mocked evaluator results
- Keep timing assertions structural, not absolute

Phase 7: docs
- Update `docs/benchmarks.md`
- Explain:
  - what `SRPS` means
  - why correctness gates can zero the score
  - how public vs holdout suites differ
  - how to capture and compare baselines

Phase 8: expansion after core is stable
- Add browser-backed workloads:
  - `dynamic_load_extract`
  - `session_flow_extract`
- Add higher-friction workload:
  - `protected_fetch_extract`
- Add crawl workload:
  - `multi_page_crawl`
- Add `release` and `holdout` suites

Recommended file map
- `scrapling/benchmarking.py`
- `scripts/perf_benchmark.py`
- `benchmarks/schema/report.schema.json`
- `benchmarks/schema/suite.schema.json`
- `benchmarks/schema/workload.schema.json`
- `benchmarks/suites/dev.json`
- `benchmarks/workloads/*.json`
- `benchmarks/fixtures/...`
- `benchmarks/expected/...`
- `tests/benchmarks/test_metric_math.py`
- `tests/benchmarks/test_correctness_gates.py`
- `tests/benchmarks/test_baseline_roundtrip.py`
- `tests/cli/test_perf_benchmark.py`

Execution order
1. Add schemas and typed report models.
2. Implement evaluator API and baseline v2.
3. Implement metric collection and scoring.
4. Implement correctness gates and artifact capture.
5. Land deterministic workloads and dev suite.
6. Add CLI support and docs.
7. Add dynamic, protected, release, and holdout workloads.

Acceptance criteria for the first milestone
- A single command can run the dev suite and emit one JSON report.
- The report includes `srps` (or `null` when not baseline-comparable), `passed`, workload metrics, correctness, and artifacts.
- Required correctness failures force `srps = 0`.
- Baselines can be saved and loaded with version checks.
- The first three workloads are deterministic and covered by automated tests.

Risks
- Dynamic and protected targets will introduce noise if added too early.
- Overly strict exact matching may reject legitimate improvements on noisy workloads.
- A single scalar score can hide diagnosis unless workload breakdown remains visible.

Risk handling
- Start with deterministic workloads first.
- Separate exact and semantic comparison modes.
- Always emit workload-level breakdown alongside the scalar score.

Definition of done
- Benchmark evaluator exists as a stable repo feature.
- It is suitable as a black-box acceptance function for external optimization loops.
- It refuses to reward performance gains that break or degrade real output.
