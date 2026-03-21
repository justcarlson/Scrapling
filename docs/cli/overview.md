# Command Line Interface

Since v0.3, Scrapling includes a powerful command-line interface that provides four main capabilities:

1. **Interactive Shell**: An interactive Web Scraping shell based on IPython that provides many shortcuts and useful tools
2. **Extract Commands**: Scrape websites from the terminal without any programming
3. **Inspect Commands**: Inspect page-derived assets and structured application state directly from the terminal
4. **Utility Commands**: Installation and management tools

```bash
# Launch interactive shell
scrapling shell

# Convert the content of a page to markdown and save it to a file
scrapling extract get "https://example.com" content.md

# List page image candidates as JSON
scrapling inspect list-page-images "https://example.com/article"

# Observe browser-side network activity as markdown
scrapling inspect observe-network "https://example.com/app" --format markdown

# Run a declarative browser flow from JSON and extract the final page content
scrapling inspect run-flow-and-extract "https://example.com/app" --actions-file actions.json --format json

# Run the same flow and capture the API traffic it triggers in the same browser session
scrapling inspect run-flow-and-extract "https://example.com/app" --actions-file actions.json --observe-network --include-bodies --format json

# Get a compact diagnostic summary for a JS-heavy page load
scrapling inspect debug-page "https://example.com/app" --format markdown

# Export cookies plus localStorage/sessionStorage in a structured snapshot
scrapling inspect export-storage-state "https://example.com/app" --format json

# Discover likely API, GraphQL, and WebSocket endpoints from browser traffic
scrapling inspect discover-endpoints "https://example.com/app" --actions-file actions.json --format markdown

# Get help for any command
scrapling --help
scrapling extract --help
scrapling inspect --help
```

## Live Smoke Runners

The repository includes repeatable live smoke harnesses for the parity features. They use the shared target registry in `tests/live/targets.json` and the TodoMVC flow fixture in `tests/live/actions/todomvc-add.json`.

```bash
# Run the full CLI live smoke suite
.venv/bin/python scripts/live_smoke.py --timeout 300

# Run only the app-state coverage targets
.venv/bin/python scripts/live_smoke.py --tests extract_app_state_next extract_app_state_nuxt

# Keep artifacts from the run for inspection
.venv/bin/python scripts/live_smoke.py --keep-output --output-dir /tmp/scrapling-live
```

The shell wrapper below is equivalent to the main Python entrypoint:

```bash
scripts/live-smoke.sh --timeout 300
```

## Requirements
This section requires you to install the extra `shell` dependency group, like the following:
```bash
pip install "scrapling[shell]"
```
and the installation of the fetchers' dependencies with the following command
```bash
scrapling install
```
This downloads all browsers, along with their system dependencies and fingerprint manipulation dependencies.
