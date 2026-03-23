Scrapling benchmark evaluator spec

Objective
- Define one benchmark system that a human or an external autoresearch loop can call to measure real-world Scrapling performance.
- The benchmark is an evaluator, not an optimizer or loop controller.
- It must make cheating difficult by requiring correctness, generalization, and auditability in addition to speed.

Non-goals
- Do not design the autoresearch loop itself.
- Do not assume any specific optimizer, scheduler, or branching workflow.
- Do not optimize only for synthetic parser microbenchmarks.

Primary output
- One scalar metric when baseline-comparable: `SRPS` (Scrapling Real-world Performance Score)
- One boolean gate: `passed`
- One structured JSON report with raw evidence

Headline metric
- `SRPS = 0` if any required correctness gate fails.
- Otherwise:
  - `SRPS = 100 * GeneralizationPenalty * StabilityPenalty * exp(sum(w_i * ln(B_i / EffectiveCost_i)))`

Definitions
- `w_i`: workload weight
- `B_i`: baseline effective cost for workload `i`
- `EffectiveCost_i`: weighted composite cost for workload `i`
- `GeneralizationPenalty`: penalty applied when holdout behavior is weaker than public-suite behavior
- `StabilityPenalty`: penalty applied for high variance, retries, crashes, or flaky outputs

Interpretation
- `100` means performance matches the baseline.
- `>100` means performance improved relative to the baseline.
- `<100` means performance regressed relative to the baseline.
- `0` means the run is invalid for performance comparison because required functionality regressed.
- `null` means the run was not baseline-comparable, so no score was emitted.

Workload cost model
- Each workload produces:
  - `wall_ms`
  - `cpu_ms`
  - `peak_rss_mb`
  - `load_ms`
  - `extract_ms`
  - `work_units`
  - `correctness`
  - `stability`
- Each workload defines its own `cost_weights`.
- `EffectiveCost_i = a*wall_ms + b*cpu_ms + c*peak_rss_mb + d*load_ms + e*extract_ms`

Core benchmark principles
- The benchmark must measure useful work, not only raw speed.
- Faster results are only credited if the extracted output remains correct.
- Public workloads must not be the only acceptance criterion.
- Every score must be explainable from stored artifacts.

Anti-cheating rules
- Hard correctness gates:
  - any required workload failure forces `SRPS = 0`
- Holdout support:
  - public suites are visible to developers
  - holdout suites exist to detect overfitting
- Multi-stage validation:
  - fetch
  - ready-state reached
  - extraction completed
  - output matched expectations
- Artifact capture:
  - raw output
  - normalized output
  - diff versus expected
  - metric traces
- Repeated trials:
  - use repeated runs and variance-aware penalties
- No partial-success scoring:
  - empty or degraded outputs must not receive a positive performance score

Evaluator contract
- Input:
  - current checkout
  - suite selection
  - baseline path
  - optional output path
  - optional artifacts path
  - optional seed and repetition overrides
- Output:
  - one JSON report
  - one scalar `srps`, or `null` when the requested run is not baseline-comparable
  - one boolean `passed`
- Exit semantics:
  - process exit code indicates evaluator execution success or failure
  - benchmark regressions are reported in JSON, not by crashing the process

CLI contract
- Canonical entrypoint:
  - `python scripts/perf_benchmark.py --suite dev --baseline benchmarks/baselines/dev.json --output .benchmarks/latest.json`
- Minimum options:
  - `--suite`
  - `--baseline`
  - `--output`
  - `--artifacts-dir`
  - `--repetitions`
  - `--seed`
  - `--json`
  - `--strict`

Python API contract
- Provide one stable suite-level function:
  - `evaluate_suite(...) -> BenchmarkReport`
- Provide one stable workload-level function:
  - `evaluate_workload(...) -> WorkloadReport`
- Keep report models typed and serializable.

Benchmark suites
- `dev`
  - fast and deterministic
  - intended for local iteration
- `release`
  - broader and slower
  - intended for final evaluation and regression review
- `holdout`
  - not the primary development target
  - intended to detect overfitting to the visible suite

Initial workload categories
- `static_extract`
  - static HTML extraction with structured fields
- `large_dom_extract`
  - large DOM parse and repeated extraction
- `text_similarity`
  - text-search and similar-node behavior
- `dynamic_load_extract`
  - browser-backed page load and extraction
- `protected_fetch_extract`
  - protected/challenge-path fetch or replay-backed equivalent
- `multi_page_crawl`
  - crawl/pagination and item aggregation
- `session_flow_extract`
  - stateful flow using cookies or storage state

Per-workload specification
- Each workload must declare:
  - `id`
  - `version`
  - `kind`
  - fixture path or replay source
  - expected output path
  - readiness condition
  - extraction spec
  - correctness thresholds
  - cost weights
  - required/optional status at suite level

Correctness gates
- A workload fails if any required check fails:
  - fetch failure
  - timeout
  - page never reaches ready condition
  - extraction exception
  - empty extraction when expected output is non-empty
  - required fields missing
  - item-count mismatch outside allowed tolerance
  - exact normalized output mismatch where exact match is required
  - semantic match below threshold where fuzzy comparison is allowed
- Any required workload failure sets:
  - `passed = false`
  - `srps = 0`

Correctness model
- Support both:
  - exact normalized comparisons
  - semantic comparisons for noisy or dynamic outputs
- At minimum record:
  - `item_count`
  - `required_fields_match`
  - `semantic_match`
  - `non_empty`
  - `success`

Stability model
- Use repeated runs to compute:
  - `mean`
  - `median`
  - `p95`
  - coefficient of variation
- Penalize:
  - high variance
  - retries
  - intermittent failures

Environment rules
- Capture environment metadata in every report:
  - Scrapling version
  - Python version
  - platform
  - CPU information if available
  - run timestamp
- Scores are only comparable across materially similar environments unless explicitly normalized.

Artifacts and auditability
- Each workload report must be able to point to:
  - raw output artifact
  - normalized output artifact
  - diff artifact
  - benchmark metadata
- The final report must retain enough information to explain why a score changed.

Schema and layout
- Introduce a benchmark-owned directory layout:
  - `benchmarks/schema/`
  - `benchmarks/suites/`
  - `benchmarks/workloads/`
  - `benchmarks/fixtures/`
  - `benchmarks/expected/`
  - `benchmarks/baselines/`

Acceptance semantics for external optimizers
- External loops should treat the benchmark as a black-box evaluator.
- Candidate changes should only be accepted if:
  - `passed == true`
  - `srps` improves beyond noise threshold
- Optionally enforce per-workload guardrails on top of the single score.

Initial implementation slice
- Phase 1 should include:
  - typed benchmark report model
  - suite and workload specs
  - baseline v2 format
  - correctness gates
  - `static_extract`
  - `large_dom_extract`
  - `text_similarity`
- Dynamic and protected workloads can land after the evaluator contract is stable.

Success criteria
- The benchmark can produce one stable scalar score.
- The score drops to zero on real output regressions.
- Benchmark output is structured enough for automated acceptance decisions.
- The benchmark can distinguish public-suite optimization from holdout generalization.
- Human reviewers can inspect artifacts and understand score changes.
