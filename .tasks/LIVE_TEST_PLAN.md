Scrapling live verification and end-to-end test plan

Deployment note
- The `scrapling-vision` endpoint should be a direct deployment of core Scrapling MCP from the forked repo.
- Live MCP tests against `scrapling-vision` validate the built-in `list_page_images` and `fetch_page_image` tools, not a separate bridge implementation.

Date baseline
- Target verification was performed on March 21, 2026.
- Verification used both `curl` and `agent-browser`.
- Purpose: confirm that the targets are live, suitable, and correctly categorized before running Scrapling CLI/MCP live tests.

Verified target matrix

1. Static positive-path target
- URL: `https://books.toscrape.com/`
- curl result:
  - `200 OK`
- browser result:
  - final URL stayed at `https://books.toscrape.com/`
  - title was `All products | Books to Scrape - Sandbox`
  - page rendered full catalog and pagination links
- use for:
  - `get`
  - `extract get`
  - `list_page_images`
  - `fetch_page_image`
  - content extraction baselines

2. JS-heavy positive-path target
- URL: `https://webscraper.io/test-sites/e-commerce/ajax`
- curl result:
  - `200 OK`
- browser result:
  - final URL stayed at `https://webscraper.io/test-sites/e-commerce/ajax`
  - title was `Ajax | Web Scraper Test Sites`
  - page rendered product content and a cookie consent button
- use for:
  - `fetch`
  - `stealthy_fetch`
  - `debug_page`
  - `observe_network`
  - `discover_endpoints`

3. SPA positive-path target
- URL: `https://demo.playwright.dev/todomvc/`
- curl result:
  - `200 OK`
- browser result:
  - final URL became `https://demo.playwright.dev/todomvc/#/`
  - title was `React • TodoMVC`
  - page rendered interactive TodoMVC UI
- use for:
  - `run_flow_and_extract`
  - `export_storage_state`
  - browser-flow action tests
  - SPA navigation/state assertions

4. HTTP/service baseline target
- URL: `https://httpbin.org/`
- curl result:
  - `/get` returned valid JSON
- browser result:
  - final URL stayed at `https://httpbin.org/`
  - title was `httpbin.org`
  - page rendered interactive docs and endpoint categories
- use for:
  - redirect tests
  - cookie tests
  - storage-state tests
  - HTTP mechanics sanity checks

5. Challenge-path negative target
- URL: `https://nopecha.com/demo/cloudflare`
- curl result:
  - `403`
  - Cloudflare challenge headers were present, including `cf-mitigated: challenge`
- browser result:
  - final URL stayed at `https://nopecha.com/demo/cloudflare`
  - title was `Just a moment...`
  - page rendered a Cloudflare challenge iframe and verification UI
- use for:
  - `debug_page`
  - challenge detection assertions
  - failure-path validation

6. API-only target
- URL: `https://countries.trevorblades.com/`
- curl result:
  - GraphQL POST returned valid data
- browser result:
  - navigation failed with `net::ERR_ABORTED`
- classification:
  - valid service/API target
  - not a reliable browser-navigation target
- use for:
  - API-only baselines
  - GraphQL request verification outside page-navigation success tests

7. Browser-negative target
- URL: `https://demo.playwright.dev/movies/`
- curl result:
  - `200 OK`
- browser result:
  - final URL became `https://demo.playwright.dev/movies/error`
  - title was `Oooops!`
  - rendered client-side error state
- classification:
  - useful for negative-path browser diagnostics
  - not a primary success-path target

Recommended live target set
- Static extraction and image tests:
  - `https://books.toscrape.com/`
- JS-heavy page tests:
  - `https://webscraper.io/test-sites/e-commerce/ajax`
- SPA flow tests:
  - `https://demo.playwright.dev/todomvc/`
- HTTP mechanics and cookie/storage tests:
  - `https://httpbin.org/`
- Challenge and failure-path tests:
  - `https://nopecha.com/demo/cloudflare`
- API-only GraphQL control:
  - `https://countries.trevorblades.com/`

Live Scrapling CLI test plan

Preconditions
- Install the project in editable mode so the `scrapling` console script is available.
- Suggested command:
  - `.venv/bin/python -m pip install -e .`
- If shell extras are needed:
  - `.venv/bin/python -m pip install -e ".[shell]"`

Test 1: Static extraction baseline
- target: `https://books.toscrape.com/`
- commands:
  - `scrapling extract get 'https://books.toscrape.com/' books.md`
  - `scrapling inspect list-page-images 'https://books.toscrape.com/' --format json`
- assertions:
  - extracted content contains `A Light in the Attic`
  - image candidate list is non-empty

Test 2: Image artifact retrieval
- target: `https://books.toscrape.com/`
- commands:
  - `scrapling inspect fetch-page-image 'https://books.toscrape.com/' cover.jpg --metadata-format json`
- assertions:
  - output file exists
  - metadata contains MIME type and resolved image URL
  - image file is non-empty

Test 3: SPA flow execution
- target: `https://demo.playwright.dev/todomvc/`
- actions file:
  - click or focus the todo input if needed
  - fill the new todo textbox with a unique string
  - press Enter
- command:
  - `scrapling inspect run-flow-and-extract 'https://demo.playwright.dev/todomvc/' --actions-file actions/todomvc-add.json --format json`
- assertions:
  - final URL contains `#/`
  - extracted content contains the inserted todo item
  - no action failed

Test 4: Flow plus network in one session
- target: `https://demo.playwright.dev/todomvc/`
- command:
  - `scrapling inspect run-flow-and-extract 'https://demo.playwright.dev/todomvc/' --actions-file actions/todomvc-add.json --observe-network --format json`
- assertions:
  - command completes successfully
  - output includes `network`
  - output includes `actions`
- note:
  - this target may produce limited useful network traffic because the app is largely local-state driven
  - this is still a valid persistence/combined-session test

Test 5: JS-heavy diagnostics
- target: `https://webscraper.io/test-sites/e-commerce/ajax`
- command:
  - `scrapling inspect debug-page 'https://webscraper.io/test-sites/e-commerce/ajax' --format json`
- assertions:
  - title contains `Ajax | Web Scraper Test Sites`
  - final URL is stable
  - page errors are empty or low-noise

Test 6: Network observation on JS-heavy page
- target: `https://webscraper.io/test-sites/e-commerce/ajax`
- command:
  - `scrapling inspect observe-network 'https://webscraper.io/test-sites/e-commerce/ajax' --include-bodies --format json`
- assertions:
  - command completes successfully
  - count is non-negative
  - if requests are captured, entries contain URL, method, stage, and status
- note:
  - this target should be kept only if live observation shows meaningful requests through Scrapling
  - if it proves too quiet, replace it with a stronger AJAX target before finalizing smoke tests

Test 7: Endpoint discovery
- target: `https://webscraper.io/test-sites/e-commerce/ajax`
- command:
  - `scrapling inspect discover-endpoints 'https://webscraper.io/test-sites/e-commerce/ajax' --format json`
- assertions:
  - command completes successfully
  - output contains `endpoints`
  - if any API-like traffic is found, endpoint kinds include `api` or `graphql`

Test 8: Storage-state export
- target: `https://httpbin.org/cookies/set?smoke=1`
- command:
  - `scrapling inspect export-storage-state 'https://httpbin.org/cookies/set?smoke=1' --format json`
- assertions:
  - returned cookies include `smoke=1`
  - final URL reflects redirect completion

Test 9: Challenge diagnostics
- target: `https://nopecha.com/demo/cloudflare`
- command:
  - `scrapling inspect debug-page 'https://nopecha.com/demo/cloudflare' --format json`
- assertions:
  - command completes without crashing
  - title indicates challenge state or challenge detection is non-null
  - debug output clearly signals failure-path conditions

Test 10: API-only control
- target: `https://countries.trevorblades.com/`
- command:
  - control with `curl`, not browser-page navigation
  - `curl -sS https://countries.trevorblades.com/ -H 'content-type: application/json' --data '{"query":"{ countries { code name } }"}'`
- assertions:
  - valid JSON response
  - confirms GraphQL endpoint is live
- note:
  - do not treat this as a browser-navigation success test unless live browser behavior changes

Live MCP test plan

Transport setup
- stdio:
  - `scrapling mcp`
- or HTTP:
  - `scrapling mcp --http --host 127.0.0.1 --port 8000`

MCP smoke matrix
- `get`
  - target: `books.toscrape.com`
  - assert extracted content contains known book title
- `list_page_images`
  - target: `books.toscrape.com`
  - assert non-empty image candidates
- `fetch_page_image`
  - target: `books.toscrape.com`
  - assert artifact is returned with structured metadata
- `run_flow_and_extract`
  - target: TodoMVC
  - assert inserted todo appears in content
- `run_flow_and_extract` with `observe_network=true`
  - target: TodoMVC
  - assert combined result contains both `actions` and `network`
- `debug_page`
  - targets:
    - Web Scraper AJAX
    - NopeCHA challenge
  - assert diagnostic summary is coherent in both positive and failure paths
- `export_storage_state`
  - target: `httpbin.org/cookies/set?smoke=1`
  - assert returned cookies include `smoke=1`
- `discover_endpoints`
  - target: Web Scraper AJAX or replacement AJAX page
  - assert unique endpoint inventory is returned

Pass/fail standard
- A test passes only if:
  - the command/tool invocation succeeds
  - the returned shape matches the expected parity model
  - the semantic assertion for the target is true
- A target should be removed or reclassified if:
  - `curl` and browser behavior diverge in a way that breaks the intended use case
  - the live site becomes unstable
  - the target no longer represents the behavior class it was chosen for

Known gaps
- A stronger public browser-page target with reliable fetch/XHR activity may still be needed for final `observe_network` and `discover_endpoints` smoke coverage if the Web Scraper AJAX page proves too quiet under Scrapling live runs.

Recommended next action
- Convert this plan into:
  - a repeatable `live-smoke.sh` CLI runner
  - a matching MCP smoke harness
  - a small target registry file so the URLs and expectations can be updated without rewriting the tests
