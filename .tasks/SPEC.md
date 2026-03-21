Scrapling JS-heavy MCP/CLI feature track

Branch / PR workflow
- This work should happen on a new branch.
- Changes should be collected into a new PR when the work is done.
- The PR will be reviewed and merged by the repo owner.

Design baseline
- Treat this as a branch-scoped feature track with PR-ready delivery, not incremental merges into the current line.
- One shared operation per capability.
- One canonical internal result model per capability.
- The caller chooses how the data is structured and returned.

Output modes
- structured: normalized JSON
- text: compact plain-text summary
- markdown: human-readable report
- artifact: returned file payload where applicable
- hybrid: structured metadata plus artifact

Parity rule
- Every capability is implemented once in shared operations.
- MCP and CLI both expose it.
- No MCP-only or CLI-only logic.
- Existing image tools are migrated into the same model.

Core rule
- The operation determines what data can be produced.
- The user chooses how it wants the data to be structured.

Recommended internal layout
- scrapling/operations/models.py
- scrapling/operations/images.py
- scrapling/operations/browser_flow.py
- scrapling/operations/network.py
- scrapling/operations/app_state.py
- scrapling/operations/debug.py
- scrapling/renderers/mcp.py
- scrapling/renderers/cli.py

Result model pattern
- Each operation should return:
  - kind
  - data
  - artifacts
  - diagnostics
  - render_options_supported

Image tool rule
- list_page_images is a shared operation returning structured image metadata.
- fetch_page_image is a shared operation returning:
  - candidate metadata
  - resolved URL
  - MIME type
  - bytes payload
  - fetch diagnostics
- MCP maps that to structuredContent plus ImageContent.
- CLI maps that to JSON/stdout plus saved image file.
- The user should be able to request:
  - metadata only
  - image only
  - metadata plus image

Remote-processing rule
- Scrapling should do retrieval and processing server-side.
- Client-side models should not depend on local code execution, interpreters, shell tooling, or decode helpers.
- Most new JS-heavy capabilities should return text/JSON.
- fetch_page_image is an explicit exception because the desired end product can be the image itself.

First features to implement under this pattern
1. list_page_images
2. fetch_page_image
3. extract_app_state
4. run_flow_and_extract
5. observe_network
6. debug_page

Implementation standard
- Build capabilities once in a shared application layer, then expose them twice.
- No drift between MCP and CLI.
- Existing image-style derived logic should be moved into this pattern before expanding further.

Testing rule
- For each capability, test:
  - the shared operation directly
  - MCP rendering
  - CLI rendering
  - normalized parity between MCP and CLI outputs

End state for the PR
- shared operation layer
- migrated image tools
- first JS-heavy parity features
- parity tests
- docs updates
