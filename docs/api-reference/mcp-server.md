---
search:
  exclude: true
---

# MCP Server API Reference

The **Scrapling MCP Server** provides powerful tools for web scraping through the Model Context Protocol (MCP). This server integrates Scrapling's capabilities directly into AI chatbots and agents, allowing conversational web scraping with advanced anti-bot bypass features, direct image-return workflows, server-side app-state extraction, browser-backed network observation, declarative browser flows for JavaScript-heavy websites, compact page diagnostics for debugging failures, storage-state export, and model-friendly endpoint discovery.

You can start the MCP server by running:

```bash
scrapling mcp
```

Or import the server class directly:

```python
from scrapling.core.ai import ScraplingMCPServer

server = ScraplingMCPServer()
server.serve(http=False, host="0.0.0.0", port=8000)
```

## Response Model

The standardized response structure that's returned by all MCP server tools:

## ::: scrapling.core.ai.ResponseModel
    handler: python
    :docstring:

## Image Candidate Models

These structures are returned by the page-image listing tool:

## ::: scrapling.core.ai.ImageCandidateModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.ImageCandidatesModel
    handler: python
    :docstring:

## App State Models

These structures are returned by the app-state extraction tool:

## ::: scrapling.core.ai.AppStateEntryModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.AppStateResultModel
    handler: python
    :docstring:

## Network Observation Models

These structures are returned by the network observation tool:

## ::: scrapling.core.ai.NetworkEntryModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.NetworkObservationResultModel
    handler: python
    :docstring:

## Browser Flow Models

These structures are returned by the declarative browser-flow extraction tool:

## ::: scrapling.core.ai.FlowActionRecordModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.FlowExtractResultModel
    handler: python
    :docstring:

## Page Debug Models

These structures are returned by the page-debug diagnostic tool:

## ::: scrapling.core.ai.RedirectEntryModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.PageDebugResultModel
    handler: python
    :docstring:

## Storage State Models

These structures are returned by the storage-state export tool:

## ::: scrapling.core.ai.StorageOriginEntryModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.StorageStateResultModel
    handler: python
    :docstring:

## Endpoint Discovery Models

These structures are returned by the endpoint discovery tool:

## ::: scrapling.core.ai.GraphQLOperationModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.DiscoveredEndpointModel
    handler: python
    :docstring:

## ::: scrapling.core.ai.EndpointDiscoveryResultModel
    handler: python
    :docstring:

## MCP Server Class

The main MCP server class that provides all web scraping tools:

## ::: scrapling.core.ai.ScraplingMCPServer
    handler: python
    :docstring:
