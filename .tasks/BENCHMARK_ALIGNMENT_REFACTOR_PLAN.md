Benchmark Alignment And Refactor Plan

Context
- PR #3 established the benchmark foundation and has been merged into `main`.
- This follow-up branch exists to realign the implementation with the original benchmark intent:
  - one correctness-gated evaluator
  - one score
  - hard-to-game acceptance semantics
  - usable by humans and external optimization loops

Original intent to preserve
- The benchmark is an evaluator, not an optimizer.
- Faster results only count if real output remains correct.
- Holdout/generalization matters, not only public-suite performance.
- Every score must be auditable from saved artifacts.
- Acceptance semantics should be explicit and consistent across:
  - scoring
  - strict mode
  - baseline writing
  - suite/workload execution

Current alignment summary
- Aligned:
  - `SRPS`, `passed`, and JSON reports exist.
  - correctness-gated scoring exists.
  - public, release, holdout, and browser suites exist.
  - artifact capture, repeated runs, and semantic comparison exist.
- Misaligned:
  - `repetitions=0` is silently coerced to suite defaults.
  - strict-mode acceptance does not match optional `environment_unavailable` scoring semantics.
  - baseline writing still accepts failed workloads too freely.
  - benchmark assets are still repo-local, not clearly product-owned.
  - benchmark acceptance policy is still distributed across multiple layers.

Current branch progress
- Done on this branch:
  - explicit invalid override values are rejected instead of being silently coerced
  - strict mode now treats optional `environment_unavailable` workloads neutrally
  - saved baselines reject non-neutral failed workloads
  - saved baselines omit neutral optional `environment_unavailable` workloads
  - reports now carry explicit `baseline_comparable` state, including holdout summary state
  - partial baselines no longer produce subset-derived `SRPS`; non-comparable runs now leave `srps` empty
  - benchmark assets are now shipped with package builds, not only resolved from a source checkout
  - acceptance-policy classification is now centralized instead of being re-encoded separately across score, strict mode, and baseline writing
- Remaining in the current acceptance/baseline slice:
  - decide whether baseline coverage should be made explicit metadata or inferred solely from comparable entries

Branch goal
- Make the evaluator contract explicit and consistent without weakening the anti-cheating guarantees from the original benchmark spec.

Non-goals
- Do not redesign the benchmark from scratch.
- Do not redesign optimizer loops.
- Do not broaden workload scope before contract fixes are green.
- Do not refactor module layout before contract behavior is pinned by tests.

Execution model
- Follow red-green TDD for every slice.
- Prefer small, acceptance-focused tests over large rewrites.
- Keep user-facing behavior changes explicit in docs and CLI help.

Slice 1: Acceptance semantics unification

Problem
- Scoring, strict mode, and baseline writing do not share one acceptance model.

Red tests first
- Optional `environment_unavailable` workloads are neutral in strict mode when they are neutral in scoring.
- Failed workloads are not accepted into a saved baseline.
- Non-comparable workloads only fail strict mode when they are part of scored acceptance.

Green implementation
- Introduce one internal acceptance-policy layer that answers:
  - is this workload scorable?
  - is this workload baseline-comparable?
  - may this workload be skipped neutrally?
  - may this workload be written into a baseline?
  - does this report satisfy strict mode?
- Make these paths consume the same policy:
  - `_suite_score()`
  - `_suite_stability_penalty()`
  - `baseline_payload()` / `save_baseline()`
  - `_report_is_strict_success()`

Refactor target
- Eliminate duplicated acceptance semantics.

Slice 2: Evaluator input contract cleanup

Problem
- Explicit overrides are still coerced implicitly at the suite boundary.

Red tests first
- `evaluate_suite(..., repetitions=0)` does not silently use suite defaults.
- `--repetitions 0` has matching CLI semantics.
- Negative or invalid warmup/repetition overrides behave consistently across API and CLI.

Green implementation
- Replace truthy/falsy override logic with explicit `is not None` handling.
- Surface invalid override values consistently from suite-level entrypoints.

Refactor target
- Remove silent coercion from the evaluator API.

Slice 3: Baseline hygiene

Problem
- A bad run can still become a weak future baseline.

Red tests first
- Saving a baseline from a failed report is rejected.
- Saving a baseline from a workload with non-positive effective cost is rejected or omitted by policy.
- Optional neutral-skip workloads do not poison baseline comparability.

Green implementation
- Decide and encode one policy:
  - either reject unsafe baseline writes entirely
  - or omit unfit workloads from the baseline with explicit metadata
- Keep comparability rules aligned with Slice 1.

Refactor target
- Make baseline writing an acceptance step, not raw report serialization.

Slice 4: Asset ownership and packaging boundary

Problem
- The evaluator still assumes a source checkout layout.

Red tests first
- Asset discovery works in an install-like layout.
- `evaluate_suite("dev")` works without repo-relative assumptions.
- Schema/suite/workload asset lookups function through a product-owned path.

Green implementation
- Move benchmark asset loading to a package-owned mechanism:
  - package data and/or `importlib.resources`
- Update packaging config so benchmark assets are shipped intentionally.

Refactor target
- Make the evaluator a stable shipped feature, not only repo-local tooling.

Slice 5: Internal module split

Problem
- `scrapling/benchmarking.py` mixes too many responsibilities, which keeps producing boundary regressions.

Precondition
- Slices 1 through 4 must already be green.

Red tests first
- No new behavioral tests needed beyond contract regression coverage from earlier slices.
- Keep a small API-level smoke suite around:
  - `evaluate_suite()`
  - `evaluate_workload()`
  - baseline round-trip
  - strict-mode CLI behavior

Green/refactor implementation
- Split by responsibility:
  - schema/spec loading
  - execution/workers
  - correctness/stability
  - scoring/acceptance
  - baseline/report I/O
- Keep the public API stable.

Refactor target
- Make future contract drift harder to introduce.

Suggested file targets
- `scrapling/benchmarking.py`
- `scripts/perf_benchmark.py`
- `docs/benchmarks.md`
- `pyproject.toml`
- `MANIFEST.in`
- `tests/benchmarks/test_benchmarking.py`
- `tests/cli/test_perf_benchmark.py`
- likely new packaging/asset tests

Recommended execution order
1. Acceptance semantics
2. Evaluator input contract
3. Baseline hygiene
4. Asset ownership / packaging
5. Internal module split
6. Docs cleanup if needed after behavior lands

Definition of done for this branch
- Acceptance semantics are consistent across score, strict mode, and baseline writing.
- Explicit invalid overrides are rejected explicitly.
- Benchmark assets are intentionally owned by the shipped product or explicitly documented as repo-only.
- Existing evaluator behavior remains green under automated tests.
- The result is more aligned with the original benchmark spec than the current merged foundation.
