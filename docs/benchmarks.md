# Performance Benchmarks

Scrapling now has two benchmark tracks:

- `benchmarks.py`: the older comparison-oriented microbenchmark used for the marketing table.
- `scripts/perf_benchmark.py`: the benchmark evaluator used for regression tracking and optimization work.

If the goal is to improve Scrapling without faking wins, use the evaluator.

## Evaluator Model

The evaluator produces:

- `srps`: Scrapling Real-world Performance Score
- `passed`: whether required correctness gates passed
- a JSON report with workload metrics, correctness, stability, and artifact paths
- workload-level failure classification via `failure_kind`

`srps` is defined as:

- `0` if any required workload fails correctness
- otherwise a weighted geometric mean of baseline-relative workload costs, adjusted by stability penalties

This design prevents an optimizer from getting credit for faster runs that return degraded output.

Suite and workload specs are schema-validated when they are loaded. Invalid benchmark definitions fail early as evaluator configuration errors.

Benchmark assets are shipped with the package build. The evaluator can resolve suites, workloads, schemas, fixtures, and expected outputs from an installed wheel, not only from a source checkout.

## Initial Dev Suite

The first deterministic suites contain:

- `static_extract`
- `large_dom_extract`
- `text_similarity`

Available suites:

- `dev`: fast local regression loop
- `release`: broader deterministic suite with heavier default repetition
- `browser`: deterministic browser-backed workloads served from local fixtures
- `browser_holdout`: alternate browser-backed fixtures used to detect overfitting in rendered flows
- `holdout`: alternate fixtures used to penalize overfitting

The release suite currently adds:

- `crawl_extract`: aggregate structured records across multiple paginated fixtures
- `session_flow_extract`: evaluate a small stateful multi-step extraction sequence
- `protected_replay_extract`: validate extraction on a protected-page replay while rejecting challenge markers
- `browser_dynamic_extract`: exercise rendered DOM extraction on a local browser-backed fixture
- `browser_session_extract`: exercise rendered stateful extraction on a local browser-backed fixture

Each workload measures:

- wall-clock time
- CPU time
- per-workload peak RSS
- load time
- extraction time
- output correctness

## Usage

Run the dev suite and write the report:

```bash
python scripts/perf_benchmark.py --suite dev
```

Write JSON to stdout:

```bash
python scripts/perf_benchmark.py --suite dev --json
```

Save a baseline:

```bash
python scripts/perf_benchmark.py --suite dev --save-baseline
```

Run against an existing baseline:

```bash
python scripts/perf_benchmark.py --suite dev --baseline benchmarks/baselines/dev.json
```

Run a public suite plus a holdout suite in one pass:

```bash
python scripts/perf_benchmark.py \
  --suite dev \
  --baseline benchmarks/baselines/dev.json \
  --holdout-suite holdout \
  --holdout-baseline benchmarks/baselines/holdout.json
```

Run only selected workloads:

```bash
python scripts/perf_benchmark.py --suite dev --workload static_extract --workload text_similarity
```

Control report and artifact paths:

```bash
python scripts/perf_benchmark.py \
  --suite dev \
  --output .benchmarks/latest.json \
  --artifacts-dir .benchmarks/artifacts
```

Fail the command if required correctness checks fail or the run is not baseline-comparable:

```bash
python scripts/perf_benchmark.py --suite dev --strict
```

Workload crashes and timeouts are reported as failed workloads in the JSON report. They do not abort the evaluator unless the evaluator itself is misconfigured.

`--strict` is acceptance-oriented. It exits non-zero when required correctness fails, when `srps` cannot be computed, or when any scored workload is missing a comparable baseline entry.

If `--save-baseline` is combined with `--strict`, the baseline is only written when the run satisfies strict acceptance.

If `--save-baseline` is used without `--strict`, baseline rejections are reported to stderr and the evaluator still returns the benchmark report instead of crashing.

If a baseline only covers part of the requested workload set, the evaluator marks the run as not baseline-comparable and leaves `srps` empty instead of emitting a subset-derived score.

## Files

Benchmark assets live under:

```text
benchmarks/
  schema/
  suites/
  workloads/
  fixtures/
  expected/
  baselines/
```

Built-in benchmark assets are also shipped inside the `scrapling` package under `scrapling._benchmark_assets`. In a source checkout, repo-local `benchmarks/` assets take precedence so local benchmark edits are picked up immediately. In install-like environments without the repo asset tree, the evaluator falls back to the packaged assets.

The current implementation uses:

- suite specs from repo-local `benchmarks/suites/` in a checkout, otherwise `scrapling._benchmark_assets/suites/`
- workload specs from repo-local `benchmarks/workloads/` in a checkout, otherwise `scrapling._benchmark_assets/workloads/`
- deterministic HTML fixtures from repo-local `benchmarks/fixtures/...` when present, otherwise the packaged copies
- expected outputs from repo-local `benchmarks/expected/` when present, otherwise the packaged copies

When a holdout suite is provided, the final `srps` is multiplied by a `generalization_penalty`. If the holdout suite fails required correctness gates, the final score is zero.

Saved baselines include workload version and a workload fingerprint. If a workload definition or its fixtures/expected output change, stale baseline entries are ignored instead of being scored as comparable.

Baselines are also schema-validated and suite-validated when loaded. A baseline for the wrong suite or suite version is treated as evaluator misconfiguration and rejected early.

Optional workloads marked `environment_unavailable` are omitted from saved baselines instead of poisoning comparability for environments that do not have those optional dependencies.

## Interpreting Results

Use the single score for acceptance decisions.

Use the workload breakdown to diagnose why the score changed:

- `effective_cost`: weighted cost used for scoring
- `wall_ms`: end-to-end elapsed time
- `load_ms`: selector construction / load stage
- `extract_ms`: extraction stage
- `correctness`: output fidelity
- `stability`: run-to-run timing and output consistency
- `metrics_trace`: per-repetition timing, correctness, and normalized-output hashes for audit
- `failure_kind`: `null`, `correctness`, `timeout`, `worker_error`, `worker_exit`, `worker_protocol_error`, or `environment_unavailable`

`baseline_comparable` is reported at the top-level `summary` (and optional `summary.holdout`), not per workload.

If `passed` is false, the score is intentionally zero. That is not a benchmark failure. It is the evaluator refusing to reward a functional regression.

Optional workloads marked `environment_unavailable` are treated neutrally in suite scoring and strict-mode comparability. Required workloads marked that way still fail the suite.
