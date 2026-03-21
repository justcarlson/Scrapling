PR prep notes

Current branch is large enough that the review will be easier if it is split into commit-sized chunks before opening the PR.

Recommended commit split

1. Shared operations and parity wiring
- `scrapling/operations/*`
- `scrapling/core/ai.py`
- `scrapling/cli.py`
- Goal: introduce the shared operations layer and MCP/CLI parity for images, app state, network, flow, debug, storage state, and endpoint discovery.

2. Parity test coverage
- `tests/operations/*`
- `tests/ai/test_ai_mcp.py`
- `tests/cli/test_cli.py`
- Goal: lock the shared behavior and both surfaces down before live-target validation.

3. Live smoke harnesses
- `scripts/live_smoke.py`
- `scripts/live-smoke.sh`
- `scripts/mcp_smoke.py`
- `tests/live/targets.json`
- `tests/live/actions/todomvc-add.json`
- Goal: executable live validation for CLI and MCP against public targets.

4. Documentation
- `README.md`
- `docs/cli/overview.md`
- `docs/ai/mcp-server.md`
- `docs/api-reference/mcp-server.md`
- Goal: explain parity commands, smoke runners, and MCP usage clearly.

5. Planning artifacts
- `.tasks/SPEC.md`
- `.tasks/LIVE_TEST_PLAN.md`
- `.tasks/PR_PREP.md`
- Goal: keep planning/history separate from user-facing code/docs if desired.

Suggested review order

1. Shared operations plus CLI/MCP parity
2. Tests
3. Live harnesses
4. Docs
5. Task notes

Suggested PR summary points

- Adds a shared operations layer so CLI and MCP use the same implementation for page images, app-state extraction, network capture, browser flows, page diagnostics, storage export, and endpoint discovery.
- Preserves hybrid outputs where needed, including direct image delivery for `fetch_page_image`.
- Adds repeatable live smoke harnesses for both CLI and MCP, backed by a shared target registry.
- Verifies parity against public live targets including Books to Scrape, Web Scraper AJAX, TodoMVC, httpbin, Next.js preview, Nuxt starter, and a Cloudflare challenge page.

Open caveat to mention in the PR

- The live harness depends on third-party public targets. The target registry can be updated without changing the smoke runner logic when those sites drift.
