## Summary

- add a shared operations layer so CLI and MCP use the same implementation for images, app-state extraction, network capture, browser flows, page diagnostics, storage export, and endpoint discovery
- preserve hybrid outputs where needed, including direct image delivery for `fetch_page_image`
- add repeatable live smoke harnesses for both CLI and MCP, backed by a shared target registry and reusable flow fixtures
- validate parity against public live targets including Books to Scrape, Web Scraper AJAX, TodoMVC, httpbin, Next.js preview, Nuxt starter, and a Cloudflare challenge page

## What Changed

- added shared operation modules under `scrapling/operations/`
- migrated parity features to those shared operations and exposed them through both `scrapling inspect ...` and the MCP server
- added focused operation tests plus MCP and CLI parity coverage
- added `scripts/live_smoke.py` and `scripts/mcp_smoke.py` for executable end-to-end verification
- documented the new parity commands, smoke runners, and MCP transport usage

## Verification

```bash
.venv/bin/python -m pytest tests/operations/test_app_state.py tests/operations/test_network.py tests/operations/test_debug.py -q
.venv/bin/python scripts/live_smoke.py --timeout 300
.venv/bin/python scripts/mcp_smoke.py --transport stdio
.venv/bin/python scripts/mcp_smoke.py --transport http --tests list_tools get
```

## Notes

- the live harness depends on public third-party targets, so the target registry in `tests/live/targets.json` may need periodic updates if those sites drift
- stdio MCP was exercised with the full live matrix; HTTP transport was spot-checked with `list_tools` and `get`
